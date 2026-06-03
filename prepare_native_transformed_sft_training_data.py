"""Prepare training artifacts from a native-transformed SFT dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pycodeagent.rl.training_prep import prepare_native_transformed_sft_training_input
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig


def _resolve_tokenizer_inputs(
    args: argparse.Namespace,
) -> tuple[TokenizerConfig, FakeTokenizerConfig | None]:
    if args.fake_tokenizer:
        return (
            TokenizerConfig(tokenizer_name="fake", max_length=args.max_length),
            FakeTokenizerConfig(
                vocab_size=args.fake_vocab_size,
                chars_per_token=args.fake_chars_per_token,
            ),
        )

    return (
        TokenizerConfig(
            tokenizer_name=args.tokenizer_name,
            max_length=args.max_length,
        ),
        None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare training artifacts from a validated native-transformed SFT dataset."
    )
    parser.add_argument(
        "source_dir",
        help="Directory containing native-transformed train.jsonl and validation artifacts",
    )
    parser.add_argument("output_dir", help="Directory to write prepared training artifacts")
    parser.add_argument("--split", default="train")
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--max-steps", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--run-id", default="native_transformed_sft_train")
    tokenizer_group = parser.add_mutually_exclusive_group(required=True)
    tokenizer_group.add_argument(
        "--tokenizer-name",
        help="HuggingFace tokenizer name or local path used for tensorization",
    )
    tokenizer_group.add_argument(
        "--fake-tokenizer",
        action="store_true",
        help="Use the deterministic fake tokenizer for dry runs and tests",
    )
    parser.add_argument("--fake-vocab-size", type=int, default=1000)
    parser.add_argument("--fake-chars-per-token", type=int, default=4)
    args = parser.parse_args()

    tokenizer_config, fake_tokenizer_config = _resolve_tokenizer_inputs(args)
    recommendation = prepare_native_transformed_sft_training_input(
        Path(args.source_dir),
        Path(args.output_dir),
        split=args.split,
        max_length=args.max_length,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        max_steps=args.max_steps,
        seed=args.seed,
        run_id=args.run_id,
        tokenizer_config=tokenizer_config,
        fake_tokenizer_config=fake_tokenizer_config,
    )
    print(json.dumps(recommendation.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
