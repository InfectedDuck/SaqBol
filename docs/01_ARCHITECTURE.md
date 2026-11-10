# SaqBol — Architecture

Status: **decided**. Nothing in this file is an open question. If you disagree with a choice, change it here first, then build. Do not re-decide during a coding session.

---

## 1. What the system does

One function, three surfaces.

```
analyze(input: Text | Screenshot | ForwardedMessage) -> Verdict
```

A `Verdict` answers four questions in the user's language:

1. Is this a scam? (`scam` / `suspicious` / `unsure` / `likely_safe`)
2. Which known scam script is it? (`playbook_id`, e.g. `kz.bank_security_call`)
3. Why? (evidence spans pointing at actual substrings of the message)
4. What do I do now? (one action + one phone number)

The fourth is the product. The first three are the research.

---

## 2. Non-negotiable design decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Hybrid: deterministic indicator engine **plus** grounded LLM. Never LLM-only. | The rules-only row on the leaderboard is what proves this is not an API wrapper. |
| D2 | The LLM is grounded in retrieved playbooks. It classifies into a closed set, it does not free-associate. | Makes output auditable and evaluable. Reduces hallucinated advice. |
| D3 | The system may answer `unsure`. Abstention is a first-class output. | Wrong "safe" verdicts cost a user money. An honest "unsure" costs nothing. |
| D4 | Evidence spans are character offsets into the input, verified to match. | Explainability that can be unit-tested, not a vibe. |
| D5 | Raw screenshots are never persisted. OCR text only, PII-scrubbed. | Privacy story, and it removes an entire class of legal risk. |
| D6 | Nothing in production depends on a VPN. | The demo and the China mode must work from a mainland China network. |
| D7 | v1 ships **text and screenshots only**. No voice, no APK analysis, no fine-tuning. | Scope creep is the biggest risk to a four-week build. These are named as future work. |
| D8 | Every number that appears in public has a confidence interval. | A number without a CI cannot be compared or trusted. |

---

## 3. Pipeline

```
                      ┌─────────────┐
  text / screenshot → │ 0 Normalize │  NFKC, strip zero-width, script mix, language ID
                      └──────┬──────┘
                             ▼
                      ┌─────────────┐
                      │ 1 Perceive  │  screenshots → vision model → text + speaker turns
                      └──────┬──────┘
                             ▼
                      ┌─────────────┐
                      │ 2 Extract   │  URLs, phones, short codes, cards, IIN, amounts, QR
                      └──────┬──────┘
                             ▼
              ┌──────────────┴──────────────┐
              ▼                             ▼
      ┌───────────────┐             ┌───────────────┐
      │ 3a Indicators │             │ 3b Retrieve   │  pgvector top-3 playbooks
      │  (rules, det.)│             │   playbooks   │
      └───────┬───────┘             └───────┬───────┘
              └──────────────┬──────────────┘
                             ▼
                      ┌─────────────┐
                      │ 4 LLM judge │  LangGraph node, forced pydantic schema
                      └──────┬──────┘
                             ▼
                      ┌─────────────┐
                      │ 5 Fuse      │  risk score + uncertainty → band (may override to unsure)
                      └──────┬──────┘
                             ▼
                      ┌─────────────┐
                      │ 6 Render    │  localized card (ru / kk / en / zh)
                      └─────────────┘
```

Stages 0, 2, 3a, 5 are pure Python and fully unit-testable with no network. That is where the test suite lives and where the "rules-only" leaderboard row comes from.

### Stage 5 in detail (the interesting part)

Three components, each in `[0, 1]`:

| Component | Source |
|---|---|
| `rule_norm` | `min(1.0, sum(indicator weights) / 100)` |
| `retrieval_sim` | cosine similarity of top-1 playbook |
| `llm_conf` | LLM's `confidence` field, or the mode share across self-consistency samples |

```python
risk = 0.45 * rule_norm + 0.20 * retrieval_sim + 0.35 * llm_conf
disagreement = abs(rule_norm - llm_conf)
```

Two corrections the implementation made to this draft, both in `fuse.py`:

**Disagreement is measured between the rules and the model only**, not across all three components. Retrieval similarity is an input to the model's judgement rather than a third opinion, and its scale is not calibrated against the other two: an unrelated message still sits at moderate cosine similarity to its nearest playbook. Including it made almost everything abstain.

**Absent components are dropped and the weights renormalised.** The `rules_only` baseline runs with no retrieval and no model. With a fixed divisor its risk would cap at 0.45 and it could never reach the scam band, making the baseline unbeatable by construction and the comparison meaningless.

