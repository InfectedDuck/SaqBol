"""The threshold fit, its selection rule and the artifact it leaves.

The synthetic tests build rule scores by hand, so each one isolates one clause
of the rule: a constraint, the tie-break, or the incumbent rule. The last
section runs the fit on the repository's own files and holds the committed
artifact, the pipeline defaults and a fresh fit to the same answer.
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import numpy as np
import pytest

from saqbol.core.fuse import DEFAULT_THRESHOLDS, Thresholds
from saqbol.eval import metrics
from saqbol.eval.__main__ import main
from saqbol.eval.calibrate import (
    CEILING_POINTS,
    DEFAULT_OUT,
    CalibrationError,
    Objective,
    Scored,
    ScoredGuard,
    calibrate,
    candidate_grid,
    choose_split,
    compare_paired,
    evaluate,
    fit,
    load_guard,
    macro_f1_from_counts,
    read_artifact,
    upper_bound,
)
from saqbol.eval.config import EvalConfig, load_config

ROOT = Path(__file__).resolve().parent.parent
DEV_CONFIG = ROOT / "eval" / "configs" / "dev.yaml"
ARTIFACT = ROOT / DEFAULT_OUT
SEED = 20260908
SAFE = frozenset({"likely_safe"})
FLAGGED = frozenset({"suspicious", "scam"})


def scam(i: int, risk: float, group: str | None = None) -> Scored:
    return Scored(f"s-{i}", "scam", risk, group=group)


def legit(i: int, risk: float = 0.0, group: str | None = None) -> Scored:
    return Scored(f"l-{i}", "legit", risk, hard_negative=True, group=group)


def at(suspicious: float) -> Thresholds:
    return dataclasses.replace(DEFAULT_THRESHOLDS, suspicious=suspicious)


def negatives(n: int = 20) -> list[Scored]:
    return [legit(i) for i in range(n)]


# ---------------------------------------------------------------------------
# The grid and the bound
# ---------------------------------------------------------------------------


def test_the_grid_has_one_candidate_per_point_up_to_one_critical_indicator():
    grid = candidate_grid()
    assert [round(t.suspicious * 100) for t in grid] == list(range(1, CEILING_POINTS + 1))
    assert grid[-1].suspicious == 0.40
    assert {t.scam for t in grid} == {DEFAULT_THRESHOLDS.scam}


def test_a_candidate_never_reaches_the_scam_threshold():
    grid = candidate_grid(Thresholds(scam=0.30, suspicious=0.20))
    assert max(t.suspicious for t in grid) == 0.29


def test_the_upper_bound_is_the_closed_form_when_nothing_happened():
    assert upper_bound(0, 17) == pytest.approx(1 - 0.05 ** (1 / 17))
    assert upper_bound(0, 17) == pytest.approx(metrics.exact_binomial_bound(0, 17)[1])
    assert upper_bound(17, 17) == 1.0


def test_the_upper_bound_grows_with_the_count():
    bounds = [upper_bound(k, 30) for k in range(5)]
    assert bounds == sorted(bounds)
    assert bounds[1] == pytest.approx(0.1486, abs=1e-3)  # 1 of 30, one-sided 95%


def test_macro_f1_from_counts_is_the_harness_statistic():
    y_true = ["scam"] * 7 + ["legit"] * 5
    y_pred = ["scam"] * 4 + ["legit"] * 3 + ["legit"] * 4 + ["scam"]
    counts = np.array([4, 1, 3, 4])  # tn, fp, fn, tp
    expected = metrics.macro_f1(y_true, y_pred, labels=("legit", "scam"))
    assert float(macro_f1_from_counts(counts)) == pytest.approx(expected)


def test_a_class_absent_from_both_sides_is_skipped_not_zero():
    assert float(macro_f1_from_counts(np.array([0, 0, 0, 5]))) == 1.0
    assert np.isnan(macro_f1_from_counts(np.array([0, 0, 0, 0])))


# ---------------------------------------------------------------------------
# Admissibility
# ---------------------------------------------------------------------------


def test_a_candidate_is_scored_like_a_harness_cell():
    rows = [scam(1, 0.50), scam(2, 0.20), legit(1), Scored("a-1", "ambiguous", 0.90)]
    candidate = evaluate(at(0.40), rows, [])
    assert candidate.labels == ("scam", "legit", "legit", "scam")
    assert candidate.n_scam_flagged == 1
    assert candidate.n_false_positive == 0
    assert candidate.coverage == 1.0
    # The ambiguous row is outside the F1, whatever the system said about it.
    assert candidate.macro_f1 == pytest.approx(
        metrics.macro_f1(["scam", "scam", "legit"], ["scam", "legit", "legit"])
    )
    assert candidate.admissible


def test_too_many_flagged_hard_negatives_rule_a_candidate_out():
    rows = [scam(1, 0.60), *negatives(9), legit(99, 0.30)]
    assert evaluate(at(0.40), rows, []).admissible
    loose = evaluate(at(0.30), rows, [])
    assert loose.n_false_positive == 1
    assert not loose.admissible
    assert "1 of 10 hard negatives flagged" in loose.rejected[0]


def test_the_false_positive_cap_is_a_share_and_a_candidate_at_the_cap_passes():
    rows = [scam(1, 0.60), *negatives(9), legit(99, 0.30)]
    assert evaluate(at(0.30), rows, [], objective=Objective(max_fpr_hard_negative=0.05)).rejected
    assert not evaluate(
        at(0.30), rows, [], objective=Objective(max_fpr_hard_negative=0.10)
    ).rejected


def test_data_with_no_hard_negative_cannot_admit_anything():
    candidate = evaluate(at(0.40), [scam(1, 0.60), Scored("l-1", "legit", 0.0)], [])
    assert not candidate.admissible
    assert "no hard negative" in candidate.rejected[0]


def test_a_guard_case_outside_its_band_rules_a_candidate_out():
    rows = [scam(1, 0.60), *negatives()]
    guard = [
        ScoredGuard("genuine_code_sms", 0.25, SAFE),
        ScoredGuard("tolerant_case", 0.25, SAFE | {"suspicious"}),
        ScoredGuard("bare_code_request", 0.40, FLAGGED),
    ]
    assert evaluate(at(0.26), rows, guard).admissible
    low = evaluate(at(0.25), rows, guard)
    assert low.guard_failures == ("genuine_code_sms",)
    assert not low.admissible
    assert "guard: 1 regression case would" in low.rejected[0]


def test_low_coverage_rules_a_candidate_out():
    rows = [scam(1, 0.60), *negatives()]
    candidate = evaluate(at(0.40), rows, [], objective=Objective(min_coverage=1.01))
    assert not candidate.admissible
    assert "coverage 1.000 is under the floor" in candidate.rejected[0]


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def spread_rows(n_groups: int) -> list[Scored]:
    """Scams at 0.30, one per source group, plus scams the incumbent already flags."""
    rows = [scam(i, 0.30, group=f"g-{i}") for i in range(n_groups)]
    rows += [scam(100 + i, 0.60, group=f"h-{i}") for i in range(10)]
    rows += [legit(i, group=f"n-{i}") for i in range(20)]
    return rows


def test_a_gain_spread_over_many_sources_moves_the_threshold():
    outcome = fit(spread_rows(12), [], seed=SEED, n_bootstrap=2000)
    assert outcome.best.suspicious == 0.30
    assert outcome.comparison is not None and outcome.comparison.decisive
    assert outcome.selected.suspicious == 0.30
    assert "replaces the incumbent" in outcome.reason


def test_a_gain_from_one_source_does_not():
    rows = [scam(i, 0.30, group="one-article") for i in range(12)]
    rows += [scam(100 + i, 0.60, group=f"h-{i}") for i in range(10)]
    rows += [legit(i, group=f"n-{i}") for i in range(20)]
    outcome = fit(rows, [], seed=SEED, n_bootstrap=2000)
    assert outcome.best.suspicious == 0.30
    assert outcome.comparison is not None
    assert outcome.comparison.delta > 0
    assert outcome.comparison.lo == 0.0
    assert outcome.selected.thresholds == DEFAULT_THRESHOLDS
    assert "the incumbent stays" in outcome.reason


def test_a_row_with_no_group_counts_as_its_own_source():
    rows = [dataclasses.replace(r, group=None) for r in spread_rows(12)]
    outcome = fit(rows, [], seed=SEED, n_bootstrap=2000)
    assert outcome.comparison is not None
    assert outcome.comparison.n_groups == len(rows)
    assert outcome.selected.suspicious == 0.30


def test_ties_go_to_the_threshold_that_warns_less():
    """Between two attainable scores every threshold scores the same."""
    outcome = fit(spread_rows(12), [], seed=SEED, n_bootstrap=500)
    same = [c for c in outcome.candidates if c.macro_f1 == outcome.best.macro_f1]
    assert len(same) > 1
    assert outcome.best.suspicious == max(c.suspicious for c in same)


def test_the_incumbent_stays_when_nothing_beats_it():
    rows = [scam(i, 0.60, group=f"h-{i}") for i in range(10)] + negatives()
    outcome = fit(rows, [], seed=SEED, n_bootstrap=500)
    assert outcome.comparison is None
    assert outcome.selected.thresholds == DEFAULT_THRESHOLDS
    assert "best admissible candidate, so it stays" in outcome.reason


def test_an_inadmissible_incumbent_is_replaced_without_a_comparison():
    rows = [scam(i, 0.60, group=f"h-{i}") for i in range(10)] + negatives()
    guard = [ScoredGuard("must_stay_safe", 0.35, SAFE)]
    incumbent = Thresholds(suspicious=0.30)
    outcome = fit(rows, guard, seed=SEED, n_bootstrap=500, incumbent=incumbent)
    assert not outcome.incumbent.admissible
    assert outcome.comparison is None
    assert outcome.selected.suspicious == 0.40
    assert "not admissible" in outcome.reason


def test_no_admissible_candidate_is_an_error_not_a_guess():
    rows = [scam(1, 0.60), *negatives()]
    guard = [ScoredGuard("contradiction", 0.40, SAFE), ScoredGuard("other", 0.01, FLAGGED)]
    with pytest.raises(CalibrationError, match="no admissible candidate"):
        fit(rows, guard, seed=SEED, n_bootstrap=500)


def test_the_paired_interval_is_seeded():
    rows = spread_rows(6)
    low = evaluate(at(0.30), rows, []).labels
    high = evaluate(at(0.40), rows, []).labels
    first = compare_paired(rows, low, high, seed=SEED, n_resamples=1000)
    again = compare_paired(rows, low, high, seed=SEED, n_resamples=1000)
    assert first == again
    assert first.lo <= first.delta <= first.hi


# ---------------------------------------------------------------------------
# What the fit may read
# ---------------------------------------------------------------------------


def config_with(tmp_path: Path, **splits: str) -> EvalConfig:
    paths = {}
    for name, content in splits.items():
        path = tmp_path / f"{name}.jsonl"
        path.write_text(content, encoding="utf-8")
        paths[name] = str(path)
    return EvalConfig(name="t", systems=["rules_only"], splits=paths)


ROW = '{"id": "r-1", "text": "x", "label": "legit", "lang": "ru"}\n'


def test_a_test_split_is_refused_by_name(tmp_path):
    config = config_with(tmp_path, test_press=ROW, dev=ROW)
    with pytest.raises(CalibrationError, match="never on 'test_press'"):
        choose_split(config, "test_press")


def test_a_config_with_only_test_splits_has_nothing_to_fit_on(tmp_path):
    config = config_with(tmp_path, test_press=ROW, test_donated=ROW)
    with pytest.raises(CalibrationError, match="never fitted on a test split"):
        choose_split(config)


def test_a_fresh_calibration_slice_is_preferred_and_an_empty_one_is_not(tmp_path):
    assert choose_split(config_with(tmp_path, calibration=ROW, dev=ROW)) == "calibration"
    assert choose_split(config_with(tmp_path, calibration="", dev=ROW)) == "dev"


def test_the_cli_reports_a_test_split_as_a_usage_error(capsys):
    with pytest.raises(SystemExit):
        main(["calibrate", "--config", str(DEV_CONFIG), "--split", "test_press"])
    assert "invalid choice" in capsys.readouterr().err


def test_known_gaps_are_left_out_of_the_guard_by_name():
    cases, left_out = load_guard(ROOT / "tests" / "fixtures" / "golden")
    assert left_out == ["hard_negatives.yaml::scam_warning_headline_pasted"]
    assert all(case.band_in for case in cases)
    assert len({case.id for case in cases}) == len(cases)


# ---------------------------------------------------------------------------
# The repository's own fit
# ---------------------------------------------------------------------------

#: Parts of the artifact that say when and from which checkout it was made.
VOLATILE = ("created_at", "code")


@pytest.fixture(scope="module")
def fresh() -> dict:
    """The fit, made now, from the repository root's files."""
    before = Path.cwd()
    os.chdir(ROOT)
    try:
        return calibrate(
            load_config(DEV_CONFIG),
            guard_dir=Path("tests") / "fixtures" / "golden",
            config_path=Path("eval") / "configs" / "dev.yaml",
        )
    finally:
        os.chdir(before)


