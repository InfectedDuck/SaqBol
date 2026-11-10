# SaqBol — Indicator catalogue

The deterministic layer. These are **detection patterns applied to a message the user received**, so they can be warned. Each is a pure function from normalized text plus extracted entities to zero or more `IndicatorHit`s with evidence spans.

This layer is the `rules_only` row on the leaderboard. It must work with no network and no LLM.

## Conventions

- ID format `<family><n>.<slug>`, stable forever. Once published in a dataset or a paper, an ID never changes meaning.
- Weights come from `Severity` (critical 40, high 25, medium 12, low 5). Cap the sum at 100 before normalizing.
- Every hit carries at least one evidence span, except metadata indicators (family I) which carry a `detail` dict instead.
- Russian patterns below are drawn from published Kazakh police and bank warnings and from press coverage. **Kazakh patterns are drafts. Toktar must verify and expand every `kk` line before week 3.** Mark unverified entries with `# TODO-kk` in code so a grep finds them.
- Match case-insensitively on the NFKC-normalized, zero-width-stripped string. Use word-boundary-aware regex, not naive substring, or "код" will match inside "кодекс".
- Phrase syntax. Words of a phrase must be adjacent, separated by whitespace; quotation marks around a word do not break the phrase, so `защищенн* счет*` matches «защищённый» счёт. A trailing `*` allows up to four more letters. A `~` between two words allows up to two other words and commas between them, within one sentence: `назов* ~ код` matches `назовите мне, пожалуйста, код`. Use `~` only where both words are specific; a loose pair is a false positive on a genuine message.

---

## Family A — Credential and secret extraction

The single strongest signal set. No legitimate institution asks for these.

| ID | Severity | What it detects | Draft patterns |
|---|---|---|---|
| `A1.otp_request` | critical | Asking for an SMS/one-time code | ru: `код из СМС`, `назовите код`, `продиктуйте код`, `код подтверждения`, `шестизначный код`<br>kk: `СМС код`, `кодты айтыңыз` `# TODO-kk`<br>en: `the code we sent`, `verification code`<br>zh: `验证码` |
| `A2.card_secrets` | critical | Full PAN, CVV, expiry, or PIN requested | ru: `три цифры на обороте`, `CVV`, `ПИН-код`, `полный номер карты`<br>zh: `卡号`, `密码` |
| `A3.password_request` | critical | Account password or bank-app login | ru: `логин и пароль`, `пароль от приложения` |
| `A4.code_relay` | critical | Asking the victim to read back a code that just arrived | ru: `какой код вам пришёл`, `прочитайте что пришло` |

Note the inversion trap: a **legitimate** bank SMS contains "никому не сообщайте код" (never share this code). Detect the *request* for a code, not the mention of a code. Both must appear in the hard-negative set, and `test_indicators.py` must include a legitimate Kaspi OTP SMS asserting zero A-family hits.

---

## Family B — Urgency and fear

| ID | Severity | Detects | Draft patterns |
|---|---|---|---|
| `B1.urgency` | medium | Artificial time pressure | ru: `срочно`, `немедленно`, `в течение \d+ минут`, `иначе будет поздно`<br>kk: `жедел`, `шұғыл` `# TODO-kk`<br>zh: `马上`, `立即` |
| `B2.account_block_threat` | medium | Threat to freeze or lose the account | ru: `счёт будет заблокирован`, `карта заблокирована` |
| `B3.criminal_threat` | high | Threat of prosecution or arrest | ru: `уголовное дело`, `статья УК`, `вас объявят в розыск`, `следователь`<br>zh: `涉嫌洗钱`, `刑事`, `通缉` |
| `B4.money_at_risk` | medium | Claim that funds are being stolen right now | ru: `пытаются списать`, `подозрительная операция`, `несанкционированный вход` |

`B4` overlaps heavily with real bank alerts. That is deliberate: it must be weak on its own and only matter in combination. Verify on hard negatives.

---

## Family C — Authority impersonation

| ID | Severity | Detects |
|---|---|---|
| `C1.bank_security` | high | Claims to be a bank security department. ru: `служба безопасности банка`, `отдел по борьбе с мошенничеством`; kk: `банк қауіпсіздік қызметі` `# TODO-kk` |
| `C2.police_prosecutor` | high | Police, prosecutor, KNB, financial monitoring. ru: `полиция`, `прокуратура`, `финмониторинг`, `АФМ`; zh: `公安局`, `检察院`, `警官` |
| `C3.egov_1414` | high | Claims to be eGov or 1414 |
| `C4.national_bank` | high | Claims to be the National Bank of Kazakhstan |
| `C5.embassy_immigration` | high | Embassy, consulate, immigration, visa office (China mode). zh: `大使馆`, `出入境`, `签证` |
| `C6.courier_post` | medium | Kazpost, delivery service, customs holding a parcel |
| `C7.telecom` | medium | Mobile operator threatening to disconnect a number |

