#!/usr/bin/env python3
"""Labelling batches: draw one, measure agreement, log the decisions, write the label record.

Four commands, in the order they are used. docs/02_DATA_CONTRACTS.md section 6
("Label records") is the contract for what comes out at the end.

``batch`` takes the message rows of the corpus that no label record covers
yet and writes them in the shape ``tools/annotate.html`` stores under
``corpus/{batchId}``, with a key file beside the batch. An item is an id and
a text and nothing else, for the reason given in ``tools/pilot.py``: source
and channel give the label away. The key maps each item to its corpus row and
to the digest of the text that was shown. ``--scope`` follows the exposure
register: ``fresh`` rows are the ones collected for a held-out split, ``dev``
rows the ones the system was developed against.

``agreement`` is the pilot's agreement report over the two annotators of the
batch.

``adjudication`` writes one entry for every item the two annotators read
differently: a different label, different scripts, or a script only one of
them named. Each entry is filled in by hand with the label, the script, a
one-line reason and who decided. Running the command again keeps the entries
that are filled in, as long as the readings they answer have not changed.

``merge`` writes the label record. It refuses while an annotator has not
finished, while a difference has no decision, or when a decision answers
readings that have since changed. It computes nothing a person did not enter:
a label is two equal readings, or a logged decision.

The exports hold the names the annotators typed. Keep them under ``data/raw/``,
which is not tracked, and give ``merge`` a pseudonym for each annotator unless
they agreed to be named.

Usage
-----
  python tools/labels.py batch --out data/annotation/batch-annot-01.json
  python tools/labels.py agreement --batch data/annotation/batch-annot-01.json \\
      --exports data/raw/annotation/*.json --annotators ID_A ID_B
  python tools/labels.py adjudication --batch data/annotation/batch-annot-01.json \\
      --exports data/raw/annotation/*.json --annotators ID_A=annotator-1 ID_B=annotator-2
  python tools/labels.py merge --batch data/annotation/batch-annot-01.json \\
      --exports data/raw/annotation/*.json --annotators ID_A=annotator-1 ID_B=annotator-2 \\
      --out data/labels/batch-annot-01.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from saqbol.eval import labels as gold
from saqbol.eval import splits


def _load_pilot() -> Any:
    """`tools/pilot.py`, loaded once whether this file is run or imported by a test."""
    module = sys.modules.get("kazscam_pilot")
    if module is None:
        spec = importlib.util.spec_from_file_location(
            "kazscam_pilot", Path(__file__).with_name("pilot.py")
        )
        module = importlib.util.module_from_spec(spec)
        # Registered before it runs: its dataclasses look their own module up by name.
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


pilot = _load_pilot()

KEY_SCHEMA = "kazscam-annotation-key/1"
ADJUDICATION_SCHEMA = "kazscam-adjudication/1"
DEFAULT_SEED = 20261111
DEFAULT_CORPUS = Path("data/corpus")
SCOPES = ("fresh", "dev", "all")
HOW_TO_DECIDE = (
    "For each item set label (scam, legit or ambiguous), playbook_id (a script, only with scam, "
    "or null), reason (one line) and decided_by (a name, or 'discussion'). Leave the readings "
    "as they are."
)


class ToolError(ValueError):
    """The batch cannot be drawn, or the exports do not make a label record."""


# ---------------------------------------------------------------------------
# batch
# ---------------------------------------------------------------------------


def candidates(
    corpus_rows: Sequence[Mapping[str, Any]],
    *,
    exposed: Collection[str] = (),
    labelled: Collection[str] = (),
    scope: str = "fresh",
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The rows still to label, as the split builder would release them.

    Going through `to_released_row` means the text shown to an annotator and
    its digest are the ones the build will check the label against.
    """
    if scope not in SCOPES:
        raise ToolError(f"scope must be one of {SCOPES}, got {scope!r}")
    counts = {"labelled": 0, "fresh": 0, "dev": 0}
    out: list[dict[str, Any]] = []
    messages = [r for r in corpus_rows if str(r.get("text_kind", "message")) == "message"]
    for row in sorted(messages, key=lambda r: str(r.get("id", ""))):
        released = splits.to_released_row(row, "")
        if released["corpus_id"] in labelled:
            counts["labelled"] += 1
            continue
        where = "dev" if released["corpus_id"] in exposed else "fresh"
        counts[where] += 1
        if scope in ("all", where):
            out.append(released)
    return out, counts


