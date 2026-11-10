"""The pilot draw and the agreement report.

The labels in this file are made up to exercise the arithmetic. They are test
inputs and stand for no annotator; the pilot itself has not been labelled.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from collections import Counter
from pathlib import Path

import pytest

from saqbol.eval import metrics

REPO = Path(__file__).resolve().parent.parent
DEV = REPO / "data" / "kazscam_v0.1" / "dev.jsonl"
BATCH = REPO / "data" / "pilot" / "batch-pilot-02.json"

spec = importlib.util.spec_from_file_location("kazscam_pilot", REPO / "tools" / "pilot.py")
pilot = importlib.util.module_from_spec(spec)
# Registered before it runs: its dataclasses look their own module up by name.
sys.modules[spec.name] = pilot
spec.loader.exec_module(pilot)

SEED = pilot.DEFAULT_SEED


# ---------------------------------------------------------------------------
# draw
# ---------------------------------------------------------------------------


def row(i: int, label: str, lang: str, group: str) -> dict:
    return {
        "id": f"r-{i:03d}",
        "text": f"message {i}",
        "label": label,
        "lang": lang,
        "source_group": group,
        "hard_negative": label == "legit",
        "channel": "web" if label == "legit" else "call",
        "source": "official_warning" if label == "legit" else "press",
    }


SMALL = {("legit", "ru"): 2, ("scam", "ru"): 3}


def pool() -> list[dict]:
    rows = [row(i, "legit", "ru", f"n-{i}") for i in range(4)]
    rows += [row(10 + i, "scam", "ru", "big-article") for i in range(6)]
    rows += [row(20 + i, "scam", "ru", f"s-{i}") for i in range(2)]
    return rows


def test_the_draw_fills_every_quota():
    chosen = pilot.draw(pool(), seed=SEED, quotas=SMALL)
    assert Counter((r["label"], r["lang"]) for r in chosen) == SMALL


def test_one_article_cannot_be_most_of_the_pilot():
    chosen = pilot.draw(pool(), seed=SEED, quotas={("scam", "ru"): 4})
    groups = Counter(r["source_group"] for r in chosen)
    assert groups["big-article"] == 2
    assert set(groups) == {"big-article", "s-0", "s-1"}


def test_a_source_another_language_used_is_taken_last():
    rows = [row(1, "legit", "kk", "notice-a"), row(2, "legit", "ru", "notice-a")]
    rows += [row(3, "legit", "ru", "notice-b"), row(4, "legit", "ru", "notice-c")]
    for seed in range(20):
        chosen = pilot.draw(rows, seed=seed, quotas={("legit", "kk"): 1, ("legit", "ru"): 2})
        assert {r["id"] for r in chosen} == {"r-001", "r-003", "r-004"}


def test_the_draw_is_seeded():
    assert pilot.draw(pool(), seed=1, quotas=SMALL) == pilot.draw(pool(), seed=1, quotas=SMALL)
    orders = {tuple(r["id"] for r in pilot.draw(pool(), seed=s, quotas=SMALL)) for s in range(8)}
    assert len(orders) > 1


def test_a_quota_the_sources_cannot_fill_is_an_error():
    with pytest.raises(pilot.PilotError, match="only 4 of 5 scam/ru rows"):
        pilot.draw(pool(), seed=SEED, quotas={("scam", "ru"): 5})


def test_an_item_shows_an_annotator_nothing_but_the_text():
    rows = pool()
    chosen = pilot.draw(rows, seed=SEED, quotas=SMALL)
    document, key = pilot.build_batch(
        chosen,
        all_rows=rows,
        dev_path="dev.jsonl",
        batch="batch-x",
        prefix="ks-x",
        seed=SEED,
        created_at="2026-11-11",
        quotas=SMALL,
    )
    assert all(set(item) == {"id", "text"} for item in document["items"])
    assert [item["id"] for item in document["items"]] == [f"ks-x-{i:03d}" for i in range(1, 6)]
    # The dataset id, the label and the source stay in the key.
    assert not any("r-0" in item["id"] for item in document["items"])
    assert [e["row_id"] for e in key["items"]] == [r["id"] for r in chosen]
    assert key["quotas"] == {"legit/ru": 2, "scam/ru": 3}


def test_the_committed_batch_is_the_seeded_draw_from_dev():
    """Fails when `dev` changed and the batch was not redrawn.

    Redraw with `python tools/pilot.py draw --dev data/kazscam_v0.1/dev.jsonl
    --out data/pilot/batch-pilot-02.json`, and only before anyone has labelled it.
    """
    rows = pilot.read_rows(DEV)
    document = json.loads(BATCH.read_text(encoding="utf-8"))
    key = json.loads(pilot.key_path_for(BATCH).read_text(encoding="utf-8"))
    fresh_document, fresh_key = pilot.build_batch(
        pilot.draw(rows, seed=key["seed"]),
        all_rows=rows,
        dev_path=key["drawn_from"]["path"],
        batch=BATCH.stem,
        prefix=pilot.DEFAULT_PREFIX,
        seed=key["seed"],
        created_at=key["created_at"],
    )
    assert document == fresh_document
    assert key == fresh_key


def test_the_committed_batch_is_thirty_dev_rows_with_nothing_to_give_the_label_away():
    by_id = {r["id"]: r for r in pilot.read_rows(DEV)}
    document = json.loads(BATCH.read_text(encoding="utf-8"))
    key = json.loads(pilot.key_path_for(BATCH).read_text(encoding="utf-8"))
    assert len(document["items"]) == 30
    assert all(set(item) == {"id", "text"} for item in document["items"])
    for item, entry in zip(document["items"], key["items"], strict=True):
        assert item["id"] == entry["pilot_id"]
        assert item["text"] == by_id[entry["row_id"]]["text"]
    mix = Counter(e["provisional_label"] for e in key["items"])
    assert mix == {"legit": 10, "scam": 20}
    assert max(Counter(e["source_group"] for e in key["items"]).values()) <= 2
    # No message appears in both languages.
    langs: dict[str, set[str]] = {}
    for entry in key["items"]:
        langs.setdefault(entry["source_group"], set()).add(
            (entry["lang"], entry["provisional_label"])
        )
    assert not any({("ru", "legit"), ("kk", "legit")} <= seen for seen in langs.values())


# ---------------------------------------------------------------------------
# agreement: the statistics
# ---------------------------------------------------------------------------


def test_alpha_matches_a_hand_calculation():
    # Two annotators, four items. Coincidences: aa 2, ab 1, ba 1, bb 4; n = 8.
    # Observed 2/8, expected 2*3*5 / (8*7); alpha = 1 - (2/8) / (30/56).
    units = [["a", "a"], ["a", "b"], ["b", "b"], ["b", "b"]]
    assert pilot.krippendorff_alpha(units) == pytest.approx(1 - 14 / 30)


def test_alpha_is_one_for_full_agreement_and_undefined_for_one_category():
    assert pilot.krippendorff_alpha([["a", "a", "a"], ["b", "b"]]) == 1.0
    assert math.isnan(pilot.krippendorff_alpha([["a", "a"], ["a", "a"]]))
    assert math.isnan(pilot.krippendorff_alpha([["a"], ["b"]]))


def test_alpha_ignores_an_item_only_one_person_labelled():
    units = [["a", "a"], ["a", "b"], ["b", "b"], ["b", "b"]]
    assert pilot.krippendorff_alpha([*units, ["a"]]) == pilot.krippendorff_alpha(units)


def test_the_kappa_interval_is_seeded_and_holds_the_estimate():
    a = ["scam"] * 12 + ["legit"] * 8 + ["scam"] * 4 + ["legit"] * 6
    b = ["scam"] * 12 + ["legit"] * 8 + ["legit"] * 4 + ["scam"] * 6
    first = pilot.kappa_interval(a, b, seed=SEED, n_resamples=2000)
    assert first == pilot.kappa_interval(a, b, seed=SEED, n_resamples=2000)
    assert first[0] < metrics.cohens_kappa(a, b) < first[1]


def test_no_interval_where_no_resample_has_a_kappa():
    assert pilot.kappa_interval(["scam"] * 5, ["scam"] * 5, seed=SEED, n_resamples=200) is None
    assert pilot.kappa_interval(["scam"], ["legit"], seed=SEED, n_resamples=200) is None


# ---------------------------------------------------------------------------
# agreement: exports
# ---------------------------------------------------------------------------

ITEMS = [f"ks-t-{i:03d}" for i in range(1, 11)]
BATCH_DOC = {"items": [{"id": i, "text": f"text of {i}"} for i in ITEMS]}


def answer(item: str, who: str, verdict: str, playbook: str = "", at: str = "") -> dict:
    """One row, in the shape the page's export writes."""
    return {
        "item_id": item,
        "text": f"text of {item}",
        "source": "",
        "annotator": who.title(),
        "annotator_id": who,
        "verdict": verdict,
        "playbook": playbook,
        "seconds": "4.2",
        "at": at or "2026-11-20T10:00:00.000Z",
    }


