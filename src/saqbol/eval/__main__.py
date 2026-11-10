"""`python -m saqbol.eval`: run the matrix, render the leaderboard, build the splits, or
fit the thresholds.

    python -m saqbol.eval run --config eval/configs/v0.1.yaml [--limit N]
        [--systems rules_only,hybrid] [--out DIR] [--run-id ID]
    python -m saqbol.eval leaderboard --results DIR/results.json --out DIR/leaderboard.md
    python -m saqbol.eval splits --corpus data/corpus --out data/kazscam_v0.1
        --seed 20260908 [--exposure data/exposure.json] [--calibration-size N]
    python -m saqbol.eval calibrate --config eval/configs/dev.yaml
        [--split dev] [--guard tests/fixtures/golden] [--out eval/calibration/rules_only.json]

`run` exits 0 whenever the run completed, however many cells were skipped:
the manifest and the summary printed here say which cells did not run and
why. A non-zero exit means the run itself could not complete — an unreadable
config, a malformed split, a system name the config does not list.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from saqbol.eval.calibrate import (
    DEFAULT_GUARD_DIR,
    DEFAULT_OUT,
    REGIMES,
    calibrate,
    describe,
    write_artifact,
)
from saqbol.eval.config import DEFAULT_SEED, load_config
from saqbol.eval.leaderboard import group_skipped, write_leaderboard
from saqbol.eval.run import DEFAULT_OUT_DIR, run
from saqbol.eval.splits import SPLIT_NAMES, build_and_write


def _say(text: str) -> None:
    """Print without tripping over a console that cannot show the text."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.write(text.encode(encoding, errors="replace").decode(encoding) + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m saqbol.eval", description="KazScam evaluation harness."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    runner = commands.add_parser("run", help="execute an evaluation matrix")
    runner.add_argument("--config", required=True, type=Path, help="matrix YAML file")
    runner.add_argument("--limit", type=int, default=None, help="rows per cell, in file order")
    runner.add_argument(
        "--systems", default=None, help="comma-separated subset of the config's systems"
    )
    runner.add_argument(
        "--out", type=Path, default=DEFAULT_OUT_DIR, help="directory that receives <run_id>/"
    )
    runner.add_argument("--run-id", default=None, help="name of the run directory")

    board = commands.add_parser("leaderboard", help="render leaderboard.md from results.json")
    board.add_argument("--results", required=True, type=Path, help="path to results.json")
    board.add_argument(
        "--out", type=Path, default=None, help="output path (default: beside results.json)"
    )

    splitter = commands.add_parser("splits", help="build the KazScam splits from the corpus")
    splitter.add_argument(
        "--corpus", type=Path, default=Path("data/corpus"), help="directory of corpus batch files"
    )
    splitter.add_argument(
        "--out", type=Path, default=Path("data/kazscam_v0.1"), help="directory for the JSONL files"
    )
    splitter.add_argument("--seed", type=int, default=DEFAULT_SEED, help="assignment seed")
    splitter.add_argument(
        "--exposure",
        type=Path,
        default=None,
        help="exposure register (default: exposure.json beside the corpus directory, if present)",
    )
    splitter.add_argument(
        "--calibration-size",
        type=int,
        default=None,
        help="override the contract's calibration rule with a row count, "
        "capped at 40%% of the fresh press pool",
    )
    fitter = commands.add_parser(
        "calibrate", help="fit the rules-only warning threshold on calibration data"
    )
    fitter.add_argument("--config", required=True, type=Path, help="matrix YAML file")
    fitter.add_argument(
        "--split",
        default=None,
        choices=sorted(REGIMES),
        help="split to fit on (default: calibration if it has rows, else dev)",
    )
    fitter.add_argument(
        "--guard", type=Path, default=DEFAULT_GUARD_DIR, help="directory of regression cases"
    )
    fitter.add_argument("--out", type=Path, default=DEFAULT_OUT, help="artifact path")
    return parser


def _run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    systems = None
    if args.systems:
        systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    outcome = run(
        config,
        out_dir=args.out,
        limit=args.limit,
        systems=systems,
        run_id=args.run_id,
        config_path=args.config,
    )
    counts = outcome.manifest["cells"]
    _say(
        f"run {outcome.run_id}: {counts['executed']} of {counts['planned']} cells executed, "
        f"{counts['skipped']} skipped"
    )
    for reason, count, systems, splits in group_skipped([s.as_dict() for s in outcome.skipped]):
        where = f"{', '.join(systems)} on {', '.join(splits)}"
        _say(f"  {count} cell{'s' if count != 1 else ''} skipped ({where}): {reason}")
    _say(f"wrote {outcome.results_path}")
    _say(f"wrote {outcome.manifest_path}")
    return 0


def _leaderboard(args: argparse.Namespace) -> int:
    out = args.out if args.out is not None else args.results.with_name("leaderboard.md")
    written = write_leaderboard(args.results, out)
    _say(f"wrote {written}")
    return 0


def _splits(args: argparse.Namespace) -> int:
    manifest = build_and_write(
        args.corpus,
        args.out,
        seed=args.seed,
        calibration_size=args.calibration_size,
        exposure_path=args.exposure,
    )
    counts = ", ".join(f"{name}={manifest['splits'][name]['n']}" for name in SPLIT_NAMES)
    _say(
        f"splits (seed {manifest['seed']}, {manifest['calibration']['regime']}): {counts}; "
        f"{manifest['excluded_fragments']} fragments excluded, "
        f"{manifest['groups']['n_multi_row_groups']} multi-row groups kept together"
    )
    _say(f"wrote {Path(args.out) / 'manifest.json'}")
    return 0


def _calibrate(args: argparse.Namespace) -> int:
    payload = calibrate(
        load_config(args.config), split=args.split, guard_dir=args.guard, config_path=args.config
    )
    for line in describe(payload):
        _say(line)
    _say(f"wrote {write_artifact(payload, args.out)}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            return _run(args)
        if args.command == "splits":
            return _splits(args)
        if args.command == "calibrate":
            return _calibrate(args)
        return _leaderboard(args)
    except (ValueError, OSError) as exc:
        # A config, split or results file the run cannot use. The message
        # names the file and the field; a traceback would add nothing.
        sys.stderr.write(f"error: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
