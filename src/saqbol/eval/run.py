"""T501 — the harness behind `python -m saqbol.eval run`.

One run walks the matrix in `EvalConfig`, executes every cell it can, and
writes three files under `<out>/<run_id>/`:

- `results.json`, in the contract section 7 shape, through `results.py`,
  with the row counts the leaderboard's minimum-support rules are checked
  against (`support.py`);
- `manifest.json`: config hash, git commit, timestamp, row counts per split
  and language, and every cell that did not run with its reason;
- `predictions.jsonl`: one line per row per executed cell, with the gold
  labels and what the system said, so any number in `results.json` can be
  traced to the rows behind it.

Three rules shape the loop.

**A cell that cannot run is a reason, not an exception.** A split file that
does not exist yet, a model with no provider key, an ablation the split cannot
support — each is written to the manifest and the run continues. The matrix in
`eval/configs/v0.1.yaml` names files and models that will exist over the
coming weeks, and the harness has to be runnable on every day in between.

**Abstention is scored as coverage, not as an error class.** Macro-F1 is
computed over the rows the system answered, with `abstain_rate` (and its
complement, `coverage`) reported beside it on every row, following the
protocol's risk-at-coverage framing. The hard-negative false-positive rate
keeps abstentions in its denominator, as `metrics.hard_negative_fpr` insists,
so declining to answer cannot flatter the number that decides whether people
uninstall. Rows whose gold label is `ambiguous` have no place in a scam/legit
F1 and are excluded from it, counted in `n_ambiguous`.

**Everything is seeded.** The bootstrap seed comes from the config (default
20260908), the same seed is used for every cell, and the seed is written into
every results row. Two runs over the same rows produce the same numbers.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import subprocess
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from saqbol.core.fuse import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS
from saqbol.eval import metrics
from saqbol.eval.config import LLM_SYSTEMS, EvalConfig, config_hash
from saqbol.eval.results import ResultRow, Results, write_results
from saqbol.eval.support import count_support
from saqbol.eval.systems import (
    ABSTAIN_BAND,
    NO_MODEL,
    Prediction,
    System,
    band_to_label,
    build_system,
    client_for,
    judge_prompt_hash,
    zeroshot_prompt_hash,
)

#: Contract section 6: the gold label set.
GoldLabel = Literal["scam", "legit", "ambiguous"]
#: The label space of the headline macro-F1.
BINARY_LABELS: tuple[str, ...] = ("legit", "scam")
#: The class a scam row belongs to when no playbook is named, on either side:
#: a gold scam that fits none of the scripts, or a system that named none.
MISSING_PLAYBOOK = "none"
#: The row field the `translated` ablation reads; absent on untranslated rows.
TRANSLATION_FIELD = "text_translated"
#: Where results go when the CLI is not told otherwise.
DEFAULT_OUT_DIR = Path("eval") / "results"

SystemFactory = Callable[..., System]


# ---------------------------------------------------------------------------
# Dataset rows
# ---------------------------------------------------------------------------


class DatasetRow(BaseModel):
    """One KazScam row, per docs/02_DATA_CONTRACTS.md section 6.

    Only the fields the harness reads are typed; the rest travel through as
    extras so a row is never rejected for carrying more than the harness
    needs.
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    text: str
    label: GoldLabel
    playbook_id: str | None = None
    stage: str | None = None
    lang: str = Field(min_length=1)
    hard_negative: bool = False
    source_group: str | None = None
    annotator_a: str | None = None
    annotator_b: str | None = None
    text_translated: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> DatasetRow:
        if self.hard_negative and self.label != "legit":
            raise ValueError(
                f"row {self.id}: a hard negative is by definition legitimate, got {self.label!r}"
            )
        if self.playbook_id and self.label != "scam":
            raise ValueError(f"row {self.id}: playbook_id is only set when label == scam")
        return self


def load_split(path: str | os.PathLike[str]) -> list[DatasetRow]:
    """Read one JSONL split. Malformed rows raise with their line number."""
    rows: list[DatasetRow] = []
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(DatasetRow.model_validate_json(line))
            except ValidationError as exc:
                raise ValueError(f"{path}:{number}: {exc}") from None
    return rows


def filter_rows(rows: Sequence[DatasetRow], lang: str) -> list[DatasetRow]:
    """Rows whose `lang` field equals `lang`; `all` keeps every row."""
    if lang == "all":
        return list(rows)
    return [r for r in rows if r.lang == lang]


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cell:
    """One square of the results matrix."""

    system: str
    model: str
    split: str
    lang: str
    ablation: str

    def as_dict(self) -> dict[str, str]:
        return {
            "system": self.system,
            "model": self.model,
            "split": self.split,
            "lang": self.lang,
            "ablation": self.ablation,
        }

    def __str__(self) -> str:
        return f"{self.system}/{self.model}/{self.split}/{self.lang}/{self.ablation}"


