"""Fit the warning threshold of the rules-only system, on calibration data only.

    python -m saqbol.eval calibrate --config eval/configs/dev.yaml \
        --out eval/calibration/rules_only.json

The rules-only system has one parameter that a labelled message can decide:
`Thresholds.suspicious`, the rule score at which a message stops being
`likely_safe`. This module searches it, applies a selection rule written down
before the search, and writes everything it looked at to one JSON file, so the
chosen value can be traced to the rows, the candidates and the code behind it.

**What is searched.** Every rule score is a whole number of points out of
`RULE_SCORE_CAP`, so a grid with one candidate per point covers every decision
the threshold can make. The grid stops at the weight of one critical
indicator: a bare request for an SMS code is the strongest single signal in
the catalogue and must never come out as likely safe, so a threshold above it
is not a candidate.

**What is not searched.** `Thresholds.scam` separates two bands the scoring
counts as the same answer (`positive_bands`), and no gold label says which of
the two a scam message deserves, so no data here can choose it. The fusion
weights and the disagreement and self-consistency thresholds only act when a
model has judged the message; they are fitted with the hybrid system. The
artifact lists each of these with its reason.

**The objective.** Among admissible candidates, the highest macro-F1 over
scam and legit, which is the protocol's primary metric. A candidate is
admissible when all three hold:

- *False positives.* No more than `max_fpr_hard_negative` of the hard
  negatives in the calibration data are flagged.
- *Coverage.* The system answers at least `min_coverage` of the rows. The
  rules never abstain, so this binds only once a model is in the loop; it is
  here so the hybrid is fitted to the same objective.
- *Guard.* Every case in the regression suite (`tests/fixtures/golden`) keeps
  a band the case allows. A configuration that fails the suite cannot ship,
  and the suite carries what the calibration rows cannot: a genuine eGov code
  message names eGov and so fires one high-severity indicator, and it must
  stay `likely_safe`. The guard cases are constructed and are not dataset
  rows; they bound the search and are never scored.

Ties go to the higher threshold, the one that warns less.

**The incumbent rule.** The value the system already runs with is replaced
only when the best candidate's gain over it is distinguishable from zero: the
95% interval of the paired difference in macro-F1 must lie above zero, with
*source groups* resampled, not rows. Several rows quoted from one article are
one piece of evidence, and a threshold moved for the sake of two articles has
been fitted to those articles. When the interval reaches zero the incumbent
stays, and the artifact still records the candidate that scored best.

**What the search may read.** `calibration` or `dev`, never a test split; the
function refuses any other name. In the `dev-calibrated` regime the rows are
ones the rules were written against, so every legitimate row already scores
low and the false-positive constraint is weaker than it looks. The guard and
the incumbent rule are what keep the fit from following that bias.

**Confirmation.** The search bands a stored rule score with `band_for`, the
function `fuse` uses. Before the artifact is written the real pipeline is run
with the selected thresholds over every calibration row and guard case, and
any difference from the searched bands is an error.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import math
import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from numpy.typing import NDArray

from saqbol.core.fuse import DEFAULT_THRESHOLDS, Thresholds, band_for
from saqbol.core.types import RULE_SCORE_CAP, SEVERITY_WEIGHT, Lang, Severity
from saqbol.eval import metrics
from saqbol.eval.config import EvalConfig, config_hash
from saqbol.eval.run import BINARY_LABELS, DatasetRow, git_commit, load_split
from saqbol.eval.support import count_support
from saqbol.eval.systems import ABSTAIN_BAND, NO_MODEL, band_to_label
from saqbol.pipeline import rules_only_analyzer

#: The artifact's shape. Bumped when a reader of the file would have to change.
SCHEMA = "saqbol-calibration/1"
#: The system this module fits.
SYSTEM = "rules_only"
#: Splits a threshold may be fitted on, in order of preference, and the label
#: the run carries for each (docs/05_EVAL_PROTOCOL.md section 7).
REGIMES: dict[str, str] = {"calibration": "calibrated", "dev": "dev-calibrated"}
#: The highest candidate, in points: one critical indicator must always warn.
CEILING_POINTS = SEVERITY_WEIGHT[Severity.CRITICAL]
#: Where the regression suite lives, relative to the repository root.
DEFAULT_GUARD_DIR = Path("tests") / "fixtures" / "golden"
#: Where the artifact is written when the CLI is not told otherwise.
DEFAULT_OUT = Path("eval") / "calibration" / "rules_only.json"

#: Parameters the rules-only fit leaves alone, and why.
NOT_FITTED: dict[str, str] = {
    "thresholds.scam": (
        "It separates `scam` from `suspicious`, which the scoring counts as the same "
        "positive answer, and no gold label says which band a scam message deserves."
    ),
    "weights.rule, weights.llm": (
        "With no model judgement the rule score is the whole risk, so the weights cancel."
    ),
    "thresholds.disagreement, thresholds.self_consistency": (
        "They decide abstention between the rules and a model; the rules alone never abstain."
    ),
    "thresholds.sample_lo, thresholds.sample_hi, thresholds.retrieval_floor": (
        "They control model sampling and which script is named; neither changes the band "
        "of a rules-only verdict."
    ),
}


class CalibrationError(ValueError):
    """The fit cannot be made, or its result cannot be trusted."""


@dataclass(frozen=True)
class Objective:
    """The constraints a candidate must meet before its macro-F1 counts."""

    #: Largest share of calibration hard negatives a candidate may flag.
    max_fpr_hard_negative: float = 0.05
    #: Smallest share of rows a candidate must answer.
    min_coverage: float = 0.80
    #: One minus the confidence level of the bounds and the paired interval.
    alpha: float = 0.05


DEFAULT_OBJECTIVE = Objective()


# ---------------------------------------------------------------------------
# What the search reads: one rule score per message
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scored:
    """A calibration row reduced to what the search needs."""

    id: str
    label: str
    risk: float
    hard_negative: bool = False
    #: The row's source group; a row that names none is its own group.
    group: str | None = None


@dataclass(frozen=True)
class GuardCase:
    """A regression case: a message and the bands it is allowed to get."""

    id: str
    text: str
    lang: Lang | None
    band_in: frozenset[str]


@dataclass(frozen=True)
class ScoredGuard:
    id: str
    risk: float
    band_in: frozenset[str]


def _lang(value: str | None) -> Lang | None:
    if not value:
        return None
    try:
        return Lang(value)
    except ValueError:
        return None


def load_guard(directory: str | os.PathLike[str]) -> tuple[list[GuardCase], list[str]]:
    """The regression cases under `directory`, and the ids of those left out.

    A case marked `xfail` is a gap the suite already records as one (a pasted
    news headline about a scam reads like the scam). It fails at every
    threshold, so it would rule out every candidate while saying nothing about
    any of them, and it is left out by name.
    """
    cases: list[GuardCase] = []
    skipped: list[str] = []
    for path in sorted(Path(directory).glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for raw in doc.get("cases") or []:
            case_id = f"{path.name}::{raw['id']}"
            if raw.get("xfail"):
                skipped.append(case_id)
                continue
            band_in = frozenset(str(b) for b in (raw.get("expect") or {}).get("band_in") or [])
            if not band_in:
                raise CalibrationError(f"{case_id}: a guard case needs expect.band_in")
            cases.append(GuardCase(case_id, str(raw["text"]), _lang(raw.get("lang_hint")), band_in))
    if not cases:
        raise CalibrationError(f"no guard cases under {Path(directory).as_posix()}")
    return cases, skipped


def _verdicts(
    messages: Sequence[tuple[str, Lang | None]], thresholds: Thresholds | None = None
) -> list[Any]:
    """The rules-only pipeline's verdict for each message, in order."""
    analyzer = rules_only_analyzer(thresholds=thresholds)

    async def every() -> list[Any]:
        return [
            await analyzer.analyze(text, locale=lang, surface="eval") for text, lang in messages
        ]

    return asyncio.run(every())


