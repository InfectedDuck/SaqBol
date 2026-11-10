"""T408 — the KazScam split builder.

Turns the collected corpus (`data/corpus/batch-*.json`, in the shape
`tools/collect.py` writes) into the five released splits of contract section
6, one JSONL each, plus a manifest. Everything is deterministic under the
seed, so two builds over the same corpus produce byte-identical files.

Five rules decide where a row goes. The policy behind them is
docs/15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md.

**Only messages.** A `phrase_fragment` is a cue phrase a journalist quoted to
illustrate wording, not something a target receives, and docs/09_SOURCES.md
section 4 says it must never enter a message split. Fragments are dropped and
counted.

**Rows that must travel together do.** Two quotes from one article, a press
warning reprinted on a second site, a Kazakh translation of a Russian
message, the two prefix-sharing variants of one fake Kazpost SMS: each of
these is one unit for leakage purposes, and a unit split across calibration
and test is a leak. Rows are joined into groups by union-find over four
signals — the same source article, a shared `parallel pair key` or `Variant
group key` in `notes`, identical normalized text, and a character-shingle
Jaccard at or above the collector's near-duplicate threshold — and a group is
assigned to a split as a unit.

**Exposed rows are development data.** A row the system was developed against
is listed in the exposure register (`data/exposure.json`), by batch or by id.
Its whole group goes to `dev`, and so does any group holding a row from an
article an exposed row or fragment was quoted from. Nothing in `dev` can
reach a calibration or test split, under any seed.

**Donated rows are held out.** Of what is left, anything with `provenance ==
"donated"` goes to `test_donated`; press and official warnings form the fresh
press pool. Hard negatives stay in whichever pool their provenance puts them
in, per the contract.

**Calibration is cut only from a pool large enough to spare it.** Below
`CALIBRATION_MIN_POOL` fresh press rows there is no calibration split:
thresholds are fitted on `dev` and the manifest says `dev-calibrated`. At or
above it, 20% of the pool, between 50 and 75 rows, is drawn by group and
stratified by (label, lang). A size given by hand overrides this, is capped at
`max_calibration_fraction` of the pool, and is recorded as `manual`. The
remainder of the pool is `test_press`. `train_synthetic` is written empty: the
paraphrases do not exist yet, and when they are generated they must come from
`dev` rows only, with the seed row recorded in `source_row_id`, or the second
leakage rule cannot be checked.

The normalization and similarity here mirror `tools/collect.py` exactly;
`tests/test_splits.py` pins the two to each other. They are duplicated rather
than imported because `tools/` is a script directory, not part of the
installed package.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import unicodedata
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Contract section 6: the five released splits, in file order.
SPLIT_NAMES: tuple[str, ...] = (
    "train_synthetic",
    "dev",
    "calibration",
    "test_press",
    "test_donated",
)
#: Contract section 6: no calibration split below this many fresh press rows.
CALIBRATION_MIN_POOL = 250
#: Contract section 6: at or above it, this share of the pool, within the bounds.
CALIBRATION_FRACTION = 0.2
CALIBRATION_MIN_ROWS = 50
CALIBRATION_MAX_ROWS = 75
#: A calibration size given by hand may never take more than this share of the pool.
DEFAULT_MAX_CALIBRATION_FRACTION = 0.4
#: The exposure register, looked for beside the corpus directory.
EXPOSURE_FILENAME = "exposure.json"
#: tools/collect.py: exact-on-normalized plus character-shingle Jaccard at 0.85.
NEAR_DUP_THRESHOLD = 0.85
SHINGLE = 5
#: Contract section 6: the gold label set.
LABELS: tuple[str, ...] = ("scam", "legit", "ambiguous")
#: The dataset version the manifest names.
DATASET_VERSION = "kazscam-v0.1"
#: Released ids look like `kazscam-000417`.
ID_FORMAT = "kazscam-{:06d}"

#: Contract section 6, in order, plus the two tracing fields at the end:
#: `text_sha256` is what the first leakage rule is stated in terms of, and
#: `corpus_id` lets a released row be traced back to its collection record.
ROW_FIELDS: tuple[str, ...] = (
    "id",
    "text",
    "label",
    "playbook_id",
    "stage",
    "lang",
    "lang_secondary",
    "is_code_switched",
    "channel",
    "source",
    "source_url",
    "collected_at",
    "annotator_a",
    "annotator_b",
    "adjudicated",
    "hard_negative",
    "scrub_applied",
    "source_group",
    "text_sha256",
    "corpus_id",
)

_KEY_RE = re.compile(
    r"(?P<kind>parallel\s+pair\s+key|variant\s+group\s+key)\s*:\s*(?P<slug>[A-Za-z0-9_.\-]+)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# normalization and similarity (mirrors tools/collect.py)
# ---------------------------------------------------------------------------

_URL_RE = re.compile(
    r"https?://\S+|(?:www\.)?[a-z0-9-]+\.(?:kz|com|ru|info|site|top|xyz|net|org)\b/?\S*",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")
_NONWORD_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_text(text: str) -> str:
    """Fold a message down to what is left when formatting stops mattering."""
    s = unicodedata.normalize("NFKC", text).lower()
    s = _URL_RE.sub(" url ", s)
    s = _NONWORD_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s)
    return s.strip()


def shingles(norm: str, n: int = SHINGLE) -> frozenset[str]:
    """Character n-grams of a normalized text with the spaces removed."""
    packed = norm.replace(" ", "")
    if len(packed) < n:
        return frozenset({packed}) if packed else frozenset()
    return frozenset(packed[i : i + n] for i in range(len(packed) - n + 1))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 1.0 if a == b else 0.0
    return len(a & b) / len(a | b)


def similarity(a: str, b: str) -> float:
    """Jaccard over character shingles of the normalized texts."""
    return jaccard(shingles(normalize_text(a)), shingles(normalize_text(b)))


def text_sha256(text: str) -> str:
    """The digest the first leakage rule is stated in terms of: the released text, verbatim."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# grouping
