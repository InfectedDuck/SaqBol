# P07 annotation pilot: preparation — 11 November 2026

Status: **the engineering half is done; no one has labelled anything.** The pilot itself needs two co-annotators, or the fallback of one person labelling twice. This record covers what [mini-plan P07](11_CODEX_MINI_PLANS.md) asks of the tooling: what the annotation page does and does not guarantee, the 30 development messages that replace the constructed pilot seeds, and how agreement is computed from the page's export.

One thing was not possible on this date. The connection to the published annotation page's database failed, so nothing was written to it or read from it. Section 1 is a reading of the page's code (`tools/annotate.html`), not a live test. The live round trip is the first item in section 5.

## 1. What the annotation page guarantees

| Question | Finding |
|---|---|
| Where is a person's work stored? | In one document per annotator, `labels/{id}`. The id is made from the name the person types when they open the page |
| Who can read it? | Anyone who can open the page. The admin tab loads every annotator's document, shows each person's counts and the pairwise kappa, and its download button saves everyone's labels |
| Who can change it? | Anyone who types the same name loads that person's labels and overwrites them. The page has no way to know who is viewing |
| What does an annotator see with a message? | The text, and two chips above it for the item's `source` and `channel` when the item has them |
| How do messages get in? | The paste box on the admin tab gives every message a new id and keeps no link to its dataset row. A batch written to the database as a whole document (`corpus/{batchId}`) keeps the ids it was given |
| What does the export hold? | One row per annotator per item: `item_id`, `annotator`, `annotator_id`, `verdict` (`scam`, `legit`, `unsure` or `skip`), `playbook`, `seconds`, `at`, `source`, `text`. JSON or CSV |

Three consequences.

**Independence rests on procedure, not on access control.** The interface never shows one annotator another's answer on a message, but the admin tab is open to all and the download holds everything. This is acceptable for three people who know each other and are told the rule in section 4. It is not a blind study and the datasheet must not call it one.

**The chips give the answer away for development data.** In `dev`, every legitimate row has channel `web` and source `official_warning`, and no scam row has channel `web`. An annotator who notices that needs to read nothing. The pilot batch therefore carries no source and no channel on its items (section 2). The fresh collection has the same exposure if legitimate and scam messages come from different kinds of source, so the batches built for it should leave both fields off as well.

**The paste box is the wrong door for the pilot.** It would relabel the 30 messages with ids nobody can map back. The batch file is written to the database as one document instead.

## 2. The pilot batch

`data/pilot/batch-pilot-02.json` holds 30 messages from the `dev` split. `data/pilot/batch-pilot-02.key.json` maps each pilot id to its dataset row. Both come from one command and a test fails if either stops matching it:

```bash
python tools/pilot.py draw --dev data/kazscam_v0.1/dev.jsonl --out data/pilot/batch-pilot-02.json
```

| Provisional label | Russian | Kazakh | Total |
|---|---|---|---|
| Scam | 12 | 8 | 20 |
| Legitimate | 7 | 3 | 10 |

How the draw works:

- **Stratified** by provisional label and language, with the seed the evaluation uses (20260908). The provisional label is the collector's reading. It sets the mix and is written to the key. No annotator sees it.
- **At most two rows from one source group**, and a group already used is taken last. The 30 messages come from 26 of the 28 source groups; the article that supplies 18 of the 76 rows supplies 2. No notice appears in both its Russian and its Kazakh version.
- **An item is an id and a text.** No source, no channel, no dataset id. Dataset ids run in collection order and the legitimate rows were collected together, so the pilot ids are new and the order is shuffled.

A third of the batch is legitimate because that is the share the release tiers ask of a test set ([P06 record](15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md), section 7).

The 36 constructed seeds stay in `data/pilot/batch-pilot-01.json` as a record of what the page was first tried with. They are not data and no agreement figure is computed on them. The agreement tool ignores labels on any item outside the batch it is given.

### What this batch cannot measure

