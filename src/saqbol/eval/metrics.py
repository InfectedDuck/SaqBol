"""T502 — evaluation metrics, bootstrap intervals and annotator agreement.

Pure functions over label arrays. Nothing here imports the pipeline, opens a
socket or knows what a message looks like, because a number that can only be
produced by running the whole system is a number nobody can check by hand, and
every figure in the report has to be checkable by hand.

Four decisions here are worth defending rather than reading past.

**Bootstrap intervals are stratified by the true class.** An unstratified
resample of 148 rows will, often enough to matter, contain none of the four
`kz.mule_account_rental` items, and macro-F1 over a label set that lost a class
is not the same statistic as macro-F1 over the label set we reported. Drawing
within each true class, preserving that class's count, keeps every resample
comparable to the point estimate. The cost is that the interval covers sampling
noise *given* the class balance, not noise in the class balance itself, which
is the right trade for a fixed benchmark split.

**Undefined is not zero.** A class absent from both the gold labels and the
predictions has no F1, and a pair of annotators who both used a single category
have no kappa: chance agreement is already total, so the statistic carries no
information. Those cases return `nan` and are excluded from the macro average
rather than being scored 0.0 and quietly punishing a system for a class the
split could never have tested. `nan` prints as a dash in the leaderboard; 0.0
prints as a failure that never happened.

**Ties in the risk-coverage curve break pessimistically.** A system that emits
three distinct confidence values has large tied blocks, and the area under the
curve would otherwise depend on the order rows happened to arrive in. Errors
rank ahead of correct answers inside a tie, so the reported curve is the worst
ordering consistent with the confidences the system actually produced.

**No comparison without separation.** `overlaps`, `compare` and `beats` are the
only sanctioned way to phrase one system against another, and `beats` raises
rather than returning a sentence when the intervals touch. The README promises
that rule; a promise enforced by a function is a promise, and one enforced by
remembering is a hope.

The bootstrap is the percentile method, not BCa. For macro-F1 over several
hundred rows the difference sits well inside the interval's own width, and the
percentile method is the one a reader can reimplement from the description.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

#: Contract: docs/05_EVAL_PROTOCOL.md section 5, "Bootstrap, 10,000 resamples".
DEFAULT_N_RESAMPLES = 10_000
#: 95 percent intervals throughout.
DEFAULT_ALPHA = 0.05
#: The band a verdict carries when the pipeline declined to answer.
ABSTAIN_LABEL = "unsure"

#: Resamples are evaluated in blocks of roughly this many label cells, which
#: bounds peak memory without changing any result: every random draw is made up
#: front, so the block size affects speed only.
_CHUNK_CELLS = 1_000_000

CI = tuple[float, float]


# ---------------------------------------------------------------------------
# Label handling
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LabelSpace:
    """The closed set of labels a metric averages over, in a fixed order.

    The order is fixed because the point estimate and all 10,000 resamples must
    average over the same classes in the same positions. A space rebuilt per
    resample would give an interval around a slightly different statistic.
    """

    labels: tuple[str, ...]

    def __len__(self) -> int:
        return len(self.labels)

    def code(self, label: str) -> int:
        try:
            return self.labels.index(label)
        except ValueError:
            raise KeyError(f"{label!r} is not in the label space {self.labels}") from None

    def encode(self, values: Sequence[str]) -> NDArray[np.int16]:
        index = {label: i for i, label in enumerate(self.labels)}
        try:
            return np.fromiter((index[v] for v in values), dtype=np.int16, count=len(values))
        except KeyError as exc:
            raise KeyError(f"{exc.args[0]!r} is not in the label space {self.labels}") from None


def _check_arrays(*arrays: Sequence[object]) -> int:
    lengths = {len(a) for a in arrays}
    if len(lengths) != 1:
        raise ValueError(f"label arrays have different lengths: {[len(a) for a in arrays]}")
    (n,) = lengths
    if n == 0:
        raise ValueError("cannot compute a metric over zero rows")
    return n


def _label_space(*arrays: Sequence[str], labels: Sequence[str] | None = None) -> LabelSpace:
    observed = {v for array in arrays for v in array}
    if labels is None:
        return LabelSpace(tuple(sorted(observed)))
    declared = tuple(labels)
    unknown = sorted(observed - set(declared))
    if unknown:
        raise ValueError(f"labels not in the declared label set {declared}: {unknown}")
    return LabelSpace(declared)


def confusion_matrix(
    y_true: Sequence[str], y_pred: Sequence[str], *, labels: Sequence[str] | None = None
) -> tuple[LabelSpace, NDArray[np.int64]]:
    """Counts indexed `[true, predicted]`, with the space they are indexed by.

    Also the natural input to the confusable-pairs paragraph the annotation
    section asks for: the largest off-diagonal cells are the playbooks that
    keep turning into one another.
    """
    _check_arrays(y_true, y_pred)
    space = _label_space(y_true, y_pred, labels=labels)
    k = len(space)
    true_codes = space.encode(y_true).astype(np.int64)
    pred_codes = space.encode(y_pred).astype(np.int64)
    counts = np.bincount(true_codes * k + pred_codes, minlength=k * k)
    return space, counts.reshape(k, k)


# ---------------------------------------------------------------------------
# F1
# ---------------------------------------------------------------------------


def per_class_f1(
    y_true: Sequence[str], y_pred: Sequence[str], *, labels: Sequence[str] | None = None
) -> dict[str, float]:
    """F1 per class, `nan` where the class appears in neither array.

    Uses the identity `F1 = 2·tp / (support_true + support_pred)`, which is the
    same number as the precision-and-recall definition with one denominator
    instead of three, so a class with no instances has one place to go wrong
    rather than three.
    """
    space, matrix = confusion_matrix(y_true, y_pred, labels=labels)
    tp = np.diag(matrix).astype(np.float64)
    denominator = matrix.sum(axis=1) + matrix.sum(axis=0)
    return {
        label: float(2.0 * tp[i] / denominator[i]) if denominator[i] > 0 else math.nan
        for i, label in enumerate(space.labels)
    }


def macro_f1(
    y_true: Sequence[str], y_pred: Sequence[str], *, labels: Sequence[str] | None = None
) -> float:
    """Unweighted mean of the per-class F1 scores that are defined.

    Classes absent from both arrays are skipped, not counted as zero. Passing
    the full 13-playbook set for a split containing only 11 of them therefore
    gives the same number as passing those 11, which is what keeps two splits
    comparable.
    """
    scores = per_class_f1(y_true, y_pred, labels=labels).values()
    defined = [v for v in scores if not math.isnan(v)]
    if not defined:
        return math.nan
    return sum(defined) / len(defined)


def accuracy(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    n = _check_arrays(y_true, y_pred)
    return sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == p) / n


# ---------------------------------------------------------------------------
# False positives on hard negatives
# ---------------------------------------------------------------------------


def false_positive_rate(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    *,
    positive_labels: Iterable[str] = ("scam",),
    negative_label: str = "legit",
) -> float:
    """Share of genuinely negative rows predicted into `positive_labels`."""
    _check_arrays(y_true, y_pred)
    positive = set(positive_labels)
    negatives = [p for t, p in zip(y_true, y_pred, strict=True) if t == negative_label]
    if not negatives:
        return math.nan
    return sum(1 for p in negatives if p in positive) / len(negatives)


def hard_negative_fpr(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    hard_negative: Sequence[bool],
    *,
    positive_labels: Iterable[str] = ("scam",),
) -> float:
    """False positives divided by the hard-negative count, per contract 6.

    Hard negatives are legitimate messages that look like scams — real 1414
    codes, Kazpost tracking, Halyk login alerts — so a row flagged
    `hard_negative` whose gold label is a scam is a dataset error and raises
    here rather than being silently averaged in.

    Abstentions sit in the denominator and not the numerator, so a system can
    lower this number by declining to answer. That is why it is never reported
    without `coverage` beside it.
    """
    _check_arrays(y_true, y_pred, hard_negative)
    positive = set(positive_labels)
    rows = [(t, p) for t, p, flag in zip(y_true, y_pred, hard_negative, strict=True) if flag]
    if not rows:
        return math.nan
    mislabelled = sorted({t for t, _ in rows if t in positive})
    if mislabelled:
        raise ValueError(
            f"rows flagged hard_negative carry positive gold labels {mislabelled}; "
            "a hard negative is by definition a legitimate message"
        )
    return sum(1 for _, p in rows if p in positive) / len(rows)


# ---------------------------------------------------------------------------
# Abstention: coverage, selective risk, risk-coverage curve
# ---------------------------------------------------------------------------


def coverage(y_pred: Sequence[str], *, abstain_label: str = ABSTAIN_LABEL) -> float:
    """Share of rows the system actually answered."""
    n = _check_arrays(y_pred)
    return sum(1 for p in y_pred if p != abstain_label) / n


def abstain_rate(y_pred: Sequence[str], *, abstain_label: str = ABSTAIN_LABEL) -> float:
    return 1.0 - coverage(y_pred, abstain_label=abstain_label)


def selective_risk(
    y_true: Sequence[str], y_pred: Sequence[str], *, abstain_label: str = ABSTAIN_LABEL
) -> float:
    """Error rate among the answered rows, at the system's own operating point.

    `nan` when the system answered nothing: an error rate over no answers is
    not zero.
    """
    _check_arrays(y_true, y_pred)
    answered = [(t, p) for t, p in zip(y_true, y_pred, strict=True) if p != abstain_label]
    if not answered:
        return math.nan
    return sum(1 for t, p in answered if t != p) / len(answered)


@dataclass(frozen=True)
class RiskCoverage:
    """Error rate among the k most confident answers, for every k.

    `coverage[i]` is `(i + 1) / n` and `risk[i]` the error rate over those
    rows. `aurc` is the mean of `risk`; lower is better, and it is the one
    number that says whether the confidence signal orders answers usefully at
    all. A system whose confidences are noise has an `aurc` equal to its
    overall error rate, so that error rate is the baseline any abstention claim
    has to beat.
    """

    coverage: tuple[float, ...]
    risk: tuple[float, ...]
    aurc: float

    def risk_at(self, coverage_target: float) -> float:
        """Risk at the smallest coverage that reaches `coverage_target`."""
        for c, r in zip(self.coverage, self.risk, strict=True):
            if c >= coverage_target - 1e-12:
                return r
        raise ValueError(f"coverage {coverage_target} is above the maximum {self.coverage[-1]}")


def risk_coverage_curve(
    y_true: Sequence[str], y_pred: Sequence[str], confidence: Sequence[float]
) -> RiskCoverage:
    """Sweep the confidence threshold and record error rate against coverage.

    Every row must carry a prediction: this is the what-if curve over the
    system's forced answers, and abstention is then one threshold on it rather
    than a separate label. The operating point the pipeline actually ships is
    `coverage()` and `selective_risk()`, which belong on the same plot as a
    marked point.
    """
    n = _check_arrays(y_true, y_pred, confidence)
    correct = np.fromiter(
        (t == p for t, p in zip(y_true, y_pred, strict=True)), dtype=bool, count=n
    )
    scores = np.asarray(confidence, dtype=np.float64)
    if not np.all(np.isfinite(scores)):
        raise ValueError("confidence values must be finite")
    # Primary key last: descending confidence, then errors before correct
    # answers within a tie, which is the pessimistic ordering.
    order = np.lexsort((correct, -scores))
    ranked = correct[order]
    k = np.arange(1, n + 1, dtype=np.float64)
    risk = np.cumsum(~ranked) / k
    return RiskCoverage(
        coverage=tuple((k / n).tolist()),
        risk=tuple(risk.tolist()),
        aurc=float(risk.mean()),
    )


# ---------------------------------------------------------------------------
# Stage accuracy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageAccuracy:
    """Stage accuracy with the denominator it was computed over.

    The denominator travels with the number because it is small: stage is only
    labelled on multi-message threads, and 0.83 over twelve eligible rows is a
    different claim from 0.83 over four hundred.
    """

    accuracy: float
    n_correct: int
    n_eligible: int


def stage_accuracy(
    true_playbook: Sequence[str],
    pred_playbook: Sequence[str],
    true_stage: Sequence[str | None],
    pred_stage: Sequence[str | None],
) -> StageAccuracy:
    """Stage accuracy conditional on the playbook being right.

    Unconditional stage accuracy is uninterpretable: a system that identified
    the wrong script and then named a stage inside it was not partly correct.
    A row counts only when the playbook matches and a gold stage exists; a
    missing predicted stage on an eligible row counts as wrong, because the
    thread had a stage and the system failed to name it.
    """
    _check_arrays(true_playbook, pred_playbook, true_stage, pred_stage)
    eligible = [
        (ts, ps)
        for tp, pp, ts, ps in zip(true_playbook, pred_playbook, true_stage, pred_stage, strict=True)
        if tp == pp and ts is not None
    ]
    if not eligible:
        return StageAccuracy(accuracy=math.nan, n_correct=0, n_eligible=0)
    correct = sum(1 for ts, ps in eligible if ps == ts)
    return StageAccuracy(
        accuracy=correct / len(eligible), n_correct=correct, n_eligible=len(eligible)
    )


# ---------------------------------------------------------------------------
# Annotator agreement
# ---------------------------------------------------------------------------


def cohens_kappa(
    annotator_a: Sequence[str],
    annotator_b: Sequence[str],
    *,
    labels: Sequence[str] | None = None,
) -> float:
    """Cohen's kappa, `nan` where chance agreement is already total.

    If both annotators used exactly one category, expected agreement is 1 and
    kappa is 0/0. That is undefined, not perfect: returning 1.0 would print
    flawless agreement for a playbook neither annotator ever chose, in the
    per-class table whose whole job is to show which playbooks are confusable.
    """
    _check_arrays(annotator_a, annotator_b)
    _, matrix = confusion_matrix(annotator_a, annotator_b, labels=labels)
    n = float(matrix.sum())
    observed = float(np.trace(matrix)) / n
    marginal_a = matrix.sum(axis=1) / n
    marginal_b = matrix.sum(axis=0) / n
    expected = float(marginal_a @ marginal_b)
    if 1.0 - expected <= 1e-12:
        return math.nan
    return (observed - expected) / (1.0 - expected)


def kappa_per_class(
    annotator_a: Sequence[str],
    annotator_b: Sequence[str],
    *,
    labels: Sequence[str] | None = None,
) -> dict[str, float]:
    """One-vs-rest kappa per label — the table protocol section 3 asks for.

    Overall kappa hides the finding. `kz.bank_security_call` against
    `kz.remote_access_loan` is expected to be low because one script often
    becomes the other, and that is a property of the domain worth a paragraph,
    not a number to bury inside an average.
    """
    space = _label_space(annotator_a, annotator_b, labels=labels)
    out: dict[str, float] = {}
    for label in space.labels:
        binary_a = ["yes" if v == label else "no" for v in annotator_a]
        binary_b = ["yes" if v == label else "no" for v in annotator_b]
        out[label] = cohens_kappa(binary_a, binary_b, labels=("no", "yes"))
    return out


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


class BatchStatistic(Protocol):
    """A metric evaluated over many resamples at once.

    Takes `(true_codes, pred_codes)` of shape `(resamples, rows)` plus the
    label space they are coded against, and returns one value per resample.
    Vectorising over resamples rather than looping is the whole reason 10,000
    of them finish in well under a second.
    """

    def __call__(
        self,
        true_codes: NDArray[np.int16],
        pred_codes: NDArray[np.int16],
        space: LabelSpace,
    ) -> NDArray[np.float64]: ...


def _macro_f1_batch(
    true_codes: NDArray[np.int16], pred_codes: NDArray[np.int16], space: LabelSpace
) -> NDArray[np.float64]:
    b, _ = true_codes.shape
    k = len(space)
    # One bincount over every resample at once: the resample index is folded
    # into the key so each resample owns its own k*k block of bins.
    keys = (
        true_codes.astype(np.int64) * k
        + pred_codes
        + (np.arange(b, dtype=np.int64) * (k * k))[:, None]
    )
    counts = np.bincount(keys.ravel(), minlength=b * k * k).reshape(b, k, k)
    diagonal = np.arange(k)
    tp = counts[:, diagonal, diagonal].astype(np.float64)
    denominator = counts.sum(axis=2) + counts.sum(axis=1)
    defined = denominator > 0
    f1 = np.where(defined, 2.0 * tp / np.maximum(denominator, 1), 0.0)
    n_defined = defined.sum(axis=1)
    return np.where(n_defined > 0, f1.sum(axis=1) / np.maximum(n_defined, 1), np.nan)


def _accuracy_batch(
    true_codes: NDArray[np.int16], pred_codes: NDArray[np.int16], space: LabelSpace
) -> NDArray[np.float64]:
    return (true_codes == pred_codes).mean(axis=1)


#: Macro-F1 over the label space. The default statistic, and the headline.
MACRO_F1: BatchStatistic = _macro_f1_batch
ACCURACY: BatchStatistic = _accuracy_batch


def class_f1_statistic(label: str) -> BatchStatistic:
    """F1 for one class, for a per-playbook interval."""

    def statistic(
        true_codes: NDArray[np.int16], pred_codes: NDArray[np.int16], space: LabelSpace
    ) -> NDArray[np.float64]:
        code = space.code(label)
        is_true = true_codes == code
        is_pred = pred_codes == code
        tp = (is_true & is_pred).sum(axis=1).astype(np.float64)
        denominator = is_true.sum(axis=1) + is_pred.sum(axis=1)
        return np.where(denominator > 0, 2.0 * tp / np.maximum(denominator, 1), np.nan)

    return statistic


def predicted_rate_statistic(labels: Iterable[str]) -> BatchStatistic:
    """Share of rows predicted into `labels`.

    Over hard negatives this is the false-positive rate, which is how the
    headline FPR gets an interval. A requested label absent from the space
    contributes nothing rather than raising: nobody predicted it, so its rate
    is genuinely zero.
    """
    wanted = tuple(labels)

    def statistic(
        true_codes: NDArray[np.int16], pred_codes: NDArray[np.int16], space: LabelSpace
    ) -> NDArray[np.float64]:
        codes = np.array([space.code(v) for v in wanted if v in space.labels], dtype=np.int16)
        if codes.size == 0:
            return np.zeros(pred_codes.shape[0], dtype=np.float64)
        return np.isin(pred_codes, codes).mean(axis=1)

    return statistic


@dataclass(frozen=True)
class Estimate:
    """A point estimate with the interval around it and the seed that made it.

    The seed travels with the number so a published interval can be regenerated
    exactly. An interval whose seed was not recorded is a number nobody can
    reproduce, which under this project's reproducibility rules means it cannot
    be published.
    """

    point: float
    lo: float
    hi: float
    n: int
    n_resamples: int
    seed: int
    alpha: float = DEFAULT_ALPHA
    #: "bootstrap", or "exact_binomial" where a bootstrap interval would have
    #: had no width and the bound was computed in closed form instead.
    method: str = "bootstrap"

    @property
    def ci(self) -> CI:
        return (self.lo, self.hi)

    @property
    def width(self) -> float:
        return self.hi - self.lo

    def format(self, ndigits: int = 3) -> str:
        return f"{self.point:.{ndigits}f} [{self.lo:.{ndigits}f}, {self.hi:.{ndigits}f}]"

    def __str__(self) -> str:
        return self.format()


def _stratified_resample(strata: Sequence[str], n_resamples: int, seed: int) -> NDArray[np.int32]:
    """Row indices for every resample, drawn within each stratum.

    Each stratum keeps exactly its original size in every resample, so a class
    with four rows has four rows in all 10,000 of them and cannot vanish.
    Strata are visited in sorted order and every draw is made up front, so the
    result depends on the seed alone: not on how the caller ordered the rows,
    and not on how the statistic is chunked afterwards.

    Costs `4 · n_resamples · n` bytes, which is 28 MB for 10,000 resamples of
    700 rows.
    """
    rng = np.random.default_rng(seed)
    values = np.asarray([str(v) for v in strata])
    groups = [np.flatnonzero(values == key) for key in sorted(set(values.tolist()))]
    draws = [
        group[rng.integers(0, group.size, size=(n_resamples, group.size))].astype(np.int32)
        for group in groups
    ]
    return np.concatenate(draws, axis=1)


def bootstrap_ci(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    *,
    statistic: BatchStatistic = MACRO_F1,
    seed: int,
    n_resamples: int = DEFAULT_N_RESAMPLES,
    alpha: float = DEFAULT_ALPHA,
    labels: Sequence[str] | None = None,
    strata: Sequence[str] | None = None,
) -> Estimate:
    """Percentile bootstrap interval, stratified by true class.

    `seed` is required and has no default, because the alternative is an
    interval nobody can regenerate and therefore nobody can publish.

    The point estimate comes from calling the same `statistic` on a batch of
    one, so the number in the middle of the interval and the numbers that built
    the interval can never come from two different definitions.

    Pass `strata` to stratify by something else — language, for a per-language
    interval — or a constant array to switch stratification off.
    """
    n = _check_arrays(y_true, y_pred)
    if n_resamples < 1:
        raise ValueError("n_resamples must be at least 1")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must lie strictly between 0 and 1")
    if strata is not None:
        _check_arrays(y_true, strata)

    space = _label_space(y_true, y_pred, labels=labels)
    true_codes = space.encode(y_true)
    pred_codes = space.encode(y_pred)
    point = float(statistic(true_codes[None, :], pred_codes[None, :], space)[0])

    indices = _stratified_resample(
        list(strata) if strata is not None else list(y_true), n_resamples, seed
    )
    values = np.empty(n_resamples, dtype=np.float64)
    chunk = max(1, min(n_resamples, _CHUNK_CELLS // n))
    for start in range(0, n_resamples, chunk):
        block = indices[start : start + chunk]
        values[start : start + chunk] = statistic(true_codes[block], pred_codes[block], space)

    lo, hi = np.percentile(values, [100.0 * alpha / 2.0, 100.0 * (1.0 - alpha / 2.0)])
    return Estimate(
        point=point,
        lo=float(lo),
        hi=float(hi),
        n=n,
        n_resamples=n_resamples,
        seed=seed,
        alpha=alpha,
    )


def exact_binomial_bound(successes: int, n: int, *, alpha: float = DEFAULT_ALPHA) -> CI:
    """One-sided exact bound on a proportion observed as none, or as all, of `n`.

    Resampling rows that all gave the same answer returns that answer every
    time, so the percentile bootstrap reports 0 of 17 as [0.000, 0.000]: a
    claim of certainty from seventeen rows. The honest statement is the
    largest rate that would still produce no events in `n` trials with
    probability `alpha`, which is `1 - alpha ** (1 / n)`. For 0 of 17 that is
    0.162; for 0 of 30, 0.095. The mirror image holds when every trial was an
    event.
    """
    if n <= 0:
        raise ValueError("a bound needs at least one trial")
    if successes not in (0, n):
        raise ValueError(
            f"the closed-form bound is for 0 or {n} events out of {n}, got {successes}; "
            "use the bootstrap interval"
        )
    edge = alpha ** (1.0 / n)
    return (0.0, 1.0 - edge) if successes == 0 else (edge, 1.0)


def hard_negative_fpr_ci(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    hard_negative: Sequence[bool],
    *,
    seed: int,
    positive_labels: Iterable[str] = ("scam",),
    n_resamples: int = DEFAULT_N_RESAMPLES,
    alpha: float = DEFAULT_ALPHA,
) -> Estimate:
    """Interval around the hard-negative false-positive rate.

    The protocol's own words make this the number that decides whether people
    uninstall, so it ships with an interval like everything else. Resampling is
    over the hard negatives only, which are all legitimate by definition, so
    there is no class left to stratify by.

    When no hard negative was flagged, or every one was, the bootstrap has
    nothing to vary and the interval is the exact one-sided binomial bound
    instead; `method` on the returned estimate says which was used.
    """
    _check_arrays(y_true, y_pred, hard_negative)
    # Validate the subset before resampling it, so a hard negative labelled
    # scam fails here rather than skewing 10,000 resamples.
    hard_negative_fpr(y_true, y_pred, hard_negative, positive_labels=positive_labels)
    subset_true = [t for t, flag in zip(y_true, hard_negative, strict=True) if flag]
    subset_pred = [p for p, flag in zip(y_pred, hard_negative, strict=True) if flag]
    if not subset_true:
        raise ValueError("no rows are flagged hard_negative")
    positive = set(positive_labels)
    estimate = bootstrap_ci(
        subset_true,
        subset_pred,
        statistic=predicted_rate_statistic(positive),
        seed=seed,
        n_resamples=n_resamples,
        alpha=alpha,
        strata=["hard_negative"] * len(subset_true),
    )
    flagged = sum(1 for p in subset_pred if p in positive)
    if flagged not in (0, len(subset_pred)):
        return estimate
    lo, hi = exact_binomial_bound(flagged, len(subset_pred), alpha=alpha)
    return replace(estimate, lo=lo, hi=hi, method="exact_binomial")


# ---------------------------------------------------------------------------
# The reporting rule
# ---------------------------------------------------------------------------


class OverlappingIntervals(ValueError):
    """Raised when a "beats" claim was requested for overlapping intervals."""


def _as_ci(value: Estimate | Sequence[float]) -> CI:
    if isinstance(value, Estimate):
        return value.ci
    lo, hi = value
    return (float(lo), float(hi))


def overlaps(ci_a: Estimate | Sequence[float], ci_b: Estimate | Sequence[float]) -> bool:
    """Do two 95 percent intervals overlap?

    Closed intervals: two that merely touch count as overlapping. The
    conservative direction is the right one, since the cost of being wrong is a
    claim in a report that the numbers do not support.
    """
    a_lo, a_hi = _as_ci(ci_a)
    b_lo, b_hi = _as_ci(ci_b)
    for lo, hi in ((a_lo, a_hi), (b_lo, b_hi)):
        if not (math.isfinite(lo) and math.isfinite(hi)):
            raise ValueError(f"interval [{lo}, {hi}] is not finite")
        if lo > hi:
            raise ValueError(f"interval [{lo}, {hi}] is inverted")
    return a_lo <= b_hi and b_lo <= a_hi


@dataclass(frozen=True)
class Comparison:
    """The outcome of holding two systems' intervals against each other."""

    metric: str
    name_a: str
    name_b: str
    a: Estimate
    b: Estimate
    separated: bool
    winner: str | None
    sentence: str


