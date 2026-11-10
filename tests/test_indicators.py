"""T105 and T106 — indicator families A to F and H to J.

Three obligations from docs/03_INDICATORS.md section "Testing requirements":

1. One positive fixture per indicator id.
2. Hard negatives that must stay below the scam threshold, and in particular a
   genuine one-time-password message that must produce no family-A hit at all.
3. The span invariant, asserted across every fixture in the file.

Point 2 is the one that matters. Building a detector that flags everything is
easy, and the false-positive rate on hard negatives is a headline metric
precisely because that is where naive systems collapse.
"""

from __future__ import annotations

import pytest

import saqbol.core.indicators  # noqa: F401  — registers every family
from saqbol.core.extract import extract
from saqbol.core.indicators.registry import REGISTRY, build_context, run_all, score
from saqbol.core.normalize import normalize

#: Rule score at or above which a message is treated as scam-like by the
#: deterministic layer alone. Fusion re-weights this later; here it is only a
#: test threshold.
SCAM_THRESHOLD = 50


def analyse(text: str, metadata: dict | None = None):
    """Run the whole deterministic layer over one message.

    `qr_payloads` is lifted out of the metadata dict because a decoded QR code
    is an entity, not channel metadata; in production the vision stage fills it.
    """
    meta = dict(metadata or {})
    payloads = meta.pop("qr_payloads", None)
    norm = normalize(text)
    entities = extract(norm.text)
    if payloads:
        entities.qr_payloads = list(payloads)
    ctx = build_context(norm, entities, metadata=meta)
    return ctx, run_all(ctx)


def fired(hits) -> set[str]:
    return {h.indicator_id for h in hits}


# --------------------------------------------------------------------------
# One positive fixture per indicator id.
# --------------------------------------------------------------------------

POSITIVES: dict[str, tuple[str, dict | None]] = {
    # A — credential extraction
    "A1.otp_request": ("Назовите код из СМС, который вам пришёл", None),
    "A2.card_secrets": ("Продиктуйте три цифры на обороте карты", None),
    "A3.password_request": ("Введите пароль от приложения банка", None),
    "A4.code_relay": ("Прочитайте СМС, которое сейчас пришло", None),
    # B — urgency and fear
    "B1.urgency": ("Срочно подтвердите операцию", None),
    "B2.account_block_threat": ("Ваш счёт будет заблокирован сегодня", None),
    "B3.criminal_threat": ("На вас заведено уголовное дело", None),
    "B4.money_at_risk": ("С вашего счёта пытаются списать средства", None),
    # C — authority impersonation
    "C1.bank_security": ("Это служба безопасности банка", None),
    "C2.police_prosecutor": ("Вас беспокоит полиция города Алматы", None),
    "C3.egov_1414": ("Портал eGov требует подтверждения", None),
    "C4.national_bank": ("Национальный банк Казахстана уведомляет вас", None),
    "C5.embassy_immigration": ("Обратитесь в посольство, ваша виза аннулирована", None),
    "C6.courier_post": ("Посылка задержана на таможне", None),
    "C7.telecom": ("Ваш номер будет отключен завтра", None),
    # D — channel migration
    "D1.move_to_messenger": ("Напишите мне в WhatsApp для деталей", None),
    "D2.leave_platform": ("Давайте оплатим напрямую, не через сайт", None),
    "D3.dont_hang_up": ("Не кладите трубку, я вас соединю", None),
    # E — money movement
    "E1.safe_account": ("Переведите средства на безопасный счёт", None),
    "E2.transfer_to_person": ("Переведите на карту для проверки", None),
    "E3.take_a_loan": ("Оформите кредит в приложении прямо сейчас", None),
    "E4.crypto_address": ("Переведите на 0x" + "a1b2c3d4e5" * 4, None),
    "E5.mule_recruitment": ("Нужна ваша карта, переводы за процент", None),
    "E6.guarantee_deposit": ("Внесите залог для проверки вашей невиновности", None),
    "E7.upfront_fee": ("Для вывода средств оплатите комиссию", None),
    # F — software installation
    "F1.remote_access_app": ("Установите AnyDesk, я вам помогу", None),
    "F2.apk_attachment": ("Откройте файл Kaspi_update.apk", None),
    "F3.install_instruction": ("Установите приложение по ссылке", None),
    "F4.disable_protection": ("Отключите Play Protect перед установкой", None),
    # G — links and domains. G4 and G6 need facts the text cannot carry, so
    # they take them through metadata exactly as family I does.
    "G1.lookalike_domain": ("Оплата на kaspі.kz", None),
    "G2.punycode_idn": ("Ссылка http://xn--80ak6aa92e.com/pay", None),
    "G3.shortener": ("Перейдите: https://bit.ly/3xYzAbc", None),
    "G4.long_redirect_chain": (
        "Ссылка https://bit.ly/3xYzAbc",
        {"redirect_chains": {"https://bit.ly/3xYzAbc": ["a", "b", "c", "d"]}},
    ),
    "G5.brand_mismatch": ("Kaspi: подтвердите вход kaspi-secure.ru", None),
    "G6.fresh_domain": (
        "Магазин super-shop-kz.top",
        {"domain_ages": {"super-shop-kz.top": 4}},
    ),
    "G7.qr_payload_risk": (
        "Отсканируйте код для оплаты",
        {"qr_payloads": ["https://kaspі.kz/pay"]},
    ),
    "G8.ip_url": ("Оплатите здесь http://45.9.148.22/pay", None),
    # H — offers
    "H1.guaranteed_returns": ("Гарантированный доход без риска", None),
    "H2.celebrity_investment": ("С вами свяжется личный менеджер платформы", None),
    "H3.unsolicited_prize": ("Поздравляем, вы выиграли главный приз", None),
    "H4.easy_job": ("Работа в телеграм, доход от 300 000 тг", None),
    "H5.romance_to_investment": ("Я научу зарабатывать, мой брокер поможет", None),
    # I — contact metadata, which pasted text cannot supply
    "I1.foreign_number_local_claim": (
        "Служба безопасности банка Kaspi, перезвоните на +44 20 7946 0958",
        None,
    ),
    "I2.spoofed_short_code": (
        "Сообщение от 1414",
        {"claimed_number": "1414", "sender_phone": "+7 707 123 45 67"},
    ),
    "I3.new_telegram_account": ("Здравствуйте", {"account_age_days": 3}),
    "I4.relative_new_number": (
        "Это твой сын, у меня новый номер",
        {"is_known_contact": False},
    ),
    # J — social engineering
    "J1.secrecy": ("Это тайна следствия, не говорите родственникам", None),
    "J2.relative_in_trouble": ("Я попал в аварию, нужны деньги", None),
    "J3.hijacked_account_ask": ("Скинь денег срочно, я потом верну", None),
    "J4.script_handoff": ("Сейчас переключу на специалиста", None),
}


