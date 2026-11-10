"""Minimum support: how much data a number needs before it is printed.

The rules are section 7 of docs/15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md
and they live here once, as numbers, so that the harness that counts and the
leaderboard that prints cannot drift apart.

**The harness counts, the leaderboard decides.** `run.py` records what every
cell and every split holds — rows, rows per class, hard negatives, source
groups — and writes every metric it computed into `results.json`. Nothing is
withheld there: a developer comparing two versions of the rules needs the
number from a 28-row slice, and the file is the record of what was computed.
`leaderboard.py` is the publication step, and it prints `not reported` where
the counts fall under a floor.

**Unknown support is no support.** A results file written before these counts
existed cannot show that a cell clears a floor, so its numbers are not
printed either. A floor that passed whenever the evidence for it was missing
would not be a floor.

Three kinds of rule:

- a *slice* (one language of one split, or a whole split) prints no metric
  under `slice_rows` rows, and no macro-F1 with fewer than `class_rows` rows
  of either class;
- the hard-negative false-positive rate needs `hard_negatives` hard negatives;
- the *release tier* of the held-out press split decides whether any test
  number is printed at all.

The per-playbook floor of the same section (ten rows per playbook, top-1
accuracy when fewer than five playbooks are supported) belongs to the task
that reports playbook scores on annotated rows, and is not applied here.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

Tier = Literal["none", "pilot", "benchmark"]

#: The split whose size sets the release tier.
TIER_SPLIT = "test_press"
#: Splits whose numbers are test results, and are withheld at tier `none`.
TEST_SPLITS: tuple[str, ...] = ("test_press", "test_donated")
#: The two classes of the headline macro-F1.
CLASSES: tuple[str, ...] = ("scam", "legit")


@dataclass(frozen=True)
class Floors:
    """The minimums, as one value that can be printed beside the numbers."""

    slice_rows: int = 30
    class_rows: int = 10
    hard_negatives: int = 30
    pilot_rows: int = 60
    pilot_legit: int = 20
    benchmark_rows: int = 200
    benchmark_legit: int = 60
    benchmark_hard_negatives: int = 40
    benchmark_lang_rows: int = 60
    benchmark_langs: tuple[str, ...] = ("ru", "kk")


DEFAULT_FLOORS = Floors()


class _Row(Protocol):
    id: str
    label: str
    lang: str
    hard_negative: bool
    source_group: str | None


def count_support(rows: Iterable[_Row]) -> dict[str, Any]:
    """What a set of rows holds, in the shape the floors are checked against.

    `n_source_groups` is present only when every row names its group. A file
    built before the field existed gets no group count, since counting each
    of its rows as independent would claim something nobody checked.
    """
    rows = list(rows)
    facts: dict[str, Any] = {
        "n_rows": len(rows),
        "by_label": dict(sorted(Counter(r.label for r in rows).items())),
        "by_lang": dict(sorted(Counter(r.lang for r in rows).items())),
        "n_hard_negative": sum(1 for r in rows if r.hard_negative),
    }
    if rows and all(r.source_group for r in rows):
        facts["n_source_groups"] = len({r.source_group for r in rows})
    return facts


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def slice_gap(n_rows: Any, floors: Floors = DEFAULT_FLOORS) -> str | None:
    """Why a slice prints no metric at all, or None when it may."""
    n = _count(n_rows)
    if n is None:
        return "row count not recorded"
    if n < floors.slice_rows:
        return f"{n} rows"
    return None


def f1_gap(by_label: Any, floors: Floors = DEFAULT_FLOORS) -> str | None:
    """Why a slice prints no macro-F1, or None when it may."""
    if not isinstance(by_label, Mapping):
        return "class counts not recorded"
    thin = [
        f"{_count(by_label.get(name)) or 0} {name}"
        for name in CLASSES
        if (_count(by_label.get(name)) or 0) < floors.class_rows
    ]
    return ", ".join(thin) if thin else None


def fpr_gap(n_hard_negative: Any, floors: Floors = DEFAULT_FLOORS) -> str | None:
    """Why a slice prints no hard-negative false-positive rate, or None."""
    n = _count(n_hard_negative)
    if n is None:
        return "hard-negative count not recorded"
    if n < floors.hard_negatives:
        return f"{n} hard negative{'' if n == 1 else 's'}"
    return None


@dataclass(frozen=True)
class Release:
    """The tier of a run and the sentence that explains it."""

    tier: Tier
    reason: str


def _missing(needs: Iterable[tuple[str, int, int]]) -> list[str]:
    return [f"{have} {what} (needs {need})" for what, have, need in needs if have < need]


def release_tier(
    facts: Mapping[str, Any] | None,
    floors: Floors = DEFAULT_FLOORS,
    *,
    limit: int | None = None,
) -> Release:
    """The release tier for the support facts of the held-out press split.

    `facts` is `count_support` of `test_press`, or None when the run read no
    such split. `limit` is the run's row cap: a pass over the first few rows
    of each cell is a look at the harness, not a result, so it has no tier.
    """
    split = f"`{TIER_SPLIT}`"
    if facts is None:
        return Release("none", f"This run read no {split} rows, so nothing here is a test result.")
    if limit is not None:
        return Release(
            "none",
            f"This was a partial run (`--limit {limit}`), and no test number is published "
            "from a partial run.",
        )
    n_rows = _count(facts.get("n_rows")) or 0
    by_label = facts.get("by_label") if isinstance(facts.get("by_label"), Mapping) else {}
    by_lang = facts.get("by_lang") if isinstance(facts.get("by_lang"), Mapping) else {}
    legit = _count(by_label.get("legit")) or 0
    hard = _count(facts.get("n_hard_negative")) or 0

    short = _missing(
        [("rows", n_rows, floors.pilot_rows), ("legitimate rows", legit, floors.pilot_legit)],
    )
    if short:
        return Release(
            "none",
            f"{split} is under the floor for a pilot: {'; '.join(short)}. "
            "No test number is published.",
        )
    short = _missing(
        [
            ("rows", n_rows, floors.benchmark_rows),
            ("legitimate rows", legit, floors.benchmark_legit),
            ("hard negatives", hard, floors.benchmark_hard_negatives),
            *(
                (f"`{lang}` rows", _count(by_lang.get(lang)) or 0, floors.benchmark_lang_rows)
                for lang in floors.benchmark_langs
            ),
        ],
    )
    if short:
        return Release(
            "pilot",
            f"{split} holds {n_rows} rows, {legit} of them legitimate, which is enough for a "
            f"pilot and not for a benchmark: {'; '.join(short)}. The test tables below are "
            "pilot results.",
        )
    return Release(
        "benchmark",
        f"{split} holds {n_rows} rows, {legit} of them legitimate and {hard} hard negatives, "
        "which meets every floor for a benchmark.",
    )