# ---------------------------------------------------------------------------


def group_keys(notes: str) -> list[str]:
    """The `parallel pair key` / `Variant group key` slugs in a notes field.

    Both spellings are read case-insensitively and share one namespace: two
    rows with the same slug travel together whichever phrase introduced it.
    """
    return sorted({m.group("slug").lower() for m in _KEY_RE.finditer(notes or "")})


_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)


def source_key(url: object) -> str:
    """What two rows quoted from the same article have in common, or "" for no source.

    The scheme, a leading `www.`, a `#fragment` and a trailing slash are
    dropped and the rest is case-folded, so the same page reached two ways is
    one source. Erring towards joining is the safe direction: it can only
    keep more rows together.
    """
    s = str(url or "").strip()
    if not s:
        return ""
    s = _SCHEME_RE.sub("", s.split("#", 1)[0]).casefold()
    if s.startswith("www."):
        s = s[4:]
    return s.rstrip("/")


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        # Attach the larger root under the smaller so the root is the row
        # with the lowest index, which is the group's deterministic key.
        if rb < ra:
            ra, rb = rb, ra
        self.parent[rb] = ra
        return True


@dataclass(frozen=True)
class Group:
    """Rows that must land in the same split, with why they were joined."""

    key: str
    indices: tuple[int, ...]
    reasons: tuple[str, ...]

    def __len__(self) -> int:
        return len(self.indices)


def group_rows(
    rows: Sequence[Mapping[str, Any]], *, threshold: float = NEAR_DUP_THRESHOLD
) -> list[Group]:
    """Union-find over one source, shared keys, identical text and near-duplicates.

    `rows` must already be in a deterministic order; the group key is the id
    of its first row and groups come back sorted by that key.
    """
    uf = _UnionFind(len(rows))
    reasons: dict[int, set[str]] = {i: set() for i in range(len(rows))}

    def join(a: int, b: int, reason: str) -> None:
        uf.union(a, b)
        reasons[a].add(reason)
        reasons[b].add(reason)

    by_source: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        source = source_key(row.get("source_url"))
        if source:
            by_source.setdefault(source, []).append(i)
    for members in by_source.values():
        for other in members[1:]:
            join(members[0], other, "same_source")

    by_key: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        for key in group_keys(str(row.get("notes", "") or "")):
            by_key.setdefault(key, []).append(i)
    for members in by_key.values():
        for other in members[1:]:
            join(members[0], other, "shared_key")

    norms = [normalize_text(str(row.get("text", ""))) for row in rows]
    by_norm: dict[str, list[int]] = {}
    for i, norm in enumerate(norms):
        by_norm.setdefault(norm, []).append(i)
    for members in by_norm.values():
        for other in members[1:]:
            join(members[0], other, "identical_text")

    shingled = [shingles(norm) for norm in norms]
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if norms[i] != norms[j] and jaccard(shingled[i], shingled[j]) >= threshold:
                join(i, j, "near_duplicate")

    members_of: dict[int, list[int]] = {}
    for i in range(len(rows)):
        members_of.setdefault(uf.find(i), []).append(i)
    groups = [
        Group(
            key=str(rows[members[0]].get("id", members[0])),
            indices=tuple(members),
            reasons=tuple(sorted(set().union(*(reasons[m] for m in members)))),
        )
        for members in members_of.values()
    ]
    return sorted(groups, key=lambda g: g.key)


