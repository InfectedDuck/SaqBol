# SaqBol — remaining roadmap

Revised 11 November 2026. This replaces the plan of 15 September 2026, whose dates have all passed. The T identifiers refer to tasks in the original build plan; the P identifiers are the mini-plans in [11_CODEX_MINI_PLANS.md](11_CODEX_MINI_PLANS.md).

## Outcome

Deliver a usable scam checker, a human-reviewed KazScam dataset, and reproducible evaluation results, on a budget close to zero. The software is built. What remains is a test set the system was not developed on, human labels, one honest benchmark run, and a small public deployment.

## Where the project stands

Checked on 11 November 2026: 1,661 offline tests pass, 22 are skipped and 2 are expected failures; lint and format checks are clean; the smoke evaluation runs.

| Mini-plan | State | Evidence or dependency |
|---|---|---|
| P01 environment and baseline | done | [baseline report](12_P01_BASELINE_2026-09-15.md) |
| P02 external dependencies | done as a tracker; the dependencies themselves are open | Owner track below |
| P03 UI and translation patch | engineering done; blocked: native-speaker review of the Kazakh and Chinese text | Web regression tests and sample-page smoke test run in CI |
| P04 production readiness | code audit and local tests done; blocked: a host that can run containers | [P04 record](14_P04_LOCAL_READINESS_2026-09-16.md) |
| P05 provider validation | blocked: one provider key | No live model call has been made yet |
| P06 corpus audit and holdout design | done | [P06 record](15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md) |
| P16 holdout policy in the tooling | done | Contract, split builder, collector screening, the exact bound for hard-negative false positives, support floors, source-group counts and the release tier in the leaderboard, with tests and a development config |
| P11 calibration and freeze | rules-only fit done; the hybrid fit is blocked on a provider key; the freeze tag waits for the owner | `eval/calibration/rules_only.json`: the `suspicious` threshold stays at 0.40 ([protocol section 7](05_EVAL_PROTOCOL.md)) |
| Rule coverage before the freeze | done on `dev`; four questions open for the owner | [record](18_PRE_FREEZE_RULE_COVERAGE_2026-11-11.md): phrases may carry quotation marks and a gap, missing forms added, two combinations. 25 of 59 `dev` scam messages flagged, up from 20; no hard negative flagged |
| P07 annotation pilot | batch and agreement tool ready; labelling blocked: two co-annotators | [P07 record](17_P07_PILOT_PREPARATION_2026-11-11.md): 30 `dev` messages drawn, agreement computed from the page's export. No label exists yet |
| P08 live pilot | blocked: a host and a bot token | — |
| Label pipeline for P09 and P10 | tooling done; no row is labelled | [record](19_LABEL_PIPELINE_2026-11-11.md): labelling batches, agreement, logged decisions, label records, the split builder applying them, and no test number while a `test_press` row lacks two readings |
| Analysis rules for P12 | fixed before the test set; the hypothesis tests are open | [record](20_ANALYSIS_RULES_2026-11-11.md): every interval is the wider of a row and a source-group interval, the hard-negative bound counts groups, and the playbook score has its floor and treats `other_scam` as naming no playbook |
| P09 to P15 | not started | In the order below |

Three facts shape the rest of the plan:

- **There is no test set yet.** All 76 usable messages were read while the rules were written. They are now the `dev` split, and `test_press` is empty until new rows are collected ([P06 record](15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md)). The only number that exists is a development number: rules-only macro-F1 of 0.548 on `dev`, from rules revised against those same rows.
- **No model has been called.** The hybrid and zero-shot systems are built and unit-tested against fake transports only.
- **Nothing is deployed.**

## Budget

The September budget of about $200 ([architecture, section 7](01_ARCHITECTURE.md)) assumed a rented server, a paid domain and four paid model providers. It is withdrawn. The rule now is that every required step has a route that costs nothing, and money is spent only where the table says it helps.

| Need | Route that costs nothing | Worth paying for only if |
|---|---|---|
| Development, tests, rules-only system, dataset tooling | Local machine; CI on the public repository | — |
| Model calls for validation and the benchmark | Sign-up credit or a free tier on one or two low-cost providers. The whole benchmark is small: a few thousand short calls, and the response cache makes every rerun free | No credit is available. Then one small prepaid top-up, with a hard cap set by the owner before the first call |
| API and bot hosting | A free container or VM tier. The bot uses long polling, so it needs no public address. The API starts without a database, on an in-memory store that forgets everything on restart; a free managed Postgres removes that limit | The free tier cannot stay up for the pilot window |
| Web app hosting | A free tier of a Next.js host, on the host's own subdomain | — |
| Domain | The host's subdomain | The mainland-network test fails on that subdomain. A custom domain is the one purchase most likely to be needed |
| Annotation | Two volunteers, credited in the datasheet | — |
| Dataset and report hosting | A public dataset repository and a release on the code host | — |
| Screenshot reading (vision model) | Left out of the pilot and reported as unverified | Credit covers it after the benchmark is paid for |

Rules for spending:

1. Prices, credits and free-tier limits change, and none was verified for this plan. The owner reads each one on the provider's own page on the day and records it in the dependency note.
2. Before any paid run, do a 20-row dry run, read the provider's usage page, and multiply. Run the full matrix only if the estimate is under the cap.
3. Two verified models are enough for v0.1. The other two in `eval/configs/v0.1.yaml` run only if they cost nothing.
4. An in-memory deployment must say so on the page and collects no donations. A deployment that stores anything needs the retention job from P04.

