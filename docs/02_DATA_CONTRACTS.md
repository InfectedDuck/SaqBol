# SaqBol — Data contracts

Every schema in one place. Lock these before writing code. Changing a contract mid-build is the main source of wasted hours.

---

## 1. Core domain types

```python
# src/saqbol/core/types.py
from __future__ import annotations
from enum import StrEnum
from pydantic import BaseModel, Field


class Lang(StrEnum):
    RU = "ru"; KK = "kk"; EN = "en"; ZH = "zh"; MIXED = "mixed"; UNKNOWN = "unknown"


class Band(StrEnum):
    SCAM = "scam"
    SUSPICIOUS = "suspicious"
    UNSURE = "unsure"
    LIKELY_SAFE = "likely_safe"


class Stage(StrEnum):
    """Where the victim is inside the script. Only set for multi-message threads."""
    CONTACT    = "contact"      # first approach
    HOOK       = "hook"         # the story that creates attention
    TRUST      = "trust"        # credentials, fake documents, transfer to "officer"
    PRESSURE   = "pressure"     # urgency, threat, secrecy
    EXTRACTION = "extraction"   # asking for code / transfer / install
    CASHOUT    = "cashout"      # money already moving


class Severity(StrEnum):
    CRITICAL = "critical"   # weight 40
    HIGH     = "high"       # weight 25
    MEDIUM   = "medium"     # weight 12
    LOW      = "low"        # weight 5


SEVERITY_WEIGHT = {
    Severity.CRITICAL: 40, Severity.HIGH: 25,
    Severity.MEDIUM: 12,   Severity.LOW: 5,
}


class EvidenceSpan(BaseModel):
    """Character offsets into the NORMALIZED text. Must be verified to match."""
    start: int
    end: int
    text: str
    indicator_id: str          # e.g. "A1.otp_request"


class IndicatorHit(BaseModel):
    indicator_id: str
    severity: Severity
    spans: list[EvidenceSpan] = Field(default_factory=list)
    detail: dict = Field(default_factory=dict)   # e.g. {"lookalike_of": "kaspi.kz", "distance": 1}


class Entities(BaseModel):
    urls: list[str] = []
    resolved_urls: dict[str, str] = {}     # short → final
    phones: list[str] = []
    short_codes: list[str] = []            # 1414, 96110, bank codes
    card_numbers: list[str] = []           # masked immediately after detection
    iins: list[str] = []                   # KZ national ID, masked
    amounts: list[str] = []
    crypto_addresses: list[str] = []
    app_names: list[str] = []              # AnyDesk, TeamViewer, ...
    has_apk: bool = False
    qr_payloads: list[str] = []


class AnalysisInput(BaseModel):
    text: str | None = None
    image_b64: str | None = None
    surface: str                            # "telegram" | "web" | "api"
    lang_hint: Lang | None = None
    consent_dataset: bool = False
    thread: list[str] = []                  # prior messages, oldest first


class Components(BaseModel):
    rule_norm: float
    retrieval_sim: float
    llm_conf: float
    self_consistency: float | None = None


class Verdict(BaseModel):
    check_id: str
    band: Band
    risk: float                             # 0..1
    playbook_id: str | None
    playbook_confidence: float
    stage: Stage | None = None
    indicators: list[IndicatorHit] = []
    evidence: list[EvidenceSpan] = []
    action_key: str                         # i18n key, e.g. "action.hang_up_call_bank"
    hotline: str                            # "1414" | "96110" | bank number
    language: Lang
    components: Components
    abstained_because: str | None = None    # "disagreement" | "low_self_consistency"
    model: str
    latency_ms: int
    cached: bool = False
```

### Invariant to unit-test

Every `EvidenceSpan` must satisfy `normalized_text[span.start:span.end] == span.text`. Assert this in `fuse.py` and raise in tests. This single check is what makes the explainability claim real rather than decorative.

---

## 2. LLM structured output

