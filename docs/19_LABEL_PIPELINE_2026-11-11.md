# Label pipeline: from two annotators' answers to a released label — 11 November 2026

Status: **the tooling is done and tested; no row has been labelled and no label record exists.** Mini-plans [P09 and P10](11_CODEX_MINI_PLANS.md) need a way to turn two annotators' answers into the `label`, `playbook_id` and annotator fields of a released row, with every decision on a disagreement kept. That path did not exist: the split builder copied the collector's label and left the annotator fields null. This record covers what was added, the rule it follows, and what it still cannot do.

Every reading used to test it is invented test input. Nothing here is an annotation result.

## 1. The path

| Step | Command | Writes |
|---|---|---|
| 1. Draw a batch | `tools/labels.py batch` | A batch file for the labelling page and a key file beside it |
| 2. Label | Each annotator works alone in `tools/annotate.html` | The page's export, one row per annotator per item |
| 3. Measure | `tools/labels.py agreement` | The agreement report, the same one the pilot uses |
| 4. Decide | `tools/labels.py adjudication` | One entry per item the two read differently, filled in by hand |
| 5. Record | `tools/labels.py merge` | One label record, `data/labels/<batch>.json` |
| 6. Build | `python -m saqbol.eval splits` | The released files, with the labels applied |

The record format is in [02_DATA_CONTRACTS.md](02_DATA_CONTRACTS.md) section 6. The procedure the annotators follow is unchanged, in [05_EVAL_PROTOCOL.md](05_EVAL_PROTOCOL.md) section 3 and the [guideline](07_ANNOTATION_GUIDELINE.md).

## 2. The rule

A reading is a label and, for a scam, optionally a script: one of the playbook ids or `other_scam`.

| The two readings | Outcome |
|---|---|
| Same label, same script (or neither names one) | That is the label. `adjudicated` is false |
| Different labels | A logged decision |
| Same label, different scripts | A logged decision |
| Same label, one names a script and the other does not | A logged decision |

A decision is a label, a script (only with `scam`, and it may be left empty), a one-line reason, and who decided: a name, or `discussion`. `merge` computes nothing a person did not enter. It refuses to write a record while an annotator has unread items, while a difference has no decision, or when a decision answers readings that have since changed.

The third row of the table is the strict choice. Taking the one script that was named would be simpler, and would let one annotator set the script on every row the other left blank.

## 3. What each part guarantees

**The batch.** An item is an id and a text. Source and channel are left off for the reason found in the [pilot preparation](17_P07_PILOT_PREPARATION_2026-11-11.md): in this corpus they give the label away. The key file maps each item to its corpus row and holds the digest of the text that was shown. The draw is seeded, skips rows a label record already covers, and refuses to overwrite an existing batch without `--force`, because redrawing a batch that annotators have started would detach their answers from the rows.

**The scope.** `--scope fresh` (the default) draws rows collected for a held-out split, by the exposure register. On this date that is an error, as it should be: `no message row to label in scope 'fresh': 0 fresh and 76 dev rows have no label record`. `--scope dev` exists for guideline rounds on development rows.

**The record.** Rows are keyed by corpus id and text digest. When the text of a row changes after it was labelled, the split builder stops with an error instead of applying a label to a text nobody read. A row may appear in one record only. Records are validated on load, so a hand-edited record that breaks the rule in section 2 is refused.

**Names.** The export holds the names the annotators typed and belongs under `data/raw/`, which is not tracked. `adjudication` and `merge` take a pseudonym for each annotator (`ID=annotator-1`), and the committed files carry the pseudonym.

**Two passes by one person.** The roadmap's fallback when no second annotator is found. `--intra` marks the record `intra-annotator`. The manifest lists those rows and the dataset README says that agreement between annotators was not measured on them.

**The pilot is kept out.** `merge` refuses a pilot key. Pilot answers were given to measure the guideline, on a guideline that the pilot then changes.

## 4. What the split builder and the leaderboard now do

- The builder reads `data/labels/` when it exists (`--labels` to point elsewhere). A labelled row takes its label, script and annotator fields from the record. A label that differs from the collector's is counted in the manifest, and a row that turns out to be a scam loses its hard-negative flag.
- `--require-labels` leaves out every row outside `dev` that does not carry two readings, and lists what it left out. This is the final build of P10.
- The manifest has a `labels` section: per split, how many rows carry two readings, how many were decided, how many still carry the collector's label. Its `status` is `annotated` only when every released row has two readings.
- The leaderboard prints no test number while any `test_press` row lacks two readings, whatever the size of the split. The results file records the count, and a results file that does not record it is treated the same way.

Without label records the builder's output is unchanged: the committed JSONL files are byte-identical after a rebuild.

## 5. Open

| Item | Needs |
|---|---|
| Any label at all | The freeze tag, fresh rows, and two annotators or the two-pass fallback |
| Named or pseudonymous annotators | Each annotator's answer, before the first record is committed |
| Should two passes by one person cap the release tier? | The owner. Today such rows are disclosed in the manifest and the README, and the tier is not lowered |
| Script accuracy when the right answer is "no playbook" | A decision before the tag. The script metric treats a missing script as its own class, so a row whose label is `other_scam`, or a scam row with no script, counts against a system that names no playbook for it. Not changed here: it is a change to a reported metric |
| One batch on the page at a time | Procedure. The page loads every batch in its database together, so the previous batch is removed when the next is written |
| Live round trip through the page's database | A working connection. Still not done; see the pilot preparation record |

## 6. How to reproduce

```bash
python tools/labels.py batch --out data/annotation/batch-annot-01.json
python tools/labels.py agreement --batch data/annotation/batch-annot-01.json \
    --exports data/raw/annotation/*.json --annotators ID_A ID_B
python tools/labels.py adjudication --batch data/annotation/batch-annot-01.json \
    --exports data/raw/annotation/*.json --annotators ID_A=annotator-1 ID_B=annotator-2
python tools/labels.py merge --batch data/annotation/batch-annot-01.json \
    --exports data/raw/annotation/*.json --annotators ID_A=annotator-1 ID_B=annotator-2 \
    --out data/labels/batch-annot-01.json
python -m saqbol.eval splits --require-labels
python -m pytest tests/test_labels.py tests/test_label_tool.py
```

The first command fails today, for the reason in section 3. The tests run the whole path on invented readings. On this date: 1,641 tests pass, 22 are skipped and 2 are expected failures.
