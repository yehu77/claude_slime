"""Validate transformed native SFT datasets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pycodeagent.rl.native_transformed_sft_dataset_validate import (
    validate_native_transformed_sft_dataset,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a transformed native SFT dataset directory."
    )
    parser.add_argument(
        "dataset_dir",
        help="Directory containing transformed native train.jsonl and manifest files",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    result = validate_native_transformed_sft_dataset(Path(args.dataset_dir))
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
