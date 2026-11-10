# P06 corpus audit and held-out design — 11 November 2026

Status: **in force as the working policy** since 11 November 2026, with the defaults recorded in section 9. The audit itself changed no code or data. The changes the policy requires are listed in section 10, and the first of them were made the same day.

This record answers three questions from [mini-plan P06](11_CODEX_MINI_PLANS.md): what the corpus contains today, which of it can still serve as a test set (none), and how rows collected from now on get into a test set that the system was not built on.

Counts are from `data/corpus` at commit `41caa9e`, read with the split builder's own loader and grouping (`saqbol.eval.splits`). The offline test suite passed on the same tree.

## 1. Inventory

| | Count | Note |
|---|---|---|
| Rows collected | 126 | Five batches, access dates 8 and 9 September 2026 |
| Phrase fragments | 50 | Cue phrases, not messages. Never enter a split. Scam only: 31 ru, 19 kk |
| Messages | 76 | The only rows that can be annotated and released |
| Scam messages | 59 | 35 ru, 24 kk |
| Legitimate messages | 17 | 13 ru, 4 kk. All are hard negatives; there is no ordinary legitimate row |
| Ambiguous, code-switched, Chinese, English | 0 | |
| Donated | 0 | 42 messages are `press`, 34 `official_warning` |
| Synthetic pilot seeds | 36 | `data/pilot`, constructed for the guideline pilot. Not counted anywhere above and never released |

**Channel.** Of the 59 scam messages, 35 are call scripts, 9 WhatsApp, 6 SMS, 4 email and 5 unknown. Only 19 are text a person receives in writing, which is what the bot and the web app classify. All 17 legitimate rows are notices published on an institution's website.

**Length.** Median 91 characters. 27 of the 76 messages are under 60 characters, mostly single lines from "phrases to watch for" lists.

**Sources.** 35 source URLs on 23 domains. Grouping rows that share a source article, a parallel-pair or variant key, or near-identical text gives **28 source groups**: 16 scam, 12 legitimate, none mixed. The groups are uneven. One has 18 rows (the Ministry of Internal Affairs list of ten phrases, in Russian and in Kazakh), and the five largest hold 42 of the 76 messages.

**Duplicates.** No exact duplicate and no pair at or above the 0.85 similarity threshold among messages. 19 keyed pairs: 15 scam and 4 legitimate; 18 are Russian–Kazakh translations and one is the two-variant fake Kazpost SMS (similarity 0.54, joined by its variant key).

**Collector's doubts.** 12 messages carry `UNSURE` in their notes (10 scam, 2 legitimate). Four are introduced by their article as a typical text and not a captured one.

**Verbatim check.** 64 of the 76 messages were checked against the page's raw HTML. The other 12, all from the first collection session (`official-01` and `press-01`), were not, and that session's fetch tool is known to have altered quoted text.

**Scrubbing.** Every row went through the regex scrubber. Two rows carry placeholders (phone, email), both hard negatives. The second pass the protocol asks for (Presidio) has not run, and there is no record of a person reviewing each row.

**Rights.** Every row rests on the quotation right in Article 19 of the Kazakh copyright law, with the source URL, publisher and access date on the row. No site's terms of use were found and read, and there is no written permission from any publisher. Details in [09_SOURCES.md](09_SOURCES.md).

**Labels.** Every label is the collector's. No row has been annotated by a second person, and `playbook_id` and `stage` are empty on all 76.

**Reuse in the code.** No corpus message appears verbatim in `src`, `tests`, `eval` or `web`. The golden fixtures are constructed text, not copied rows.

## 2. What is exposed

All 76 messages are development data. Three facts make that unavoidable:

- The author read every row of both provisional splits in one error listing before revising the rules ([design decisions, section 4](DESIGN_DECISIONS.md)).
- The effect is measurable. Rules-only flags 12 of 23 scam rows in the old `calibration` file, whose rows justified the phrase changes, and 8 of 36 in the old `test_press` file.
- The provisional split was not a separation in the first place. The builder kept keyed pairs together but not rows from one article, so 6 of the 28 source groups, holding 39 of the 76 rows, sit on both sides.

The marker is the batch: every row in `press-01`, `press-02`, `official-01`, `official-02` and `negatives-01` is in the **dev pool**, permanently. Reshuffling these rows cannot produce a test set. Any number computed on them, including the rules-only recall counts quoted in the design decisions, is a development number and is labelled as one. The files `data/kazscam_v0.1/calibration.jsonl` and `test_press.jsonl` keep their provisional status until they are rebuilt under this policy.