def build_batch(
    rows: Sequence[Mapping[str, Any]],
    *,
    batch: str,
    prefix: str,
    seed: int,
    scope: str,
    created_at: str,
    corpus_path: str,
    counts: Mapping[str, int],
    limit: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The document the annotator page stores, and the key that explains it."""
    chosen = list(rows)
    random.Random(seed).shuffle(chosen)
    if limit is not None:
        chosen = chosen[:limit]
    if not chosen:
        raise ToolError(
            f"no message row to label in scope {scope!r}: {counts['fresh']} fresh and "
            f"{counts['dev']} dev rows have no label record, {counts['labelled']} already do"
        )
    ids = [f"{prefix}-{i:03d}" for i in range(1, len(chosen) + 1)]
    document = {
        "items": [{"id": i, "text": row["text"]} for i, row in zip(ids, chosen, strict=True)],
        "source": "corpus",
        "note": (
            f"Labelling batch {batch}: {len(chosen)} messages. Items carry no source and no "
            "channel on purpose. The key file beside this one maps each id to its corpus row."
        ),
        "createdAt": created_at,
    }
    key = {
        "schema": KEY_SCHEMA,
        "batch": batch,
        "created_at": created_at,
        "seed": seed,
        "drawn_from": {
            "path": corpus_path,
            "scope": scope,
            "unlabelled_fresh_rows": counts["fresh"],
            "unlabelled_dev_rows": counts["dev"],
            "rows_already_labelled": counts["labelled"],
        },
        "provisional_label": "the collector's reading, not an annotation and not gold",
        "items": [
            {
                "item_id": i,
                "corpus_id": row["corpus_id"],
                "text_sha256": row["text_sha256"],
                "lang": row["lang"],
                "provisional_label": row["label"],
                "hard_negative": bool(row["hard_negative"]),
            }
            for i, row in zip(ids, chosen, strict=True)
        ],
    }
    return document, key


# ---------------------------------------------------------------------------
# reading a batch and its exports
# ---------------------------------------------------------------------------


def read_batch(batch_path: Path, key_path: Path | None = None) -> tuple[dict, dict]:
    """The batch document and its key, checked against each other."""
    batch = json.loads(Path(batch_path).read_text(encoding="utf-8"))
    key_path = key_path or pilot.key_path_for(Path(batch_path))
    if not key_path.is_file():
        raise ToolError(f"{key_path} not found: a label record needs the batch's key")
    key = json.loads(key_path.read_text(encoding="utf-8"))
    if key.get("schema") != KEY_SCHEMA:
        raise ToolError(
            f"{key_path.name} is not a labelling key (schema {KEY_SCHEMA}). A pilot batch "
            "measures agreement; its answers are not merged into labels."
        )
    shown = [str(item["id"]) for item in batch["items"]]
    keyed = [str(entry["item_id"]) for entry in key["items"]]
    if shown != keyed:
        raise ToolError(f"{key_path.name} does not describe the items of {Path(batch_path).name}")
    return batch, key


def annotator_names(specs: Sequence[str]) -> tuple[tuple[str, str], tuple[str, str]]:
    """`ID` or `ID=PSEUDONYM`, twice: the ids in the exports, and the names written to files."""
    if len(specs) != 2:
        raise ToolError("name exactly two annotators, as ID or ID=PSEUDONYM")
    ids, names = [], []
    for spec in specs:
        annotator, _, pseudonym = spec.partition("=")
        annotator, pseudonym = annotator.strip(), pseudonym.strip()
        if not annotator:
            raise ToolError(f"{spec!r} names no annotator id")
        ids.append(annotator)
        names.append(pseudonym or annotator)
    if ids[0] == ids[1] or names[0] == names[1]:
        raise ToolError("the two annotators must be different, and so must their names")
    return (ids[0], ids[1]), (names[0], names[1])


def only(exports: Sequence[Sequence[Mapping[str, Any]]], ids: Collection[str]) -> list[list]:
    """The export rows of the named annotators."""
    return [[row for row in rows if str(row["annotator_id"]) in ids] for rows in exports]


def paired_readings(
    batch: Mapping[str, Any],
    exports: Sequence[Sequence[Mapping[str, Any]]],
    ids: tuple[str, str],
) -> tuple[dict[str, tuple[gold.Reading, gold.Reading]], list[str]]:
    """Both annotators' readings per item, and the items that lack one."""
    item_ids = [str(item["id"]) for item in batch["items"]]
    got = pilot.collect(only(exports, ids), item_ids)
    for annotator in ids:
        if annotator not in got.labels:
            seen = sorted({str(row["annotator_id"]) for rows in exports for row in rows})
            raise ToolError(
                f"no answer from {annotator!r} on this batch. Annotator ids in the exports: "
                f"{', '.join(seen) or 'none'}"
            )
    first, second = (got.labels[annotator] for annotator in ids)
    pairs: dict[str, tuple[gold.Reading, gold.Reading]] = {}
    missing: list[str] = []
    problems: list[str] = []
    for item in item_ids:
        if item not in first or item not in second:
            missing.append(item)
            continue
        try:
            pairs[item] = (
                gold.Reading(first[item].verdict, first[item].script),
                gold.Reading(second[item].verdict, second[item].script),
            )
        except gold.LabelError as exc:
            problems.append(f"{item}: {exc}")
    if problems:
        raise ToolError("answers that are not in the label set:\n  " + "\n  ".join(problems))
    return pairs, missing


# ---------------------------------------------------------------------------
# adjudication
# ---------------------------------------------------------------------------


def _is_filled(entry: Mapping[str, Any]) -> bool:
    return entry.get("label") is not None


def adjudication_template(
    batch: Mapping[str, Any],
    pairs: Mapping[str, tuple[gold.Reading, gold.Reading]],
    *,
    batch_name: str,
    names: tuple[str, str],
    previous: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """One entry per item the two readings differ on.

    An entry from `previous` is kept when it is filled in and answers the same
    two readings. A filled entry whose readings changed is dropped and
    counted, because the decision was made about answers that no longer stand.
    """
    texts = {str(item["id"]): str(item["text"]) for item in batch["items"]}
    earlier: dict[str, Mapping[str, Any]] = {}
    if previous is not None:
        if previous.get("annotators") != {"a": names[0], "b": names[1]}:
            raise ToolError(
                "the adjudication file was written for other annotators, or the same two in "
                "the other order"
            )
        earlier = {str(entry["item_id"]): entry for entry in previous.get("items", [])}
    tally = {"kept": 0, "reset": 0, "new": 0}
    items = []
    for item, (a, b) in pairs.items():
        on = gold.difference(a, b)
        if on is None:
            continue
        entry: dict[str, Any] = {
            "item_id": item,
            "text": texts[item],
            "on": on,
            "annotator_a": str(a),
            "annotator_b": str(b),
            "label": None,
            "playbook_id": None,
            "reason": "",
            "decided_by": "",
        }
        old = earlier.get(item)
        if old is not None and _is_filled(old):
            if (old.get("annotator_a"), old.get("annotator_b")) == (str(a), str(b)):
                entry.update({k: old.get(k) for k in ("label", "playbook_id", "reason")})
                entry["decided_by"] = old.get("decided_by")
                tally["kept"] += 1
            else:
                tally["reset"] += 1
        else:
            tally["new"] += 1
        items.append(entry)
    document = {
        "schema": ADJUDICATION_SCHEMA,
        "batch": batch_name,
        "annotators": {"a": names[0], "b": names[1]},
        "how": HOW_TO_DECIDE,
        "items": items,
    }
    return document, tally


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------


def _decisions(
    adjudication: Mapping[str, Any] | None, names: tuple[str, str]
) -> dict[str, Mapping[str, Any]]:
    if adjudication is None:
        return {}
    if adjudication.get("schema") != ADJUDICATION_SCHEMA:
        raise ToolError(f"not an adjudication file (schema {ADJUDICATION_SCHEMA})")
    if adjudication.get("annotators") != {"a": names[0], "b": names[1]}:
        raise ToolError(
            "the adjudication file was written for other annotators, or the same two in the "
            "other order"
        )
    return {str(entry["item_id"]): entry for entry in adjudication.get("items", [])}


def merge(
    batch: Mapping[str, Any],
    key: Mapping[str, Any],
    exports: Sequence[Sequence[Mapping[str, Any]]],
    *,
    ids: tuple[str, str],
    names: tuple[str, str],
    adjudication: Mapping[str, Any] | None = None,
    created_at: str,
    allow_missing: bool = False,
    intra: bool = False,
) -> dict[str, Any]:
    """The label record for one batch, or a `ToolError` that lists everything in the way."""
    pairs, missing = paired_readings(batch, exports, ids)
    decisions = _decisions(adjudication, names)
    by_item = {str(entry["item_id"]): entry for entry in key["items"]}
    problems: list[str] = []
    if missing and not allow_missing:
        problems.append(
            f"{len(missing)} items have fewer than two readings ({', '.join(missing[:8])}"
            f"{', ...' if len(missing) > 8 else ''}). Finish the batch, or pass --allow-missing "
            "to leave them unlabelled."
        )
    rows: list[gold.RowLabel] = []
    for item, (a, b) in pairs.items():
        entry = decisions.get(item)
        decision = None
        if gold.difference(a, b) is None:
            if entry is not None and _is_filled(entry):
                problems.append(
                    f"{item}: a decision is logged, and the two readings now agree ({a}). "
                    "Run `adjudication` again."
                )
                continue
        elif entry is None or not _is_filled(entry):
            problems.append(f"{item}: the readings differ ({a} and {b}) and no decision is logged")
            continue
        elif (entry.get("annotator_a"), entry.get("annotator_b")) != (str(a), str(b)):
            problems.append(
                f"{item}: the decision answers {entry.get('annotator_a')} and "
                f"{entry.get('annotator_b')}, and the readings are now {a} and {b}. "
                "Run `adjudication` again."
            )
            continue
        else:
            decision = gold.Decision(
                entry.get("label"),
                entry.get("playbook_id") or None,
                entry.get("reason"),
                entry.get("decided_by"),
            )
        keyed = by_item[item]
        try:
            rows.append(gold.make_row(keyed["corpus_id"], keyed["text_sha256"], a, b, decision))
        except gold.LabelError as exc:
            problems.append(f"{item}: {exc}")
    if problems:
        raise ToolError("no label record written:\n  " + "\n  ".join(problems))
    return gold.record_payload(
        batch=str(key["batch"]),
        created_at=created_at,
        annotators=names,
        rows=rows,
        not_labelled=[by_item[item]["corpus_id"] for item in missing],
        kind=gold.INTRA if intra else gold.INTER,
    )


def labelled_elsewhere(payload: Mapping[str, Any], out: Path) -> list[str]:
    """Rows of this record that another record in the same directory already labels."""
    mine = {row["corpus_id"] for row in payload["rows"]}
    clashes: list[str] = []
    if not out.parent.is_dir():
        return clashes
    for path in sorted(p for p in out.parent.glob("*.json") if p.is_file()):
        if path.resolve() == out.resolve():
            continue
        theirs = {row.corpus_id for row in gold.read_record(path).rows}
        clashes += [f"{corpus_id} (in {path.name})" for corpus_id in sorted(mine & theirs)]
    return clashes


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="labels.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    drawer = commands.add_parser("batch", help="write a labelling batch from unlabelled rows")
    drawer.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS, help="corpus directory")
    drawer.add_argument("--out", type=Path, required=True, help="batch file to write")
    drawer.add_argument("--scope", choices=SCOPES, default="fresh")
    drawer.add_argument("--exposure", type=Path, default=None, help="exposure register")
    drawer.add_argument("--labels", type=Path, default=None, help="directory of label records")
    drawer.add_argument("--limit", type=int, default=None, help="at most this many items")
    drawer.add_argument("--seed", type=int, default=DEFAULT_SEED)
    drawer.add_argument("--prefix", default=None, help="prefix of the item ids")
    drawer.add_argument("--date", default=None, help="creation date to record (default: today)")
    drawer.add_argument("--force", action="store_true", help="replace an existing batch file")

    def shared(command: argparse.ArgumentParser, *, annotators_required: bool) -> None:
        command.add_argument("--batch", type=Path, required=True, help="the batch file")
        command.add_argument("--exports", type=Path, nargs="+", required=True, help="exports")
        command.add_argument("--key", type=Path, default=None, help="key (default: beside batch)")
        command.add_argument(
            "--annotators",
            nargs=2,
            required=annotators_required,
            metavar="ID[=PSEUDONYM]",
            help="the two annotators, by the annotator_id in the exports",
        )

    scorer = commands.add_parser("agreement", help="agreement between the two annotators")
    shared(scorer, annotators_required=False)
    scorer.add_argument("--out", type=Path, default=None, help="Markdown report to write")
    scorer.add_argument("--json", type=Path, default=None, help="the same report as JSON")
    scorer.add_argument("--intra", action="store_true", help="two passes by one person")
    scorer.add_argument("--seed", type=int, default=pilot.DEFAULT_SEED)
    scorer.add_argument("--resamples", type=int, default=10_000)

    decider = commands.add_parser("adjudication", help="list the items that need a decision")
    shared(decider, annotators_required=True)
    decider.add_argument("--out", type=Path, default=None, help="adjudication file")

    merger = commands.add_parser("merge", help="write the label record")
    shared(merger, annotators_required=True)
    merger.add_argument("--adjudication", type=Path, default=None, help="adjudication file")
    merger.add_argument("--out", type=Path, required=True, help="label record to write")
    merger.add_argument("--allow-missing", action="store_true", help="leave unread items out")
    merger.add_argument("--intra", action="store_true", help="two passes by one person")
    merger.add_argument("--date", default=None, help="creation date to record (default: today)")
    return parser


def adjudication_path_for(batch_path: Path) -> Path:
    return batch_path.with_name(batch_path.stem + ".adjudication.json")


def _batch(args: argparse.Namespace) -> int:
    if args.out.exists() and not args.force:
        raise ToolError(
            f"{args.out} exists. A batch that annotators may have opened is not redrawn; "
            "choose another name, or pass --force."
        )
    rows = splits.load_corpus(args.corpus)
    register = args.exposure or args.corpus.parent / splits.EXPOSURE_FILENAME
    exposed: set[str] = set()
    if args.exposure is not None or register.is_file():
        exposed = splits.exposed_corpus_ids(rows, splits.load_exposure(register))
    records = args.labels or args.corpus.parent / splits.LABELS_DIRNAME
    labelled: set[str] = set()
    if args.labels is not None or records.is_dir():
        labelled = set(gold.load_records(records).rows)
    todo, counts = candidates(rows, exposed=exposed, labelled=labelled, scope=args.scope)
    batch_name = args.out.stem
    document, key = build_batch(
        todo,
        batch=batch_name,
        prefix=args.prefix or batch_name.removeprefix("batch-"),
        seed=args.seed,
        scope=args.scope,
        created_at=args.date or date.today().isoformat(),
        corpus_path=args.corpus.as_posix(),
        counts=counts,
        limit=args.limit,
    )
    pilot.write_json(args.out, document)
    pilot.write_json(pilot.key_path_for(args.out), key)
    mix = Counter((e["provisional_label"], e["lang"]) for e in key["items"])
    print(f"{len(key['items'])} items in scope {args.scope} ({len(todo)} rows had no label)")
    for (label, lang), n in sorted(mix.items()):
        print(f"  collected as {label}/{lang}: {n}")
    print(f"wrote {args.out} and {pilot.key_path_for(args.out)}")
    return 0


def _agreement(args: argparse.Namespace) -> int:
    batch, key = read_batch(args.batch, args.key)
    exports = [pilot.read_export(path) for path in args.exports]
    if args.annotators:
        ids, _ = annotator_names(args.annotators)
        exports = only(exports, ids)
    report = pilot.analyse(
        batch,
        exports,
        key=key,
        intra=args.intra,
        seed=args.seed,
        n_resamples=args.resamples,
        batch_name=args.batch.stem,
        needed=2,
        what="batch",
    )
    text = pilot.render(
        report,
        title="Annotation agreement",
        tool="tools/labels.py agreement",
        adjudication_lines=False,
    )
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)
    if args.json is not None:
        pilot.write_json(args.json, report)
        print(f"wrote {args.json}")
    return 0


