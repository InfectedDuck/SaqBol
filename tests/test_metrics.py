"""T502 — metrics, bootstrap intervals and agreement.

Every F1 and kappa here is hand-computed in the test body and the arithmetic is
written out in a comment, because a metric checked against another
implementation of the same metric only proves the two agree. The numbers in the
report have to be defensible from first principles, so the tests are too.

The three properties worth the most are the ones the rest of M5 leans on: a
seeded resample is reproducible, a rare class survives every resample, and a
"beats" claim is impossible to write when the intervals overlap.
"""

from __future__ import annotations

import json
import math
import random
import time

import numpy as np
import pytest

from saqbol.eval.metrics import (
    ACCURACY,
    DEFAULT_N_RESAMPLES,
    MACRO_F1,
    CountStatistic,
    Estimate,
    OverlappingIntervals,
    abstain_rate,
    accuracy,
    beats,
    bootstrap_ci,
    class_f1_statistic,
    cohens_kappa,
    compare,
    confusion_matrix,
    coverage,
    exact_binomial_bound,
    false_positive_rate,
    hard_negative_fpr,
    hard_negative_fpr_ci,
    kappa_per_class,
    macro_f1,
    macro_f1_statistic,
    overlaps,
    per_class_f1,
    predicted_rate_statistic,
    risk_coverage_curve,
    selective_risk,
    stage_accuracy,
)
from saqbol.eval.results import ResultRow, Results, read_results, write_results

# A six-row set small enough to compute every metric by hand.
#
#   row  true       pred
#   0    scam       scam        correct
#   1    scam       legit       miss
#   2    legit      legit       correct
#   3    legit      legit       correct
#   4    legit      scam        false positive
#   5    ambiguous  ambiguous   correct
Y_TRUE = ["scam", "scam", "legit", "legit", "legit", "ambiguous"]
Y_PRED = ["scam", "legit", "legit", "legit", "scam", "ambiguous"]


def estimate(point: float, lo: float, hi: float) -> Estimate:
    return Estimate(point=point, lo=lo, hi=hi, n=100, n_resamples=10, seed=1)


# ---------------------------------------------------------------------------
# F1, by hand
# ---------------------------------------------------------------------------


def test_per_class_f1_matches_hand_computation():
    scores = per_class_f1(Y_TRUE, Y_PRED)
    # scam:      tp 1, support_true 2, support_pred 2 -> 2*1/(2+2) = 0.5
    # legit:     tp 2, support_true 3, support_pred 3 -> 2*2/(3+3) = 2/3
    # ambiguous: tp 1, support_true 1, support_pred 1 -> 2*1/(1+1) = 1.0
    assert scores["scam"] == pytest.approx(0.5)
    assert scores["legit"] == pytest.approx(2 / 3)
    assert scores["ambiguous"] == pytest.approx(1.0)


def test_macro_f1_is_the_unweighted_mean_of_the_three():
    # (0.5 + 2/3 + 1.0) / 3 = 0.7222...
    assert macro_f1(Y_TRUE, Y_PRED) == pytest.approx((0.5 + 2 / 3 + 1.0) / 3)


def test_f1_identity_agrees_with_precision_and_recall():
    # scam: precision 1/2, recall 1/2 -> F1 = 2pr/(p+r) = 0.5
    precision, recall = 1 / 2, 1 / 2
    assert per_class_f1(Y_TRUE, Y_PRED)["scam"] == pytest.approx(
        2 * precision * recall / (precision + recall)
    )


def test_accuracy_counts_the_four_correct_rows():
    assert accuracy(Y_TRUE, Y_PRED) == pytest.approx(4 / 6)


def test_confusion_matrix_is_indexed_true_then_predicted():
    space, matrix = confusion_matrix(Y_TRUE, Y_PRED)
    assert space.labels == ("ambiguous", "legit", "scam")
    # One legit row was predicted scam; no scam row was predicted ambiguous.
    assert matrix[space.code("legit"), space.code("scam")] == 1
    assert matrix[space.code("scam"), space.code("ambiguous")] == 0
    assert matrix.sum() == len(Y_TRUE)


def test_class_absent_from_both_arrays_is_undefined_not_zero():
    # kz.fake_store is in the declared label set but appears in neither array,
    # so it has no F1 and must not drag the macro average down.
    labels = ("scam", "legit", "ambiguous", "kz.fake_store")
    scores = per_class_f1(Y_TRUE, Y_PRED, labels=labels)
    assert math.isnan(scores["kz.fake_store"])
    assert macro_f1(Y_TRUE, Y_PRED, labels=labels) == pytest.approx(macro_f1(Y_TRUE, Y_PRED))


def test_unknown_label_is_rejected_rather_than_silently_averaged():
    with pytest.raises(ValueError, match="not in the declared label set"):
        macro_f1(Y_TRUE, Y_PRED, labels=("scam", "legit"))


def test_mismatched_lengths_are_rejected():
    with pytest.raises(ValueError, match="different lengths"):
        macro_f1(Y_TRUE, Y_PRED[:-1])


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------


