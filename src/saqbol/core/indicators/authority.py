"""Family C — authority impersonation.

Claiming to be an institution is not itself proof of anything: real banks do
write to customers. These rules earn their weight through the combination
bonuses, particularly authority plus a credential request, and authority
contradicted by the contact metadata.

C3 deliberately fires on genuine eGov traffic as well. At high severity alone
it cannot reach the scam band, and suppressing it would lose the signal that
makes the code-phishing playbook recognisable when a request accompanies it.
"""

from __future__ import annotations

from saqbol.core.indicators.kk_lexicon import kk
from saqbol.core.indicators.registry import keyword_indicator
from saqbol.core.types import Severity

keyword_indicator(
    "C1.bank_security",
    Severity.HIGH,
    "Claims to be a bank security or anti-fraud department",
    phrases=[
        "служб* безопасности банка",
        "служб* безопасности",
        "отдел по борьбе с мошенничеством",
        "сотрудник банка",
        "специалист банка",
        "финансов* мониторинг",
        "bank security department",
        "fraud department",
        # kk
        *kk("C1.bank_security"),
    ],
)

keyword_indicator(
    "C2.police_prosecutor",
    Severity.HIGH,
    "Claims to be police, prosecutor or a financial-crime agency",
    phrases=[
        "полиц*",
        "прокуратур*",
        "следственн* комитет",
        "департамент полиции",
        "мвд",
        "police officer",
        "расследовани*",
        "следственн* действи*",
        "до окончания расследования",
        # zh
        "公安局",
        "检察院",
        "警官",
        "民警",
        "反诈中心",
        # kk
        *kk("C2.police_prosecutor"),
    ],
)

keyword_indicator(
    "C3.egov_1414",
    Severity.HIGH,
    "Claims to be eGov or the 1414 service",
    phrases=[
        "egov",
        "егов",
        "электронн* правительств*",
        "портал госуслуг",
        # kk
        *kk("C3.egov_1414"),
    ],
)

keyword_indicator(
    "C4.national_bank",
    Severity.HIGH,
    "Claims to be the National Bank",
    phrases=[
        "национальн* банк*",
        "нацбанк",
        "national bank of kazakhstan",
        # kk
        *kk("C4.national_bank"),
    ],
)

keyword_indicator(
    "C5.embassy_immigration",
    Severity.HIGH,
    "Claims to be an embassy, consulate or immigration authority",
    phrases=[
        "посольств*",
        "консульств*",
        "миграционн* служб*",
        "миграционн* полиц*",
        "виза аннулирован*",
        "embassy",
        "consulate",
        "immigration office",
        "visa cancelled",
        # zh
        "大使馆",
        "领事馆",
        "出入境",
        "签证注销",
        # kk
        *kk("C5.embassy_immigration"),
    ],
)

keyword_indicator(
    "C6.courier_post",
    Severity.MEDIUM,
    "Claims a parcel, delivery or customs matter",
    phrases=[
        "казпочта",
        "kazpost",
        "почта казахстана",
        "курьерск* служб*",
        "таможн*",
        "посылка задержан*",
        "отправление задержан*",
        "не удалось доставить",
        "не может быть доставлен*",
        "оплатите доставку",
        "customs fee",
        "delivery failed",
        # kk. The draft here was the bare word "жеткізу" (delivery), which
        # every genuine Kazpost SMS contains; kk_lexicon.yaml records why it
        # was replaced with the delivery-problem phrasings instead.
        *kk("C6.courier_post"),
    ],
)

keyword_indicator(
    "C7.telecom",
    Severity.MEDIUM,
    "Claims a mobile number will be disconnected or must be re-registered",
    phrases=[
        "номер будет отключен",
        "перерегистрац* номера",
        "блокировка номера",
        "договор связи истекает",
        "sim карта будет заблокирована",
        "беспокоит сотовый оператор",
        "sim-карты истекает",
        "sim карты истекает",
        "срок действия вашей sim",
        # kk
        *kk("C7.telecom"),
    ],
)
