#!/usr/bin/env python3
"""Collection helper for the KazScam corpus (T403).

Turns a source URL plus verbatim message text into a corpus row in the exact
shape ``tools/annotate.html`` consumes, and refuses rows that duplicate text
already in the corpus.

Why the duplicate check matters: a single police or bank warning is reprinted
across a dozen news sites, so naive collection lands the same message under
several URLs. If those copies land in different splits, the leakage tests in
``docs/05_EVAL_PROTOCOL.md`` fire and the whole release is suspect. So every
row is checked twice, exact on a normalized form and fuzzy on character
shingles, before it is written.

It also screens every new row against development data. The system was
written while reading the batches listed in ``data/exposure.json``, so a row
that repeats one of them, shares its article or is a variant of it cannot be a
test row (``docs/15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md``, section 4).
A batch collected before the tag ``system-freeze-v0.1`` exists is development
data too, and has to be collected with ``--dev``.

This module deliberately does not scrub PII. T405 owns scrubbing. What it does
is *flag* rows containing a phone number, an IIN, a card number or an email, so
the scrubber gets a checklist instead of a haystack.

Stdlib only, so it runs without the project venv.

Usage
-----
  # one row
  python tools/collect.py add --url https://example.kz/news/1 \
      --text-file msg.txt --lang ru --provenance press \
      --label scam --channel sms --batch official-01

  # many rows from a staging file (a list of draft objects)
  python tools/collect.py ingest staging.json --batch press-01

  # before the system freeze every new batch is development data
  python tools/collect.py ingest staging.json --batch press-03 --dev

  # validation and duplicate sweep over everything collected so far
  python tools/collect.py check --stats

  # paste-ready block for the labelling tool's import box
  python tools/collect.py paste --batch press-01
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "data" / "corpus"
# Which batches and single rows the system was developed against. The split
# builder reads the same file and sends everything it names to `dev`.
EXPOSURE_PATH = ROOT / "data" / "exposure.json"
# Rows collected after this tag are the only ones that can be test rows.
FREEZE_TAG = "system-freeze-v0.1"

# `provenance` answers "how did this row reach us", which is the question a
# release reviewer asks. `source` on the emitted item mirrors it, because
# annotate.html renders item.source as the chip an annotator sees.
PROVENANCE = ("press", "official_warning", "donated")
LABELS = ("scam", "legit")
LANGS = ("kk", "ru", "kk-ru", "en")
CHANNELS = (
    "sms",
    "call",
    "whatsapp",
    "telegram",
    "instagram",
    "email",
    "push",
    "web",
    "marketplace",
    "unknown",
)

# Kazakhstani sources very often quote a scam's *cue phrase* ("картаңыз
# бұғатталды") rather than the whole message. Those quotes are real and
# sourced, but a three-word stub is not a message and must never sit in a
# message split, so it is carried as a separate kind and filtered on export.
TEXT_KINDS = ("message", "phrase_fragment")

NEAR_DUP_THRESHOLD = 0.85
# Between this and NEAR_DUP_THRESHOLD a new row may be a reworded copy of a
# development row. A person has to say which; the tool will not guess.
REVIEW_THRESHOLD = 0.50
SIMILAR_DECISIONS = ("variant", "distinct")
SHINGLE = 5

# ---------------------------------------------------------------------------
# normalization and hashing
# ---------------------------------------------------------------------------

_URL_RE = re.compile(
    r"https?://\S+|(?:www\.)?[a-z0-9-]+\.(?:kz|com|ru|info|site|top|xyz|net|org)\b/?\S*",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")
_NONWORD_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_text(text: str) -> str:
    """Fold a message down to what is left when formatting stops mattering.

    Case, punctuation, URL spelling and whitespace all vary between reprints of
    the same warning, so none of them may participate in identity.
    """
    s = unicodedata.normalize("NFKC", text).lower()
    s = _URL_RE.sub(" url ", s)
    s = _NONWORD_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s)
    return s.strip()


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:16]


def _shingles(norm: str, n: int = SHINGLE) -> set[str]:
    packed = norm.replace(" ", "")
    if len(packed) < n:
        return {packed} if packed else set()
    return {packed[i : i + n] for i in range(len(packed) - n + 1)}


def similarity(a: str, b: str) -> float:
    """Jaccard over character shingles of the normalized texts."""
    sa, sb = _shingles(normalize_text(a)), _shingles(normalize_text(b))
    if not sa or not sb:
        return 1.0 if sa == sb else 0.0
    return len(sa & sb) / len(sa | sb)


# ---------------------------------------------------------------------------
# PII flagging (flag only, never scrub -- T405 owns scrubbing)
# ---------------------------------------------------------------------------

PII_PATTERNS: dict[str, re.Pattern[str]] = {
    # +7 700 000 00 00 / 8(701)0000000 / 87010000000
    "phone": re.compile(r"(?:\+7|\b8)[\s\-()]*7\d{2}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}\b"),
    "short_code": re.compile(r"\b(?:1414|1408|141\d)\b"),
    # IIN / BIN: exactly 12 digits standing alone
    "iin": re.compile(r"(?<!\d)\d{12}(?!\d)"),
    "card": re.compile(r"(?<!\d)(?:\d{4}[\s\-]?){3}\d{4}(?!\d)"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"),
    "handle": re.compile(r"(?<![\w/])@[A-Za-z][A-Za-z0-9_]{3,}\b"),
    "iban": re.compile(r"\bKZ\d{2}[A-Z0-9]{16}\b"),
}


def flag_pii(text: str) -> list[str]:
    """Return the PII kinds present, sorted. Never modifies the text."""
    return sorted(k for k, pat in PII_PATTERNS.items() if pat.search(text))


# ---------------------------------------------------------------------------
# corpus io
# ---------------------------------------------------------------------------


def batch_path(batch: str) -> Path:
    return CORPUS_DIR / f"batch-{batch}.json"


def load_batch(batch: str) -> dict[str, Any]:
    path = batch_path(batch)
    if not path.exists():
        return {"batch": batch, "created_at": _now(), "items": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_batch(data: dict[str, Any]) -> Path:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    path = batch_path(data["batch"])
    data["updated_at"] = _now()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_all_rows(exclude: str | None = None) -> list[dict[str, Any]]:
    """Every row already collected, across every batch. The dedupe universe."""
    rows: list[dict[str, Any]] = []
    if not CORPUS_DIR.exists():
        return rows
    for path in sorted(CORPUS_DIR.glob("batch-*.json")):
        if exclude and path == batch_path(exclude):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            print(f"  ! {path.name}: unreadable ({err})", file=sys.stderr)
            continue
        for item in data.get("items", []):
            item["_batch"] = data.get("batch", path.stem)
            rows.append(item)
    return rows


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# row construction
# ---------------------------------------------------------------------------


class RowError(ValueError):
    """A draft that must not become a row."""


def make_row(
    *,
    text: str,
    source_url: str,
    provenance: str,
    lang: str,
    label: str,
    access_date: str,
    channel: str = "unknown",
    publisher: str = "",
    source_title: str = "",
    hard_negative: bool = False,
    is_code_switched: bool | None = None,
    verbatim: bool = True,
    text_kind: str = "message",
    notes: str = "",
    row_id: str = "",
) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise RowError("empty text")
    if text_kind not in TEXT_KINDS:
        raise RowError(f"text_kind must be one of {TEXT_KINDS}, got {text_kind!r}")
    if provenance not in PROVENANCE:
        raise RowError(f"provenance must be one of {PROVENANCE}, got {provenance!r}")
    if lang not in LANGS:
        raise RowError(f"lang must be one of {LANGS}, got {lang!r}")
    if label not in LABELS:
        raise RowError(f"label must be one of {LABELS}, got {label!r}")
    if channel not in CHANNELS:
        raise RowError(f"channel must be one of {CHANNELS}, got {channel!r}")
    if not verbatim:
        raise RowError("only verbatim text may enter the corpus")
    # Provenance is the whole point of the release: a donated row has no URL,
    # everything else must have one.
    if provenance != "donated" and not source_url.startswith("http"):
        raise RowError(f"{provenance} rows need a source_url, got {source_url!r}")
    try:
        date.fromisoformat(access_date)
    except ValueError as err:
        raise RowError(f"access_date must be ISO yyyy-mm-dd: {err}") from err

    pii = flag_pii(text)
    code_switched = bool(is_code_switched) if is_code_switched is not None else lang == "kk-ru"
    return {
        "id": row_id or "",
        "text": text,
        # annotate.html shows item.source as a chip; keep it equal to
        # provenance so an annotator can see where the row came from.
        "source": provenance,
        "provenance": provenance,
        "source_url": source_url,
        "source_title": source_title,
        "publisher": publisher or _domain(source_url),
        "access_date": access_date,
        "lang": lang,
        "is_code_switched": code_switched,
        "label": label,
        "hard_negative": bool(hard_negative),
        "channel": channel,
        "verbatim": True,
        "text_kind": text_kind,
        "pii_flags": pii,
        "needs_scrub": bool(pii),
        "scrub_applied": [],
        "text_hash": text_hash(text),
        "collected_at": _now(),
        "notes": notes,
    }


def _domain(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url)
    return m.group(1).lower() if m else ""


def assign_ids(data: dict[str, Any]) -> None:
    """Stable ids: ks-<batch>-NNN in insertion order."""
    for i, item in enumerate(data["items"], start=1):
        if not item.get("id"):
            item["id"] = f"ks-{data['batch']}-{i:03d}"


# ---------------------------------------------------------------------------
# duplicate detection
# ---------------------------------------------------------------------------


def find_duplicate(
    text: str, rows: list[dict[str, Any]]
) -> tuple[str, dict[str, Any], float] | None:
    """Exact-on-normalized first, then fuzzy. Returns (kind, row, score)."""
    h = text_hash(text)
    for row in rows:
        if row.get("text_hash") == h:
            return ("exact", row, 1.0)
    best: tuple[dict[str, Any], float] | None = None
    for row in rows:
        score = similarity(text, row.get("text", ""))
        if score >= NEAR_DUP_THRESHOLD and (best is None or score > best[1]):
            best = (row, score)
    if best:
        return ("near", best[0], best[1])
    return None


# ---------------------------------------------------------------------------
# screening against development data
# ---------------------------------------------------------------------------

# The next two functions mirror `saqbol.eval.splits`, which cannot be imported
# here because this script runs without the project venv. A test holds the two
# copies to the same answers.
_KEY_RE = re.compile(
    r"(?:parallel\s+pair\s+key|variant\s+group\s+key)\s*:\s*(?P<slug>[A-Za-z0-9_.\-]+)",
    re.IGNORECASE,
)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)


def group_keys(notes: str) -> list[str]:
    """The parallel-pair and variant-group slugs written in a notes field."""
    return sorted({m.group("slug").lower() for m in _KEY_RE.finditer(notes or "")})


def source_key(url: object) -> str:
    """What two rows quoted from the same article have in common, or "" for no source."""
    s = str(url or "").strip()
    if not s:
        return ""
    s = _SCHEME_RE.sub("", s.split("#", 1)[0]).casefold()
    if s.startswith("www."):
        s = s[4:]
    return s.rstrip("/")


def load_register() -> dict[str, Any]:
    """The exposure register, or an empty one if the file does not exist."""
    data: dict[str, Any] = {}
    if EXPOSURE_PATH.exists():
        data = json.loads(EXPOSURE_PATH.read_text(encoding="utf-8"))
    for key in ("exposed_batches", "exposed_ids", "log"):
        data.setdefault(key, [])
    return data


def register_exposure(*, batches: list[str] = (), ids: list[str] = (), reason: str) -> None:
    """Add batches or rows to the register, with a dated log entry. Never removes."""
    register = load_register()
    new_batches = [b for b in batches if b not in register["exposed_batches"]]
    new_ids = [i for i in ids if i not in register["exposed_ids"]]
    if not new_batches and not new_ids:
        return
    register["exposed_batches"] = sorted({*register["exposed_batches"], *new_batches})
    register["exposed_ids"] = sorted({*register["exposed_ids"], *new_ids})
    scope = []
    if new_batches:
        scope.append("batches " + ", ".join(new_batches))
    if new_ids:
        scope.append("rows " + ", ".join(new_ids))
    register["log"].append(
        {"date": date.today().isoformat(), "scope": "; ".join(scope), "reason": reason}
    )
    EXPOSURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPOSURE_PATH.write_text(
        json.dumps(register, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def is_dev(row: dict[str, Any], register: dict[str, Any]) -> bool:
    return (
        row.get("_batch") in register["exposed_batches"] or row.get("id") in register["exposed_ids"]
    )


def freeze_time() -> datetime | None:
    """When the freeze tag was made, or None if this checkout has no such tag."""
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "for-each-ref",
                "--format=%(creatordate:iso-strict)",
                f"refs/tags/{FREEZE_TAG}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    stamp = out.stdout.strip()
    if out.returncode != 0 or not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def screen(row: dict[str, Any], dev_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Where a new row belongs, judged against development rows and fragments.

    `pool` is "dev" when the row is tied to something the system was built on,
    "review" when a person has to decide, and "fresh" otherwise. A new message
    that merely contains a known cue phrase scores far below the review
    threshold and stays fresh, which is the generalisation the rules are
    supposed to show.
    """
    src = source_key(row.get("source_url"))
    if src:
        for other in dev_rows:
            if source_key(other.get("source_url")) == src:
                return {"pool": "dev", "rule": "same_source", "dev_id": other.get("id", "")}
    keys = set(group_keys(row.get("notes", "")))
    if keys:
        for other in dev_rows:
            shared = keys & set(group_keys(other.get("notes", "")))
            if shared:
                return {
                    "pool": "dev",
                    "rule": "shared_key",
                    "dev_id": other.get("id", ""),
                    "key": min(shared),
                }
    best: tuple[dict[str, Any], float] | None = None
    for other in dev_rows:
        score = similarity(row.get("text", ""), other.get("text", ""))
        if score >= REVIEW_THRESHOLD and (best is None or score > best[1]):
            best = (other, score)
    if best is None:
        return {"pool": "fresh"}
    other, score = best
    near = score >= NEAR_DUP_THRESHOLD
    return {
        "pool": "dev" if near else "review",
        "rule": "near_duplicate" if near else "similar",
        "dev_id": other.get("id", ""),
        "score": round(score, 3),
    }