# ---------------------------------------------------------------------------
# row shape
# ---------------------------------------------------------------------------


class CorpusError(ValueError):
    """A corpus row that cannot become a released row."""


def _released_lang(lang: str) -> tuple[str, str | None]:
    """Contract: `lang` is one code; a code-switched `kk-ru` row is kk with ru secondary."""
    if lang == "kk-ru":
        return "kk", "ru"
    return lang, None


def _scrub_record(row: Mapping[str, Any]) -> list[str]:
    """The placeholder types in the text, from whichever field the corpus kept them in.

    `tools/scrub_corpus.py` writes `scrub_applied: true` and the list in
    `scrub_placeholders`; a row that never went through the scrubber still
    carries the collector's empty `scrub_applied` list.
    """
    placeholders = row.get("scrub_placeholders")
    if isinstance(placeholders, list):
        return [str(p) for p in placeholders]
    applied = row.get("scrub_applied")
    if isinstance(applied, list):
        return [str(p) for p in applied]
    return []


def to_released_row(row: Mapping[str, Any], row_id: str) -> dict[str, Any]:
    """One corpus row in the contract section 6 shape, with the two tracing fields."""
    corpus_id = str(row.get("id") or "") or "(no id)"
    text = str(row.get("text") or "").strip()
    if not text:
        raise CorpusError(f"{corpus_id}: empty text")
    label = row.get("label")
    if label not in LABELS:
        raise CorpusError(f"{corpus_id}: label must be one of {LABELS}, got {label!r}")
    hard_negative = bool(row.get("hard_negative", False))
    if hard_negative and label != "legit":
        raise CorpusError(f"{corpus_id}: a hard negative must be legit, got {label!r}")
    raw_lang = str(row.get("lang") or "")
    if not raw_lang:
        raise CorpusError(f"{corpus_id}: missing lang")
    lang, lang_secondary = _released_lang(raw_lang)
    provenance = str(row.get("provenance") or row.get("source") or "")
    if not provenance:
        raise CorpusError(f"{corpus_id}: missing provenance")
    source_url = str(row.get("source_url") or "") or None
    collected_at = str(row.get("access_date") or "")
    if not collected_at:
        # A row without an access date still has the collector's timestamp.
        collected_at = str(row.get("collected_at") or "")[:10]
    if not collected_at:
        raise CorpusError(f"{corpus_id}: missing access_date")
    default_switched = raw_lang == "kk-ru"
    return {
        "id": row_id,
        "text": text,
        "label": label,
        "playbook_id": None,
        "stage": None,
        "lang": lang,
        "lang_secondary": lang_secondary,
        "is_code_switched": bool(row.get("is_code_switched", default_switched)),
        "channel": str(row.get("channel") or "unknown"),
        "source": provenance,
        "source_url": source_url,
        "collected_at": collected_at,
        "annotator_a": None,
        "annotator_b": None,
        "adjudicated": False,
        "hard_negative": hard_negative,
        "scrub_applied": _scrub_record(row),
        # A row is its own group until `assemble` joins it to others.
        "source_group": row_id,
        "text_sha256": text_sha256(text),
        "corpus_id": corpus_id,
    }


# ---------------------------------------------------------------------------
# the build
# ---------------------------------------------------------------------------


@dataclass
class SplitBuild:
    """The five splits plus everything the manifest reports about how they were made."""

    splits: dict[str, list[dict[str, Any]]]
    report: dict[str, Any] = field(default_factory=dict)