## 3. Pools

| Pool | What is in it | May be used for | May not be used for |
|---|---|---|---|
| `dev` | The 76 exposed messages, plus any later row demoted under section 4 or 8 | Writing rules, lexicons and prompts; the annotation pilot; fitting thresholds; error analysis; seeds for synthetic paraphrases | Any reported test number |
| `calibration` | A slice of fresh rows, cut only when there are enough (section 6) | Fitting fusion weights and thresholds. Reported separately | Rule or prompt changes; test numbers |
| `test_press` | Fresh press and official rows | The headline table | Anything before the system is frozen |
| `test_donated` | Consented submissions reviewed after the freeze | The second table | Same |
| `train_synthetic` | Optional paraphrases, seeded from `dev` rows only | Prompt development | Any reported number |

Fragments stay out of every pool. They remain what they are now: a lexicon source for the rules.

## 4. How a fresh row gets into a test pool

A fresh row is one collected after 11 November 2026. It is clean only if the people and sessions that change the system did not read it before the system was frozen. There are two ways to guarantee that.

**Route A, sealed.** The row is collected before the freeze by someone who does not work on the system: a co-annotator, a data steward, or an assistant session started only for collection. It is stored outside the tracked tree, its hash is committed the same day, and the developer does not open it until the freeze tag exists.

**Route B, after the freeze.** The row is collected by anyone after the tag `system-freeze-v0.1`. Git history proves the order.

A fresh row that fits neither route goes to `dev`. So does a donated row reviewed before the freeze.

### Screening against what is already known

Before a fresh row counts, the collection tooling compares it with every `dev` row and with the fragments:

| Finding | Result |
|---|---|
| Its source URL already has rows in `dev` | Every fresh row from that URL goes to `dev`. The article has been read |
| It shares a parallel-pair or variant key with a `dev` row | That row goes to `dev` |
| Identical normalized text, or similarity of 0.85 or more, with a `dev` row | That row is a duplicate and is dropped |
| Similarity between 0.50 and 0.85 with a `dev` row | The steward decides. A variant of the same message gets the variant key and goes to `dev`; otherwise it stays |

A fresh message that merely contains a known cue phrase stays. Matching known wording in a new message is the generalisation the rules are supposed to show.

### Source groups

Fresh rows are grouped the way section 1 grouped the old ones: same source URL, same key, identical or near-identical text. One original list relayed by two outlets gets one key. A group is assigned to a pool whole.

### Movement is one way

A row can move from `test` to `calibration` to `dev`, never back. If a later batch joins two groups that sit in different pools, the merged group takes the less protected pool.

## 5. Keeping test text out of development

- **Storage.** Route A rows live in `private/holdout/`, which is ignored by git and skipped by code search. Because that folder exists on one machine, the owner keeps a private backup. Route B rows can go straight into `data/corpus/` as ordinary batches.
- **Commitments.** For each Route A batch, `data/holdout/commitments.jsonl` gets one tracked line per row: the SHA-256 of the text, the batch name, the date and who collected it. This shows a reader that the test rows existed, unchanged, before the freeze, without showing the text.
- **Sessions.** A collection session writes to the sealed folder and to the sources document and does not edit `src/`, `tests/`, `eval/` or the playbooks. A development session does not open the sealed folder.
- **Exposure register.** `data/exposure.json` lists the batches and single rows that are development data, and the split builder reads it. Its `log` entries record, with dates, each exposure: who read which rows and why they moved. Any change to rules, lexicons, prompts or playbooks made after the freeze is logged there too, with the `dev` row or provider error that justified it. In a project with one developer this register is the honest substitute for a wall, and the report quotes it.
- **Order of work.** Develop on `dev`. Tag `system-freeze-v0.1`, which pins rules, lexicons, prompts, playbooks and model identifiers. Unseal and annotate. Fit thresholds on the calibration data only. Run the test cells once. Commit `results.json`. Only then read per-row test errors for the report.
- **After the run.** No change to the frozen system under v0.1. A fix ships as a new version, with either a new holdout or a contamination note.

## 6. Calibration and the old 150-row target

