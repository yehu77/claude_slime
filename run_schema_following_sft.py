"""Run a local schema-following SFT experiment with before/after evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pycodeagent.rl.schema_following_sft import run_schema_following_sft_experiment


def _parse_eval_splits(raw_value: str | None) -> list[str] | None:
    if raw_value is None or not raw_value.strip():
        return None
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a local schema-following SFT experiment and eval report."
    )
    parser.add_argument("dataset_dir", help="Schema-following dataset directory")
    parser.add_argument("output_dir", help="Directory to write experiment artifacts")
    parser.add_argument(
        "--model-name-or-path",
        required=True,
        help="Local Hugging Face causal LM path used for base and trained evaluation",
    )
    parser.add_argument(
        "--tokenizer-name-or-path",
        help="Optional tokenizer path; defaults to --model-name-or-path",
    )
    parser.add_argument("--train-split", default="train")
    parser.add_argument(
        "--eval-splits",
        help="Comma-separated eval splits. Defaults to dataset present_splits excluding train.",
    )
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--max-steps", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument(
        "--allow-remote-files",
        action="store_true",
        help="Allow transformers to read remote model/tokenizer files if needed",
    )
    args = parser.parse_args()

    result = run_schema_following_sft_experiment(
        Path(args.dataset_dir),
        Path(args.output_dir),
        model_name_or_path=Path(args.model_name_or_path),
        tokenizer_name_or_path=(
            Path(args.tokenizer_name_or_path)
            if args.tokenizer_name_or_path
            else None
        ),
        train_split=args.train_split,
        eval_splits=_parse_eval_splits(args.eval_splits),
        max_length=args.max_length,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        max_steps=args.max_steps,
        seed=args.seed,
        device=args.device,
        max_new_tokens=args.max_new_tokens,
        local_files_only=not args.allow_remote_files,
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
