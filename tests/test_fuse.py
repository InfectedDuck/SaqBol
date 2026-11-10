"""T113 — fusion, combination bonuses and abstention.

The abstention behaviour is the part worth testing hardest. It is the mechanism
that turns a silent wrong answer into an admitted uncertainty, and it is what
the risk-coverage curve in the evaluation measures.
"""

from __future__ import annotations

import pytest

import saqbol.core.indicators  # noqa: F401  — registers the rules
from saqbol.core.extract import extract
from saqbol.core.fuse import (
    COMBINATIONS,
    DEFAULT_THRESHOLDS,
    FusionWeights,
    Thresholds,
    assert_spans_match,
    band_for,
    collect_evidence,
    combination_bonuses,
    fuse,
    rule_norm,
    rule_score,
    should_sample_self_consistency,
)
from saqbol.core.indicators.registry import build_context, run_all
from saqbol.core.normalize import normalize
from saqbol.core.types import (
    Band,
    EvidenceSpan,
    IndicatorHit,
    LLMJudgement,
    Severity,
    Stage,
)


def hit(indicator_id: str, severity: Severity = Severity.HIGH, spans=None) -> IndicatorHit:
    return IndicatorHit(indicator_id=indicator_id, severity=severity, spans=spans or [])


def analysed(text: str, metadata: dict | None = None):
    norm = normalize(text)
    ctx = build_context(norm, extract(norm.text), metadata=metadata or {})
    return norm, run_all(ctx)


class TestCombinationBonuses:
    def test_authority_plus_credentials(self):
        fired = combination_bonuses([hit("C1.bank_security"), hit("A1.otp_request")])
        assert ("authority_plus_credentials", 20) in fired

    def test_needs_both_halves(self):
        assert combination_bonuses([hit("C1.bank_security")]) == []
        assert combination_bonuses([hit("A1.otp_request")]) == []

    def test_exact_id_token_is_respected(self):
        """E1 specifically, not the whole E family: a crypto address under
        pressure is not the safe-account script."""
        assert combination_bonuses([hit("E1.safe_account"), hit("B1.urgency")])
        assert not combination_bonuses([hit("E4.crypto_address"), hit("B1.urgency")])

    def test_delivery_pattern(self):
        fired = combination_bonuses([hit("G5.brand_mismatch"), hit("C6.courier_post")])
        assert ("delivery_link", 10) in fired

    def test_a_prize_that_must_be_paid_for(self):
        fired = combination_bonuses(
            [hit("H3.unsolicited_prize", Severity.MEDIUM), hit("E7.upfront_fee")]
        )
        assert ("prize_with_fee", 10) in fired
        assert not combination_bonuses([hit("H3.unsolicited_prize"), hit("B1.urgency")])

    def test_a_known_contact_who_needs_money_now(self):
        for ask in ("J2.relative_in_trouble", "J3.hijacked_account_ask"):
            fired = combination_bonuses([hit(ask), hit("B1.urgency", Severity.MEDIUM)])
            assert ("known_contact_under_pressure", 10) in fired
        # Urgency specifically: a threat to block an account is another script.
        assert not combination_bonuses(
            [hit("J3.hijacked_account_ask"), hit("B2.account_block_threat")]
        )

    def test_several_can_fire_together(self):
        fired = combination_bonuses(
            [
                hit("C1.bank_security"),
                hit("A1.otp_request"),
                hit("F1.remote_access_app"),
                hit("E1.safe_account"),
                hit("B1.urgency"),
            ]
        )
        assert len(fired) >= 3

    def test_every_combination_references_real_rules(self):
        """A combination naming a renamed rule would silently never fire."""
        from saqbol.core.indicators.registry import REGISTRY

        families = {rid[0] for rid in REGISTRY}
        for combo in COMBINATIONS:
            for token in combo.left | combo.right:
                assert token in REGISTRY or token in families, (combo.name, token)