The 150-row calibration split in the contract assumed a corpus of 600 to 700 rows. With 76 exposed rows and a nearly exhausted open web, holding 150 fresh rows back from the test set would leave no test set. The target is retired as a fixed number and replaced by two regimes, chosen by the number of fresh, adjudicated press-pool messages, *F*:

| Fresh press pool | Calibration data | Label on the run |
|---|---|---|
| *F* under 250 | The `dev` pool. Every fresh group goes to `test_press` | `dev-calibrated` |
| *F* of 250 or more | A fresh slice of 20% of *F*, between 50 and 75 rows, drawn by source group and stratified by label and language with the builder's seeded draw (seed 20260908, fixed now) | `calibrated` |

Fitting thresholds on `dev` does not touch the test set, so it is clean. Its cost is bias: the rules score better on rows they were written against (section 2), so thresholds fitted there may be too strict for new text. The report says which regime applied. The regime is decided from *F* alone, before any test result exists.

## 7. Minimum support

Nothing is reported from a slice too small to mean anything. The interval widths below come from this project's own bootstrap on simulated predictions (recall 0.6 to 0.85, false-positive rate 0.1).

| Test rows (scam / legit) | Typical 95% half-width of macro-F1 |
|---|---|
| 46 (36 / 10), the provisional size | ±0.11 to ±0.12 |
| 60 (45 / 15) | ±0.10 |
| 100 (70 / 30) | ±0.07 to ±0.08 |
| 200 (140 / 60) | ±0.05 to ±0.06 |
| 300 (210 / 90) | ±0.04 to ±0.05 |

**Release tiers for `test_press`:**

| Tier | Requirement | What may be published |
|---|---|---|
| None | Fewer than 60 rows, or fewer than 20 legitimate | No test number. Development numbers only, labelled |
| Pilot | At least 60 rows, of which at least 20 legitimate | Overall numbers and supported slices. The release and every table are titled "pilot" |
| Benchmark | At least 200 rows, of which at least 60 legitimate and 40 hard negatives; at least 60 rows each in Russian and Kazakh | The full leaderboard |

**Slices.** A language, channel or source slice is reported only with at least 30 rows, and an F1 on it only with at least 10 rows in each class. An unsupported slice is printed with its row count and "not reported". The number of source groups is printed beside every row count, because 76 rows from 28 groups are less evidence than 76 independent rows.

**Hard-negative false positives.** Reported only with at least 30 hard negatives. When the count is zero or equals the total, the percentile bootstrap returns a zero-width interval (0 of 17 gives [0.000, 0.000]), which overstates certainty. In those cases the exact binomial bound is reported instead: 0 of 17 is "at most 16%", 0 of 30 "at most 10%", 0 of 60 "at most 5%" (one-sided, 95%).

**Playbook label.** A per-playbook score needs at least 10 test rows of that playbook. Macro-F1 over playbooks is computed over supported playbooks only, and the unsupported ones are listed. With fewer than five supported playbooks the 13-way macro-F1 is dropped in favour of top-1 playbook accuracy over scam rows.

**Language comparison (H1).** Tested only with at least 50 test rows in each language, and stated "at matched content" only on fresh parallel pairs, of which there are none yet. The 15 scam pairs in the corpus are all exposed.

**Empty and rare classes.**

- `test_donated` with no rows is "unavailable". Its cells are skipped with a reason and never shown as zero errors.
- `ambiguous` rows are released and counted but excluded from the binary metrics, as the harness already does.
- Chinese and code-switched text: zero rows. Both are unsupported in v0.1 and the report says so, including that the three China playbooks are untested on real text.
- Ordinary legitimate messages: zero rows. Until donations exist, "legitimate" in every table means "institutional notice that resembles a scam".

## 8. Contamination recovery

| Event | Response |
|---|---|
| A test row's text is shown in a development session, an error listing or an issue | Its source group moves to `dev`: its ids are added to `data/exposure.json` with a log entry. Affected cells are re-run |
| A rule, lexicon, prompt or playbook changes after the freeze | New system version. The previous test numbers stay attached to the previous version |
| A change is made after test results were inspected | That test set is spent for the new version. It is reported as a development result until a new batch is collected |
| More than 10% of test rows have been demoted | The test set is rebuilt and the dataset version changes |
| A fresh row turns out to duplicate a `dev` row after allocation | That row moves to `dev`. The rest of its group stays |

## 9. Decisions for the owner

