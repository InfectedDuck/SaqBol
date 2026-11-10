"""T502 — the `results.json` reader and writer, per contract section 7.

`eval/results/results.json` is committed to git and `leaderboard.md` is
generated from it, never hand-edited. Both facts shape this module.

**Committed means the diff has to be readable.** Two runs that produce the same
numbers must produce byte-identical files, or every rerun shows as a change to
every row and the history stops being evidence of anything. So: fields in
contract order, two-space indent, floats rounded on write, a trailing newline,
and `ensure_ascii=False` so a Cyrillic model name stays legible.

**Generated means the file is the record.** `allow_nan=False` on write, because
Python emits bare `NaN` into JSON quite happily and every strict parser
downstream then rejects a file we have already committed. A metric that came
back undefined is a bug to fix at the call site, not a token to write into the
published record.

Unknown keys are preserved on read and written back out. T501 owns the harness
and may want to record more per row than the contract lists; this reader is not
the place that silently drops it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from saqbol.core.types import Lang
from saqbol.eval.metrics import Estimate

System = Literal["rules_only", "llm_zeroshot", "hybrid"]
Ablation = Literal["none", "translated", "cue_masked", "no_playbook_context"]
Split = Literal["train_synthetic", "dev", "calibration", "test_press", "test_donated"]

SYSTEMS: tuple[System, ...] = get_args(System)
ABLATIONS: tuple[Ablation, ...] = get_args(Ablation)
SPLITS: tuple[Split, ...] = get_args(Split)

#: Language codes come from the frozen `Lang` enum so they cannot drift, plus
#: "all" for a row aggregated over every language.
LANGS: tuple[str, ...] = (*(lang.value for lang in Lang), "all")

#: Floats are rounded to this many places on write. Six is far more precision
#: than any interval justifies and still kills the 0.7810000000000001 noise
#: that would otherwise churn the diff.
WRITE_NDIGITS = 6


class ResultRow(BaseModel):
    """One cell of the results matrix: a system, a model and a slice of data."""

    model_config = ConfigDict(extra="allow", protected_namespaces=())

    system: System
    model: str = Field(min_length=1)
    split: Split
    lang: str
    ablation: Ablation
    macro_f1: float = Field(ge=0.0, le=1.0)
    ci95: tuple[float, float]
    n: int = Field(ge=0)
    fpr_hard_negative: float | None = Field(default=None, ge=0.0, le=1.0)
    abstain_rate: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("lang")
    @classmethod
    def _known_language(cls, value: str) -> str:
        if value not in LANGS:
            raise ValueError(f"lang must be one of {LANGS}, got {value!r}")
        return value

    @field_validator("ci95")
    @classmethod
    def _ordered_interval(cls, value: tuple[float, float]) -> tuple[float, float]:
        lo, hi = value
        if not 0.0 <= lo <= hi <= 1.0:
            raise ValueError(f"ci95 must satisfy 0 <= lo <= hi <= 1, got [{lo}, {hi}]")
        return value

    @classmethod
    def from_estimate(
        cls,
        estimate: Estimate,
        *,
        system: System,
        model: str,
        split: Split,
        lang: str,
        ablation: Ablation = "none",
        fpr_hard_negative: float | None = None,
        abstain_rate: float | None = None,
        **extra: Any,
    ) -> ResultRow:
        """Build a row from a bootstrap estimate.

        The single seam T501 and T506 should use, so that no caller ever has to
        remember which end of `ci95` is which, or that `n` is the row count and
        not the resample count.
        """
        return cls(
            system=system,
            model=model,
            split=split,
            lang=lang,
            ablation=ablation,
            macro_f1=estimate.point,
            ci95=estimate.ci,
            n=estimate.n,
            fpr_hard_negative=fpr_hard_negative,
            abstain_rate=abstain_rate,
            **extra,
        )

    @property
    def ci(self) -> tuple[float, float]:
        return self.ci95


class Results(BaseModel):
    """A whole run: `eval/results/results.json`."""

    model_config = ConfigDict(extra="allow", protected_namespaces=())

    run_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    n_bootstrap: int = Field(ge=1)
    rows: list[ResultRow] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_duplicate_cells(self) -> Results:
        """A repeated cell means two numbers claim the same square of the
        matrix and the leaderboard would silently pick one of them."""
        seen: set[tuple[str, str, str, str, str]] = set()
        for row in self.rows:
            key = (row.system, row.model, row.split, row.lang, row.ablation)
            if key in seen:
                raise ValueError(f"duplicate result cell {key}")
            seen.add(key)
        return self

    def select(self, **criteria: str) -> list[ResultRow]:
        """Rows matching every named field, in file order.

        `results.select(system="hybrid", split="test_press", ablation="none")`
        is the query the leaderboard is built from.
        """
        unknown = set(criteria) - set(ResultRow.model_fields)
        if unknown:
            raise ValueError(f"unknown row fields {sorted(unknown)}")
        return [
            row
            for row in self.rows
            if all(getattr(row, field) == value for field, value in criteria.items())
        ]

    def __iter__(self) -> Iterator[ResultRow]:  # type: ignore[override]
        return iter(self.rows)


def _round_floats(value: Any, ndigits: int) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, ndigits)
    if isinstance(value, dict):
        return {k: _round_floats(v, ndigits) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_floats(v, ndigits) for v in value]
    return value


def read_results(path: str | os.PathLike[str]) -> Results:
    """Load and validate a results file.

    Validation is strict about the closed sets — an unknown system or ablation
    is a typo that would otherwise become a leaderboard row nobody can trace.
    """
    text = Path(path).read_text(encoding="utf-8")
    return Results.model_validate_json(text)


def write_results(
    path: str | os.PathLike[str],
    results: Results,
    *,
    ndigits: int = WRITE_NDIGITS,
) -> None:
    """Write a results file deterministically and atomically.

    Atomically because this file is the published record: a crash halfway
    through a write would replace a valid committed artefact with a truncated
    one. Fields with no value are omitted rather than written as `null`, so a
    row keeps only the numbers that were actually measured.
    """
    payload = _round_floats(results.model_dump(mode="json", exclude_none=True), ndigits)
    text = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, destination)
