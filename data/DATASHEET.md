# KazScam v0.1 datasheet

Version: `v0.1-draft`. Drafted 2026-09-09.

**This is a draft written before annotation and before release.** The corpus
has been collected and scrubbed but not yet labelled by annotators, split, or
published. Every count below is the real count on 2026-09-09, from
`python tools/collect.py check --stats`, or an explicit placeholder in the form
`[[TBD: ...]]` naming the task that produces it (pilot annotation T406, full
annotation T407, splits T408, release T409). Nothing here is estimated. When
the placeholders are filled, the version line changes and this notice goes.

The structure follows *Datasheets for Datasets* (Gebru et al., 2021), plus
the Ethics and Limitations sections that the release checklist in
`docs/05_EVAL_PROTOCOL.md` section 9 requires. Two companion documents ship
with the dataset: `docs/07_ANNOTATION_GUIDELINE.md` (how rows were labelled)
and `docs/09_SOURCES.md` (every source domain, its status, and the
redistribution basis).

## Motivation

**Why the dataset exists.** There is no public, labelled corpus of scam
messages as they circulate in Kazakhstan, in Kazakh or in Russian. A tool that
triages messages for Kazakhstani users cannot be evaluated without local data,
and a claim that language models handle Kazakh worse than Russian cannot be
tested without matched rows in both languages.

KazScam was built to evaluate SaqBol, a scam-triage bot for Telegram and the
web, and to test three hypotheses pre-registered in `docs/05_EVAL_PROTOCOL.md`:

- H1: frontier LLMs score lower macro-F1 on Kazakh scam messages than on
  Russian ones at matched content.
- H2: a hybrid rules-plus-grounded-LLM system has a lower false-positive rate
  on hard negatives than an LLM alone at matched recall.
- H3: masking surface cues (brand names, short codes, numbers) hurts the
  LLM-only system more than the hybrid.

A null result on any of them is reported as such.

**Who created it.** Toktar Kametay, an undergraduate at BNBU, as sole
collector and maintainer. Two Kazakh-speaking co-annotators join for the
annotation phase: `[[TBD: co-annotator names or roles, recruited for T406]]`.

**Funding.** No external funding is recorded for this work.

## Composition

**What one row is.** One text, quoted verbatim from a public web page, with
the URL and access date of that page. In v0.1 a row is either a scam message
or cue phrase that a publisher quoted, or a genuine institutional notice quoted
from the institution's own site. Donated rows from bot users are planned for
v0.2: `[[TBD: donated row count in v0.1, if any, from T408]]`.

**Counts on 2026-09-09.** 126 rows from 27 source domains, in 5 batch files
under `data/corpus/`.

| | RU | KK | Total |
|---|---|---|---|
| Scam, `message` | 35 | 24 | 59 |
| Scam, `phrase_fragment` | 31 | 19 | 50 |
| Legitimate hard negative, `message` | 13 | 4 | 17 |
| All rows | 79 | 47 | 126 |

By provenance: 92 `press`, 34 `official_warning`, 0 `donated`. By channel, as
the source states it: 58 `call`, 16 `sms`, 16 `whatsapp`, 17 `web`, 5 `email`,
4 `marketplace`, 2 `instagram`, 8 `unknown`. All 17 `web` rows are the hard
negatives. No row is code-switched. Message rows run from 22 to 1,524
characters (median 87.5); fragments from 13 to 55 (median 25.5).

**Messages and fragments.** Kazakhstani sources often quote a scam's cue
phrase ("картаңыз бұғатталды", "your card is blocked") rather than a whole
message. Those quotes are real and sourced, but a three-word stub is not a
message, so every row carries `text_kind`: `message` is a complete utterance a
target would receive, a full sentence with a claim and usually an instruction;
`phrase_fragment` is a cue phrase quoted to illustrate wording.

**Fragments are not in any message split.** They ship as a separate file for
use as an indicator lexicon, and `tools/collect.py paste` will not emit them
for annotators unless `--include-fragments` is passed. The 76 message rows are
the population that annotation, splitting and every reported metric operate
on. Ten scam rows and two hard-negative rows carry `UNSURE` in `notes` where
the message-or-fragment call was close.

**Label set.** Every row carries `label`:

| `label` | Meaning |
|---|---|
| `scam` | An attempt to defraud the recipient. |
| `legit` | A real message, including alarming real ones. Hard negatives are `legit` with `hard_negative: true`. |
| `ambiguous` | Neither answer could be defended to the other annotator. Kept and reported, not discarded. |

