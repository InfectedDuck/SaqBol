"""The public entry point: one message in, one verdict out.

    from saqbol.pipeline import analyze
    verdict = await analyze(text, locale=Lang.RU, surface="telegram")

This is the seam the bot and the web app code against, so its signature is
fixed. Everything behind it is swappable, which is what lets the evaluation run
the same pipeline in four configurations:

| System           | Retriever   | Model |
|------------------|-------------|-------|
| `rules_only`     | none        | no    |
| `llm_zeroshot`   | none        | yes   |
| `hybrid`         | lexical     | yes   |
| ablation         | dense, etc. | yes   |

The whole thing runs with no key and no network when no client is supplied,
which is how the deterministic baseline and CI work.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from saqbol.core.extract import extract
from saqbol.core.fuse import (
    DEFAULT_THRESHOLDS,
    DEFAULT_WEIGHTS,
    FusionWeights,
    Thresholds,
    choose_playbook,
    fuse,
)
from saqbol.core.graph import JUDGE_SYSTEM, build_user_prompt, sanitise_judgement
from saqbol.core.indicators.registry import build_context, run_all
from saqbol.core.normalize import normalize
from saqbol.core.retrieval import LexicalRetriever, NullRetriever, Retriever
from saqbol.core.types import Lang, LLMJudgement, Verdict
from saqbol.playbooks import loader
from saqbol.playbooks.schema import Playbook


@dataclass
class AnalyzerConfig:
    model: str = "deepseek-flash"
    top_k: int = 3
    temperature: float = 0.0
    weights: FusionWeights = field(default_factory=lambda: DEFAULT_WEIGHTS)
    thresholds: Thresholds = field(default_factory=lambda: DEFAULT_THRESHOLDS)
    #: Follow shorteners to their destination. Off by default: it makes a
    #: network call per link, and the baseline must stay offline.
    resolve_links: bool = False


class Analyzer:
    """Holds the loaded playbooks, the retriever and the optional model client.

    Constructed once and reused. Loading playbooks and building the retrieval
    index on every message would dominate the latency of an otherwise
    microsecond pipeline.
    """

    def __init__(
        self,
        *,
        playbooks: dict[str, Playbook] | None = None,
        retriever: Retriever | None = None,
        client: Any = None,
        config: AnalyzerConfig | None = None,
    ) -> None:
        self.playbooks = loader.load_all() if playbooks is None else playbooks
        self.retriever = retriever if retriever is not None else LexicalRetriever(self.playbooks)
        self.client = client
        self.config = config or AnalyzerConfig()

    # -- the pipeline ------------------------------------------------------

    async def analyze(
        self,
        text: str,
        *,
        locale: Lang | None = None,
        surface: str = "api",
        metadata: dict | None = None,
        thread: list[str] | None = None,
    ) -> Verdict:
        norm = normalize(text, lang_hint=locale)
        meta = dict(metadata or {})
        if self.config.resolve_links:
            meta["resolve_links"] = True

        entities = extract(norm.text)
        ctx = build_context(norm, entities, thread=thread or [], metadata=meta)
        hits = run_all(ctx)

        candidates = self.retriever.search(norm.text, self.config.top_k)
        retrieval = candidates[0] if candidates else None

        judgement: LLMJudgement | None = None
        spans = []
        model_name = ""
        latency_ms = 0
        cached = False

        if self.client is not None and norm.text.strip():
            judged = await self._judge(norm.text, candidates, hits)
            if judged is not None:
                judgement, spans, model_name, latency_ms, cached = judged

        playbook_id, _confidence = choose_playbook(judgement, retrieval)
        playbook = self.playbooks.get(playbook_id) if playbook_id else None

        return fuse(
            norm,
            hits,
            retrieval=retrieval,
            judgement=judgement,
            extra_evidence=spans,
            # Advice and the phone number come from the playbook file, never
            # from the model. This line is the whole safety property.
            action_key=playbook.action.key if playbook else "",
            hotline=playbook.hotline if playbook else "",
            model=model_name,
            latency_ms=latency_ms,
            cached=cached,
            weights=self.config.weights,
            thresholds=self.config.thresholds,
        )

    async def _judge(self, text: str, candidates, hits):
        """Ask the model, then sanitise. Returns None if the call fails.

        A provider outage, a refusal or a malformed answer must degrade to the
        deterministic verdict rather than to an error page: a user mid-scam
        needs an answer, and the rules alone still give one.
        """
        prompt = build_user_prompt(text, candidates, self.playbooks, hits)
        try:
            raw, stats = await self.client.structured(
                model=self.config.model,
                system=JUDGE_SYSTEM,
                user=prompt,
                schema=LLMJudgement,
                temperature=self.config.temperature,
            )
        except Exception:
            return None

        sanitised = sanitise_judgement(
            raw, text=text, candidates=[pid for pid, _score in candidates]
        )
        return (
            sanitised.judgement,
            sanitised.spans,
            getattr(stats, "model", self.config.model),
            getattr(stats, "latency_ms", 0),
            getattr(stats, "cached", False),
        )


_default: Analyzer | None = None

log = logging.getLogger(__name__)

#: Which model the live surfaces ask. Only the leaderboard varies it.
MODEL_ENV = "SAQBOL_MODEL"


def client_from_env(model: str, env: dict[str, str] | None = None) -> Any:
    """A model client when the model's provider has a key, otherwise None.

    None means the pipeline runs rules-only, which is the correct behaviour on a
    laptop with no .env and in CI. The decision is logged once at startup so a
    box that was meant to be hybrid and is silently deterministic gets noticed.
    """
    from saqbol.core.llm import LLMClient, ProviderNotConfigured, credentials, resolve

    source = os.environ if env is None else env
    try:
        credentials(resolve(model), source)
    except (ProviderNotConfigured, KeyError, ValueError) as exc:
        log.warning("Running rules-only: %s", exc)
        return None
    log.info("Model client ready for %s", model)
    return LLMClient(env=source)


def default_analyzer() -> Analyzer:
    """Process-wide analyzer. Call `reset_default()` after editing a playbook.

    Hybrid when the configured model's provider key is present, rules-only
    otherwise. SAQBOL_MODEL picks the model; the default is in AnalyzerConfig.
    """
    global _default
    if _default is None:
        model = os.environ.get(MODEL_ENV, "").strip() or AnalyzerConfig.model
        _default = Analyzer(client=client_from_env(model), config=AnalyzerConfig(model=model))
    return _default


def reset_default() -> None:
    global _default
    _default = None
    loader.registry.cache_clear()


async def analyze(
    text: str,
    *,
    locale: Lang | None = None,
    surface: str = "api",
    thread: list[str] | None = None,
    metadata: dict | None = None,
) -> Verdict:
    """The pinned seam. See the module docstring.

    `thread` is the earlier messages of a conversation, for stage detection.
    `metadata` carries what a surface knows and the text does not, such as
    forwarded-message provenance for indicator family I. Both are optional and
    both are ignored by the deterministic baseline when absent.
    """
    return await default_analyzer().analyze(
        text, locale=locale, surface=surface, thread=thread, metadata=metadata
    )


def rules_only_analyzer(
    playbooks: dict[str, Playbook] | None = None, *, thresholds: Thresholds | None = None
) -> Analyzer:
    """The `rules_only` leaderboard row: no retrieval, no model, no network.

    `thresholds` is for the calibration search, which confirms its choice by
    running this pipeline with it. Everything else uses the defaults.
    """
    config = AnalyzerConfig() if thresholds is None else AnalyzerConfig(thresholds=thresholds)
    return Analyzer(
        playbooks=playbooks or {}, retriever=NullRetriever(), client=None, config=config
    )