def _adjudication(args: argparse.Namespace) -> int:
    batch, _ = read_batch(args.batch, args.key)
    ids, names = annotator_names(args.annotators)
    pairs, missing = paired_readings(batch, [pilot.read_export(p) for p in args.exports], ids)
    out = args.out or adjudication_path_for(args.batch)
    previous = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
    document, tally = adjudication_template(
        batch, pairs, batch_name=args.batch.stem, names=names, previous=previous
    )
    pilot.write_json(out, document)
    print(
        f"{len(document['items'])} of {len(pairs)} items read twice need a decision: "
        f"{tally['kept']} already decided, {tally['new']} to decide"
    )
    if tally["reset"]:
        print(f"  {tally['reset']} decisions were dropped: the readings they answered changed")
    if missing:
        print(f"  {len(missing)} items have fewer than two readings and are not listed")
    print(f"wrote {out}")
    return 0


def _merge(args: argparse.Namespace) -> int:
    batch, key = read_batch(args.batch, args.key)
    ids, names = annotator_names(args.annotators)
    adjudication_path = args.adjudication or adjudication_path_for(args.batch)
    if args.adjudication is not None and not adjudication_path.is_file():
        raise ToolError(f"{adjudication_path} not found")
    adjudication = None
    if adjudication_path.is_file():
        adjudication = json.loads(adjudication_path.read_text(encoding="utf-8"))
    payload = merge(
        batch,
        key,
        [pilot.read_export(path) for path in args.exports],
        ids=ids,
        names=names,
        adjudication=adjudication,
        created_at=args.date or date.today().isoformat(),
        allow_missing=args.allow_missing,
        intra=args.intra,
    )
    clashes = labelled_elsewhere(payload, args.out)
    if clashes:
        raise ToolError(
            "no label record written; rows already labelled in another record:\n  "
            + "\n  ".join(clashes)
        )
    pilot.write_json(args.out, payload)
    gold.read_record(args.out)
    rows = payload["rows"]
    print(
        f"{len(rows)} rows labelled, {sum(1 for row in rows if row['adjudicated'])} by a logged "
        f"decision; {len(payload['not_labelled'])} left unlabelled"
    )
    print(f"wrote {args.out}")
    return 0


COMMANDS = {
    "batch": _batch,
    "agreement": _agreement,
    "adjudication": _adjudication,
    "merge": _merge,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except (
        ToolError,
        gold.LabelError,
        splits.CorpusError,
        pilot.PilotError,
        OSError,
        KeyError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