def test_single_class_perfect_agreement_does_not_divide_by_zero():
    rows = ["scam"] * 5
    assert macro_f1(rows, rows) == pytest.approx(1.0)
    assert per_class_f1(rows, rows) == {"scam": 1.0}
    assert accuracy(rows, rows) == pytest.approx(1.0)
    # Chance agreement is already total, so kappa carries no information.
    assert math.isnan(cohens_kappa(rows, rows))


def test_single_class_completely_wrong_scores_zero_without_dividing_by_zero():
    # Both classes are defined (each has support on one side), each scores 0.
    assert macro_f1(["scam"] * 5, ["legit"] * 5) == pytest.approx(0.0)


def test_bootstrap_over_a_degenerate_input_is_a_degenerate_interval():
    rows = ["scam"] * 5
    result = bootstrap_ci(rows, rows, seed=1, n_resamples=200)
    assert result.point == pytest.approx(1.0)
    assert result.ci == (1.0, 1.0)


def test_metrics_refuse_an_empty_split():
    with pytest.raises(ValueError, match="zero rows"):
        macro_f1([], [])


# ---------------------------------------------------------------------------
# Agreement, by hand
# ---------------------------------------------------------------------------


def kappa_fixture() -> tuple[list[str], list[str]]:
    """The textbook 2x2 case: 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no."""
    a = ["yes"] * 20 + ["yes"] * 5 + ["no"] * 10 + ["no"] * 15
    b = ["yes"] * 20 + ["no"] * 5 + ["yes"] * 10 + ["no"] * 15
    return a, b


def test_cohens_kappa_matches_hand_computation():
    a, b = kappa_fixture()
    # po = (20 + 15) / 50                      = 0.70
    # pe = (25/50)(30/50) + (25/50)(20/50)     = 0.30 + 0.20 = 0.50
    # k  = (0.70 - 0.50) / (1 - 0.50)          = 0.40
    assert cohens_kappa(a, b) == pytest.approx(0.4)


def test_per_class_kappa_of_a_binary_task_equals_overall_kappa():
    a, b = kappa_fixture()
    per_class = kappa_per_class(a, b)
    assert per_class["yes"] == pytest.approx(0.4)
    assert per_class["no"] == pytest.approx(0.4)


def test_per_class_kappa_separates_a_confusable_pair_from_a_clean_one():
    # Six rows. The two annotators agree on every fake_store row and disagree
    # on half the bank_security_call rows, which land on remote_access_loan.
    a = ["bank_security_call"] * 4 + ["fake_store"] * 4
    b = ["bank_security_call", "remote_access_loan"] * 2 + ["fake_store"] * 4
    per_class = kappa_per_class(a, b)
    assert per_class["fake_store"] == pytest.approx(1.0)
    assert per_class["bank_security_call"] < per_class["fake_store"]


def test_kappa_is_undefined_for_a_label_neither_annotator_used():
    a, b = kappa_fixture()
    per_class = kappa_per_class(a, b, labels=("yes", "no", "kz.apk_install"))
    # Reporting 1.0 here would claim flawless agreement on a playbook nobody
    # ever chose, in the table whose job is to show what is confusable.
    assert math.isnan(per_class["kz.apk_install"])


def test_perfect_agreement_over_two_classes_is_kappa_one():
    a = ["scam", "legit", "scam", "legit"]
    assert cohens_kappa(a, list(a)) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Hard negatives
# ---------------------------------------------------------------------------


def test_hard_negative_fpr_divides_by_the_hard_negative_count():
    y_true = ["legit", "legit", "legit", "legit", "scam"]
    y_pred = ["scam", "legit", "legit", "scam", "scam"]
    hard = [True, True, True, False, False]
    # One of the three hard negatives was flagged. The other false positive is
    # on row 3, an ordinary legit message, which belongs to the plain FPR and
    # not to this one: the denominators are deliberately different.
    assert hard_negative_fpr(y_true, y_pred, hard) == pytest.approx(1 / 3)
    assert false_positive_rate(y_true, y_pred) == pytest.approx(2 / 4)


def test_abstentions_stay_in_the_hard_negative_denominator():
    y_true = ["legit"] * 4
    y_pred = ["scam", "unsure", "unsure", "legit"]
    hard = [True] * 4
    # One flag out of four, not one out of two: declining to answer must not
    # flatter the number that decides whether people uninstall.
    assert hard_negative_fpr(y_true, y_pred, hard) == pytest.approx(0.25)


def test_suspicious_can_be_counted_as_a_false_positive():
    y_true = ["legit"] * 2
    y_pred = ["suspicious", "legit"]
    hard = [True, True]
    assert hard_negative_fpr(y_true, y_pred, hard) == pytest.approx(0.0)
    assert hard_negative_fpr(
        y_true, y_pred, hard, positive_labels=("scam", "suspicious")
    ) == pytest.approx(0.5)


