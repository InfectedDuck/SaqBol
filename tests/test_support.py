"""Minimum support: the floors and the release tier, at their edges.

The figures are section 7 of docs/15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md.
Each test sits on one side of one floor, because a floor that is off by one
row publishes a number the policy withholds.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from saqbol.eval.support import (
    DEFAULT_FLOORS,
    Floors,
    count_support,
    f1_gap,
    fpr_gap,
    release_tier,
    slice_gap,
)


def row(i: int, label: str = "scam", lang: str = "ru", *, hard=False, group: str | None = "g"):
    return SimpleNamespace(
        id=f"r-{i}", label=label, lang=lang, hard_negative=hard, source_group=group
    )


def facts(n_rows: int, legit: int, *, hard: int = 0, ru: int | None = None, kk: int = 0) -> dict:
    return {
        "n_rows": n_rows,
        "by_label": {"legit": legit, "scam": n_rows - legit},
        "by_lang": {"ru": n_rows - kk if ru is None else ru, "kk": kk},
        "n_hard_negative": hard,
    }


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def test_the_policy_figures_are_the_defaults():
    assert (
        Floors(
            slice_rows=30,
            class_rows=10,
            hard_negatives=30,
            pilot_rows=60,
            pilot_legit=20,
            benchmark_rows=200,
            benchmark_legit=60,
            benchmark_hard_negatives=40,
            benchmark_lang_rows=60,
            benchmark_langs=("ru", "kk"),
        )
        == DEFAULT_FLOORS
    )


def test_support_counts_rows_classes_languages_hard_negatives_and_groups():
    rows = [
        row(1, group="a"),
        row(2, group="a"),
        row(3, lang="kk", group="b"),
        row(4, "legit", hard=True, group="c"),
        row(5, "ambiguous", lang="kk", group="c"),
    ]
    assert count_support(rows) == {
        "n_rows": 5,
        "by_label": {"ambiguous": 1, "legit": 1, "scam": 3},
        "by_lang": {"kk": 2, "ru": 3},
        "n_hard_negative": 1,
        "n_source_groups": 3,
    }


def test_groups_are_not_counted_when_any_row_names_none():
    """Counting an unnamed row as independent would claim what nobody checked."""
    assert "n_source_groups" not in count_support([row(1, group="a"), row(2, group=None)])
    assert "n_source_groups" not in count_support([])


# ---------------------------------------------------------------------------
# Slice floors
# ---------------------------------------------------------------------------


def test_a_slice_needs_thirty_rows():
    assert slice_gap(29) == "29 rows"
    assert slice_gap(30) is None
    assert slice_gap(None) == "row count not recorded"


def test_macro_f1_needs_ten_rows_of_each_class():
    assert f1_gap({"scam": 40, "legit": 10}) is None
    assert f1_gap({"scam": 40, "legit": 9}) == "9 legit"
    assert f1_gap({"scam": 3, "legit": 9}) == "3 scam, 9 legit"
    # A class with no rows at all is the thinnest class there is.
    assert f1_gap({"scam": 40}) == "0 legit"
    assert f1_gap(None) == "class counts not recorded"


def test_the_false_positive_rate_needs_thirty_hard_negatives():
    assert fpr_gap(17) == "17 hard negatives"
    assert fpr_gap(1) == "1 hard negative"
    assert fpr_gap(30) is None
    assert fpr_gap(None) == "hard-negative count not recorded"


def test_a_true_is_not_a_count():
    assert slice_gap(True) == "row count not recorded"


# ---------------------------------------------------------------------------
# Release tier
# ---------------------------------------------------------------------------


def test_a_run_with_no_press_split_has_no_tier():
    release = release_tier(None)
    assert release.tier == "none"
    assert "read no `test_press` rows" in release.reason


@pytest.mark.parametrize(
    ("n_rows", "legit", "tier"),
    [
        (0, 0, "none"),
        (59, 30, "none"),
        (60, 19, "none"),
        (60, 20, "pilot"),
        (199, 80, "pilot"),
    ],
)
def test_a_pilot_needs_sixty_rows_and_twenty_legitimate(n_rows, legit, tier):
    assert release_tier(facts(n_rows, legit)).tier == tier


def test_the_reason_names_what_is_short():
    release = release_tier(facts(46, 10))
    assert release.tier == "none"
    assert "46 rows (needs 60)" in release.reason
    assert "10 legitimate rows (needs 20)" in release.reason
    assert "No test number is published" in release.reason


@pytest.mark.parametrize(
    ("kwargs", "short"),
    [
        ({"n_rows": 199, "legit": 60, "hard": 40, "ru": 100, "kk": 99}, "199 rows (needs 200)"),
        ({"n_rows": 200, "legit": 59, "hard": 40, "ru": 100, "kk": 100}, "59 legitimate rows"),
        ({"n_rows": 200, "legit": 60, "hard": 39, "ru": 100, "kk": 100}, "39 hard negatives"),
        ({"n_rows": 200, "legit": 60, "hard": 40, "ru": 141, "kk": 59}, "59 `kk` rows"),
        ({"n_rows": 200, "legit": 60, "hard": 40, "ru": 59, "kk": 141}, "59 `ru` rows"),
    ],
)
def test_a_benchmark_needs_every_one_of_its_floors(kwargs, short):
    release = release_tier(facts(**kwargs))
    assert release.tier == "pilot"
    assert short in release.reason


def test_a_split_that_meets_every_floor_is_a_benchmark():
    release = release_tier(facts(200, 60, hard=40, ru=100, kk=100))
    assert release.tier == "benchmark"


def test_a_partial_run_has_no_tier_however_large_the_split():
    release = release_tier(facts(200, 60, hard=40, ru=100, kk=100), limit=20)
    assert release.tier == "none"
    assert "--limit 20" in release.reason


def test_facts_with_no_counts_are_under_every_floor():
    assert release_tier({}).tier == "none"
