PROVISIONAL splits, built from collection labels, not annotated: `playbook_id`, `stage` and both annotator fields are null on every row, and these files must be rebuilt after T407 (annotation) lands.

# KazScam v0.1 splits

Built by `python -m saqbol.eval splits --corpus data/corpus --out data/kazscam_v0.1 --seed 20260908` on 2026-11-10T19:54:01Z. One JSONL per split in the shape of docs/02_DATA_CONTRACTS.md section 6, plus `text_sha256` (what the leakage rules key on) and `corpus_id` (the collection record the row came from). `manifest.json` records the seed, the counts and every group of rows that had to travel together.

| Split | Rows | Source groups | By label | By lang | Hard negatives |
|---|---|---|---|---|---|
| `train_synthetic` | 0 | 0 | none | none | 0 |
| `dev` | 76 | 28 | legit 17, scam 59 | kk 28, ru 48 | 17 |
| `calibration` | 0 | 0 | none | none | 0 |
| `test_press` | 0 | 0 | none | none | 0 |
| `test_donated` | 0 | 0 | none | none | 0 |

Rows that share a source article, a translation or variant key, or near-identical text are one source group and carry the same `source_group`. A split with far fewer groups than rows holds less independent evidence than its row count suggests.

- `dev` holds every row the system was developed against, as listed in `data/exposure.json`, and every row grouped with one. A number computed on `dev` is a development number and is never reported as a test result (docs/15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md).
- No calibration split was cut: the fresh press pool has 0 rows, below the 250 that can spare one, so thresholds are fitted on `dev` and a run on these files is labelled `dev-calibrated`.
- 50 `phrase_fragment` rows were excluded; fragments never enter a message split.
- 15 groups of 63 rows (one source article, parallel translations, variant groups, near-duplicates) were assigned as units.
- `train_synthetic` is empty: the LLM paraphrases do not exist yet. When generated they must be derived from dev rows only, never from calibration or a test split, with the seed row's released id recorded in `source_row_id` so the second leakage rule (no synthetic row shares a source row with any test row) can be checked.

Leakage checks over these files live in `tests/test_splits.py`.