def test_a_hard_negative_labelled_scam_is_a_dataset_error():
    with pytest.raises(ValueError, match="hard negative is by definition"):
        hard_negative_fpr(["scam"], ["scam"], [True])


# ---------------------------------------------------------------------------
# Abstention and the risk-coverage curve
# ---------------------------------------------------------------------------


def test_coverage_and_abstain_rate_are_complements():
    y_pred = ["scam", "unsure", "legit", "unsure"]
    assert coverage(y_pred) == pytest.approx(0.5)
    assert abstain_rate(y_pred) == pytest.approx(0.5)


def test_selective_risk_ignores_the_rows_the_system_declined():
    y_true = ["scam", "scam", "legit", "legit"]
    y_pred = ["scam", "unsure", "scam", "legit"]
    # Three answered, one of them wrong.
    assert selective_risk(y_true, y_pred) == pytest.approx(1 / 3)


def test_selective_risk_over_no_answers_is_undefined_not_zero():
    assert math.isnan(selective_risk(["scam"] * 3, ["unsure"] * 3))


def test_risk_coverage_curve_when_confidence_ranks_the_error_last():
    y_true = ["a", "a", "a", "a"]
    y_pred = ["a", "a", "a", "b"]
    confidence = [0.9, 0.8, 0.7, 0.6]
    curve = risk_coverage_curve(y_true, y_pred, confidence)
    assert curve.coverage == (0.25, 0.5, 0.75, 1.0)
    assert curve.risk == pytest.approx([0.0, 0.0, 0.0, 0.25])
    assert curve.aurc == pytest.approx((0.0 + 0.0 + 0.0 + 0.25) / 4)


def test_risk_coverage_curve_punishes_a_confident_error():
    y_true = ["a", "a", "a", "a"]
    y_pred = ["a", "a", "a", "b"]
    confidence = [0.1, 0.2, 0.3, 0.9]  # the one error is the most confident
    curve = risk_coverage_curve(y_true, y_pred, confidence)
    assert curve.risk == pytest.approx([1.0, 0.5, 1 / 3, 0.25])
    assert curve.aurc == pytest.approx((1.0 + 0.5 + 1 / 3 + 0.25) / 4)


def test_ties_break_pessimistically():
    # Identical confidences everywhere: the curve must not depend on the order
    # the rows arrived in, so the error is ranked first either way.
    y_true = ["a", "a", "a", "a"]
    flat = [0.5] * 4
    first = risk_coverage_curve(y_true, ["b", "a", "a", "a"], flat)
    last = risk_coverage_curve(y_true, ["a", "a", "a", "b"], flat)
    assert first.risk[0] == pytest.approx(1.0)
    assert first.risk == pytest.approx(last.risk)


def test_risk_at_returns_the_first_coverage_that_reaches_the_target():
    curve = risk_coverage_curve(["a"] * 4, ["a", "a", "a", "b"], [0.9, 0.8, 0.7, 0.6])
    assert curve.risk_at(0.75) == pytest.approx(0.0)
    assert curve.risk_at(1.0) == pytest.approx(0.25)
    with pytest.raises(ValueError, match="above the maximum"):
        curve.risk_at(1.5)


def test_aurc_of_an_uninformative_confidence_signal_is_near_the_error_rate():
    # The baseline any abstention claim has to beat.
    rng = random.Random(0)
    y_true = ["a"] * 400
    y_pred = ["a"] * 360 + ["b"] * 40  # 10 percent error rate
    confidence = [rng.random() for _ in y_true]
    curve = risk_coverage_curve(y_true, y_pred, confidence)
    assert curve.aurc == pytest.approx(0.1, abs=0.05)


# ---------------------------------------------------------------------------
# Stage accuracy
# ---------------------------------------------------------------------------


def test_stage_accuracy_is_conditional_on_the_playbook_being_right():
    true_playbook = ["p1", "p1", "p1", "p2", "p1"]
    pred_playbook = ["p1", "p1", "p2", "p2", "p1"]
    true_stage = ["hook", "pressure", "hook", "contact", None]
    pred_stage = ["hook", "contact", "hook", "contact", "hook"]
    # Eligible: rows 0, 1, 3. Row 2 has the wrong playbook, row 4 has no gold
    # stage. Two of the three eligible rows have the right stage.
    result = stage_accuracy(true_playbook, pred_playbook, true_stage, pred_stage)
    assert result.n_eligible == 3
    assert result.n_correct == 2
    assert result.accuracy == pytest.approx(2 / 3)


def test_a_missing_predicted_stage_counts_as_wrong():
    result = stage_accuracy(["p1"], ["p1"], ["hook"], [None])
    assert result.n_eligible == 1
    assert result.accuracy == pytest.approx(0.0)


