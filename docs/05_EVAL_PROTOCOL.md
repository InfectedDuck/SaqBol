# SaqBol — Dataset and evaluation protocol

This is the part that turns a useful bot into a research artifact. It is also the part a sceptical reader will attack first, so it has to be defensible before it is impressive.

**Pre-register the hypothesis before you look at results.** Commit this section to git at the start of week 3, with a timestamp.

> H1: Frontier LLMs achieve lower macro-F1 on Kazakh scam messages than on Russian ones, at matched content.
> H2: A hybrid rules-plus-grounded-LLM system achieves a lower false-positive rate on hard negatives than an LLM alone at matched recall.
> H3: Performance drop under cue-masking is larger for the LLM-only system than for the hybrid, indicating the LLM leans on surface brand cues.

If H1 turns out false, **that is a publishable result and you report it as such**. The mechanism questions (H2, H3) are more interesting anyway and do not depend on H1's direction. Say this in the report. A null result reported honestly is worth more than numbers that conveniently match the pitch.

---

## 1. Dataset targets for KazScam v0.1

| Category | Target rows | Source |
|---|---|---|
| Scam, Russian | 200–260 | Public police and bank warnings, press articles, public awareness channels |
| Scam, Kazakh | as many as honestly exist, likely 60–120 | Same, plus Kazakh-language sources |
| Scam, code-switched | 40–80 | Naturally occurring, flagged `is_code_switched` |
| Legitimate, ordinary | 180–220 | Real bank, delivery, and marketplace messages, donated with consent |
| Legitimate, **hard negatives** | 100–140 | Real 1414 codes, Kazpost tracking, Kaspi promos, Halyk login alerts, genuine OLX chats |
| **Total released** | **≈ 600–700** | |
| Synthetic paraphrases | 400–800 | Train and prompt-development split only, never reported |

Do not pad Kazakh with translations to hit a quota. The Kazakh share is whatever the data honestly contains, and the ablation runs only on genuinely Kazakh items. A forced quota is the first thing a reviewer detects and it invalidates H1.

**Provenance is mandatory.** Every `source: press` row carries a `source_url`. A dataset without provenance cannot be released and cannot be defended.

---

## 2. Collection procedure

1. **Press and official sources.** Work through published warnings from the Ministry of Internal Affairs, the National Bank, the Financial Monitoring Agency, bank security pages, and awareness channels. Copy the scam text verbatim where it is quoted. Log the URL and the access date for each row.
2. **Donated.** Bot users who tick the per-submission consent box. These land in `dataset_candidates` with `status = pending`, never straight into the dataset.
3. **Hard negatives.** Ask friends and family to forward genuine messages from banks, delivery services, and eGov. This is the most under-collected and most valuable category. Start it in week 1, not week 3.
4. **Synthetic.** LLM paraphrases of `dev` rows, recorded with the seed row's ID so leakage checks can trace them. Train split only.

### PII scrubbing

Run before any human sees a row, and again before release.

- Regex first: phone numbers, national ID numbers, card numbers, emails, messenger handles, full names where detectable.
- Presidio second, as a safety net.
- Replace with typed placeholders (`<PHONE>`, `<IIN>`, `<CARD>`, `<NAME>`) so the text stays linguistically usable.
- Keep amounts and institution names. They are semantic content, not PII.
- Record which scrubbers fired in `scrub_applied`.
- **Human review of every released row.** Roughly 700 rows at a few seconds each is a two-hour job. Do not skip it.

---

## 3. Annotation

Three annotators: Toktar plus two Kazakh-speaking co-annotators. Recruit them on day 0, because this is the only task with an external dependency on other people's calendars.

**Guideline** (`docs/ANNOTATION_GUIDELINE.md`, two pages):

- Label set and one worked example per playbook.
- The decision rule for `ambiguous` and for `other_scam`.
- The rule for `stage`, which is only labelled on multi-message threads.
- Five hard cases with the correct answer and the reasoning, chosen from the pilot.

**Procedure**:

1. Pilot on 30 items. Compute agreement. Revise the guideline. **Keep the pre-revision and post-revision numbers**, since guideline improvement is itself a reportable result.
2. Double-annotate 100 percent of the released rows.
3. Report Cohen's kappa overall and **per class**. Per-class kappa is what shows which playbooks are genuinely confusable, and confusable pairs are the most interesting paragraph in the report.
4. Adjudicate every disagreement, with a third annotator or by discussion. Log the adjudication with a one-line reason.
5. Publish the guideline alongside the dataset.

Expect low kappa on `kz.bank_security_call` versus `kz.remote_access_loan`, since one often becomes the other. Do not hide it. Explain it as a property of the domain and consider whether they should be merged in v0.2.

---

## 4. Systems compared