class NeedsDecision(Exception):
    """A new row resembles a development row and nobody has said what it is."""

    def __init__(self, finding: dict[str, Any]) -> None:
        super().__init__(finding)
        self.finding = finding


def settle(row: dict[str, Any], dev_rows: list[dict[str, Any]], decision: str) -> dict[str, Any]:
    """Screen a row and apply the collector's decision where one is needed."""
    if decision and decision not in SIMILAR_DECISIONS:
        raise RowError(f"similar_to_dev must be one of {SIMILAR_DECISIONS}, got {decision!r}")
    finding = screen(row, dev_rows)
    if finding["pool"] != "review":
        return finding
    if decision == "variant":
        return {**finding, "pool": "dev", "decision": "variant"}
    if decision == "distinct":
        return {**finding, "pool": "fresh", "decision": "distinct"}
    raise NeedsDecision(finding)


def _describe(finding: dict[str, Any]) -> str:
    if finding["pool"] == "fresh" and "rule" not in finding:
        return "fresh"
    detail = f"{finding['rule']} {finding.get('dev_id', '')}".strip()
    if "score" in finding:
        detail += f" {finding['score']:.2f}"
    if "decision" in finding:
        detail += f", judged {finding['decision']}"
    return f"{finding['pool']}: {detail}"