The LLM never returns prose. It returns exactly this, enforced by pydantic through the provider's JSON-schema mode.

```python
class LLMJudgement(BaseModel):
    playbook_id: str | None      # MUST be one of the retrieved candidate IDs, or null
    confidence: float            # 0..1
    stage: Stage | None
    evidence_quotes: list[str]   # verbatim substrings of the input; resolved to spans afterwards
    reasoning: str               # <= 300 chars, for the design doc and error analysis, not shown to users
```

Rules enforced in code after the call, not trusted from the model:

1. `playbook_id` not in candidates → set to `None`, log a `schema_violation` metric.
2. Every `evidence_quotes` entry that is not a substring of the normalized input is **dropped**. If more than half are dropped, halve `confidence`.
3. The user-facing action text comes from the playbook YAML, never from the model. The model picks the playbook; the playbook supplies the advice.

Rule 3 is a safety property. A hallucinated phone number in scam advice is the worst failure this product can have.

---

## 3. Playbook YAML

One file per playbook in `src/saqbol/playbooks/data/`. Validated by `schema.py` at load time and in CI.

```yaml
# src/saqbol/playbooks/data/kz.bank_security_call.yaml
id: kz.bank_security_call
version: 1
region: KZ
family: authority_impersonation

name:
  ru: "Звонок «службы безопасности банка»"
  kk: "«Банк қауіпсіздік қызметінен» қоңырау"
  en: "Fake bank security service call"
  zh: "冒充银行安全部门来电"

summary:
  ru: "Звонящий представляется сотрудником банка и говорит, что с вашего счёта пытаются списать деньги."
  kk: "..."      # translated in week 2 by co-annotators
  en: "..."
  zh: "..."

# Phrases used ONLY for embedding/retrieval. Not shown to users.
retrieval_phrases:
  - "служба безопасности банка"
  - "с вашего счёта пытаются списать деньги"
  - "переведите средства на безопасный счёт"
  - "назовите код из СМС"
  - "не кладите трубку, я вас соединю со следователем"
  - "банк қауіпсіздік қызметі"

# Which indicators typically co-occur. Used for a consistency check, not for scoring.
expected_indicators: [C1.bank_security, A1.otp_request, E1.safe_account, B1.urgency, J1.secrecy]

stages:
  contact:    { ru: "Входящий звонок или WhatsApp-звонок с незнакомого номера." }
  hook:       { ru: "«С вашего счёта пытаются списать сумму»." }
  trust:      { ru: "Называет ваше ФИО, переключает на «следователя», присылает «удостоверение»." }
  pressure:   { ru: "«Не кладите трубку», «это тайна следствия», «никому не говорите»." }
  extraction: { ru: "Просит код из СМС, полные данные карты, или перевод на «безопасный счёт»." }
  cashout:    { ru: "Деньги переведены или оформлен кредит." }

red_flags:
  ru:
    - "Настоящий банк никогда не просит код из СМС."
    - "«Безопасного счёта» не существует."
    - "Просьба не класть трубку — это способ помешать вам перезвонить."
  kk: ["..."]

action:
  key: action.hang_up_call_bank
  ru: "Положите трубку. Перезвоните в банк по номеру на обороте карты — не по тому, что вам назвали."
  kk: "..."
hotline: "1414"                 # eGov; bank-specific numbers listed in `hotlines`
hotlines:
  - { name: "Kaspi", number: "+7 727 330 00 00" }
  - { name: "eGov", number: "1414" }
  - { name: "Полиция", number: "102" }

sources:
  - https://www.gov.kz/...          # official warning
  - https://...                     # press article
```

Loader requirements:

- Fail loudly on a missing required field. A silently half-loaded playbook produces bad advice.
- `id` must match the filename.
- Embed `summary.ru + retrieval_phrases` with `multilingual-e5-small`, store in `playbooks.embedding`.
- Bump `version` whenever text changes; the verdict records which version answered.

---