def test_stage_accuracy_over_no_eligible_rows_is_undefined():
    result = stage_accuracy(["p1"], ["p2"], ["hook"], ["hook"])
    assert result.n_eligible == 0
    assert math.isnan(result.accuracy)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def synthetic_run(n: int = 500, seed: int = 7) -> tuple[list[str], list[str]]:
    """A run with realistic class imbalance, including a four-row playbook."""
    rng = random.Random(seed)
    labels = ["legit"] * (n // 2) + ["scam"] * (n // 2 - 4) + ["ambiguous"] * 4
    y_true = labels[:n]
    y_pred = [
        label if rng.random() < 0.85 else rng.choice(["legit", "scam", "ambiguous"])
        for label in y_true
    ]
    return y_true, y_pred


def test_the_same_seed_gives_the_same_interval():
    y_true, y_pred = synthetic_run(n=200)
    first = bootstrap_ci(y_true, y_pred, seed=20260926, n_resamples=2000)
    second = bootstrap_ci(y_true, y_pred, seed=20260926, n_resamples=2000)
    # Exact equality, not approximate: a published interval that cannot be
    # regenerated bit for bit is not reproducible.
    assert first == second
    assert (first.lo, first.hi) == (second.lo, second.hi)


def test_a_different_seed_gives_a_different_interval_around_the_same_point():
    y_true, y_pred = synthetic_run(n=200)
    first = bootstrap_ci(y_true, y_pred, seed=1, n_resamples=2000)
    second = bootstrap_ci(y_true, y_pred, seed=2, n_resamples=2000)
    assert first.point == second.point
    assert (first.lo, first.hi) != (second.lo, second.hi)
    assert first.lo == pytest.approx(second.lo, abs=0.02)


def test_the_seed_and_resample_count_travel_with_the_estimate():
    y_true, y_pred = synthetic_run(n=100)
    result = bootstrap_ci(y_true, y_pred, seed=99, n_resamples=500)
    assert (result.seed, result.n_resamples, result.n) == (99, 500, 100)


def test_the_point_estimate_is_the_plain_macro_f1():
    y_true, y_pred = synthetic_run(n=200)
    result = bootstrap_ci(y_true, y_pred, seed=3, n_resamples=200)
    assert result.point == pytest.approx(macro_f1(y_true, y_pred))
    assert result.lo <= result.point <= result.hi


def test_the_interval_brackets_the_point_for_other_statistics_too():
    y_true, y_pred = synthetic_run(n=200)
    for statistic, expected in (
        (ACCURACY, accuracy(y_true, y_pred)),
        (class_f1_statistic("scam"), per_class_f1(y_true, y_pred)["scam"]),
    ):
        result = bootstrap_ci(y_true, y_pred, statistic=statistic, seed=5, n_resamples=500)
        assert result.point == pytest.approx(expected)
        assert result.lo <= result.point <= result.hi


def test_stratification_keeps_a_rare_class_in_every_resample():
    y_true, y_pred = synthetic_run(n=200)
    rare = "ambiguous"
    assert y_true.count(rare) == 4

    def count_rare(true_codes, pred_codes, space):
        return (true_codes == space.code(rare)).sum(axis=1).astype(float)

    result = bootstrap_ci(y_true, y_pred, statistic=count_rare, seed=11, n_resamples=2000)
    # Every resample holds exactly the original four rows of the rare class, so
    # the whole distribution collapses to a point. Unstratified, the class
    # would vanish from a resample often enough to distort the interval.
    assert result.ci == (4.0, 4.0)


def test_stratification_can_be_switched_off_with_a_constant_stratum():
    y_true, y_pred = synthetic_run(n=200)
    rare = "ambiguous"

    def count_rare(true_codes, pred_codes, space):
        return (true_codes == space.code(rare)).sum(axis=1).astype(float)

    result = bootstrap_ci(
        y_true,
        y_pred,
        statistic=count_rare,
        seed=11,
        n_resamples=2000,
        strata=["all"] * len(y_true),
    )
    assert result.lo < 4.0  # the rare class does shrink, and sometimes vanishes


def test_hard_negative_fpr_interval_agrees_with_the_point_estimate():
    y_true = ["legit"] * 40 + ["scam"] * 10
    y_pred = ["scam"] * 4 + ["legit"] * 36 + ["scam"] * 10
    hard = [True] * 40 + [False] * 10
    result = hard_negative_fpr_ci(y_true, y_pred, hard, seed=42, n_resamples=2000)
    assert result.point == pytest.approx(hard_negative_fpr(y_true, y_pred, hard))
    assert result.point == pytest.approx(0.1)
    assert result.n == 40
    assert 0.0 <= result.lo <= result.point <= result.hi <= 1.0


def test_a_positive_label_nobody_predicted_has_a_rate_of_zero():
    y_true = ["legit"] * 10
    y_pred = ["legit"] * 10
    hard = [True] * 10
    result = hard_negative_fpr_ci(y_true, y_pred, hard, seed=1, n_resamples=200)
    assert result.point == pytest.approx(0.0)
    # Ten clean rows do not prove a rate of zero: the interval is the exact
    # bound, not the zero-width one the bootstrap would give.
    assert result.method == "exact_binomial"
    assert result.lo == 0.0
    assert result.hi == pytest.approx(1 - 0.05 ** (1 / 10))


@pytest.mark.parametrize(("n", "upper"), [(17, 0.162), (30, 0.095), (60, 0.049)])
def test_the_exact_bound_for_no_events_matches_the_figures_in_the_holdout_policy(n, upper):
    lo, hi = exact_binomial_bound(0, n)
    assert lo == 0.0
    assert hi == pytest.approx(upper, abs=0.0005)


def test_the_exact_bound_mirrors_when_every_trial_was_an_event():
    lo, hi = exact_binomial_bound(17, 17)
    assert hi == 1.0
    assert lo == pytest.approx(1 - 0.162, abs=0.0005)


def test_the_exact_bound_refuses_a_count_the_bootstrap_can_handle():
    with pytest.raises(ValueError, match="bootstrap"):
        exact_binomial_bound(3, 17)
    with pytest.raises(ValueError, match="at least one trial"):
        exact_binomial_bound(0, 0)


def test_every_hard_negative_flagged_gets_a_lower_bound_not_a_point():
    y_true = ["legit"] * 12
    y_pred = ["scam"] * 12
    result = hard_negative_fpr_ci(y_true, y_pred, [True] * 12, seed=1, n_resamples=200)
    assert result.method == "exact_binomial"
    assert result.point == pytest.approx(1.0)
    assert result.hi == 1.0
    assert result.lo == pytest.approx(0.05 ** (1 / 12))


def test_a_mixed_hard_negative_cell_keeps_its_bootstrap_interval():
    y_true = ["legit"] * 40
    y_pred = ["scam"] * 4 + ["legit"] * 36
    result = hard_negative_fpr_ci(y_true, y_pred, [True] * 40, seed=42, n_resamples=500)
    assert result.method == "bootstrap"
    assert result.lo < result.point < result.hi


def test_predicted_rate_statistic_counts_several_labels():
    y_true = ["legit"] * 4
    y_pred = ["scam", "suspicious", "legit", "legit"]
    result = bootstrap_ci(
        y_true,
        y_pred,
        statistic=predicted_rate_statistic(("scam", "suspicious")),
        seed=1,
        n_resamples=200,
    )
    assert result.point == pytest.approx(0.5)


def test_ten_thousand_resamples_over_five_hundred_rows_finish_in_under_two_seconds():
    y_true, y_pred = synthetic_run(n=500)
    start = time.perf_counter()
    result = bootstrap_ci(y_true, y_pred, seed=13, n_resamples=DEFAULT_N_RESAMPLES)
    elapsed = time.perf_counter() - start
    assert result.n_resamples == 10_000
    assert elapsed < 2.0, f"bootstrap took {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# Intervals over source groups
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statistic",
    [MACRO_F1, ACCURACY, class_f1_statistic("scam"), predicted_rate_statistic(["scam"])],
)
def test_one_row_per_group_is_the_row_bootstrap_draw_for_draw(statistic):
    y_true, y_pred = synthetic_run(n=200)
    rows = bootstrap_ci(y_true, y_pred, statistic=statistic, seed=7, n_resamples=2000)
    groups = bootstrap_ci(
        y_true,
        y_pred,
        statistic=statistic,
        seed=7,
        n_resamples=2000,
        groups=[f"g{i}" for i in range(200)],
    )
    # Exact equality: the grouped path makes the same draws from the same
    # seed, so a split whose rows are all independent keeps its intervals.
    assert (groups.point, groups.lo, groups.hi) == (rows.point, rows.lo, rows.hi)
    assert groups.ci_rows == groups.ci_groups == rows.ci
    assert (rows.n_groups, groups.n_groups) == (None, 200)


