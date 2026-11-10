"""Family A — credential and secret extraction.

The strongest signal set in the catalogue. No bank, government service or
courier ever asks for these, so a request is close to conclusive on its own.

The whole family respects negation. A genuine one-time-password message reads
"никому не сообщайте код" and contains the same verb and noun as the scam that
asks for the code. Firing on it would put the most common legitimate message in
the corpus into the scam band, which is exactly the failure the hard-negative
set exists to catch.

That guard is word-based, and Kazakh negates with a verb suffix rather than a
separate word, so `NEGATION_CUES` cannot see "кодты ешкімге айтпаңыз". The
Kazakh phrases in `kk_lexicon.yaml` are written with the positive imperative
spelled out for that reason; the file says so at length.
"""

from __future__ import annotations

from saqbol.core.indicators.kk_lexicon import kk
from saqbol.core.indicators.registry import keyword_indicator
from saqbol.core.types import Severity

keyword_indicator(
    "A1.otp_request",
    Severity.CRITICAL,
    "Asks the recipient for a one-time code sent by SMS or an app",
    respect_negation=True,
    phrases=[
        # Request forms only. The bare noun phrases — "код подтверждения",
        # "одноразовый код", "verification code" — are what a GENUINE message
        # says about the code it carries, so matching them puts every real
        # one-time-password SMS into the scam band. What separates the scam is
        # the imperative: someone is asking you to hand the code over.
        # ru. The gap admits "назовите мне, пожалуйста, код". It is given only
        # to verb forms that cannot be read as a noun or a participle:
        # "сообщ* ~ код" would match "в сообщении указан код", which is what a
        # genuine message says.
        "назов* ~ код",
        "продиктуй* ~ код",
        "скаж* ~ код",
        "сообщите ~ код",
        "перешлите ~ код",
        "сообщ* код",
        "отправ* код",
        "перешл* код",
        # The code is named first and asked for after: "придёт SMS, в котором
        # указан код, назовите его". A message that carries its own code puts
        # digits between the two words, and digits end the gap.
        "код ~ назовите",
        "код ~ продиктуйте",
        "код ~ сообщите",
        "код ~ скажите",
        "какой код",
        "код из смс",
        "код из сообщени*",
        "пришл* код",
        "пришли мне код",
        # kk
        *kk("A1.otp_request"),
        # en
        "send me the code",
        "give me the code",
        "tell me the code",
        "what code did you",
        "the code we sent",
        # zh
        "告诉我验证码",
        "把验证码",
        "验证码是多少",
        "提供验证码",
    ],
)

keyword_indicator(
    "A2.card_secrets",
    Severity.CRITICAL,
    "Asks for a full card number, expiry, CVV or PIN",
    respect_negation=True,
    phrases=[
        "три цифры",
        "три последние цифры",
        "последние три цифры",
        "цифры на обороте",
        "cvv",
        "cvc",
        "пин код",
        "пин-код",
        "полный номер карты",
        "номер вашей карты",
        "данные карты",
        "срок действия карты",
        "card number",
        "security code",
        # kk
        *kk("A2.card_secrets"),
        # zh
        "卡号",
        "银行卡密码",
    ],
)

keyword_indicator(
    "A3.password_request",
    Severity.CRITICAL,
    "Asks for an account password or banking-app login",
    respect_negation=True,
    phrases=[
        "логин и пароль",
        "ваш пароль",
        "введите пароль",
        "пароль от приложени*",
        "пароль от личного кабинета",
        "пароль от аккаунт*",
        "your password",
        # kk
        *kk("A3.password_request"),
        # zh
        "登录密码",
    ],
)

keyword_indicator(
    "A4.code_relay",
    Severity.CRITICAL,
    "Asks the recipient to read back whatever code has just arrived",
    respect_negation=True,
    phrases=[
        "какой код вам пришел",
        "что вам пришло",
        "прочит* смс",
        "прочит* что пришло",
        "продиктуй* что пришло",
        "назов* цифры",
        "read me the code",
        "read out the code",
        "мне пришел код",
        "пришел код перешл*",
        # kk
        *kk("A4.code_relay"),
    ],
)