def export(who: str, verdicts: str, scripts: dict[int, str] | None = None, **kw) -> list[dict]:
    """`verdicts` is one letter per item: s scam, l legit, u unsure, k skip, - none."""
    names = {"s": "scam", "l": "legit", "u": "unsure", "k": "skip"}
    rows = []
    for index, letter in enumerate(verdicts):
        if letter == "-":
            continue
        script = (scripts or {}).get(index, "kz.bank_security_call" if letter == "s" else "")
        rows.append(answer(ITEMS[index], who, names[letter], script, **kw))
    return rows


A = export("aigerim", "ssssslllll")
B = export("bolat", "sssssllllu")
C = export("dana", "sssslllllu", scripts={0: "kz.remote_access_loan"})


def test_three_complete_annotators_make_a_finished_pilot():
    report = pilot.analyse(BATCH_DOC, [A, B, C], n_resamples=500)
    assert report["finished"] is True
    assert report["notes"] == []
    assert report["kind"] == "inter-annotator"
    assert [row["n_labelled"] for row in report["coverage"]] == [10, 10, 10]
    assert len(report["verdict"]["pairs"]) == 3


def test_pairwise_kappa_is_the_harness_statistic_on_dataset_labels():
    report = pilot.analyse(BATCH_DOC, [A, B, C], n_resamples=500)
    pair = report["verdict"]["pairs"][0]
    assert pair["annotators"] == ["aigerim", "bolat"]
    a = ["scam"] * 5 + ["legit"] * 5
    b = ["scam"] * 5 + ["legit"] * 4 + ["ambiguous"]
    assert pair["n_items"] == 10
    assert pair["agreement"] == 0.9
    assert pair["kappa"] == pytest.approx(metrics.cohens_kappa(a, b), abs=1e-4)
    # "Not sure" on the page is `ambiguous` in the dataset.
    assert report["coverage"][1]["by_verdict"] == {"scam": 5, "legit": 4, "ambiguous": 1}
    assert pair["kappa_per_class"]["ambiguous"] == pytest.approx(0.0, abs=1e-9)