def _copies(n_groups: int, size: int) -> tuple[list[str], list[str], list[str]]:
    """Groups of identical rows: every row of a group has the same answer."""
    rng = random.Random(4)
    y_true, y_pred, groups = [], [], []
    for g in range(n_groups):
        label = "scam" if g % 2 else "legit"
        answer = label if rng.random() < 0.75 else ("legit" if label == "scam" else "scam")
        y_true += [label] * size
        y_pred += [answer] * size
        groups += [f"article-{g}"] * size
    return y_true, y_pred, groups


def test_rows_copied_within_an_article_widen_the_interval_as_one_piece_of_evidence():
    y_true, y_pred, groups = _copies(n_groups=24, size=5)
    rows = bootstrap_ci(y_true, y_pred, seed=3, n_resamples=4000)
    grouped = bootstrap_ci(y_true, y_pred, seed=3, n_resamples=4000, groups=groups)
    assert grouped.point == rows.point
    assert grouped.n_groups == 24
    # Five copies of each answer are one answer: resampling rows treats them
    # as five and gives an interval about sqrt(5) times too narrow.
    assert grouped.width > 1.8 * rows.width
    assert grouped.ci_rows == rows.ci
    assert grouped.ci == grouped.ci_groups


def test_few_mixed_groups_cannot_narrow_the_interval_below_the_row_one():
    # Every article holds one right and one wrong answer, so the articles
    # look alike and resampling eight of them understates the spread.
    y_true = ["scam", "scam"] * 8 + ["legit", "legit"] * 8
    y_pred = ["scam", "legit"] * 8 + ["legit", "scam"] * 8
    groups = [f"article-{i // 2}" for i in range(32)]
    result = bootstrap_ci(y_true, y_pred, seed=2, n_resamples=4000, groups=groups)
    rows = bootstrap_ci(y_true, y_pred, seed=2, n_resamples=4000)
    assert result.ci_groups is not None
    assert result.ci_groups[1] - result.ci_groups[0] < rows.width
    assert result.ci == rows.ci