class TestRuleScore:
    def test_bonus_is_added(self):
        plain = sum(h.weight for h in [hit("C1.bank_security"), hit("A1.otp_request")])
        scored, fired = rule_score([hit("C1.bank_security"), hit("A1.otp_request")])
        assert scored == plain + 20
        assert fired == ["authority_plus_credentials"]

    def test_capped_at_one_hundred(self):
        many = [hit(f"C{i}.x", Severity.CRITICAL) for i in range(1, 6)]
        assert rule_score(many)[0] == 100

    def test_norm_is_a_fraction(self):
        assert rule_norm([]) == 0.0
        assert 0.0 < rule_norm([hit("C1.bank_security")]) < 1.0

    def test_delivery_scam_now_clears_the_threshold(self):
        """Regression on the gap T107 recorded.

        This message fired the right rules but scored 49 out of 100 with no
        combination bonus, just under the scam band. The courier-plus-link
        bonus is exactly what it was missing."""
        _norm, hits = analysed(
            "Казпочта: ваша посылка задержана на таможне. Срочно оплатите "
            "таможенный сбор 1 200 тг по ссылке kazpost-dostavka.info/pay"
        )
        base = sum(h.weight for h in hits)
        scored, fired = rule_score(hits)
        assert base == 49
        assert "delivery_link" in fired
        assert scored >= 50


class TestWeightRenormalisation:
    def test_rules_only_can_reach_the_scam_band(self):
        """Without renormalisation the baseline caps at the rule weight and can
        never be beaten, which makes the comparison meaningless."""
        norm, hits = analysed(
            "Это служба безопасности банка. Срочно назовите код из СМС и "
            "переведите деньги на безопасный счёт. Не кладите трубку."
        )
        verdict = fuse(norm, hits)
        assert verdict.components.rule_norm == 1.0
        assert verdict.risk == 1.0
        assert verdict.band is Band.SCAM

    def test_rules_only_never_abstains(self):
        """One signal cannot disagree with itself, so the baseline answers
        every item. That is what makes its coverage comparable."""
        norm, hits = analysed("Назовите код из СМС")
        assert fuse(norm, hits).abstained_because is None

    def test_adding_a_model_changes_the_divisor(self):
        norm, hits = analysed("Ваш заказ отправлен")
        rules_only = fuse(norm, hits)
        with_model = fuse(norm, hits, judgement=LLMJudgement(confidence=0.0))
        assert rules_only.risk == pytest.approx(with_model.risk)

    def test_custom_weights_are_honoured(self):
        norm, hits = analysed("Назовите код из СМС")
        heavy = fuse(norm, hits, weights=FusionWeights(rule=1.0, llm=0.0))
        assert heavy.risk == pytest.approx(heavy.components.rule_norm)


class TestBanding:
    @pytest.mark.parametrize(
        "risk,expected",
        [
            (1.0, Band.SCAM),
            (0.70, Band.SCAM),
            (0.69, Band.SUSPICIOUS),
            (0.40, Band.SUSPICIOUS),
            (0.39, Band.LIKELY_SAFE),
            (0.0, Band.LIKELY_SAFE),
        ],
    )
    def test_boundaries(self, risk, expected):
        assert band_for(risk) is expected

    def test_thresholds_are_configurable(self):
        strict = Thresholds(scam=0.9, suspicious=0.8)
        assert band_for(0.85, strict) is Band.SUSPICIOUS

    def test_one_critical_indicator_is_never_likely_safe(self):
        """A bare credential request is the strongest single signal in the
        catalogue. The suspicious threshold is tied to the severity scale so it
        cannot fall below one critical hit."""
        norm, hits = analysed("Назовите код из СМС")
        verdict = fuse(norm, hits)
        assert verdict.components.rule_norm == pytest.approx(0.40)
        assert verdict.band is Band.SUSPICIOUS