- **The verdict will be easy.** The ten legitimate messages are announcements from organisations: maintenance and outage notices, an admissions notice, a tax-committee notice. The shortest is 230 characters, and 19 of the 20 scam messages are shorter than that. None is the kind of genuine message people mistake for a scam, such as a one-time code or a delivery notice. High agreement on scam against legitimate will therefore say little about the hard boundary. `dev` has no such rows to draw; the fresh collection must look for them.
- **The script is the informative part.** No `dev` row has a script label yet, so the pilot is the first time anyone assigns one. Agreement on the script, and the pairs of scripts chosen against each other, are what the guideline revision should be read from.
- **The owner is not a blind annotator.** They collected every row and read all of them while the rules were written. The two co-annotators are the independent readings.
- **Thirty items give wide intervals.** The report prints an interval beside every kappa for that reason.

## 3. Agreement

```bash
python tools/pilot.py agreement --batch data/pilot/batch-pilot-02.json \
    --exports kazscam-labels.json --out data/pilot/agreement-pilot-02-round1.md \
    --json data/pilot/agreement-pilot-02-round1.json
```

The tool reads the page's export, JSON or CSV, and reports:

| Part | What it is |
|---|---|
| Coverage | Items labelled per annotator, by verdict, and items not labelled |
| Verdict, all annotators | Krippendorff's alpha for nominal labels, which allows any number of annotators and missing answers |
| Verdict, each pair | Share of same answers, Cohen's kappa, a 95% interval that resamples items, and kappa per class |
| Script | Over the items both annotators called a scam: share with the same script, Cohen's kappa, and the scripts chosen against each other |
| Provisional label | How many answers match the collector's reading. It is not gold, and the table is not an accuracy |
| Disagreements | Every item with two verdicts, or one verdict and two scripts, with each answer and an empty adjudication line for a person to fill |

Rules it follows:

- "Not sure" on the page is `ambiguous` in the dataset. A skipped item is not an answer and is counted as not labelled.
- Kappa is the function the evaluation harness uses (`saqbol.eval.metrics.cohens_kappa`). It is undefined, not 1, where both annotators used one category.
- Fewer than three annotators, or an annotator who did not finish, makes the report say "not a finished pilot" in its first lines. One annotator is an error.
- `--intra` is for the fallback in the roadmap, one person labelling twice under two names. The report is titled intra-annotator, and it says so when the two passes are less than 14 days apart.
- The tool computes. It does not suggest a label, break a tie or fill a gap.

The tests for it use invented answers to check the arithmetic. Those are test inputs. No agreement figure exists yet.

## 4. Procedure for the pilot

1. Write `batch-pilot-02` to the page's database as `corpus/batch-pilot-02` and remove `corpus/batch-pilot-01`, so annotators see the 30 messages and nothing else.
2. Each annotator opens the page under their own name and labels all 30 using the [guideline](07_ANNOTATION_GUIDELINE.md). They do not open the admin tab, do not use the download button and do not discuss a message until all three have finished. This is a rule they are asked to keep; the page does not enforce it.
3. When all three have finished, the owner downloads the labels once and runs the agreement command. The export and the report are the round-one record.
4. The three go through the disagreement list together, write one line of reasoning per item, and revise the guideline.
5. A second round on other development rows measures the revised guideline. Both rounds' figures are kept, with the method stated.

**Names.** The export holds the name each annotator typed, and a committed export is public. Before round one, each annotator either agrees to be named or types a pseudonym such as `A2`.

**Labels suggested by a model are never one of the three readings.**

## 5. Open

| Item | Needs |
|---|---|
| Live round trip: write the batch, label two items under two names, download, run the agreement command on the file | A working connection to the page's database |
| Round one | Two co-annotators, or the two-pass fallback |
| Guideline revision and round two | Round one |
| Per-person access control | Not planned. It needs the page to know who is viewing; the trusted-group rule stands in for it and is stated wherever agreement is reported |