def compare(
    name_a: str,
    a: Estimate,
    name_b: str,
    b: Estimate,
    *,
    metric: str = "macro-F1",
    ndigits: int = 3,
) -> Comparison:
    """Compare two estimates and produce a sentence that is safe to publish.

    Never raises: when the intervals overlap it says so and names no winner.
    `beats` is the variant that refuses instead, for a caller that wants the
    claim or nothing.
    """
    separated = not overlaps(a, b)
    winner: str | None = None
    if separated:
        winner = name_a if a.point > b.point else name_b
        winner_estimate, loser, loser_estimate = (
            (a, name_b, b) if winner == name_a else (b, name_a, a)
        )
        sentence = (
            f"{winner} beats {loser} on {metric}: "
            f"{winner_estimate.format(ndigits)} against {loser_estimate.format(ndigits)}, "
            f"95 percent intervals disjoint."
        )
    else:
        sentence = (
            f"{name_a} and {name_b} are not separated on {metric}: "
            f"{a.format(ndigits)} against {b.format(ndigits)}, "
            f"95 percent intervals overlap, so no claim is made."
        )
    return Comparison(
        metric=metric,
        name_a=name_a,
        name_b=name_b,
        a=a,
        b=b,
        separated=separated,
        winner=winner,
        sentence=sentence,
    )


def beats(
    name_a: str,
    a: Estimate,
    name_b: str,
    b: Estimate,
    *,
    metric: str = "macro-F1",
    ndigits: int = 3,
) -> str:
    """The only sanctioned way to write an "X beats Y" sentence.

    Raises `OverlappingIntervals` when the intervals overlap. The README
    promises that no such claim appears without disjoint intervals, and the
    leaderboard is generated rather than written precisely so that the promise
    is kept by a function instead of by discipline.
    """
    result = compare(name_a, a, name_b, b, metric=metric, ndigits=ndigits)
    if not result.separated:
        raise OverlappingIntervals(result.sentence)
    return result.sentence
