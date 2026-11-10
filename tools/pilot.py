#!/usr/bin/env python3
"""Annotation pilot helper: draw the pilot batch, then measure agreement.

Two commands.

``draw`` picks the pilot items from the ``dev`` split and writes them in the
shape ``tools/annotate.html`` stores under ``corpus/{batchId}``, with a key
file beside the batch that maps each pilot id back to its dataset row.

The batch carries an id and a text for each item and nothing else. That is on
purpose. The annotator page shows ``source`` and ``channel`` as chips above
the message, and in ``dev`` every legitimate row has channel ``web`` and
source ``official_warning`` while no scam row has that channel, so either
field would hand over the answer. Dataset ids are replaced too, because they
run in collection order and the legitimate rows were collected together. The
items are shuffled and numbered in the order they will be shown.

The draw is stratified by provisional label and language, and takes at most
two rows from one source group, so one article with eighteen quotes cannot be
most of the pilot. The provisional label is the collector's reading. It
decides the mix and is written to the key; it is never shown to an annotator.

``agreement`` reads what the page's "Download labels" button saves, JSON or
CSV, and reports coverage per annotator, pairwise Cohen's kappa on the verdict
with an interval, Krippendorff's alpha over all annotators, agreement on the
script where both said scam, and every item the annotators split on. It
computes; it does not label, adjudicate or fill a gap. An unfinished pilot is
reported as unfinished.

Usage
-----
  python tools/pilot.py draw --dev data/kazscam_v0.1/dev.jsonl \\
      --out data/pilot/batch-pilot-02.json
  python tools/pilot.py agreement --batch data/pilot/batch-pilot-02.json \\
      --exports kazscam-labels.json --out pilot-agreement.md
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np

from saqbol.eval import metrics

KEY_SCHEMA = "kazscam-pilot-key/1"
REPORT_SCHEMA = "kazscam-pilot-agreement/1"
DEFAULT_SEED = 20260908
DEFAULT_PREFIX = "ks-p02"

#: Rows to draw per (provisional label, language). A third of the pilot is
#: legitimate, the share the release tiers ask of a test set, so the decision
#: the guideline most needs to settle is exercised often enough to measure.
#: Kazakh comes first in each label because it has the fewest source groups:
#: the draw fills strata in this order and prefers sources it has not used.
QUOTAS: dict[tuple[str, str], int] = {
    ("legit", "kk"): 3,
    ("legit", "ru"): 7,
    ("scam", "kk"): 8,
    ("scam", "ru"): 12,
}
MAX_PER_GROUP = 2

#: The page's verdict buttons, and the dataset label each one stands for.
VERDICTS = {"scam": "scam", "legit": "legit", "unsure": "ambiguous"}
LABELS = ("scam", "legit", "ambiguous")
SKIP = "skip"
NO_SCRIPT = "(none)"

#: Shortest gap between two passes by one person for the second to count as
#: blind to the first (roadmap, fallback for a pilot with no co-annotators).
MIN_INTRA_GAP = timedelta(days=14)
ANNOTATORS_NEEDED = 3
EXPORT_COLUMNS = ("item_id", "annotator", "annotator_id", "verdict", "playbook", "at")


class PilotError(ValueError):
    """The draw cannot be made, or the exports cannot be read as a pilot."""


# ---------------------------------------------------------------------------
# draw
# ---------------------------------------------------------------------------


def read_rows(path: Path) -> list[dict[str, Any]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rows_digest(rows: Iterable[Mapping[str, Any]]) -> str:
    """Fingerprint of the ids and texts drawn from, whatever the file layout."""
    lines = sorted(f"{row['id']}\t{text_sha256(row['text'])}" for row in rows)
    return "sha256:" + hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def draw(
    rows: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    quotas: Mapping[tuple[str, str], int] = QUOTAS,
    max_per_group: int = MAX_PER_GROUP,
) -> list[Mapping[str, Any]]:
    """The pilot rows, in the order they will be shown.

    Each row goes to the stratum's source group that has given the fewest
    rows so far, counted over the whole draw, in a seeded order among equals.
    So a stratum draws from as many sources as it can before it takes a
    second row from any, and it avoids a source another stratum has used: a
    Russian and a Kazakh rendering of one notice share a group, and showing
    both makes the second answer a copy of the first.
    """
    rng = random.Random(seed)
    taken: Counter[str] = Counter()
    chosen: list[Mapping[str, Any]] = []
    for (label, lang), quota in quotas.items():
        by_group: dict[str, list[Mapping[str, Any]]] = {}
        for row in sorted(rows, key=lambda r: r["id"]):
            if row["label"] == label and row["lang"] == lang:
                by_group.setdefault(row.get("source_group") or row["id"], []).append(row)
        groups = sorted(by_group)
        rng.shuffle(groups)
        for group in groups:
            rng.shuffle(by_group[group])
        for n_picked in range(quota):
            open_groups = [g for g in groups if by_group[g] and taken[g] < max_per_group]
            if not open_groups:
                raise PilotError(
                    f"only {n_picked} of {quota} {label}/{lang} rows can be drawn with at most "
                    f"{max_per_group} per source group"
                )
            group = min(open_groups, key=lambda g: taken[g])
            chosen.append(by_group[group].pop())
            taken[group] += 1
    rng.shuffle(chosen)
    return chosen


def build_batch(
    selected: Sequence[Mapping[str, Any]],
    *,
    all_rows: Sequence[Mapping[str, Any]],
    dev_path: str,
    batch: str,
    prefix: str,
    seed: int,
    created_at: str,
    quotas: Mapping[tuple[str, str], int] = QUOTAS,
    max_per_group: int = MAX_PER_GROUP,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The document the annotator page stores, and the key that explains it."""
    ids = [f"{prefix}-{i:03d}" for i in range(1, len(selected) + 1)]
    document = {
        "items": [{"id": pid, "text": row["text"]} for pid, row in zip(ids, selected, strict=True)],
        "source": "dev",
        "note": (
            f"Annotation pilot: {len(selected)} messages drawn from the dev split. "
            "Items carry no source and no channel on purpose: in dev either one gives the "
            "label away. The key file beside this one maps each id to its dataset row."
        ),
        "createdAt": created_at,
    }
    key = {
        "schema": KEY_SCHEMA,
        "batch": batch,
        "created_at": created_at,
        "seed": seed,
        "drawn_from": {"path": dev_path, "n_rows": len(all_rows), "digest": rows_digest(all_rows)},
        "quotas": {f"{label}/{lang}": n for (label, lang), n in quotas.items()},
        "max_per_source_group": max_per_group,
        "provisional_label": "the collector's reading, not an annotation and not gold",
        "items": [
            {
                "pilot_id": pid,
                "row_id": row["id"],
                "source_group": row.get("source_group") or row["id"],
                "lang": row["lang"],
                "provisional_label": row["label"],
                "hard_negative": bool(row.get("hard_negative")),
                "text_sha256": text_sha256(row["text"]),
            }
            for pid, row in zip(ids, selected, strict=True)
        ],
    }
    return document, key