| System | Definition |
|---|---|
| `rules_only` | Indicator engine plus thresholds. No LLM, no network. |
| `llm_zeroshot` | The message and the label set, no playbook context, no rules. |
| `hybrid` | The full pipeline: rules, retrieved playbooks, LLM, fusion, abstention. |

Models on the leaderboard: DeepSeek-V3, Qwen3, GPT-4o-mini, Llama-3.3-70B. Fixed temperature 0, fixed prompt version, prompt hash recorded in `results.json`.

`rules_only` is not a formality. If the hybrid does not clearly beat it, the honest conclusion is that the LLM adds little, and reporting that is more valuable than hiding it.

---

## 5. Metrics

| Metric | Definition | Why |
|---|---|---|
| Macro-F1 | Over `scam` / `legit`, and separately over the 13-way playbook label | Headline |
| 95% CI | Bootstrap, 10,000 resamples, stratified by class | No number ships without one |
| FPR on hard negatives | False positives divided by hard-negative count. When none or all of them are flagged, the bootstrap interval has no width, so the exact one-sided binomial bound is reported instead and marked in the table | The metric that decides whether people uninstall |
| Abstention coverage | Share not answered `unsure` | |
| Risk at coverage | Error rate among answered items, plotted against coverage | Proves abstention buys something |
| Stage accuracy | Threads only | Secondary |

**Reporting rule**: no claim that one system beats another unless the 95% confidence intervals do not overlap. Put that sentence in the README and in the report. It is a small sentence that signals a great deal.

---

## 6. Ablations

Each is one cell in the results table. All run on the same test rows.

| Ablation | Manipulation | Question |
|---|---|---|
| `none` | Baseline | |
| `translated` | 100–150 items human-translated Kazakh to Russian and back by co-annotators | Is the Kazakh gap linguistic, or is it a content difference between what circulates in each language? |
| `cue_masked` | Brand names, short codes, and numbers replaced with typed placeholders | Does the model reason about structure, or pattern-match on "Kaspi"? |
| `no_playbook_context` | Retrieval disabled, otherwise identical | What does grounding actually contribute? |

`translated` is the ablation that makes H1 meaningful. Without it, a Kazakh-versus-Russian gap is confounded with the fact that different scams circulate in each language. Human translation by the co-annotators, not machine translation, or the ablation measures the translator.

`cue_masked` is the most likely source of the report's genuinely novel finding. Prioritize it if time runs short.

---

## 7. Calibration

Calibration data is **disjoint from every test split** and is used to fit:

- the three fusion weights
- the band thresholds
- the disagreement and self-consistency thresholds for abstention

Which rows it is depends on how many fresh press rows exist when collection ends. A fresh row is one collected after the system freeze and never seen during development ([contract section 6](02_DATA_CONTRACTS.md), [holdout policy](15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md)).

| Fresh press rows | Calibration data | Label on the run |
|---|---|---|
| Under 250 | The `dev` split. Every fresh row is a test row | `dev-calibrated` |
| 250 or more | A stratified slice of the fresh rows: 20% of them, between 50 and 75 | `calibrated` |

The regime follows from the row count alone and is fixed before any test result exists. The report says which one applied. Thresholds fitted on `dev` lean towards text the rules were written against, and the report says that beside the number. The earlier fixed target of 150 calibration rows assumed a corpus of 600 to 700 rows and is retired.

Report calibration and `dev` numbers separately and label them as such. Tuning on test and reporting it as test is the most common way an evaluation loses credibility.

Say "thresholded abstention". Only call it conformal prediction if you actually report coverage guarantees and set sizes.

### The fit

`python -m saqbol.eval calibrate --config eval/configs/dev.yaml` runs the fit and writes `eval/calibration/rules_only.json`. It reads the `calibration` split when that has rows and `dev` otherwise, and refuses any other split.

**What is searched.** For the rules-only system only one parameter can be fitted: the `suspicious` threshold, which separates a warning from "likely safe". The candidates are 0.01 to 0.40, one per rule-score point. The ceiling is fixed by design: one critical indicator is worth 40 points and must never come out as likely safe. The `scam` threshold is not fitted, because the scoring counts `scam` and `suspicious` as the same positive answer and no gold label says which band a scam deserves. The fusion weights and the two abstention thresholds have no effect until a model runs, so they wait for the hybrid system.

**Objective.** Take the candidate with the highest macro-F1 over scam and legit among the admissible ones. A candidate is admissible when all three hold:

| Constraint | Value | Why |
|---|---|---|
| Hard-negative false positives | at most 5% of the hard negatives in the calibration data | A warning on a genuine bank or eGov message is the costly error |
| Coverage | at least 0.80 of rows answered | Abstaining on everything must not win. The rules alone never abstain, so this binds only for model systems |
| Regression suite | every case in `tests/fixtures/golden` keeps a band it allows | The `dev` hard negatives all score zero, because the rules were written against them. The suite holds the genuine messages that carry one real cue |