1. **Accept that all 76 current messages are development data**, and that the provisional `test_press` file is never cited as a test set.
2. **Choose the route.** Route B needs no one else: freeze, then collect. Route A lets collection start earlier but needs a second person or collection-only sessions, plus a private backup of the sealed folder.
3. **Accept the tiers in section 7**, in particular that a test set under 60 rows publishes no test number and that anything under 200 is called a pilot.
4. **Name a data steward**, if anyone is available. Otherwise the exposure register carries that role and the report says the developer also collected the test rows.

One thing follows from decision 2 that needs no outside help: the rules-only system can be frozen as it stands today. Rows collected after that tag would give a clean rules-only number, even while the model systems wait for provider access.

**Working defaults, 11 November 2026.** Work continued on the choices that cost nothing and need no second person: decision 1 accepted; Route B; the tiers of section 7 as written; no separate data steward. Decisions 1 and 3 are not reversible in any honest way. Decisions 2 and 4 can still change until the freeze tag exists: a volunteer who collects before the tag would make Route A possible for their rows.

## 10. Changes this policy requires

The data contract changes before the code that implements it. The tooling changes were gathered into mini-plan P16 on 11 November 2026, because all of them must exist before the freeze.

| Change | Owner | State |
|---|---|---|
| Contract section 6 and protocol section 7: add the `dev` pool, the source-group leakage rule, and the calibration regimes in place of "150 rows" | P16 | Done 11 November 2026 |
| Split builder and tests: join rows by source URL; route exposed batches to `dev`; never emit them as `test_press`; record the regime in the manifest | P16 | Done 11 November 2026. The rebuilt files hold 76 `dev` rows in 28 groups and no calibration or test rows |
| Seeds for synthetic paraphrases come from `dev` only | P16 | Done 11 November 2026 |
| `tools/collect.py`: screen new rows against `dev` and fragments (section 4) | P16 | Done 11 November 2026. The tool also refuses a new batch before the freeze tag unless it is collected as development data |
| `tools/collect.py`, only if Route A is ever used: write to a chosen directory and write commitments | P09 | Not needed under Route B |
| Exact binomial bound for a false-positive count of zero or all | P16 | Done 11 November 2026 |
| Source-group counts, unsupported-slice rows and the release tier in the leaderboard | P16 | Done 11 November 2026. On the current files the development table prints the overall and Russian macro-F1; the Kazakh slice (28 rows) and the false-positive rate (17 hard negatives) are not reported |
| Per-playbook support floor and the 50-rows-per-language condition on H1 | P12 | Open. No row has a playbook label yet |
| Re-verify the 12 first-session messages against raw HTML; settle the 12 `UNSURE` rows during annotation | P07, P09 | Open |
| Pilot batch: 30 messages drawn from `dev` to replace the synthetic seeds | P07 | Open |
| Second scrub pass and a recorded human review of every released row; written permission requests to the heaviest publishers | P13 | Open |

## 11. Leakage review of this policy

| Path by which test data could shape the system | What closes it |
|---|---|
| The developer reads test rows, then edits rules or prompts | Routes A and B; the freeze tag; the exposure register |
| An assistant session finds test rows while searching the repository | Sealed rows are outside the tracked tree until the freeze |
| A reprint, translation or variant of a known row lands in test | Screening against `dev`; pair and variant keys; the 0.50 to 0.85 manual band |
| Rows from one article on both sides of a split | Source-group assignment |
| Thresholds tuned on test | Calibration data is `dev` or a separate fresh slice; the regime is fixed by row count |
| Picking the split that gives the best number | Seed fixed in this document; one draw at freeze |
| A paraphrase of a test row used in prompt development | Seeds from `dev` only |
| Fixing the system after seeing test errors and re-reporting | Version rule in section 8 |

What the policy does not close:

- **One developer.** If the developer also collects under Route B, cleanliness rests on the freeze tag and the log. This is stated in the report, not hidden.
- **Public text.** Press rows are on the open web and may be in a model's training data. This affects the model rows, not the rules-only row. `test_donated` is the only pool free of it.
- **Selection.** Press-quoted scams are chosen by journalists for being newsworthy, and 35 of the 59 current scam rows are call scripts. A clean test set from the same sources inherits that skew.
- **Annotators.** Co-annotators read test rows. They do not change the system, and their names and roles are recorded.