## Order of work

The order changed in one important way. Under the holdout policy the system is frozen **before** the test rows are collected, so calibration and the freeze (P11) now come before collection (P09), not after it.

| Step | Mini-plan | Depends on | Deliverable |
|---|---|---|---|
| 1 | P16 holdout policy in the tooling | — | Builder, collector and leaderboard enforce the policy; CI fails on a leak |
| 2, owner track | One provider key, a bot token, two co-annotators, a free host | — | Dependency note updated with dates |
| 3 | P05 provider validation, with one or two low-cost providers | A provider key | Real call evidence, offline replays, a measured cost per row |
| 4 | P11 fit thresholds on `dev`, then tag `system-freeze-v0.1` | P16; P05 if model systems are included | Frozen rules, lexicons, prompts, playbooks and thresholds |
| 5, parallel | P07 annotation pilot on 30 `dev` rows | Two co-annotators | Agreement figures and a revised guideline |
| 5, parallel | P08 free-tier pilot deployment and reachability test | A host and a bot token | Dated web, bot and mainland-network checks |
| 6 | P09 collect fresh rows and double-annotate them | The freeze tag; P07 | Reviewed test rows with provenance |
| 7 | P10 final splits | P09 | Frozen, hashed dataset; leakage checks pass |
| 8 | P12 benchmark and ablations, run once | P10 | Results, manifest, intervals, generated leaderboard |
| 9 | P13 dataset release package | P10 | Reviewable publication bundle |
| 10 | P14 report and demo | P08, P12, P13 | Report, one-pager, offline demo |
| Ongoing | P15 feedback and evidence | P08 | Dated usage evidence |

P03's language review and P04's container proof are not on the critical path. They close when a native speaker and a container host are available, and P08 cannot store user data until P04 has.

**If no provider key exists by the freeze date**, tag anyway. Prompts and playbooks freeze with the rules. Later provider work may change transport code and model identifiers, and may run the threshold fit that was specified at the tag, but a prompt change after the tag is a new system version for which every row read so far is development data.

**If no co-annotators are found by the end of the pilot window**, v0.1 becomes a single-annotator pilot. The owner labels every row twice, at least two weeks apart and blind to the first pass, and the datasheet reports intra-annotator agreement and says plainly that inter-annotator agreement was not measured. Labels suggested by a model are never counted as human labels.

## Working dates

These are targets. Human availability and the number of scam messages that can still be found in public sources govern the schedule.

| Window | Gate | If blocked |
|---|---|---|
| 11–17 November | P16 finished. Owner has asked two annotators and started on a provider key and a bot token | Continue with rules-only; record the dependency |
| 18–24 November | P05 on at least one provider; thresholds fitted on `dev`; `system-freeze-v0.1` tagged by 24 November | Freeze without model systems, as above |
| 25 November – 1 December | Annotation pilot finished; free-tier pilot deployed and tested from a mainland network | Start collection regardless; it depends only on the tag |
| 2 December – 10 January | Fresh rows collected and double-annotated in batches | Report the real count; do not pad with fragments or synthetic text |
| 11–24 January | Final splits; benchmark run once; leaderboard generated | Publish no test number below the support floor |
| 25 January – 14 February | Dataset bundle, report, demo | Cut optional experiments and visual polish first |
| 15–20 February | Dated evidence snapshot and owner review | Show what exists and what is missing |

## Scope and release gates

**Keep:** hard negatives, human annotation and agreement, provenance and PII review, a test set collected after the freeze, confidence intervals, the rules-only baseline, the datasheet, an accessible demo and honest limitations.

**Defer first:** benchmark models beyond two verified ones; screenshot reading on a live provider; the human-translation ablation if translations are unavailable; dense-retrieval experiments; new stage-detection work; cosmetic polish.

**After v0.1:** a larger donated corpus, fine-tuning, voice notes, APK analysis and longer conversations. Each needs a new evaluation question and success criterion before implementation.

**Research gate.** The support floors come from the [P06 record](15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md), section 7:

| Fresh, adjudicated test rows | What may be published |
|---|---|
| Fewer than 60, or fewer than 20 legitimate | No test number. Development numbers only, labelled as such |
| At least 60, with at least 20 legitimate | A pilot result, called a pilot, with intervals |
| At least 200, with at least 60 legitimate (40 of them hard negatives) and at least 60 rows in each of Russian and Kazakh | A benchmark result |

On top of that: independent human labels, logged adjudication, release rights and scrub review, calibration data that is never test data, a frozen run configuration, and explicit skipped or unsupported cells. Annotation standards are not lowered to reach a row count.

**Public-service gate.** A real API connection with no accidental mock mode, consent, useful failure states, correct evidence highlighting, abuse controls, and dated deployment and reachability evidence. Persistence and retention scheduling are required before anything a user sends is stored.

Outreach and publication are future actions and are not performed by this plan.

## Keeping the plan current

Use `ready`, `in progress`, `blocked: <specific dependency>`, or `done: <evidence link>` per mini-plan. Check in a result note containing the scope, changed paths, checks, limitations and next task. Preserve original T identifiers in notes. Update this roadmap when a gate changes; leave historical snapshots clearly dated.