def test_the_fit_reads_dev_and_says_so(fresh):
    assert fresh["regime"] == "dev-calibrated"
    assert fresh["data"]["split"] == "dev"
    assert fresh["system"] == "rules_only"
    assert fresh["model"] == "none"
    assert fresh["confirmation"]["pipeline_agrees_with_search"] is True


def test_a_lone_high_severity_cue_cannot_be_flagged(fresh):
    """A genuine eGov code message carries one, and the suite keeps it safe."""
    by_threshold = {round(c["suspicious"] * 100): c for c in fresh["candidates"]}
    assert "hard_negatives.yaml::egov_1414_code_sms" in by_threshold[25]["guard_failures"]
    assert not by_threshold[25]["admissible"]
    assert by_threshold[26]["admissible"]


def test_the_committed_artifact_is_what_the_fit_produces_today(fresh):
    """Fails when the rules, the dev split or the suite moved and the fit was not redone.

    Redo it with `python -m saqbol.eval calibrate --config eval/configs/dev.yaml`.
    """
    committed = read_artifact(ARTIFACT)
    for key in VOLATILE:
        committed.pop(key)
    # Through JSON, so tuples and lists compare as the file stores them.
    expected = json.loads(json.dumps({k: v for k, v in fresh.items() if k not in VOLATILE}))
    # The interval is a percentile of a resampled statistic; allow for the last digit.
    was, now = committed.pop("comparison"), expected.pop("comparison")
    for key in ("delta_macro_f1", "ci95"):
        assert was.pop(key) == pytest.approx(now.pop(key), abs=1e-5)
    assert was == now
    assert committed == expected


def test_the_pipeline_runs_with_the_selected_thresholds():
    selected = read_artifact(ARTIFACT)["selected"]["thresholds"]
    assert selected == {
        "suspicious": DEFAULT_THRESHOLDS.suspicious,
        "scam": DEFAULT_THRESHOLDS.scam,
    }


def test_the_cli_writes_the_artifact(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    out = tmp_path / "fit.json"
    assert main(["calibrate", "--config", "eval/configs/dev.yaml", "--out", str(out)]) == 0
    written = read_artifact(out)
    assert written["selected"]["thresholds"]["suspicious"] == DEFAULT_THRESHOLDS.suspicious
    printed = capsys.readouterr().out
    assert "dev-calibrated" in printed
    assert "selected: suspicious" in printed


def test_a_file_of_another_shape_is_not_read_as_an_artifact(tmp_path):
    other = tmp_path / "other.json"
    other.write_text('{"schema": "something-else/1"}', encoding="utf-8")
    with pytest.raises(CalibrationError, match="is not a saqbol-calibration/1 file"):
        read_artifact(other)
