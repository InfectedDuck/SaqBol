"""T408 — the split builder, and the leakage rules over the released files.

The first half exercises `saqbol.eval.splits` on small synthetic corpora in
the `tools/collect.py` row shape: fragments are excluded, rows that must
travel together do, exposed rows go to `dev` and take their group and their
article with them, donated rows are held out, calibration follows the
contract's rule or a capped manual size, the same seed gives the same files,
and every emitted row is one the harness's `DatasetRow` accepts.

The second half is the CI gate docs/05_EVAL_PROTOCOL.md section 8 asks for,
run over whatever is actually in `data/kazscam_v0.1/`: no `text_sha256` in
two splits, no synthetic row derived from a test row, calibration disjoint
from every test split, no source article or near-duplicate pair straddling
two splits, and no row from the exposure register outside `dev`. These skip
with a reason when the directory does not exist, so a checkout without built
splits still passes, and fail the build the moment a leak is written.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
from pathlib import Path

import pytest

from saqbol.eval import splits
from saqbol.eval.__main__ import main
from saqbol.eval.run import DatasetRow, load_split
from saqbol.eval.splits import (
    CALIBRATION_MAX_ROWS,
    CALIBRATION_MIN_POOL,
    CALIBRATION_MIN_ROWS,
    NEAR_DUP_THRESHOLD,
    ROW_FIELDS,
    SPLIT_NAMES,
    CorpusError,
    assemble,
    build_splits,
    exposed_corpus_ids,
    group_keys,
    group_rows,
    load_exposure,
    normalize_text,
    policy_calibration_size,
    read_split,
    similarity,
    source_key,
    text_sha256,
    to_released_row,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SPLIT_DIR = REPO_ROOT / "data" / "kazscam_v0.1"
CORPUS_DIR = REPO_ROOT / "data" / "corpus"
EXPOSURE_FILE = REPO_ROOT / "data" / "exposure.json"
COLLECT_PY = REPO_ROOT / "tools" / "collect.py"

TEST_SPLITS = ("test_press", "test_donated")
HELD_OUT_SPLITS = ("calibration", "test_press", "test_donated")
SEEDS = (1, 2, 3, 20260908, 4242)


# ---------------------------------------------------------------------------
# Synthetic corpora
# ---------------------------------------------------------------------------


def corpus_row(
    row_id: str,
    text: str,
    *,
    lang: str = "ru",
    label: str = "scam",
    provenance: str = "press",
    text_kind: str = "message",
    hard_negative: bool = False,
    notes: str = "",
    channel: str = "sms",
    **extra: object,
) -> dict[str, object]:
    """One row in the shape `tools/collect.py` writes after scrubbing."""
    row: dict[str, object] = {
        "id": row_id,
        "text": text,
        "source": provenance,
        "provenance": provenance,
        "source_url": "" if provenance == "donated" else f"https://example.kz/{row_id}",
        "source_title": "",
        "publisher": "example.kz",
        "access_date": "2026-09-08",
        "lang": lang,
        "is_code_switched": lang == "kk-ru",
        "label": label,
        "hard_negative": hard_negative,
        "channel": channel,
        "verbatim": True,
        "text_kind": text_kind,
        "pii_flags": [],
        "needs_scrub": False,
        "scrub_applied": True,
        "scrub_placeholders": [],
        "text_hash": "0" * 16,
        "collected_at": "2026-09-08T12:00:00+00:00",
        "notes": notes,
    }
    row.update(extra)
    return row


def filler(
    n: int, *, prefix: str = "f", lang: str = "ru", label: str = "scam", start: int = 0
) -> list[dict]:
    """`n` mutually dissimilar message rows, so the sampler has something to choose from.

    The text depends only on the row's number, so two calls that must not
    share a message need ranges that do not overlap: pass `start`.
    """
    rows = []
    for i in range(start, start + n):
        # Each text is a distinct sentence built from a distinct number so no
        # two share enough character shingles to count as near-duplicates.
        text = (
            f"Сообщение номер {i * 7919 + 13}: ваш заказ {i * 104729 + 1} оформлен, "
            f"код {i * 31 + 7} действителен {i % 9 + 1} минут."
        )
        rows.append(corpus_row(f"ks-{prefix}-{i:03d}", text, lang=lang, label=label))
    return rows


def where(split_of: dict[str, str], corpus_id: str) -> str:
    return split_of[corpus_id]


def split_index(result: dict[str, list[dict]]) -> dict[str, str]:
    """corpus_id -> split name."""
    return {row["corpus_id"]: name for name, rows in result.items() for row in rows}


# ---------------------------------------------------------------------------
# Normalization mirrors the collector
# ---------------------------------------------------------------------------


def _load_collect():
    spec = importlib.util.spec_from_file_location("collect", COLLECT_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not COLLECT_PY.is_file(), reason="tools/collect.py is not in this checkout")
def test_normalization_and_similarity_match_tools_collect():
    collect = _load_collect()
    samples = [
        "Здравствуйте! Это служба безопасности Kaspi... Срочно позвоните: +7 700 000 00 00",
        "Сіздің картаңыз бұғатталды. Сілтеме: https://kaspi-bank.site/unlock",
        "Ваша посылка задержана на складе, оплатите 350 тг по ссылке www.kazpost-kz.top/pay",
        "Кратко",
        "",
    ]
    assert collect.NEAR_DUP_THRESHOLD == NEAR_DUP_THRESHOLD
    for text in samples:
        assert normalize_text(text) == collect.normalize_text(text)
    for a, b in itertools.combinations(samples, 2):
        assert similarity(a, b) == pytest.approx(collect.similarity(a, b))


def test_group_keys_read_both_spellings_case_insensitively():
    notes = (
        "GENUINE notice. Parallel pair key: bcc-maint-2026-05-12 (RU). Verified against raw HTML."
    )
    assert group_keys(notes) == ["bcc-maint-2026-05-12"]
    assert group_keys("variant group key: Kazpost-Parcel-KK — keep together") == [
        "kazpost-parcel-kk"
    ]
    assert group_keys("parallel pair key: a-1; Variant Group Key: b.2") == ["a-1", "b.2"]
    assert group_keys("nothing to see") == []
    assert group_keys("") == []


# ---------------------------------------------------------------------------
# Eligibility and grouping
# ---------------------------------------------------------------------------


def test_fragments_never_enter_a_split():
    rows = [
        *filler(12),
        corpus_row("ks-frag-1", "картаңыз бұғатталды", lang="kk", text_kind="phrase_fragment"),
        corpus_row("ks-frag-2", "Оформлена заявка на кредит", text_kind="phrase_fragment"),
    ]
    build = assemble(rows, seed=1)
    released = {row["corpus_id"] for split in build.splits.values() for row in split}
    assert "ks-frag-1" not in released
    assert "ks-frag-2" not in released
    assert build.report["excluded_fragments"] == 2
    assert build.report["eligible_rows"] == 12
    assert sum(len(s) for s in build.splits.values()) == 12


@pytest.mark.parametrize("seed", SEEDS)
def test_a_parallel_pair_never_splits(seed):
    pair = [
        corpus_row(
            "ks-pair-ru",
            "С вашего счёта пытаются списать деньги, назовите код из SMS.",
            lang="ru",
            notes="Parallel pair key: vishing-7 (RU). Verified.",
        ),
        corpus_row(
            "ks-pair-kk",
            "Сіздің шотыңыздан ақша шығарылмақшы, SMS кодын айтыңыз.",
            lang="kk",
            notes="parallel pair key: vishing-7 (KK)",
        ),
    ]
    variants = [
        corpus_row(
            "ks-var-a",
            "Сіздің пакетіңіз қоймаға келді, мекенжайды толықтырыңыз.",
            lang="kk",
            notes="Variant group key: kazpost-parcel-kk — baq.kz row shares the first sentence",
        ),
        corpus_row(
            "ks-var-b",
            "Сіздің пакетіңіз қоймаға келді. Жеткізу үшін төмендегі сілтеме бойынша "
            "толық мекенжайыңызды және телефон нөміріңізді енгізіңіз.",
            lang="kk",
            notes="variant group key: kazpost-parcel-kk",
        ),
    ]
    rows = filler(20) + pair + variants
    result = build_splits(rows, seed=seed, calibration_size=10)
    index = split_index(result)
    assert where(index, "ks-pair-ru") == where(index, "ks-pair-kk")
    assert where(index, "ks-var-a") == where(index, "ks-var-b")


@pytest.mark.parametrize("seed", SEEDS)
def test_near_duplicates_never_split(seed):
    base = (
        "Уважаемый клиент! Ваша карта заблокирована из-за подозрительной операции на сумму "
        "48 500 тенге. Для разблокировки в течение 30 минут перейдите по ссылке, подтвердите "
        "данные и введите код из SMS, иначе средства будут списаны безвозвратно. "
        "Служба безопасности банка."
    )
    reprint = base.replace("30 минут", "20 минут")
    assert similarity(base, reprint) >= NEAR_DUP_THRESHOLD
    same_normalized = base.upper().replace(",", " ,") + "!!!"
    assert normalize_text(same_normalized) == normalize_text(base)
    rows = [
        *filler(20),
        corpus_row("ks-dup-a", base),
        corpus_row("ks-dup-b", reprint),
        corpus_row("ks-dup-c", same_normalized),
    ]
    result = build_splits(rows, seed=seed, calibration_size=10)
    index = split_index(result)
    assert where(index, "ks-dup-a") == where(index, "ks-dup-b") == where(index, "ks-dup-c")


def test_groups_are_reported_with_their_reasons():
    base = (
        "Ваша посылка задержана на таможенном складе, так как не оплачена пошлина 350 тенге. "
        "Оплатите по ссылке в течение суток, иначе отправление вернётся отправителю. Kazpost."
    )
    rows = [
        corpus_row("ks-a", base),
        corpus_row("ks-b", base.replace("суток", "двух суток")),
        corpus_row("ks-c", base + "!"),
        corpus_row("ks-d", "Другое сообщение", notes="parallel pair key: x-1"),
        corpus_row("ks-e", "Басқа хабарлама", lang="kk", notes="Parallel pair key: x-1"),
        corpus_row("ks-f", "Совсем другое сообщение про выигрыш в лотерею"),
    ]
    groups = group_rows(rows)
    by_key = {g.key: g for g in groups}
    assert set(by_key) == {"ks-a", "ks-d", "ks-f"}
    assert by_key["ks-a"].indices == (0, 1, 2)
    assert set(by_key["ks-a"].reasons) == {"identical_text", "near_duplicate"}
    assert by_key["ks-d"].reasons == ("shared_key",)
    assert by_key["ks-f"].reasons == ()

    report = assemble(rows, seed=1).report["groups"]
    assert report["n_groups"] == 3
    assert report["n_multi_row_groups"] == 2
    assert report["rows_in_multi_row_groups"] == 5
    assert report["largest_group"] == 3
    assert report["by_reason"] == {"identical_text": 1, "near_duplicate": 1, "shared_key": 1}


def test_source_key_treats_one_page_reached_two_ways_as_one_source():
    page = "tengrinews.kz/news/moshenniki-123"
    for url in (
        "https://tengrinews.kz/news/moshenniki-123",
        "http://www.tengrinews.kz/news/moshenniki-123/",
        "HTTPS://Tengrinews.kz/news/moshenniki-123#comments",
        "  https://tengrinews.kz/news/moshenniki-123  ",
    ):
        assert source_key(url) == page
    assert source_key("https://tengrinews.kz/news/moshenniki-124") != page
    assert source_key("") == ""
    assert source_key(None) == ""


@pytest.mark.parametrize("seed", SEEDS)
def test_rows_quoted_from_one_article_never_split(seed):
    article = [
        corpus_row(
            "ks-art-1",
            "Ваш аккаунт взломан, срочно переведите средства на безопасный счёт.",
            source_url="https://example.kz/article-9",
        ),
        corpus_row(
            "ks-art-2",
            "Сіздің атыңызға несие рәсімделді, растау үшін кодты айтыңыз.",
            lang="kk",
            source_url="http://www.example.kz/article-9/",
        ),
        corpus_row(
            "ks-art-3",
            "Информируем о плановых работах, приложение будет недоступно ночью.",
            label="legit",
            hard_negative=True,
            source_url="https://example.kz/article-9#update",
        ),
    ]
    rows = filler(20) + article
    groups = {g.key: g for g in group_rows(sorted(rows, key=lambda r: r["id"]))}
    assert groups["ks-art-1"].reasons == ("same_source",)
    assert len(groups["ks-art-1"]) == 3
    index = split_index(build_splits(rows, seed=seed, calibration_size=10))
    assert where(index, "ks-art-1") == where(index, "ks-art-2") == where(index, "ks-art-3")


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------


def _exposure_corpus() -> list[dict]:
    """Twenty fresh rows, five that exposure touches, and one new article it must leave alone."""
    return [
        *filler(20),
        corpus_row("ks-seen", "Назовите код из SMS, иначе счёт будет заблокирован навсегда."),
        corpus_row(
            "ks-seen-kk",
            "SMS кодын айтыңыз, әйтпесе шотыңыз біржола бұғатталады.",
            lang="kk",
            notes="parallel pair key: seen-1",
        ),
        corpus_row("ks-seen-ru", "Пара к казахской строке.", notes="Parallel pair key: seen-1"),
        corpus_row(
            "ks-same-article",
            "Новое сообщение из уже прочитанной статьи про выигрыш автомобиля.",
            source_url="https://example.kz/ks-seen",
        ),
        corpus_row(
            "ks-frag",
            "безопасный счёт",
            text_kind="phrase_fragment",
            source_url="https://example.kz/read-for-its-phrases",
        ),
        corpus_row(
            "ks-fragment-article",
            "Сообщение из статьи, из которой раньше взяли только фразу для лексикона.",
            source_url="https://www.example.kz/read-for-its-phrases/",
        ),
        corpus_row(
            "ks-fresh",
            "Совсем новая статья: курьер просит оплатить доставку по ссылке.",
            source_url="https://example.kz/a-new-article",
        ),
    ]


@pytest.mark.parametrize("seed", SEEDS)
def test_exposed_rows_take_their_group_and_their_article_to_dev(seed):
    rows = _exposure_corpus()
    exposed = {"ks-seen", "ks-seen-kk", "ks-frag"}
    build = assemble(rows, seed=seed, exposed_ids=exposed, calibration_size=8)
    index = split_index(build.splits)
    # The listed rows, the partner of a listed pair, a second quote from a
    # listed row's article, and a message from an article a listed fragment
    # was taken from.
    for corpus_id in ("ks-seen", "ks-seen-kk", "ks-seen-ru", "ks-same-article"):
        assert where(index, corpus_id) == "dev", corpus_id
    assert where(index, "ks-fragment-article") == "dev"
    assert "ks-frag" not in index
    assert where(index, "ks-fresh") in {"calibration", "test_press"}
    assert all(where(index, r["id"]) != "dev" for r in filler(20))

    report = build.report["dev"]
    assert report["exposed_rows"] == 2  # the fragment is exposed but is not a message
    assert report["exposed_sources"] == 3
    assert report["rows_pulled_in_by_group_or_source"] == [
        "ks-fragment-article",
        "ks-same-article",
        "ks-seen-ru",
    ]
    assert build.report["splits"]["dev"]["n"] == 5
    assert build.report["calibration"]["press_pool_rows"] == 21


@pytest.mark.parametrize("seed", SEEDS)
def test_no_exposed_row_reaches_a_held_out_split_under_any_seed(seed):
    old = filler(30, prefix="old")
    donated_old = corpus_row(
        "ks-old-don", "Старый донат: код 9911, никому не сообщайте.", provenance="donated"
    )
    rows = [*old, donated_old, *filler(300, prefix="new", lang="kk", start=30)]
    exposed = {r["id"] for r in old} | {"ks-old-don"}
    result = build_splits(rows, seed=seed, exposed_ids=exposed)
    assert {r["corpus_id"] for r in result["dev"]} == exposed
    for name in HELD_OUT_SPLITS:
        assert not ({r["corpus_id"] for r in result[name]} & exposed), name
    # An exposed donated row is development data too, not a held-out donation.
    assert result["test_donated"] == []
    assert len(result["calibration"]) == 60


def test_the_register_names_whole_batches_and_single_rows(tmp_path):
    register = tmp_path / "exposure.json"
    register.write_text(
        json.dumps({"exposed_batches": ["press-01"], "exposed_ids": ["ks-x-2"], "log": []}),
        encoding="utf-8",
    )
    rows = [
        {"id": "ks-a-1", "batch": "press-01"},
        {"id": "ks-a-2", "batch": "press-01"},
        {"id": "ks-x-1", "batch": "press-09"},
        {"id": "ks-x-2", "batch": "press-09"},
    ]
    assert exposed_corpus_ids(rows, load_exposure(register)) == {"ks-a-1", "ks-a-2", "ks-x-2"}

    register.write_text(json.dumps({"exposed_batches": "press-01"}), encoding="utf-8")
    with pytest.raises(ValueError, match="exposed_batches must be a list of strings"):
        load_exposure(register)
    register.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="expected an object"):
        load_exposure(register)


# ---------------------------------------------------------------------------
# Routing, capping, stratification, determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_donated_rows_are_held_out_and_press_rows_are_not(seed):
    donated = [
        corpus_row(
            f"ks-don-{i}",
            f"Донат {i}: ваш код подтверждения {1000 + i * 37}, никому не сообщайте.",
            provenance="donated",
            label="legit" if i % 2 else "scam",
            hard_negative=bool(i % 2),
        )
        for i in range(6)
    ]
    official = [
        corpus_row(
            "ks-off-1",
            "Информируем о технических работах 12.05.2026, приложение будет недоступно.",
            provenance="official_warning",
            label="legit",
            hard_negative=True,
        )
    ]
    result = build_splits(filler(20) + donated + official, seed=seed, calibration_size=8)
    index = split_index(result)
    assert all(where(index, r["id"]) == "test_donated" for r in donated)
    assert where(index, "ks-off-1") in {"calibration", "test_press"}
    assert all(row["source"] != "donated" for row in result["calibration"])
    assert all(row["source"] != "donated" for row in result["test_press"])
    assert all(row["source"] == "donated" for row in result["test_donated"])
    assert result["train_synthetic"] == []
    # Hard negatives stay in the pool their provenance puts them in.
    assert any(row["hard_negative"] for row in result["test_donated"])
    assert any(row["hard_negative"] for row in result["calibration"] + result["test_press"])


def test_a_group_touching_a_donated_row_is_held_out_whole_and_reported():
    text = (
        "Ваш аккаунт будет заблокирован в течение часа из-за подозрительной активности. "
        "Подтвердите данные по ссылке ниже, чтобы сохранить доступ к счёту и картам. Kaspi.kz"
    )
    rows = [
        *filler(10),
        corpus_row("ks-press-x", text, provenance="press"),
        corpus_row("ks-don-x", text.replace("часа", "одного часа"), provenance="donated"),
    ]
    build = assemble(rows, seed=1, calibration_size=4)
    index = split_index(build.splits)
    assert where(index, "ks-press-x") == where(index, "ks-don-x") == "test_donated"
    assert build.report["groups"]["mixed_provenance_groups"] == ["ks-don-x"]


def test_calibration_is_capped_at_the_pool_fraction_and_stratified():
    rows = (
        filler(50, prefix="sr", lang="ru", label="scam")
        + filler(30, prefix="sk", lang="kk", label="scam")
        + filler(20, prefix="lr", lang="ru", label="legit")
    )
    build = assemble(rows, seed=7, calibration_size=150)
    calibration = build.splits["calibration"]
    # 150 asked, 40% of a 100-row pool is 40, so 40, split 20 / 12 / 8.
    assert len(calibration) == 40
    assert len(build.splits["test_press"]) == 60
    report = build.report["calibration"]
    assert report == {
        "regime": "manual",
        "size_requested": 150,
        "max_fraction": 0.4,
        "press_pool_rows": 100,
        "cap_rows": 40,
        "target_rows": 40,
        "rows": 40,
        "fraction_of_pool": pytest.approx(0.4),
        "quota_by_label_lang": {"legit/ru": 8, "scam/kk": 12, "scam/ru": 20},
    }
    tally = build.report["splits"]["calibration"]["by_label_lang"]
    assert tally == {"legit/ru": 8, "scam/kk": 12, "scam/ru": 20}

    # Below the cap, the requested size is honoured exactly.
    small = assemble(rows, seed=7, calibration_size=10)
    assert len(small.splits["calibration"]) == 10
    assert small.report["splits"]["calibration"]["by_label_lang"] == {
        "legit/ru": 2,
        "scam/kk": 3,
        "scam/ru": 5,
    }
    assert small.report["calibration"]["fraction_of_pool"] == pytest.approx(0.1)

    # Every row ends up somewhere, exactly once.
    ids = [r["corpus_id"] for s in small.splits.values() for r in s]
    assert sorted(ids) == sorted(r["id"] for r in rows)


def test_the_contract_rule_cuts_calibration_only_from_a_pool_that_can_spare_it():
    assert policy_calibration_size(0) == 0
    assert policy_calibration_size(CALIBRATION_MIN_POOL - 1) == 0
    assert policy_calibration_size(CALIBRATION_MIN_POOL) == CALIBRATION_MIN_ROWS
    assert policy_calibration_size(300) == 60
    assert policy_calibration_size(375) == CALIBRATION_MAX_ROWS
    assert policy_calibration_size(5000) == CALIBRATION_MAX_ROWS

    # Below the line: no calibration split, every fresh row is a test row.
    small = assemble(filler(120), seed=3)
    assert small.splits["calibration"] == []
    assert len(small.splits["test_press"]) == 120
    assert small.report["calibration"]["regime"] == "dev-calibrated"
    assert small.report["calibration"]["size_requested"] == 0

    # At or above it: a fifth of the pool, stratified, the rest is the test set.
    rows = filler(200, prefix="r") + filler(100, prefix="k", lang="kk", label="legit", start=200)
    large = assemble(rows, seed=3)
    assert large.report["calibration"]["regime"] == "calibrated"
    assert len(large.splits["calibration"]) == 60
    assert len(large.splits["test_press"]) == 240
    assert large.report["splits"]["calibration"]["by_label_lang"] == {
        "legit/kk": 20,
        "scam/ru": 40,
    }


def test_a_tiny_pool_yields_a_tiny_calibration_not_a_padded_one():
    build = assemble(filler(7), seed=1, calibration_size=150)
    assert len(build.splits["calibration"]) == 2  # int(0.4 * 7)
    assert len(build.splits["test_press"]) == 5
    assert build.report["calibration"]["cap_rows"] == 2


def test_same_seed_same_output_different_seed_different_assignment():
    rows = [
        *filler(40),
        corpus_row("ks-p-ru", "Пара по-русски, назовите код.", notes="parallel pair key: p"),
        corpus_row(
            "ks-p-kk", "Қазақша жұп, кодты айтыңыз.", lang="kk", notes="parallel pair key: p"
        ),
    ]
    first = build_splits(rows, seed=20260908, calibration_size=16)
    again = build_splits(rows, seed=20260908, calibration_size=16)
    assert first == again
    # Input order must not matter either.
    shuffled = build_splits(list(reversed(rows)), seed=20260908, calibration_size=16)
    assert shuffled == first

    assignments = {
        json.dumps(split_index(build_splits(rows, seed=s, calibration_size=16)), sort_keys=True)
        for s in SEEDS
    }
    assert len(assignments) > 1, "every seed produced the same assignment"


def test_released_ids_follow_corpus_order_and_do_not_depend_on_the_seed():
    rows = filler(15)
    by_seed = [
        {r["corpus_id"]: r["id"] for s in build_splits(rows, seed=seed).values() for r in s}
        for seed in SEEDS
    ]
    assert all(mapping == by_seed[0] for mapping in by_seed[1:])
    expected = {f"ks-f-{i:03d}": f"kazscam-{i + 1:06d}" for i in range(15)}
    assert by_seed[0] == expected


# ---------------------------------------------------------------------------
# Row shape
# ---------------------------------------------------------------------------


def test_every_emitted_row_has_the_contract_shape_and_loads_in_the_harness():
    rows = [
        *filler(12),
        corpus_row(
            "ks-mixed",
            "Сәлем, это Kaspi қауіпсіздік қызметі, назовите код.",
            lang="kk-ru",
            channel="whatsapp",
            scrub_placeholders=["phone", "name"],
        ),
        corpus_row(
            "ks-hn",
            "Никому не сообщайте код 4821. Halyk Bank.",
            label="legit",
            hard_negative=True,
            provenance="donated",
        ),
    ]
    result = build_splits(rows, seed=3)
    seen_ids: set[str] = set()
    for split in result.values():
        for row in split:
            assert tuple(row) == ROW_FIELDS
            DatasetRow.model_validate(row)
            assert row["id"] not in seen_ids
            seen_ids.add(row["id"])
            assert row["playbook_id"] is None
            assert row["stage"] is None
            assert row["annotator_a"] is None
            assert row["annotator_b"] is None
            assert row["adjudicated"] is False
            assert row["text_sha256"] == text_sha256(row["text"])
            # None of these rows has a relative, so each is its own group.
            assert row["source_group"] == row["id"]
            assert row["collected_at"] == "2026-09-08"
            assert isinstance(row["scrub_applied"], list)

    by_corpus = {row["corpus_id"]: row for s in result.values() for row in s}
    mixed = by_corpus["ks-mixed"]
    assert mixed["lang"] == "kk"
    assert mixed["lang_secondary"] == "ru"
    assert mixed["is_code_switched"] is True
    assert mixed["channel"] == "whatsapp"
    assert mixed["scrub_applied"] == ["phone", "name"]
    assert mixed["source"] == "press"
    assert mixed["source_url"] == "https://example.kz/ks-mixed"

    donated = by_corpus["ks-hn"]
    assert donated["source"] == "donated"
    assert donated["source_url"] is None
    assert donated["hard_negative"] is True
    assert donated["lang_secondary"] is None


def test_the_collectors_unscrubbed_shape_is_accepted_too():
    row = corpus_row("ks-raw", "Текст без скраба")
    row["scrub_applied"] = []
    del row["scrub_placeholders"]
    assert to_released_row(row, "kazscam-000001")["scrub_applied"] == []


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"label": "scam", "hard_negative": True}, "hard negative must be legit"),
        ({"label": "spam"}, "label must be one of"),
        ({"text": "   "}, "empty text"),
        ({"lang": ""}, "missing lang"),
    ],
)
def test_a_corpus_row_that_cannot_be_released_is_named(overrides, message):
    fields = {"text": "Текст", **overrides}
    rows = [*filler(3), corpus_row("ks-bad", fields.pop("text"), **fields)]
    with pytest.raises(CorpusError, match=message) as excinfo:
        build_splits(rows, seed=1)
    assert "ks-bad" in str(excinfo.value)


# ---------------------------------------------------------------------------
# The CLI and the files it writes
# ---------------------------------------------------------------------------


def _write_corpus(directory: Path, rows: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    half = len(rows) // 2
    for name, items in (("batch-a.json", rows[:half]), ("batch-b.json", rows[half:])):
        payload = {"batch": name[6:-5], "created_at": "2026-09-08T00:00:00+00:00", "items": items}
        (directory / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def test_the_cli_writes_one_jsonl_per_split_a_manifest_and_a_provisional_readme(tmp_path, capsys):
    corpus = tmp_path / "corpus"
    out = tmp_path / "kazscam"
    rows = [
        *filler(30),
        corpus_row("ks-frag", "бұғатталды", lang="kk", text_kind="phrase_fragment"),
        corpus_row("ks-don", "Донат: код 1234", provenance="donated", label="legit"),
    ]
    _write_corpus(corpus, rows)

    argv = ["splits", "--corpus", str(corpus), "--out", str(out), "--seed", "5"]
    assert main([*argv, "--calibration-size", "10"]) == 0
    printed = capsys.readouterr().out
    assert "calibration=10" in printed
    assert "1 fragments excluded" in printed

    for name in SPLIT_NAMES:
        assert (out / f"{name}.jsonl").is_file()
    assert read_split(out / "train_synthetic.jsonl") == []
    assert len(read_split(out / "calibration.jsonl")) == 10
    assert len(read_split(out / "test_press.jsonl")) == 20
    assert [r["corpus_id"] for r in read_split(out / "test_donated.jsonl")] == ["ks-don"]
    for name in ("calibration", "test_press", "test_donated"):
        assert all(isinstance(r, DatasetRow) for r in load_split(out / f"{name}.jsonl"))

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == 5
    assert manifest["status"] == "provisional"
    assert manifest["excluded_fragments"] == 1
    assert manifest["splits"]["calibration"]["n"] == 10
    assert manifest["calibration"]["size_requested"] == 10
    assert "built_at" in manifest
    assert any("source_row_id" in note for note in manifest["notes"])

    assert manifest["calibration"]["regime"] == "manual"
    assert manifest["exposure_register"] is None

    readme = (out / "README.md").read_text(encoding="utf-8")
    first_line = readme.splitlines()[0]
    assert first_line.startswith("PROVISIONAL")
    assert "not annotated" in first_line
    assert "T407" in first_line
    assert "asked for by hand" in readme

    # A rebuild with the same seed rewrites the JSONL files byte for byte.
    before = {name: (out / f"{name}.jsonl").read_bytes() for name in SPLIT_NAMES}
    assert main([*argv, "--calibration-size", "10"]) == 0
    after = {name: (out / f"{name}.jsonl").read_bytes() for name in SPLIT_NAMES}
    assert before == after


def test_the_cli_reads_the_register_beside_the_corpus_and_sends_exposed_batches_to_dev(
    tmp_path, capsys
):
    corpus = tmp_path / "data" / "corpus"
    out = tmp_path / "kazscam"
    rows = filler(30)  # batch "a" is the first fifteen, batch "b" the rest
    _write_corpus(corpus, rows)
    register = tmp_path / "data" / "exposure.json"
    register.write_text(
        json.dumps({"exposed_batches": ["a"], "exposed_ids": ["ks-f-029"]}), encoding="utf-8"
    )

    argv = ["splits", "--corpus", str(corpus), "--out", str(out), "--seed", "5"]
    assert main(argv) == 0
    printed = capsys.readouterr().out
    assert "dev-calibrated" in printed
    assert "dev=16" in printed
    assert "calibration=0" in printed
    assert "test_press=14" in printed

    dev = {r["corpus_id"] for r in read_split(out / "dev.jsonl")}
    assert dev == {r["id"] for r in rows[:15]} | {"ks-f-029"}
    assert read_split(out / "calibration.jsonl") == []
    assert all(isinstance(r, DatasetRow) for r in load_split(out / "dev.jsonl"))

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["calibration"]["regime"] == "dev-calibrated"
    assert manifest["dev"]["exposed_rows"] == 16
    assert manifest["exposure_register"].endswith("data/exposure.json")
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "No calibration split was cut" in readme

    # A register named on the command line replaces the one beside the corpus.
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"exposed_batches": [], "exposed_ids": []}), encoding="utf-8")
    assert main([*argv, "--exposure", str(other)]) == 0
    assert read_split(out / "dev.jsonl") == []
    assert len(read_split(out / "test_press.jsonl")) == 30
    capsys.readouterr()

    # One that is named but missing is an error, not an empty register.
    assert main([*argv, "--exposure", str(tmp_path / "missing.json")]) == 2
    assert "missing.json" in capsys.readouterr().err


def test_the_cli_reports_a_missing_corpus_directory(tmp_path, capsys):
    code = main(["splits", "--corpus", str(tmp_path / "nowhere"), "--out", str(tmp_path / "o")])
    assert code == 2
    assert "corpus directory not found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The leakage rules over data/kazscam_v0.1/ (CI)
# ---------------------------------------------------------------------------

needs_release = pytest.mark.skipif(
    not SPLIT_DIR.is_dir(), reason=f"{SPLIT_DIR.relative_to(REPO_ROOT)} has not been built"
)


@pytest.fixture(scope="module")
def released() -> dict[str, list[dict]]:
    """Every split file that exists, by name. Missing files are empty splits."""
    if not SPLIT_DIR.is_dir():
        pytest.skip(f"{SPLIT_DIR} has not been built")
    result: dict[str, list[dict]] = {}
    for name in SPLIT_NAMES:
        path = SPLIT_DIR / f"{name}.jsonl"
        result[name] = read_split(path) if path.is_file() else []
    if not any(result.values()):
        pytest.skip(f"{SPLIT_DIR} holds no rows")
    return result


def _pairs(released: dict[str, list[dict]]):
    names = list(released)
    for a, b in itertools.combinations(names, 2):
        yield a, b, released[a], released[b]


@needs_release
def test_no_text_sha256_appears_in_two_splits(released):
    for a, b, rows_a, rows_b in _pairs(released):
        shared = {r["text_sha256"] for r in rows_a} & {r["text_sha256"] for r in rows_b}
        assert not shared, f"{len(shared)} text_sha256 in both {a} and {b}: {sorted(shared)[:3]}"
    for name, rows in released.items():
        assert all(r["text_sha256"] == text_sha256(r["text"]) for r in rows), name


@needs_release
def test_no_synthetic_row_shares_a_source_row_with_a_test_row(released):
    test_ids: set[str] = set()
    for name in TEST_SPLITS:
        for row in released[name]:
            test_ids.update({row["id"], row.get("corpus_id", "")})
    test_ids.discard("")
    for row in released["train_synthetic"]:
        source = row.get("source_row_id")
        assert source, f"synthetic row {row.get('id')} records no source_row_id"
        assert source not in test_ids, f"synthetic row {row['id']} derives from test row {source}"


@needs_release
def test_calibration_is_disjoint_from_every_test_split(released):
    calibration = released["calibration"]
    for key in ("id", "corpus_id", "text_sha256"):
        mine = {r[key] for r in calibration if r.get(key)}
        for name in TEST_SPLITS:
            theirs = {r[key] for r in released[name] if r.get(key)}
            assert not (mine & theirs), f"calibration shares {key} with {name}: {mine & theirs}"


@needs_release
def test_no_near_duplicate_pair_straddles_two_splits(released):
    shingled = {
        name: [(r["id"], splits.shingles(normalize_text(r["text"]))) for r in rows]
        for name, rows in released.items()
    }
    leaks = []
    for a, b, _, _ in _pairs(released):
        for (id_a, sh_a), (id_b, sh_b) in itertools.product(shingled[a], shingled[b]):
            score = splits.jaccard(sh_a, sh_b)
            if score >= NEAR_DUP_THRESHOLD:
                leaks.append(f"{id_a} ({a}) ~ {id_b} ({b}) at {score:.2f}")
    assert not leaks, "\n".join(leaks)


@needs_release
def test_no_source_article_straddles_two_splits(released):
    splits_of: dict[str, set[str]] = {}
    for name, rows in released.items():
        for row in rows:
            key = source_key(row.get("source_url"))
            if key:
                splits_of.setdefault(key, set()).add(name)
    torn = {key: sorted(names) for key, names in splits_of.items() if len(names) > 1}
    assert not torn, f"source articles spanning splits: {torn}"


@needs_release
@pytest.mark.skipif(not CORPUS_DIR.is_dir(), reason="data/corpus is not in this checkout")
@pytest.mark.skipif(
    not EXPOSURE_FILE.is_file(), reason="data/exposure.json is not in this checkout"
)
def test_no_exposed_row_or_exposed_article_is_in_a_held_out_split(released):
    corpus = splits.load_corpus(CORPUS_DIR)
    exposed = exposed_corpus_ids(corpus, load_exposure(EXPOSURE_FILE))
    exposed_sources = {source_key(r.get("source_url")) for r in corpus if r["id"] in exposed}
    exposed_sources.discard("")
    for name in HELD_OUT_SPLITS:
        leaked = [r["corpus_id"] for r in released[name] if r["corpus_id"] in exposed]
        assert not leaked, f"exposed rows in {name}: {leaked[:5]}"
        same_article = [
            r["corpus_id"]
            for r in released[name]
            if source_key(r.get("source_url")) in exposed_sources
        ]
        assert not same_article, f"rows in {name} from an exposed article: {same_article[:5]}"
    in_dev = {r["corpus_id"] for r in released["dev"]}
    messages = {r["id"] for r in corpus if r.get("text_kind", "message") == "message"}
    assert (exposed & messages) <= in_dev, "an exposed message is missing from dev"


def test_rows_that_travel_together_name_the_same_source_group():
    pair = "parallel pair key: kaspi-code"
    rows = [
        corpus_row("ks-a-ru", "Назовите код из SMS, это служба безопасности банка.", notes=pair),
        corpus_row(
            "ks-b-kk", "SMS кодын айтыңыз, бұл банк қауіпсіздік қызметі.", lang="kk", notes=pair
        ),
        corpus_row("ks-c", "Ваша посылка задержана на таможне, оплатите пошлину по ссылке."),
        *filler(4),
    ]
    build = splits.assemble(rows, seed=5)
    by_corpus = {r["corpus_id"]: r for s in build.splits.values() for r in s}

    # The group is named after its first row, in corpus-id order.
    assert by_corpus["ks-a-ru"]["source_group"] == by_corpus["ks-a-ru"]["id"]
    assert by_corpus["ks-b-kk"]["source_group"] == by_corpus["ks-a-ru"]["id"]
    assert by_corpus["ks-c"]["source_group"] == by_corpus["ks-c"]["id"]
    assert len({r["source_group"] for r in by_corpus.values()}) == 6

    # A group is never divided, so its name is an id in the row's own split,
    # and the manifest counts the groups of each split.
    for name, split in build.splits.items():
        ids = {r["id"] for r in split}
        assert all(r["source_group"] in ids for r in split), name
        tally = build.report["splits"][name]
        assert tally["source_groups"] == len({r["source_group"] for r in split})
    assert sum(t["source_groups"] for t in build.report["splits"].values()) == 6


@needs_release
def test_the_released_rows_name_the_groups_the_manifest_reports(released):
    manifest = json.loads((SPLIT_DIR / "manifest.json").read_text(encoding="utf-8"))
    names: set[str] = set()
    for split, rows in released.items():
        if split == "train_synthetic":
            continue
        ids = {r["id"] for r in rows}
        groups = {r["source_group"] for r in rows}
        assert groups <= ids, f"{split}: a source group is named after a row outside the split"
        assert manifest["splits"][split]["source_groups"] == len(groups)
        names |= groups
    assert len(names) == manifest["groups"]["n_groups"]


@needs_release
def test_every_released_id_is_unique_and_every_row_loads_in_the_harness(released):
    ids = [r["id"] for rows in released.values() for r in rows]
    assert len(ids) == len(set(ids))
    for name in SPLIT_NAMES:
        path = SPLIT_DIR / f"{name}.jsonl"
        if path.is_file():
            assert len(load_split(path)) == len(released[name])


@needs_release
@pytest.mark.skipif(not CORPUS_DIR.is_dir(), reason="data/corpus is not in this checkout")
def test_group_keys_and_fragments_are_honoured_against_the_corpus(released):
    corpus = {row["id"]: row for row in splits.load_corpus(CORPUS_DIR)}
    split_of = {r["corpus_id"]: name for name, rows in released.items() for r in rows}
    unknown = [cid for cid in split_of if cid not in corpus]
    assert not unknown, f"released rows with no corpus record: {unknown[:5]}"
    fragments = [cid for cid in split_of if corpus[cid].get("text_kind", "message") != "message"]
    assert not fragments, f"fragments in a message split: {fragments[:5]}"
    by_key: dict[str, set[str]] = {}
    for cid, name in split_of.items():
        for key in group_keys(str(corpus[cid].get("notes", "") or "")):
            by_key.setdefault(key, set()).add(name)
    torn = {key: names for key, names in by_key.items() if len(names) > 1}
    assert not torn, f"group keys spanning splits: {torn}"


@needs_release
def test_the_release_directory_says_it_is_provisional():
    readme = SPLIT_DIR / "README.md"
    manifest = SPLIT_DIR / "manifest.json"
    assert readme.is_file() and manifest.is_file()
    assert readme.read_text(encoding="utf-8").splitlines()[0].startswith("PROVISIONAL")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["status"] == "provisional"
    assert "seed" in payload
    assert payload["calibration"]["regime"] in {"dev-calibrated", "calibrated", "manual"}
    assert payload["calibration"]["rows"] == payload["splits"]["calibration"]["n"]