At collection time `label` records how the source framed the text. That is
provisional. The released label is the annotators' adjudicated answer.

Scam rows also carry `playbook_id`: one of the 13 playbooks below, or
`other_scam` (plainly a scam, none of the 13 fit), or empty (the annotator was
not sure which). `stage` (`contact`, `hook`, `trust`, `pressure`,
`extraction`, `cashout`) is set only on multi-message threads.

| `playbook_id` | Gloss |
|---|---|
| `kz.bank_security_call` | Caller poses as a bank's security service; a transfer is "being attempted", stay on the line. |
| `kz.egov_1414_code` | An unrequested eGov/1414 code arrives, then a caller asks for it, usually toward a loan in the victim's name. |
| `kz.delivery_link` | Fake parcel, post or customs notice with a payment link. |
| `kz.marketplace_safe_deal` | OLX or Instagram "safe deal": the counterparty sends a link to "receive" money. |
| `kz.mule_account_rental` | Recruiting the victim to rent out a card or account as a money mule. |
| `kz.investment_deepfake` | Fabricated or deepfaked endorsement of an investment platform, funnelling to a "personal manager". |
| `kz.hijacked_account_relative` | A relative's or friend's hijacked messenger account asks for an urgent transfer. |
| `kz.apk_install` | An Android package sent in chat, framed as a bank update, court document or tracker. |
| `kz.fake_store` | Fake online shop or Instagram storefront: prepayment, then silence. |
| `kz.remote_access_loan` | Remote-access takeover (AnyDesk, TeamViewer) ending in a loan; often the second half of a bank call. |
| `cn.fake_police_deposit` | Fake Chinese police, prosecutor or embassy demanding a "guarantee deposit" from a foreign student. |
| `cn.currency_exchange` | Private RMB-to-tenge exchange over a messenger; money taken or the card frozen. |
| `cn.part_time_task_job` | Task-commission or fake part-time work that requires paying for "orders" to continue. |

Per-playbook counts: `[[TBD: rows per playbook_id after adjudication, from
T407]]`. Share of scam rows labelled `other_scam`, a health metric for the
playbook set: `[[TBD: other_scam share, from T407]]`. `ambiguous` rows:
`[[TBD: ambiguous count, from T407]]`.

**Row schema.** The released row follows `docs/02_DATA_CONTRACTS.md` section
6, plus the attribution fields the redistribution basis requires.

| Field | Type | Notes |
|---|---|---|
| `id` | string | `ks-<batch>-NNN` at collection; `kazscam-NNNNNN` at release. |
| `text` | string | Verbatim quoted text, PII scrubbed. |
| `text_kind` | `message`, `phrase_fragment` | Fragments ship in a separate file. |
| `label` | `scam`, `legit`, `ambiguous` | Adjudicated. |
| `playbook_id` | string or null | Only when `label` is `scam`. |
| `stage` | string or null | Threads only. |
| `lang` | `ru`, `kk`, `kk-ru`, `en` | Language of the text. |
| `lang_secondary` | string or null | Second language of a code-switched row. |
| `is_code_switched` | bool | False on every row so far. |
| `channel` | string | `sms`, `call`, `whatsapp`, `web`, ... |
| `source` / `provenance` | `press`, `official_warning`, `donated` | How the row reached the corpus. |
| `source_url` | string | Required unless `donated`. |
| `publisher` | string | Domain of the source page. |
| `access_date` | date | Day the page was fetched. |
| `collected_at` | timestamp | When the row was written. |
| `hard_negative` | bool | Legitimate text that resembles a scam. |
| `annotator_a`, `annotator_b` | string | `label/playbook_id` per annotator. |
| `adjudicated` | bool | True where the two disagreed and a decision was logged. |
| `scrub_applied` | bool | Scrubber has run. |
| `scrub_placeholders` | list | Placeholder types present in `text`. |
| `source_group` | string | Released rows only. The `id` of the first row of the row's source group: rows from one article, a translation pair, a variant group or near-identical text share it. |
| `text_hash` | string | Hash of the normalised verbatim text, for duplicate and leakage checks. |
| `notes` | string | Pair keys, `UNSURE`, "illustrative text" flags. |

