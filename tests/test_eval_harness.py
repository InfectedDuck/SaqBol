"""T501 — the evaluation harness, end to end and offline.

Every test here runs without a provider key and without a network. The smoke
matrix is the offline baseline over the twelve-row fixture split; the cells
that need a model are proven to skip with a recorded reason, never to fail.
The one metric test computes every number by hand in a comment, in the same
spirit as `test_metrics.py`: the harness assembles numbers from `metrics.py`,
and the assembly is what has to be checked.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from saqbol.core.types import LLMJudgement, Stage
from saqbol.eval.__main__ import main
from saqbol.eval.config import EvalConfig, config_hash, load_config
from saqbol.eval.leaderboard import (
    NOT_REPORTED,
    WITHHELD_NOTE,
    render_leaderboard,
    run_release,
    write_leaderboard,
)
from saqbol.eval.results import ResultRow, Results, read_results
from saqbol.eval.run import CellSkipped, DatasetRow, load_split, run, score_cell
from saqbol.eval.support import Floors
from saqbol.eval.systems import Prediction, ZeroShotJudgement

REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE_CONFIG = REPO_ROOT / "eval" / "configs" / "smoke.yaml"
FULL_CONFIG = REPO_ROOT / "eval" / "configs" / "v0.1.yaml"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "eval" / "smoke.jsonl"

#: Contract section 7: the keys every results row carries.
CONTRACT_ROW_KEYS = {
    "system",
    "model",
    "split",
    "lang",
    "ablation",
    "macro_f1",
    "ci95",
    "n",
    "fpr_hard_negative",
    "abstain_rate",
}

#: No key, no network: every run in this file looks providers up in here.
NO_KEYS: dict[str, str] = {}

#: The twelve-row fixture is under every real floor. Tests of how a number is
#: laid out use floors of one row, which make the fixture a pilot; the tests
#: of the floors themselves use the defaults.
TINY_FLOORS = Floors(slice_rows=1, class_rows=1, hard_negatives=1, pilot_rows=1, pilot_legit=1)


@pytest.fixture(autouse=True)
def _repo_root(monkeypatch):
    """Split paths in the configs are relative to the repository root."""
    monkeypatch.chdir(REPO_ROOT)


def smoke_config(**overrides) -> EvalConfig:
    base = load_config(SMOKE_CONFIG).model_dump()
    base.update(overrides)
    return EvalConfig.model_validate(base)


# ---------------------------------------------------------------------------
# The fixture split
# ---------------------------------------------------------------------------


def test_the_fixture_split_covers_what_the_harness_needs():
    rows = load_split(FIXTURE)
    assert len(rows) == 12
    assert {r.lang for r in rows} == {"ru", "kk"}
    playbooks = {r.playbook_id for r in rows if r.label == "scam"}
    assert len(playbooks) >= 3
    assert sum(1 for r in rows if r.hard_negative) == 3
    assert all(r.label == "legit" for r in rows if r.hard_negative)
    assert any(r.label == "ambiguous" for r in rows)
    assert any(r.stage for r in rows)


def test_a_hard_negative_labelled_scam_is_a_dataset_error(tmp_path):
    split = tmp_path / "bad.jsonl"
    row = {"id": "x-1", "text": "…", "label": "scam", "lang": "ru", "hard_negative": True}
    split.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad\.jsonl:1"):
        load_split(split)


# ---------------------------------------------------------------------------
# The smoke run
# ---------------------------------------------------------------------------


def test_the_smoke_config_runs_offline_and_writes_the_contract_shape(tmp_path):
    outcome = run(load_config(SMOKE_CONFIG), out_dir=tmp_path, env=NO_KEYS, run_id="smoke")

    assert outcome.results_path == tmp_path / "smoke" / "results.json"
    payload = json.loads(outcome.results_path.read_text(encoding="utf-8"))
    assert {"run_id", "dataset_version", "n_bootstrap", "rows"} <= set(payload)
    assert payload["n_bootstrap"] == 10_000
    assert len(payload["rows"]) == 3  # rules_only x test_press x {all, ru, kk} x none
    for row in payload["rows"]:
        assert set(row) >= CONTRACT_ROW_KEYS
        assert row["system"] == "rules_only"
        assert row["model"] == "none"
        lo, hi = row["ci95"]
        assert 0.0 <= lo <= row["macro_f1"] <= hi <= 1.0
        assert row["seed"] == 20260908
    assert not outcome.skipped
    # The file is the record: it reads back through the contract reader, with
    # the floats rounded the way results.py writes them.
    read_back = read_results(outcome.results_path)
    assert [(r.system, r.lang, r.n) for r in read_back.rows] == [
        (r.system, r.lang, r.n) for r in outcome.results.rows
    ]
    assert [r.macro_f1 for r in read_back.rows] == pytest.approx(
        [r.macro_f1 for r in outcome.results.rows], abs=1e-6
    )


def test_the_manifest_records_provenance_counts_and_skips(tmp_path):
    outcome = run(load_config(SMOKE_CONFIG), out_dir=tmp_path, env=NO_KEYS, run_id="m")
    manifest = json.loads(outcome.manifest_path.read_text(encoding="utf-8"))

    assert manifest["config_hash"] == config_hash(load_config(SMOKE_CONFIG))
    assert manifest["config_hash"].startswith("sha256:")
    assert "git_commit" in manifest and "timestamp" in manifest
    assert manifest["seed"] == 20260908
    # The thresholds the systems ran with, to hold against the calibration artifact.
    assert manifest["fusion"]["thresholds"]["suspicious"] == 0.40
    assert manifest["fusion"]["thresholds"]["scam"] == 0.70
    assert manifest["fusion"]["weights"] == {"rule": 0.55, "llm": 0.45}
    split = manifest["splits"]["test_press"]
    assert split["exists"] is True
    assert split["n_rows"] == 12
    assert split["by_lang"] == {"kk": 5, "ru": 7}
    assert split["by_label"] == {"ambiguous": 1, "legit": 4, "scam": 7}
    assert split["n_hard_negative"] == 3
    # The fixture predates `source_group`, so no group count is claimed for it.
    assert "n_source_groups" not in split
    assert manifest["cells"] == {"planned": 3, "executed": 3, "skipped": 0}
    assert manifest["skipped"] == []
    # Every executed row is traceable: one prediction line per row per cell.
    lines = outcome.predictions_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 12 + 7 + 5


def test_language_filtering_uses_the_rows_lang_field(tmp_path):
    outcome = run(load_config(SMOKE_CONFIG), out_dir=tmp_path, env=NO_KEYS, run_id="lang")
    by_lang = {row.lang: row for row in outcome.results.rows}
    assert by_lang["all"].n_rows == 12
    assert by_lang["ru"].n_rows == 7
    assert by_lang["kk"].n_rows == 5
    # The one ambiguous row is Kazakh and has no place in a scam/legit F1.
    assert by_lang["kk"].n_ambiguous == 1
    assert by_lang["kk"].n == 4


def test_two_runs_give_identical_numbers(tmp_path):
    config = load_config(SMOKE_CONFIG)
    first = run(config, out_dir=tmp_path / "a", env=NO_KEYS, run_id="same")
    second = run(config, out_dir=tmp_path / "b", env=NO_KEYS, run_id="same")
    assert first.results.rows == second.results.rows
    assert first.results_path.read_bytes() == second.results_path.read_bytes()
    assert first.predictions_path.read_bytes() == second.predictions_path.read_bytes()


def test_limit_caps_the_rows_in_every_cell(tmp_path):
    outcome = run(load_config(SMOKE_CONFIG), out_dir=tmp_path, env=NO_KEYS, run_id="lim", limit=4)
    assert {row.n_rows for row in outcome.results.rows} == {4}


# ---------------------------------------------------------------------------
# Cells that cannot run
# ---------------------------------------------------------------------------


def test_a_cell_that_needs_a_provider_key_is_skipped_with_a_reason(tmp_path):
    config = smoke_config(
        systems=["rules_only", "llm_zeroshot", "hybrid"],
        models=["deepseek-chat"],
        languages=["all"],
    )
    outcome = run(config, out_dir=tmp_path, env=NO_KEYS, run_id="keys")

    assert [row.system for row in outcome.results.rows] == ["rules_only"]
    skipped = {(s.cell.system, s.cell.model): s.reason for s in outcome.skipped}
    assert set(skipped) == {("llm_zeroshot", "deepseek-chat"), ("hybrid", "deepseek-chat")}
    for reason in skipped.values():
        assert "DEEPSEEK_API_KEY" in reason
    manifest = json.loads(outcome.manifest_path.read_text(encoding="utf-8"))
    assert manifest["cells"] == {"planned": 3, "executed": 1, "skipped": 2}
    assert {s["reason"] for s in manifest["skipped"]} == set(skipped.values())


def test_a_missing_split_file_is_reported_not_raised(tmp_path):
    # The full matrix, pointed at split files that do not exist.
    base = load_config(FULL_CONFIG).model_dump()
    base["splits"] = {
        split: (tmp_path / "absent" / f"{split}.jsonl").as_posix() for split in base["splits"]
    }
    config = EvalConfig.model_validate(base)
    for path in config.splits.values():
        assert not Path(path).exists()

    outcome = run(config, out_dir=tmp_path, env=NO_KEYS, run_id="missing")

    assert outcome.results.rows == []
    assert len(outcome.skipped) == len(outcome.manifest["skipped"]) > 0
    assert all(s.reason.startswith("split file missing: ") for s in outcome.skipped)
    assert all(not entry["exists"] for entry in outcome.manifest["splits"].values())
    assert outcome.results_path.is_file()


def test_ablations_run_or_skip_for_the_reason_the_split_gives(tmp_path):
    config = smoke_config(
        languages=["all"],
        ablations=["none", "cue_masked", "no_playbook_context", "translated"],
    )
    outcome = run(config, out_dir=tmp_path, env=NO_KEYS, run_id="abl")

    executed = {row.ablation for row in outcome.results.rows}
    assert executed == {"none", "cue_masked"}
    reasons = {s.cell.ablation: s.reason for s in outcome.skipped}
    assert "no retrieval" in reasons["no_playbook_context"]
    assert "no translations" in reasons["translated"]
    # Masking changes the input, so the masked cell scored different text.
    lines = [
        json.loads(line)
        for line in outcome.predictions_path.read_text(encoding="utf-8").splitlines()
    ]
    assert sum(1 for line in lines if line["ablation"] == "cue_masked") == 12


def test_the_translated_ablation_runs_on_the_rows_that_carry_a_translation(tmp_path):
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    for row in rows[:5]:
        row["text_translated"] = row["text"]
    split = tmp_path / "translated.jsonl"
    split.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    config = smoke_config(
        splits={"test_press": str(split)}, languages=["all"], ablations=["translated"]
    )
    outcome = run(config, out_dir=tmp_path, env=NO_KEYS, run_id="tr")
    assert not outcome.skipped
    (row,) = outcome.results.rows
    assert row.ablation == "translated"
    assert row.n_rows == 5


# ---------------------------------------------------------------------------
# Scoring, by hand
# ---------------------------------------------------------------------------


def _row(n: int, label: str, **kwargs) -> DatasetRow:
    return DatasetRow(id=f"r{n}", text=f"text {n}", label=label, lang="ru", **kwargs)


def test_score_cell_matches_hand_computation():
    a, b = "kz.bank_security_call", "kz.delivery_link"
    rows = [
        _row(1, "scam", playbook_id=a, stage="hook"),
        _row(2, "scam", playbook_id=a, stage="pressure"),
        _row(3, "scam", playbook_id=b),
        _row(4, "scam", playbook_id=b, stage="hook"),
        _row(5, "legit", hard_negative=True),
        _row(6, "legit", hard_negative=True),
        _row(7, "legit", hard_negative=True),
        _row(8, "legit"),
        _row(9, "ambiguous"),
    ]
    predictions = [
        Prediction(band="scam", playbook_id=a, stage="hook"),
        Prediction(band="scam", playbook_id=a, stage="contact"),
        Prediction(band="suspicious", playbook_id=b),
        Prediction(band="likely_safe"),
        Prediction(band="scam"),  # a false positive on a hard negative
        Prediction(band="likely_safe"),
        Prediction(band="unsure", error="model call failed"),
        Prediction(band="likely_safe"),
        Prediction(band="suspicious"),
    ]
    score = score_cell(rows, predictions, seed=1, n_bootstrap=200)

    # Binary, over the answered non-ambiguous rows 1-6 and 8 (row 7 abstained,
    # row 9 is ambiguous):
    #   true  scam scam scam scam  legit legit legit
    #   pred  scam scam scam legit scam  legit legit
    #   scam:  tp 3, support_true 4, support_pred 4 -> 6/8 = 0.75
    #   legit: tp 2, support_true 3, support_pred 3 -> 4/6 = 2/3
    assert score.macro_f1.n == 7
    assert score.macro_f1.point == pytest.approx((0.75 + 2 / 3) / 2)
    assert score.extra["per_class_f1"] == pytest.approx({"legit": 2 / 3, "scam": 0.75})
    assert score.extra["selective_risk"] == pytest.approx(2 / 7)
    # One abstention in nine rows.
    assert score.abstain_rate == pytest.approx(1 / 9)
    assert score.extra["coverage"] == pytest.approx(8 / 9)
    assert score.extra["n_rows"] == 9
    assert score.extra["n_answered"] == 8
    assert score.extra["n_ambiguous"] == 1
    # Hard negatives 5, 6, 7: one flagged, one cleared, one abstained -> 1/3,
    # with the abstention kept in the denominator.
    assert score.fpr_hard_negative == pytest.approx(1 / 3)
    assert score.extra["n_hard_negative"] == 3
    # Playbooks over the answered scam rows 1-4: gold A A B B, predicted A A B none.
    #   A: 2*2/(2+2) = 1.0; B: 2*1/(2+1) = 2/3; none: 0/(0+1) = 0 -> mean 5/9
    assert score.extra["playbook_n"] == 4
    assert score.extra["playbook_macro_f1"] == pytest.approx((1.0 + 2 / 3 + 0.0) / 3)
    # Stage: rows 1 and 2 have the right playbook and a gold stage; row 3 has
    # no gold stage, row 4 the wrong playbook. One of the two is right.
    assert score.extra["stage_n_eligible"] == 2
    assert score.extra["stage_n_correct"] == 1
    assert score.extra["stage_accuracy"] == pytest.approx(0.5)
    assert score.extra["n_errors"] == 1


def test_a_system_that_answers_nothing_has_no_macro_f1():
    rows = [_row(1, "scam", playbook_id="kz.fake_store"), _row(2, "legit")]
    predictions = [Prediction(band="unsure"), Prediction(band="unsure")]
    with pytest.raises(CellSkipped, match="answered none of the 2"):
        score_cell(rows, predictions, seed=1, n_bootstrap=10)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_original_is_an_alias_for_the_contract_ablation_none():
    aliased = smoke_config(ablations=["original", "cue_masked"])
    plain = smoke_config(ablations=["none", "cue_masked"])
    assert aliased.ablations == ["none", "cue_masked"]
    assert config_hash(aliased) == config_hash(plain)
    assert config_hash(aliased) != config_hash(smoke_config(seed=1))


def test_a_model_system_without_models_is_rejected_at_load():
    with pytest.raises(ValueError, match="models"):
        smoke_config(systems=["rules_only", "hybrid"], models=[])


# ---------------------------------------------------------------------------
# Leaderboard and CLI
# ---------------------------------------------------------------------------


def test_the_leaderboard_prints_intervals_and_makes_no_ranking_claim(tmp_path):
    config = smoke_config(
        systems=["rules_only", "hybrid"], models=["deepseek-chat"], languages=["all", "kk"]
    )
    outcome = run(config, out_dir=tmp_path, env=NO_KEYS, run_id="lb")
    text = render_leaderboard(
        outcome.results, skipped=outcome.manifest["skipped"], floors=TINY_FLOORS
    )

    assert "beats" not in text
    assert "## test_press" in text
    for row in outcome.results.rows:
        lo, hi = row.ci95
        assert f"{row.macro_f1:.3f} [{lo:.3f}, {hi:.3f}]" in text
    assert "## Cells not run" in text
    assert "DEEPSEEK_API_KEY" in text

    written = write_leaderboard(
        outcome.results_path, tmp_path / "lb" / "leaderboard.md", floors=TINY_FLOORS
    )
    assert written.read_text(encoding="utf-8") == text


def test_the_leaderboard_says_a_dev_table_is_not_a_test_result(tmp_path):
    config = smoke_config(splits={"dev": str(FIXTURE), "test_press": str(FIXTURE)})
    outcome = run(config, out_dir=tmp_path, env=NO_KEYS, run_id="dev")
    text = render_leaderboard(outcome.results)

    dev_section, test_section = text.split("## dev", 1)[1].split("## test_press", 1)
    assert "are not test results" in dev_section
    assert "Development data" in dev_section
    assert "not test results" not in test_section


def test_a_split_with_no_gold_playbooks_gets_no_playbook_score(tmp_path):
    """Unannotated rows name no playbook; agreeing with nothing is not a result."""
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line]
    for row in rows:
        row["playbook_id"] = None
    bare = tmp_path / "bare.jsonl"
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    bare.write_text("\n".join(lines) + "\n", encoding="utf-8")

    outcome = run(
        smoke_config(splits={"dev": str(bare)}), out_dir=tmp_path, env=NO_KEYS, run_id="bare"
    )
    assert outcome.results.rows
    for row in outcome.results.rows:
        assert "playbook_macro_f1" not in (row.model_extra or {})


def test_the_leaderboard_marks_an_exact_bound_and_explains_the_mark(tmp_path):
    outcome = run(smoke_config(), out_dir=tmp_path, env=NO_KEYS, run_id="bound")
    plain = [
        ResultRow(**{**row.model_dump(), "fpr_hard_negative_ci_method": "bootstrap"})
        for row in outcome.results.rows
    ]
    text = render_leaderboard(
        outcome.results.model_copy(update={"rows": plain}), floors=TINY_FLOORS
    )
    assert "exact one-sided" not in text

    first = {
        **plain[0].model_dump(),
        "fpr_hard_negative": 0.0,
        "fpr_hard_negative_ci95": [0.0, 0.162],
        "fpr_hard_negative_ci_method": "exact_binomial",
    }
    marked = outcome.results.model_copy(update={"rows": [ResultRow(**first), *plain[1:]]})
    text = render_leaderboard(marked, floors=TINY_FLOORS)
    assert "0.000 [0.000, 0.162]* |" in text
    assert "exact one-sided 95 percent binomial bound" in text
    # Under the real floors the cell prints no rate, so there is no mark to explain.
    assert "exact one-sided" not in render_leaderboard(marked)


# ---------------------------------------------------------------------------
# Minimum support in the leaderboard
# ---------------------------------------------------------------------------


def result_row(
    *,
    split: str = "dev",
    lang: str = "all",
    system: str = "rules_only",
    model: str = "none",
    macro_f1: float = 0.5,
    n_rows: int = 76,
    legit: int = 17,
    hard: int | None = None,
    groups: int | None = 28,
    **extra,
) -> ResultRow:
    """A results row with the support counts the harness records."""
    payload: dict = {
        "system": system,
        "model": model,
        "split": split,
        "lang": lang,
        "ablation": "none",
        "macro_f1": macro_f1,
        "ci95": (max(0.0, macro_f1 - 0.1), min(1.0, macro_f1 + 0.1)),
        "n": n_rows,
        "abstain_rate": 0.0,
        "n_rows": n_rows,
        "n_by_label": {"legit": legit, "scam": n_rows - legit},
    }
    if hard is not None:
        payload.update(
            fpr_hard_negative=0.1, fpr_hard_negative_ci95=[0.05, 0.2], n_hard_negative=hard
        )
    if groups is not None:
        payload["n_source_groups"] = groups
    payload.update(extra)
    return ResultRow(**payload)


def results_of(rows: list[ResultRow], **extra) -> Results:
    return Results(run_id="t", dataset_version="kazscam-test", n_bootstrap=100, rows=rows, **extra)


def press_support(n_rows: int, legit: int, *, hard: int = 0, kk: int = 0) -> dict:
    return {
        "test_press": {
            "n_rows": n_rows,
            "by_label": {"legit": legit, "scam": n_rows - legit},
            "by_lang": {"kk": kk, "ru": n_rows - kk},
            "n_hard_negative": hard,
        }
    }


def table_line(text: str, *cells: str) -> str:
    """The one table line that starts with these cells."""
    start = "| " + " | ".join(cells) + " |"
    matches = [line for line in text.splitlines() if line.startswith(start)]
    assert len(matches) == 1, f"{len(matches)} lines start with {start!r}"
    return matches[0]


def test_the_harness_records_the_support_behind_every_cell(tmp_path):
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line]
    # Two groups of two and eight rows on their own: ten groups in twelve rows.
    for row, group in zip(rows, ["a", "a", "b", "b"], strict=False):
        row["source_group"] = group
    for row in rows[4:]:
        row["source_group"] = row["id"]
    grouped = tmp_path / "grouped.jsonl"
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    grouped.write_text("\n".join(lines) + "\n", encoding="utf-8")

    config = smoke_config(splits={"test_press": str(grouped)})
    outcome = run(config, out_dir=tmp_path, env=NO_KEYS, run_id="support")
    by_lang = {row.lang: row for row in outcome.results.rows}
    assert by_lang["all"].n_by_label == {"ambiguous": 1, "legit": 4, "scam": 7}
    assert by_lang["all"].n_source_groups == 10
    assert by_lang["kk"].n_by_label == {"ambiguous": 1, "legit": 1, "scam": 3}

    # The split's own counts travel in results.json, which is all the
    # leaderboard reads, and survive the round trip through the file.
    read_back = read_results(outcome.results_path)
    assert read_back.split_support == {
        "test_press": {
            "n_rows": 12,
            "by_label": {"ambiguous": 1, "legit": 4, "scam": 7},
            "by_lang": {"kk": 5, "ru": 7},
            "n_hard_negative": 3,
            "n_source_groups": 10,
        }
    }
    # A full run records no limit; the file leaves out what has no value.
    assert "limit" not in (read_back.model_extra or {})
    assert "| 12 (10) |" in render_leaderboard(read_back)

    # A file whose rows name no group gets a dash, never a count of its rows.
    plain = run(load_config(SMOKE_CONFIG), out_dir=tmp_path, env=NO_KEYS, run_id="plain")
    assert all("n_source_groups" not in (r.model_extra or {}) for r in plain.results.rows)
    assert "| 12 (—) |" in render_leaderboard(plain.results)


def test_the_smoke_fixture_is_too_small_to_publish_anything(tmp_path):
    outcome = run(load_config(SMOKE_CONFIG), out_dir=tmp_path, env=NO_KEYS, run_id="small")
    text = render_leaderboard(outcome.results)

    assert run_release(outcome.results).tier == "none"
    assert "**Release tier: none.**" in text
    assert "12 rows (needs 60)" in text
    assert WITHHELD_NOTE in text
    assert "(pilot)" not in text
    for row in outcome.results.rows:
        assert f"{row.macro_f1:.3f}" not in text.split("## test_press", 1)[1]
    assert table_line(text, "rules_only", "none", "all", "none", "12 (—)").count(NOT_REPORTED) == 5
    # results.json still holds every number that was computed.
    assert all(row.macro_f1 > 0 for row in read_results(outcome.results_path).rows)


def test_a_partial_run_publishes_no_test_number(tmp_path):
    outcome = run(load_config(SMOKE_CONFIG), out_dir=tmp_path, env=NO_KEYS, run_id="cut", limit=5)
    assert read_results(outcome.results_path).limit == 5
    text = render_leaderboard(outcome.results, floors=TINY_FLOORS)
    assert "**Release tier: none.**" in text
    assert "--limit 5" in text
    assert WITHHELD_NOTE in text


def test_a_development_table_prints_only_the_numbers_with_enough_rows_behind_them():
    results = results_of(
        [
            result_row(lang="all", macro_f1=0.486, n_rows=76, legit=17, hard=17, groups=28),
            result_row(lang="ru", macro_f1=0.499, n_rows=48, legit=13, hard=13, groups=20),
            result_row(lang="kk", macro_f1=0.447, n_rows=28, legit=4, hard=4, groups=16),
        ],
        split_support={"dev": {"n_rows": 76}},
    )
    text = render_leaderboard(results)

    assert "This run read no `test_press` rows" in text
    whole = table_line(text, "rules_only", "none", "all", "none", "76 (28)")
    assert "0.486 [0.386, 0.586]" in whole
    assert "not reported (17 hard negatives)" in whole
    assert "1.000" in whole  # coverage is still printed
    russian = table_line(text, "rules_only", "none", "ru", "none", "48 (20)")
    assert "0.499 [0.399, 0.599]" in russian
    assert "not reported (13 hard negatives)" in russian
    # Twenty-eight rows are under the slice floor: no metric at all.
    kazakh = table_line(text, "rules_only", "none", "kk", "none", "28 (16)")
    assert kazakh.count(NOT_REPORTED) == 5
    assert "0.447" not in text


def test_macro_f1_is_withheld_from_a_slice_with_a_thin_class():
    results = results_of([result_row(n_rows=40, legit=9, hard=30, macro_f1=0.7)])
    line = table_line(render_leaderboard(results), "rules_only", "none", "all", "none", "40 (28)")
    assert "not reported (9 legit)" in line
    assert "0.700" not in line
    # Thirty hard negatives are enough for the rate, whatever the F1 lacks.
    assert "0.100 [0.050, 0.200]" in line


def test_a_cell_that_records_no_counts_prints_no_number():
    bare = ResultRow(
        system="rules_only",
        model="none",
        split="dev",
        lang="all",
        ablation="none",
        macro_f1=0.9,
        ci95=(0.8, 1.0),
        n=500,
        fpr_hard_negative=0.0,
        abstain_rate=0.0,
    )
    line = table_line(
        render_leaderboard(results_of([bare])), "rules_only", "none", "all", "none", "500 (—)"
    )
    assert "not reported (class counts not recorded)" in line
    assert "not reported (hard-negative count not recorded)" in line
    assert "0.900" not in line


def test_a_cell_with_no_hard_negatives_still_prints_a_dash_for_the_rate():
    results = results_of([result_row(n_rows=40, legit=12)])
    line = table_line(render_leaderboard(results), "rules_only", "none", "all", "none", "40 (28)")
    assert "0.500 [0.400, 0.600] | — |" in line


def test_a_pilot_is_titled_a_pilot_wherever_a_test_number_appears():
    results = results_of(
        [
            result_row(split="dev"),
            result_row(split="test_press", n_rows=80, legit=25, hard=25, macro_f1=0.6),
            result_row(split="test_press", lang="kk", n_rows=20, legit=5, macro_f1=0.3),
        ],
        split_support=press_support(80, 25, hard=25, kk=20),
    )
    text = render_leaderboard(results)

    assert text.startswith("# Leaderboard — kazscam-test (pilot)\n")
    assert "**Release tier: pilot.**" in text
    assert "80 rows (needs 200)" in text
    assert "## test_press (pilot)" in text
    assert "## dev\n" in text
    assert WITHHELD_NOTE not in text
    test_table = text.split("## test_press (pilot)", 1)[1]
    assert "0.600 [0.500, 0.700]" in test_table
    assert "not reported (25 hard negatives)" in test_table
    # The pilot publishes supported slices only.
    assert table_line(text, "rules_only", "none", "kk", "none", "20 (28)").count(NOT_REPORTED) == 5


def test_a_benchmark_prints_the_full_table_without_the_pilot_title():
    results = results_of(
        [result_row(split="test_press", n_rows=200, legit=60, hard=40, macro_f1=0.8)],
        split_support=press_support(200, 60, hard=40, kk=100),
    )
    text = render_leaderboard(results)
    assert "**Release tier: benchmark.**" in text
    assert "(pilot)" not in text
    assert "0.800 [0.700, 0.900] | 0.100 [0.050, 0.200] |" in text


def test_a_tier_of_none_withholds_the_donated_table_too():
    results = results_of(
        [
            result_row(split="test_press", n_rows=46, legit=10, macro_f1=0.61),
            result_row(split="test_donated", n_rows=90, legit=40, macro_f1=0.72),
        ],
        split_support=press_support(46, 10),
    )
    text = render_leaderboard(results)
    assert "**Release tier: none.**" in text
    assert text.count(WITHHELD_NOTE) == 2
    assert "0.610" not in text
    assert "0.720" not in text


def test_test_rows_with_no_recorded_split_size_are_not_published():
    """A results file from before the counts existed cannot show it clears a floor."""
    results = results_of([result_row(split="test_press", n_rows=300, legit=90, macro_f1=0.9)])
    text = render_leaderboard(results)
    assert "does not record the size of its splits" in text
    assert "0.900" not in text


def test_withheld_rows_are_not_ranked_by_the_number_that_was_withheld():
    rows = [
        result_row(split="test_press", system="hybrid", model="m", macro_f1=0.2, n_rows=12),
        result_row(split="test_press", system="rules_only", macro_f1=0.9, n_rows=12),
        result_row(split="test_press", system="llm_zeroshot", model="m", macro_f1=0.5, n_rows=12),
    ]
    text = render_leaderboard(results_of(rows, split_support=press_support(12, 4)))
    order = [line.split(" | ")[0] for line in text.splitlines() if " | all | none | 12 " in line]
    assert order == ["| hybrid", "| llm_zeroshot", "| rules_only"]

    # With numbers that may be printed, the best point estimate comes first.
    big = [
        row.model_copy(update={"n_rows": 80, "n_by_label": {"legit": 30, "scam": 50}})
        for row in rows
    ]
    text = render_leaderboard(results_of(big, split_support=press_support(80, 30)))
    order = [line.split(" | ")[0] for line in text.splitlines() if " | all | none | 80 " in line]
    assert order == ["| rules_only", "| llm_zeroshot", "| hybrid"]


def test_the_header_states_the_floors_that_were_applied():
    results = results_of([result_row()])
    text = render_leaderboard(results)
    assert "fewer than 30 rows" in text
    assert "at least 10 rows of each class" in text
    assert "at least 30 hard negatives" in text
    assert "The intervals resample rows, not groups" in text
    loose = render_leaderboard(results, floors=TINY_FLOORS)
    assert "fewer than 1 rows" in loose


def test_the_cli_runs_the_smoke_matrix_and_renders_the_leaderboard(tmp_path, capsys):
    out = tmp_path / "cli"
    assert main(["run", "--config", str(SMOKE_CONFIG), "--out", str(out), "--run-id", "r"]) == 0
    assert (out / "r" / "results.json").is_file()
    assert (out / "r" / "manifest.json").is_file()
    assert "3 of 3 cells executed" in capsys.readouterr().out

    results = out / "r" / "results.json"
    board = out / "r" / "leaderboard.md"
    assert main(["leaderboard", "--results", str(results), "--out", str(board)]) == 0
    assert "beats" not in board.read_text(encoding="utf-8")

    # A system the config does not list is an error, not a silent no-op.
    bad = ["run", "--config", str(SMOKE_CONFIG), "--out", str(out), "--systems", "hybrid"]
    assert main(bad) == 2
    assert "not in the config" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The model path, with a client that never leaves the process
# ---------------------------------------------------------------------------


class StubClient:
    """Answers every model call offline, the way a replay client would."""

    def __init__(self) -> None:
        self.calls = 0

    async def structured(self, *, model, system, user, schema, temperature):
        self.calls += 1
        stats = SimpleNamespace(model=model, latency_ms=1, cached=True)
        scammy = "kaspi" in user.lower()
        if schema is ZeroShotJudgement:
            if scammy:
                judgement = schema(
                    label="scam", playbook_id="kz.bank_security_call", stage=Stage.HOOK
                )
            else:
                judgement = schema(label="legit", confidence=0.8)
            return judgement, stats
        judgement = LLMJudgement(
            playbook_id="kz.bank_security_call" if scammy else None,
            confidence=0.9 if scammy else 0.1,
            stage=Stage.HOOK if scammy else None,
        )
        return judgement, stats


def test_model_systems_run_through_a_supplied_client_without_a_key(tmp_path):
    stub = StubClient()
    config = smoke_config(
        systems=["llm_zeroshot", "hybrid"],
        models=["stub-model"],
        languages=["all"],
        ablations=["none", "no_playbook_context"],
    )
    outcome = run(
        config, out_dir=tmp_path, env=NO_KEYS, run_id="stub", clients={"stub-model": stub}
    )

    cells = {(row.system, row.ablation) for row in outcome.results.rows}
    assert cells == {
        ("llm_zeroshot", "none"),
        ("hybrid", "none"),
        ("hybrid", "no_playbook_context"),
    }
    assert [s.cell.system for s in outcome.skipped] == ["llm_zeroshot"]
    assert "never sees playbook context" in outcome.skipped[0].reason
    assert stub.calls == 3 * 12
    for row in outcome.results.rows:
        assert row.model == "stub-model"
        assert row.prompt_hash.startswith("sha256:")
        assert "n_errors" not in (row.model_extra or {})

    (zeroshot,) = [r for r in outcome.results.rows if r.system == "llm_zeroshot"]
    # The stub never abstains, and names the playbook on the two Kaspi rows,
    # which carry the gold stages hook and pressure; it says hook for both.
    assert zeroshot.abstain_rate == 0.0
    assert zeroshot.stage_n_eligible == 2
    assert zeroshot.stage_n_correct == 1
