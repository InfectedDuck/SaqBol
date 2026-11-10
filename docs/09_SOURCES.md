# SaqBol — Sources and redistribution basis

Every domain the KazScam corpus draws from, what it is, and whether quoted text
from it can be redistributed in a public release. This table is what makes the
Hugging Face release defensible. A row whose domain is not in this table does
not ship.

Owner: T403/T404. Last updated 2026-09-09 (second collection session; the
first was 2026-09-08).

---

## 1. What the corpus redistributes

The released dataset contains **the scam message text quoted inside a source
article, plus a URL and an access date**. It does not contain the article, the
headline, the journalist's analysis, or any image.

That distinction carries most of the legal weight:

- The scam text is a **third-party criminal artifact**. The publisher who
  quoted it does not own it and did not author it. Quoting a fraudster's SMS
  does not make the newspaper its author.
- What the publisher does own is **the article around the quote**, and the
  corpus redistributes none of that.
- The residual claim — that the *selection and arrangement* of quoted examples
  is itself editorial work — is answered by the statutory quotation right
  below, and by the fact that rows are re-mixed across sources and never
  reproduce any one article's set as a set.

**Statutory basis.** Law of the Republic of Kazakhstan of 10 June 1996 No. 6-I
*On Copyright and Related Rights*, Article 19: use of a lawfully published work
without the author's consent and without royalty is permitted, **with mandatory
attribution of the author and the source**, including citation "in scientific,
research, polemical, critical and informational purposes, in a volume justified
by the purpose of the citation". A single quoted SMS, attributed with a live
URL, is inside that allowance by a wide margin.