@dataclass(frozen=True)
class SkippedCell:
    cell: Cell
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {**self.cell.as_dict(), "reason": self.reason}


class CellSkipped(Exception):
    """Raised inside cell execution to record a reason and move on."""


def plan_cells(config: EvalConfig, systems: Sequence[str] | None = None) -> list[Cell]:
    """Every cell of the matrix, in a fixed order.

    `rules_only` has no model, so it is crossed with the single model name
    `none` rather than with every model in the config.
    """
    chosen = list(config.systems) if systems is None else list(systems)
    cells: list[Cell] = []
    for system in chosen:
        models = config.models if system in LLM_SYSTEMS else [NO_MODEL]
        for model in models:
            for split in config.splits:
                for lang in config.languages:
                    for ablation in config.ablations:
                        cells.append(Cell(system, model, split, lang, ablation))
    return cells


# ---------------------------------------------------------------------------
# Ablation texts
# ---------------------------------------------------------------------------


def _cue_mask_transform() -> Callable[[str], str] | None:
    """The cue-masking transform, if `saqbol.core.obfuscation` exports one."""
    try:
        from saqbol.core import obfuscation
    except ImportError:
        return None
    transform = getattr(obfuscation, "cue_mask", None)
    if transform is None:
        return None

    def masked(text: str) -> str:
        # The transform ignores its rate and rng by design; both are passed
        # so the call matches the signature every transform shares.
        return transform(text, 1.0, random.Random(0))

    return masked


def ablation_inputs(
    rows: Sequence[DatasetRow], ablation: str, system: str
) -> tuple[list[DatasetRow], list[str]]:
    """The rows a cell runs on and the text each one is run with.

    Raises `CellSkipped` when the ablation cannot be applied to this system or
    these rows.
    """
    if ablation == "none":
        return list(rows), [r.text for r in rows]
    if ablation == "no_playbook_context":
        if system == "rules_only":
            raise CellSkipped("ablation not applicable: rules_only has no retrieval to disable")
        if system == "llm_zeroshot":
            raise CellSkipped("ablation not applicable: llm_zeroshot never sees playbook context")
        return list(rows), [r.text for r in rows]
    if ablation == "cue_masked":
        transform = _cue_mask_transform()
        if transform is None:
            raise CellSkipped("cue-masking transform is not exported by saqbol.core.obfuscation")
        return list(rows), [transform(r.text) for r in rows]
    if ablation == "translated":
        translated = [r for r in rows if r.text_translated and r.text_translated.strip()]
        if not translated:
            raise CellSkipped(f"split has no translations (no row carries `{TRANSLATION_FIELD}`)")
        return translated, [r.text_translated or "" for r in translated]
    raise CellSkipped(f"unknown ablation {ablation!r}")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CellScore:
    """Every number one cell contributes to `results.json`."""

    macro_f1: metrics.Estimate
    abstain_rate: float
    fpr_hard_negative: float | None
    extra: dict[str, Any] = field(default_factory=dict)


def _defined(values: Mapping[str, float]) -> dict[str, float]:
    return {k: v for k, v in values.items() if not math.isnan(v)}