**Splits.** Built by `python -m saqbol.eval splits`. The counts are the
build of 11 November 2026 and change when fresh rows are collected. The
policy is in [docs/15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md](../docs/15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md).

| Split | Contents | Rows |
|---|---|---|
| `dev` | Every message the system was developed against, as listed in `data/exposure.json`, and any row grouped with one. Never a reported test number | 76, in 28 source groups |
| `test_press` | Message rows from press and official warnings collected after the system freeze, including hard negatives | 0; collection has not started |
| `test_donated` | Consented user submissions reviewed after the freeze, held out | 0 |
| `calibration` | A stratified slice of fresh press rows for tuning fusion weights and abstention thresholds, cut only when at least 250 exist (20% of them, 50 to 75 rows). Below that, thresholds are fitted on `dev` and the run is labelled `dev-calibrated` | 0 |
| `train_synthetic` | LLM paraphrases of `dev` rows, each recording its seed row; never in a reported metric | 0; not generated |

Leakage rules checked in CI: no text digest in two splits, no synthetic row
derived from a test row, calibration disjoint from every test split, no
source article, translation pair, variant group or near-duplicate cluster
divided between splits, and no row from the exposure register outside `dev`.

**Relationships between rows.** 38 rows carry a `parallel pair key` in
`notes`: the same content in Russian and Kazakh (the ARDFM vishing page, the
Ministry of Internal Affairs top-10 list of September 2025, a vote-for-my-niece
message, and four bilingual hard-negative notices). Pairs are what the
`translated` ablation needs and they are a leakage hazard, so pairs move
together. Two rows carry `Variant group key: kazpost-parcel-kk`, a
prefix-sharing variant the duplicate check does not catch; they also stay in
one split.

**Known noise.** Four session-2 messages are introduced by their article as a
typical text rather than a captured one ("с примерно таким текстом"); they are
verbatim from the page but are the publisher's illustration, and `notes` says
so. One hard-negative row is a live site banner and one is an excerpt of a
longer notice; both are marked `UNSURE`.

**Self-contained? Sensitive?** The text is in the row; `source_url` points to
an external page that may disappear, and `access_date` records when it was
live. All source pages are public and PII is scrubbed. Scam texts contain
threats and impersonation of police and banks, because that is what they are.

## Collection process

**Procedure.** Rows were collected by the maintainer in two sessions, on
2026-09-08 (session 1) and 2026-09-08 to 2026-09-09 (session 2). Each row went
through the same steps.

1. Fetch a candidate page from a Kazakhstani press site, official portal,
   bank, operator or university site. The fetch tool returns page content
   through a summarising model, and every fetch was instructed to answer
   `NO_VERBATIM` rather than paraphrase when the page quoted nothing. About
   two thirds of session-1 fetches and three quarters of around 110 session-2
   fetches returned that. Around 135 fetches were made in total.