Banding. The `suspicious` threshold was put to the calibration fit on 11 November 2026 and kept ([protocol section 7](05_EVAL_PROTOCOL.md)); the abstention thresholds are initial values until a model system is calibrated:

| Condition | Band |
|---|---|
| `disagreement > 0.40` | `unsure` (override) |
| `self_consistency_agreement < 0.60` | `unsure` (override) |
| `risk >= 0.70` | `scam` |
| `0.40 <= risk < 0.70` | `suspicious` |
| `risk < 0.40` | `likely_safe` |

The override rule is the abstention mechanism. It fires when the rules and the model disagree, which is exactly the case where a single-signal system silently fails. Report coverage and risk-at-coverage, not just accuracy.

**Cost control**: self-consistency (5 samples, temp 0.7) runs **only** when the single-pass `risk` lands in `[0.30, 0.75]`. Outside that band, one call. Cuts LLM spend by roughly two thirds on the observed distribution.

---

## 4. Stack

| Layer | Choice | Note |
|---|---|---|
| Language | Python 3.12 | Matches the EPAM capstone experience |
| API | FastAPI + uvicorn | |
| Orchestration | LangGraph | Already known; also a talking point |
| Validation | pydantic v2 | Structured LLM output is enforced here |
| DB | Postgres 16 + pgvector | One instance, also holds playbook embeddings |
| Bot | aiogram 3 | Async, same process family as FastAPI |
| Embeddings | `multilingual-e5-small` (local, CPU) | 384-dim, no API cost, handles kk/ru/zh |
| LLM primary | DeepSeek-V3 | Reachable from China, cheap, OpenAI-compatible |
| LLM secondary | Qwen3 (Alibaba Cloud International) | Reachable from China, strong on zh |
| LLM fallback | GPT-4o-mini via OpenRouter | For the leaderboard, not the hot path |
| Vision (OCR) | Qwen-VL | One call returns OCR text plus speaker attribution |
| Web | Next.js 15 + Tailwind | Matches Forge experience |
| Host | Hetzner CPX21, Falkenstein or Helsinki | Bot + API + DB on one box |
| Edge | Cloudflare proxy on `saqbol.app` | Keep a direct-IP hostname as China fallback |
| CI | GitHub Actions | pytest + ruff + smoke eval on recorded cassettes |

### Why not

- **Not `.kz`**: KazNIC requires Kazakhstan-hosted infrastructure. Buy `saqbol.app` or `saqbol.com`.
- **Not bare `*.vercel.app`**: blocked or unreliable from mainland China. The demo must load there.
- **Not WeChat Mini Program**: foreign-entity registration is a multi-week bureaucratic path. Not in a 4-week plan.
- **Not a fine-tuned XLM-R in v1**: GPU cost and time with no demo benefit. It is the v0.2 story.

---

## 5. Repository layout

```
saqbol/
├── README.md                    # GIF, one-command run, leaderboard table
├── LICENSE                      # MIT for code
├── PRIVACY.md  SECURITY.md  CONTRIBUTING.md
├── docker-compose.yml           # api + bot + postgres, `docker compose up`
├── pyproject.toml               # ruff, pytest, deps
├── .github/workflows/ci.yml
│
├── src/saqbol/
│   ├── core/
│   │   ├── normalize.py         # stage 0
│   │   ├── extract.py           # stage 2: entities
│   │   ├── indicators/
│   │   │   ├── registry.py      # ID → detector, weight, languages
│   │   │   ├── credentials.py   # family A
│   │   │   ├── urgency.py       # family B
│   │   │   ├── authority.py     # family C
│   │   │   ├── channel.py       # family D
│   │   │   ├── money.py         # family E
│   │   │   ├── software.py      # family F
│   │   │   ├── links.py         # family G  (+ url_analyzer.py)
│   │   │   ├── offers.py        # family H
│   │   │   ├── metadata.py      # family I
│   │   │   └── social.py        # family J
│   │   ├── url_analyzer.py      # sandboxed HEAD redirects, confusables, WHOIS
│   │   ├── retrieval.py         # pgvector top-k over playbooks
│   │   ├── llm.py               # multi-provider OpenAI-compatible client
│   │   ├── graph.py             # LangGraph verdict graph
│   │   ├── fuse.py              # stage 5, scoring + abstention
│   │   └── render.py            # stage 6, localized cards
│   ├── playbooks/
│   │   ├── schema.py            # pydantic model for a playbook
│   │   ├── loader.py
│   │   └── data/*.yaml          # 13 files, one per playbook
│   ├── api/
│   │   ├── main.py              # FastAPI app
│   │   ├── routes.py            # /analyze /feedback /stats /healthz
│   │   └── ratelimit.py
│   ├── bot/
│   │   ├── main.py              # aiogram entrypoint
│   │   ├── handlers.py
│   │   └── keyboards.py
│   ├── db/
│   │   ├── models.py            # SQLAlchemy
│   │   └── migrations/          # alembic
│   ├── i18n/
│   │   └── {ru,kk,en,zh}.yaml   # every user-visible string
│   └── eval/
│       ├── run.py               # CLI entrypoint
│       ├── metrics.py           # macro-F1, bootstrap CI, risk-coverage
│       ├── systems.py           # rules_only | llm_zeroshot | hybrid
│       └── ablations.py
│
├── tests/
│   ├── fixtures/                # 60 golden cases, no network
│   ├── test_indicators.py
│   ├── test_fuse.py
│   ├── test_url_analyzer.py
│   └── cassettes/               # recorded LLM responses for CI
│
├── data/
│   ├── raw/                     # gitignored, source URLs logged
│   ├── kazscam_v0.1/            # released splits
│   └── DATASHEET.md
│
├── eval/results/                # results.json + leaderboard.md, committed
│
├── web/                         # Next.js app
│   ├── app/[locale]/
│   ├── components/VerdictCard.tsx
│   └── ...
│
└── docs/
    ├── DESIGN_DECISIONS.md      # why each choice was made
    └── ANNOTATION_GUIDELINE.md
```

