"""T104 — indicator registry, phrase compilation and scoring."""

from __future__ import annotations

import re as stdlib_re
from pathlib import Path

import pytest

from saqbol.core.extract import extract
from saqbol.core.indicators import registry as reg
from saqbol.core.normalize import normalize
from saqbol.core.types import RULE_SCORE_CAP, IndicatorHit, Severity

DOCS = Path(__file__).resolve().parents[1] / "docs" / "03_INDICATORS.md"


@pytest.fixture
def clean_registry():
    """Registration mutates module state, so tests must not leak into each other."""
    saved = dict(reg.REGISTRY)
    reg.REGISTRY.clear()
    yield reg.REGISTRY
    reg.REGISTRY.clear()
    reg.REGISTRY.update(saved)


def ctx(text: str) -> reg.DetectionContext:
    norm = normalize(text)
    return reg.build_context(norm, extract(norm.text))


class TestPhraseCompilation:
    def test_matches_across_whitespace_runs(self):
        pattern = reg.compile_phrase("код из смс")
        assert pattern.search("назовите код  из   смс сейчас")

    def test_respects_word_boundaries(self):
        """The reason boundaries use a Unicode lookaround rather than \\b."""
        pattern = reg.compile_phrase("код")
        assert pattern.search("назовите код")
        assert not pattern.search("гражданский кодекс")

    def test_star_allows_inflection(self):
        pattern = reg.compile_phrase("безопасн* счет*")
        assert pattern.search("переведите на безопасный счет")
        assert pattern.search("перевод на безопасного счета")

    def test_star_does_not_run_away(self):
        """Four letters of slack, not unlimited, or the rule matches anything."""
        pattern = reg.compile_phrase("счет*")
        assert not pattern.search("счетоводственный")

    @pytest.mark.parametrize(
        "text",
        [
            "переведите на «защищенный» счет",
            "переведите на “защищенный” счет",
            'переведите на "защищенный" счет',
            "переведите на „защищенный“ счет",
        ],
    )
    def test_quotation_marks_do_not_break_a_phrase(self, text):
        assert reg.compile_phrase("защищенн* счет*").search(text)

    @pytest.mark.parametrize(
        "text",
        [
            "назовите код",
            "назовите мне код",
            "назовите, пожалуйста, код",
            "назовите мне, пожалуйста, код",
            "назовите — пожалуйста — код",
        ],
    )
    def test_a_gap_admits_up_to_two_words_and_commas(self, text):
        assert reg.compile_phrase("назов* ~ код").search(text)

    @pytest.mark.parametrize(
        "text",
        [
            "назовите мне прямо сейчас код",  # three words
            "назовите имя. Код придет позже",  # a sentence end
            "назовите имя\nкод придет позже",  # a line break
            "назовите сумму 5000 код",  # digits are not words
            "назовитекод",
        ],
    )
    def test_a_gap_stops_at_three_words_a_sentence_end_and_digits(self, text):
        assert not reg.compile_phrase("назов* ~ код").search(text)

    def test_a_gap_is_only_where_it_is_written(self):
        pattern = reg.compile_phrase("переведите ~ на счет")
        assert pattern.search("переведите их на счет")
        assert not pattern.search("переведите их на другой счет")
        assert reg.compile_phrase("переведите ~ на ~ счет").search("переведите их на другой счет")

    def test_words_on_both_sides_of_a_gap_keep_their_boundaries(self):
        pattern = reg.compile_phrase("код ~ назовите")
        assert pattern.search("указан код, назовите его")
        assert not pattern.search("гражданский кодекс, назовите статью")

    @pytest.mark.parametrize("phrase", ["~ код", "код ~", "назов* ~ ~ код", "", "   "])
    def test_a_malformed_phrase_is_rejected(self, phrase):
        with pytest.raises(ValueError):
            reg.compile_phrase(phrase)


