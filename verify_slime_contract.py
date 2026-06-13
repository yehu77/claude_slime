"""CLI entrypoint for verifying slime-compatible data contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pycodeagent.rl.contract import verify_slime_contract
from pycodeagent.rl.dataset_manifest import FilterConfig
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig


def _resolve_tokenizer_inputs(
    args: argparse.Namespace,
) -> tuple[TokenizerConfig, FakeTokenizerConfig | None]:
    if args.fake_tokenizer:
        return (
            TokenizerConfig(tokenizer_name="fake", max_length=args.pack_max_length),
            FakeTokenizerConfig(
                vocab_size=args.fake_vocab_size,
                chars_per_token=args.fake_chars_per_token,
            ),
        )

    return (
        TokenizerConfig(
            tokenizer_name=args.tokenizer_name,
            max_length=args.pack_max_length,
        ),
        None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify pycodeagent rollout data against the slime training contract."
    )
    parser.add_argument("source_dir", help="Experiment, batch, or study output directory")
    parser.add_argument("output_dir", help="Directory to write verified dataset artifacts")
    parser.add_argument(
        "--source-type",
        choices=["experiment", "batch", "study"],
        default="experiment",
        help="Type of source directory",
    )
    parser.add_argument(
        "--include-failed",
        action="store_true",
        help="Include failed/error runs when building the dataset",
    )
    parser.add_argument(
        "--pack-max-length",
        type=int,
        default=2048,
        help="Max sequence length used for packing/tokenization verification",
    )
    tokenizer_group = parser.add_mutually_exclusive_group(required=True)
    tokenizer_group.add_argument(
        "--tokenizer-name",
        help="HuggingFace tokenizer name or local path used for contract verification",
    )
    tokenizer_group.add_argument(
        "--fake-tokenizer",
        action="store_true",
        help="Use the deterministic fake tokenizer for dry runs and tests",
    )
    parser.add_argument("--fake-vocab-size", type=int, default=1000)
    parser.add_argument("--fake-chars-per-token", type=int, default=4)
    args = parser.parse_args()

    filter_config = FilterConfig(include_failed=args.include_failed)
    tokenizer_config, fake_tokenizer_config = _resolve_tokenizer_inputs(args)
    result = verify_slime_contract(
        Path(args.source_dir),
        Path(args.output_dir),
        source_type=args.source_type,
        filter_config=filter_config,
        tokenizer_config=tokenizer_config,
        fake_tokenizer_config=fake_tokenizer_config,
        pack_max_length=args.pack_max_length,
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