2. Verify verbatim against the raw HTML. The summariser was caught altering
   quoted text three times: it respelled Kazakh words ("ауыстырғаңыз" for the
   page's "ауыстырғыңыз", "құпія" for "құпия"), silently dropped a section of
   a long notice, and moved a period inside a closing guillemet. So the raw
   HTML of every page was downloaded separately and each row's text was
   confirmed to occur in it as a whitespace-normalised substring before
   ingest. Long notices were cut from the raw text by start and end markers,
   not retyped. `docs/09_SOURCES.md` records that every session-2 row was
   checked; the 64 session-2 message rows say "Verified against raw HTML" in
   `notes`, the 33 session-2 fragments do not carry the note.
3. Record `source_url`, `publisher` and `access_date`. `tools/collect.py`
   refuses a non-donated row without a URL, any row marked non-verbatim, and
   any access date that is not ISO formatted.
4. Duplicate check. Each incoming row is compared with every existing row:
   exact match on a normalised form (NFKC, lower case, URLs replaced by a
   token, punctuation and whitespace folded), then Jaccard similarity over
   5-character shingles of that form, rejected at 0.85 or above. This caught
   the `elordainfo.kz` reprint of a `turkystan.kz` quote in session 1. It
   missed one variant pair at 0.54, recorded above under relationships.
5. PII flagging. `collect.py` flags, and does not alter, rows containing a
   phone number, IIN, card number, email, messenger handle or IBAN. Two rows
   were flagged, both hard negatives listing corporate or staff contacts.

**Yields.** Session 1: 29 rows, 12 scam messages (7 RU, 5 KK) and 17
fragments (3 RU, 14 KK), no hard negatives. Session 2: 97 rows, 47 scam
messages (28 RU, 19 KK), 33 fragments (28 RU, 5 KK) and 17 hard negatives (13
RU, 4 KK). The session-2 brief asked for at least 40 messages and 15 hard
negatives.

**What did not yield.** Most Kazakhstani coverage of fraud describes schemes
without quoting message text. `docs/09_SOURCES.md` section 3 logs every domain
attempted, including the MIA's own portal, the National Bank, Kaspi's help
centre, and around 25 pages fetched specifically for genuine SMS wording
(1414, Kazpost, IMEI registration, tax notices), none of which prints a
message. The two fact-checkers that reproduce viral text by design,
`factcheck.kz` and `stopfake.kz`, block automated fetching and need a manual
browser session.

**Timeframe of the texts.** Where the source log records a date, quoted pages
run from 2021 (a bank maintenance notice) to 2026. Some pages are undated.

**Ethical review.** None. This is a student project with no review board. The
consent, scrubbing and takedown procedures below stand in for it and are
stated so they can be criticised. No person was contacted for v0.1; all rows
come from published pages. Donated rows come only from bot users who tick a
per-submission consent box (see Ethics).

## Preprocessing, cleaning and labeling

**Normalisation.** The released `text` is the verbatim quote. Normalisation
is used only for `text_hash` and the duplicate check and never changes the
stored text.

**PII scrubbing.** `tools/scrub_corpus.py` passes every row's `text` through
`saqbol.core.privacy.scrub`, the same regex scrubber the bot applies at parse
time. Matches become typed placeholders, `<PHONE>`, `<IIN>`, `<CARD>`,
`<IBAN>`, `<EMAIL>`, `<HANDLE>`, so it stays visible that a card number was
asked for while the number itself is gone. Amounts and institution names are
kept on purpose: they are the semantic content of a scam. `scrub_applied` is
set on every row and the placeholder types present are recorded in
`scrub_placeholders`. On 2026-09-09 all 126 rows are scrubbed; 2 rows carry
placeholders (one `<PHONE>`, one `<PHONE>` and `<EMAIL>`). A test in
`tests/test_privacy.py` asserts over the committed corpus that no phone
number, IIN or card number survives.

Two honest gaps. The regex scrubber does not detect personal names: one
hard-negative row (`ku.edu.kz`) originally ended with a university staff
member's name, which was found by hand and cut from the excerpt, and its
`notes` field records that. Names in any future row will need the same manual
pass. Presidio is an optional second pass considered before release and has
not been run.

**Human review.** Every released row is read by a person before release, for
scrubbing and for whether it belongs in the corpus at all. This has not yet
happened.

**Labeling.** Annotation runs in `tools/annotate.html`, a browser tool that
asks two questions: is this a scam (`scam`, `legit`, `ambiguous`), and if so,
which playbook. The second may be left blank. Annotators never see each
other's answers. The procedure, from `docs/05_EVAL_PROTOCOL.md` section 3:

1. Pilot on 30 items with three annotators; compute agreement; revise the
   guideline; keep both numbers. Before revision: `[[TBD: pilot Cohen's
   kappa before guideline revision, from T406]]`. After: `[[TBD: pilot
   Cohen's kappa after guideline revision, from T406]]`.
2. Double-annotate every released message row.
3. Report Cohen's kappa overall and per class. Overall: `[[TBD: overall
   kappa on the binary and the 13-way label, from T407]]`. Per class:
   `[[TBD: per-class kappa table, from T407]]`. The pair
   `kz.bank_security_call` versus `kz.remote_access_loan` is expected to be
   confusable, since one script becomes the other, and its kappa is reported
   rather than hidden.
4. Adjudicate every disagreement, by a third annotator or discussion, with a
   one-line logged reason. Rows adjudicated: `[[TBD: adjudicated row count,
   from T407]]`.

**Raw data.** The unsplit, scrubbed batches in `data/corpus/` are the raw form
and are under version control. Unscrubbed text is kept nowhere; `text_hash`
was computed before scrubbing so a re-collected duplicate is still recognised.

## Uses

**Intended uses.** Evaluating scam-message classifiers on Kazakh and Russian
text; testing H1 to H3; measuring false-positive rate on hard negatives;
building an indicator lexicon from the fragment file; the `translated` and
`cue_masked` ablations, which depend on the parallel pairs and the typed
placeholders. The SaqBol evaluation harness
(`python -m saqbol.eval run --config eval/configs/v0.1.yaml`) is the first
consumer.

**What the dataset should not be used for.** Training a model to generate
scam messages. Any claim about how common a scam type is in Kazakhstan, since
rows reach the corpus by being quoted, which selects for newsworthiness, not
frequency. Any claim about the language balance of scams, since the Kazakh
share (47 of 126 rows) reflects which publishers quote. Deploying a classifier
trained only on this corpus as a user's sole protection; it is an evaluation
set. Identifying or profiling any person; no row is tied to a recipient.

**Reporting rule for consumers.** No claim that one system beats another
unless 95 percent bootstrap confidence intervals do not overlap.
`train_synthetic` never appears in a reported number.

## Distribution

**Where and when.** Hugging Face Datasets, as JSONL with one file per split
plus a fragment file and a loading script: `[[TBD: Hugging Face dataset URL,
from T409]]`. Source repository:
`https://github.com/InfectedDuck/Scam-Detector`. Release date: `[[TBD: release
date, from T409]]`. Before the push, an external Kazakh NLP researcher reviews
this datasheet: `[[TBD: reviewer and review date, from T409]]`.

**Licence for annotations and metadata.** The proposed licence for everything
the project authored (labels, playbook assignments, stage tags, adjudication
log, provenance fields, splits, loading script, this datasheet) is Creative
Commons Attribution 4.0 (CC BY 4.0). This is a proposal until Toktar Kametay
confirms it at release: `[[TBD: licence confirmation, from T409]]`.

**Basis for redistributing the quoted texts.** The message texts are not
licensed by the project, because the project does not own them. Scam rows are
third-party criminal artifacts quoted by a publisher, who does not own them
either. Hard-negative rows are institutions' own short public notices. Both
are redistributed under Article 19 of the Law of the Republic of Kazakhstan of
10 June 1996 No. 6-I *On Copyright and Related Rights*, which permits use of a
lawfully published work without consent or royalty, with mandatory attribution
of author and source, for citation in scientific, research and informational
purposes in a volume justified by the purpose. A single quoted message,
attributed by live URL, publisher and access date, is inside that allowance.
The corpus never reproduces an article, a headline or any one article's set of
examples as a set. `docs/09_SOURCES.md` section 1 gives the argument in full
and section 2 lists every domain; for most, no terms-of-use page was located,
so the release rests on the statutory right, not on any site's grant. Written
permission is to be sought from the heaviest contributors (`zakon.kz`,
`stan.kz`, `rus.baq.kz`, `azattyq-ruhy.kz`, `finance.kz`) before the push.

**Takedown.** If a rights-holder objects to a row, the row is removed from
the next version and the domain's status in `docs/09_SOURCES.md` changes to
`withdrawn`. A released version is immutable and downloaded copies cannot be
recalled; the removal is logged in the changelog so consumers can apply it.

**Export controls or regulatory restrictions.** None known.

## Maintenance

**Maintainer.** Toktar Kametay, through the repository.

**Where issues go.** `https://github.com/InfectedDuck/Scam-Detector`. A
deletion request from a bot user follows `PRIVACY.md` section 9:
acknowledgement within 5 working days, deletion within 30 days.