Ties go to the higher threshold, which warns less.

**The incumbent rule.** The current threshold is replaced only when the 95% interval of the paired macro-F1 gain lies above zero. The interval resamples source groups, not rows, so several quotes from one article count as one piece of evidence. The same rule applies when thresholds are refitted on a fresh calibration slice.

**What the fit on `dev` found** (11 November 2026, after the [phrase revision of that day](18_PRE_FREEZE_RULE_COVERAGE_2026-11-11.md): 76 rows in 28 source groups, 17 hard negatives, 78 suite cases):

| `suspicious` | Macro-F1 | Scams flagged | Hard negatives flagged | Suite cases broken | Admissible |
|---|---|---|---|---|---|
| 0.01 to 0.12 | 0.883 | 52 of 59 | 0 of 17 | 2 | no |
| 0.13 to 0.24 | 0.737 | 41 of 59 | 0 of 17 | 1 | no |
| 0.25 | 0.713 | 39 of 59 | 0 of 17 | 1 | no |
| 0.26 to 0.37 | 0.572 | 27 of 59 | 0 of 17 | 0 | yes |
| 0.38 to 0.40 | 0.548 | 25 of 59 | 0 of 17 | 0 | yes |

The best admissible candidate is 0.37. Its gain over 0.40 is +0.024 macro-F1, and the interval of that gain over source groups is 0.000 to 0.050. The two extra scam rows come from one article. The interval reaches zero, so the threshold stays at 0.40. The first fit of the day, before the phrase revision, gave the same answer: 0.37 was the best candidate at +0.062, interval 0.000 to 0.111, and 0.40 scored 0.486 with 20 of 59 flagged. The artifact records 0.37 as the best candidate by the objective, with the whole search.

The 5% cap, the 0.80 floor and the incumbent rule are choices, and they can be changed until the tag `system-freeze-v0.1` exists. After it they are fixed.

**The artifact** holds the selected thresholds, all 40 candidates with their counts, the objective, the comparison with its interval, digests of the calibration rows and the suite cases, the config hash, the seed, the playbook version, the code revision and the regime. A test reruns the fit and fails when the committed artifact differs from it, or when the pipeline defaults differ from the selected thresholds. Each run manifest records the weights and thresholds in force under `fusion`.

---

## 8. Reproducibility

- `python -m saqbol.eval run --config eval/configs/v0.1.yaml` reproduces every reported number. `eval/configs/dev.yaml` runs the same harness on the `dev` split for development numbers, which the leaderboard marks as not test results.
- `results.json` is committed, and `leaderboard.md` is generated from it and never hand-edited.
- `results.json` holds every number the harness computed, with the row, class, hard-negative and source-group counts behind it. The leaderboard prints a number only when those counts clear the minimum-support floors, prints "not reported" otherwise, and states the release tier (none, pilot, benchmark) in its header. The tier is none, whatever the size of the split, while any `test_press` row lacks two annotators' readings: a row nobody annotated carries its collector's label, which is the thing annotation exists to check. The floors are in `src/saqbol/eval/support.py` and their reasoning is in [15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md](15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md) section 7.
- The prompt is versioned and its hash is recorded per row.
- LLM responses are cached to disk by (model, prompt hash, input hash), so a rerun costs nothing and the exact responses behind a published number are inspectable.
- CI runs the harness over 30 fixture rows using recorded cassettes, so the pipeline is proven to work on every commit without spending money.

**Leakage tests in CI**: no `text_sha256` in two splits, no synthetic row derived from a test row, calibration disjoint from test, no source article and no near-duplicate pair in two splits, and no row from the exposure register (`data/exposure.json`) outside `dev`. Make them fail the build.

---

## 9. Release checklist for the dataset

- [ ] JSONL per split, plus a loading script
- [ ] `DATASHEET.md` following Datasheets for Datasets: motivation, composition, collection, preprocessing, uses, distribution, maintenance
- [ ] Annotation guideline included
- [ ] Per-class kappa table included
- [ ] Provenance column populated on every press row
- [ ] Licence chosen and stated, with a clear note on the press-quoted rows
- [ ] Ethics section: consent flow, scrubbing procedure, dual-use consideration and why release is net positive
- [ ] Limitations section, written honestly: size, regional and temporal scope, class imbalance, the fact that press-quoted scams are pre-filtered by newsworthiness
- [ ] Reviewed by one external Kazakh NLP researcher before release, with the request sent in week 3

The limitations section is not a weakness. Readers want to know whether the author understands the artifact's boundaries, and stating them first is what makes the rest believable.