def _largest_remainder(total: int, weights: Mapping[Any, int]) -> dict[Any, int]:
    """Integer quotas summing to `total`, proportional to `weights`."""
    denominator = sum(weights.values())
    if total <= 0 or denominator == 0:
        return dict.fromkeys(weights, 0)
    exact = {k: total * w / denominator for k, w in weights.items()}
    quotas = {k: int(v) for k, v in exact.items()}
    shortfall = total - sum(quotas.values())
    # Ties broken by key so the allocation is deterministic.
    by_remainder = sorted(weights, key=lambda k: (-(exact[k] - quotas[k]), str(k)))
    for k in by_remainder[:shortfall]:
        quotas[k] += 1
    return quotas


def _stratum(row: Mapping[str, Any]) -> tuple[str, str]:
    return (str(row["label"]), str(row["lang"]))


def _tally(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    by_label = Counter(str(r["label"]) for r in rows)
    by_lang = Counter(str(r["lang"]) for r in rows)
    by_stratum = Counter("/".join(_stratum(r)) for r in rows)
    return {
        "n": len(rows),
        "by_label": dict(sorted(by_label.items())),
        "by_lang": dict(sorted(by_lang.items())),
        "by_label_lang": dict(sorted(by_stratum.items())),
        "hard_negative": sum(1 for r in rows if r["hard_negative"]),
        "source_groups": len({r["source_group"] for r in rows}),
    }


def policy_calibration_size(fresh_press_rows: int) -> int:
    """Contract section 6: how many calibration rows a fresh press pool can spare."""
    if fresh_press_rows < CALIBRATION_MIN_POOL:
        return 0
    wanted = round(CALIBRATION_FRACTION * fresh_press_rows)
    return min(CALIBRATION_MAX_ROWS, max(CALIBRATION_MIN_ROWS, wanted))


def assemble(
    rows: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    exposed_ids: Collection[str] = (),
    calibration_size: int | None = None,
    max_calibration_fraction: float = DEFAULT_MAX_CALIBRATION_FRACTION,
    near_dup_threshold: float = NEAR_DUP_THRESHOLD,
) -> SplitBuild:
    """Assign every eligible corpus row to a split. Pure and deterministic.

    `exposed_ids` are the corpus ids of rows the system was developed against,
    fragments included. `calibration_size=None` applies the contract's rule;
    a number overrides it. See the module docstring for the rules. Raises
    `CorpusError` on a row that cannot be released, naming it.
    """
    if calibration_size is not None and calibration_size < 0:
        raise ValueError("calibration_size must not be negative")
    if not 0.0 <= max_calibration_fraction <= 1.0:
        raise ValueError("max_calibration_fraction must be between 0 and 1")

    # Eligible rows, in corpus-id order so nothing downstream depends on the
    # order the batch files were read in.
    fragments = 0
    eligible: list[Mapping[str, Any]] = []
    for row in rows:
        if str(row.get("text_kind", "message")) != "message":
            fragments += 1
            continue
        eligible.append(row)
    eligible.sort(key=lambda r: str(r.get("id", "")))

    # Released ids follow corpus-id order and ignore the split, so the same
    # message keeps its id under a different seed.
    released = [to_released_row(row, ID_FORMAT.format(i)) for i, row in enumerate(eligible, 1)]
    groups = group_rows(eligible, threshold=near_dup_threshold)
    # Every row names its group by the released id of the group's first row,
    # so a reader of one split file can count independent sources without the
    # manifest. Groups are never divided, so the name never points outside
    # the split the row is in.
    for group in groups:
        name = released[group.indices[0]]["id"]
        for i in group.indices:
            released[i]["source_group"] = name

    # Exposure. An exposed row takes its whole group to dev, and an article
    # that any exposed row or fragment was quoted from is an exposed source:
    # whoever read the fragment read the page.
    exposed = {str(i) for i in exposed_ids}
    exposed_sources = {
        source_key(row.get("source_url")) for row in rows if str(row.get("id", "")) in exposed
    } - {""}

    # Pools. Of the groups that are not dev, one with any donated row is held
    # out whole, since a message that reached us both ways cannot be in the
    # headline set without leaking.
    dev_groups: list[Group] = []
    donated_groups: list[Group] = []
    press_groups: list[Group] = []
    mixed: list[str] = []
    pulled_in: list[str] = []
    for group in groups:
        members = [eligible[i] for i in group.indices]
        ids = [str(m.get("id", "")) for m in members]
        if any(cid in exposed for cid in ids) or any(
            source_key(m.get("source_url")) in exposed_sources for m in members
        ):
            dev_groups.append(group)
            pulled_in.extend(cid for cid in ids if cid not in exposed)
            continue
        provenances = {str(m.get("provenance") or "") for m in members}
        if "donated" in provenances:
            donated_groups.append(group)
            if len(provenances) > 1:
                mixed.append(group.key)
        else:
            press_groups.append(group)

    pool_rows = [released[i] for g in press_groups for i in g.indices]
    if calibration_size is None:
        requested = policy_calibration_size(len(pool_rows))
        regime = "calibrated" if requested else "dev-calibrated"
    else:
        requested = calibration_size
        regime = "manual"
    cap = int(max_calibration_fraction * len(pool_rows))
    target = min(requested, cap)
    strata = Counter(_stratum(r) for r in pool_rows)
    quotas = _largest_remainder(target, dict(sorted(strata.items())))

    # Groups are indivisible and a parallel pair spans two language strata,
    # so sampling is two passes over one seeded shuffle: a strict pass that
    # takes a group only if every stratum it touches stays within quota, then
    # a relaxed pass that fills whatever quota is left with groups that still
    # fit under the total. The manifest reports quota and actual side by side.
    rng = random.Random(seed)
    order = list(press_groups)
    rng.shuffle(order)
    chosen: set[str] = set()
    filled: Counter[tuple[str, str]] = Counter()
    total = 0
    for strict in (True, False):
        for group in order:
            if group.key in chosen or total + len(group) > target:
                continue
            touched = Counter(_stratum(released[i]) for i in group.indices)
            fits = (
                all(filled[s] + n <= quotas[s] for s, n in touched.items())
                if strict
                else any(filled[s] < quotas[s] for s in touched)
            )
            if not fits:
                continue
            chosen.add(group.key)
            total += len(group)
            filled.update(touched)

    calibration = [released[i] for g in press_groups if g.key in chosen for i in g.indices]
    test_press = [released[i] for g in press_groups if g.key not in chosen for i in g.indices]
    test_donated = [released[i] for g in donated_groups for i in g.indices]
    dev = [released[i] for g in dev_groups for i in g.indices]
    for split in (dev, calibration, test_press, test_donated):
        split.sort(key=lambda r: r["id"])

    splits: dict[str, list[dict[str, Any]]] = {
        "train_synthetic": [],
        "dev": dev,
        "calibration": calibration,
        "test_press": test_press,
        "test_donated": test_donated,
    }
    multi = [g for g in groups if len(g) > 1]
    report: dict[str, Any] = {
        "seed": seed,
        "corpus_rows": len(rows),
        "eligible_rows": len(eligible),
        "excluded_fragments": fragments,
        "groups": {
            "n_groups": len(groups),
            "n_multi_row_groups": len(multi),
            "rows_in_multi_row_groups": sum(len(g) for g in multi),
            "largest_group": max((len(g) for g in groups), default=0),
            "by_reason": dict(
                sorted(Counter(reason for g in multi for reason in g.reasons).items())
            ),
            "multi_row_groups": [
                {"key": g.key, "corpus_ids": [str(eligible[i]["id"]) for i in g.indices]}
                for g in multi
            ],
            "mixed_provenance_groups": mixed,
        },
        "dev": {
            "exposed_rows": sum(1 for row in eligible if str(row.get("id", "")) in exposed),
            "exposed_sources": len(exposed_sources),
            "rows_pulled_in_by_group_or_source": sorted(pulled_in),
        },
        "calibration": {
            "regime": regime,
            "size_requested": requested,
            "max_fraction": max_calibration_fraction,
            "press_pool_rows": len(pool_rows),
            "cap_rows": cap,
            "target_rows": target,
            "rows": len(calibration),
            "fraction_of_pool": (len(calibration) / len(pool_rows)) if pool_rows else 0.0,
            "quota_by_label_lang": {"/".join(k): v for k, v in sorted(quotas.items())},
        },
        "splits": {name: _tally(split) for name, split in splits.items()},
    }
    return SplitBuild(splits=splits, report=report)


def build_splits(
    rows: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    exposed_ids: Collection[str] = (),
    calibration_size: int | None = None,
    max_calibration_fraction: float = DEFAULT_MAX_CALIBRATION_FRACTION,
    near_dup_threshold: float = NEAR_DUP_THRESHOLD,
) -> dict[str, list[dict[str, Any]]]:
    """The five splits, by name, from corpus rows in the `tools/collect.py` shape."""
    return assemble(
        rows,
        seed=seed,
        exposed_ids=exposed_ids,
        calibration_size=calibration_size,
        max_calibration_fraction=max_calibration_fraction,
        near_dup_threshold=near_dup_threshold,
    ).splits


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------


def load_corpus(corpus_dir: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Every row in every batch file, in file order. Bare lists are accepted too.

    Each row comes back with a `batch` field, the batch file's own name for
    itself, so the exposure register can name whole batches.
    """
    directory = Path(corpus_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"corpus directory not found: {directory}")
    rows: list[dict[str, Any]] = []
    for path in sorted(p for p in directory.glob("*.json") if p.is_file()):
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("items", []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError(f"{path}: expected a batch object or a list of rows")
        batch = str(data.get("batch") or "") if isinstance(data, dict) else ""
        batch = batch or path.stem.removeprefix("batch-")
        for item in items:
            if isinstance(item, dict):
                item.setdefault("batch", batch)
                rows.append(item)
    return rows


def load_exposure(path: str | os.PathLike[str]) -> dict[str, list[str]]:
    """The exposure register: which batches and which single rows are development data."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected an object with exposed_batches and exposed_ids")
    register: dict[str, list[str]] = {}
    for key in ("exposed_batches", "exposed_ids"):
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"{path}: {key} must be a list of strings")
        register[key] = value
    return register


