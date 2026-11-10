# Rule coverage before the freeze — 11 November 2026

Status: **done on `dev`; the freeze tag does not exist yet.** The tag `system-freeze-v0.1` fixes the rules, the lexicons and the thresholds. After it, a phrase the rules lack stays missing for every reported number. This record covers the last revision of the rules before that point: what the rules missed on `dev`, what was changed, what was left alone, and what the owner still has to decide.

Every figure here is a development number. The rules were revised while looking at these 76 messages, so none of this says how the rules do on messages they were not written against. That is what the test set collected after the tag is for ([P06 record](15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md)).

## 1. What the rules missed

The first threshold fit ([protocol section 7](05_EVAL_PROTOCOL.md)) showed that the misses were a coverage problem. At the 0.40 threshold the rules flagged 20 of the 59 `dev` scam messages. The 39 they missed:

| Rule score | Messages | What it means |
|---|---|---|
| 0 | 15 | No rule fired |
| 12 | 8 | One medium cue |
| 24 | 1 | Two medium cues |
| 25 | 10 | One high-severity cue |
| 37 | 5 | One high-severity and one medium cue |

Reading the 39 gave four causes.

- **Words inside a phrase.** A phrase matched only when its words stood next to each other. "Назовите мне, пожалуйста, код" and "проголосуй, пожалуйста, за Настю" are the same requests as the two-word forms and did not match.
- **Quotation marks.** The press quotes the safe-account script as «безопасный» счёт or “защищённый” счёт. The quotation marks broke the phrase.
- **Missing forms.** "Заблокирована" is five letters past the stem `заблокир`, one more than `*` allows, so "ваша карта заблокирована" matched nothing. "Подозрительные транзакции", "Почта Казахстана" and "не может быть доставлена" were absent, with their Kazakh counterparts.
- **Pairs that are a script.** A prize with a fee, and a relative in trouble who needs money now, each fired two rules and scored 37, three points under the threshold. No combination covered them.

The rest are one-line fragments quoted in articles, where one cue is all the text holds. Section 4 is about those.

## 2. What changed

**The phrase matcher** (`core/indicators/registry.py`, syntax in [03_INDICATORS.md](03_INDICATORS.md)):

- Quotation marks around a word no longer break a phrase.
- A new operator, `~`, written between two words, allows up to two other words between them, with commas, dashes and quotation marks. It stays on one line and inside one sentence. Digits are not words, so a phrase cannot reach across a code or an amount.

**Phrases.**

| Indicator | Added or changed | Why |
|---|---|---|
| A1 code request, Russian | `назов* ~ код`, `продиктуй* ~ код`, `скаж* ~ код`, `сообщите ~ код`, `перешлите ~ код`; and the code named first: `код ~ назовите`, `код ~ продиктуйте`, `код ~ сообщите`, `код ~ скажите` | Polite and indirect wording. The gap goes only to forms that cannot be a noun or a participle: `сообщ* ~ код` would match "в сообщении указан код", which genuine messages say |
| B2 account block | `счет заблокирован*`, `карта заблокирован*`, `карточк* заблокирован*` | The commonest form was out of reach of the stem |
| B4 money at risk | `подозрительн* транзакци*`; Kazakh `күмәнді транзакция*` | Absent |
| C6 courier or post | `почта казахстана`, `не может быть доставлен*`; Kazakh `қазақстан пошта*`, `жеткізу мүмкін емес` | The parcel SMS as published |
| E2 transfer to a person | `переведите ~ на ~ счет*` | "Переведите их на другой счёт" |
| J3 hijacked account | `проголосуй* за` became `проголосуй* ~ за` | "Проголосуй, пожалуйста, за" |

Kazakh has no phrase with `~`, and family A must never get one. Kazakh negates with a verb suffix, so a gap would let a request verb reach "код" across the words that negate it. The note is in the lexicon header.

**Two combinations** (`core/fuse.py`), 10 points each:

| Combination | Fires when | Reason |
|---|---|---|
| `prize_with_fee` | H3 unsolicited prize and E7 upfront fee | A prize that has to be paid for is the advance-fee pattern |
| `known_contact_under_pressure` | J2 relative in trouble or J3 hijacked-account ask, and B1 urgency | A known contact who needs money now is the hijacked-account script |

**One regression case.** `pickup_code_told_to_staff`, a parcel notice that states its own pickup code and says to give it to the staff of the pickup point. It must stay likely safe and must not fire family A. It guards the phrases where the code is named first.

**Tests.** The matcher's new syntax, including where a gap must stop; each new phrase on a positive example; a list of messages that carry or mention a code without asking for one; the two combinations.

## 3. Effect on `dev`