def test_the_script_is_compared_only_where_both_said_scam():
    report = pilot.analyse(BATCH_DOC, [A, B, C], n_resamples=500)
    by_pair = {tuple(p["annotators"]): p["script"] for p in report["verdict"]["pairs"]}
    assert by_pair[("aigerim", "bolat")] == {
        "n_items": 5,
        "agreement": 1.0,
        "kappa": None,  # one script only: chance agreement is total
        "confused": [],
    }
    with_dana = by_pair[("aigerim", "dana")]
    assert with_dana["n_items"] == 4
    assert with_dana["agreement"] == 0.75
    assert with_dana["confused"] == [
        {"scripts": ["kz.bank_security_call", "kz.remote_access_loan"], "n": 1}
    ]


def test_every_split_item_is_listed_and_no_other():
    report = pilot.analyse(BATCH_DOC, [A, B, C], n_resamples=500)
    listed = {d["item_id"]: d["on"] for d in report["disagreements"]}
    assert listed == {
        ITEMS[0]: "script",  # all scam, two scripts
        ITEMS[4]: "verdict",  # dana said legit
        ITEMS[9]: "verdict",  # one legit, two unsure
    }
    text = pilot.render(report)
    assert "### ks-t-005 (verdict)" in text
    assert "- Dana: legit" in text
    assert text.count("Adjudication:") == 3
    assert "Not a finished pilot" not in text


