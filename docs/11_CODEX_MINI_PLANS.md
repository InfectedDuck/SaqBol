# SaqBol — Codex mini-plans

Use with [the remaining roadmap](10_REMAINING_ROADMAP.md). Written 15 September 2026; states, order and budget notes revised 11 November 2026. Tasks are proposals; none is marked complete merely because this file exists.

The mini-plans keep their numbers but no longer run in number order. The current order is P16, P05, P11, then P07 and P08 side by side, P09, P10, P12, P13, P14, with P15 ongoing. The roadmap explains why the freeze (P11) now comes before collection (P09). Every step has a route that costs nothing; see the roadmap's budget section before any step that could spend money.

## Model selection

The following assignments are project-specific recommendations based on the [official Codex model guidance](https://learn.chatgpt.com/docs/models), checked September 15 and not re-checked since. Any capable coding assistant can run a mini-plan; the model names are a guide to how hard each task is, not a requirement. Terra fits everyday implementation; Sol fits complex changes and reviews; Luna fits precise repetitive work; Astra fits the hardest end-to-end reasoning. Start with the lowest effort that passes the task's checks. Model access and effort options depend on your account/client.

| Preferred model | Suggested effort | Use here |
|---|---|---|
| `gpt-5.6-terra` | medium | Default for bounded implementation and integration |
| `gpt-5.6-sol` | high | Privacy, deployment, annotation design and evaluation correctness |
| `gpt-5.6-luna` | low | Formatting, metadata checks and documentation assembly under a fixed specification |
| `gpt-6-astra` | high | Escalation for unresolved cross-system bugs or difficult experimental-design decisions |

Use Sol if Astra is unavailable. Use Terra for a Luna task if Luna is unavailable. Do not default every small task to the strongest model. Escalate when a focused attempt leaves a documented failure or a material unresolved ambiguity; include the failed check and relevant evidence.

These are **development assistant** choices. The models evaluated by SaqBol remain defined separately in `eval/configs/v0.1.yaml`; this plan does not replace that experimental matrix. Verify provider model identifiers and availability before freezing a run.

## Session template

Select the model in Codex before starting. Run one mini-plan, or one numbered subtask of a longer mini-plan, per session. Estimates below are focused engineering time; exclude volunteer time, account setup, network waits and paid evaluation runtime.

```text
Work on Pxx, subtask N, from docs/11_CODEX_MINI_PLANS.md.
Read its inputs and the relevant current implementation/tests.
Inspect git status and preserve existing changes. Implement only this scope.
Follow the completion checks; report anything that could not be verified.
For a contract change, update its documentation and consumers together.
Do not fabricate labels, source URLs, provider responses, or benchmark results.
Finish with changed paths, check results, limitations and the next dependency.
Do not stage unrelated work or publish/send anything as part of this task.
```

### P01 — Restore a trustworthy local baseline

**Model:** Terra / medium. **Depends:** none. **Size:** 1–2 hours. **State:** done 15 September 2026 — see [P01 baseline report](12_P01_BASELINE_2026-09-15.md).

**Read:** `pyproject.toml`, `.github/workflows/ci.yml`, `web/package.json`, current `git status`.

1. Locate or install a usable Python 3.12+ interpreter; repair/recreate the project environment without removing source or user changes. Record the interpreter and setup command.
2. Install declared extras and web dependencies serially. Run Python offline tests, Ruff lint/format checks, and the existing web typecheck, tests, build and smoke scripts.
3. Record actual pass/fail/skip counts and environmental failures. Separate existing defects from newly introduced ones.

**Done:** reproducible setup and dated results exist; every failing check has a scoped follow-up. Do not claim green if a prerequisite prevents execution. Follow the CI smoke-eval commands too, writing outputs to a task-specific temporary directory.

### P02 — Confirm external dependencies

**Model:** Luna / low for tracking and drafts; **owner performs account decisions and recruitment**. **Depends:** none. **Size:** 30–60 minutes for the tracker. **State:** done 15 September 2026; the dependency report holds account details and is kept outside the repository.

**Read:** `06_DAY0_CHECKLIST.md`, `.env.example`, current roadmap.

1. Record available/pending/unknown for provider access, bot token, domain/host, dataset namespace, two co-annotators and an external reviewer. Store secret names only, never values.
2. Assign an owner and next check date to each missing dependency. Prepare concise volunteer requests and account setup notes.

**Done:** blocker table with owners and evidence; drafts ready for the owner. Do not purchase, send messages or publish while completing this planning task.

### P03 — Finish the existing UI and translation patch

**Model:** Terra / medium; native speakers review language/advice. **Depends:** P01. **Size:** 2–3 hours. **State:** engineering done (form and screenshot regression tests and the sample-page smoke test run in CI); blocked: native-speaker review of the Kazakh and Chinese text, which is not recorded anywhere yet.

**Read:** existing diffs, `web/README.md`, `web/tests`, `api/schemas.py`, playbook schema and changed YAML/locales.

1. Review the existing form/image race fixes and sample-page behavior; change only demonstrated gaps.
2. Audit localized field coverage and fallback behavior. Present questionable Kazakh/Chinese phrasing for native review; do not equate generated text with review.
3. Verify `normalized_text` reaches the web client and evidence spans remain correct across Unicode normalization. Correct stale contract documentation after verification.

**Done:** existing web checks and affected API/render/playbook tests pass; language-review status is recorded separately. Preserve the current patch's intent and do not rewrite it wholesale.

### P04 — Prove production readiness locally

**Model:** Sol / high. **Depends:** P01. **Size:** two 1–2 hour sessions. **State:** code audit and local tests done 16 September 2026; container/DB proof blocked until a Docker-capable host is available. See [P04 record](14_P04_LOCAL_READINESS_2026-09-16.md).

**Read:** Compose/Dockerfiles, `.env.example`, `api/deps.py`, `db/retention.py`, `db/repo.py`, privacy tests and policy.

1. Build/start the stack on a Docker-capable machine; verify migration on an empty database, restart persistence and real web-to-API routing. Audit proxy trust, abuse controls and configured secrets against the intended deployment.
2. Verify retention across stored text, verdict/evidence payloads, model caches, pending donations and logs; do not assume clearing one column proves the policy. Schedule retention and document backup/restore and rollback. Test discovered gaps with representative data.

**Done:** dated container/DB checks and an actionable operations runbook; material privacy/persistence findings fixed or explicitly blocking public launch. No live deployment is part of this mini-plan.

### P05 — Validate providers and capture offline replays

**Model:** Terra / medium; Sol / high for persistent provider/schema failures. **Depends:** P01 and provider access from P02. **Size:** two 1–2 hour sessions. **State:** blocked: one provider key. No live model call has been made.

**Budget note (11 November 2026):** start with one or two low-cost providers and whatever sign-up credit or free tier they offer; the other models in the matrix wait. Do a 20-row dry run first, read the usage page, and extrapolate before any larger run. The owner sets the cap; record what was actually charged.

**Read:** `core/llm.py`, `core/perceive.py`, `test_llm.py`, `test_perceive.py`, `08_REFUSAL_PROBE.md`, `eval/probes/README.md`.

1. With an owner-set spend limit, verify current provider IDs/endpoints and one structured call per intended provider from the production environment. Run the refusal probe and an authorized screenshot smoke test.
2. Capture sanitized, genuine golden replays and verify `SAQBOL_LLM_OFFLINE=1` replays without keys/network. Cover schema errors, refusal, timeout and fallback; distinguish fake-transport fixtures from recorded real outputs.

**Done:** dated provider matrix, failures/costs recorded, replay tests passing, and explicit unsupported capabilities. No result is inferred from a mocked provider call.

### P06 — Audit corpus and design a clean holdout

**Model:** Sol / high; Astra / high only if a design conflict remains unresolved. **Depends:** P01; reviewer coordination via P02. **Size:** 1–2 hours. **State:** done 11 November 2026 — see [P06 record](15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md). The policy is in force with the defaults that need no money and no second person: collect after the freeze, no separate data steward. The tooling that enforces it is P16.

**Read:** `DESIGN_DECISIONS.md` section 4, `05_EVAL_PROTOCOL.md`, `09_SOURCES.md`, split builder/tests, corpus metadata and manifest.

1. Inventory messages versus fragments, language, label, source, duplicates, rights and scrub status. Keep the 36 synthetic pilot seeds out of reported real-data counts.
2. Mark exposed provisional rows as development data. Specify how newly collected source/duplicate groups enter calibration or a held-out pool; keep test text/labels out of development sessions and assign a data steward where possible.
3. Predefine allocation, minimum usable slice support, handling of empty/rare classes and contamination recovery. Reconcile the old 150-row calibration target with available data before inspecting fresh test results.

**Done:** documented allocation and collection policy, reviewed for leakage; no random reshuffle described as a clean holdout.

### P07 — Run a real annotation pilot

**Model:** Terra / medium for tool/export repairs; Sol / high for agreement design. **Depends:** P06 and human annotators. **Size:** two 1–2 hour engineering sessions plus annotation. **State:** engineering half done on 11 November 2026 ([record](17_P07_PILOT_PREPARATION_2026-11-11.md)); labelling is blocked on two co-annotators, and the live check of the page's storage on a working connection to its database.

**Fallback (11 November 2026):** with no co-annotators, the owner labels the pilot twice, at least two weeks apart and blind to the first pass. That measures intra-annotator agreement only and is reported as such.

**Read:** `tools/annotate.html`, `data/pilot`, `07_ANNOTATION_GUIDELINE.md`, T402/T406 history.

1. Verify actual storage access, per-annotator export/import and label independence. Existing UI hiding is not proof of access control; document the trusted-group limitation or fix access as needed.
2. Replace constructed pilot seeds with 30 suitable sourced development items. Obtain three independent human annotations, export them, calculate agreement and log disagreements.
3. Revise the guideline and retain pre/post-revision agreement with the measurement method stated.

**Done:** reproducible pilot exports, agreement report and guideline revision. AI suggestions are not counted as independent human annotations.

**Prepared, 11 November 2026.** `tools/pilot.py draw` wrote `data/pilot/batch-pilot-02.json`: 30 `dev` messages (20 scam, 10 legitimate; 19 Russian, 11 Kazakh) from 26 source groups, with a key file beside it. Items carry no source and no channel, because in `dev` either one gives the label away. `tools/pilot.py agreement` turns the page's export into the agreement report and the disagreement list. The page's admin tab lets every annotator download everyone's labels, so independence is a rule the three are asked to keep and is reported as such. No label exists yet.

### P08 — Deploy a small pilot and test reachability

**Model:** Sol / high. **Depends:** P03, P04, host/token from P02; P05 for hybrid/screenshots. **Size:** 2–3 hours plus external testing. **State:** blocked: a host and a bot token.

**Budget note (11 November 2026):** use free hosting tiers. The bot needs no public address. The API can run on its in-memory store for a demonstration, in which case the page says nothing is kept and donations are switched off; storing anything a user sends needs a database and the P04 retention job first. Buy a domain only if the mainland-network test fails on the host's own subdomain.

**Read:** P04 runbook, `01_ARCHITECTURE.md`, API/bot configuration, `06_DAY0_CHECKLIST.md` section E.

1. Prepare the exact release/configuration and rollback, then deploy within the owner's authorization. Verify HTTPS, consent, text analysis, feedback, dataset opt-in and restart recovery.
2. Check outage behavior, abuse controls, provider capabilities and absence of accidental mock mode. A rules-only pilot must say so.
3. Have a person test the actual hostname from a mainland SIM without VPN and inside WeChat; record date, URL, device, result and load time. Test the configured fallback.

**Done:** usable pilot with dated evidence and known limits. Local browser success cannot satisfy the mainland-network gate.

### P09 — Collect and double-annotate in batches

**Model:** Luna / low for structured metadata checks; Terra / medium for tooling fixes. **Depends:** P07 and the `system-freeze-v0.1` tag from P11. **Size:** 30–60 minutes engineering per batch, plus human collection/review. **State:** blocked: the freeze tag. A row collected before the tag is development data, so collection for the test set does not start early. The tooling for step 2 exists since 11 November 2026 ([record](19_LABEL_PIPELINE_2026-11-11.md)): `tools/labels.py batch`, `agreement`, `adjudication` and `merge`.

**Read:** P06 policy, revised annotation guideline, `tools/collect.py`, `tools/scrub_corpus.py`, source inventory.

1. Collect small source-backed batches, prioritizing real Kazakh/code-switched messages and genuine hard negatives. Preserve source URLs/dates, donation consent and redistribution basis.
2. Scrub and group duplicates before allocation. Have two humans label independently and adjudicate disagreements with a log; calculate per-class agreement.
3. Keep fresh held-out material under the P06 process. Report progress using eligible reviewed rows, not fragments or synthetic filler.

**Done per batch:** metadata and PII checks pass, two labels plus adjudication exist, and allocation is recorded. Iterate until the declared release scope is supported; revise scope if collection remains thin.

### P10 — Freeze final splits

**Model:** Sol / high. **Depends:** P09. **Size:** 1–2 hours. **State:** blocked: annotated fresh rows. The builder already follows the policy (P16) and reads label records since 11 November 2026 ([record](19_LABEL_PIPELINE_2026-11-11.md)); what remains is the final build, `python -m saqbol.eval splits --require-labels`, once the records exist.

**Read:** split builder/tests, P06 policy, adjudicated metadata, `02_DATA_CONTRACTS.md`, datasheet.

1. Build splits from adjudicated labels using the approved source/duplicate groups. Exclude exposed development rows and synthetic descendants from held-out evaluation.
2. Check exact/near duplicates, source groups, synthetic ancestry and calibration/test separation. Record dataset hashes, seed, label/language support and exclusions.
3. Freeze files and manifest. Mark an empty donated split unavailable, never as a zero-error result.

**Done:** leakage checks pass and a versioned manifest explains every included/excluded row. Fresh test contents are not fed back into implementation.

### P11 — Calibrate, then freeze the system

**Model:** Sol / high. **Depends:** P16; P05 for the model systems. **Size:** 2–3 hours. **State:** rules-only fit done on 11 November 2026; the hybrid fit is blocked on a provider key; the tag `system-freeze-v0.1` is not created and waits for the owner.

**Reordered 11 November 2026.** This step now runs before collection. The fresh pool will almost certainly hold fewer than 250 rows, so thresholds are fitted on `dev` (`eval/configs/dev.yaml`) and the run is labelled `dev-calibrated`. The tag `system-freeze-v0.1` pins rules, lexicons, prompts, playbooks, thresholds and model identifiers, and collection for the test set starts the day after. If the fresh pool does reach 250 rows, the calibration slice the builder cuts is used to refit thresholds only, by the procedure fixed at the tag.

**Read:** `core/fuse.py`, `eval/systems.py`, `eval/config.py`, calibration protocol and P10 manifest.

1. Define an explicit calibration objective including false positives and coverage. Fit weights/thresholds only on calibration data (`dev` in the `dev-calibrated` regime, the fresh slice otherwise); never on a test split.
2. Save chosen parameters, candidate search, calibration results, model IDs, prompts, playbook version, code revision and run seed. Confirm evaluation uses the selected parameters.
3. Freeze the configuration before running final test cells. If tuning requires more data, revisit allocation without inspecting the held-out results.

**Done:** reproducible calibration artifact and frozen configuration; final test data has not influenced tuning. This deliberately precedes P12, correcting the old backlog's ambiguous order.

**Result for the rules-only system, 11 November 2026.** `python -m saqbol.eval calibrate --config eval/configs/dev.yaml` writes `eval/calibration/rules_only.json`. Only the `suspicious` threshold can be fitted without a model. The objective is macro-F1 subject to at most 5% of hard negatives flagged, coverage of at least 0.80, and no broken case in the regression suite; the current value is replaced only when the interval of the paired gain over source groups lies above zero. The best candidate was 0.37 (+0.062 macro-F1, five more scam rows from two articles, interval 0.000 to 0.111), so the threshold stays at 0.40. The phrase lists were then revised once before the freeze ([record](18_PRE_FREEZE_RULE_COVERAGE_2026-11-11.md)) and the fit was run again: 0.37 is still the best candidate (+0.024, two more scam rows from one article, interval 0.000 to 0.050) and the threshold still stays at 0.40. The committed artifact is the second fit. The procedure and the table are in [05_EVAL_PROTOCOL.md](05_EVAL_PROTOCOL.md) section 7. Open before the tag: the owner confirms the 5% cap, the 0.80 floor and the incumbent rule, or changes them, and answers the questions in section 6 of the rule-coverage record; the hybrid system is fitted if a provider key arrives, or is declared out of the frozen set.

### P12 — Run the benchmark and inspect completeness

**Model:** Sol / high. **Depends:** P10, P11. **Size:** two 1–2 hour sessions plus bounded provider runtime. **State:** blocked: final splits. The interval rule, the hard-negative bound and the playbook score were fixed on 11 November 2026, before any test row existed ([record](20_ANALYSIS_RULES_2026-11-11.md)); the tests of H1 to H3 are still to be written, also before the test set is read.

**Budget note (11 November 2026):** two verified models are the whole required matrix. The response cache makes reruns free, so the cost is one pass. Publish at the tier the row count supports (roadmap, research gate).

**Read:** `eval/configs/v0.1.yaml`, eval run/results/leaderboard modules, metrics tests and protocol.

1. Run rules-only and zero-shot/hybrid with two verified providers first. Expand to the other models only within the agreed budget. Record precise provider IDs and dates.
2. Run cue-masked and no-playbook-context ablations; add translated only on human-translated paired rows. Report support and compare matched subsets.
3. Inspect the manifest: the runner can exit successfully while cells are skipped. Generate the leaderboard, intervals, hard-negative false positives, coverage and supported language/stage slices. Separate refusals/errors from predictions and report omissions.

**Done:** reproducible results/configuration/manifest plus generated leaderboard, with no unexplained missing required cells. No claim of superiority when intervals overlap; no tuning on these results. A later fix needs a new version and contamination disclosure.

### P13 — Assemble the dataset release

**Model:** Terra / medium; Luna / low for final formatting. **Depends:** P10. **Size:** 2–3 hours. **State:** pending dataset freeze.

**Read:** `data/DATASHEET.md`, dataset README, annotation exports, manifest and source/rights records.

1. Package JSONL, loading instructions, license, provenance, annotation guideline, agreement table and exclusions. Replace placeholders only with measured or verified facts.
2. Check installation/loading from a clean environment and have the external reviewer inspect rights, privacy and claims.
3. Prepare a versioned Hugging Face release bundle and exact publication metadata for owner review.

**Done:** complete reviewable bundle; publication remains a separate authorized action with the final version/link recorded afterward.

### P14 — Build the report and demo

**Model:** Sol / high for report; Terra / medium for demo; Luna / low for assembly. **Depends:** P08, P12, P13. **Size:** three 1–2 hour sessions. **State:** pending evidence.

**Read:** generated results, dataset bundle, design decisions, README, deployment evidence and original T604–606 specifications.

1. Write the six-page report from actual results: method, dataset, intervals, ablations, related work, limitations and ethics. Verify any novelty claim against current sources.
2. Update README/decisions with released links and measured limitations. Produce a 60-second demo and verify the offline fallback with network disabled; screenshots require replay support or an explicit limitation.
3. Assemble the one-page impact artifact and DOI submission package with dated, traceable numbers. Use document/presentation/PDF skills when creating those artifacts.

**Done:** reviewed report, one-pager, recording and reproducible offline demo. Do not invent a DOI, deployment URL or published dataset link.

### P15 — Gather pilot feedback and external evidence

**Model:** Terra / medium for instrumentation fixes; Luna / low for drafts and evidence indexing. **Depends:** P08. **Size:** 30–60 minutes per weekly review. **State:** pending live pilot.

**Read:** stats/feedback implementation, privacy policy, original distribution strategy, observed pilot feedback.

1. Verify what counts as a unique user/check, exclude developer/test traffic and preserve privacy. Record real usage with date windows and known measurement limitations.
2. Triage feedback into bounded follow-ups. Donations enter review, not ground truth; do not tune the frozen benchmark system from test feedback.
3. Draft outreach and awareness-session materials from real artifacts, and maintain an evidence index for press/reviewer/session links supplied later.

**Done per review:** dated usage snapshot, feedback backlog and evidence index. Sending outreach requires a separate explicit instruction; 300 users and press coverage remain aspirations until observed.

### P16 — Put the holdout policy into the tooling

**Model:** Sol / high for the builder and metrics; Terra / medium for the collector. **Depends:** P06. **Size:** two 1–2 hour sessions. **State:** done 11 November 2026. Added 11 November 2026; it gathers the tooling changes the [P06 record](15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md) listed against P09, P10 and P12, because all of them must exist before the freeze.

**Read:** the P06 record, `02_DATA_CONTRACTS.md` section 6, `eval/splits.py`, `eval/leaderboard.py`, `eval/metrics.py`, `eval/support.py`, `tools/collect.py` and their tests.

1. **Done 11 November 2026.** Contract section 6 gains the `dev` split, the source-group rule and the calibration rule. The split builder joins rows from one article, sends every row in `data/exposure.json` to `dev` with its group and its article, cuts calibration only from 250 or more fresh rows, and records the regime in the manifest. `eval/configs/dev.yaml` runs development numbers, and the leaderboard marks a `dev` or calibration table as not a test result. Leakage tests over the released files fail the build on an exposed row or a divided article.
2. **Done 11 November 2026.** `tools/collect.py` compares each new row with every `dev` row and fragment. A row from an article already in `dev`, or sharing a pair or variant key with a `dev` row, is marked as development data; a duplicate is refused; a similarity between 0.50 and 0.85 is held back until the collector rules `variant` (the row joins the exposure register) or `distinct`. Without the freeze tag a new batch is accepted only with `--dev`. `collect.py check` fails on a batch outside the register that predates the tag and on a lookalike with no ruling.
3. **Done 11 November 2026.** The exact one-sided binomial bound replaces the bootstrap interval when a hard-negative false-positive count is zero or equals the total, and the leaderboard marks it. Every released row names its `source_group`, and the leaderboard prints the number of groups beside every row count. The floors of the P06 record's section 7 are in `eval/support.py`: a slice under 30 rows prints no metric, macro-F1 needs 10 rows of each class, the false-positive rate needs 30 hard negatives, and a number under its floor prints as "not reported" with the count that fell short. The release tier (none, pilot, benchmark) is computed from `test_press` and printed in the header; at tier none the held-out tables print row counts and no number, and a partial run (`--limit`) has no tier. `results.json` still holds every number the harness computed.

Left for P12, which is the first task to score annotated playbook labels: the per-playbook floor (10 rows per playbook; top-1 accuracy when fewer than five playbooks are supported) and the 50-rows-per-language condition on the H1 comparison. The intervals still resample rows, not source groups; the leaderboard says so, and a grouped bootstrap is a P12 decision. **Settled 11 November 2026** ([record](20_ANALYSIS_RULES_2026-11-11.md)), except the H1 condition: the playbook floor is applied, and every interval is the wider of a row interval and a source-group interval.

**Done:** a fresh batch cannot enter a test split if it repeats, translates or shares an article with a development row; a table cannot be generated that presents development data, an unsupported slice or a zero-width interval as a test result. No row is collected as part of this mini-plan.
