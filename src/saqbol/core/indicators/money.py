"""Family E — money movement.

Where the loss actually happens. E1, E3, E5 and E6 have no legitimate
counterpart in an unsolicited message, which is why they sit at critical.
"""

from __future__ import annotations

from saqbol.core.indicators.kk_lexicon import kk
from saqbol.core.indicators.registry import DetectionContext, indicator, keyword_indicator
from saqbol.core.types import IndicatorHit, Severity

keyword_indicator(
    "E1.safe_account",
    Severity.CRITICAL,
    "The safe-account fiction",
    phrases=[
        "безопасн* счет*",
        "резервн* счет*",
        "страхов* счет*",
        "защищенн* счет*",
        "специальн* счет* банка",
        "safe account",
        "secure account",
        "временн* счет*",
        # kk. "қауіпсіз счетке" — Kazakh adjective, Russian noun — is the form
        # heard most often, so both it and "шот" are carried.
        *kk("E1.safe_account"),
        # zh
        "安全账户",
    ],
)

keyword_indicator(
    "E2.transfer_to_person",
    Severity.HIGH,
    "Asks for a transfer to a personal card, often framed as verification",
    phrases=[
        "переведите на карту",
        "перевести на карту",
        "на мою карту",
        "на эту карту",
        "переведите на счет",
        "переведите ~ на ~ счет*",
        "для проверки переведите",
        "transfer to this card",
        "деньги по ошибке",
        "по ошибке перевел*",
        "по ошибке отправил*",
        "верните мне",
        "деньги моему другу",
        "другу на номер",
        # kk
        *kk("E2.transfer_to_person"),
        # zh
        "先转",
        "转到我",
        "转账到我",
        "打到我卡",
        "转到这张卡",
        "先付款",
    ],
)

keyword_indicator(
    "E3.take_a_loan",
    Severity.CRITICAL,
    "Instructs the recipient to take out a loan",
    phrases=[
        "оформите кредит",
        "оформить кредит",
        "оформите займ",
        "возьмите кредит",
        "подтвердите заявку на кредит",
        "кредит на ваше имя",
        "take out a loan",
        # kk
        *kk("E3.take_a_loan"),
    ],
)

keyword_indicator(
    "E5.mule_recruitment",
    Severity.CRITICAL,
    "Recruits the recipient to rent out a card or account",
    phrases=[
        "сдать карту в аренду",
        "аренда карты",
        "аренду карту",
        "нужен ваш kaspi",
        "нужна ваша карта",
        "пропустить через карту",
        "переводы за процент",
        "дроп",
        "дропов",
        # kk
        *kk("E5.mule_recruitment"),
    ],
)

keyword_indicator(
    "E6.guarantee_deposit",
    Severity.CRITICAL,
    "Demands a deposit to prove innocence or clear an investigation",
    phrases=[
        "гарантийн* взнос",
        "залог для проверки",
        "внесите залог",
        "депозит для проверки",
        "guarantee deposit",
        # zh
        "保证金",
        "缴纳保证金",
        # kk
        *kk("E6.guarantee_deposit"),
    ],
)

keyword_indicator(
    "E7.upfront_fee",
    Severity.HIGH,
    "Requires a payment before a prize, job, loan or refund is released",
    phrases=[
        "оплатите комиссию",
        "оплатить комиссию",
        "предоплат*",
        "оплатите налог",
        "для вывода оплатите",
        "внесите платеж",
        "оплатите страховку",
        "advance fee",
        "pay the fee first",
        # kk
        *kk("E7.upfront_fee"),
        # zh
        "垫付本金",
        "先垫付",
        "充值后提现",
        "缴纳手续费",
        "先交费",
        "解冻费",
        "再充值",
    ],
)


@indicator(
    "E4.crypto_address",
    Severity.HIGH,
    "A wallet address appears in an unsolicited message",
)
def crypto_address(ctx: DetectionContext) -> list[IndicatorHit]:
    """Entity-driven rather than phrase-driven.

    A wallet address is self-identifying: no phrase list is needed, and the
    checksummed formats in `patterns.CRYPTO` are what make it precise.
    """
    if not ctx.entities.crypto_addresses:
        return []
    return [
        IndicatorHit(
            indicator_id="E4.crypto_address",
            severity=Severity.HIGH,
            detail={"addresses": len(ctx.entities.crypto_addresses)},
        )
    ]