def key_path_for(batch_path: Path) -> Path:
    return batch_path.with_name(batch_path.stem + ".key.json")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# agreement: reading the exports
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Label:
    verdict: str
    script: str | None
    at: str


@dataclass
class Collected:
    names: dict[str, str] = field(default_factory=dict)
    labels: dict[str, dict[str, Label]] = field(default_factory=dict)
    n_skipped: int = 0
    n_outside_batch: int = 0
    n_superseded: int = 0


def read_export(path: Path) -> list[dict[str, Any]]:
    """Rows of one "Download labels" file, JSON or CSV."""
    path = Path(path)
    # utf-8-sig: the CSV starts with a byte-order mark so Excel reads Cyrillic.
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        rows: list[dict[str, Any]] = list(csv.DictReader(io.StringIO(text, newline="")))
    else:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PilotError(f"{path} is not JSON: {exc}") from exc
        rows = payload.get("rows") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise PilotError(f'{path} has no "rows" list; it is not a label export')
    for row in rows:
        missing = [column for column in ("item_id", "annotator_id", "verdict") if column not in row]
        if missing:
            raise PilotError(f"{path}: a row has no {', '.join(missing)}")
    return rows


def collect(exports: Iterable[Sequence[Mapping[str, Any]]], item_ids: Sequence[str]) -> Collected:
    """One answer per annotator per pilot item.

    Rows for items outside the batch and skipped items are counted and left
    out. Where two exports hold different answers from one annotator for one
    item, the later answer is the one the page would show, so it is kept.
    """
    known = set(item_ids)
    out = Collected()
    for rows in exports:
        for row in rows:
            annotator = str(row["annotator_id"])
            item = str(row["item_id"])
            verdict = str(row["verdict"])
            if item not in known:
                out.n_outside_batch += 1
                continue
            out.names.setdefault(annotator, str(row.get("annotator") or annotator))
            mine = out.labels.setdefault(annotator, {})
            if verdict == SKIP:
                answer = None
            elif verdict in VERDICTS:
                script = str(row.get("playbook") or "") or None
                answer = Label(
                    VERDICTS[verdict],
                    script if verdict == "scam" else None,
                    str(row.get("at") or ""),
                )
            else:
                raise PilotError(f"unknown verdict {verdict!r} from {annotator} on {item}")
            previous = mine.get(item, ...)
            if previous is ... or previous == answer:
                mine[item] = answer
                continue
            out.n_superseded += 1
            if (answer.at if answer else "") >= (previous.at if previous else ""):
                mine[item] = answer
    for annotator, mine in out.labels.items():
        out.n_skipped += sum(1 for answer in mine.values() if answer is None)
        out.labels[annotator] = {item: answer for item, answer in mine.items() if answer}
    return out


