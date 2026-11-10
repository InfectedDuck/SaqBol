# Analysis rules fixed before the test set — 11 November 2026

Status: **fixed before any test row exists.** No row has been collected for `test_press` and no test number has been computed, so none of the rules below was chosen by looking at a result. Changing one of them after a test row has been read makes a new analysis, and it is reported as one.

[Mini-plan P16](11_CODEX_MINI_PLANS.md) left three questions to P12: what an interval resamples, the per-playbook floor, and the language condition on H1. A fourth came from the [label pipeline](19_LABEL_PIPELINE_2026-11-11.md): how a scam that fits no playbook is scored. This record settles the first, second and fourth. The language condition is left open, with the other hypothesis tests (section 6).

## 1. Intervals

**The rule.** Every interval is the wider of two percentile bootstrap intervals computed from the same seed. The first resamples rows, stratified by gold class, as before. The second resamples whole source groups: each resample draws, among the groups that hold the same set of gold labels, as many groups as there are. A row that names no group is a group of one.

**Why two.** Rows quoted from one article share their wording, their scam and often their verdict. When they agree, resampling rows treats one piece of evidence as several and the interval is too narrow. Resampling groups corrects that. When there are few groups, the group interval is too narrow in turn, and a small held-out split will have few groups. Each method fails in one of the two situations. If either method is valid for the data, the wider interval covers at least as often as that method does, so no number is shown as more certain than either method allows.

**What it changes.** When every row is its own group the two intervals are identical, draw for draw, and equal the old row interval; a test checks this. The development data shows the second failure in practice. These are development numbers for the rules-only system, from `eval/configs/dev.yaml`, and not test results:

| `dev` slice | Rows (groups) | Resampling rows | Resampling groups | Reported |
|---|---|---|---|---|
| all | 76 (28) | 0.460 to 0.630 | 0.461 to 0.627 | 0.460 to 0.630 |
| `ru` | 48 (23) | 0.477 to 0.719 | 0.474 to 0.708 | 0.474 to 0.719 |
| `kk` | 28 (12) | 0.321 to 0.591 | 0.350 to 0.550 | 0.321 to 0.591 |

The point estimate is unchanged: macro-F1 0.548 on all rows. On the Kazakh slice the group interval is narrower than the row one. Its 24 scam rows come from 8 articles, and resampling 8 articles understates the spread. Had the group interval replaced the row interval, the Kazakh figure would have looked more certain than before. The leaderboard prints nothing for that slice anyway, since it is under the 30-row floor; `results.json` keeps both component intervals for every cell.

## 2. The hard-negative bound

When no hard negative is flagged, or every one is, the bootstrap has nothing to vary and the exact one-sided binomial bound is reported instead. That bound now counts source groups as its trials, not rows. Forty genuine notices copied from four bank pages are four observations of how the system treats such a page.

On `dev` no hard negative is flagged. The 17 hard negatives come from 12 groups, because each Kazakh notice shares a group with its Russian original. The bound on the false-positive rate rises from 0.162 to 0.221. For the Russian slice, 13 hard negatives in 12 groups, it rises from 0.206 to 0.221. The floor of 30 hard negatives still counts rows, and the leaderboard prints the group count beside every row count.

## 3. The playbook score

**Before.** Macro-F1 over every class that occurred, with "no playbook" as one class and an annotator's `other_scam` as another. A system never answers `other_scam`. It names no playbook, so it was marked wrong for agreeing with the annotators, and "no playbook" was averaged as though it were a playbook.

**Now.**

| Part | Rule |
|---|---|
| Rows | The scam rows the system answered. A scam row answered `legit` is a miss with no playbook, and stays in |
| No playbook | `other_scam` and no script are one answer, the one a system gives by naming none. That class is scored and never averaged |
| Support | Gold scam rows per playbook, counted over every scam row of the slice, so every system on the slice is held to the same playbooks |
| Score with five or more playbooks of at least 10 rows | Macro-F1 averaged over those playbooks. A playbook named on a scam that fits none still lowers that playbook's precision |
| Score with fewer | Top-1 accuracy over the rows whose gold label names a playbook, printed as `acc`. It needs 30 such rows, the slice floor |
| Neither | `not reported`, with the number of rows that name a playbook |
| Listed | Under each table, the playbooks of each slice above and under the floor, with their counts |

The accuracy leaves out the rows that name no playbook. Kept in, they would reward a system for naming nothing, the failure the old rule guarded against by not scoring a slice with no gold playbook at all. That guard stays.

No released row carries a gold playbook yet, so no playbook number has ever been computed. This change alters no figure.

## 4. Where the rules live

| Rule | Code | Document |
|---|---|---|
| The two intervals and their envelope | `metrics.bootstrap_ci`, with `groups` | [protocol](05_EVAL_PROTOCOL.md) section 5 |
| The bound over groups | `metrics.hard_negative_fpr_ci`, with `groups` | the same |
| The playbook score | `run.playbook_class`, `run._score_playbooks` | the same |
| The playbook floors | `support.Floors.playbook_rows`, `playbooks_for_macro`, `support.playbook_gap` | the same |
| What `results.json` records | `ci_resampled`, `ci95_rows`, `ci95_groups`, `ci_n_groups`, `fpr_hard_negative_n_groups`, the `playbook_*` keys | [contracts](02_DATA_CONTRACTS.md) section 7 |

A results file written before these rules has no `ci_resampled` key. The leaderboard prints it with the sentence that says its intervals resampled rows, and prints none of its playbook scores, since their support was not recorded.

## 5. What did not change

- The support floors and the release tiers.
- The calibration procedure. Its paired comparison already resampled source groups; the hard-negative bound in its record counts rows and describes the fit without deciding it.
- The reporting rule. No claim that one system beats another unless the intervals are disjoint. Wider intervals make fewer such claims.

## 6. Open

| Item | Needs |
|---|---|
| H1, the language comparison: at least 50 test rows in each language, and "at matched content" only on fresh parallel pairs | To be written with the H2 and H3 tests, before the test set is read |
| H2, "at matched recall", and H3, the difference between two drops under cue masking | The same. Both compare systems on the same rows, so the interval belongs on the paired difference |
| The calibration comparison resamples groups alone, and with few groups that interval is too narrow, which makes a threshold change easier to justify. On `dev` it decided nothing: the interval reached zero and the threshold stayed | A decision before any refit on a fresh calibration slice |
| Any rule here | The owner may overturn it until a test row is read |

## 7. How to reproduce

```bash
python -m saqbol.eval run --config eval/configs/dev.yaml --out eval/runs --run-id dev-check
python -m saqbol.eval leaderboard --results eval/runs/dev-check/results.json
python -m pytest tests/test_metrics.py tests/test_eval_harness.py
```

The first command writes `ci95_rows` and `ci95_groups` beside every `ci95`. On this date: 1,661 tests pass, 22 are skipped and 2 are expected failures.