**Versioning.** v0.1 is the first release: press and official-warning rows,
double-annotated, with the fragment file and the kappa table. v0.2 is planned
with donated rows from the consent queue, genuine SMS and push hard negatives
that only donation can supply, code-switched rows if any are donated, and a
fine-tuned baseline alongside the prompted systems. v0.2 also decides whether
`kz.bank_security_call` and `kz.remote_access_loan` merge, based on their v0.1
kappa. Each version is a new tag; earlier versions stay available unchanged.

**What removes a row.** A rights-holder's objection; a donor's deletion
request; PII found after release; a row shown not to occur verbatim on its
source page; a misattributed source. In every case the row leaves the next
version and the removal is logged.

**Contributions.** New rows enter only through `tools/collect.py` and only
from a domain listed in `docs/09_SOURCES.md`. The tool screens each new row
against the development data and records the outcome on the row, so a row
that repeats, rewords or shares an article with a development row cannot be
collected as a test row.

## Ethics

**Consent flow for donated rows.** No text from a bot user enters the corpus
without a consent box ticked on that specific submission; a general yes when
the bot is first started grants nothing. Consented messages go to a
`dataset_candidates` queue with status `pending`, never straight into the
dataset. A person reads each candidate, re-checks the scrubbing, and approves
or rejects it. Declining changes nothing about the check the user receives. A
user can ask for pending rows to be deleted at any time; a published row
cannot be recalled from downloaded copies, which is why consent is asked per
submission.

