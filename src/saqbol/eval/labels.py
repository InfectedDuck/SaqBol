"""Annotation labels: two readings per row, and a logged decision where they differ.

docs/02_DATA_CONTRACTS.md section 6 ("Label records") is the contract. A label
record is one JSON file per annotation batch in `data/labels/`. It holds, for
each corpus row, what each of two annotators answered and the label that
follows. `tools/labels.py merge` writes the records; the split builder reads
them and nothing else sets a gold field on a released row.

The rule is small and it is here once. Two readings that agree on the label
and on the script are the label. Any difference needs a decision with a reason
and a name behind it. A record is checked against that rule when it is loaded,
so a label typed into the file by hand, with no reading that supports it and
no reason logged, stops the build.

A reading with no script is not a weaker vote for the other annotator's
script. The guideline lets an annotator answer "scam" and stop, which means
"one of the thirteen fits and I cannot say which". If the other annotator
named one, a single person chose the script, and that takes a decision like
any other difference.

A record says whether its two readings are two people's or two passes by one
person (the roadmap's fallback when no second annotator is found). The rule
is the same for both. The kind is carried to the split manifest so that
nobody reads the second as agreement between annotators.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from saqbol.playbooks.schema import PLAYBOOK_IDS

RECORD_SCHEMA = "kazscam-labels/1"
#: Contract section 6: the gold label set.
LABELS: tuple[str, ...] = ("scam", "legit", "ambiguous")
#: "Plainly a scam, and none of the thirteen describe it" (guideline section 4).
OTHER_SCAM = "other_scam"
#: What question two of the labelling page can answer.
SCRIPTS: tuple[str, ...] = (*PLAYBOOK_IDS, OTHER_SCAM)
#: `decided_by` when the two annotators settled it between them.
DISCUSSION = "discussion"
#: Whose the two readings of a record are: two people's, or one person's two passes.
INTER = "inter-annotator"
INTRA = "intra-annotator"
KINDS: tuple[str, ...] = (INTER, INTRA)


class LabelError(ValueError):
    """A reading, a decision or a label record that breaks the contract."""


def _check(label: object, script: object, where: str) -> None:
    if label not in LABELS:
        raise LabelError(f"{where}: label must be one of {LABELS}, got {label!r}")
    if script is None:
        return
    if label != "scam":
        raise LabelError(f"{where}: a script is named only with `scam`, got {label}/{script}")
    if script not in SCRIPTS:
        raise LabelError(f"{where}: unknown script {script!r}")


@dataclass(frozen=True)
class Reading:
    """What one annotator answered: the label, and the script if they named one."""

    label: str
    script: str | None = None

    def __post_init__(self) -> None:
        _check(self.label, self.script, "reading")

    def __str__(self) -> str:
        return f"{self.label}/{self.script}" if self.script else self.label


def parse_reading(value: object, where: str = "reading") -> Reading:
    """`scam/kz.delivery_link`, `scam`, `legit` or `ambiguous`, as the contract writes them."""
    if not isinstance(value, str) or not value:
        raise LabelError(f"{where}: expected a reading such as 'scam/kz.delivery_link'")
    label, _, script = value.partition("/")
    _check(label, script or None, where)
    return Reading(label, script or None)


@dataclass(frozen=True)
class Decision:
    """The logged answer to a disagreement."""

    label: str
    script: str | None
    reason: str
    decided_by: str


@dataclass(frozen=True)
class Gold:
    """The label a row is released with, and how it was reached."""

    label: str
    playbook_id: str | None
    adjudicated: bool
    reason: str | None = None
    decided_by: str | None = None


def difference(a: Reading, b: Reading) -> str | None:
    """`verdict`, `script`, or None when the two readings are the same."""
    if a.label != b.label:
        return "verdict"
    if a.script != b.script:
        return "script"
    return None


def resolve(
    a: Reading, b: Reading, decision: Decision | None = None, *, where: str = "row"
) -> Gold:
    """The gold fields that follow from two readings, by the table in the contract."""
    on = difference(a, b)
    if on is None:
        if decision is not None:
            raise LabelError(f"{where}: the readings agree ({a}), so there is nothing to decide")
        return Gold(a.label, a.script, adjudicated=False)
    if decision is None:
        raise LabelError(f"{where}: the readings differ on the {on} ({a} and {b}); no decision")
    _check(decision.label, decision.script, f"{where}: decision")
    reason = decision.reason.strip() if isinstance(decision.reason, str) else ""
    if not reason:
        raise LabelError(f"{where}: a decision needs a reason")
    if "\n" in reason or "\r" in reason:
        raise LabelError(f"{where}: the reason is one line")
    decided_by = decision.decided_by.strip() if isinstance(decision.decided_by, str) else ""
    if not decided_by:
        raise LabelError(f"{where}: a decision names who made it, or '{DISCUSSION}'")
    return Gold(decision.label, decision.script, True, reason, decided_by)


@dataclass(frozen=True)
class RowLabel:
    """One row of a label record."""

    corpus_id: str
    text_sha256: str
    annotator_a: Reading
    annotator_b: Reading
    gold: Gold

    def to_json(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "corpus_id": self.corpus_id,
            "text_sha256": self.text_sha256,
            "annotator_a": str(self.annotator_a),
            "annotator_b": str(self.annotator_b),
            "label": self.gold.label,
            "playbook_id": self.gold.playbook_id,
            "adjudicated": self.gold.adjudicated,
        }
        if self.gold.adjudicated:
            row["reason"] = self.gold.reason
            row["decided_by"] = self.gold.decided_by
        return row


def make_row(
    corpus_id: str,
    text_sha256: str,
    a: Reading,
    b: Reading,
    decision: Decision | None = None,
) -> RowLabel:
    return RowLabel(corpus_id, text_sha256, a, b, resolve(a, b, decision, where=corpus_id))


def row_from_json(payload: object, where: str) -> RowLabel:
    """One record row, checked: the label must follow from the readings."""
    if not isinstance(payload, Mapping):
        raise LabelError(f"{where}: a row is an object")
    corpus_id = payload.get("corpus_id")
    if not isinstance(corpus_id, str) or not corpus_id:
        raise LabelError(f"{where}: a row has no corpus_id")
    where = f"{where}: {corpus_id}"
    digest = payload.get("text_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise LabelError(f"{where}: text_sha256 must be a SHA-256 hex digest")
    a = parse_reading(payload.get("annotator_a"), f"{where}: annotator_a")
    b = parse_reading(payload.get("annotator_b"), f"{where}: annotator_b")
    adjudicated = payload.get("adjudicated")
    if not isinstance(adjudicated, bool):
        raise LabelError(f"{where}: adjudicated must be true or false")
    decision = None
    if adjudicated:
        decision = Decision(
            payload.get("label"),  # type: ignore[arg-type]
            payload.get("playbook_id"),  # type: ignore[arg-type]
            payload.get("reason"),  # type: ignore[arg-type]
            payload.get("decided_by"),  # type: ignore[arg-type]
        )
    gold = resolve(a, b, decision, where=where)
    if (payload.get("label"), payload.get("playbook_id")) != (gold.label, gold.playbook_id):
        raise LabelError(
            f"{where}: the record says {payload.get('label')}/{payload.get('playbook_id')}, "
            f"and the readings ({a} and {b}) give {gold.label}/{gold.playbook_id}"
        )
    return RowLabel(corpus_id, digest, a, b, gold)


def record_payload(
    *,
    batch: str,
    created_at: str,
    annotators: tuple[str, str],
    rows: Iterable[RowLabel],
    not_labelled: Iterable[str] = (),
    kind: str = INTER,
) -> dict[str, Any]:
    """A label record in the shape of the contract, rows in corpus-id order."""
    name_a, name_b = annotators
    if not name_a or not name_b or name_a == name_b:
        raise LabelError("a label record needs two different annotators")
    if kind not in KINDS:
        raise LabelError(f"a label record is one of {KINDS}, got {kind!r}")
    ordered = sorted(rows, key=lambda row: row.corpus_id)
    ids = [row.corpus_id for row in ordered]
    if len(set(ids)) != len(ids):
        raise LabelError("a label record names each row once")
    return {
        "schema": RECORD_SCHEMA,
        "batch": batch,
        "created_at": created_at,
        "kind": kind,
        "annotators": {"a": name_a, "b": name_b},
        "rows": [row.to_json() for row in ordered],
        "not_labelled": sorted(set(not_labelled)),
    }


@dataclass(frozen=True)
class Record:
    """One label record, read and checked."""

    batch: str
    kind: str
    rows: tuple[RowLabel, ...]


def read_record(path: str | os.PathLike[str]) -> Record:
    """One label record, each row checked against the resolution rule."""
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LabelError(f"{path.name} is not JSON: {exc}") from exc
    if not isinstance(payload, Mapping) or payload.get("schema") != RECORD_SCHEMA:
        raise LabelError(f"{path.name}: not a label record (schema {RECORD_SCHEMA})")
    names = payload.get("annotators")
    if not isinstance(names, Mapping) or not names.get("a") or names.get("a") == names.get("b"):
        raise LabelError(f"{path.name}: a label record needs two different annotators")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise LabelError(f'{path.name}: no "rows" list')
    # A record written before the field existed is two people's readings.
    kind = payload.get("kind", INTER)
    if kind not in KINDS:
        raise LabelError(f"{path.name}: kind must be one of {KINDS}, got {kind!r}")
    return Record(
        batch=str(payload.get("batch") or path.stem),
        kind=kind,
        rows=tuple(row_from_json(row, path.name) for row in rows),
    )


@dataclass(frozen=True)
class LabelSet:
    """Every label record of a directory, by corpus id."""

    rows: Mapping[str, RowLabel]
    files: tuple[str, ...] = ()
    #: Corpus ids whose two readings are one person's two passes.
    intra: frozenset[str] = frozenset()


def load_records(directory: str | os.PathLike[str]) -> LabelSet:
    """Every `*.json` label record in `directory`. A row in two records is an error."""
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"label directory not found: {directory}")
    rows: dict[str, RowLabel] = {}
    seen_in: dict[str, str] = {}
    files: list[str] = []
    intra: set[str] = set()
    for path in sorted(p for p in directory.glob("*.json") if p.is_file()):
        files.append(path.name)
        record = read_record(path)
        if record.kind == INTRA:
            intra.update(row.corpus_id for row in record.rows)
        for row in record.rows:
            if row.corpus_id in rows:
                raise LabelError(
                    f"{row.corpus_id} is labelled in both {seen_in[row.corpus_id]} and {path.name}"
                )
            rows[row.corpus_id] = row
            seen_in[row.corpus_id] = path.name
    return LabelSet(rows=rows, files=tuple(files), intra=frozenset(intra))