**Hard negatives are a different object.** The 17 hard negatives collected in
session 2 are not third-party criminal artifacts: they are institutions'
*own* customer notices (bank maintenance windows, an operator's system-update
notice, a university's tuition announcement), quoted from the institution's
own website. The institution is the author. These are short factual notices
published for the widest possible dissemination, quoted in full with
attribution for research, and the same Art. 19 quotation right applies; but a
reviewer should know the authorship situation differs from the scam rows.

**Practical rule.** Attribution is not optional and not a footnote: every row
carries `source_url`, `publisher` and `access_date`, and the release ships this
file. If a rights-holder objects to a specific row, the row is removed and the
domain's status here changes to `withdrawn`.

---

## 2. Domains used in the corpus

Status values: `in use` (rows collected), `no yield` (fetched, quotes nothing
verbatim), `blocked` (refuses automated fetching), `withdrawn` (rights-holder
objection).

"Terms verified?" records whether a terms-of-use or reuse page was actually
located and read. "No" means it was not looked for or not found in the session
that added the domain; it never means "assumed permissive".

### 2a. Scam rows (label `scam`)

| Domain | What it is | Provenance class | Rows | Terms verified? | Redistribution basis |
|---|---|---|---|---|---|
| `fingramota.kz` | Financial-literacy portal operated by the **Agency of the RK for Regulation and Development of the Financial Market (ARDFM)**. Confirmed on its About page: "один из проектов, реализуемых Агентством РК по регулированию и развитию финансового рынка". | `official_warning` | 9 | No published reuse terms found on site | Art. 19 quotation right. State-agency awareness material published for public dissemination; quoting it back for research is squarely within its purpose. **Lowest-risk source in the set.** |
| `zakon.kz` | Private legal-and-news portal, one of the largest in KZ. Russian-language edition. Session 2 rows come from its *Советы* (advice) section and from a news item that quotes a Kazpost Instagram post; two of the three rows-yielding articles relay MIA phrase lists. | `press` | 28 | **No** — `/pravila-polzovaniya/` returned 404 in session 1; not re-checked | Art. 19 quotation right only. Attribution + URL mandatory. Heaviest contributor; a written grant should be sought before release. |
| `kaz.zakon.kz` | Kazakh-language edition of the same publisher. | `press` | 1 | **No** — as above | Art. 19 quotation right only. |
| `stan.kz` | Private Kazakh-language news portal. | `press` | 12 | **No** — not located | Art. 19 quotation right only. All rows from it are `phrase_fragment` (see §4). |
| `sp.stan.kz` | Special-projects subdomain of the same publisher; the *secureweb* project is a first-person piece by a stan.kz journalist. | `press` | 2 | **No** — not checked | Art. 19 quotation right only. One row is a first-hand received WhatsApp message, the strongest provenance in the Kazakh set. |
| `turkystan.kz` | Online edition of the newspaper *Türkistan*. | `press` | 1 | **No** — not located | Art. 19 quotation right only. |
| `elordainfo.kz` | Astana city news outlet. | `press` | 1 | **No** — not located | Art. 19 quotation right only. |
| `massaget.kz` | Kazakh-language youth news portal (private). | `press` | 1 | **No** — not checked | Art. 19 quotation right only. Quotes a fake Kazpost SMS as received by a named journalist. |
| `baq.kz` | Kazakh-language edition of the BAQ.KZ news agency. | `press` | 1 | **No** — not checked | Art. 19 quotation right only. Variant of the massaget.kz SMS; see §4 on the near-duplicate threshold. |
| `rus.baq.kz` | Russian-language edition of BAQ.KZ. | `press` | 10 | **No** — not checked | Art. 19 quotation right only. The 10 rows are the MIA's "top-10 phrases" list (08.09.2025), relayed by BAQ.KZ from Polisia.kz; the phrases themselves are the MIA's compilation of criminal wording. |
| `azattyq-ruhy.kz` | Kazakh-language private news site *Azattyq Rýhy* (not RFE/RL's azattyq.org). | `press` | 11 | **No** — not checked | Art. 19 quotation right only. 10 rows are the Kazakh edition of the same MIA top-10 list (09.09.2025); 1 row is the Kazakh twin of the time.kz vote-for-my-niece message. |
| `rus.azattyq-ruhy.kz` | Russian-language edition of the same site. | `press` | 1 | **No** — not checked | Art. 19 quotation right only. |
| `time.kz` | Online edition of the newspaper *Время*. | `press` | 1 | **No** — not checked | Art. 19 quotation right only. Article marks its message as "примерно таким текстом" — an illustrative typical text, recorded as such in `notes`. |
| `kaz.tengrinews.kz` | Kazakh-language edition of Tengrinews. The yielding article ("Қаржы жобасы: ТОП-5 алаяқтық схема") is a financial-literacy project piece, undated on the page. | `press` | 8 | **No** — not checked | Art. 19 quotation right only. Note the Russian edition `tengrinews.kz` is `no yield` in §3; the Kazakh edition behaves differently. |
| `nur.kz` | Major Russian-language portal; the yielding article is from its *Nurfin* personal-finance section. | `press` | 1 | **No** — not checked | Art. 19 quotation right only. Article marks its message as "примерно так выглядят". |
| `finance.kz` | Private personal-finance portal. | `press` | 13 | **No** — not checked | Art. 19 quotation right only. All 13 rows are `phrase_fragment` (a list of caller phrases in an explainer). |
| `bcc.kz` | Bank CenterCredit, official site, press-centre section. | `official_warning` | 7 scam (+2 hard negatives, §2b) | **No** — not checked | Art. 19 quotation right. A bank's own public anti-fraud warning listing the phrases a caller uses; quoting it back for research is within its purpose. |
| `halyklife.kz` | Halyk Life, insurer in the Halyk Group; customer-support "useful news" section, Kazakh-language page. | `official_warning` | 1 | **No** — not checked | Art. 19 quotation right. Corporate anti-fraud warning. |

### 2b. Hard negatives (label `legit`, `hard_negative: true`)

All hard-negative rows are the institution's own published notice, quoted from
the institution's own site. Provenance is recorded as `official_warning`
because the schema has no "official publication" class; every such row says
"official publication, not a warning" in `notes`. Channel is `web` (the
notice was published on the website; whether it was also pushed or texted is
not known from the page).

| Domain | What it is | Rows | Terms verified? | Why it is genuine |
|---|---|---|---|---|
| `bcc.kz` | Bank CenterCredit press centre (RU and KZ editions of one notice). | 2 | **No** | Published by the bank on its own site. |
| `halykfinance.kz` | Halyk Finance, brokerage in the Halyk Group; news section. | 2 | **No** | Published by the company on its own site. One row lists manager phone numbers and an email (corporate contacts; PII flags fire). |
| `vtb-bank.kz` | VTB (Kazakhstan) bank; news section plus a site-wide banner. | 2 | **No** | Published by the bank on its own site. The banner row is marked UNSURE in `notes` (a live banner rather than a message a person receives). |
| `beeline.kz` | Beeline Kazakhstan, mobile operator; news section (RU and KZ editions of one notice). | 2 | **No** | Published by the operator on its own site. Closest open-web analogue to a genuine operator SMS: "top up before the 14th", "support unavailable". |
| `tele2.kz` | Tele2/Altel Kazakhstan, mobile operator; news section. | 1 | **No** | Published by the operator on its own site. |
| `nurbank.kz` | Nurbank; press centre (KZ and RU editions of one notice). | 2 | **No** | Published by the bank on its own site. |
| `forte.kz` | ForteBank; announcements section (one page carries RU and KZ text; a second page is RU only). | 3 | **No** | Published by the bank on its own site. |
| `kgd.gov.kz` | State Revenue Committee of the Ministry of Finance; news section. | 1 | **No** | Published by the state body on its own site. Weakest resemblance to scam text in the set (bureaucratic register, addressed to organisations); kept as a state-body "technical works" notice. |
| `amu.edu.kz` | Astana Medical University; news section. | 1 | **No** | Published by the university on its own site; a genuine tuition-increase announcement. |
| `ku.edu.kz` | Kozybayev University (SKU), Petropavl; news section. | 1 | **No** | Published by the university on its own site; a genuine "apply for a tuition discount by this date, call this number / WhatsApp" notice. Row is an EXCERPT (opening three paragraphs of a longer announcement) and is marked UNSURE; it contains a staff member's name and phone numbers for T405 to scrub. |

**Terms column is honest, not decorative.** No terms-of-use page was located
or checked for any domain added in session 2, and only `zakon.kz` was checked
in session 1 (404). The release rests on the statutory quotation right, not on
any site's grant. Before the Hugging Face push, someone should attempt written
permission from `zakon.kz`, `stan.kz`, `rus.baq.kz` / `azattyq-ruhy.kz` (the
MIA-list carriers) and `finance.kz`, the heaviest contributors, because a
written grant is strictly better than a statutory argument when a reviewer
asks.

---

## 3. Domains attempted, with outcome

Logged so the next collection session does not repeat the work. Session 1
entries are kept; session 2 entries are marked (s2).

| Domain | What it is | Outcome | Note |
|---|---|---|---|
| `polisia.kz` | MIA official media portal | `no yield` | 4 articles fetched, all describe schemes without quoting message text. Appears to be deliberate editorial policy — not handing criminals a template. (s2: not re-fetched; but note the MIA *does* publish phrase lists, which reach the corpus through `rus.baq.kz`, `azattyq-ruhy.kz` and `zakon.kz`.) |
| `factcheck.kz` | Fact-checking organisation (MediaNet) | `blocked` | HTTP 403 in session 1. (s2) Re-tried the front page and one article URL: both 403. Needs manual collection in a browser; still the highest-value untapped source. |
| `baribar.kz` | Kazakh-language news | `blocked` | HTTP 403 in session 1. (s2) Re-tried the front page: 403. |
| `stopfake.kz` | Government-affiliated fact-checker (s2) | `blocked` | TLS certificate mismatch — the host presents a `*.ps.kz` certificate, so every fetch fails before any content. Six article URLs found by search; none reachable. Manual browser visit needed. |
| `egov.kz`, `gov.kz` | Government portals | `no yield` | JavaScript SPAs. (s2) The `/cms/ru/news/sms_1414` page ("Сообщение от 1414: У вас отсутствует регистрация по месту жительства") would be a genuine-1414-SMS source, but `/cms/` paths also return only the shell, in the raw HTML as well. |
| `nitec.kz` | State IT operator (s2) | `no yield` | TLS chain not verifiable by the fetcher; raw HTML (fetched with verification relaxed, for inspection only) shows only the truncated headline of the 1414 message, not its text. |
| `tengrinews.kz` | Major news portal | `no yield` | 4 articles fetched in session 1; describes, does not quote. (s2) Not re-fetched. The Kazakh edition `kaz.tengrinews.kz` did yield (§2). |
| `informburo.kz` | News portal | `no yield` | Describes only. |
| `kaspi.kz`, `guide.kaspi.kz` | Bank customer help | `no yield` | (s2) 5 more Kaspi Guide pages fetched (SMS types, SMS-code definition, partner SMS security, fake-link page, Postomat). They state the sender name ("от имени kaspi.kz" / "Kaspi Pay") and describe notification types, but never print message wording. |
| `halykbank.kz` | Bank knowledge base | `no yield` | Halyk dropped SMS notifications entirely in June 2022 in favour of push. |
| `profit.kz` | Tech/business news | `no yield` | Confirms Kazpost sends from short number 1499; quotes no message text. |
| `eubank.kz` | Eurasian Bank blog | `no yield` | Target article 404s. |
| `prodengi.kz`, `dknews.kz` | Finance news (s2) | `no yield` (reprints) | Both reproduce the 13.11.2024 zakon.kz SMS column word for word; every quote is already in `press-01` and would be rejected as an exact duplicate. `kapital.kz` carries the same column (not fetched). |
| `kazpravda.kz` | State newspaper (s2) | `no yield` | 2 articles (fake-fine SMS 25.05.2026; SMS scheme 16.06.2026): describe, name the fake sender header, do not quote. |
| `lada.kz` | Aktau regional portal (s2) | `no yield` | 6 articles fetched (1414 authenticity, ЭЦП/1414, bank-SMS fakes, Kazpost appeal, benefit SMS, sorcery-for-parents). Only the last quotes two fragments, which duplicate the turkystan.kz/elordainfo.kz family; none taken. |
| `bes.media` | News (s2) | `no yield` | 3 articles (SMS-blaster, voting link, 1414 calls): describe only. |
| `inbusiness.kz` | Business news, Kazakh edition (s2) | `no yield` | Describes only. |
| `finratings.kz`, `forbes.kz` | Finance news (s2) | `no yield` | SMS-blaster coverage (Apr 2026) names the impersonated brands but never prints the SMS. |
| `liter.kz`, `el.kz`, `otyrar.kz`, `egemen.kz`, `24.kz`, `dalanews.kz`, `arasha.kz`, `kaz.inform.kz`, `inform.kz` | Press, RU and KK (s2) | `no yield` | Kazpost-parcel, SIM-expiry, WhatsApp-relative and 1414 stories: all describe. `inform.kz` quotes a victim's son in indirect speech only, which is not verbatim message text. |
| `arnapress.kz`, `pricom.kz`, `kazlenta.kz` | Regional press (s2) | `no yield` | 404 / 403 / 404. |
| `nationalbank.kz` | National Bank (s2) | `no yield` | 19.09.2024 phone-fraud warning (RU; KZ twin exists) describes, does not quote. |
| `nursultan.kgd.gov.kz`, `pvl.kgd.gov.kz`, `kgd.gov.kz` (3 pages) | State Revenue Committee (s2) | `no yield` for scam text | Fake-tax-message warning and SMS-notification announcements describe; none prints the SMS. (One unrelated "technical works" notice became a hard negative, §2b.) |
| `prg.kz` | Legal database carrying an NCA (НУЦ РК) warning (s2) | `no yield` | Says certificate-expiry reminders go by SMS and email at 30/10/1 days; does not print them. |
| `beeline.kz/ru/fraud`, `tele2.kz/new/helps/scammers` | Operator anti-fraud pages (s2) | `no yield` | Describe scheme types; no wording. (The operators' *news* sections did yield hard negatives, §2b.) |
| `b2b.kcell.kz`, `centralmedia24.kz`, `b2b.telecom.kz`, `inaktau.kz`, `kazkredit.kz`, `brobank.kz` | IMEI / 1414 explainers (s2) | `no yield` | All describe the 6006 / 1414 SMS without printing it. |
| `nur.kz` (7 further articles) | (s2) | `no yield` | Six 1414 / WhatsApp explainers describe; one quotes (in §2). Its "это не фейк" 1414 piece paraphrases the genuine SMS rather than printing it. |
| `zakon.kz` (8 further articles) | (s2) | `no yield` | 6512356, 6477495, 6452884, 6428718, 6472103, 6522104 describe; 6513285 shows the court-summons message as an image only; 6493897 quotes only slang markers. |
| `azattyq-ruhy.kz` (4 further articles), `stan.kz` 432849, `kaz.tengrinews.kz` (2 further) | (s2) | `no yield` | Fine-SMS, Telegram, "Мама мен ғой" and business-phishing pieces describe only. |
| `help.olx.kz`, `blog.olx.kz`, `lsm.kz` | OLX help / blog, LS business news (s2) | `no yield` | Help centre redirects to a login; blog and LS describe the delivery scam without the buyer's message. |
| `uchet.kz`, `halyklife.kz/…/11`, `fingramota.kz` (3 further pages), `online.fingramota.kz` | (s2) | `no yield` | Describe; `online.fingramota.kz` closed the socket twice. |
| `vse.kz` | Public forum (s2) | `blocked` | Expired certificate. A thread there quotes a genuine Kaspi password-change SMS; even if reachable, forum posts have no provenance class in the schema and were not going to be used without a decision on that. |
| `t.me/s/egovkz` | Telegram channel preview (s2) | `no yield` | Preview renders no posts. |
| Chinese-side playbooks | (s2) | `no yield` | Searched in Russian for consulate / "public security bureau" warnings to Kazakhstani students in China; only a zakon.kz travel-scam explainer (21.06.2026) surfaced, and it describes without quoting. No Chinese-language source located. |

---

## 4. Collection rules applied

**Verbatim only.** `tools/collect.py` rejects any row marked non-verbatim. No
row was written from a search-result summary; every row came from a fetch of
the cited page, and every fetch was asked to return `NO_VERBATIM` rather than
paraphrase when the page quoted nothing. In session 1 roughly two thirds of
fetches returned exactly that; in session 2 about three quarters of ~110
fetches did.

**Raw-HTML verification (added in session 2).** The fetch tool answers through
a summarising model, and that model was caught altering quoted text three
times: it respelled Kazakh words ("ауыстырғаңыз" for the page's
"ауыстырғыңыз", "құпія" for "құпия"), silently dropped a section of a long
notice, and moved a period inside a closing guillemet. So every row added in
session 2 was also checked against the page's raw HTML downloaded separately,
and the text of every row was confirmed to occur verbatim in that HTML before
ingest (the check script lived in the session scratchpad; it is a
whitespace-normalised substring test). Long notices were cut from the raw text
by start/end markers rather than retyped. Every session-2 row says "Verified
against raw HTML" in `notes`.

**`message` vs `phrase_fragment`.** Kazakhstani sources very often quote a
scam's *cue phrase* ("картаңыз бұғатталды") rather than a whole message. Those
quotes are real and sourced, but a three-word stub is not a message and would
poison a message-classification split. The rule applied:

- `message` — a complete utterance a target would actually receive: a full
  sentence carrying a claim, and usually an instruction.
- `phrase_fragment` — a cue phrase quoted to illustrate wording.

Session 2 added a run of borderline cases: MIA "phrases to watch for" lists
contain both two-clause scripts with an instruction ("С вашего счёта пытались
снять деньги. Назовите код из SMS" — `message`) and bare claims ("Оформлена
заявка на кредит" — `phrase_fragment`). The rule was applied line by line; the
ten scam rows where the call was genuinely close carry `UNSURE` in `notes` so
a reviewer can re-sort them in one pass (two hard-negative rows also carry
`UNSURE`, for the different reasons given in §2b).

`collect.py paste` emits only `message` rows unless `--include-fragments` is
passed, so fragments cannot reach annotators by accident. **Fragments must not
enter a released message split.** They are useful as an indicator lexicon for
the rules engine, and that is what they are for.

Three items quoted by `stan.kz` were dropped rather than recorded: "делдал",
"қаржы кеңесшісі" and "брондау керек" are role labels and generic vocabulary,
not quoted message wording. Recording them would have been padding. In session
2 one Kazakh line was dropped for a different reason: `sp.stan.kz` renders the
Telegram lure "Сәлем, суреттегі сенбісің?" in Kazakh while stating the message
is sent in Russian, so the Kazakh text is the journalist's translation, not
what a target receives.

**"Roughly like this."** Four session-2 messages are introduced by their
article as a typical text rather than a captured one ("с примерно таким
текстом", "мынаған ұқсас хабарлама", "примерно так выглядят", "примерно так
обращаются"). They are still verbatim from the page, but they are the
publisher's illustration of the genre; `notes` says so on each.

**Duplicate check.** Exact-on-normalized plus character-shingle Jaccard at
0.85. It caught the elordainfo.kz/turkystan.kz reprint in session 1. In
session 2 it rejected nothing, and one miss is worth recording: `baq.kz` and
`massaget.kz` printed two versions of the same fake Kazpost SMS a day apart
(08/09.01.2024); the baq.kz text is the first sentence plus a shorter second
sentence, and because the massaget.kz text is much longer the shingle Jaccard
is 0.54, well under the threshold. Both rows are in the corpus, both carry
`Variant group key: kazpost-parcel-kk` in `notes`, and they must be kept in
the same split. The threshold is right for reprints and wrong for
prefix-sharing variants; the split tooling should honour the group key.

**Parallel translations.** Pairs are matched content across languages, which
is what the `translated` ablation in `docs/05_EVAL_PROTOCOL.md` §6 needs, and
they are a **split hazard**: a pair split across train and test is
cross-language leakage. Pairs must move together. All pairs carry a
`parallel pair key` in `notes` on both rows. Pair families now in the corpus:

- `fingramota-vishing-1..4` — ARDFM vishing page, RU/KK (session 1).
- `mia-top10-2025-1..10` — the MIA's September-2025 list, RU via
  `rus.baq.kz`, KK via `azattyq-ruhy.kz`. The Kazakh list is the MIA's own
  wording and is a *loose* translation (items 1 and 7 are longer in Kazakh).
- `vote-niece-nastya` — time.kz RU and azattyq-ruhy.kz KK.
- Hard-negative pairs: `bcc-maint-2026-05-12`, `beeline-sysupdate-2026-08`,
  `nurbank-maint-2024-10-12`, `forte-maint-2021-02-18` (the Forte pair sits
  on one page).

**Hard negatives: what was and was not found.** Genuine bank, Kazpost, eGov
and operator *SMS/push wording* is still not published anywhere reachable:
~25 pages were fetched for it in session 2 (Kaspi Guide, KGD, egov/nitec, 1414
explainers on nur.kz/lada.kz/kazkredit/brobank, Kazpost coverage, NCA warning,
IMEI-6006 pages) and every one describes the message instead of printing it.
What institutions *do* publish in full is their own customer notices, and
`docs/05_EVAL_PROTOCOL.md` §2 and the session brief both count "real
university or employer notices about urgent payment" as hard negatives, so
that class was collected: 17 notices from banks, operators, a state body and
two universities, in RU and KK. Their scam-resemblance varies and `notes`
says how strong it is. They are web-published notices (`channel: web`), not
SMS, and the never-cut set still depends on donation for genuine SMS/push
text.

**Access dates.** Session-2 rows carry the actual fetch date: `2026-09-08`
for the first wave and `2026-09-09` for rows fetched after midnight.

**PII.** Not scrubbed here; T405 owns that. Rows carry `pii_flags` and
`needs_scrub`. Two rows are flagged (both hard negatives that list corporate
or staff contact numbers); one of them (`ku.edu.kz`) also names a staff
member, which the regex flags do not catch and which `notes` points out.

---

## 5. Honest state of the collection

**126 rows** after two sessions:

| | RU | KK | Total |
|---|---|---|---|
| Scam `message` | 35 | 24 | **59** |
| Scam `phrase_fragment` | 31 | 19 | 50 |
| Hard negative (`legit`, `message`) | 13 | 4 | **17** |
| All rows | 79 | 47 | 126 |

Session 2 added 47 scam messages (28 RU, 19 KK), 33 fragments and 17 hard
negatives; the session brief asked for 40+ messages and 15+ hard negatives.
No code-switched (`kk-ru`) row has been found in either session; every
quoted text so far is monolingual, which itself says something about what
publishers choose to reproduce.

Against the `docs/05_EVAL_PROTOCOL.md` §1 targets (200–260 RU scam, 60–120 KK
scam, 100–140 hard negatives), the collection stands at roughly a seventh of the
RU target, a fifth to two-fifths of the KK target, and an eighth of the
hard-negative target — and the hard negatives are of a different kind from the
one the protocol describes.

**What the open web actually yields, after ~135 fetches across two sessions:**

1. Kazakhstani press and official coverage of fraud overwhelmingly
   **describes** schemes. The pages that quote are a narrow set of formats:
   advice columns and explainers (zakon.kz *Советы*, nur.kz *Nurfin*,
   finance.kz, time.kz), institutions' own "phrases to watch for" lists (MIA
   via BAQ.KZ / Azattyq Rýhy / zakon.kz; Bank CenterCredit; the ARDFM portal),
   first-person special projects (sp.stan.kz), and Kazakh-language portals
   quoting a screenshot a journalist received (massaget.kz, baq.kz). News
   reports of arrests and warnings, in either language, almost never quote.
2. The quoted material is therefore skewed toward **call scripts**: 58 of 126
   rows have `channel: call`, against 16 `sms` and 16 `whatsapp`. Messaging
   text — the thing the bot actually classifies — is the scarcer half.
3. The two fact-checkers that reproduce viral text by design (`factcheck.kz`,
   `stopfake.kz`) are both unreachable to automation (403; broken TLS). They
   are still the densest untapped seam and need a browser session.
4. Genuine notification wording does not exist on the open web. The 17
   hard negatives are institutional notices, honest and useful for the
   false-positive test, but they are not "real 1414 codes, Kazpost tracking,
   Kaspi promos, Halyk login alerts". Those come only from donation.
5. Kazakh is not the scarce half in this collection either: 47 of 126 rows,
   and 24 of 59 scam messages, are Kazakh. Most of that is the MIA's
   bilingual publishing and the Kazakh-language portals' habit of quoting
   screenshots. Before H1 is interpreted, the report must say the language
   balance is a property of collection, not of the threat landscape.

### What actually gets the corpus to target

1. **Donation, started now.** Still the only path to genuine SMS/push hard
   negatives and to code-switched text. Per §2 of the eval protocol this is
   a week-1 task with an external dependency on other people.
2. **Manual collection from `factcheck.kz`, `stopfake.kz` and `baribar.kz`.**
   Blocked to automation, open in a browser. Search results show at least
   six stopfake.kz and eight factcheck.kz articles on message-based fraud.
3. **Mine the formats that quote.** More zakon.kz *Советы* columns, more
   MIA phrase lists (the ministry publishes them roughly every six months
   and press carries both languages), more Kazakh-language portals
   (massaget.kz, baq.kz, kaz.tengrinews.kz), and the bank press centres
   (bcc.kz yielded seven lines from one page; Forte, Jusan, Freedom, Home
   Credit and Eurasian press centres were not searched for phrase lists).
4. **Split tooling must honour `parallel pair key` and `Variant group key`**
   before any split is cut; §4 explains why the duplicate threshold alone is
   not enough.

---

## 6. Adding a domain

1. Fetch the page and confirm it quotes message text verbatim.
2. Download the raw HTML separately and confirm the text occurs in it; the
   fetch summariser has altered quotes before (§4).
3. Add a row to §2 with what the domain is and its terms status. Do not write
   "permits redistribution" without a located, quoted clause.
4. Collect with `tools/collect.py ingest`, which enforces provenance, URL and
   access date. Until the tag `system-freeze-v0.1` exists, every new batch is
   development data and the tool asks for `--dev`, which adds the batch to
   `data/exposure.json`. After the tag, each new row is compared with the
   development rows and fragments: a row from an article already read, or
   carrying a pair or variant key a development row has, is marked as
   development data; a row that resembles a development row without repeating
   it is held back until the draft says `"similar_to_dev": "variant"` or
   `"distinct"`
   ([holdout policy](15_P06_CORPUS_AUDIT_AND_HOLDOUT_2026-11-11.md), section 4).
5. Run `python tools/collect.py check --stats` before committing. It fails if
   a batch outside the register was collected before the freeze, or if a
   lookalike of a development row has no ruling.