def test_two_annotators_are_reported_as_unfinished_not_refused():
    report = pilot.analyse(BATCH_DOC, [A, B], n_resamples=500)
    assert report["finished"] is False
    assert "2 annotators, and the protocol asks for 3" in report["notes"][0]
    assert "**Not a finished pilot" in pilot.render(report)


def test_one_annotator_is_refused():
    with pytest.raises(pilot.PilotError, match="at least two annotators"):
        pilot.analyse(BATCH_DOC, [A], n_resamples=500)


def test_missing_and_skipped_items_are_counted_not_filled():
    partial = export("dana", "ssk-------")
    report = pilot.analyse(BATCH_DOC, [A, B, partial], n_resamples=500)
    dana = report["coverage"][2]
    assert dana["n_labelled"] == 2
    assert dana["n_missing"] == 8
    assert report["ignored"]["skipped"] == 1
    assert report["finished"] is False
    assert "Dana did not label every item" in " ".join(report["notes"])
    assert report["verdict"]["pairs"][2]["n_items"] == 2  # bolat and dana


def test_labels_on_another_batch_are_left_out():
    stray = [answer("ks-pilot-001", "aigerim", "scam")]
    report = pilot.analyse(BATCH_DOC, [A, B, C, stray], n_resamples=500)
    assert report["ignored"]["outside_batch"] == 1
    assert report["coverage"][0]["n_labelled"] == 10


def test_a_changed_answer_keeps_the_later_one():
    early = [answer(ITEMS[0], "aigerim", "legit", at="2026-11-19T09:00:00.000Z")]
    report = pilot.analyse(BATCH_DOC, [early, A, B, C], n_resamples=500)
    assert report["coverage"][0]["by_verdict"]["scam"] == 5
    assert "1 answers differed between exports" in " ".join(report["notes"])


def test_an_unknown_verdict_is_an_error():
    bad = [answer(ITEMS[0], "dana", "probably")]
    with pytest.raises(pilot.PilotError, match="unknown verdict 'probably'"):
        pilot.analyse(BATCH_DOC, [A, B, bad], n_resamples=500)


def test_the_provisional_label_is_compared_only_when_a_key_is_given():
    key = {
        "items": [
            {"pilot_id": item, "provisional_label": "scam" if i < 5 else "legit"}
            for i, item in enumerate(ITEMS)
        ]
    }
    assert "provisional" not in pilot.analyse(BATCH_DOC, [A, B, C], n_resamples=500)
    report = pilot.analyse(BATCH_DOC, [A, B, C], key=key, n_resamples=500)
    assert [row["n_same"] for row in report["provisional"]] == [10, 9, 8]
    assert "It is not gold" in pilot.render(report)


def test_two_passes_by_one_person_are_called_what_they_are():
    first = export("toktar-1", "ssssslllll", at="2026-11-20T10:00:00.000Z")
    late = export("toktar-2", "sssssllllu", at="2026-12-05T10:00:00.000Z")
    report = pilot.analyse(BATCH_DOC, [first, late], intra=True, n_resamples=500)
    assert report["kind"] == "intra-annotator"
    assert report["finished"] is True
    assert "Intra-annotator agreement on 10 items, 2 passes by one person" in pilot.render(report)