Combine with family I. A caller claiming to be a bank from a `+44` number is a much stronger signal than either fact alone. Implement that as a **combination rule** in `fuse.py`, not by inflating a single weight.

---

## Family D — Channel migration

| ID | Severity | Detects |
|---|---|---|
| `D1.move_to_messenger` | medium | Pushing a phone call or marketplace chat into WhatsApp or Telegram. ru: `напишите мне в WhatsApp`, `переходите в телеграм` |
| `D2.leave_platform` | medium | Leaving OLX, Instagram, or a marketplace to "finish the deal" |
| `D3.dont_hang_up` | high | ru: `не кладите трубку`, `оставайтесь на линии`. Isolating the victim from a second opinion. |

---

## Family E — Money movement

| ID | Severity | Detects |
|---|---|---|
| `E1.safe_account` | critical | The "safe account" fiction. ru: `безопасный счёт`, `резервный счёт`, `страховой счёт`; zh: `安全账户` |
| `E2.transfer_to_person` | high | Transfer to a personal card "for verification" |
| `E3.take_a_loan` | critical | Instructing the victim to take out a loan. ru: `оформите кредит`, `подтвердите заявку на кредит` |
| `E4.crypto_address` | high | A wallet address present in an unsolicited message |
| `E5.mule_recruitment` | critical | Renting the victim's card or account. ru: `сдать карту в аренду`, `нужен ваш Kaspi`, `дропы` |
| `E6.guarantee_deposit` | critical | Pay a deposit to prove innocence (China fake-police pattern). zh: `保证金` |
| `E7.upfront_fee` | high | Pay first to receive a prize, job, loan, or refund |

---

## Family F — Software installation

| ID | Severity | Detects |
|---|---|---|
| `F1.remote_access_app` | critical | AnyDesk, TeamViewer, RustDesk, QuickSupport, AirDroid mentioned in an unsolicited context |
| `F2.apk_attachment` | critical | `.apk` file or a link ending in `.apk` |
| `F3.install_instruction` | high | ru: `установите приложение`, `скачайте по ссылке`, combined with a claimed institution |
| `F4.disable_protection` | high | Asking to disable Play Protect or grant accessibility permissions |

---

## Family G — Link and domain risk

Implemented in `url_analyzer.py`. **All network calls sandboxed**: `HEAD` only, no cookies, no JS, 3-second timeout, maximum 5 redirects, private IP ranges refused, and a hard allowlist of schemes.

| ID | Severity | Detects |
|---|---|---|
| `G1.lookalike_domain` | high | Damerau-Levenshtein ≤ 2 against a ~60-entry brand list, or Unicode-confusable skeleton match. `detail: {lookalike_of, distance, method}` |
| `G2.punycode_idn` | high | `xn--` in the host |
| `G3.shortener` | medium | Known shortener host (`bit.ly`, `clck.ru`, `t.me/+`, `is.gd`, `vk.cc`, `goo.su`) |
| `G4.long_redirect_chain` | medium | More than 2 hops to the final host |
| `G5.brand_mismatch` | high | The **host** carries a brand's name while its registrable domain belongs to someone else, as in `kaspi-secure.ru`. `detail: {host, claims, registrable}` |
| `G6.fresh_domain` | low | Registration under 90 days, supplied through `metadata["domain_ages"]` |
| `G7.qr_payload_risk` | high | Decoded QR contains a URL or payment payload that trips any other G rule |
| `G8.ip_url` | medium | Bare IP address in place of a hostname |

Brand list lives in `src/saqbol/core/data/brands.yaml`, each entry carrying the written forms a message uses and every domain the brand legitimately sends from.

**Verify every `domains` entry before release.** A wrong official domain makes G5 flag a real bank link, which is a false positive on the most important negative class in the corpus. When unsure, drop the brand: a missing brand costs recall, a wrong one costs precision on legitimate messages.

Two rules in this family read facts the message text cannot carry, exactly as family I does, and stay silent when no enrichment step has supplied them:

| Rule | Metadata key | Shape |
|---|---|---|
| `G4.long_redirect_chain` | `redirect_chains` | `{url: [hop, hop, …]}` |
| `G6.fresh_domain` | `domain_ages` | `{registrable_domain: days}` |