def score_cell(
    rows: Sequence[DatasetRow],
    predictions: Sequence[Prediction],
    *,
    seed: int,
    n_bootstrap: int,
    positive_bands: Sequence[str] = ("scam", "suspicious"),
) -> CellScore:
    """Compute every metric for one cell from its rows and predictions.

    Raises `CellSkipped` when macro-F1 is undefined, which happens when the
    system answered none of the scorable rows.
    """
    if len(rows) != len(predictions):
        raise ValueError(f"{len(rows)} rows but {len(predictions)} predictions")
    if not rows:
        raise CellSkipped("no rows to score")

    n = len(rows)
    y_true = [r.label for r in rows]
    y_pred = [band_to_label(p.band, positive_bands) for p in predictions]
    abstain = metrics.abstain_rate(y_pred)

    n_ambiguous = sum(1 for t in y_true if t == "ambiguous")
    scorable = [(t, p) for t, p in zip(y_true, y_pred, strict=True) if t != "ambiguous"]
    answered = [(t, p) for t, p in scorable if p != ABSTAIN_BAND]
    if not answered:
        raise CellSkipped(
            f"macro-F1 undefined: the system answered none of the {len(scorable)} scorable rows"
        )
    bin_true = [t for t, _ in answered]
    bin_pred = [p for _, p in answered]

    estimate = metrics.bootstrap_ci(
        bin_true, bin_pred, seed=seed, n_resamples=n_bootstrap, labels=BINARY_LABELS
    )
    extra: dict[str, Any] = {
        "seed": seed,
        "n_rows": n,
        "n_answered": sum(1 for p in y_pred if p != ABSTAIN_BAND),
        "n_ambiguous": n_ambiguous,
        "coverage": 1.0 - abstain,
        "selective_risk": metrics.selective_risk(bin_true, bin_pred),
        "per_class_f1": _defined(metrics.per_class_f1(bin_true, bin_pred, labels=BINARY_LABELS)),
    }
    # What the cell holds, for the leaderboard's minimum-support rules. The
    # counts are of gold rows, whatever the system did with them: support is
    # a property of the data, so every system on one slice is treated alike.
    support = count_support(rows)
    extra["n_by_label"] = support["by_label"]
    if "n_source_groups" in support:
        extra["n_source_groups"] = support["n_source_groups"]

    hard = [r.hard_negative for r in rows]
    fpr: float | None = None
    if any(hard):
        fpr = metrics.hard_negative_fpr(y_true, y_pred, hard)
        fpr_ci = metrics.hard_negative_fpr_ci(
            y_true, y_pred, hard, seed=seed, n_resamples=n_bootstrap
        )
        extra["n_hard_negative"] = sum(hard)
        extra["fpr_hard_negative_ci95"] = [fpr_ci.lo, fpr_ci.hi]
        extra["fpr_hard_negative_ci_method"] = fpr_ci.method

    # The 13-way playbook label, over the scam rows the system answered. A
    # scam row answered `legit` is a miss with no playbook, and stays in.
    # Rows that have not been annotated carry no gold playbook at all; a
    # system that names none would then score a perfect 1.000 for agreeing
    # with nothing, so a cell without a single gold playbook is not scored.
    scam_rows = [
        (r, p)
        for r, p, label in zip(rows, predictions, y_pred, strict=True)
        if r.label == "scam" and label != ABSTAIN_BAND
    ]
    if any(r.playbook_id for r, _ in scam_rows):
        true_pb = [r.playbook_id or MISSING_PLAYBOOK for r, _ in scam_rows]
        pred_pb = [p.playbook_id or MISSING_PLAYBOOK for _, p in scam_rows]
        playbook = metrics.bootstrap_ci(true_pb, pred_pb, seed=seed, n_resamples=n_bootstrap)
        extra["playbook_macro_f1"] = playbook.point
        extra["playbook_ci95"] = [playbook.lo, playbook.hi]
        extra["playbook_n"] = playbook.n
        extra["playbook_f1"] = _defined(metrics.per_class_f1(true_pb, pred_pb))

        stage = metrics.stage_accuracy(
            true_pb, pred_pb, [r.stage for r, _ in scam_rows], [p.stage for _, p in scam_rows]
        )
        if stage.n_eligible:
            extra["stage_accuracy"] = stage.accuracy
            extra["stage_n_eligible"] = stage.n_eligible
            extra["stage_n_correct"] = stage.n_correct

    n_errors = sum(1 for p in predictions if p.error)
    if n_errors:
        extra["n_errors"] = n_errors

    return CellScore(macro_f1=estimate, abstain_rate=abstain, fpr_hard_negative=fpr, extra=extra)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@dataclass
class RunOutcome:
    run_id: str
    out_dir: Path
    results: Results
    manifest: dict[str, Any]
    skipped: list[SkippedCell]

    @property
    def results_path(self) -> Path:
        return self.out_dir / "results.json"

    @property
    def manifest_path(self) -> Path:
        return self.out_dir / "manifest.json"

    @property
    def predictions_path(self) -> Path:
        return self.out_dir / "predictions.jsonl"


def fusion_in_force() -> dict[str, dict[str, float]]:
    """The weights and thresholds every pipeline system in a run is built with.

    Written to the manifest so a result can be checked against the calibration
    artifact that selected them.
    """
    return {"weights": asdict(DEFAULT_WEIGHTS), "thresholds": asdict(DEFAULT_THRESHOLDS)}


