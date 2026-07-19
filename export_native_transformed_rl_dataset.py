"""Export native-transformed RL prompt datasets from existing SFT samples."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pycodeagent.auxiliary.native_transformed.rl_dataset import (
    export_native_transformed_rl_dataset,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export prompt-only native-transformed RL samples from an existing "
            "native-transformed SFT train.jsonl or dataset directory."
        )
    )
    parser.add_argument(
        "source_path",
        help="Native-transformed SFT dataset directory or train.jsonl path",
    )
    parser.add_argument("output_dir", help="Directory to write RL prompt dataset files")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    result = export_native_transformed_rl_dataset(
        Path(args.source_path),
        Path(args.output_dir),
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