# ---------------------------------------------------------------------------
# agreement: the statistics
# ---------------------------------------------------------------------------


def krippendorff_alpha(units: Iterable[Sequence[str]]) -> float:
    """Krippendorff's alpha for nominal labels, any number of annotators.

    A unit is the labels one item received. Units with fewer than two labels
    carry no information about agreement and are left out. `nan` when every
    label is the same category, where chance agreement is already total.
    """
    coincidence: Counter[tuple[str, str]] = Counter()
    for unit in units:
        if len(unit) < 2:
            continue
        weight = 1.0 / (len(unit) - 1)
        for i, a in enumerate(unit):
            for j, b in enumerate(unit):
                if i != j:
                    coincidence[(a, b)] += weight
    totals: Counter[str] = Counter()
    for (a, _), value in coincidence.items():
        totals[a] += value
    n = sum(totals.values())
    if n <= 1:
        return math.nan
    observed = sum(v for (a, b), v in coincidence.items() if a != b) / n
    expected = sum(totals[a] * totals[b] for a in totals for b in totals if a != b) / (n * (n - 1))
    if expected <= 1e-12:
        return math.nan
    return 1.0 - observed / expected


def kappa_interval(
    a: Sequence[str], b: Sequence[str], *, seed: int, n_resamples: int, alpha: float = 0.05
) -> tuple[float, float] | None:
    """Percentile interval of Cohen's kappa, resampling items.

    Resamples in which both annotators used a single category have no kappa
    and are left out; `None` when that is all of them or there is one item.
    """
    if len(a) < 2:
        return None
    space = sorted(set(a) | set(b))
    codes_a = np.array([space.index(v) for v in a])
    codes_b = np.array([space.index(v) for v in b])
    rng = np.random.default_rng(seed)
    index = rng.integers(0, len(a), size=(n_resamples, len(a)))
    sample_a, sample_b = codes_a[index], codes_b[index]
    observed = (sample_a == sample_b).mean(axis=1)
    expected = np.zeros(n_resamples)
    for code in range(len(space)):
        expected += (sample_a == code).mean(axis=1) * (sample_b == code).mean(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        kappas = np.where(1.0 - expected > 1e-12, (observed - expected) / (1.0 - expected), np.nan)
    kappas = kappas[~np.isnan(kappas)]
    if kappas.size == 0:
        return None
    lo, hi = np.percentile(kappas, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi)


def _num(value: float | None, ndigits: int = 4) -> float | None:
    if value is None or math.isnan(value):
        return None
    return round(float(value), ndigits)


def pair_report(
    first: Mapping[str, Label], second: Mapping[str, Label], *, seed: int, n_resamples: int
) -> dict[str, Any]:
    shared = sorted(set(first) & set(second))
    a = [first[item].verdict for item in shared]
    b = [second[item].verdict for item in shared]
    out: dict[str, Any] = {"n_items": len(shared), "agreement": None, "kappa": None}
    out["kappa_ci95"] = None
    out["kappa_per_class"] = dict.fromkeys(LABELS)
    if shared:
        out["agreement"] = _num(sum(x == y for x, y in zip(a, b, strict=True)) / len(shared))
        out["kappa"] = _num(metrics.cohens_kappa(a, b, labels=LABELS))
        interval = kappa_interval(a, b, seed=seed, n_resamples=n_resamples)
        out["kappa_ci95"] = None if interval is None else [_num(interval[0]), _num(interval[1])]
        per_class = metrics.kappa_per_class(a, b, labels=LABELS)
        out["kappa_per_class"] = {label: _num(per_class[label]) for label in LABELS}

    both_scam = [i for i in shared if first[i].verdict == second[i].verdict == "scam"]
    scripts_a = [first[i].script or NO_SCRIPT for i in both_scam]
    scripts_b = [second[i].script or NO_SCRIPT for i in both_scam]
    script: dict[str, Any] = {"n_items": len(both_scam), "agreement": None, "kappa": None}
    confused: Counter[tuple[str, str]] = Counter()
    if both_scam:
        same = sum(x == y for x, y in zip(scripts_a, scripts_b, strict=True))
        script["agreement"] = _num(same / len(both_scam))
        script["kappa"] = _num(metrics.cohens_kappa(scripts_a, scripts_b))
        for x, y in zip(scripts_a, scripts_b, strict=True):
            if x != y:
                confused[tuple(sorted((x, y)))] += 1
    script["confused"] = [
        {"scripts": list(pair), "n": n} for pair, n in sorted(confused.items(), key=_by_count)
    ]
    out["script"] = script
    return out


def _by_count(entry: tuple[tuple[str, str], int]) -> tuple[int, tuple[str, str]]:
    return (-entry[1], entry[0])


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def intra_gap(first: Mapping[str, Label], second: Mapping[str, Label]) -> timedelta | None:
    """Time from the end of the earlier pass to the start of the later one."""
    spans = []
    for labels in (first, second):
        times = [_parse_time(label.at) for label in labels.values()]
        if not times or any(t is None for t in times):
            return None
        spans.append((min(times), max(times)))
    spans.sort()
    return spans[1][0] - spans[0][1]


def analyse(
    batch: Mapping[str, Any],
    exports: Iterable[Sequence[Mapping[str, Any]]],
    *,
    key: Mapping[str, Any] | None = None,
    intra: bool = False,
    seed: int = DEFAULT_SEED,
    n_resamples: int = 10_000,
    batch_name: str = "",
) -> dict[str, Any]:
    items = {str(item["id"]): str(item["text"]) for item in batch["items"]}
    got = collect(exports, list(items))
    annotators = sorted(got.labels)
    if len(annotators) < 2:
        raise PilotError(
            f"agreement needs at least two annotators with labels on this batch; found "
            f"{len(annotators)}"
        )
    if intra and len(annotators) != 2:
        raise PilotError(
            f"an intra-annotator report compares exactly two passes; found {len(annotators)}"
        )

    notes: list[str] = []
    needed = 2 if intra else ANNOTATORS_NEEDED
    incomplete = [a for a in annotators if len(got.labels[a]) < len(items)]
    if len(annotators) < needed:
        notes.append(
            f"Not a finished pilot: {len(annotators)} annotators, and the protocol asks for "
            f"{needed}."
        )
    if incomplete:
        names = ", ".join(got.names[a] for a in incomplete)
        notes.append(f"Not a finished pilot: {names} did not label every item.")
    if intra:
        gap = intra_gap(got.labels[annotators[0]], got.labels[annotators[1]])
        if gap is None:
            notes.append("The gap between the two passes cannot be checked: a label has no time.")
        elif gap < MIN_INTRA_GAP:
            notes.append(
                f"The two passes are {max(gap.days, 0)} days apart, under the "
                f"{MIN_INTRA_GAP.days} the protocol asks for. The second pass is not blind "
                "to the first."
            )
    if got.n_superseded:
        notes.append(
            f"{got.n_superseded} answers differed between exports; the later answer was kept."
        )

    coverage = []
    for annotator in annotators:
        counts = Counter(label.verdict for label in got.labels[annotator].values())
        coverage.append(
            {
                "annotator_id": annotator,
                "name": got.names[annotator],
                "n_labelled": len(got.labels[annotator]),
                "n_missing": len(items) - len(got.labels[annotator]),
                "by_verdict": {label: counts.get(label, 0) for label in LABELS},
            }
        )

    pairs = []
    for index, (a, b) in enumerate(combinations(annotators, 2)):
        report = pair_report(
            got.labels[a], got.labels[b], seed=seed + index, n_resamples=n_resamples
        )
        pairs.append({"annotators": [a, b], **report})

    units = [
        [got.labels[a][item].verdict for a in annotators if item in got.labels[a]] for item in items
    ]
    disagreements = []
    for item, text in items.items():
        answers = {a: got.labels[a][item] for a in annotators if item in got.labels[a]}
        verdicts = {answer.verdict for answer in answers.values()}
        scripts = {answer.script or NO_SCRIPT for answer in answers.values()}
        if len(verdicts) > 1 or (verdicts == {"scam"} and len(scripts) > 1):
            disagreements.append(
                {
                    "item_id": item,
                    "text": text,
                    "on": "verdict" if len(verdicts) > 1 else "script",
                    "answers": {
                        a: {"verdict": answer.verdict, "script": answer.script}
                        for a, answer in answers.items()
                    },
                }
            )

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "batch": batch_name,
        "kind": "intra-annotator" if intra else "inter-annotator",
        "finished": not any(note.startswith("Not a finished pilot") for note in notes),
        "notes": notes,
        "n_items": len(items),
        "annotators": {a: got.names[a] for a in annotators},
        "ignored": {"skipped": got.n_skipped, "outside_batch": got.n_outside_batch},
        "seed": seed,
        "n_resamples": n_resamples,
        "coverage": coverage,
        "verdict": {
            "labels": list(LABELS),
            "n_items_with_two_labels": sum(1 for unit in units if len(unit) >= 2),
            "krippendorff_alpha": _num(krippendorff_alpha(units)),
            "pairs": pairs,
        },
        "disagreements": disagreements,
    }
    if key is not None:
        provisional = {str(e["pilot_id"]): str(e["provisional_label"]) for e in key["items"]}
        report["provisional"] = [
            {
                "annotator_id": a,
                "n_items": len(got.labels[a]),
                "n_same": sum(
                    1
                    for item, answer in got.labels[a].items()
                    if provisional.get(item) == answer.verdict
                ),
            }
            for a in annotators
        ]
    return report