**Scrubbing.** Regex scrubbing to typed placeholders on every row, a test that
fails if a phone, IIN or card number survives, and a human read of every row
before release. Names are the known weak point and are handled by hand.

**Dual use.** The objection deserves a direct answer: does a public corpus of
scam messages help scammers? Four points.

1. The texts are already public. Every scam row was quoted in a newspaper, a
   bank's press centre or a ministry warning, published so that as many
   people as possible would read it. The corpus adds nothing a scammer could
   not find with a search engine in an afternoon.
2. The corpus adds labels, not scripts. What the project authored is the
   playbook assignment, the provenance, the pair keys and the adjudication
   log. None of that helps someone write a better scam; all of it helps
   someone detect one.
3. The detection rules are already public. The indicator engine, the
   playbooks and the fusion logic live in this repository. Anyone wanting to
   evade SaqBol can read the source; the corpus changes nothing there.
4. The asymmetry runs the other way. Attackers have unlimited labelled data:
   they know which messages worked. Defenders in Kazakhstan have none.
   Releasing a small, attributed, scrubbed evaluation set closes part of that
   gap for defenders and none of it for attackers.

The release is judged net positive on that basis. The one measure taken
against misuse is the one that matters: no row contains a working phone
number, card, account or handle, so the corpus is neither a contact list nor a
template with live payment details.

## Limitations

- **Size.** 126 rows, 76 of them messages, against a protocol target of
  roughly 600 to 700. The collection stands at about a seventh of the Russian
  scam target (200 to 260), between a fifth and two fifths of the Kazakh
  target (60 to 120), and an eighth of the hard-negative target (100 to 140).
  Confidence intervals will be wide.
- **Regional and temporal scope.** Kazakhstan only, plus three China-side
  playbooks for which no source and no row was found. Underlying pages run
  from 2021 to 2026. Scam wording drifts within months; this is a snapshot.
- **Class imbalance.** 109 scam rows to 17 legitimate; among messages, 59 to
  17. The false-positive rate on 17 hard negatives has coarse resolution.
- **Newsworthiness filter.** A scam reaches the corpus by being quoted in
  press or an official warning, which selects for scams that were novel,
  large or already widely reported. The corpus says nothing about prevalence.
- **Call scripts over SMS.** 58 of 126 rows, and 35 of 59 scam messages, are
  phone-call wording; only 16 rows are SMS and 16 WhatsApp. Messaging text,
  the thing the bot classifies, is the scarcer half.
- **No code-switched rows.** The protocol wanted 40 to 80; zero were found.
  Every quoted text is monolingual, which itself says something about what
  publishers reproduce. Code-switched text will come from donation or not at
  all.
- **Hard negatives are the wrong kind.** The protocol asks for real 1414
  codes, Kazpost tracking, Kaspi promotions, Halyk login alerts and genuine
  OLX chats. None of that wording exists on the open web. The 17 hard
  negatives are institutions' web-published notices (maintenance windows, a
  system update, tuition announcements) in a bureaucratic register. They test
  the false-positive rate on something, but not on the SMS class the protocol
  names.
- **Language balance is an artifact of collection.** 47 of 126 rows are
  Kazakh, mostly because the MIA publishes bilingual lists and Kazakh-language
  portals print screenshots. H1 must be read with that in mind.
- **Single-author Kazakh review pending.** Rows were collected by one person.
  The Kazakh rows have not yet been read by a second Kazakh speaker; the
  raw-HTML check guards spelling, not interpretation.
- **Everything before annotation is provisional.** Today's `label` is the
  source's framing, not an adjudicated judgement. No `playbook_id` has been
  assigned. The `UNSURE` rows, the illustrative texts and the excerpt may be
  re-sorted or dropped. Counts here will change when annotation and splits
  are done, and this file is re-issued with them.
- **Terms of use unverified.** Redistribution rests on the statutory
  quotation right; written grants from the main contributors are still to be
  requested.