@pytest.mark.parametrize("indicator_id", sorted(POSITIVES))
def test_every_indicator_has_a_working_positive_fixture(indicator_id):
    text, metadata = POSITIVES[indicator_id]
    _, hits = analyse(text, metadata)
    assert indicator_id in fired(hits)


def test_every_registered_indicator_is_covered():
    """A rule with no fixture is a rule nobody has checked."""
    missing = sorted(set(REGISTRY) - set(POSITIVES))
    assert not missing, f"registered but untested: {missing}"


# --------------------------------------------------------------------------
# Hard negatives. Genuine messages that superficially resemble scams.
# --------------------------------------------------------------------------

HARD_NEGATIVES = {
    "kaspi_otp": "Никому не сообщайте код 4821. Kaspi Bank",
    "egov_1414": "Код подтверждения 8391 для входа в eGov. Никому не сообщайте код.",
    "kazpost_tracking": "Ваш заказ отправлен. Отследить: https://post.kz/track/AB123456789KZ",
    "halyk_login": (
        "Halyk Bank: зафиксирован вход в приложение с нового устройства. "
        "Если это не вы, позвоните в банк."
    ),
    "olx_buyer": "Здравствуйте, товар ещё продаётся? Могу забрать завтра после обеда.",
    "kaspi_promo": "Kaspi Bonus: вам начислено 500 бонусов за покупки в июле.",
    # A bank's own "we never ask" warning names the code, the CVV and the
    # password in one sentence, and then quotes the scam to warn against it.
    "bank_never_asks": (
        "Kaspi: мы никогда не спрашиваем код из СМС, CVV или пароль от приложения. "
        "Если вам звонят «из службы безопасности банка» и просят назвать код — это "
        "мошенники. Положите трубку и позвоните 9999."
    ),
    # "Tell me the code" of a door, not of a bank.
    "courier_intercom": (
        "Добрый день, курьер Яндекс Еды, стою у подъезда 3. "
        "Скажите код от домофона или спуститесь, пожалуйста."
    ),
}


@pytest.mark.parametrize("name", sorted(HARD_NEGATIVES))
def test_hard_negatives_stay_below_threshold(name):
    _, hits = analyse(HARD_NEGATIVES[name])
    assert score(hits) < SCAM_THRESHOLD, f"{name} fired {fired(hits)}"


def test_genuine_otp_produces_no_credential_hit():
    """The single most important negative in the corpus.

    A real one-time-password message contains the same verb and noun as the
    scam that asks for the code. The family must fire on the request, never on
    the warning.
    """
    _, hits = analyse(HARD_NEGATIVES["kaspi_otp"])
    assert not [h for h in hits if h.indicator_id.startswith("A")]


def test_negation_is_checked_in_both_directions():
    """Genuine messages place the warning before the code as often as after."""
    for text in [
        "Никому не сообщайте код 4821",
        "Код 4821 для входа. Никому не сообщайте код.",
    ]:
        _, hits = analyse(text)
        assert not [h for h in hits if h.indicator_id.startswith("A")], text


# --------------------------------------------------------------------------
# Requests written with a word, a comma or quotation marks inside the phrase.
# --------------------------------------------------------------------------