## 4. Database schema

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- One row per analysis. text is purged after 30 days; hash is kept.
CREATE TABLE checks (
    id              UUID PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    surface         TEXT NOT NULL,             -- telegram | web | api
    input_type      TEXT NOT NULL,             -- text | image | forward
    lang            TEXT NOT NULL,
    text_sha256     TEXT NOT NULL,
    text_scrubbed   TEXT,                      -- NULL after retention purge
    verdict         JSONB NOT NULL,
    playbook_id     TEXT,
    band            TEXT NOT NULL,
    risk            REAL NOT NULL,
    model           TEXT NOT NULL,
    latency_ms      INTEGER NOT NULL,
    cost_usd        NUMERIC(10,6),
    consent_dataset BOOLEAN NOT NULL DEFAULT FALSE,
    actor_hash      TEXT NOT NULL              -- HMAC(tg_user_id | ip), never the raw value
);
CREATE INDEX ON checks (created_at);
CREATE INDEX ON checks (text_sha256);
CREATE INDEX ON checks (playbook_id);

-- "Was this right?" votes. Feeds the review queue, never the dataset directly.
CREATE TABLE feedback (
    id          BIGSERIAL PRIMARY KEY,
    check_id    UUID REFERENCES checks(id) ON DELETE CASCADE,
    was_correct BOOLEAN,
    comment     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Human-reviewed queue on the way into KazScam.
CREATE TABLE dataset_candidates (
    id             BIGSERIAL PRIMARY KEY,
    check_id       UUID REFERENCES checks(id),
    text_scrubbed  TEXT NOT NULL,
    source         TEXT NOT NULL,      -- press | donated | synthetic
    source_url     TEXT,               -- required when source = 'press'
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    reviewer       TEXT,
    reviewed_at    TIMESTAMPTZ,
    reject_reason  TEXT
);

CREATE TABLE playbooks (
    id         TEXT PRIMARY KEY,
    version    INTEGER NOT NULL,
    content    JSONB NOT NULL,
    embedding  VECTOR(384) NOT NULL
);
CREATE INDEX ON playbooks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE rate_limits (
    actor_hash TEXT NOT NULL,
    day        DATE NOT NULL,
    count      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (actor_hash, day)
);

-- Materialized nightly for the public stats page. Never exposes text.
CREATE TABLE stats_daily (
    day             DATE PRIMARY KEY,
    checks          INTEGER NOT NULL,
    unique_actors   INTEGER NOT NULL,
    scam_count      INTEGER NOT NULL,
    unsure_count    INTEGER NOT NULL,
    top_playbook    TEXT
);
```

`actor_hash` is `HMAC-SHA256(secret, telegram_user_id or client_ip)`. Raw identifiers never touch the disk. Say this in PRIVACY.md.

---

## 5. HTTP API

```
POST /api/v1/analyze
  body: AnalysisInput
  200:  Verdict
  429:  {"error": "rate_limited", "retry_after": 3600}
  413:  image over 5 MB

POST /api/v1/feedback
  body: {check_id: str, was_correct: bool, comment: str | null}
  204

GET  /api/v1/stats
  200: {total_checks, unique_users, scam_share, days: [...], updated_at}

GET  /api/v1/playbooks            # public library, powers SEO pages
GET  /api/v1/playbooks/{id}

GET  /healthz                     # 200 with db + llm reachability booleans
```

Limits: 10 checks per `actor_hash` per day, 5 MB image, 8000 characters of text. Cloudflare Turnstile on the web form after the third check in a session.

---

## 6. KazScam dataset row

Released on Hugging Face as JSONL, one file per split.

```json
{
  "id": "kazscam-000417",
  "text": "Здравствуйте, это служба безопасности Kaspi. С вашего счёта пытаются списать 480 000 тг...",
  "label": "scam",
  "playbook_id": "kz.bank_security_call",
  "stage": "hook",
  "lang": "ru",
  "lang_secondary": null,
  "is_code_switched": false,
  "channel": "whatsapp",
  "source": "press",
  "source_url": "https://...",
  "collected_at": "2026-09-19",
  "annotator_a": "scam/kz.bank_security_call",
  "annotator_b": "scam/kz.bank_security_call",
  "adjudicated": false,
  "hard_negative": false,
  "scrub_applied": ["phone", "amount_kept", "name"],
  "source_group": "kazscam-000416"
}
```

Label set: `scam` | `legit` | `ambiguous`. Playbook ID only when `label == scam`: one of the thirteen playbooks, `other_scam`, or null when the script was not named.

`annotator_a` and `annotator_b` are the two readings of the row, one per annotator, written as the label, with the script after a slash where the annotator named one: `scam/kz.delivery_link`, `scam`, `legit`, `ambiguous`. Both are null on a row that has not been annotated, and `label` is then the collector's provisional reading. `adjudicated` is true where the two readings differed and a logged decision set the label. `stage` is null unless the row is a multi-message thread; the labelling page never asks for it.

`source_group` is the `id` of the first row of the row's source group. Rows that share a source article, a parallel-pair or variant key, or near-identical text are one group and carry the same value; a row with no such relative carries its own `id`. A group is one piece of evidence however many rows it holds, so the evaluation prints the number of groups beside every row count. The split files carry two more fields after it for tracing: `text_sha256`, which the leakage rules are stated in, and `corpus_id`, the collection record the row came from.

### Splits

| Split | Contents | Used for |
|---|---|---|
| `train_synthetic` | LLM paraphrases of `dev` rows | Training and prompt development only. **Never** in a reported metric. |
| `dev` | Every row the system was developed against, listed in `data/exposure.json`, plus any row grouped with one | Writing rules and prompts, the annotation pilot, error analysis. Reported only as development numbers. |
| `calibration` | A stratified slice of fresh press rows, cut only when at least 250 exist: 20% of them, between 50 and 75 rows | Tuning fusion weights and abstention thresholds. Reported separately. |
| `test_press` | Fresh rows from public warnings and press | Headline leaderboard number |
| `test_donated` | Consented user submissions | Held out. Second table. Shows real-world drift. |

A row is *fresh* when no development session read it before the system was frozen. With fewer than 250 fresh press rows there is no `calibration` split: thresholds are fitted on `dev` and the run is labelled `dev-calibrated`. The reasoning and the reporting minimums are in [15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md](15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md).

Hard negatives live in every split, flagged by `hard_negative: true`; the reported false-positive rate uses the ones in `test_press` and `test_donated`. They are legitimate messages that look like scams: real 1414 codes, Kazpost tracking SMS, Kaspi promotions, Halyk login alerts, genuine OLX buyer chats. False-positive rate on this subset is a headline metric because a tool that flags a real bank SMS gets uninstalled.

**Leakage rules**, checked by a test in CI:

- No `text_sha256` appears in two splits.
- No synthetic row shares a source row with any test row.
- The calibration split is disjoint from every test split.
- Rows that share a source article, a parallel-pair or variant key, or near-identical text are one group, and a group is never divided between splits.
- No row listed in `data/exposure.json`, and no row grouped with one, appears in `calibration`, `test_press` or `test_donated`.

### Label records

The annotators' answers reach the splits through label records: one JSON file per annotation batch in `data/labels/`, written by `tools/labels.py merge` and read by the split builder. Nothing else sets `label`, `playbook_id`, `annotator_a`, `annotator_b` or `adjudicated` on a released row.

```json
{
  "schema": "kazscam-labels/1",
  "batch": "batch-annot-01",
  "created_at": "2027-01-15",
  "kind": "inter-annotator",
  "annotators": {"a": "annotator-1", "b": "annotator-2"},
  "rows": [
    {
      "corpus_id": "ks-press-03-014",
      "text_sha256": "9f2c…",
      "annotator_a": "scam/kz.delivery_link",
      "annotator_b": "scam/kz.fake_store",
      "label": "scam",
      "playbook_id": "kz.delivery_link",
      "adjudicated": true,
      "reason": "The payment page sits behind a parcel notice; the payload decides.",
      "decided_by": "discussion"
    }
  ],
  "not_labelled": ["ks-press-03-020"]
}
```

A row is keyed by `corpus_id`, because released ids are renumbered whenever the corpus grows, and by `text_sha256`, so a label cannot follow a text that was edited after it was read. The build stops on a digest that does not match.

How two readings become a label:

| The two readings | Result |
|---|---|
| Same label, same script (or neither named one) | That label and script. `adjudicated: false`, no reason |
| Different label | A decision is required |
| Both `scam`, different scripts, or one named a script and the other did not | A decision is required |

A decision gives a label from the label set, a script (only with `scam`, and it may be null), a one-line `reason` and `decided_by`: a third annotator's name or `discussion`. It may be any label, not only one of the two readings. `merge` refuses to write a record while a decision is missing, and a record whose label does not follow from its readings by this table does not load. The same row may not appear in two records.

`not_labelled` lists batch items that have fewer than two readings, for example an item an annotator skipped. Those rows keep the collector's label and null annotator fields.

`annotators` names who is behind each column. The labelling page derives an annotator's id from the name they typed, so `merge` takes a pseudonym for each annotator, and the record should carry the pseudonym unless the annotator agreed to be named.

`kind` is `inter-annotator` when the two columns are two people, and `intra-annotator` when they are two passes by one person, made at least two weeks apart and blind to each other (the fallback in the roadmap when no second annotator is found). The resolution rule is the same. The manifest lists the rows whose readings are two passes, so that agreement on them is never reported as agreement between annotators.

A build records in `manifest.json` how many rows of each split carry two readings. `status` is `annotated` only when every row of every split does, and `provisional` otherwise. A hard negative whose final label is not `legit` loses the flag and is listed in the manifest. The leaderboard publishes no test number while any `test_press` row lacks two readings.

---

## 7. Eval results format

`eval/results/results.json`, committed so the leaderboard is reproducible and diffable.

```json
{
  "run_id": "2026-09-26T14:02Z",
  "dataset_version": "kazscam-v0.1",
  "n_bootstrap": 10000,
  "rows": [
    {
      "system": "hybrid",
      "model": "deepseek-v3",
      "split": "test_press",
      "lang": "kk",
      "ablation": "none",
      "macro_f1": 0.781,
      "ci95": [0.724, 0.833],
      "n": 148,
      "fpr_hard_negative": 0.061,
      "abstain_rate": 0.093
    }
  ]
}
```

`leaderboard.md` is generated from this file, never hand-edited. Systems: `rules_only`, `llm_zeroshot`, `hybrid`. Ablations: `none`, `translated`, `cue_masked`, `no_playbook_context`.

The harness writes more than the fields above, and a reader keeps keys it does not know. Some of the additions decide what the leaderboard may print:

| Where | Key | Meaning |
|---|---|---|
| Row | `n_rows` | Rows in the cell. `n` is the number of them the macro-F1 was computed on |
| Row | `n_by_label` | Rows in the cell per gold label |
| Row | `n_hard_negative` | Hard negatives in the cell; absent when there are none |
| Row | `n_source_groups` | Distinct `source_group` values in the cell; absent unless every row names its group |
| Top level | `split_support` | Per split that was read: `n_rows`, `by_label`, `by_lang`, `n_hard_negative`, `n_source_groups` |
| Top level | `limit` | The `--limit` the run was given; absent on a full run |

`results.json` holds every number the harness computed. The leaderboard applies the minimum-support rules of [15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md](15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md) section 7 to these counts: a number under its floor prints as `not reported`, and the size of `test_press` sets the release tier (`none`, `pilot` or `benchmark`) printed in the header. A count that is missing is treated as a count that is too small.

State in the README: no "X beats Y" claim without non-overlapping confidence intervals.