def test_a_second_pass_made_too_soon_is_flagged():
    first = export("toktar-1", "ssssslllll", at="2026-11-20T10:00:00.000Z")
    soon = export("toktar-2", "sssssllllu", at="2026-11-23T10:00:00.000Z")
    report = pilot.analyse(BATCH_DOC, [first, soon], intra=True, n_resamples=500)
    assert "3 days apart, under the 14" in " ".join(report["notes"])
    with pytest.raises(pilot.PilotError, match="exactly two passes"):
        pilot.analyse(BATCH_DOC, [first, soon, C], intra=True, n_resamples=500)


# ---------------------------------------------------------------------------
# agreement: files
# ---------------------------------------------------------------------------


def write_export_json(path: Path, rows: list[dict]) -> Path:
    payload = {"exportedAt": "2026-11-21T08:00:00.000Z", "rows": rows}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_export_csv(path: Path, rows: list[dict]) -> Path:
    """As the page writes it: quoted, CRLF, with a byte-order mark."""
    cols = ["item_id", "annotator", "annotator_id", "verdict", "playbook", "seconds", "at"]
    cols += ["source", "text"]
    quote = lambda value: '"' + str(value).replace('"', '""') + '"'  # noqa: E731
    lines = [",".join(cols)] + [",".join(quote(r[c]) for c in cols) for r in rows]
    path.write_bytes(("﻿" + "\r\n".join(lines)).encode("utf-8"))
    return path


def test_the_json_and_the_csv_export_read_the_same(tmp_path):
    rows = A + B + C
    as_json = pilot.read_export(write_export_json(tmp_path / "labels.json", rows))
    as_csv = pilot.read_export(write_export_csv(tmp_path / "labels.csv", rows))
    assert as_json == rows
    assert pilot.analyse(BATCH_DOC, [as_csv], n_resamples=500) == pilot.analyse(
        BATCH_DOC, [as_json], n_resamples=500
    )


def test_a_file_that_is_not_an_export_is_refused(tmp_path):
    other = tmp_path / "other.json"
    other.write_text('{"items": []}', encoding="utf-8")
    with pytest.raises(pilot.PilotError, match='no "rows" list'):
        pilot.read_export(other)
    short = write_export_json(tmp_path / "short.json", [{"item_id": "x", "verdict": "scam"}])
    with pytest.raises(pilot.PilotError, match="no annotator_id"):
        pilot.read_export(short)


def test_the_command_writes_the_report_and_its_json(tmp_path, capsys):
    batch = tmp_path / "batch-t.json"
    batch.write_text(json.dumps(BATCH_DOC), encoding="utf-8")
    labels = write_export_json(tmp_path / "labels.json", A + B + C)
    out, data = tmp_path / "report.md", tmp_path / "report.json"
    code = pilot.main(
        [
            *["agreement", "--batch", str(batch), "--exports", str(labels)],
            *["--out", str(out), "--json", str(data), "--resamples", "500"],
        ]
    )
    assert code == 0
    assert out.read_text(encoding="utf-8").startswith("# Annotation pilot agreement: batch-t")
    assert json.loads(data.read_text(encoding="utf-8"))["schema"] == pilot.REPORT_SCHEMA
    assert pilot.main(["agreement", "--batch", str(batch), "--exports", str(batch)]) == 2
    assert 'no "rows" list' in capsys.readouterr().err


def test_the_draw_command_writes_the_batch_and_its_key(tmp_path, capsys):
    out = tmp_path / "batch-new.json"
    assert pilot.main(["draw", "--dev", str(DEV), "--out", str(out), "--date", "2026-11-11"]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == json.loads(
        BATCH.read_text(encoding="utf-8")
    )
    key = json.loads((tmp_path / "batch-new.key.json").read_text(encoding="utf-8"))
    assert key["schema"] == pilot.KEY_SCHEMA
    assert "drew 30 of 76 rows" in capsys.readouterr().out