def collecting_as_dev(batch: str, register: dict[str, Any], *, as_dev: bool) -> bool:
    """Whether rows added to this batch now are development data.

    Without the freeze tag there is no such thing as a test row, so the
    collector has to say out loud that the batch is development data.
    """
    if batch in register["exposed_batches"] or as_dev:
        return True
    if freeze_time() is None:
        raise RowError(
            f"there is no {FREEZE_TAG} tag, so a row collected now is development data. "
            f"Pass --dev to collect it as such; the batch is then added to "
            f"{EXPOSURE_PATH.name} and can never be a test batch."
        )
    return False


def _register_outcome(
    batch: str, register: dict[str, Any], *, batch_is_dev: bool, variants: list[tuple[str, str]]
) -> None:
    if batch_is_dev and batch not in register["exposed_batches"]:
        register_exposure(
            batches=[batch],
            reason=f"Collected as development data: --dev was given, or no {FREEZE_TAG} tag existed.",
        )
    for row_id, dev_id in variants:
        register_exposure(
            ids=[row_id],
            reason=f"Judged at collection to be a variant of the development row {dev_id}.",
        )


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_add(args: argparse.Namespace) -> int:
    text = Path(args.text_file).read_text(encoding="utf-8") if args.text_file else (args.text or "")
    row = make_row(
        text=text,
        source_url=args.url,
        provenance=args.provenance,
        lang=args.lang,
        label=args.label,
        access_date=args.access_date,
        channel=args.channel,
        publisher=args.publisher,
        source_title=args.title,
        hard_negative=args.hard_negative,
        verbatim=not args.paraphrase,
        text_kind=args.text_kind,
        notes=args.notes,
    )
    register = load_register()
    batch_is_dev = collecting_as_dev(args.batch, register, as_dev=args.dev)
    data = load_batch(args.batch)
    others = load_all_rows(exclude=args.batch)
    universe = others + data["items"]
    dup = find_duplicate(row["text"], universe)
    if dup and not args.allow_dup:
        kind, other, score = dup
        print(
            f"rejected: {kind} duplicate of {other.get('id')} "
            f"({other.get('_batch', args.batch)}, score {score:.2f})\n"
            f"  existing source: {other.get('source_url')}",
            file=sys.stderr,
        )
        return 2
    if batch_is_dev:
        finding: dict[str, Any] = {"pool": "dev", "rule": "dev_batch"}
    else:
        try:
            finding = settle(row, [r for r in others if is_dev(r, register)], args.similar_to_dev)
        except NeedsDecision as need:
            print(_undecided(need.finding, others), file=sys.stderr)
            return 2
    row["screening"] = finding
    data["items"].append(row)
    assign_ids(data)
    path = save_batch(data)
    variants = [(row["id"], finding["dev_id"])] if finding.get("decision") == "variant" else []
    _register_outcome(args.batch, register, batch_is_dev=batch_is_dev, variants=variants)
    flags = ",".join(row["pii_flags"]) or "none"
    print(f"added {row['id']} -> {path.relative_to(ROOT)}  [pii: {flags}]  [{_describe(finding)}]")
    if finding["pool"] == "dev" and not batch_is_dev:
        print(
            f"  note: {row['id']} is development data and will not be a test row",
            file=sys.stderr,
        )
    return 0


