"""`tools/labels.py`: from a labelling batch to a label record.

Every answer in this file is made up to exercise the tool. They are test
inputs and stand for no annotator: no KazScam row has been labelled.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from saqbol.eval.__main__ import main as eval_main
from saqbol.eval.labels import read_record
from tests.test_splits import _write_corpus, corpus_row, filler

REPO = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("kazscam_labels_tool", REPO / "tools" / "labels.py")
tool = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tool
spec.loader.exec_module(tool)

DELIVERY = "kz.delivery_link"
STORE = "kz.fake_store"


def run(*argv: object) -> int:
    return tool.main([str(arg) for arg in argv])


# ---------------------------------------------------------------------------
# batch
# ---------------------------------------------------------------------------


def a_corpus(tmp_path: Path) -> Path:
    """Six fresh rows, two exposed ones, a fragment, under `tmp_path/data/corpus`."""
    rows = [
        *filler(6, prefix="new"),
        corpus_row("ks-old-001", "  Ваш счёт заблокирован, назовите код.  "),
        corpus_row("ks-old-002", "Kaspi: код 4821. Никому не сообщайте.", label="legit"),
        corpus_row("ks-frag-001", "бұғатталды", lang="kk", text_kind="phrase_fragment"),
    ]
    rows[7]["hard_negative"] = True
    corpus = tmp_path / "data" / "corpus"
    _write_corpus(corpus, rows)
    register = {"exposed_batches": [], "exposed_ids": ["ks-old-001", "ks-old-002"]}
    (tmp_path / "data" / "exposure.json").write_text(json.dumps(register), encoding="utf-8")
    return corpus


def draw(tmp_path: Path, *extra: object, name: str = "batch-annot-01") -> tuple[int, Path]:
    out = tmp_path / "data" / "annotation" / f"{name}.json"
    code = run("batch", "--corpus", tmp_path / "data" / "corpus", "--out", out, *extra)
    return code, out


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_batch_is_the_fresh_unlabelled_messages_and_shows_nothing_but_the_text(tmp_path, capsys):
    a_corpus(tmp_path)
    code, out = draw(tmp_path, "--date", "2027-01-10")
    assert code == 0
    assert "6 items in scope fresh" in capsys.readouterr().out

    batch = read(out)
    assert [set(item) for item in batch["items"]] == [{"id", "text"}] * 6
    assert [item["id"] for item in batch["items"]] == [f"annot-01-{i:03d}" for i in range(1, 7)]
    assert batch["createdAt"] == "2027-01-10"

    key = read(out.with_name("batch-annot-01.key.json"))
    assert key["schema"] == "kazscam-annotation-key/1"
    assert key["batch"] == "batch-annot-01"
    assert key["drawn_from"]["scope"] == "fresh"
    assert key["drawn_from"]["unlabelled_dev_rows"] == 2
    assert sorted(e["corpus_id"] for e in key["items"]) == [f"ks-new-{i:03d}" for i in range(6)]
    # Shuffled: the order shown is not the order collected.
    assert [e["corpus_id"] for e in key["items"]] != sorted(e["corpus_id"] for e in key["items"])
    assert [e["item_id"] for e in key["items"]] == [item["id"] for item in batch["items"]]
    assert set(key["items"][0]) == {
        "item_id",
        "corpus_id",
        "text_sha256",
        "lang",
        "provisional_label",
        "hard_negative",
    }


def test_the_digest_in_the_key_is_the_one_the_split_builder_checks(tmp_path):
    a_corpus(tmp_path)
    code, out = draw(tmp_path, "--scope", "dev")
    assert code == 0
    batch, key = read(out), read(out.with_name("batch-annot-01.key.json"))
    assert {e["corpus_id"] for e in key["items"]} == {"ks-old-001", "ks-old-002"}
    shown = {item["id"]: item["text"] for item in batch["items"]}
    for entry in key["items"]:
        text = shown[entry["item_id"]]
        # The released text is stripped, and that is what the annotator saw.
        assert text == text.strip()
        assert entry["text_sha256"] == tool.splits.text_sha256(text)
    flagged = {e["corpus_id"]: e["hard_negative"] for e in key["items"]}
    assert flagged == {"ks-old-001": False, "ks-old-002": True}


def test_the_draw_is_seeded_and_a_limit_takes_the_first_of_the_shuffle(tmp_path):
    a_corpus(tmp_path)
    _, first = draw(tmp_path, "--scope", "all", name="batch-a")
    _, again = draw(tmp_path, "--scope", "all", name="batch-b")
    _, other = draw(tmp_path, "--scope", "all", "--seed", "7", name="batch-c")
    _, short = draw(tmp_path, "--scope", "all", "--limit", "3", name="batch-d")
    texts = [[item["text"] for item in read(path)["items"]] for path in (first, again, other)]
    assert len(texts[0]) == 8
    assert texts[0] == texts[1] != texts[2]
    assert [item["text"] for item in read(short)["items"]] == texts[0][:3]


def test_an_existing_batch_is_not_redrawn_and_an_empty_scope_is_an_error(tmp_path, capsys):
    a_corpus(tmp_path)
    assert draw(tmp_path)[0] == 0
    capsys.readouterr()
    assert draw(tmp_path)[0] == 2
    assert "is not redrawn" in capsys.readouterr().err
    assert draw(tmp_path, "--force")[0] == 0

    (tmp_path / "data" / "exposure.json").write_text(
        json.dumps({"exposed_batches": ["a", "b"], "exposed_ids": []}), encoding="utf-8"
    )
    code, _ = draw(tmp_path, name="batch-annot-02")
    assert code == 2
    assert "0 fresh and 8 dev rows have no label record" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# exports
# ---------------------------------------------------------------------------

LETTERS = {"s": "scam", "l": "legit", "u": "unsure", "k": "skip"}


def answers(batch: dict, who: str, verdicts: str, scripts: dict[int, str] | None = None) -> list:
    """`verdicts` is one letter per item: s scam, l legit, u unsure, k skip, - none."""
    rows = []
    for index, (item, letter) in enumerate(zip(batch["items"], verdicts, strict=True)):
        if letter == "-":
            continue
        script = (scripts or {}).get(index, DELIVERY if letter == "s" else "")
        rows.append(
            {
                "item_id": item["id"],
                "annotator": who.title(),
                "annotator_id": who,
                "verdict": LETTERS[letter],
                "playbook": script,
                "at": "2027-01-12T10:00:00.000Z",
            }
        )
    return rows


def save(path: Path, rows: list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def labelled(tmp_path):
    """A six-item batch read by two annotators who differ on three items."""
    a_corpus(tmp_path)
    _, batch_path = draw(tmp_path)
    batch = read(batch_path)
    raw = tmp_path / "data" / "raw"
    exports = [
        # Item 2: a script against none. Item 3: two scripts. Item 5: the verdict.
        save(raw / "a.json", answers(batch, "aigerim-1a2b", "ssssll", {2: ""})),
        save(raw / "b.json", answers(batch, "bolat-3c4d", "sssslu", {3: STORE})),
        save(raw / "c.json", answers(batch, "dana-5e6f", "llllll")),
    ]
    return batch_path, exports


WHO = ("aigerim-1a2b=annotator-1", "bolat-3c4d=annotator-2")


def decide(path: Path, **by_item: tuple) -> None:
    document = read(path)
    for entry in document["items"]:
        made = by_item.get(entry["item_id"].replace("-", "_"))
        if made:
            entry["label"], entry["playbook_id"], entry["reason"], entry["decided_by"] = made
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")


ALL_DECIDED = {
    "annot_01_003": ("scam", DELIVERY, "A parcel notice with a payment link.", "discussion"),
    "annot_01_004": ("scam", None, "Both scripts fit; neither annotator would give way.", "Dana"),
    "annot_01_006": ("legit", None, "The sender is the bank's own short number.", "discussion"),
}


def test_the_adjudication_file_lists_exactly_the_items_read_differently(labelled, capsys):
    batch_path, exports = labelled
    code = run("adjudication", "--batch", batch_path, "--exports", *exports, "--annotators", *WHO)
    assert code == 0
    assert "3 of 6 items read twice need a decision" in capsys.readouterr().out

    document = read(tool.adjudication_path_for(batch_path))
    assert document["schema"] == "kazscam-adjudication/1"
    # The file carries the pseudonyms, not the ids derived from typed names.
    assert document["annotators"] == {"a": "annotator-1", "b": "annotator-2"}
    assert "aigerim" not in json.dumps(document)
    assert [
        (e["item_id"], e["on"], e["annotator_a"], e["annotator_b"]) for e in document["items"]
    ] == [
        ("annot-01-003", "script", "scam", "scam/kz.delivery_link"),
        ("annot-01-004", "script", "scam/kz.delivery_link", "scam/kz.fake_store"),
        ("annot-01-006", "verdict", "legit", "ambiguous"),
    ]
    assert all(e["label"] is None and e["reason"] == "" for e in document["items"])
    assert all(e["text"] for e in document["items"])


def test_merge_refuses_while_a_difference_has_no_decision(labelled, capsys):
    batch_path, exports = labelled
    out = batch_path.parents[1] / "labels" / "batch-annot-01.json"
    shared = ("--batch", batch_path, "--exports", *exports, "--annotators", *WHO)

    assert run("merge", *shared, "--out", out) == 2
    err = capsys.readouterr().err
    assert "no label record written" in err
    assert err.count("no decision is logged") == 3
    assert not out.exists()

    assert run("adjudication", *shared) == 0
    decide(tool.adjudication_path_for(batch_path), annot_01_003=ALL_DECIDED["annot_01_003"])
    assert run("merge", *shared, "--out", out) == 2
    assert capsys.readouterr().err.count("no decision is logged") == 2
    assert not out.exists()


def test_merge_writes_a_record_that_follows_from_the_readings_and_the_decisions(labelled, capsys):
    batch_path, exports = labelled
    out = batch_path.parents[1] / "labels" / "batch-annot-01.json"
    shared = ("--batch", batch_path, "--exports", *exports, "--annotators", *WHO)
    assert run("adjudication", *shared) == 0
    decide(tool.adjudication_path_for(batch_path), **ALL_DECIDED)
    capsys.readouterr()

    assert run("merge", *shared, "--out", out, "--date", "2027-01-15") == 0
    assert "6 rows labelled, 3 by a logged decision; 0 left unlabelled" in capsys.readouterr().out

    payload = read(out)
    assert payload["annotators"] == {"a": "annotator-1", "b": "annotator-2"}
    assert payload["kind"] == "inter-annotator"
    assert payload["created_at"] == "2027-01-15"
    assert "aigerim" not in json.dumps(payload) and "bolat" not in json.dumps(payload)

    key = {e["item_id"]: e for e in read(tool.pilot.key_path_for(batch_path))["items"]}
    rows = {row["corpus_id"]: row for row in payload["rows"]}
    assert len(rows) == 6

    def row_of(item: str) -> dict:
        row = rows[key[item]["corpus_id"]]
        assert row["text_sha256"] == key[item]["text_sha256"]
        return row

    agreed = row_of("annot-01-001")
    assert (agreed["label"], agreed["playbook_id"], agreed["adjudicated"]) == (
        "scam",
        DELIVERY,
        False,
    )
    assert "reason" not in agreed
    open_script = row_of("annot-01-004")
    assert (open_script["label"], open_script["playbook_id"]) == ("scam", None)
    assert (open_script["adjudicated"], open_script["decided_by"]) == (True, "Dana")
    settled = row_of("annot-01-006")
    assert (settled["annotator_a"], settled["annotator_b"], settled["label"]) == (
        "legit",
        "ambiguous",
        "legit",
    )

    # The record loads, and the split builder takes it from beside the corpus.
    assert len(read_record(out).rows) == 6
    release = batch_path.parents[1] / "kazscam"
    corpus = batch_path.parents[1] / "corpus"
    assert eval_main(["splits", "--corpus", str(corpus), "--out", str(release), "--seed", "5"]) == 0
    assert "6 of 8 rows carry two readings, 1 label records read" in capsys.readouterr().out


def test_a_decision_made_about_readings_that_changed_is_not_used(labelled, capsys):
    batch_path, exports = labelled
    out = batch_path.parents[1] / "labels" / "batch-annot-01.json"
    shared = ("--batch", batch_path, "--exports", *exports, "--annotators", *WHO)
    assert run("adjudication", *shared) == 0
    adjudication = tool.adjudication_path_for(batch_path)
    decide(adjudication, **ALL_DECIDED)

    # Bolat changes two answers afterwards: item 4 to another script, and
    # item 6 to the answer Aigerim gave.
    batch = read(batch_path)
    save(exports[1], answers(batch, "bolat-3c4d", "ssssll", {3: "kz.apk_install"}))
    capsys.readouterr()
    assert run("merge", *shared, "--out", out) == 2
    err = capsys.readouterr().err
    assert "annot-01-004: the decision answers scam/kz.delivery_link and scam/kz.fake_store" in err
    assert "annot-01-006: a decision is logged, and the two readings now agree (legit)" in err
    assert not out.exists()

    # Running `adjudication` again keeps the decision that still stands.
    assert run("adjudication", *shared) == 0
    printed = capsys.readouterr().out
    assert "2 of 6 items read twice need a decision: 1 already decided, 0 to decide" in printed
    assert "1 decisions were dropped" in printed
    entries = {e["item_id"]: e for e in read(adjudication)["items"]}
    assert sorted(entries) == ["annot-01-003", "annot-01-004"]
    assert entries["annot-01-003"]["reason"] == "A parcel notice with a payment link."
    assert entries["annot-01-004"]["label"] is None


def test_an_unfinished_batch_is_refused_unless_the_gap_is_recorded(labelled, capsys):
    batch_path, exports = labelled
    out = batch_path.parents[1] / "labels" / "batch-annot-01.json"
    batch = read(batch_path)
    # Aigerim skipped item 1 and never reached item 2; the rest agree.
    save(exports[0], answers(batch, "aigerim-1a2b", "k-ssll"))
    save(exports[1], answers(batch, "bolat-3c4d", "ssssll"))
    shared = ("--batch", batch_path, "--exports", *exports, "--annotators", *WHO)

    assert run("merge", *shared, "--out", out) == 2
    assert "2 items have fewer than two readings" in capsys.readouterr().err
    assert not out.exists()

    assert run("merge", *shared, "--out", out, "--allow-missing") == 0
    assert "4 rows labelled, 0 by a logged decision; 2 left unlabelled" in capsys.readouterr().out
    key = {e["item_id"]: e["corpus_id"] for e in read(tool.pilot.key_path_for(batch_path))["items"]}
    payload = read(out)
    assert payload["not_labelled"] == sorted([key["annot-01-001"], key["annot-01-002"]])
    assert not set(payload["not_labelled"]) & {row["corpus_id"] for row in payload["rows"]}


def test_answers_outside_the_label_set_and_unknown_annotators_are_named(labelled, capsys):
    batch_path, exports = labelled
    out = batch_path.parents[1] / "labels" / "batch-annot-01.json"
    batch = read(batch_path)
    save(exports[1], answers(batch, "bolat-3c4d", "ssssll", {0: "kz.made_up_script"}))
    shared = ("--batch", batch_path, "--exports", *exports)

    assert run("merge", *shared, "--annotators", *WHO, "--out", out) == 2
    assert "annot-01-001: reading: unknown script 'kz.made_up_script'" in capsys.readouterr().err

    assert run("merge", *shared, "--annotators", "aigerim-1a2b", "nobody", "--out", out) == 2
    err = capsys.readouterr().err
    assert "no answer from 'nobody'" in err
    assert "aigerim-1a2b, bolat-3c4d, dana-5e6f" in err

    assert run("merge", *shared, "--annotators", "aigerim-1a2b", "aigerim-1a2b", "--out", out) == 2
    assert "must be different" in capsys.readouterr().err
    assert not out.exists()


def test_a_row_is_not_labelled_by_two_records_and_a_labelled_row_is_not_drawn_again(
    labelled, capsys
):
    batch_path, exports = labelled
    data = batch_path.parents[1]
    batch = read(batch_path)
    save(exports[0], answers(batch, "aigerim-1a2b", "ssssll"))
    save(exports[1], answers(batch, "bolat-3c4d", "ssssll"))
    shared = ("--batch", batch_path, "--exports", *exports, "--annotators", *WHO)
    assert run("merge", *shared, "--out", data / "labels" / "batch-annot-01.json") == 0

    assert run("merge", *shared, "--out", data / "labels" / "copy.json") == 2
    assert "already labelled in another record" in capsys.readouterr().err
    assert not (data / "labels" / "copy.json").exists()
    # Writing the same record again, over itself, is not a clash.
    assert run("merge", *shared, "--out", data / "labels" / "batch-annot-01.json") == 0

    capsys.readouterr()
    code, _ = draw(data.parent, "--scope", "all", name="batch-annot-02")
    assert code == 0
    assert "2 items in scope all" in capsys.readouterr().out
    key = read(data / "annotation" / "batch-annot-02.key.json")
    assert {e["corpus_id"] for e in key["items"]} == {"ks-old-001", "ks-old-002"}
    assert key["drawn_from"]["rows_already_labelled"] == 6


def test_two_passes_by_one_person_are_recorded_as_that(labelled):
    batch_path, exports = labelled
    out = batch_path.parents[1] / "labels" / "batch-annot-01.json"
    batch = read(batch_path)
    save(exports[0], answers(batch, "owner-pass1", "ssssll"))
    save(exports[1], answers(batch, "owner-pass2", "ssssll"))
    who = ("owner-pass1=pass-1", "owner-pass2=pass-2")
    code = run(
        "merge", "--batch", batch_path, "--exports", *exports, "--annotators", *who,
        "--out", out, "--intra",
    )  # fmt: skip
    assert code == 0
    assert read(out)["kind"] == "intra-annotator"
    assert read_record(out).kind == "intra-annotator"


def test_the_agreement_report_is_the_pilots_over_the_two_named_annotators(labelled, capsys):
    batch_path, exports = labelled
    report = batch_path.with_name("agreement.md")
    code = run(
        "agreement", "--batch", batch_path, "--exports", *exports, "--annotators", *WHO,
        "--out", report, "--json", batch_path.with_name("agreement.json"), "--resamples", "200",
    )  # fmt: skip
    assert code == 0
    text = report.read_text(encoding="utf-8")
    assert text.startswith("# Annotation agreement: batch-annot-01")
    assert "tools/labels.py agreement" in text
    assert "Not a finished" not in text
    assert "Adjudication:" not in text
    assert "Dana" not in text
    assert "## Against the collector's provisional label" in text
    payload = read(batch_path.with_name("agreement.json"))
    assert sorted(payload["annotators"]) == ["aigerim-1a2b", "bolat-3c4d"]
    assert payload["finished"] is True
    assert [d["item_id"] for d in payload["disagreements"]] == [
        "annot-01-003",
        "annot-01-004",
        "annot-01-006",
    ]


def test_a_batch_one_annotator_has_not_finished_is_reported_as_unfinished(labelled, capsys):
    batch_path, exports = labelled
    batch = read(batch_path)
    save(exports[1], answers(batch, "bolat-3c4d", "sss---"))
    code = run("agreement", "--batch", batch_path, "--exports", *exports, "--annotators", *WHO)
    assert code == 0
    assert (
        "**Not a finished batch: Bolat-3C4D did not label every item.**" in capsys.readouterr().out
    )


def test_a_pilot_batch_is_not_merged_into_labels(tmp_path, capsys):
    pilot_batch = REPO / "data" / "pilot" / "batch-pilot-02.json"
    export = save(tmp_path / "x.json", [])
    code = run(
        "merge", "--batch", pilot_batch, "--exports", export, "--annotators", "a", "b",
        "--out", tmp_path / "labels" / "pilot.json",
    )  # fmt: skip
    assert code == 2
    assert "its answers are not merged into labels" in capsys.readouterr().err