def test_every_class_of_the_point_estimate_is_in_every_grouped_resample():
    # Two groups hold the only ambiguous rows, and one group mixes classes.
    y_true = ["ambiguous", "ambiguous", "ambiguous"] + ["scam"] * 20 + ["legit"] * 20
    y_pred = ["scam"] * 3 + ["scam"] * 15 + ["legit"] * 5 + ["legit"] * 18 + ["scam"] * 2
    groups = ["a", "a", "b"] + [f"s{i // 2}" for i in range(20)] + [f"l{i // 4}" for i in range(20)]
    groups[3] = "b"  # article b quotes an ambiguous row and a scam

    def classes_present(counts, space):
        return (counts.sum(axis=2) > 0).sum(axis=1).astype(float)

    result = bootstrap_ci(
        y_true,
        y_pred,
        statistic=CountStatistic(classes_present),
        seed=1,
        n_resamples=2000,
        groups=groups,
    )
    assert result.ci == (3.0, 3.0)


def test_the_same_seed_gives_the_same_grouped_interval():
    y_true, y_pred, groups = _copies(n_groups=30, size=3)
    first = bootstrap_ci(y_true, y_pred, seed=11, n_resamples=1000, groups=groups)
    second = bootstrap_ci(y_true, y_pred, seed=11, n_resamples=1000, groups=groups)
    assert first == second


def test_a_grouped_interval_needs_a_statistic_of_the_confusion_matrix():
    y_true, y_pred, groups = _copies(n_groups=10, size=2)

    def count_rows(true_codes, pred_codes, space):
        return true_codes.shape[1] * np.ones(true_codes.shape[0])

    with pytest.raises(TypeError, match="CountStatistic"):
        bootstrap_ci(y_true, y_pred, statistic=count_rows, seed=1, n_resamples=10, groups=groups)


def test_the_exact_bound_counts_source_groups_as_trials():
    y_true = ["legit"] * 40
    y_pred = ["legit"] * 40
    hard = [True] * 40
    by_row = hard_negative_fpr_ci(y_true, y_pred, hard, seed=1, n_resamples=200)
    by_group = hard_negative_fpr_ci(
        y_true, y_pred, hard, seed=1, n_resamples=200, groups=[f"page-{i // 5}" for i in range(40)]
    )
    # Forty clean notices from eight pages are eight observations.
    assert by_row.hi == pytest.approx(1 - 0.05 ** (1 / 40))
    assert by_group.hi == pytest.approx(1 - 0.05 ** (1 / 8))
    assert (by_group.method, by_group.n_groups, by_group.n) == ("exact_binomial", 8, 40)


def test_hard_negative_groups_are_counted_among_the_hard_negatives_only():
    y_true = ["legit"] * 6 + ["scam"] * 4
    y_pred = ["scam", "legit", "scam", "legit", "legit", "legit"] + ["scam"] * 4
    hard = [True] * 6 + [False] * 4
    groups = ["a", "a", "b", "b", "c", "c", "a", "z", "z", "z"]
    result = hard_negative_fpr_ci(y_true, y_pred, hard, seed=1, n_resamples=500, groups=groups)
    assert result.point == pytest.approx(2 / 6)
    assert (result.n, result.n_groups, result.method) == (6, 3, "bootstrap")


def test_macro_f1_over_listed_labels_averages_those_and_still_counts_every_error():
    # A is the only listed class. Row 3 (gold: none) filed under A lowers A's
    # precision; row 2 (gold B) filed under A does too, and B is not averaged.
    #   A: tp 1, gold 2, predicted 3 -> 2*1/(2+3) = 0.4
    y_true = ["A", "A", "B", "none", "none"]
    y_pred = ["A", "none", "A", "A", "none"]
    only_a = bootstrap_ci(
        y_true, y_pred, statistic=macro_f1_statistic(["A"]), seed=1, n_resamples=200
    )
    assert only_a.point == pytest.approx(0.4)
    #   B: tp 0, gold 1, predicted 0 -> 0.0; the mean of A and B is 0.2
    both = bootstrap_ci(
        y_true, y_pred, statistic=macro_f1_statistic(["A", "B"]), seed=1, n_resamples=200
    )
    assert both.point == pytest.approx(0.2)
    # A listed label nobody used is undefined and skipped, not scored zero.
    absent = bootstrap_ci(
        y_true, y_pred, statistic=macro_f1_statistic(["A", "Z"]), seed=1, n_resamples=200
    )
    assert absent.point == pytest.approx(0.4)


