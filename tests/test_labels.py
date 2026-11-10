"""Label records, and what the split builder does with them.

docs/02_DATA_CONTRACTS.md section 6 ("Label records") is the contract under
test. Every reading and every decision in this file is made up to exercise
the rule. They are test inputs and stand for no annotator: no KazScam row has
been labelled.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saqbol.eval import labels
from saqbol.eval.__main__ import main
from saqbol.eval.labels import (
    DISCUSSION,
    INTRA,
    Decision,
    LabelError,
    Reading,
    difference,
    load_records,
    make_row,
    parse_reading,
    read_record,
    record_payload,
    resolve,
)
from saqbol.eval.run import load_split
from saqbol.eval.splits import CorpusError, assemble, read_split, text_sha256
from saqbol.eval.support import count_support
from tests.test_splits import _write_corpus, corpus_row, filler

DELIVERY = "kz.delivery_link"
STORE = "kz.fake_store"
WHY = "The payment page sits behind a parcel notice; the payload decides."


def decision(label: str = "scam", script: str | None = DELIVERY, **kw) -> Decision:
    return Decision(label, script, kw.get("reason", WHY), kw.get("decided_by", DISCUSSION))


# ---------------------------------------------------------------------------
# readings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, reading",
    [
        ("scam/kz.delivery_link", Reading("scam", DELIVERY)),
        ("scam/other_scam", Reading("scam", "other_scam")),
        ("scam", Reading("scam")),
        ("legit", Reading("legit")),
        ("ambiguous", Reading("ambiguous")),
    ],
)
def test_a_reading_is_written_the_way_the_contract_writes_it(text, reading):
    assert parse_reading(text) == reading
    assert str(reading) == text


@pytest.mark.parametrize(
    "text, message",
    [
        ("unsure", "label must be one of"),
        ("legit/kz.delivery_link", "only with `scam`"),
        ("scam/kz.no_such_script", "unknown script"),
        ("", "expected a reading"),
        (None, "expected a reading"),
    ],
)
def test_a_reading_outside_the_label_set_is_refused(text, message):
    with pytest.raises(LabelError, match=message):
        parse_reading(text, "row 7")


def test_the_scripts_are_the_thirteen_playbooks_and_other_scam():
    assert len(labels.SCRIPTS) == 14
    assert labels.SCRIPTS[-1] == labels.OTHER_SCAM


# ---------------------------------------------------------------------------
# the resolution table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a, b",
    [
        (Reading("scam", DELIVERY), Reading("scam", DELIVERY)),
        (Reading("scam"), Reading("scam")),
        (Reading("legit"), Reading("legit")),
        (Reading("ambiguous"), Reading("ambiguous")),
    ],
)
def test_two_equal_readings_are_the_label_and_nobody_decides(a, b):
    assert difference(a, b) is None
    gold = resolve(a, b)
    assert (gold.label, gold.playbook_id, gold.adjudicated) == (a.label, a.script, False)
    assert gold.reason is None and gold.decided_by is None
    with pytest.raises(LabelError, match="nothing to decide"):
        resolve(a, b, decision())


@pytest.mark.parametrize(
    "a, b, on",
    [
        (Reading("scam", DELIVERY), Reading("legit"), "verdict"),
        (Reading("ambiguous"), Reading("legit"), "verdict"),
        (Reading("scam", DELIVERY), Reading("scam", STORE), "script"),
        # One annotator named a script and the other stopped at "scam": a
        # single person chose the script, so it is not agreed.
        (Reading("scam", DELIVERY), Reading("scam"), "script"),
    ],
)
def test_any_difference_needs_a_logged_decision(a, b, on):
    assert difference(a, b) == on
    with pytest.raises(LabelError, match=f"differ on the {on}"):
        resolve(a, b)
    gold = resolve(a, b, decision())
    assert (gold.label, gold.playbook_id, gold.adjudicated) == ("scam", DELIVERY, True)
    assert (gold.reason, gold.decided_by) == (WHY, DISCUSSION)


def test_a_decision_may_be_a_label_neither_annotator_gave_and_may_leave_the_script_open():
    a, b = Reading("scam", DELIVERY), Reading("legit")
    assert resolve(a, b, decision("ambiguous", None)).label == "ambiguous"
    open_script = resolve(Reading("scam", DELIVERY), Reading("scam", STORE), decision("scam", None))
    assert (open_script.label, open_script.playbook_id) == ("scam", None)


@pytest.mark.parametrize(
    "made, message",
    [
        (decision(reason="  "), "needs a reason"),
        (decision(reason="first line\nsecond line"), "one line"),
        (decision(decided_by=""), "names who made it"),
        (decision("legit", DELIVERY), "only with `scam`"),
        (decision("scam", "kz.no_such_script"), "unknown script"),
        (decision("unsure", None), "label must be one of"),
    ],
)
def test_a_decision_without_a_reason_a_name_or_a_valid_label_is_refused(made, message):
    with pytest.raises(LabelError, match=message):
        resolve(Reading("scam", DELIVERY), Reading("legit"), made, where="ks-x-001")


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------

DIGEST = "ab" * 32


def a_record(rows=None, **kw) -> dict:
    rows = rows or [
        make_row("ks-x-002", DIGEST, Reading("scam", DELIVERY), Reading("scam", STORE), decision()),
        make_row("ks-x-001", DIGEST, Reading("legit"), Reading("legit")),
    ]
    return record_payload(
        batch=kw.pop("batch", "batch-annot-01"),
        created_at="2027-01-15",
        annotators=kw.pop("annotators", ("annotator-1", "annotator-2")),
        rows=rows,
        **kw,
    )


def write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_a_record_has_the_contract_shape_and_reads_back(tmp_path):
    payload = a_record(not_labelled=["ks-x-009", "ks-x-009"])
    assert list(payload) == [
        "schema",
        "batch",
        "created_at",
        "kind",
        "annotators",
        "rows",
        "not_labelled",
    ]
    assert payload["schema"] == "kazscam-labels/1"
    assert payload["kind"] == "inter-annotator"
    assert payload["annotators"] == {"a": "annotator-1", "b": "annotator-2"}
    assert payload["not_labelled"] == ["ks-x-009"]
    # Rows are in corpus-id order; only a decided row carries a reason.
    assert payload["rows"] == [
        {
            "corpus_id": "ks-x-001",
            "text_sha256": DIGEST,
            "annotator_a": "legit",
            "annotator_b": "legit",
            "label": "legit",
            "playbook_id": None,
            "adjudicated": False,
        },
        {
            "corpus_id": "ks-x-002",
            "text_sha256": DIGEST,
            "annotator_a": "scam/kz.delivery_link",
            "annotator_b": "scam/kz.fake_store",
            "label": "scam",
            "playbook_id": DELIVERY,
            "adjudicated": True,
            "reason": WHY,
            "decided_by": DISCUSSION,
        },
    ]
    record = read_record(write(tmp_path / "r.json", payload))
    assert record.batch == "batch-annot-01"
    assert [row.to_json() for row in record.rows] == payload["rows"]


@pytest.mark.parametrize(
    "edit, message",
    [
        # A label typed over the readings, with nothing logged.
        (lambda row: row.update(label="scam", playbook_id=DELIVERY), "the readings"),
        (lambda row: row.update(adjudicated=True), "nothing to decide"),
        (lambda row: row.update(annotator_b="scam"), "no decision"),
        (lambda row: row.update(text_sha256="abc"), "SHA-256"),
        (lambda row: row.pop("adjudicated"), "true or false"),
        (lambda row: row.pop("corpus_id"), "no corpus_id"),
    ],
)
def test_a_record_edited_by_hand_into_something_the_rule_does_not_give_is_refused(
    tmp_path, edit, message
):
    payload = a_record()
    edit(payload["rows"][0])
    with pytest.raises(LabelError, match=message):
        read_record(write(tmp_path / "r.json", payload))


def test_a_record_needs_its_schema_two_annotators_and_a_known_kind(tmp_path):
    with pytest.raises(LabelError, match="two different annotators"):
        a_record(annotators=("annotator-1", "annotator-1"))
    with pytest.raises(LabelError, match="names each row once"):
        a_record(rows=[make_row("ks-x-001", DIGEST, Reading("legit"), Reading("legit"))] * 2)
    with pytest.raises(LabelError, match="one of"):
        a_record(kind="self-annotated")

    wrong_schema = {**a_record(), "schema": "kazscam-pilot-key/1"}
    with pytest.raises(LabelError, match="not a label record"):
        read_record(write(tmp_path / "a.json", wrong_schema))
    (tmp_path / "b.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(LabelError, match="not JSON"):
        read_record(tmp_path / "b.json")
    with pytest.raises(LabelError, match="kind must be"):
        read_record(write(tmp_path / "c.json", {**a_record(), "kind": "self-annotated"}))

    # A record from before the field existed is two people's readings.
    older = a_record()
    del older["kind"]
    assert read_record(write(tmp_path / "d.json", older)).kind == "inter-annotator"


def test_a_directory_of_records_is_read_whole_and_a_row_in_two_of_them_is_an_error(tmp_path):
    first = [make_row("ks-x-001", DIGEST, Reading("legit"), Reading("legit"))]
    second = [make_row("ks-x-002", DIGEST, Reading("scam"), Reading("scam"))]
    write(tmp_path / "labels" / "batch-01.json", a_record(first, batch="batch-01"))
    write(tmp_path / "labels" / "batch-02.json", a_record(second, batch="batch-02", kind=INTRA))

    found = load_records(tmp_path / "labels")
    assert sorted(found.rows) == ["ks-x-001", "ks-x-002"]
    assert found.files == ("batch-01.json", "batch-02.json")
    assert found.intra == frozenset({"ks-x-002"})

    write(tmp_path / "labels" / "batch-03.json", a_record(first, batch="batch-03"))
    with pytest.raises(LabelError, match="ks-x-001 is labelled in both"):
        load_records(tmp_path / "labels")
    with pytest.raises(FileNotFoundError):
        load_records(tmp_path / "nowhere")


# ---------------------------------------------------------------------------
# the split builder
# ---------------------------------------------------------------------------


def label_for(row: dict, a: str, b: str, made: Decision | None = None):
    """A label-record row for a corpus row, keyed by the digest of its released text."""
    return make_row(
        str(row["id"]),
        text_sha256(str(row["text"]).strip()),
        parse_reading(a),
        parse_reading(b),
        made,
    )


def by_corpus_id(build) -> dict[str, dict]:
    return {row["corpus_id"]: row for rows in build.splits.values() for row in rows}


def labelled_corpus() -> tuple[list[dict], dict]:
    rows = filler(12)
    rows.append(corpus_row("ks-neg-001", "Kaspi: код 4821. Никому не сообщайте.", label="legit"))
    rows[-1]["hard_negative"] = True
    made = {
        "ks-f-000": label_for(rows[0], "scam/kz.delivery_link", "scam/kz.delivery_link"),
        "ks-f-001": label_for(rows[1], "scam/kz.delivery_link", "legit", decision("legit", None)),
        "ks-f-002": label_for(rows[2], "scam", "scam"),
        "ks-neg-001": label_for(rows[-1], "legit", "ambiguous", decision("ambiguous", None)),
    }
    return rows, made


def test_a_labelled_row_is_released_with_the_readings_and_the_label_that_follows():
    rows, made = labelled_corpus()
    build = assemble(rows, seed=3, labels=made)
    out = by_corpus_id(build)

    agreed = out["ks-f-000"]
    assert (agreed["label"], agreed["playbook_id"], agreed["adjudicated"]) == (
        "scam",
        DELIVERY,
        False,
    )
    assert agreed["annotator_a"] == agreed["annotator_b"] == "scam/kz.delivery_link"
    assert agreed["stage"] is None

    decided = out["ks-f-001"]
    assert (decided["label"], decided["playbook_id"], decided["adjudicated"]) == (
        "legit",
        None,
        True,
    )
    assert (decided["annotator_a"], decided["annotator_b"]) == ("scam/kz.delivery_link", "legit")

    # "Scam", with no script named by either: the script stays open.
    assert out["ks-f-002"]["playbook_id"] is None

    # An unlabelled row keeps the collector's reading and null annotator fields.
    untouched = out["ks-f-005"]
    assert untouched["label"] == "scam"
    assert untouched["annotator_a"] is None and untouched["annotator_b"] is None

    report = build.report["labels"]
    assert report["label_differs_from_collection"] == [
        {"corpus_id": "ks-f-001", "collected_as": "scam", "label": "legit"},
        {"corpus_id": "ks-neg-001", "collected_as": "legit", "label": "ambiguous"},
    ]
    assert sum(t["two_readings"] for t in report["by_split"].values()) == 4
    assert sum(t["adjudicated"] for t in report["by_split"].values()) == 2
    assert sum(t["collection_label"] for t in report["by_split"].values()) == 9


def test_a_hard_negative_the_annotators_did_not_call_legit_loses_the_flag():
    rows, made = labelled_corpus()
    build = assemble(rows, seed=3, labels=made)
    row = by_corpus_id(build)["ks-neg-001"]
    assert row["label"] == "ambiguous"
    assert row["hard_negative"] is False
    assert build.report["labels"]["hard_negative_flag_dropped"] == ["ks-neg-001"]

    kept = {"ks-neg-001": label_for(rows[-1], "legit", "legit")}
    assert by_corpus_id(assemble(rows, seed=3, labels=kept))["ks-neg-001"]["hard_negative"] is True


def test_a_label_does_not_follow_a_text_that_changed_after_it_was_read():
    rows, made = labelled_corpus()
    rows[0]["text"] = rows[0]["text"] + " Срочно!"
    with pytest.raises(CorpusError, match="ks-f-000: the text is not the one that was labelled"):
        assemble(rows, seed=3, labels=made)


def test_a_label_for_a_row_the_corpus_does_not_have_is_reported_not_dropped_silently():
    rows, made = labelled_corpus()
    made["ks-gone-001"] = make_row("ks-gone-001", DIGEST, Reading("legit"), Reading("legit"))
    report = assemble(rows, seed=3, labels=made).report["labels"]
    assert report["records_without_a_message_row"] == ["ks-gone-001"]


def test_labels_change_no_assignment_and_no_released_id():
    rows, made = labelled_corpus()
    plain = assemble(rows, seed=3)
    with_labels = assemble(rows, seed=3, labels=made)
    for name, split in plain.splits.items():
        assert [r["id"] for r in split] == [r["id"] for r in with_labels.splits[name]]


def test_require_labels_leaves_unread_rows_out_of_every_split_but_dev():
    fresh = filler(10, prefix="new")
    old = filler(4, prefix="old", start=50)
    made = {
        str(row["id"]): label_for(row, "scam/kz.delivery_link", "scam/kz.delivery_link")
        for row in fresh[:6]
    }
    exposed = [str(row["id"]) for row in old]
    build = assemble([*fresh, *old], seed=3, exposed_ids=exposed, labels=made, require_labels=True)

    assert len(build.splits["dev"]) == 4
    held_out = [r for name in ("calibration", "test_press") for r in build.splits[name]]
    assert sorted(r["corpus_id"] for r in held_out) == sorted(made)
    assert all(r["annotator_a"] and r["annotator_b"] for r in held_out)
    assert build.report["labels"]["left_out_unlabelled"] == sorted(
        str(row["id"]) for row in fresh[6:]
    )
    assert build.report["labels"]["require_labels"] is True

    # Without the flag the same rows are released on the collector's label.
    lax = assemble([*fresh, *old], seed=3, exposed_ids=exposed, labels=made)
    assert sum(len(lax.splits[name]) for name in ("calibration", "test_press")) == 10
    assert lax.report["labels"]["left_out_unlabelled"] == []


def test_a_group_that_loses_its_first_row_is_named_after_a_row_it_still_has():
    # Two renderings of one notice travel together; only the second was read.
    pair = [
        corpus_row(
            "ks-new-001", "Сіздің сәлемдемеңіз кедергіге ұшырады", lang="kk", notes="pair:p1"
        ),
        corpus_row("ks-new-002", "Ваша посылка задержана на таможне", notes="pair:p1"),
    ]
    made = {"ks-new-002": label_for(pair[1], "scam/kz.delivery_link", "scam/kz.delivery_link")}
    build = assemble(pair, seed=3, labels=made, require_labels=True)
    released = [row for rows in build.splits.values() for row in rows]
    assert [row["corpus_id"] for row in released] == ["ks-new-002"]
    assert released[0]["source_group"] == released[0]["id"]


def _cli(tmp_path: Path, rows: list[dict], made: dict, *extra: str, kind: str = "inter-annotator"):
    corpus = tmp_path / "corpus"
    _write_corpus(corpus, rows)
    if made:
        write(
            tmp_path / "labels" / "batch-annot-01.json",
            a_record(list(made.values()), kind=kind),
        )
    out = tmp_path / "kazscam"
    argv = ["splits", "--corpus", str(corpus), "--out", str(out), "--seed", "5", *extra]
    code = main(argv)
    return code, out


def test_the_cli_reads_the_records_beside_the_corpus_and_says_what_is_still_unread(
    tmp_path, capsys
):
    rows, made = labelled_corpus()
    code, out = _cli(tmp_path, rows, made)
    assert code == 0
    printed = capsys.readouterr().out
    assert "labels (provisional): 4 of 13 rows carry two readings, 1 label records read" in printed

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "provisional"
    assert manifest["labels"]["records"] == ["batch-annot-01.json"]
    assert manifest["labels"]["directory"].endswith("labels")
    assert manifest["labels"]["two_passes_by_one_annotator"] == []
    assert manifest["notes"][0].startswith("PROVISIONAL: 4 of 13 rows")

    readme = (out / "README.md").read_text(encoding="utf-8")
    assert readme.splitlines()[0].startswith(
        "PROVISIONAL splits: 4 of 13 rows carry two annotators' readings"
    )
    assert "## Labels" in readme
    assert "2 rows were released with a label other than the one they were collected" in readme
    assert "1 rows collected as hard negatives were not labelled `legit`" in readme

    # The harness reads the readings, and counts the rows that have both.
    loaded = [
        row for name in ("test_press", "calibration") for row in load_split(out / f"{name}.jsonl")
    ]
    assert count_support(loaded)["n_double_annotated"] == 4


def test_a_build_is_annotated_only_when_every_released_row_was_read_twice(tmp_path, capsys):
    rows = filler(8)
    made = {str(r["id"]): label_for(r, "scam", "scam") for r in rows}
    code, out = _cli(tmp_path, rows, made)
    assert code == 0
    assert "labels (annotated): 8 of 8 rows carry two readings" in capsys.readouterr().out
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "annotated"
    assert manifest["notes"][0].startswith("Every row carries two annotators' readings")
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert readme.splitlines()[0] == "# KazScam v0.1 splits"
    assert "PROVISIONAL" not in readme
    assert "8 of 8 rows carry two annotators' readings" in readme


def test_require_labels_on_the_command_line_builds_an_annotated_release_from_a_part(
    tmp_path, capsys
):
    rows = filler(8)
    made = {str(r["id"]): label_for(r, "scam", "scam") for r in rows[:5]}
    code, out = _cli(tmp_path, rows, made, "--require-labels")
    assert code == 0
    printed = capsys.readouterr().out
    assert "labels (annotated): 5 of 5 rows carry two readings" in printed
    assert "3 rows without a label were left out" in printed
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["labels"]["left_out_unlabelled"]) == 3
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "--require-labels" in readme
    assert "3 rows outside `dev` had no label record and were left out" in readme
    assert sum(len(read_split(out / f"{n}.jsonl")) for n in ("calibration", "test_press")) == 5


def test_two_passes_by_one_person_are_never_reported_as_two_annotators(tmp_path, capsys):
    rows = filler(6)
    made = {str(r["id"]): label_for(r, "scam", "scam") for r in rows}
    code, out = _cli(tmp_path, rows, made, kind=INTRA)
    assert code == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["labels"]["two_passes_by_one_annotator"] == sorted(made)
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "On 6 rows the two readings are two passes by one annotator" in readme
    assert "agreement between annotators was not measured on them" in readme


def test_the_cli_stops_on_a_record_that_does_not_fit_the_corpus(tmp_path, capsys):
    rows, made = labelled_corpus()
    rows[0]["text"] = "Текст изменили после разметки."
    code, _ = _cli(tmp_path, rows, made)
    assert code != 0
    assert "the text is not the one that was labelled" in capsys.readouterr().err


def test_an_explicit_label_directory_must_exist(tmp_path, capsys):
    rows, _ = labelled_corpus()
    code, _ = _cli(tmp_path, rows, {}, "--labels", str(tmp_path / "nowhere"))
    assert code != 0
    assert "label directory not found" in capsys.readouterr().err
