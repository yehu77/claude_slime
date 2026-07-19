"""Export transformed native SFT datasets from Claude tool-use traces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pycodeagent.auxiliary.native_transformed.sft_dataset import (
    build_native_transformed_sft_dataset,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export transformed native SFT datasets from Claude tool-use traces."
    )
    parser.add_argument("source_dir", help="Directory containing Claude gateway session JSONL files")
    parser.add_argument("output_dir", help="Directory to write dataset files")
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="Allow orphan gateway events to be retained instead of failing the session loader",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Skip bad session files and continue building the dataset",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    result = build_native_transformed_sft_dataset(
        Path(args.source_dir),
        Path(args.output_dir),
        strict=not args.no_strict,
        continue_on_error=args.continue_on_error,
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
