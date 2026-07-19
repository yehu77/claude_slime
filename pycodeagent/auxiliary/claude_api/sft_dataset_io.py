"""JSONL helpers for auxiliary Claude API SFT datasets."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from pycodeagent.auxiliary.claude_api.sft import ClaudeApiSFTSample


class ClaudeApiSFTDatasetError(ValueError):
    """Raised when a Claude API SFT dataset file is malformed."""


def write_claude_api_sft_jsonl(
    samples: list[ClaudeApiSFTSample],
    path: str | Path,
) -> None:
    """Write Claude API SFT samples to deterministic JSONL."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(
                json.dumps(
                    sample.model_dump(mode="json"),
                    sort_keys=True,
                    ensure_ascii=False,
                )
            )
            handle.write("\n")


def read_claude_api_sft_jsonl(path: str | Path) -> list[ClaudeApiSFTSample]:
    """Read and validate Claude API SFT samples from JSONL."""
    path = Path(path)
    samples: list[ClaudeApiSFTSample] = []
    with open(path, encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ClaudeApiSFTDatasetError(
                    f"Invalid JSON on line {line_no} of {path}: {exc}"
                ) from exc
            try:
                samples.append(ClaudeApiSFTSample.model_validate(data))
            except ValidationError as exc:
                raise ClaudeApiSFTDatasetError(
                    f"Invalid Claude API SFT sample on line {line_no} of {path}: {exc}"
                ) from exc
    return samples


def validate_claude_api_sft_jsonl(path: str | Path) -> None:
    """Validate a Claude API SFT dataset JSONL file."""
    read_claude_api_sft_jsonl(path)