def test_bootstrap_rejects_an_impossible_alpha():
    y_true, y_pred = synthetic_run(n=50)
    with pytest.raises(ValueError, match="alpha"):
        bootstrap_ci(y_true, y_pred, seed=1, n_resamples=10, alpha=1.0)


# ---------------------------------------------------------------------------
# The reporting rule
# ---------------------------------------------------------------------------


def test_overlaps_detects_the_three_arrangements():
    assert overlaps((0.10, 0.20), (0.15, 0.30))  # genuine overlap
    assert not overlaps((0.10, 0.20), (0.25, 0.30))  # disjoint
    assert not overlaps((0.25, 0.30), (0.10, 0.20))  # disjoint, other order


def test_touching_intervals_count_as_overlapping():
    # Conservative on purpose: the cost of the error is a claim in a report
    # that the numbers do not support.
    assert overlaps((0.10, 0.20), (0.20, 0.30))


def test_overlaps_accepts_estimates_as_well_as_pairs():
    a = estimate(0.78, 0.72, 0.83)
    b = estimate(0.68, 0.64, 0.71)
    assert not overlaps(a, b)
    assert overlaps(a, (0.80, 0.90))


def test_overlaps_rejects_an_inverted_interval():
    with pytest.raises(ValueError, match="inverted"):
        overlaps((0.5, 0.4), (0.1, 0.2))


def test_beats_refuses_to_make_a_claim_when_the_intervals_overlap():
    hybrid = estimate(0.781, 0.724, 0.833)
    zeroshot = estimate(0.770, 0.710, 0.820)
    with pytest.raises(OverlappingIntervals, match="no claim is made"):
        beats("hybrid", hybrid, "llm_zeroshot", zeroshot)


def test_beats_produces_a_sentence_when_the_intervals_are_disjoint():
    hybrid = estimate(0.781, 0.724, 0.833)
    zeroshot = estimate(0.640, 0.590, 0.700)
    sentence = beats("hybrid", hybrid, "llm_zeroshot", zeroshot)
    assert sentence.startswith("hybrid beats llm_zeroshot on macro-F1")
    assert "0.781 [0.724, 0.833]" in sentence


def test_beats_names_the_higher_system_whichever_way_round_it_is_passed():
    strong = estimate(0.781, 0.724, 0.833)
    weak = estimate(0.640, 0.590, 0.700)
    assert beats("weak", weak, "strong", strong).startswith("strong beats weak")


def test_compare_never_raises_and_names_no_winner_when_intervals_overlap():
    a = estimate(0.781, 0.724, 0.833)
    b = estimate(0.770, 0.710, 0.820)
    result = compare("hybrid", a, "rules_only", b)
    assert result.separated is False
    assert result.winner is None
    assert "not separated" in result.sentence
    assert "beats" not in result.sentence


def test_compare_names_the_winner_when_intervals_are_disjoint():
    a = estimate(0.781, 0.724, 0.833)
    b = estimate(0.640, 0.590, 0.700)
    result = compare("hybrid", a, "rules_only", b, metric="hard-negative FPR")
    assert result.separated is True
    assert result.winner == "hybrid"
    assert "hard-negative FPR" in result.sentence


# ---------------------------------------------------------------------------
# results.json
# ---------------------------------------------------------------------------


def sample_results() -> Results:
    return Results(
        run_id="2026-09-26T14:02Z",
        dataset_version="kazscam-v0.1",
        n_bootstrap=10_000,
        rows=[
            ResultRow(
                system="hybrid",
                model="deepseek-v3",
                split="test_press",
                lang="kk",
                ablation="none",
                macro_f1=0.781,
                ci95=(0.724, 0.833),
                n=148,
                fpr_hard_negative=0.061,
                abstain_rate=0.093,
            )
        ],
    )


def test_results_round_trip_through_the_file(tmp_path):
    path = tmp_path / "results.json"
    original = sample_results()
    write_results(path, original)
    assert read_results(path) == original


def test_the_written_file_matches_the_contract_example(tmp_path):
    path = tmp_path / "results.json"
    write_results(path, sample_results())
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "2026-09-26T14:02Z"
    assert payload["n_bootstrap"] == 10_000
    assert payload["rows"][0]["ci95"] == [0.724, 0.833]
    assert payload["rows"][0]["macro_f1"] == 0.781


def test_writing_twice_produces_an_identical_file(tmp_path):
    # The file is committed, so a rerun that changed nothing must show no diff.
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    write_results(first, sample_results())
    write_results(second, sample_results())
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().endswith(b"\n")


def test_float_noise_is_rounded_out_of_the_committed_file(tmp_path):
    path = tmp_path / "results.json"
    results = sample_results()
    results.rows[0].macro_f1 = 0.1 + 0.2  # 0.30000000000000004
    write_results(path, results)
    assert '"macro_f1": 0.3' in path.read_text(encoding="utf-8")