def _undecided(finding: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    other = next((r for r in rows if r.get("id") == finding["dev_id"]), {})
    preview = " ".join(str(other.get("text", "")).split())[:160]
    return (
        f"needs a decision: similarity {finding['score']:.2f} with the development row "
        f"{finding['dev_id']}\n"
        f"  that row: {preview}\n"
        f"  if this is the same message reworded, say variant; it becomes development data\n"
        f"  if it is a different message, say distinct; it stays a candidate test row\n"
        f'  (--similar-to-dev on `add`, "similar_to_dev" on a draft)'
    )


def cmd_ingest(args: argparse.Namespace) -> int:
    """Ingest a staging file: a JSON list of drafts, or {"items": [...]}.

    Each draft carries the keys ``make_row`` takes. Batch-level defaults may be
    set under ``defaults`` so a run of rows from one article does not repeat the
    URL and access date on every line.
    """
    raw = json.loads(Path(args.file).read_text(encoding="utf-8"))
    defaults: dict[str, Any] = {}
    if isinstance(raw, dict):
        defaults = raw.get("defaults", {})
        drafts = raw.get("items", [])
    else:
        drafts = raw

    register = load_register()
    batch_is_dev = collecting_as_dev(args.batch, register, as_dev=args.dev)
    data = load_batch(args.batch)
    others = load_all_rows(exclude=args.batch)
    dev_rows = [r for r in others if is_dev(r, register)]
    universe = others + data["items"]
    added = rejected = failed = undecided = to_dev = 0
    pending_variants: list[tuple[dict[str, Any], str]] = []
    for i, draft in enumerate(drafts, start=1):
        merged = {**defaults, **draft}
        try:
            row = make_row(
                text=merged.get("text", ""),
                source_url=merged.get("source_url", ""),
                provenance=merged.get("provenance", ""),
                lang=merged.get("lang", ""),
                label=merged.get("label", ""),
                access_date=merged.get("access_date", ""),
                channel=merged.get("channel", "unknown"),
                publisher=merged.get("publisher", ""),
                source_title=merged.get("source_title", ""),
                hard_negative=merged.get("hard_negative", False),
                is_code_switched=merged.get("is_code_switched"),
                verbatim=merged.get("verbatim", True),
                text_kind=merged.get("text_kind", "message"),
                notes=merged.get("notes", ""),
            )
        except RowError as err:
            print(f"  ! draft {i}: {err}", file=sys.stderr)
            failed += 1
            continue
        dup = find_duplicate(row["text"], universe)
        if dup:
            kind, other, score = dup
            print(
                f"  - draft {i}: {kind} duplicate of {other.get('id') or '(pending)'} "
                f"({score:.2f}) -- skipped",
                file=sys.stderr,
            )
            rejected += 1
            continue
        if batch_is_dev:
            finding: dict[str, Any] = {"pool": "dev", "rule": "dev_batch"}
        else:
            try:
                finding = settle(row, dev_rows, str(merged.get("similar_to_dev", "")))
            except RowError as err:
                print(f"  ! draft {i}: {err}", file=sys.stderr)
                failed += 1
                continue
            except NeedsDecision as need:
                print(f"  ? draft {i}: {_undecided(need.finding, others)}", file=sys.stderr)
                undecided += 1
                continue
            if finding["pool"] == "dev":
                print(f"  > draft {i}: development data ({_describe(finding)})", file=sys.stderr)
                to_dev += 1
        row["screening"] = finding
        if finding.get("decision") == "variant":
            pending_variants.append((row, finding["dev_id"]))
        data["items"].append(row)
        universe.append(row)
        added += 1

    assign_ids(data)
    if added:
        path = save_batch(data)
        _register_outcome(
            args.batch,
            register,
            batch_is_dev=batch_is_dev,
            variants=[(row["id"], dev_id) for row, dev_id in pending_variants],
        )
        print(f"{added} added -> {path.relative_to(ROOT)}")
    pool = "all development data" if batch_is_dev else f"{to_dev} of them development data"
    print(
        f"summary: added={added} ({pool}) duplicates={rejected} "
        f"invalid={failed} undecided={undecided}"
    )
    return 0 if failed == 0 and undecided == 0 else 1


def cmd_check(args: argparse.Namespace) -> int:
    """Validation and duplicate sweep over the whole corpus."""
    rows = load_all_rows()
    if not rows:
        print("corpus is empty")
        return 0

    problems = 0
    seen_ids: dict[str, str] = {}
    for row in rows:
        rid = row.get("id", "")
        where = row.get("_batch", "?")
        if rid in seen_ids:
            print(f"  ! duplicate id {rid} in {where} and {seen_ids[rid]}")
            problems += 1
        seen_ids[rid] = where
        for key in ("text", "provenance", "access_date", "lang", "label"):
            if not row.get(key):
                print(f"  ! {rid}: missing {key}")
                problems += 1
        if row.get("provenance") != "donated" and not row.get("source_url"):
            print(f"  ! {rid}: no source_url")
            problems += 1
        if "synthetic_seed" in (row.get("source", ""), row.get("provenance", "")):
            print(f"  ! {rid}: synthetic_seed must not appear in the corpus")
            problems += 1
        # tools/scrub_corpus.py keeps text_hash as the hash of the verbatim
        # text on purpose, so a re-collected copy is still caught as a
        # duplicate; a row whose text was changed by scrubbing is expected
        # to differ. A row scrubbed to no change must still match.
        scrubbed = bool(row.get("scrub_applied")) and bool(row.get("scrub_placeholders"))
        if not scrubbed and row.get("text_hash") != text_hash(row.get("text", "")):
            print(f"  ! {rid}: text_hash does not match text")
            problems += 1

    # pairwise near-duplicate sweep
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            score = similarity(rows[i].get("text", ""), rows[j].get("text", ""))
            if score >= NEAR_DUP_THRESHOLD:
                print(
                    f"  ! near-duplicate {score:.2f}: "
                    f"{rows[i].get('id')} ({rows[i].get('_batch')}) ~ "
                    f"{rows[j].get('id')} ({rows[j].get('_batch')})"
                )
                problems += 1

    problems += _check_pools(rows)

    n_pii = sum(1 for r in rows if r.get("needs_scrub"))
    print(f"\n{len(rows)} rows, {problems} problems, {n_pii} flagged for T405 scrubbing")
    if args.stats:
        _print_stats(rows)
    return 0 if problems == 0 else 1


def _check_pools(rows: list[dict[str, Any]]) -> int:
    """Hold the corpus to the holdout policy. Returns the number of problems.

    A row outside the exposure register is a candidate test row, so it has to
    have been collected after the freeze tag, and any resemblance to a
    development row has to have been ruled on.
    """
    register = load_register()
    dev_rows = [r for r in rows if is_dev(r, register)]
    fresh = [r for r in rows if not is_dev(r, register)]
    if not fresh:
        print(f"  pools: {len(dev_rows)} development rows, no candidate test rows")
        return 0

    problems = 0
    frozen_at = freeze_time()
    by_batch: dict[str, list[dict[str, Any]]] = {}
    for row in fresh:
        by_batch.setdefault(str(row.get("_batch", "?")), []).append(row)
    for batch, members in sorted(by_batch.items()):
        if frozen_at is None:
            print(
                f"  ! batch {batch}: {len(members)} rows are not in {EXPOSURE_PATH.name} "
                f"and there is no {FREEZE_TAG} tag, so they cannot be test rows"
            )
            problems += 1
            continue
        early = [r for r in members if _collected_before(r, frozen_at)]
        if early:
            print(
                f"  ! batch {batch}: {len(early)} rows were collected before {FREEZE_TAG} "
                f"or carry no collection time, and are not in {EXPOSURE_PATH.name}"
            )
            problems += 1

    to_dev = 0
    for row in fresh:
        finding = screen(row, dev_rows)
        if finding["pool"] == "dev":
            to_dev += 1
        elif finding["pool"] == "review":
            ruling = (row.get("screening") or {}).get("decision")
            if ruling != "distinct":
                print(
                    f"  ! {row.get('id')}: similarity {finding['score']:.2f} with the "
                    f"development row {finding['dev_id']} and no decision recorded"
                )
                problems += 1
    print(
        f"  pools: {len(dev_rows)} development rows, {len(fresh)} candidate test rows "
        f"({to_dev} of them tied to development data; the split builder sends those to dev)"
    )
    return problems


def _collected_before(row: dict[str, Any], moment: datetime) -> bool:
    try:
        stamp = datetime.fromisoformat(str(row.get("collected_at", "")))
    except ValueError:
        return True
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp <= moment


def _print_stats(rows: list[dict[str, Any]]) -> None:
    def tally(key: str) -> str:
        counts: dict[str, int] = {}
        for r in rows:
            counts[str(r.get(key))] = counts.get(str(r.get(key)), 0) + 1
        return ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))

    print(f"  label:      {tally('label')}")
    print(f"  lang:       {tally('lang')}")
    print(f"  provenance: {tally('provenance')}")
    print(f"  channel:    {tally('channel')}")
    print(f"  text_kind:  {tally('text_kind')}")
    print(f"  hard_neg:   {sum(1 for r in rows if r.get('hard_negative'))}")
    domains: dict[str, int] = {}
    for r in rows:
        domains[r.get("publisher") or "(donated)"] = (
            domains.get(r.get("publisher") or "(donated)", 0) + 1
        )
    print("  domains:")
    for d, n in sorted(domains.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {n:>3}  {d}")
    flags: dict[str, int] = {}
    for r in rows:
        for f in r.get("pii_flags", []):
            flags[f] = flags.get(f, 0) + 1
    if flags:
        print("  pii flags:  " + ", ".join(f"{k}={v}" for k, v in sorted(flags.items())))


def cmd_paste(args: argparse.Namespace) -> int:
    """Emit the block the labelling tool's import box accepts.

    annotate.html splits the box on a line containing exactly ``---`` and
    attaches one batch-level source string, so per-row provenance lives in the
    corpus JSON, not in the paste. Import one provenance at a time and set the
    source field to match.
    """
    rows = load_batch(args.batch)["items"] if args.batch else load_all_rows()
    if args.provenance:
        rows = [r for r in rows if r.get("provenance") == args.provenance]
    # Fragments are cue phrases, not messages; they are never sent to
    # annotators unless asked for explicitly.
    if not args.include_fragments:
        rows = [r for r in rows if r.get("text_kind", "message") == "message"]
    if not rows:
        print("no rows match", file=sys.stderr)
        return 1
    out = "\n---\n".join(r["text"].replace("\r\n", "\n").strip() for r in rows)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
        print(f"{len(rows)} rows -> {args.out}", file=sys.stderr)
    else:
        print(out)
    provs = sorted({r.get("provenance", "?") for r in rows})
    print(f"\n[set the import box source field to: {', '.join(provs)}]", file=sys.stderr)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    rows = load_all_rows()
    print(f"{len(rows)} rows in {CORPUS_DIR.relative_to(ROOT)}")
    if rows:
        _print_stats(rows)
    return 0


# ---------------------------------------------------------------------------


_DEV_HELP = "collect this batch as development data and add it to the exposure register"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="collect.py", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="add one row")
    a.add_argument("--text")
    a.add_argument("--text-file")
    a.add_argument("--url", default="")
    a.add_argument("--publisher", default="")
    a.add_argument("--title", default="")
    a.add_argument("--provenance", required=True, choices=PROVENANCE)
    a.add_argument("--lang", required=True, choices=LANGS)
    a.add_argument("--label", required=True, choices=LABELS)
    a.add_argument("--channel", default="unknown", choices=CHANNELS)
    a.add_argument("--access-date", default=date.today().isoformat())
    a.add_argument("--hard-negative", action="store_true")
    a.add_argument("--text-kind", default="message", choices=TEXT_KINDS)
    a.add_argument(
        "--paraphrase", action="store_true", help="marks text as not verbatim; always rejected"
    )
    a.add_argument("--notes", default="")
    a.add_argument("--batch", required=True)
    a.add_argument("--allow-dup", action="store_true")
    a.add_argument("--dev", action="store_true", help=_DEV_HELP)
    a.add_argument(
        "--similar-to-dev",
        default="",
        choices=("", *SIMILAR_DECISIONS),
        help="your ruling when the row resembles a development row",
    )
    a.set_defaults(func=cmd_add)

    i = sub.add_parser("ingest", help="add many rows from a staging JSON file")
    i.add_argument("file")
    i.add_argument("--batch", required=True)
    i.add_argument("--dev", action="store_true", help=_DEV_HELP)
    i.set_defaults(func=cmd_ingest)

    c = sub.add_parser("check", help="validate and sweep for duplicates")
    c.add_argument("--stats", action="store_true")
    c.set_defaults(func=cmd_check)

    q = sub.add_parser("paste", help="emit an import-box block")
    q.add_argument("--batch", default="")
    q.add_argument("--provenance", default="", choices=("", *PROVENANCE))
    q.add_argument("--out", default="")
    q.add_argument("--include-fragments", action="store_true")
    q.set_defaults(func=cmd_paste)

    s = sub.add_parser("stats", help="corpus composition")
    s.set_defaults(func=cmd_stats)
    return p


def main(argv: list[str] | None = None) -> int:
    # The corpus is Kazakh and Russian, and the default Windows console
    # codepage cannot encode either, so `paste` would die on its own output.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except RowError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