class TestAbstention:
    def test_disagreement_overrides_the_band(self):
        """Rules certain, model certain the other way. Neither is trusted."""
        norm, hits = analysed(
            "Это служба безопасности банка. Назовите код из СМС и переведите на безопасный счёт."
        )
        verdict = fuse(norm, hits, judgement=LLMJudgement(confidence=0.0))
        assert verdict.abstained_because == "disagreement"
        assert verdict.band is Band.UNSURE

    def test_agreement_does_not_abstain(self):
        norm, hits = analysed(
            "Это служба безопасности банка. Назовите код из СМС и переведите на безопасный счёт."
        )
        verdict = fuse(norm, hits, judgement=LLMJudgement(confidence=0.95))
        assert verdict.abstained_because is None
        assert verdict.band is Band.SCAM

    def test_abstains_when_the_model_says_scam_and_rules_are_silent(self):
        """The dangerous direction. A quiet rule set plus a confident model is
        exactly the case where a single-signal system says 'safe' and is wrong."""
        norm, hits = analysed("Здравствуйте, как ваши дела сегодня?")
        verdict = fuse(norm, hits, judgement=LLMJudgement(confidence=0.95))
        assert verdict.abstained_because == "disagreement"

    def test_low_self_consistency_abstains(self):
        norm, hits = analysed("Назовите код из СМС")
        verdict = fuse(norm, hits, judgement=LLMJudgement(confidence=0.5), self_consistency=0.4)
        assert verdict.abstained_because == "low_self_consistency"

    def test_high_self_consistency_does_not(self):
        norm, hits = analysed("Назовите код из СМС")
        verdict = fuse(norm, hits, judgement=LLMJudgement(confidence=0.5), self_consistency=0.9)
        assert verdict.abstained_because is None

    def test_disagreement_takes_precedence(self):
        norm, hits = analysed("Здравствуйте, как ваши дела?")
        verdict = fuse(norm, hits, judgement=LLMJudgement(confidence=0.99), self_consistency=0.2)
        assert verdict.abstained_because == "disagreement"

    def test_retrieval_alone_never_abstains(self):
        """Retrieval is an input to the model's judgement, not a third opinion.
        Including it in the disagreement measure made almost everything
        abstain, because an unrelated message still sits at moderate cosine
        similarity to its nearest playbook."""
        norm, hits = analysed("Здравствуйте, как ваши дела?")
        verdict = fuse(norm, hits, retrieval=("kz.bank_security_call", 0.55))
        assert verdict.abstained_because is None

    def test_weak_retrieval_does_not_dilute_a_strong_rule_signal(self):
        """Regression found by running the pipeline end to end.

        A real delivery scam scored 59 on the rules, then a retrieval score of
        0.007 dragged the fused risk to 0.41 and out of the scam band. A low
        similarity only ever meant "no playbook matched well", which is not
        evidence of safety."""
        norm, hits = analysed(
            "Казпочта: посылка задержана на таможне. Срочно оплатите "
            "сбор 1 200 тг: kazpost-dostavka.info/pay"
        )
        weak = fuse(norm, hits, retrieval=("kz.delivery_link", 0.007))
        assert weak.risk == pytest.approx(weak.components.rule_norm)
        assert weak.band is not Band.LIKELY_SAFE

    def test_weak_retrieval_names_no_playbook(self):
        """A legitimate tracking message was being labelled a Chinese
        task-commission scam with a Chinese hotline, purely because something
        had to be top of the list."""
        norm, hits = analysed("Ваш заказ отправлен. Отследить: https://post.kz/track/AB1")
        verdict = fuse(norm, hits, retrieval=("cn.part_time_task_job", 0.003))
        assert verdict.playbook_id is None

    def test_strong_retrieval_still_names_a_playbook(self):
        norm, hits = analysed("Назовите код из СМС")
        verdict = fuse(norm, hits, retrieval=("kz.bank_security_call", 0.8))
        assert verdict.playbook_id == "kz.bank_security_call"


class TestSelfConsistencySampling:
    @pytest.mark.parametrize("risk", [0.30, 0.5, 0.75])
    def test_sampled_in_the_ambiguous_band(self, risk):
        assert should_sample_self_consistency(risk)

    @pytest.mark.parametrize("risk", [0.0, 0.29, 0.76, 1.0])
    def test_not_sampled_outside_it(self, risk):
        """Clear cases must not pay for five samples."""
        assert not should_sample_self_consistency(risk)