| | Before | After |
|---|---|---|
| Scam messages flagged at 0.40 | 20 of 59 | 25 of 59 |
| Scam messages where no rule fires | 15 | 7 |
| Hard negatives flagged | 0 of 17 | 0 of 17 |
| Hard negatives with any rule score | 0 | 0 |
| Macro-F1 at 0.40 | 0.486 | 0.548 |
| Regression suite | 77 cases, all hold | 78 cases, all hold |
| Scam source groups with at least one message flagged | 8 of 16 | 8 of 16 |

The last row is the honest size of the gain. The five newly flagged messages come from three articles, and each of those articles already had a flagged message. By article, nothing moved.

The five: "ваша карточка заблокирована … указан код, назовите его" (0 to 52), "нужно перевести деньги на “защищённый” счёт" (0 to 40), and three that the combinations lift from 37 to 47: "мама, срочно, я в больнице", "ваш родственник в беде! Срочно нужны деньги!" and "вы выиграли приз! Оплатите налог / доставку". Seven more messages gained a cue and stay under the threshold, and one that was already flagged gained one.

The threshold fit was run again on the revised rules. The `suspicious` threshold stays at 0.40. The best candidate is still 0.37, now worth +0.024 macro-F1 with an interval of 0.000 to 0.050: two more messages, both from one article. The table is in [protocol section 7](05_EVAL_PROTOCOL.md) and the artifact is `eval/calibration/rules_only.json`.

## 4. What still misses, and why it was left

34 of the 59 scam messages stay under the threshold: 19 of the 35 Russian ones and 15 of the 24 Kazakh ones.

| Rule score | Messages |
|---|---|
| 0 | 7 |
| 12, one medium cue | 11 |
| 24, two medium cues | 2 |
| 25, one high-severity cue | 12 |
| 37, one high-severity and one medium cue | 2 |

**One high-severity cue never warns (12 messages).** "Не сообщайте никому о нашем разговоре", "следуйте нашим инструкциям и не отключайте телефон", "чтобы сохранить деньги, переведите их на другой счёт": each fires one high-severity rule, scores 25 and comes out likely safe. A threshold of 0.25 would reach them and is ruled out by the regression suite: a genuine eGov code SMS fires one high-severity rule too. The other route is to regrade some indicators, for example secrecy and "do not hang up" from high to critical. That was not done. `dev` cannot test it: its 17 legitimate messages are announcements that fire no rule at all, so any regrade looks free on `dev`. It is a design decision for the owner, and the evidence for it would be genuine messages of the hard kind, which the fresh collection is meant to find.

**Parcel phishing with the link removed (4 messages).** The published examples of the parcel SMS say "confirm your address at the link below", and the link itself is cut out. What is left is "your parcel cannot be delivered, confirm your address", which a genuine notice also says. These score 0 to 24. The link rules have nothing to read, and a rule for the words "at the link below" would fire on real post-office messages.

**A Kazakh code request spread over several words (1 message).** Left alone because of the suffix negation described above.

**No cue at all (7 messages).** "Сіздің кредит алғыңыз келгені рас па?" and "Депозиттегі қаражатты банк шотына аудару қажет" are examples. Nothing in the words separates them from a real bank's sentence. The article around them says they are scam lines; the text alone does not. These are for the model judgement, or they are the cases where the right answer is "not sure".

## 5. Costs accepted

- **A genuine handover instruction worded as a request is flagged.** "Назовите код курьеру при получении" fired the code-request rule before this revision and still does (score 40, "suspicious"). The gap widens it to "назовите курьеру код 4821". The regression case in section 2 covers only the wording where the code comes first. Exempting "курьеру" is not safe either: posing as a courier and asking for the code from an SMS is a known script.
- **A real relative writing in a hurry is flagged.** "Мама, срочно, я в больнице" scores 47 whoever sent it. The advice attached to that warning is to call the person back on a known number, which is the right advice in both cases.
- **The Kazakh additions are unreviewed.** `күмәнді транзакция*` and `жеткізу мүмкін емес` are taken as written from published warnings and marked `VERIFY-kk` in the lexicon for a native speaker.

## 6. Open, for the owner

| Question | Why it cannot be settled here |
|---|---|
| Should one high-severity cue be enough for a warning, by regrading secrecy, "do not hang up" or others to critical? | `dev` has no legitimate message that fires a rule, so it cannot show the cost |
| Is "suspicious" on a courier handover instruction acceptable? | It trades a false warning on a common genuine message against a known scam script |
| Native-speaker check of the two `VERIFY-kk` phrases | Needs a native speaker |
| The 5% cap, the 0.80 floor and the incumbent rule of the threshold fit | Unchanged from the first fit; they are fixed by the tag |

All four are cheaper to settle before the tag than after it.

## 7. How to reproduce

```bash
python -m saqbol.eval calibrate --config eval/configs/dev.yaml
python -m pytest
```

The first command rewrites `eval/calibration/rules_only.json`; a test fails when the committed file differs from a fresh fit. On this date: 1,573 tests pass, 22 are skipped and 2 are expected failures.