def git_commit() -> str | None:
    """The checked-out commit, read with a command that writes nothing."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_run_id(timestamp: str) -> str:
    """The timestamp without colons, since the run id names a directory."""
    return timestamp.replace(":", "")


async def _predict_all(
    system: System, texts: Sequence[str], langs: Sequence[str], concurrency: int
) -> list[Prediction]:
    """Every row's prediction, in row order, at most `concurrency` in flight."""
    gate = asyncio.Semaphore(concurrency)

    async def one(text: str, lang: str) -> Prediction:
        async with gate:
            return await system.predict(text, lang=lang)

    return list(await asyncio.gather(*(one(t, lang) for t, lang in zip(texts, langs, strict=True))))


def _prediction_records(
    cell: Cell,
    rows: Sequence[DatasetRow],
    predictions: Sequence[Prediction],
    positive_bands: Sequence[str],
) -> Iterator[dict[str, Any]]:
    for row, prediction in zip(rows, predictions, strict=True):
        yield {
            **cell.as_dict(),
            "id": row.id,
            "gold_label": row.label,
            "gold_playbook_id": row.playbook_id,
            "gold_stage": row.stage,
            "hard_negative": row.hard_negative,
            "band": prediction.band,
            "label": band_to_label(prediction.band, positive_bands),
            "playbook_id": prediction.playbook_id,
            "stage": prediction.stage,
            "confidence": round(prediction.confidence, 6),
            "error": prediction.error,
        }


class _Runner:
    """State for one run: loaded splits, built systems, client lookups."""

    def __init__(
        self,
        config: EvalConfig,
        *,
        env: Mapping[str, str],
        limit: int | None,
        system_factory: SystemFactory,
        loop: asyncio.Runner,
        clients: Mapping[str, Any],
    ) -> None:
        self.config = config
        self.env = env
        self.limit = limit
        self.system_factory = system_factory
        self.loop = loop
        self._splits: dict[str, list[DatasetRow] | None] = {}
        self._systems: dict[tuple[str, str, bool], System] = {}
        self._clients: dict[str, tuple[Any | None, str | None]] = {
            model: (client, None) for model, client in clients.items()
        }

    # -- inputs -------------------------------------------------------------

    def split_rows(self, split: str) -> list[DatasetRow] | None:
        if split not in self._splits:
            path = self.config.split_path(split)
            self._splits[split] = load_split(path) if path.is_file() else None
        return self._splits[split]

    def split_summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for split in self.config.splits:
            rows = self.split_rows(split)
            entry: dict[str, Any] = {"path": self.config.splits[split], "exists": rows is not None}  # type: ignore[index]
            if rows is not None:
                entry.update(count_support(rows))
            summary[split] = entry
        return summary

    def split_support(self) -> dict[str, Any]:
        """`count_support` of every split that was read, for `results.json`.

        The leaderboard is generated from that file alone, and the release
        tier is a fact about a whole split, which no single cell records.
        """
        support: dict[str, Any] = {}
        for split in self.config.splits:
            rows = self.split_rows(split)
            if rows is not None:
                support[split] = count_support(rows)
        return support

    # -- systems ------------------------------------------------------------

    def client(self, model: str) -> tuple[Any | None, str | None]:
        if model not in self._clients:
            self._clients[model] = client_for(model, self.env)
        return self._clients[model]

    def system(self, cell: Cell) -> System:
        no_context = cell.ablation == "no_playbook_context"
        key = (cell.system, cell.model, no_context)
        if key not in self._systems:
            client = None
            if cell.system in LLM_SYSTEMS:
                client, reason = self.client(cell.model)
                if client is None:
                    raise CellSkipped(reason or "no model client")
            self._systems[key] = self.system_factory(
                cell.system, model=cell.model, client=client, no_playbook_context=no_context
            )
        return self._systems[key]

    # -- one cell -----------------------------------------------------------

    def execute(self, cell: Cell) -> tuple[ResultRow, list[dict[str, Any]]]:
        """Run one cell. Raises `CellSkipped` with the reason when it cannot."""
        rows = self.split_rows(cell.split)
        if rows is None:
            raise CellSkipped(f"split file missing: {self.config.splits[cell.split]}")  # type: ignore[index]
        rows = filter_rows(rows, cell.lang)
        if not rows:
            raise CellSkipped(f"no rows with lang={cell.lang!r} in split {cell.split!r}")
        # The system comes before the ablation so that a model with no key is
        # recorded as exactly that, whatever else the cell would have lacked.
        system = self.system(cell)
        rows, texts = ablation_inputs(rows, cell.ablation, cell.system)
        if self.limit is not None:
            rows, texts = rows[: self.limit], texts[: self.limit]

        predictions = self.loop.run(
            _predict_all(system, texts, [r.lang for r in rows], self.config.concurrency)
        )
        score = score_cell(
            rows,
            predictions,
            seed=self.config.seed,
            n_bootstrap=self.config.n_bootstrap,
            positive_bands=self.config.positive_bands,
        )
        extra = dict(score.extra)
        if system.prompt_hash:
            extra["prompt_hash"] = system.prompt_hash
        row = ResultRow.from_estimate(
            score.macro_f1,
            system=cell.system,  # type: ignore[arg-type]
            model=cell.model,
            split=cell.split,  # type: ignore[arg-type]
            lang=cell.lang,
            ablation=cell.ablation,  # type: ignore[arg-type]
            fpr_hard_negative=score.fpr_hard_negative,
            abstain_rate=score.abstain_rate,
            **extra,
        )
        records = list(_prediction_records(cell, rows, predictions, self.config.positive_bands))
        return row, records