def score_rows(rows: Sequence[DatasetRow]) -> list[Scored]:
    """Run the rules once over the calibration rows and keep the risk."""
    verdicts = _verdicts([(row.text, _lang(row.lang)) for row in rows])
    return [
        Scored(row.id, row.label, verdict.risk, row.hard_negative, row.source_group)
        for row, verdict in zip(rows, verdicts, strict=True)
    ]


def score_guard(cases: Sequence[GuardCase]) -> list[ScoredGuard]:
    verdicts = _verdicts([(case.text, case.lang) for case in cases])
    return [
        ScoredGuard(case.id, verdict.risk, case.band_in)
        for case, verdict in zip(cases, verdicts, strict=True)
    ]


# ---------------------------------------------------------------------------
# One candidate
# ---------------------------------------------------------------------------


def candidate_grid(incumbent: Thresholds = DEFAULT_THRESHOLDS) -> list[Thresholds]:
    """One candidate per rule-score point, up to one critical indicator.

    Only `suspicious` varies. A candidate at or above the scam threshold would
    leave no suspicious band at all and is not offered.
    """
    grid = []
    for points in range(1, CEILING_POINTS + 1):
        value = points / RULE_SCORE_CAP
        if value < incumbent.scam:
            grid.append(dataclasses.replace(incumbent, suspicious=value))
    return grid