---

## 6. Deployment

> Sections 6 and 7 describe the deployment and budget planned in September 2026. The current plan uses free hosting tiers and a budget close to zero: see [the roadmap's budget section](10_REMAINING_ROADMAP.md#budget). The container layout below is still what `docker compose up` builds.

Single box, three containers, `docker compose up`.

```
Hetzner CPX21 (3 vCPU, 4 GB, ~€8/mo)
├── postgres:16 + pgvector    (volume-backed)
├── saqbol-api                (uvicorn, port 8000)
└── saqbol-bot                (aiogram long-polling, no public port)

Cloudflare → saqbol.app → :8000
Fallback:   api-direct.saqbol.app → origin IP, grey-cloud (no Cloudflare proxy)
```

Long-polling for the bot, not webhooks. It removes the need for inbound TLS on the bot and works identically in development.

**China reachability is a task, not an assumption** (T306). Test the domain from a mainland SIM and inside the WeChat in-app browser during week 2. If Cloudflare is slow, cut to the direct hostname.

---

## 7. Budget

| Item | Cost |
|---|---|
| Hetzner CPX21, 2 months | €16 |
| Domain `saqbol.app`, 1 year | €18 |
| Vision OCR (Qwen-VL), ~3k screenshots | ~$25 |
| LLM hot path (DeepSeek/Qwen), ~15k checks | ~$35 |
| Leaderboard reruns (4 models × splits × ablations, ×3 reruns) | ~$60 |
| Buffer | $40 |
| **Total** | **≈ $200** |

Pre-fund $100 on each of Alibaba Cloud International and OpenRouter in Day 0. A dead API key on demo day is the failure mode to design out.

---

## 8. Privacy and safety posture

- Consent on `/start` in Russian and Kazakh, plus a per-submission opt-in before any row enters the dataset.
- PII scrubbing: regex first (`+7` numbers, IIN, card PANs, emails, Telegram handles), Presidio second, human review of every released row.
- Raw images discarded after OCR. Only scrubbed text is retained.
- 30-day retention on `checks.text`; the SHA-256 hash is kept indefinitely for dedup and cache.
- User "was this right?" votes go to a **review queue**, never straight into the dataset. Self-labelled data is the first thing a reviewer attacks.
- The bot never asks for and never stores a phone number, card number, or code. State this in the `/start` message.
- Every China-mode playbook cites and routes to the official 96110 hotline first. The tool restates official guidance, it does not replace it.

---

## 9. Explaining the design

Keep `docs/DESIGN_DECISIONS.md` current. It should be enough to explain, at a whiteboard and without notes:

- why hybrid beats LLM-only, with the rules-only number to prove it
- how the abstention override works and what coverage it buys
- how the dataset splits avoid leakage (press / donated / synthetic are separate, synthetic is train-only)
- what the cue-masked ablation controls for, and why it is the interesting result even if the Kazakh gap turns out small
- one thing you got wrong and fixed

Record a 60-second demo video and keep a local Docker copy. Telegram is blocked in Shenzhen. Do not let the demo depend on it.
