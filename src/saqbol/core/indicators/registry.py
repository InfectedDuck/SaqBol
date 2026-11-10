"""Indicator registry: the plugin mechanism for the deterministic layer.

Every rule in docs/03_INDICATORS.md registers here. The registry is what the
`rules_only` leaderboard row runs, so nothing in this module may touch the
network or an API key.

Two ways to register:

* `@indicator(...)` for a rule needing real logic, such as comparing a caller's
  country code against the institution it claims to be.
* `keyword_indicator(...)` for a phrase list, which is most of families A to D
  and H to J.

Phrase syntax is deliberately small and transparent, because a reviewer has to
be able to read the rules and a paper has to be able to describe them:

    "код из смс"        words separated by any whitespace run; quotation marks
                        around a word do not break the phrase
    "безопасн* счет*"   a trailing star allows up to four more letters, which
                        covers Russian and Kazakh inflection without a stemmer
    "назов* ~ код"      a tilde allows up to two other words, and commas,
                        between its neighbours, inside one sentence
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import cached_property, lru_cache

import regex as re

from saqbol.core.types import (
    RULE_SCORE_CAP,
    Entities,
    EvidenceSpan,
    IndicatorHit,
    NormalizedText,
    Severity,
)

ID_PATTERN = re.compile(r"^[A-J]\d+\.[a-z0-9_]+$")


@dataclass
class DetectionContext:
    """Everything a detector may look at. Read-only by convention.

    `metadata` carries surface-supplied facts that pasted text cannot provide:
    the sender's number, whether a Telegram account is newly created, whether
    the contact is known. Family I reads it and returns nothing when it is
    absent, rather than guessing from the text.
    """

    norm: NormalizedText
    entities: Entities
    thread: list[str]
    metadata: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.norm.text

    @cached_property
    def matchable(self) -> str:
        """Text folded for matching.

        Only same-length substitutions are permitted here, so character offsets
        into this string remain valid offsets into `text`. That is what lets a
        rule match "счёт" and still produce a span that quotes the original.
        """
        return fold_for_matching(self.norm.text)


Detector = Callable[[DetectionContext], list[IndicatorHit]]


def fold_for_matching(text: str) -> str:
    """Length-preserving fold: casefold plus the Russian yo/ye collapse.

    Writers use "счет" and "счёт" interchangeably, and a rule that misses one
    of them misses half its hits. Casefold already maps Ё to ё.

    `str.casefold` is not length-preserving for every character, German ß being
    the usual example, so the invariant is checked and a safe fallback used.
    Offsets into the result must stay valid offsets into the input.
    """
    folded = text.casefold().replace("ё", "е")
    if len(folded) == len(text):
        return folded
    return text.lower().replace("ё", "е")


@dataclass(frozen=True)
class IndicatorSpec:
    id: str
    severity: Severity
    description: str
    detector: Detector
    languages: tuple[str, ...] = ("ru", "kk", "en", "zh")

    @property
    def family(self) -> str:
        return self.id[0]


REGISTRY: dict[str, IndicatorSpec] = {}


def register(spec: IndicatorSpec) -> None:
    if not ID_PATTERN.match(spec.id):
        raise ValueError(
            f"indicator id {spec.id!r} must look like 'A1.otp_request' "
            "(family letter A-J, number, dot, snake_case slug)"
        )
    if spec.id in REGISTRY:
        raise ValueError(f"duplicate indicator id {spec.id!r}")
    REGISTRY[spec.id] = spec


def indicator(
    id: str,
    severity: Severity,
    description: str,
    languages: tuple[str, ...] = ("ru", "kk", "en", "zh"),
) -> Callable[[Detector], Detector]:
    """Decorator for a rule that needs real logic rather than a phrase list."""

    def deco(fn: Detector) -> Detector:
        register(
            IndicatorSpec(
                id=id,
                severity=severity,
                description=description,
                detector=fn,
                languages=languages,
            )
        )
        return fn

    return deco


_HAN = re.compile(r"[\p{Han}\p{Hiragana}\p{Katakana}]")

#: Between two adjacent words: whitespace, and the quotation marks a writer puts
#: around one of them. The safe-account phrase usually arrives as «безопасный»
#: счёт, scare quotes included.
_QUOTES = '"«»“”„‟'
_SEPARATOR = rf"[\s{_QUOTES}]+"

#: What a "~" stands for: up to two other words, with commas and dashes, on one
#: line and with no sentence end. "Проголосуй, пожалуйста, за Настю" is the same
#: request as "проголосуй за Настю". Digits are not words, so a phrase cannot
#: reach across a code or an amount.
GAP = "~"
_GAP_FILL = rf"[ \t,;:\-–—{_QUOTES}]+"
_GAP_WORD = r"\p{L}+(?:-\p{L}+)*"
_GAP_PATTERN = rf"(?:{_GAP_FILL}{_GAP_WORD}){{0,2}}{_GAP_FILL}"


@lru_cache(maxsize=2048)
def compile_phrase(phrase: str) -> re.Pattern:
    """Compile one phrase into a pattern.

    For alphabetic scripts, boundaries use a Unicode letter lookaround rather
    than `\\b`, so "код" does not fire inside "кодекс" in Russian or inside a
    Kazakh inflection.

    Chinese is written without spaces, so a Han phrase is almost always flanked
    by other Han characters. Applying the same lookaround there suppresses every
    match and silently disables the entire China playbook set, so Han phrases
    are matched without boundary assertions.
    """
    words = phrase.strip().split()
    if not words or words[0] == GAP or words[-1] == GAP:
        raise ValueError(f"phrase {phrase!r} must begin and end with a word")
    body = ""
    joiner = ""
    for word in words:
        if word == GAP:
            if joiner == _GAP_PATTERN:
                raise ValueError(f"phrase {phrase!r} has two gaps in a row")
            joiner = _GAP_PATTERN
            continue
        body += joiner
        if word.endswith("*"):
            body += re.escape(word[:-1]) + r"\p{L}{0,4}"
        else:
            body += re.escape(word)
        joiner = _SEPARATOR
    if _HAN.search(phrase):
        return re.compile(body)
    return re.compile(rf"(?<!\p{{L}}){body}(?!\p{{L}})")


#: Cues that invert the meaning of a following request phrase.
#: A genuine bank message reads "никому не сообщайте код" — never share this
#: code — which contains the same verb and noun as the scam that asks for it.
#: Without this, the highest-severity rule in the catalogue fires on the most
#: common legitimate message in the corpus.
NEGATION_CUES = (
    "никому не",
    "не сообщ",
    "не говор",
    "не передав",
    "не назыв",
    "не дикту",
    "не вводите",
    # A bank describing what it never does: "мы никогда не спрашиваем код".
    "никогда не",
    "не спрашива",
    "не запрашива",
    "не просим",
    "не просит",
    "не просят",
    # A warning quoting the request and then naming it: "просят назвать код
    # — это мошенники". Scammers say "мошенники пытаются", never "это
    # мошенники" about their own request, so the phrase is safe as a cue.
    "это мошенники",
    "never share",
    "do not share",
    "never ask",
    "请勿",
    "不要告诉",
)

#: Nouns that make a "tell me the code" request benign: the code of a door,
#: not of a bank. Checked only in a short window after the phrase, so
#: "скажите код от домофона" is a courier and "скажите код, домофон не
#: работает" is still a request.
BENIGN_OBJECT_CUES = ("домофон", "подъезд", "intercom", "есік коды", "домофонн")
BENIGN_OBJECT_WINDOW = 24

#: How far a negation cue may sit from the phrase and still govern it.
#: Checked in both directions: genuine one-time-password messages put the
#: warning before the code ("Никому не сообщайте код 4821") about as often as
#: after it ("Код подтверждения 8391 ... Никому не сообщайте код").
NEGATION_WINDOW_BEFORE = 40
NEGATION_WINDOW_AFTER = 60


def is_negated(
    haystack: str,
    start: int,
    end: int | None = None,
    before: int = NEGATION_WINDOW_BEFORE,
    after: int = NEGATION_WINDOW_AFTER,
) -> bool:
    end = start if end is None else end
    prefix = haystack[max(0, start - before) : start]
    suffix = haystack[end : end + after]
    if any(cue in prefix or cue in suffix for cue in NEGATION_CUES):
        return True
    near = haystack[end : end + BENIGN_OBJECT_WINDOW]
    return any(cue in near for cue in BENIGN_OBJECT_CUES)


def find_phrase_spans(
    ctx: DetectionContext,
    phrases: Iterable[str],
    indicator_id: str,
    *,
    respect_negation: bool = False,
) -> list[EvidenceSpan]:
    """Match `phrases` against the folded text, quoting the original.

    Shared by `keyword_indicator` and by custom detectors that need to add
    their own conditions on top of a phrase list.
    """
    haystack = ctx.matchable
    spans: list[EvidenceSpan] = []
    seen: set[tuple[int, int]] = set()
    for phrase in phrases:
        for m in compile_phrase(phrase).finditer(haystack):
            if (m.start(), m.end()) in seen:
                continue
            if respect_negation and is_negated(haystack, m.start(), m.end()):
                continue
            seen.add((m.start(), m.end()))
            spans.append(
                EvidenceSpan(
                    start=m.start(),
                    end=m.end(),
                    # Quote the ORIGINAL text, not the folded haystack, so the
                    # user is shown what they actually received.
                    text=ctx.text[m.start() : m.end()],
                    indicator_id=indicator_id,
                )
            )
    spans.sort(key=lambda s: s.start)
    return spans


def keyword_indicator(
    id: str,
    severity: Severity,
    description: str,
    phrases: Iterable[str],
    languages: tuple[str, ...] = ("ru", "kk", "en", "zh"),
    respect_negation: bool = False,
) -> None:
    """Register a rule that fires on any of `phrases`."""
    phrase_list = list(phrases)

    def detector(ctx: DetectionContext) -> list[IndicatorHit]:
        spans = find_phrase_spans(ctx, phrase_list, id, respect_negation=respect_negation)
        if not spans:
            return []
        return [IndicatorHit(indicator_id=id, severity=severity, spans=spans)]

    register(
        IndicatorSpec(
            id=id,
            severity=severity,
            description=description,
            detector=detector,
            languages=languages,
        )
    )


def run_all(ctx: DetectionContext, only: Iterable[str] | None = None) -> list[IndicatorHit]:
    """Run every registered detector. Order of results follows indicator id."""
    ids = sorted(REGISTRY) if only is None else sorted(only)
    hits: list[IndicatorHit] = []
    for indicator_id in ids:
        hits.extend(REGISTRY[indicator_id].detector(ctx))
    return hits


def score(hits: Iterable[IndicatorHit]) -> int:
    """Summed severity weight, capped. Combination bonuses are applied later,
    in `fuse.py`, so this stays a pure function of the individual rules."""
    return min(RULE_SCORE_CAP, sum(h.weight for h in hits))


def rule_norm(hits: Iterable[IndicatorHit]) -> float:
    return score(hits) / RULE_SCORE_CAP


def build_context(
    norm: NormalizedText,
    entities: Entities,
    thread: list[str] | None = None,
    metadata: dict | None = None,
) -> DetectionContext:
    return DetectionContext(
        norm=norm, entities=entities, thread=thread or [], metadata=metadata or {}
    )
