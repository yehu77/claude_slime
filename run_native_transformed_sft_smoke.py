"""Run a minimal native-transformed Claude API SFT overfit smoke."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pycodeagent.rl.native_transformed_sft_smoke import run_native_transformed_sft_smoke


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a minimal native-transformed SFT overfit smoke."
    )
    parser.add_argument("dataset_dir", help="Validated native-transformed raw dataset directory")
    parser.add_argument("prepared_dir", help="Existing native-transformed training-prep directory")
    parser.add_argument("output_dir", help="Directory to write smoke artifacts")
    parser.add_argument(
        "--model-name-or-path",
        required=True,
        help="Local Hugging Face causal LM path used for base eval and training",
    )
    parser.add_argument(
        "--tokenizer-name-or-path",
        help="Optional tokenizer path; defaults to --model-name-or-path",
    )
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--per-mode-probe-count", type=int, default=2)
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument(
        "--smoke-max-length",
        type=int,
        help=(
            "Optional smoke-only max token length. When set, the runner rebuilds "
            "the probe train set from trimmed raw samples instead of using full "
            "prepared examples."
        ),
    )
    parser.add_argument(
        "--allow-remote-files",
        action="store_true",
        help="Allow transformers to read remote model/tokenizer files if needed",
    )
    args = parser.parse_args()

    result = run_native_transformed_sft_smoke(
        Path(args.dataset_dir),
        Path(args.prepared_dir),
        Path(args.output_dir),
        model_name_or_path=Path(args.model_name_or_path),
        tokenizer_name_or_path=(
            Path(args.tokenizer_name_or_path)
            if args.tokenizer_name_or_path
            else None
        ),
        device=args.device,
        max_steps=args.max_steps,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        seed=args.seed,
        per_mode_probe_count=args.per_mode_probe_count,
        max_new_tokens=args.max_new_tokens,
        smoke_max_length=args.smoke_max_length,
        local_files_only=not args.allow_remote_files,
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