# ---------------------------------------------------------------------------
# agreement: the report
# ---------------------------------------------------------------------------


def _fmt(value: float | None, ndigits: int = 2) -> str:
    return "undefined" if value is None else f"{value:.{ndigits}f}"


def _share(value: float | None) -> str:
    return "none" if value is None else f"{value:.0%}"


def render(report: Mapping[str, Any]) -> str:
    names = report["annotators"]
    kind = "Intra-annotator" if report["kind"] == "intra-annotator" else "Inter-annotator"
    lines = [
        f"# Annotation pilot agreement: {report['batch'] or 'pilot batch'}",
        "",
        f"{kind} agreement on {report['n_items']} items, {len(names)} "
        f"{'passes by one person' if report['kind'] == 'intra-annotator' else 'annotators'}. "
        "Generated by `tools/pilot.py agreement`; nothing here is typed in by hand except the "
        "adjudication lines.",
        "",
    ]
    lines += [f"**{note}**" for note in report["notes"]]
    if report["notes"]:
        lines.append("")
    ignored = report["ignored"]
    lines += [
        "## Coverage",
        "",
        "| Annotator | Labelled | Scam | Legit | Ambiguous | Not labelled |",
        "|---|---|---|---|---|---|",
    ]
    for row in report["coverage"]:
        by = row["by_verdict"]
        lines.append(
            f"| {row['name']} | {row['n_labelled']} | {by['scam']} | {by['legit']} | "
            f"{by['ambiguous']} | {row['n_missing']} |"
        )
    lines += [
        "",
        f"Left out: {ignored['skipped']} skipped answers and {ignored['outside_batch']} answers "
        "on items outside this batch.",
        "",
        "## Verdict",
        "",
    ]
    verdict = report["verdict"]
    lines += [
        f"Krippendorff's alpha, nominal, over the {verdict['n_items_with_two_labels']} items "
        f"with at least two labels: {_fmt(verdict['krippendorff_alpha'])}.",
        "",
        "| Pair | Items | Same verdict | Cohen's kappa | 95% interval | Kappa: scam | "
        "Kappa: legit | Kappa: ambiguous |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for pair in verdict["pairs"]:
        a, b = pair["annotators"]
        ci = pair["kappa_ci95"]
        interval = "none" if ci is None else f"{_fmt(ci[0])} to {_fmt(ci[1])}"
        per = pair["kappa_per_class"]
        lines.append(
            f"| {names[a]} and {names[b]} | {pair['n_items']} | {_share(pair['agreement'])} | "
            f"{_fmt(pair['kappa'])} | {interval} | {_fmt(per['scam'])} | {_fmt(per['legit'])} | "
            f"{_fmt(per['ambiguous'])} |"
        )
    lines += [
        "",
        f"The interval resamples items ({report['n_resamples']} resamples, seed "
        f"{report['seed']}). A kappa is undefined where both annotators used one category "
        "only, and a per-class kappa where neither used that class.",
        "",
        "## Script",
        "",
        "Over the items both annotators called a scam.",
        "",
        "| Pair | Items | Same script | Cohen's kappa |",
        "|---|---|---|---|",
    ]
    confused: Counter[tuple[str, str]] = Counter()
    for pair in verdict["pairs"]:
        a, b = pair["annotators"]
        script = pair["script"]
        lines.append(
            f"| {names[a]} and {names[b]} | {script['n_items']} | {_share(script['agreement'])} | "
            f"{_fmt(script['kappa'])} |"
        )
        for entry in script["confused"]:
            confused[tuple(entry["scripts"])] += entry["n"]
    if confused:
        lines += ["", "Scripts chosen against each other, counted over pairs of annotators:", ""]
        lines += [
            f"- `{x}` and `{y}`: {n}" for (x, y), n in sorted(confused.items(), key=_by_count)
        ]
    if "provisional" in report:
        lines += [
            "",
            "## Against the collector's provisional label",
            "",
            "The provisional label is one person's reading at collection. It is not gold, and "
            "this table is not an accuracy.",
            "",
            "| Annotator | Items | Same as the provisional label |",
            "|---|---|---|",
        ]
        lines += [
            f"| {names[row['annotator_id']]} | {row['n_items']} | {row['n_same']} |"
            for row in report["provisional"]
        ]
    lines += ["", "## Disagreements", ""]
    if not report["disagreements"]:
        lines.append("None.")
    for entry in report["disagreements"]:
        lines += [f"### {entry['item_id']} ({entry['on']})", ""]
        lines += [f"> {part}" for part in entry["text"].splitlines() or [""]]
        lines.append("")
        for annotator, answer in entry["answers"].items():
            script = f", `{answer['script']}`" if answer["script"] else ""
            lines.append(f"- {names[annotator]}: {answer['verdict']}{script}")
        lines += ["", "Adjudication:", ""]
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pilot.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    drawer = commands.add_parser("draw", help="draw the pilot batch from the dev split")
    drawer.add_argument("--dev", type=Path, required=True, help="the dev split, JSONL")
    drawer.add_argument("--out", type=Path, required=True, help="batch file to write")
    drawer.add_argument("--seed", type=int, default=DEFAULT_SEED)
    drawer.add_argument("--prefix", default=DEFAULT_PREFIX, help="prefix of the pilot item ids")
    drawer.add_argument("--date", default=None, help="creation date to record (default: today)")

    scorer = commands.add_parser("agreement", help="measure agreement on exported labels")
    scorer.add_argument("--batch", type=Path, required=True, help="the batch file")
    scorer.add_argument("--exports", type=Path, nargs="+", required=True, help="label exports")
    scorer.add_argument("--key", type=Path, default=None, help="key file (default: beside batch)")
    scorer.add_argument("--out", type=Path, default=None, help="Markdown report to write")
    scorer.add_argument("--json", type=Path, default=None, help="the same report as JSON")
    scorer.add_argument("--intra", action="store_true", help="two passes by one person")
    scorer.add_argument("--seed", type=int, default=DEFAULT_SEED)
    scorer.add_argument("--resamples", type=int, default=10_000)
    return parser


def _draw(args: argparse.Namespace) -> int:
    rows = read_rows(args.dev)
    selected = draw(rows, seed=args.seed)
    document, key = build_batch(
        selected,
        all_rows=rows,
        dev_path=args.dev.as_posix(),
        batch=args.out.stem,
        prefix=args.prefix,
        seed=args.seed,
        created_at=args.date or date.today().isoformat(),
    )
    write_json(args.out, document)
    write_json(key_path_for(args.out), key)
    mix = Counter((e["provisional_label"], e["lang"]) for e in key["items"])
    groups = len({e["source_group"] for e in key["items"]})
    print(f"drew {len(selected)} of {len(rows)} rows from {groups} source groups")
    for (label, lang), n in sorted(mix.items()):
        print(f"  {label}/{lang}: {n}")
    print(f"wrote {args.out} and {key_path_for(args.out)}")
    return 0


def _agreement(args: argparse.Namespace) -> int:
    batch = json.loads(args.batch.read_text(encoding="utf-8"))
    key_path = args.key or key_path_for(args.batch)
    key = json.loads(key_path.read_text(encoding="utf-8")) if key_path.is_file() else None
    report = analyse(
        batch,
        [read_export(path) for path in args.exports],
        key=key,
        intra=args.intra,
        seed=args.seed,
        n_resamples=args.resamples,
        batch_name=args.batch.stem,
    )
    text = render(report)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)
    if args.json is not None:
        write_json(args.json, report)
        print(f"wrote {args.json}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _draw(args) if args.command == "draw" else _agreement(args)
    except (PilotError, OSError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