SPACED_REQUESTS = {
    "A1.otp_request": [
        "Назовите мне код, который пришёл",
        "Продиктуйте, пожалуйста, код",
        "Скажите мне, пожалуйста, код из сообщения",
        "На ваш телефон придет SMS, в котором указан код, назовите его",
        "Сейчас придёт код, продиктуйте его оператору",
    ],
    "E1.safe_account": [
        "Нужно перевести деньги на “защищённый” счёт",
        "Переведите средства на «безопасный» счёт",
    ],
    "E2.transfer_to_person": ["Чтобы сохранить деньги, переведите их на другой счёт"],
    "J3.hijacked_account_ask": ["Привет! Проголосуй, пожалуйста, за Настю - это моя племянница"],
    "B2.account_block_threat": [
        "Ваша карточка заблокирована",
        "Ваша карта заблокирована",
        "Ваш счёт заблокирован",
    ],
    "B4.money_at_risk": ["Кто-то проводит подозрительные транзакции по вашей карточке"],
    "C6.courier_post": [
        "Почта Казахстана: ваша посылка прибыла на склад, но не может быть доставлена",
    ],
}


@pytest.mark.parametrize(
    ("indicator_id", "text"),
    [(rule, text) for rule, texts in sorted(SPACED_REQUESTS.items()) for text in texts],
)
def test_a_request_is_found_with_words_or_quotes_inside_it(indicator_id, text):
    _, hits = analyse(text)
    assert indicator_id in fired(hits), f"{text!r} fired {fired(hits)}"


#: What the wider request forms must not reach: a code the message itself
#: carries, a code that is only mentioned, and a warning not to share one.
NOT_A_REQUEST = [
    "CDEK: заказ готов к выдаче. Код получения 4821, назовите его сотруднику пункта выдачи.",
    "В сообщении указан код для входа в приложение.",
    "Вам отправлено сообщение, в нём код. Никому его не сообщайте.",
    "Код 4821. Никому не называйте его, даже сотрудникам банка.",
    "Никому не называйте этот код.",
    "Скажите, пожалуйста, код от домофона",
]


@pytest.mark.parametrize("text", NOT_A_REQUEST)
def test_a_carried_or_mentioned_code_is_not_a_request(text):
    _, hits = analyse(text)
    assert not [h for h in hits if h.indicator_id.startswith("A")], f"{text!r} fired {fired(hits)}"


# --------------------------------------------------------------------------
# Positives that must clear the threshold end to end.
# --------------------------------------------------------------------------

REALISTIC_SCAMS = {
    "bank_security_call": (
        "Здравствуйте! Это служба безопасности банка. С вашего счёта пытаются "
        "списать 480 000 тг. Срочно назовите код из СМС и переведите деньги на "
        "безопасный счёт. Не кладите трубку."
    ),
    "apk_install": "Установите Kaspi_update.apk и отключите Play Protect для обновления.",
    "remote_access_loan": (
        "Установите AnyDesk, я помогу. Затем оформите кредит в приложении, это для проверки."
    ),
    "mule_recruitment": "Нужна ваша карта, переводы за процент. Доход от 200 000 тг без опыта.",
    "china_fake_police": (
        "您好，我是公安局的警官。您涉嫌洗钱，需要缴纳保证金到安全账户。不要告诉家人。"
    ),
}


@pytest.mark.parametrize("name", sorted(REALISTIC_SCAMS))
def test_realistic_scams_clear_threshold(name):
    _, hits = analyse(REALISTIC_SCAMS[name])
    assert score(hits) >= SCAM_THRESHOLD, f"{name} only fired {fired(hits)}"


def test_chinese_rules_actually_fire():
    """Regression. Han phrases are flanked by other Han characters, so the
    Unicode letter boundary used for alphabetic scripts suppressed every match
    and silently disabled the entire China playbook set."""
    _, hits = analyse(REALISTIC_SCAMS["china_fake_police"])
    assert {"C2.police_prosecutor", "E6.guarantee_deposit", "E1.safe_account"} <= fired(hits)


# --------------------------------------------------------------------------
# Invariants.
# --------------------------------------------------------------------------

ALL_TEXTS = (
    [t for t, _ in POSITIVES.values()]
    + list(HARD_NEGATIVES.values())
    + list(REALISTIC_SCAMS.values())
)


def test_span_invariant_holds_across_every_fixture():
    """normalized[start:end] == span.text, for every hit this file can produce.

    The explainability claim rests on this. A span that does not quote the real
    text is a highlight pointing at the wrong words.
    """
    for text in ALL_TEXTS:
        ctx, hits = analyse(text)
        for hit in hits:
            for span in hit.spans:
                assert span.matches(ctx.text), f"{span.indicator_id} in {text!r}"


def test_scores_are_capped():
    _, hits = analyse(REALISTIC_SCAMS["bank_security_call"])
    assert 0 <= score(hits) <= 100


def test_empty_input_is_silent():
    _, hits = analyse("")
    assert hits == []