def exposed_corpus_ids(
    rows: Iterable[Mapping[str, Any]], register: Mapping[str, Sequence[str]]
) -> set[str]:
    """Corpus ids the register marks as exposed, fragments included."""
    batches = set(register.get("exposed_batches", ()))
    ids = set(register.get("exposed_ids", ()))
    return {
        str(row.get("id", ""))
        for row in rows
        if str(row.get("batch", "")) in batches or str(row.get("id", "")) in ids
    } - {""}


def read_split(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """One JSONL split back as dicts. Blank lines are ignored."""
    rows: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def git_commit(cwd: str | os.PathLike[str] | None = None) -> str | None:
    """The checked-out commit, or None when git is unavailable."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
            cwd=cwd,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


SYNTHETIC_NOTE = (
    "`train_synthetic` is empty: the LLM paraphrases do not exist yet. When generated they "
    "must be derived from dev rows only, never from calibration or a test split, with "
    "the seed row's released id recorded in `source_row_id` so the second leakage rule "
    "(no synthetic row shares a source row with any test row) can be checked."
)

PROVISIONAL_NOTE = (
    "PROVISIONAL: built from collection labels, not annotated. playbook_id, stage, "
    "annotator_a and annotator_b are null on every row. Rebuild after T407."
)


def _counts(tally: Mapping[str, int]) -> str:
    return ", ".join(f"{key} {n}" for key, n in tally.items()) or "none"


def _readme(manifest: Mapping[str, Any]) -> str:
    counts = "\n".join(
        f"| `{name}` | {tally['n']} | {tally['source_groups']} | {_counts(tally['by_label'])} | "
        f"{_counts(tally['by_lang'])} | {tally['hard_negative']} |"
        for name, tally in manifest["splits"].items()
    )
    calib = manifest["calibration"]
    groups = manifest["groups"]
    pool = calib["press_pool_rows"]
    if calib["regime"] == "dev-calibrated":
        calibration_line = (
            f"No calibration split was cut: the fresh press pool has {pool} rows, below the "
            f"{CALIBRATION_MIN_POOL} that can spare one, so thresholds are fitted on `dev` and "
            "a run on these files is labelled `dev-calibrated`."
        )
    elif calib["regime"] == "calibrated":
        calibration_line = (
            f"Calibration is {calib['rows']} rows, drawn by group from the {pool}-row fresh "
            f"press pool ({calib['fraction_of_pool']:.1%} of it)."
        )
    else:
        calibration_line = (
            f"Calibration is {calib['rows']} rows: {calib['size_requested']} were asked for by "
            f"hand, capped at {calib['max_fraction']:.0%} of the {pool}-row fresh press pool "
            f"({calib['fraction_of_pool']:.1%} used)."
        )
    return f"""PROVISIONAL splits, built from collection labels, not annotated: `playbook_id`, `stage` and both annotator fields are null on every row, and these files must be rebuilt after T407 (annotation) lands.

# KazScam v0.1 splits

Built by `python -m saqbol.eval splits --corpus data/corpus --out data/kazscam_v0.1 --seed {manifest["seed"]}` on {manifest["built_at"]}. One JSONL per split in the shape of docs/02_DATA_CONTRACTS.md section 6, plus `text_sha256` (what the leakage rules key on) and `corpus_id` (the collection record the row came from). `manifest.json` records the seed, the counts and every group of rows that had to travel together.

| Split | Rows | Source groups | By label | By lang | Hard negatives |
|---|---|---|---|---|---|
{counts}

Rows that share a source article, a translation or variant key, or near-identical text are one source group and carry the same `source_group`. A split with far fewer groups than rows holds less independent evidence than its row count suggests.

- `dev` holds every row the system was developed against, as listed in `data/exposure.json`, and every row grouped with one. A number computed on `dev` is a development number and is never reported as a test result (docs/15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md).
- {calibration_line}
- {manifest["excluded_fragments"]} `phrase_fragment` rows were excluded; fragments never enter a message split.
- {groups["n_multi_row_groups"]} groups of {groups["rows_in_multi_row_groups"]} rows (one source article, parallel translations, variant groups, near-duplicates) were assigned as units.
- {SYNTHETIC_NOTE}

Leakage checks over these files live in `tests/test_splits.py`.
"""


def write_splits(
    build: SplitBuild,
    out_dir: str | os.PathLike[str],
    *,
    corpus_commit: str | None = None,
    built_at: str | None = None,
) -> dict[str, Any]:
    """Write one JSONL per split, `manifest.json` and `README.md`. Returns the manifest."""
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    for name in SPLIT_NAMES:
        rows = build.splits.get(name, [])
        with (destination / f"{name}.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                ordered = {key: row.get(key) for key in ROW_FIELDS}
                handle.write(json.dumps(ordered, ensure_ascii=False) + "\n")

    manifest: dict[str, Any] = {
        "dataset_version": DATASET_VERSION,
        "status": "provisional",
        "built_at": built_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **build.report,
        "files": {name: f"{name}.jsonl" for name in SPLIT_NAMES},
        "notes": [PROVISIONAL_NOTE, SYNTHETIC_NOTE],
    }
    if corpus_commit:
        manifest["corpus_commit"] = corpus_commit
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    (destination / "README.md").write_text(_readme(manifest), encoding="utf-8", newline="\n")
    return manifest


def build_and_write(
    corpus_dir: str | os.PathLike[str],
    out_dir: str | os.PathLike[str],
    *,
    seed: int,
    calibration_size: int | None = None,
    max_calibration_fraction: float = DEFAULT_MAX_CALIBRATION_FRACTION,
    exposure_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Read the corpus, build the splits, write the directory. Returns the manifest.

    The exposure register is `exposure_path`, or `exposure.json` beside the
    corpus directory when that exists. A register named explicitly must exist.
    """
    rows = load_corpus(corpus_dir)
    register_path = Path(exposure_path) if exposure_path is not None else None
    if register_path is None:
        default = Path(corpus_dir).parent / EXPOSURE_FILENAME
        register_path = default if default.is_file() else None
    exposed: set[str] = set()
    if register_path is not None:
        exposed = exposed_corpus_ids(rows, load_exposure(register_path))
    build = assemble(
        rows,
        seed=seed,
        exposed_ids=exposed,
        calibration_size=calibration_size,
        max_calibration_fraction=max_calibration_fraction,
    )
    build.report["exposure_register"] = register_path.as_posix() if register_path else None
    return write_splits(build, out_dir, corpus_commit=git_commit())
