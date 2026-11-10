"""The collector's screening against development data.

`tools/collect.py` is the only door into the corpus, so it is where the
holdout policy has to bite first: a row that repeats, rewords or shares an
article with something the system was built on must not arrive looking like a
test row, and nothing collected before the freeze tag can be one at all.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from saqbol.eval import splits

REPO = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("kazscam_collect", REPO / "tools" / "collect.py")
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)

DEV_URL = "https://example.kz/news/fake-kaspi-sms"
DEV_TEXT = (
    "Kaspi Bank: с вашей карты списано 45 000 тг. Если это были не вы, "
    "срочно позвоните по номеру службы безопасности и назовите код из SMS."
)
# The same message with the amount and the last clause changed.
REWORDED = (
    "Kaspi Bank: с вашей карты списано 80 000 тг. Если это были не вы, "
    "срочно позвоните по номеру службы безопасности банка."
)
UNRELATED = (
    "Сәлеметсіз бе! Сіздің сәлемдемеңіз қоймада күтіп тұр, мекенжайды "
    "растау үшін сілтемеге өтіңіз, әйтпесе ол кері қайтарылады."
)
OTHER = (
    "Поздравляем, вы выиграли автомобиль в розыгрыше от магазина. Чтобы забрать "
    "приз, оплатите доставку и налог по ссылке в течение суток."
)


def draft(text: str, url: str = "https://other.kz/a/1", **extra: object) -> dict:
    return {
        "text": text,
        "source_url": url,
        "provenance": "press",
        "lang": "ru",
        "label": "scam",
        "access_date": "2026-12-05",
        **extra,
    }


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """A corpus of one development batch, frozen an hour ago."""
    root = tmp_path
    corpus_dir = root / "data" / "corpus"
    corpus_dir.mkdir(parents=True)
    monkeypatch.setattr(collect, "ROOT", root)
    monkeypatch.setattr(collect, "CORPUS_DIR", corpus_dir)
    monkeypatch.setattr(collect, "EXPOSURE_PATH", root / "data" / "exposure.json")
    frozen = datetime.now(UTC) - timedelta(hours=1)
    monkeypatch.setattr(collect, "freeze_time", lambda: frozen)

    old = collect.make_row(
        **draft(DEV_TEXT, DEV_URL, notes="Variant group key: kaspi-debit-2026"),
    )
    old["id"] = "ks-press-01-001"
    old["collected_at"] = "2026-09-01T10:00:00+00:00"
    (corpus_dir / "batch-press-01.json").write_text(
        json.dumps({"batch": "press-01", "items": [old]}, ensure_ascii=False), encoding="utf-8"
    )
    collect.EXPOSURE_PATH.write_text(
        json.dumps({"exposed_batches": ["press-01"], "exposed_ids": [], "log": []}),
        encoding="utf-8",
    )
    return root


def ingest(root: Path, drafts: list[dict], batch: str = "press-03", *flags: str) -> int:
    staging = root / "staging.json"
    staging.write_text(json.dumps(drafts, ensure_ascii=False), encoding="utf-8")
    return collect.main(["ingest", str(staging), "--batch", batch, *flags])


def batch_rows(root: Path, batch: str = "press-03") -> list[dict]:
    path = root / "data" / "corpus" / f"batch-{batch}.json"
    return json.loads(path.read_text(encoding="utf-8"))["items"] if path.exists() else []


def register(root: Path) -> dict:
    return json.loads((root / "data" / "exposure.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# the two copies of the grouping keys agree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.Example.kz/News/1/",
        "http://example.kz/news/1#comments",
        "example.kz/news/1",
        "https://example.kz/news/1?page=2",
        "",
        None,
    ],
)
def test_the_collector_and_the_split_builder_name_a_source_the_same_way(url):
    assert collect.source_key(url) == splits.source_key(url)


@pytest.mark.parametrize(
    "notes",
    [
        "Parallel pair key: bcc-maint-2026-05-12 (RU). Verified.",
        "variant GROUP key: Kazpost_SMS.2 and Parallel pair key: a-b",
        "no key here",
        "",
    ],
)
def test_the_collector_and_the_split_builder_read_the_same_keys(notes):
    assert collect.group_keys(notes) == splits.group_keys(notes)


def test_the_collector_and_the_split_builder_score_similarity_alike():
    assert collect.similarity(DEV_TEXT, REWORDED) == pytest.approx(
        splits.similarity(DEV_TEXT, REWORDED)
    )
    assert collect.NEAR_DUP_THRESHOLD == splits.NEAR_DUP_THRESHOLD


# ---------------------------------------------------------------------------
# screening
# ---------------------------------------------------------------------------


def test_the_fixture_texts_sit_where_the_tests_need_them():
    """Guards the fixtures: one pair in the review band, the rest well below it."""
    score = collect.similarity(DEV_TEXT, REWORDED)
    assert collect.REVIEW_THRESHOLD <= score < collect.NEAR_DUP_THRESHOLD
    for text in (UNRELATED, OTHER):
        assert collect.similarity(DEV_TEXT, text) < collect.REVIEW_THRESHOLD


def test_a_new_message_unlike_anything_known_is_a_candidate_test_row(corpus):
    assert ingest(corpus, [draft(UNRELATED)]) == 0
    (row,) = batch_rows(corpus)
    assert row["screening"] == {"pool": "fresh"}
    assert register(corpus)["exposed_ids"] == []


def test_a_row_from_an_article_already_read_is_development_data(corpus):
    assert ingest(corpus, [draft(UNRELATED, DEV_URL.replace("https://", "http://www.") + "/")]) == 0
    (row,) = batch_rows(corpus)
    assert row["screening"] == {
        "pool": "dev",
        "rule": "same_source",
        "dev_id": "ks-press-01-001",
    }


def test_a_row_sharing_a_variant_key_with_a_development_row_is_development_data(corpus):
    assert ingest(corpus, [draft(UNRELATED, notes="variant group key: KASPI-debit-2026")]) == 0
    (row,) = batch_rows(corpus)
    assert row["screening"]["pool"] == "dev"
    assert row["screening"]["rule"] == "shared_key"
    assert row["screening"]["key"] == "kaspi-debit-2026"


def test_a_reworded_copy_is_refused_until_someone_rules_on_it(corpus, capsys):
    assert ingest(corpus, [draft(REWORDED), draft(UNRELATED, "https://other.kz/a/2")]) == 1
    # The undecided draft is left out; the clean one beside it still lands.
    assert [r["text"] for r in batch_rows(corpus)] == [UNRELATED]
    err = capsys.readouterr().err
    assert "needs a decision" in err
    assert "ks-press-01-001" in err


def test_ruling_variant_makes_the_row_development_data_in_the_register(corpus):
    assert ingest(corpus, [draft(REWORDED, similar_to_dev="variant")]) == 0
    (row,) = batch_rows(corpus)
    assert row["screening"]["pool"] == "dev"
    assert row["screening"]["decision"] == "variant"
    reg = register(corpus)
    assert reg["exposed_ids"] == [row["id"]]
    assert reg["exposed_batches"] == ["press-01"]
    assert "ks-press-01-001" in reg["log"][-1]["reason"]
    assert row["id"] in reg["log"][-1]["scope"]


def test_ruling_distinct_keeps_the_row_and_records_the_ruling(corpus):
    assert ingest(corpus, [draft(REWORDED, similar_to_dev="distinct")]) == 0
    (row,) = batch_rows(corpus)
    assert row["screening"]["pool"] == "fresh"
    assert row["screening"]["decision"] == "distinct"
    assert row["screening"]["dev_id"] == "ks-press-01-001"
    assert register(corpus)["exposed_ids"] == []


def test_an_unknown_ruling_is_an_invalid_draft(corpus):
    assert ingest(corpus, [draft(REWORDED, similar_to_dev="probably fine")]) == 1
    assert batch_rows(corpus) == []


def test_a_copy_of_a_development_row_is_still_refused_as_a_duplicate(corpus):
    assert ingest(corpus, [draft(DEV_TEXT.upper())]) == 0
    assert batch_rows(corpus) == []


def test_add_takes_the_ruling_on_the_command_line(corpus):
    base = [
        "add",
        "--text",
        REWORDED,
        "--url",
        "https://other.kz/a/1",
        "--provenance",
        "press",
        "--lang",
        "ru",
        "--label",
        "scam",
        "--batch",
        "press-03",
    ]
    assert collect.main(base) == 2
    assert batch_rows(corpus) == []
    assert collect.main([*base, "--similar-to-dev", "variant"]) == 0
    (row,) = batch_rows(corpus)
    assert register(corpus)["exposed_ids"] == [row["id"]]


# ---------------------------------------------------------------------------
# the freeze
# ---------------------------------------------------------------------------


def test_before_the_freeze_tag_a_new_batch_is_refused_unless_collected_as_dev(corpus, monkeypatch):
    monkeypatch.setattr(collect, "freeze_time", lambda: None)
    assert ingest(corpus, [draft(UNRELATED)]) == 2
    assert batch_rows(corpus) == []

    assert ingest(corpus, [draft(UNRELATED)], "press-03", "--dev") == 0
    (row,) = batch_rows(corpus)
    assert row["screening"] == {"pool": "dev", "rule": "dev_batch"}
    reg = register(corpus)
    assert reg["exposed_batches"] == ["press-01", "press-03"]
    assert "press-03" in reg["log"][-1]["scope"]


def test_adding_to_a_registered_batch_needs_no_flag_and_no_ruling(corpus, monkeypatch):
    monkeypatch.setattr(collect, "freeze_time", lambda: None)
    assert ingest(corpus, [draft(REWORDED)], "press-01") == 0
    assert len(batch_rows(corpus, "press-01")) == 2
    assert register(corpus)["log"] == []


def test_check_passes_a_corpus_collected_after_the_freeze(corpus, capsys):
    assert ingest(corpus, [draft(UNRELATED), draft(OTHER, DEV_URL)]) == 0
    assert collect.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "1 development rows, 2 candidate test rows" in out
    assert "1 of them tied to development data" in out


def test_check_fails_a_candidate_batch_when_there_is_no_freeze_tag(corpus, monkeypatch, capsys):
    assert ingest(corpus, [draft(UNRELATED)]) == 0
    monkeypatch.setattr(collect, "freeze_time", lambda: None)
    assert collect.main(["check"]) == 1
    assert "batch press-03" in capsys.readouterr().out


def test_check_fails_a_candidate_row_collected_before_the_freeze(corpus, monkeypatch, capsys):
    assert ingest(corpus, [draft(UNRELATED)]) == 0
    later = datetime.now(UTC) + timedelta(hours=1)
    monkeypatch.setattr(collect, "freeze_time", lambda: later)
    assert collect.main(["check"]) == 1
    assert "collected before" in capsys.readouterr().out


def test_check_fails_a_lookalike_that_reached_the_corpus_without_a_ruling(corpus, capsys):
    assert ingest(corpus, [draft(REWORDED, similar_to_dev="distinct")]) == 0
    assert collect.main(["check"]) == 0

    path = corpus / "data" / "corpus" / "batch-press-03.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["items"][0]["screening"]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert collect.main(["check"]) == 1
    assert "no decision recorded" in capsys.readouterr().out


def test_the_real_register_and_corpus_pass_the_pool_check():
    """The corpus as it stands: every batch is development data, so nothing is a test row."""
    reg = collect.load_register()
    rows = collect.load_all_rows()
    if not rows:
        pytest.skip("no corpus in this checkout")
    assert all(collect.is_dev(row, reg) for row in rows)
