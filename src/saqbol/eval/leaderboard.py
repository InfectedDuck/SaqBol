"""T501 — `leaderboard.md`, generated from `results.json` and never hand-edited.

The table prints numbers with their 95 percent intervals and nothing else. It
makes no ranking claim: rows within a group are ordered by point estimate so
the table is readable, and the header says in so many words that overlapping
intervals support no claim about which system is better. The sentence that
would make such a claim lives in `metrics.compare`, which checks the
intervals first; this module never calls it.

A metric a cell did not measure prints as a dash. That is the reading rule
`metrics.py` sets for an undefined number, and it keeps a cell with no hard
negatives from printing a false-positive rate of zero.

A metric a cell measured on too little data prints as `not reported`. The
floors are defined in `support.py`; this module applies them, because the
leaderboard is where a number becomes a published one. `results.json` keeps
every number the harness computed. The held-out tables also depend on the
release tier of the run: under the floor for a pilot they print row counts
and no number.

The notes under the header describe the file they print, not the current
code: a results file written before intervals took source groups into
account is printed with the sentence that says its intervals resampled rows.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from saqbol.eval.results import (
    ABLATIONS,
    GROUPED_CI,
    LANGS,
    SPLITS,
    ResultRow,
    Results,
    read_results,
)
from saqbol.eval.support import (
    DEFAULT_FLOORS,
    TEST_SPLITS,
    TIER_SPLIT,
    Floors,
    Release,
    f1_gap,
    fpr_gap,
    playbook_gap,
    release_tier,
    slice_gap,
)

DASH = "—"

RULE = (
    "Every number is a point estimate with its 95 percent bootstrap interval in brackets. "
    "Two intervals that overlap support no claim about which system is better; rows are "
    "ordered by point estimate within each group only so the table can be read."
)

#: Printed under the heading of a split whose numbers are not test results,
#: so the table cannot be quoted without the caveat.
SPLIT_NOTES: dict[str, str] = {
    "dev": (
        "Development data. The system was built against these rows, so the numbers below "
        "are development numbers and are not test results."
    ),
    "calibration": (
        "Calibration data. Thresholds were fitted on these rows, so the numbers below are "
        "not test results."
    ),
}

#: Printed over a held-out table when the release tier allows no test number.
WITHHELD_NOTE = (
    "The release tier is `none`, so this table lists the cells that ran and how many rows "
    "each one read, and prints no number."
)

#: Marks a hard-negative interval that is an exact bound, not a bootstrap one.
EXACT_MARK = "*"
EXACT_NOTE = (
    f"A hard-negative FPR marked `{EXACT_MARK}` comes from a cell where no hard negative was "
    "flagged, or every one was. Resampling such a cell gives an interval with no width, so "
    "the bracket is the exact one-sided 95 percent binomial bound instead: with none of "
    "`n` flagged, the rate is at most the upper figure."
)
#: The same, for a file whose bound counts source groups as its trials.
EXACT_NOTE_GROUPED = (
    f"A hard-negative FPR marked `{EXACT_MARK}` comes from a cell where no hard negative was "
    "flagged, or every one was. Resampling such a cell gives an interval with no width, so "
    "the bracket is the exact one-sided 95 percent binomial bound instead, with each source "
    "group of hard negatives counted as one trial: with none flagged, the rate is at most the "
    "upper figure."
)

#: Marks a playbook figure that is top-1 accuracy, not macro-F1.
ACCURACY_MARK = "acc"

#: Printed in place of a number the cell has too little data for.
NOT_REPORTED = "not reported"


#: How the intervals of a file were drawn, by what it records.
GROUPED_NOTE = (
    "Each interval is the wider of two: one resampling rows, and one resampling whole source "
    "groups among the groups that hold the same gold labels. The first is too narrow when the "
    "rows of one article agree with each other, the second when there are few articles, so the "
    "wider bounds are printed."
)
ROW_NOTE = (
    "The intervals resample rows, not groups, and are narrower than that evidence warrants "
    "wherever the two figures differ."
)


def support_note(floors: Floors, *, grouped: bool = False) -> str:
    """The two paragraphs that explain `not reported` and the bracketed count."""
    return (
        f"`{NOT_REPORTED}` marks a number with too little data behind it. A slice of fewer than "
        f"{floors.slice_rows} rows prints no metric; macro-F1 needs at least {floors.class_rows} "
        f"rows of each class; the hard-negative FPR needs at least {floors.hard_negatives} hard "
        "negatives. The count that fell short is given in brackets. `results.json` keeps every "
        "number.\n"
        "\n"
        "`rows (source groups)` is the number of rows in the cell and, in brackets, the number "
        "of source groups they come from. Rows that share an article, a translation pair or "
        "near-identical text are one group, so the bracketed figure is the better guide to how "
        "much independent evidence the cell holds. " + (GROUPED_NOTE if grouped else ROW_NOTE)
    )


def playbook_note(floors: Floors) -> str:
    """How the playbook column is computed and which figure it prints."""
    return (
        "The playbook score is over the scam rows the system answered. It is macro-F1 over the "
        f"playbooks with at least {floors.playbook_rows} gold rows in the slice when there are "
        f"at least {floors.playbooks_for_macro} of them, and otherwise `{ACCURACY_MARK}`: top-1 "
        "accuracy over the rows whose gold label names a playbook. A scam that fits no playbook "
        "and a system that names none give the same answer, and that class is never averaged."
    )


_COLUMNS = (
    "system",
    "model",
    "lang",
    "ablation",
    "rows (source groups)",
    "macro-F1 [95% CI]",
    "hard-neg FPR [95% CI]",
    "coverage",
    "playbook [95% CI]",
    "stage acc. (correct/eligible)",
)


def _fmt(value: float | None, ndigits: int = 3) -> str:
    if value is None:
        return DASH
    return f"{value:.{ndigits}f}"


def _interval(point: float | None, ci: Sequence[float] | None, ndigits: int = 3) -> str:
    if point is None:
        return DASH
    if ci is None:
        return _fmt(point, ndigits)
    lo, hi = ci
    return f"{point:.{ndigits}f} [{lo:.{ndigits}f}, {hi:.{ndigits}f}]"


def _extra(row: ResultRow, key: str) -> Any:
    return (row.model_extra or {}).get(key)


def _is_exact(row: ResultRow) -> bool:
    return _extra(row, "fpr_hard_negative_ci_method") == "exact_binomial"


def _withheld(reason: str | None = None) -> str:
    return f"{NOT_REPORTED} ({reason})" if reason else NOT_REPORTED


def _n_rows(row: ResultRow) -> int:
    recorded = _extra(row, "n_rows")
    return recorded if isinstance(recorded, int) else row.n


def _f1_reported(row: ResultRow, floors: Floors, withhold: bool) -> bool:
    if withhold or slice_gap(_n_rows(row), floors):
        return False
    return f1_gap(_extra(row, "n_by_label"), floors) is None


def _playbook_cell(row: ResultRow, floors: Floors) -> str:
    """Macro-F1 over the supported playbooks, top-1 accuracy, or the reason for neither."""
    n_by_class = _extra(row, "playbook_n_by_class")
    if n_by_class is None and _extra(row, "playbook_macro_f1") is None:
        return DASH
    kind, gap = playbook_gap(n_by_class, _extra(row, "playbook_supported"), floors)
    if gap:
        return _withheld(gap)
    if kind == "macro":
        return _interval(_extra(row, "playbook_macro_f1"), _extra(row, "playbook_ci95"))
    figure = _interval(_extra(row, "playbook_accuracy"), _extra(row, "playbook_accuracy_ci95"))
    return figure if figure == DASH else f"{ACCURACY_MARK} {figure}"


def _render_row(row: ResultRow, floors: Floors, *, withhold: bool) -> str:
    """One table line. `withhold` blanks every metric: the tier allows no test number."""
    n_rows = _n_rows(row)
    groups = _extra(row, "n_source_groups")
    counts = f"{n_rows} ({groups if isinstance(groups, int) else DASH})"
    identity = (row.system, row.model, row.lang, row.ablation, counts)

    if withhold or slice_gap(n_rows, floors):
        blank = (NOT_REPORTED,) * (len(_COLUMNS) - len(identity))
        return "| " + " | ".join((*identity, *blank)) + " |"

    thin_classes = f1_gap(_extra(row, "n_by_label"), floors)
    f1_cell = _withheld(thin_classes) if thin_classes else _interval(row.macro_f1, row.ci95)

    if row.fpr_hard_negative is None:
        fpr_cell = DASH
    else:
        thin_hard = fpr_gap(_extra(row, "n_hard_negative"), floors)
        if thin_hard:
            fpr_cell = _withheld(thin_hard)
        else:
            fpr_cell = _interval(row.fpr_hard_negative, _extra(row, "fpr_hard_negative_ci95"))
            fpr_cell += EXACT_MARK if _is_exact(row) else ""

    coverage = None if row.abstain_rate is None else 1.0 - row.abstain_rate
    stage = _extra(row, "stage_accuracy")
    if stage is None:
        stage_cell = DASH
    else:
        stage_cell = (
            f"{stage:.3f} ({_extra(row, 'stage_n_correct')}/{_extra(row, 'stage_n_eligible')})"
        )
    cells = (
        *identity,
        f1_cell,
        fpr_cell,
        _fmt(coverage),
        _playbook_cell(row, floors),
        stage_cell,
    )
    return "| " + " | ".join(cells) + " |"


#: Groups print the whole split first, then each language slice.
_LANG_ORDER: tuple[str, ...] = ("all", *(lang for lang in LANGS if lang != "all"))


def _table(rows: Sequence[ResultRow], floors: Floors, *, withhold: bool) -> list[str]:
    def order(row: ResultRow) -> tuple[int, int, float, str, str]:
        ablation_rank = ABLATIONS.index(row.ablation)
        lang_rank = _LANG_ORDER.index(row.lang) if row.lang in _LANG_ORDER else len(_LANG_ORDER)
        # A row whose macro-F1 is not printed is not ranked by it either, or
        # its place in the table would give away the number that was withheld.
        point = -row.macro_f1 if _f1_reported(row, floors, withhold) else 0.0
        return (ablation_rank, lang_rank, point, row.system, row.model)

    header = "| " + " | ".join(_COLUMNS) + " |"
    rule = "|" + "|".join("---" for _ in _COLUMNS) + "|"
    return [
        header,
        rule,
        *(_render_row(r, floors, withhold=withhold) for r in sorted(rows, key=order)),
    ]


def _playbook_support(rows: Sequence[ResultRow], floors: Floors) -> list[str]:
    """Which playbooks each language slice of a split averages, and which it cannot."""
    by_lang: dict[str, ResultRow] = {}
    for row in rows:
        if isinstance(_extra(row, "playbook_n_by_class"), Mapping):
            by_lang.setdefault(row.lang, row)
    if not by_lang:
        return []
    first = next(iter(by_lang.values()))
    floor = _extra(first, "playbook_floor")
    lines = [
        "Gold scam rows per playbook in each slice. A playbook is averaged into the playbook "
        f"score with at least {floor if isinstance(floor, int) else floors.playbook_rows}.",
        "",
    ]
    for lang in sorted(by_lang, key=lambda v: _LANG_ORDER.index(v) if v in _LANG_ORDER else 99):
        row = by_lang[lang]
        counts = _extra(row, "playbook_n_by_class")
        supported = _extra(row, "playbook_supported") or []
        above = [f"`{c}` {n}" for c, n in counts.items() if c in supported]
        below = [f"`{c}` {n}" for c, n in counts.items() if c not in supported]
        parts = [f"averaged: {', '.join(above)}" if above else "none averaged"]
        if below:
            parts.append(f"under the floor: {', '.join(below)}")
        lines.append(f"- `{lang}`: {'; '.join(parts)}")
    return [*lines, ""]


def _grouped(results: Results) -> bool:
    """Did every interval in the file resample source groups?"""
    return bool(results.rows) and all(
        _extra(row, "ci_resampled") == GROUPED_CI for row in results.rows
    )


def _exact_mark_printed(results: Results, floors: Floors, withheld_splits: Sequence[str]) -> bool:
    return any(
        _is_exact(row)
        and row.split not in withheld_splits
        and row.fpr_hard_negative is not None
        and not slice_gap(_n_rows(row), floors)
        and not fpr_gap(_extra(row, "n_hard_negative"), floors)
        for row in results.rows
    )


def run_release(results: Results, floors: Floors = DEFAULT_FLOORS) -> Release:
    """The release tier of a results file, from the split sizes it records.

    A file that holds held-out rows and does not say how large the split is
    cannot show that it clears a floor, so it gets no tier.
    """
    extras = results.model_extra or {}
    support = extras.get("split_support")
    if not isinstance(support, Mapping):
        if any(row.split in TEST_SPLITS for row in results.rows):
            return Release(
                "none",
                "This results file does not record the size of its splits, so the release "
                "tier cannot be checked and no test number is published. Run the evaluation "
                "again.",
            )
        support = {}
    facts = support.get(TIER_SPLIT)
    limit = extras.get("limit")
    return release_tier(
        facts if isinstance(facts, Mapping) else None,
        floors,
        limit=limit if isinstance(limit, int) else None,
    )


def render_leaderboard(
    results: Results,
    *,
    skipped: Sequence[Mapping[str, Any]] = (),
    floors: Floors = DEFAULT_FLOORS,
) -> str:
    """The markdown leaderboard for one results file.

    `skipped` is the manifest's list of cells that did not run; when given,
    they are listed with their reasons so an absent row is explained rather
    than left to be inferred. `floors` are the minimum-support rules; the
    paragraph under the header prints whichever ones were applied.
    """
    release = run_release(results, floors)
    grouped = _grouped(results)
    pilot = " (pilot)" if release.tier == "pilot" else ""
    withheld_splits = TEST_SPLITS if release.tier == "none" else ()
    lines = [
        f"# Leaderboard — {results.dataset_version}{pilot}",
        "",
        f"Generated from `results.json` for run `{results.run_id}` "
        f"({results.n_bootstrap:,} bootstrap resamples). Do not edit by hand; regenerate "
        "with `python -m saqbol.eval leaderboard`.",
        "",
        RULE,
        "",
        "Macro-F1 is over `scam` / `legit` on the rows the system answered; `coverage` is the "
        "share of rows it answered. The hard-negative FPR keeps abstentions in its denominator. "
        "A dash marks a metric the cell did not measure.",
        "",
        playbook_note(floors),
        "",
        support_note(floors, grouped=grouped),
        "",
        f"**Release tier: {release.tier}.** {release.reason}",
        "",
    ]
    if _exact_mark_printed(results, floors, withheld_splits):
        lines += [EXACT_NOTE_GROUPED if grouped else EXACT_NOTE, ""]
    present = [s for s in SPLITS if any(r.split == s for r in results.rows)]
    if not present:
        lines += ["No cell of the matrix produced a result.", ""]
    for split in present:
        lines += [f"## {split}{pilot if split in TEST_SPLITS else ''}", ""]
        if split in SPLIT_NOTES:
            lines += [SPLIT_NOTES[split], ""]
        withhold = split in withheld_splits
        if withhold:
            lines += [WITHHELD_NOTE, ""]
        rows = [r for r in results.rows if r.split == split]
        lines += [*_table(rows, floors, withhold=withhold), ""]
        if not withhold:
            lines += _playbook_support(rows, floors)
    if skipped:
        lines += [
            "## Cells not run",
            "",
            "Grouped by reason; `manifest.json` lists every cell.",
            "",
            "| cells | systems | splits | reason |",
            "|---|---|---|---|",
        ]
        for reason, count, systems, splits in group_skipped(skipped):
            fields = (str(count), ", ".join(systems), ", ".join(splits), reason.replace("|", "\\|"))
            lines.append("| " + " | ".join(fields) + " |")
        lines.append("")
    return "\n".join(lines)


def group_skipped(
    skipped: Sequence[Mapping[str, Any]],
) -> list[tuple[str, int, list[str], list[str]]]:
    """Skipped cells collapsed by reason: `(reason, count, systems, splits)`.

    Reasons keep their first-seen order, which is matrix order, so a split
    that is missing is listed before a model that has no key.
    """
    groups: dict[str, tuple[int, list[str], list[str]]] = {}
    for cell in skipped:
        reason = str(cell.get("reason", ""))
        count, systems, splits = groups.get(reason, (0, [], []))
        system, split = str(cell.get("system", DASH)), str(cell.get("split", DASH))
        if system not in systems:
            systems.append(system)
        if split not in splits:
            splits.append(split)
        groups[reason] = (count + 1, systems, splits)
    return [(reason, count, systems, splits) for reason, (count, systems, splits) in groups.items()]


def _skipped_beside(results_path: Path) -> list[Mapping[str, Any]]:
    manifest = results_path.with_name("manifest.json")
    if not manifest.is_file():
        return []
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    skipped = payload.get("skipped") if isinstance(payload, dict) else None
    return [s for s in skipped if isinstance(s, dict)] if isinstance(skipped, list) else []


def write_leaderboard(
    results_path: str | os.PathLike[str],
    out_path: str | os.PathLike[str],
    *,
    floors: Floors = DEFAULT_FLOORS,
) -> Path:
    """Render `results_path` to markdown at `out_path`.

    A `manifest.json` beside the results file, if present, supplies the list
    of cells that did not run.
    """
    source = Path(results_path)
    results = read_results(source)
    text = render_leaderboard(results, skipped=_skipped_beside(source), floors=floors)
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8", newline="\n")
    return destination