class TestFolding:
    def test_yo_and_case_are_folded(self):
        assert reg.fold_for_matching("СЧЁТ") == "счет"

    def test_fold_preserves_length(self):
        """Offsets into the folded text must index the original exactly."""
        for sample in ["СЧЁТ", "Ёлка", "Привет, МИР", "您好", "Ätzend"]:
            assert len(reg.fold_for_matching(sample)) == len(sample)


class TestKeywordIndicator:
    def test_detects_and_quotes_the_original_text(self, clean_registry):
        reg.keyword_indicator("A1.otp_request", Severity.CRITICAL, "test", ["код из смс"])
        hits = reg.run_all(ctx("Назовите КОД ИЗ СМС немедленно"))
        assert len(hits) == 1
        span = hits[0].spans[0]
        # The user is shown what they received, not the lowercased haystack.
        assert span.text == "КОД ИЗ СМС"

    def test_span_invariant_holds(self, clean_registry):
        """normalized[start:end] == span.text. The whole explainability claim
        rests on this, so it is asserted directly."""
        reg.keyword_indicator("E1.safe_account", Severity.CRITICAL, "test", ["безопасн* счет*"])
        c = ctx("Срочно переведите на Безопасный Счёт всю сумму")
        for hit in reg.run_all(c):
            for span in hit.spans:
                assert span.matches(c.text)

    def test_no_hit_on_clean_text(self, clean_registry):
        reg.keyword_indicator("A1.otp_request", Severity.CRITICAL, "test", ["код из смс"])
        assert reg.run_all(ctx("Ваш заказ отправлен")) == []

    def test_duplicate_id_rejected(self, clean_registry):
        reg.keyword_indicator("A1.otp_request", Severity.CRITICAL, "test", ["код"])
        with pytest.raises(ValueError, match="duplicate"):
            reg.keyword_indicator("A1.otp_request", Severity.HIGH, "test", ["другое"])

    @pytest.mark.parametrize("bad", ["otp_request", "Z1.bad_family", "A.no_number", "A1.Bad_Case"])
    def test_malformed_id_rejected(self, clean_registry, bad):
        with pytest.raises(ValueError, match="must look like"):
            reg.keyword_indicator(bad, Severity.LOW, "test", ["x"])


class TestScoring:
    def _hit(self, severity: Severity, n: int) -> list[IndicatorHit]:
        return [IndicatorHit(indicator_id=f"A{i}.x", severity=severity) for i in range(1, n + 1)]

    def test_weights_sum(self):
        assert reg.score(self._hit(Severity.MEDIUM, 2)) == 24

    def test_capped(self):
        """Ten critical hits must not produce a score of four hundred."""
        assert reg.score(self._hit(Severity.CRITICAL, 10)) == RULE_SCORE_CAP

    def test_norm_is_a_fraction(self):
        assert reg.rule_norm([]) == 0.0
        assert reg.rule_norm(self._hit(Severity.CRITICAL, 10)) == 1.0

    def test_empty(self):
        assert reg.score([]) == 0


class TestDocumentationContract:
    """Every implemented rule must be described in docs/03_INDICATORS.md.

    The catalogue is what a reviewer reads and what the paper describes. A rule
    that exists only in code is a rule nobody can audit.
    """

    def documented_ids(self) -> set[str]:
        text = DOCS.read_text(encoding="utf-8")
        return set(stdlib_re.findall(r"`([A-J]\d+\.[a-z0-9_]+)`", text))

    def test_registry_ids_are_documented(self):
        undocumented = sorted(set(reg.REGISTRY) - self.documented_ids())
        assert not undocumented, f"implemented but absent from the catalogue: {undocumented}"

    def test_ids_are_well_formed(self):
        for indicator_id in reg.REGISTRY:
            assert reg.ID_PATTERN.match(indicator_id)

    def test_docs_file_is_parseable(self):
        """Guards against the catalogue being renamed or emptied."""
        assert len(self.documented_ids()) >= 30