def test_a_row_is_built_from_an_estimate_without_hand_placing_the_interval():
    result = Estimate(point=0.781, lo=0.724, hi=0.833, n=148, n_resamples=10_000, seed=7)
    row = ResultRow.from_estimate(
        result,
        system="hybrid",
        model="deepseek-v3",
        split="test_press",
        lang="kk",
        fpr_hard_negative=0.061,
    )
    assert row.ci95 == (0.724, 0.833)
    assert row.macro_f1 == pytest.approx(0.781)
    assert row.n == 148
    assert row.ablation == "none"


def test_an_undefined_metric_never_reaches_the_published_record(tmp_path):
    results = sample_results()
    results.rows[0].fpr_hard_negative = math.nan
    with pytest.raises(ValueError):
        write_results(tmp_path / "results.json", results)


def test_a_missing_optional_metric_is_omitted_rather_than_written_as_null(tmp_path):
    path = tmp_path / "results.json"
    results = sample_results()
    results.rows[0].abstain_rate = None
    write_results(path, results)
    assert "abstain_rate" not in path.read_text(encoding="utf-8")


def test_an_unknown_system_is_rejected():
    with pytest.raises(ValueError):
        ResultRow(
            system="hybrid_v2",
            model="deepseek-v3",
            split="test_press",
            lang="kk",
            ablation="none",
            macro_f1=0.5,
            ci95=(0.4, 0.6),
            n=10,
        )


def test_an_unknown_ablation_is_rejected():
    with pytest.raises(ValueError):
        ResultRow(
            system="hybrid",
            model="deepseek-v3",
            split="test_press",
            lang="kk",
            ablation="cue_masked_v2",
            macro_f1=0.5,
            ci95=(0.4, 0.6),
            n=10,
        )


def test_an_unknown_language_is_rejected():
    with pytest.raises(ValueError, match="lang must be one of"):
        ResultRow(
            system="hybrid",
            model="deepseek-v3",
            split="test_press",
            lang="kz",  # the language code is kk; kz is the country
            ablation="none",
            macro_f1=0.5,
            ci95=(0.4, 0.6),
            n=10,
        )


def test_an_inverted_interval_is_rejected():
    with pytest.raises(ValueError, match="lo <= hi"):
        ResultRow(
            system="hybrid",
            model="deepseek-v3",
            split="test_press",
            lang="kk",
            ablation="none",
            macro_f1=0.5,
            ci95=(0.6, 0.4),
            n=10,
        )


def test_two_rows_cannot_claim_the_same_cell_of_the_matrix():
    results = sample_results()
    with pytest.raises(ValueError, match="duplicate result cell"):
        Results(
            run_id=results.run_id,
            dataset_version=results.dataset_version,
            n_bootstrap=results.n_bootstrap,
            rows=[results.rows[0], results.rows[0].model_copy()],
        )


def test_unknown_keys_survive_a_round_trip(tmp_path):
    # T501 owns the harness and may record more than the contract lists; this
    # reader is not the place that silently drops it.
    path = tmp_path / "results.json"
    path.write_text(
        json.dumps(
            {
                "run_id": "2026-09-26T14:02Z",
                "dataset_version": "kazscam-v0.1",
                "n_bootstrap": 10_000,
                "prompt_hash": "sha256:abc",
                "rows": [
                    {
                        "system": "hybrid",
                        "model": "deepseek-v3",
                        "split": "test_press",
                        "lang": "kk",
                        "ablation": "none",
                        "macro_f1": 0.781,
                        "ci95": [0.724, 0.833],
                        "n": 148,
                        "seed": 20260926,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    results = read_results(path)
    assert results.prompt_hash == "sha256:abc"
    out = tmp_path / "out.json"
    write_results(out, results)
    assert json.loads(out.read_text(encoding="utf-8"))["rows"][0]["seed"] == 20260926


def test_select_finds_the_cell_the_leaderboard_asks_for():
    results = sample_results()
    results.rows.append(
        results.rows[0].model_copy(update={"system": "rules_only", "macro_f1": 0.61})
    )
    hybrid = results.select(system="hybrid", split="test_press", ablation="none")
    assert len(hybrid) == 1
    assert hybrid[0].macro_f1 == pytest.approx(0.781)
    assert results.select(system="llm_zeroshot") == []


def test_select_rejects_a_field_that_does_not_exist():
    with pytest.raises(ValueError, match="unknown row fields"):
        sample_results().select(sistem="hybrid")


def test_the_reporting_rule_composes_with_the_results_file():
    # The end-to-end shape T506 depends on: two cells out of the file, one
    # comparison, and a sentence that is safe to paste into leaderboard.md.
    results = sample_results()
    results.rows.append(
        results.rows[0].model_copy(
            update={"system": "rules_only", "macro_f1": 0.610, "ci95": (0.550, 0.670)}
        )
    )
    hybrid = results.select(system="hybrid")[0]
    rules = results.select(system="rules_only")[0]
    assert not overlaps(hybrid.ci, rules.ci)