def select_systems(config: EvalConfig, systems: Sequence[str] | None) -> list[str]:
    """The systems to run: the config's, or the requested subset of them."""
    if systems is None:
        return list(config.systems)
    unknown = [s for s in systems if s not in config.systems]
    if unknown:
        raise ValueError(f"systems {unknown} are not in the config, which lists {config.systems}")
    return [s for s in config.systems if s in systems]


def run(
    config: EvalConfig,
    *,
    out_dir: str | os.PathLike[str] = DEFAULT_OUT_DIR,
    limit: int | None = None,
    systems: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    run_id: str | None = None,
    config_path: str | os.PathLike[str] | None = None,
    system_factory: SystemFactory = build_system,
    clients: Mapping[str, Any] | None = None,
) -> RunOutcome:
    """Execute the matrix and write `<out_dir>/<run_id>/`.

    `env` is where provider keys are looked up; pass an empty mapping to
    guarantee that no model is called. `clients` supplies ready-made model
    clients by model name — a replay client, a stub in a test — and a model
    listed there needs no key. `limit` caps the rows per cell, in file order,
    for a quick pass over a large split.
    """
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    environment: Mapping[str, str] = os.environ if env is None else env
    chosen = select_systems(config, systems)
    timestamp = _timestamp()
    run_id = run_id or _default_run_id(timestamp)

    cells = plan_cells(config, chosen)
    rows: list[ResultRow] = []
    skipped: list[SkippedCell] = []
    records: list[dict[str, Any]] = []
    # One event loop for the whole run, so a client built for the first cell
    # is still usable by the last one.
    with asyncio.Runner() as loop:
        runner = _Runner(
            config,
            env=environment,
            limit=limit,
            system_factory=system_factory,
            loop=loop,
            clients=clients or {},
        )
        for cell in cells:
            try:
                row, cell_records = runner.execute(cell)
            except CellSkipped as exc:
                skipped.append(SkippedCell(cell, str(exc)))
                continue
            rows.append(row)
            records.extend(cell_records)

    digest = config_hash(config)
    commit = git_commit()
    results = Results(
        run_id=run_id,
        dataset_version=config.dataset_version,
        n_bootstrap=config.n_bootstrap,
        rows=rows,
        seed=config.seed,
        config_hash=digest,
        git_commit=commit,
        limit=limit,
        split_support=runner.split_support(),
    )
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "timestamp": timestamp,
        "config_name": config.name,
        "config_path": Path(config_path).as_posix() if config_path is not None else None,
        "config_hash": digest,
        "git_commit": commit,
        "dataset_version": config.dataset_version,
        "seed": config.seed,
        "n_bootstrap": config.n_bootstrap,
        "limit": limit,
        "systems": chosen,
        "models": list(config.models),
        "languages": list(config.languages),
        "ablations": list(config.ablations),
        "positive_bands": list(config.positive_bands),
        "fusion": fusion_in_force(),
        "prompt_hashes": {
            "llm_zeroshot": zeroshot_prompt_hash(),
            "hybrid": judge_prompt_hash(),
        },
        "splits": runner.split_summary(),
        "cells": {
            "planned": len(cells),
            "executed": len(rows),
            "skipped": len(skipped),
        },
        "skipped": [s.as_dict() for s in skipped],
    }

    destination = Path(out_dir) / run_id
    destination.mkdir(parents=True, exist_ok=True)
    write_results(destination / "results.json", results)
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (destination / "predictions.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    return RunOutcome(
        run_id=run_id, out_dir=destination, results=results, manifest=manifest, skipped=skipped
    )