Live resolution is opt-in per call through `metadata["resolve_links"]`, so the default path and the `rules_only` baseline never touch the network.

### G5 is keyed on the host, not on the message

The catalogue's first draft fired G5 when the message named a brand and linked anywhere unofficial. That flags a genuine bank message that also links to a survey. Keying on the host instead means the rule fires on `kaspi-secure.ru` and stays quiet when a real Kaspi message links to `forms.gle`. It is the tighter rule and it catches the shape a lookalike check structurally cannot: `kaspi-secure.ru` is seven edits from `kaspi.kz`, so G1 never sees it.

---

## Family H — Offers too good to be true

| ID | Severity | Detects |
|---|---|---|
| `H1.guaranteed_returns` | high | ru: `гарантированный доход`, `\d+% в месяц`, `без риска` |
| `H2.celebrity_investment` | high | A public figure's name plus an investment pitch. The deepfake-ad funnel. |
| `H3.unsolicited_prize` | medium | ru: `вы выиграли`, `вам положена выплата`, `компенсация` |
| `H4.easy_job` | medium | High pay, no experience, work from a phone. ru: `работа в телеграм`, `от 300 000 тг`; zh: `刷单`, `日结` |
| `H5.romance_to_investment` | high | Extended friendly rapport pivoting to a trading platform |

---

## Family I — Contact metadata anomalies

No text spans. These populate `detail`.

| ID | Severity | Detects |
|---|---|---|
| `I1.foreign_number_local_claim` | high | Country code outside `+7` while claiming a Kazakhstani institution |
| `I2.spoofed_short_code` | high | An 11-digit number presented as a bank's 4-digit short code |
| `I3.new_telegram_account` | medium | Forwarded message from an account with no username, default name, or recent creation |
| `I4.relative_new_number` | medium | Claims to be a relative while writing from an unknown number |

Family I only applies when the surface supplies metadata. Telegram forwards do; a pasted screenshot mostly does not. Return nothing rather than guessing.

---

## Family J — Social engineering context

| ID | Severity | Detects |
|---|---|---|
| `J1.secrecy` | high | ru: `никому не говорите`, `это тайна следствия`, `не сообщайте родственникам` |
| `J2.relative_in_trouble` | high | Accident, hospital, police, needs money now |
| `J3.hijacked_account_ask` | high | A known contact asking for an urgent transfer, especially with a changed writing style |
| `J4.script_handoff` | medium | ru: `сейчас переключу на специалиста`, `с вами свяжется` |

---

## Combination rules

Applied in `fuse.py` after individual scoring. Each adds a flat bonus, capped so the total cannot exceed 100.

| Rule | Bonus | Reason |
|---|---|---|
| Family C hit **and** family A hit | +20 | Impersonation plus credential request is the core of the bank-security script |
| Family C hit **and** family I hit | +15 | Claimed institution contradicted by the contact metadata |
| `E1.safe_account` **and** any B-family hit | +15 | The safe-account fiction only works under pressure |
| `F1` or `F2` **and** any C-family hit | +20 | Remote access plus claimed authority is near-conclusive |
| Any G-family hit **and** `C6.courier_post` | +10 | The delivery-link pattern |
| `H3.unsolicited_prize` **and** `E7.upfront_fee` | +10 | A prize that has to be paid for is the advance-fee pattern |
| `J2.relative_in_trouble` or `J3.hijacked_account_ask` **and** `B1.urgency` | +10 | A known contact in trouble who needs money now is the hijacked-account script. A real relative can write the same words, which is why the result is a warning to call them back and not a scam verdict |

---

## Testing requirements

`tests/test_indicators.py` must contain, at minimum:

1. One positive fixture per indicator ID, asserting the ID fires and the span text is correct.
2. **Negative fixtures that must produce zero hits from the named family**:
   - a genuine Kaspi OTP SMS (contains a code, must not fire family A)
   - a genuine Kazpost tracking SMS with a real tracking link (must not fire G1 or G5)
   - a genuine Halyk suspicious-login alert (mentions a suspicious operation, must not fire B4 alone above threshold)
   - a real eGov 1414 notification
   - a normal OLX buyer conversation
3. A property test asserting `normalized[span.start:span.end] == span.text` for every hit produced across all fixtures.
4. A test asserting every indicator ID referenced by any playbook's `expected_indicators` exists in the registry.

Point 2 is the one that matters. It is easy to build a detector that flags everything. The hard-negative false-positive rate is a headline metric precisely because it is where naive systems collapse.
