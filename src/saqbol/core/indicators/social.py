"""Family J — social engineering context.

J1 is deliberately narrow. The obvious phrasing, "никому не говорите", is also
what a genuine one-time-password message says about the code it carries, so
matching it would fire this rule on the single most common legitimate message
in the corpus. The phrases here are the ones that isolate a victim from a
second opinion, not the ones that protect a code.
"""

from __future__ import annotations

from saqbol.core.indicators.kk_lexicon import kk
from saqbol.core.indicators.registry import keyword_indicator
from saqbol.core.types import Severity

keyword_indicator(
    "J1.secrecy",
    Severity.HIGH,
    "Demands secrecy about the conversation itself",
    phrases=[
        "тайна следствия",
        "не говорите родственник*",
        "не говорите родным",
        "не рассказывайте близк*",
        "не сообщайте никому о звонке",
        "не говорите сотрудникам банка",
        "это между нами",
        "строго конфиденциальн*",
        "не обсуждайте это ни с кем",
        "do not tell anyone about this call",
        "о нашем разговоре",
        "никому о разговоре",
        "секретн* операци*",
        # zh
        "不要告诉家人",
        "保密",
        # kk
        *kk("J1.secrecy"),
    ],
)

keyword_indicator(
    "J2.relative_in_trouble",
    Severity.HIGH,
    "A relative is in trouble and money is needed now",
    phrases=[
        "попал в аварию",
        "попала в аварию",
        "я в больнице",
        "меня задержали",
        "случилась беда",
        "нужны деньги на операцию",
        "сбил человека",
        "i had an accident",
        "у меня проблемы",
        # kk
        *kk("J2.relative_in_trouble"),
    ],
)

keyword_indicator(
    "J3.hijacked_account_ask",
    Severity.HIGH,
    "A known contact asks for an urgent transfer",
    phrases=[
        "скинь денег",
        "скинь пожалуйста",
        "переведи срочно",
        "займи до завтра",
        "я потом верну",
        "срочно нужны деньги",
        "можешь одолжить",
        "can you send me money",
        "одолжи* денег",
        "одолжить денег",
        "не звони",
        "проголосуй* ~ за",
        # kk
        *kk("J3.hijacked_account_ask"),
    ],
)

keyword_indicator(
    "J4.script_handoff",
    Severity.MEDIUM,
    "Transfers the victim to another supposed official",
    phrases=[
        "переключу на специалиста",
        "соединю вас со следователем",
        "соединю с сотрудником",
        "с вами свяжется специалист",
        "передаю трубку",
        "переведу ваш звонок",
        "i will transfer you",
        # kk
        *kk("J4.script_handoff"),
    ],
)
