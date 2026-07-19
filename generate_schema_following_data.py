"""Generate controlled synthetic or trajectory-derived baseline datasets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pycodeagent.baselines import (
    SyntheticSchemaFollowingGenerationResult,
    TrajectoryDerivedGenerationResult,
    generate_schema_following_from_trajectories,
    generate_synthetic_schema_following_data,
)
from pycodeagent.rl.dataset_manifest import FilterConfig


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate controlled schema-following baseline datasets.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    synthetic = subparsers.add_parser(
        "synthetic",
        help="Generate a synthetic baseline from canonical intents.",
    )
    synthetic.add_argument("output_dir", help="Directory to write synthetic dataset files")
    synthetic.add_argument("--num-intents", type=int, default=120)
    synthetic.add_argument("--seed", type=int, default=42)

    trajectory = subparsers.add_parser(
        "trajectory-derived",
        help="Generate a baseline from recorded run trajectories.",
    )
    trajectory.add_argument("source_dir", help="Study, experiment, or batch directory")
    trajectory.add_argument("output_dir", help="Directory to write trajectory-derived dataset files")
    trajectory.add_argument(
        "--source-type",
        choices=["study", "experiment", "batch"],
        default="study",
    )
    trajectory.add_argument(
        "--include-failed",
        action="store_true",
        help="Include non-completed runs in extraction",
    )
    trajectory.add_argument(
        "--verifier-passed",
        choices=["true", "false", "any"],
        default="any",
        help="Filter source runs on verifier outcome",
    )
    trajectory.add_argument("--min-reward", type=float)
    trajectory.add_argument("--seed", type=int, default=42)

    return parser


def _print_result(
    result: SyntheticSchemaFollowingGenerationResult | TrajectoryDerivedGenerationResult,
) -> None:
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.subcommand == "synthetic":
        result = generate_synthetic_schema_following_data(
            Path(args.output_dir),
            num_intents=args.num_intents,
            seed=args.seed,
        )
        _print_result(result)
        return 0

    if args.subcommand == "trajectory-derived":
        verifier_passed = None
        if args.verifier_passed == "true":
            verifier_passed = True
        elif args.verifier_passed == "false":
            verifier_passed = False
        result = generate_schema_following_from_trajectories(
            Path(args.source_dir),
            Path(args.output_dir),
            source_type=args.source_type,
            filter_config=FilterConfig(
                include_failed=args.include_failed,
                verifier_passed=verifier_passed,
                min_reward=args.min_reward,
            ),
            seed=args.seed,
        )
        _print_result(result)
        return 0

    parser.error(f"Unknown subcommand: {args.subcommand}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