class TestEvidence:
    def test_span_invariant_is_enforced(self):
        bad = hit(
            "A1.otp_request",
            spans=[EvidenceSpan(start=0, end=4, text="wrong", indicator_id="A1.otp_request")],
        )
        with pytest.raises(ValueError, match="quotes"):
            assert_spans_match("Назовите код", [bad])

    def test_fuse_refuses_a_bad_span(self):
        norm = normalize("Назовите код")
        bad = hit(
            "A1.otp_request",
            spans=[EvidenceSpan(start=0, end=4, text="zzzz", indicator_id="A1.otp_request")],
        )
        with pytest.raises(ValueError):
            fuse(norm, [bad])

    def test_evidence_is_deduplicated_and_ordered(self):
        span_a = EvidenceSpan(start=10, end=14, text="код", indicator_id="A1.otp_request")
        span_b = EvidenceSpan(start=0, end=3, text="Это", indicator_id="C1.bank_security")
        collected = collect_evidence(
            [
                hit("A1.otp_request", spans=[span_a, span_a]),
                hit("C1.bank_security", spans=[span_b]),
            ]
        )
        assert [s.start for s in collected] == [0, 10]

    def test_real_pipeline_evidence_quotes_the_message(self):
        norm, hits = analysed("Срочно назовите код из СМС и не кладите трубку")
        verdict = fuse(norm, hits)
        assert verdict.evidence
        for span in verdict.evidence:
            assert norm.text[span.start : span.end] == span.text


class TestVerdictShape:
    def test_playbook_comes_from_the_model_when_present(self):
        norm, hits = analysed("Назовите код из СМС")
        verdict = fuse(
            norm,
            hits,
            retrieval=("kz.delivery_link", 0.4),
            judgement=LLMJudgement(playbook_id="kz.bank_security_call", confidence=0.8),
        )
        assert verdict.playbook_id == "kz.bank_security_call"

    def test_falls_back_to_retrieval(self):
        norm, hits = analysed("Назовите код из СМС")
        verdict = fuse(norm, hits, retrieval=("kz.bank_security_call", 0.62))
        assert verdict.playbook_id == "kz.bank_security_call"
        assert verdict.playbook_confidence == pytest.approx(0.62)

    def test_action_and_hotline_are_passed_through_not_generated(self):
        """They come from the playbook. A model must never author advice."""
        norm, hits = analysed("Назовите код из СМС")
        verdict = fuse(norm, hits, action_key="action.hang_up_call_bank", hotline="1414")
        assert verdict.action_key == "action.hang_up_call_bank"
        assert verdict.hotline == "1414"

    def test_stage_from_the_model_is_kept(self):
        norm, hits = analysed("Назовите код из СМС")
        verdict = fuse(
            norm,
            hits,
            judgement=LLMJudgement(confidence=0.9, stage=Stage.EXTRACTION),
        )
        assert verdict.stage is Stage.EXTRACTION

    def test_language_is_carried_through(self):
        norm, hits = analysed("Сәлеметсіз бе, бұл банктің қауіпсіздік қызметі")
        assert fuse(norm, hits).language.value == "kk"

    def test_components_are_recorded(self):
        norm, hits = analysed("Назовите код из СМС")
        verdict = fuse(
            norm,
            hits,
            retrieval=("kz.bank_security_call", 0.7),
            judgement=LLMJudgement(confidence=0.8),
            self_consistency=0.8,
        )
        assert verdict.components.retrieval_sim == pytest.approx(0.7)
        assert verdict.components.llm_conf == pytest.approx(0.8)
        assert verdict.components.self_consistency == pytest.approx(0.8)

    def test_check_id_is_generated_when_absent(self):
        norm, hits = analysed("тест")
        assert len(fuse(norm, hits).check_id) == 32

    def test_serialises(self):
        norm, hits = analysed("Назовите код из СМС")
        assert "risk" in fuse(norm, hits).model_dump_json()


class TestHardNegativesStayCalm:
    @pytest.mark.parametrize(
        "text",
        [
            "Никому не сообщайте код 4821. Kaspi Bank",
            "Ваш заказ отправлен. Отследить: https://post.kz/track/AB123456789KZ",
            "Halyk Bank: вход с нового устройства. Если это не вы, позвоните в банк.",
            "Здравствуйте, товар ещё продаётся?",
        ],
    )
    def test_genuine_messages_are_not_scam(self, text):
        """The combination bonuses must not push a real message over the line."""
        norm, hits = analysed(text)
        assert fuse(norm, hits).band is not Band.SCAM, text


def test_thresholds_are_ordered_sensibly():
    t = DEFAULT_THRESHOLDS
    assert 0 < t.suspicious < t.scam <= 1
    assert t.sample_lo < t.sample_hi