def upper_bound(events: int, n: int, alpha: float = 0.05) -> float:
    """One-sided exact upper bound on a rate seen as `events` of `n`.

    The largest rate that would still give this few events with probability
    `alpha` (Clopper-Pearson). For no events it is `1 - alpha ** (1 / n)`,
    the bound `metrics.exact_binomial_bound` reports: 0 of 17 is 0.162.
    """
    if n <= 0:
        raise ValueError("a bound needs at least one trial")
    if not 0 <= events <= n:
        raise ValueError(f"{events} events out of {n} trials")
    if events == n:
        return 1.0

    def at_most(rate: float) -> float:
        return sum(math.comb(n, i) * rate**i * (1.0 - rate) ** (n - i) for i in range(events + 1))

    lo, hi = events / n, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if at_most(mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


@dataclass(frozen=True)
class Candidate:
    """One threshold setting and everything the objective needs to know of it."""

    thresholds: Thresholds
    #: The answer for each calibration row, in row order.
    labels: tuple[str, ...]
    macro_f1: float | None
    per_class_f1: dict[str, float]
    n_scam: int
    n_scam_flagged: int
    n_hard_negative: int
    n_false_positive: int
    coverage: float
    guard_failures: tuple[str, ...]
    #: Why the candidate is not admissible; empty when it is.
    rejected: tuple[str, ...]

    @property
    def admissible(self) -> bool:
        return not self.rejected

    @property
    def suspicious(self) -> float:
        return self.thresholds.suspicious


def _label(risk: float, thresholds: Thresholds, positive_bands: Sequence[str]) -> str:
    return band_to_label(band_for(risk, thresholds).value, positive_bands)


def evaluate(
    thresholds: Thresholds,
    rows: Sequence[Scored],
    guard: Sequence[ScoredGuard],
    *,
    objective: Objective = DEFAULT_OBJECTIVE,
    positive_bands: Sequence[str] = ("scam", "suspicious"),
) -> Candidate:
    """Score one candidate and decide whether it is admissible."""
    labels = tuple(_label(row.risk, thresholds, positive_bands) for row in rows)
    # The harness's scoring policy: `ambiguous` gold rows have no place in a
    # scam/legit F1, and an abstention costs coverage, not F1.
    answered = [
        (row.label, label)
        for row, label in zip(rows, labels, strict=True)
        if row.label != "ambiguous" and label != ABSTAIN_BAND
    ]
    macro: float | None = None
    per_class: dict[str, float] = {}
    if answered:
        y_true = [t for t, _ in answered]
        y_pred = [p for _, p in answered]
        value = metrics.macro_f1(y_true, y_pred, labels=BINARY_LABELS)
        macro = None if math.isnan(value) else value
        per_class = {
            k: v
            for k, v in metrics.per_class_f1(y_true, y_pred, labels=BINARY_LABELS).items()
            if not math.isnan(v)
        }

    scam = [label for row, label in zip(rows, labels, strict=True) if row.label == "scam"]
    hard = [label for row, label in zip(rows, labels, strict=True) if row.hard_negative]
    n_false_positive = sum(1 for label in hard if label == "scam")
    coverage = metrics.coverage(labels) if labels else 0.0
    failures = tuple(
        case.id for case in guard if band_for(case.risk, thresholds).value not in case.band_in
    )

    rejected: list[str] = []
    if macro is None:
        rejected.append("macro-F1 is undefined: no scorable row was answered")
    if not hard:
        rejected.append("the calibration data holds no hard negative to check false positives on")
    elif n_false_positive / len(hard) > objective.max_fpr_hard_negative:
        rejected.append(
            f"false positives: {n_false_positive} of {len(hard)} hard negatives flagged, "
            f"above the cap of {objective.max_fpr_hard_negative:.0%}"
        )
    if coverage < objective.min_coverage:
        rejected.append(
            f"coverage {coverage:.3f} is under the floor of {objective.min_coverage:.2f}"
        )
    if failures:
        rejected.append(
            f"guard: {len(failures)} regression case{'s' if len(failures) != 1 else ''} "
            "would leave the allowed band"
        )

    return Candidate(
        thresholds=thresholds,
        labels=labels,
        macro_f1=macro,
        per_class_f1=per_class,
        n_scam=len(scam),
        n_scam_flagged=sum(1 for label in scam if label == "scam"),
        n_hard_negative=len(hard),
        n_false_positive=n_false_positive,
        coverage=coverage,
        guard_failures=failures,
        rejected=tuple(rejected),
    )


# ---------------------------------------------------------------------------
# The paired comparison, resampling source groups
# ---------------------------------------------------------------------------

#: Position of each (gold, predicted) pair in a group's count vector.
_PAIRS: dict[tuple[str, str], int] = {
    ("legit", "legit"): 0,
    ("legit", "scam"): 1,
    ("scam", "legit"): 2,
    ("scam", "scam"): 3,
}


def _group_counts(rows: Sequence[Scored], labels: Sequence[str]) -> NDArray[np.int64]:
    """Per source group, how many rows fall in each cell of the 2x2 table."""
    order: dict[str, int] = {}
    for row in rows:
        order.setdefault(row.group or row.id, len(order))
    counts = np.zeros((len(order), len(_PAIRS)), dtype=np.int64)
    for row, label in zip(rows, labels, strict=True):
        cell = _PAIRS.get((row.label, label))
        if cell is not None:  # ambiguous gold rows and abstentions are not scored
            counts[order[row.group or row.id], cell] += 1
    return counts


def macro_f1_from_counts(counts: NDArray[Any]) -> NDArray[np.float64]:
    """Macro-F1 from `[tn, fp, fn, tp]` along the last axis.

    The same statistic as `metrics.macro_f1` over the two binary labels: a
    class absent from both the gold and the predicted side is skipped.
    """
    tn, fp, fn, tp = (counts[..., i].astype(np.float64) for i in range(4))
    numerator = np.stack([2.0 * tn, 2.0 * tp], axis=-1)
    denominator = np.stack([2.0 * tn + fp + fn, 2.0 * tp + fp + fn], axis=-1)
    defined = denominator > 0
    f1 = np.where(defined, numerator / np.maximum(denominator, 1.0), 0.0)
    n_defined = defined.sum(axis=-1)
    return np.where(n_defined > 0, f1.sum(axis=-1) / np.maximum(n_defined, 1), np.nan)


@dataclass(frozen=True)
class Comparison:
    """Macro-F1 of a challenger minus that of the incumbent, with its interval."""

    delta: float
    lo: float
    hi: float
    n_groups: int
    n_resamples: int
    seed: int

    @property
    def decisive(self) -> bool:
        """The whole interval lies above zero."""
        return self.lo > 0.0


def compare_paired(
    rows: Sequence[Scored],
    challenger: Sequence[str],
    incumbent: Sequence[str],
    *,
    seed: int,
    n_resamples: int,
    alpha: float = 0.05,
) -> Comparison:
    """Percentile interval of the paired macro-F1 difference over source groups.

    Each resample draws as many groups as there are, with replacement, and
    both systems are scored on the same draw, so the interval is of the
    difference and not of two numbers that happen to share rows.
    """
    theirs = _group_counts(rows, challenger)
    ours = _group_counts(rows, incumbent)
    n_groups = theirs.shape[0]
    if n_groups == 0:
        raise CalibrationError("no rows to compare on")
    rng = np.random.default_rng(seed)
    draws = rng.multinomial(n_groups, np.full(n_groups, 1.0 / n_groups), size=n_resamples)
    deltas = macro_f1_from_counts(draws @ theirs) - macro_f1_from_counts(draws @ ours)
    deltas = deltas[~np.isnan(deltas)]
    if deltas.size == 0:
        raise CalibrationError("the paired difference is undefined in every resample")
    lo, hi = np.quantile(deltas, [alpha / 2.0, 1.0 - alpha / 2.0])
    point = macro_f1_from_counts(theirs.sum(axis=0)) - macro_f1_from_counts(ours.sum(axis=0))
    return Comparison(float(point), float(lo), float(hi), n_groups, n_resamples, seed)


# ---------------------------------------------------------------------------
# The fit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fit:
    """The search and its outcome."""

    candidates: tuple[Candidate, ...]
    incumbent: Candidate
    #: The admissible candidate with the highest macro-F1.
    best: Candidate
    #: Present when the best candidate is not the incumbent and both are admissible.
    comparison: Comparison | None
    selected: Candidate
    reason: str


def fit(
    rows: Sequence[Scored],
    guard: Sequence[ScoredGuard],
    *,
    seed: int,
    n_bootstrap: int,
    incumbent: Thresholds = DEFAULT_THRESHOLDS,
    objective: Objective = DEFAULT_OBJECTIVE,
    positive_bands: Sequence[str] = ("scam", "suspicious"),
) -> Fit:
    """Search the grid and apply the selection rule in the module docstring."""
    if not rows:
        raise CalibrationError("no calibration rows")

    def score(thresholds: Thresholds) -> Candidate:
        return evaluate(thresholds, rows, guard, objective=objective, positive_bands=positive_bands)

    candidates = tuple(score(t) for t in candidate_grid(incumbent))
    current = next((c for c in candidates if c.thresholds == incumbent), None) or score(incumbent)
    pool = [c for c in (*candidates, current) if c.admissible]
    if not pool:
        raise CalibrationError(
            "no admissible candidate: every threshold breaks the false-positive cap, "
            "the coverage floor or the regression suite"
        )
    best = max(pool, key=lambda c: (c.macro_f1, c.suspicious))

    if best.thresholds == current.thresholds:
        return Fit(
            candidates,
            current,
            best,
            None,
            current,
            "The incumbent is the best admissible candidate, so it stays.",
        )
    if not current.admissible:
        return Fit(
            candidates,
            current,
            best,
            None,
            best,
            "The incumbent is not admissible ("
            + "; ".join(current.rejected)
            + "), so the best admissible candidate replaces it.",
        )

    comparison = compare_paired(
        rows,
        best.labels,
        current.labels,
        seed=seed,
        n_resamples=n_bootstrap,
        alpha=objective.alpha,
    )
    interval = f"[{comparison.lo:+.3f}, {comparison.hi:+.3f}]"
    if comparison.decisive:
        return Fit(
            candidates,
            current,
            best,
            comparison,
            best,
            f"The best candidate gains {comparison.delta:+.3f} macro-F1 over the incumbent "
            f"and the interval of that gain over source groups, {interval}, lies above "
            "zero, so it replaces the incumbent.",
        )
    return Fit(
        candidates,
        current,
        best,
        comparison,
        current,
        f"The best candidate gains {comparison.delta:+.3f} macro-F1 over the incumbent, "
        f"but the interval of that gain over source groups, {interval}, reaches zero: "
        "the gain rests on too few sources to tell from chance, so the incumbent stays.",
    )


# ---------------------------------------------------------------------------
# The artifact
# ---------------------------------------------------------------------------


def _digest(lines: Sequence[str]) -> str:
    return "sha256:" + hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rows_digest(rows: Sequence[DatasetRow]) -> str:
    """A fingerprint of what the fit read from the rows, whatever the file layout."""
    return _digest(
        [
            f"{r.id}\t{_text_hash(r.text)}\t{r.label}\t{int(r.hard_negative)}\t{r.source_group}"
            for r in rows
        ]
    )


def guard_digest(cases: Sequence[GuardCase]) -> str:
    return _digest([f"{c.id}\t{_text_hash(c.text)}\t{','.join(sorted(c.band_in))}" for c in cases])


def inputs_dirty(paths: Sequence[str | os.PathLike[str]]) -> bool | None:
    """Whether any of `paths` differs from the checked-out commit; None if unknown."""
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain", "--", *(str(p) for p in paths)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return bool(completed.stdout.strip())


def _num(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def _thresholds(thresholds: Thresholds) -> dict[str, float]:
    return {"suspicious": thresholds.suspicious, "scam": thresholds.scam}


def _candidate(candidate: Candidate, objective: Objective) -> dict[str, Any]:
    bound = None
    if candidate.n_hard_negative:
        bound = upper_bound(candidate.n_false_positive, candidate.n_hard_negative, objective.alpha)
    return {
        "suspicious": candidate.suspicious,
        "macro_f1": _num(candidate.macro_f1),
        "per_class_f1": {k: _num(v) for k, v in sorted(candidate.per_class_f1.items())},
        "n_scam_flagged": candidate.n_scam_flagged,
        "n_scam": candidate.n_scam,
        "n_false_positive": candidate.n_false_positive,
        "n_hard_negative": candidate.n_hard_negative,
        "fpr_upper_bound": _num(bound),
        "coverage": _num(candidate.coverage),
        "guard_failures": list(candidate.guard_failures),
        "admissible": candidate.admissible,
        "rejected": list(candidate.rejected),
    }


def _confirm(
    selected: Thresholds, rows: Sequence[DatasetRow], cases: Sequence[GuardCase]
) -> dict[str, Any]:
    """Run the real pipeline with the selected thresholds and compare bands.

    The search bands a stored risk; the product bands inside `fuse`. If the
    two ever differ the search has described a system that does not exist.
    """
    messages = [(row.text, _lang(row.lang)) for row in rows]
    messages += [(case.text, case.lang) for case in cases]
    stored = _verdicts(messages)
    live = _verdicts(messages, selected)
    differing = [
        index
        for index, (before, after) in enumerate(zip(stored, live, strict=True))
        if band_for(before.risk, selected) is not after.band
    ]
    if differing:
        raise CalibrationError(
            f"the pipeline run with the selected thresholds disagrees with the search on "
            f"{len(differing)} of {len(messages)} messages"
        )
    return {"messages": len(messages), "pipeline_agrees_with_search": True}


def choose_split(config: EvalConfig, split: str | None = None) -> str:
    """The split to fit on: the one asked for, else the first usable one.

    Raises for anything that is not calibration data. This is the line that
    keeps a test split out of the fit.
    """
    if split is not None:
        if split not in REGIMES:
            raise CalibrationError(
                f"thresholds are fitted on {' or '.join(REGIMES)}, never on {split!r}"
            )
        if split not in config.splits:
            raise CalibrationError(f"the config lists no {split!r} split")
        return split
    for name in REGIMES:
        if name in config.splits:
            path = config.split_path(name)
            if path.is_file() and path.stat().st_size > 0:
                return name
    raise CalibrationError(
        f"the config lists no readable {' or '.join(REGIMES)} split to fit on; "
        "thresholds are never fitted on a test split"
    )


def calibrate(
    config: EvalConfig,
    *,
    split: str | None = None,
    guard_dir: str | os.PathLike[str] = DEFAULT_GUARD_DIR,
    config_path: str | os.PathLike[str] | None = None,
    incumbent: Thresholds = DEFAULT_THRESHOLDS,
    objective: Objective = DEFAULT_OBJECTIVE,
) -> dict[str, Any]:
    """Fit the rules-only threshold and return the artifact as a dictionary."""
    name = choose_split(config, split)
    split_path = config.split_path(name)
    rows = load_split(split_path)
    if not rows:
        raise CalibrationError(f"{split_path.as_posix()} holds no rows")
    cases, skipped = load_guard(guard_dir)

    outcome = fit(
        score_rows(rows),
        score_guard(cases),
        seed=config.seed,
        n_bootstrap=config.n_bootstrap,
        incumbent=incumbent,
        objective=objective,
        positive_bands=config.positive_bands,
    )
    confirmation = _confirm(outcome.selected.thresholds, rows, cases)

    comparison = None
    if outcome.comparison is not None:
        comparison = {
            "challenger": outcome.best.suspicious,
            "incumbent": outcome.incumbent.suspicious,
            "delta_macro_f1": _num(outcome.comparison.delta),
            "ci95": [_num(outcome.comparison.lo), _num(outcome.comparison.hi)],
            "resampled": "source groups",
            "n_groups": outcome.comparison.n_groups,
            "n_resamples": outcome.comparison.n_resamples,
            "decisive": outcome.comparison.decisive,
        }
    watched = ["src", split_path, guard_dir]
    if config_path is not None:
        watched.append(config_path)

    return {
        "schema": SCHEMA,
        "system": SYSTEM,
        "model": NO_MODEL,
        "prompt_hash": None,
        "playbooks": "none: the rules-only system reads no playbook",
        "regime": REGIMES[name],
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code": {"git_commit": git_commit(), "inputs_differ_from_commit": inputs_dirty(watched)},
        "config": {
            "name": config.name,
            "path": Path(config_path).as_posix() if config_path is not None else None,
            "hash": config_hash(config),
            "positive_bands": list(config.positive_bands),
        },
        "seed": config.seed,
        "n_bootstrap": config.n_bootstrap,
        "data": {
            "split": name,
            "path": split_path.as_posix(),
            "digest": rows_digest(rows),
            **count_support(rows),
        },
        "guard": {
            "path": Path(guard_dir).as_posix(),
            "digest": guard_digest(cases),
            "n_cases": len(cases),
            "left_out": skipped,
        },
        "objective": {
            "maximise": "macro_f1 over scam and legit",
            "max_fpr_hard_negative": objective.max_fpr_hard_negative,
            "min_coverage": objective.min_coverage,
            "guard": "every regression case keeps a band it allows",
            "ties": "the higher threshold",
            "incumbent_rule": (
                "the incumbent is replaced only when the interval of the paired macro-F1 "
                "gain, resampling source groups, lies above zero"
            ),
            "alpha": objective.alpha,
        },
        "search": {
            "parameter": "thresholds.suspicious",
            "from": 1 / RULE_SCORE_CAP,
            "to": CEILING_POINTS / RULE_SCORE_CAP,
            "step": 1 / RULE_SCORE_CAP,
            "ceiling": "one critical indicator must never be likely safe",
            "not_fitted": NOT_FITTED,
        },
        "incumbent": _thresholds(outcome.incumbent.thresholds),
        "candidates": [_candidate(c, objective) for c in outcome.candidates],
        "best_by_objective": _candidate(outcome.best, objective),
        "comparison": comparison,
        "selected": {
            "thresholds": _thresholds(outcome.selected.thresholds),
            "reason": outcome.reason,
            **{
                key: value
                for key, value in _candidate(outcome.selected, objective).items()
                if key not in {"suspicious", "admissible", "rejected", "guard_failures"}
            },
        },
        "confirmation": confirmation,
    }


def write_artifact(payload: dict[str, Any], out_path: str | os.PathLike[str]) -> Path:
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return destination


def read_artifact(path: str | os.PathLike[str]) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise CalibrationError(f"{Path(path).as_posix()} is not a {SCHEMA} file")
    return payload


def describe(payload: dict[str, Any]) -> list[str]:
    """The fit in a few lines, for the terminal.

    Candidates that behave alike are folded into one line: between two
    attainable rule scores the threshold changes nothing.
    """
    data = payload["data"]
    groups = data.get("n_source_groups")
    lines = [
        f"{payload['system']} on `{data['split']}` ({payload['regime']}): {data['n_rows']} rows"
        + (f" in {groups} source groups" if groups is not None else "")
        + f", {data['n_hard_negative']} hard negatives; {payload['guard']['n_cases']} guard cases",
        "suspicious    macro-F1   scams flagged   false positives   guard failures",
    ]
    runs: list[list[dict[str, Any]]] = []
    for candidate in payload["candidates"]:
        key = (
            candidate["n_scam_flagged"],
            candidate["n_false_positive"],
            len(candidate["guard_failures"]),
            candidate["admissible"],
        )
        if runs and runs[-1][0]["_key"] == key:
            runs[-1].append(candidate)
        else:
            runs.append([{**candidate, "_key": key}])
    for run in runs:
        first, last = run[0], run[-1]
        span = (
            f"{first['suspicious']:.2f}"
            if first is last
            else f"{first['suspicious']:.2f}-{last['suspicious']:.2f}"
        )
        f1 = "-" if first["macro_f1"] is None else f"{first['macro_f1']:.3f}"
        lines.append(
            f"{span:<13} {f1:<10} {first['n_scam_flagged']:>3} of {first['n_scam']:<8} "
            f"{first['n_false_positive']:>3} of {first['n_hard_negative']:<11} "
            f"{len(first['guard_failures'])}" + ("" if first["admissible"] else "   not admissible")
        )
    best = payload["best_by_objective"]
    lines.append(
        f"best by the objective: {best['suspicious']:.2f} (macro-F1 {best['macro_f1']:.3f})"
    )
    selected = payload["selected"]
    lines.append(
        f"selected: suspicious {selected['thresholds']['suspicious']:.2f}, "
        f"scam {selected['thresholds']['scam']:.2f}. {selected['reason']}"
    )
    return lines
