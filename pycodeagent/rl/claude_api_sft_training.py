"""Prepared training artifacts for Claude API SFT samples."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.rl.claude_api_sft import ClaudeApiSFTSample
from pycodeagent.rl.loss_mask import build_loss_mask
from pycodeagent.rl.serializer import serialize_claude_api_sft_sample


class ClaudeApiSFTPreparedSample(BaseModel):
    """Claude API SFT sample after serialization and mask construction."""

    sample_id: str
    sample_type: str
    source_type: str
    task_id: str
    tool_profile_id: str
    loss_mask_policy: str
    text: str
    segments: list[dict[str, Any]]
    character_mask: list[int]
    spans: list[dict[str, Any]]
    trainable_char_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_claude_api_sft_prepared_sample(
    sample: ClaudeApiSFTSample,
    *,
    extra_metadata: dict[str, Any] | None = None,
) -> ClaudeApiSFTPreparedSample:
    """Build a prepared Claude API SFT sample from the raw SFT sample."""
    serialized = serialize_claude_api_sft_sample(sample)
    loss_mask = build_loss_mask(serialized)
    metadata = dict(serialized.metadata)
    if extra_metadata:
        metadata.update(extra_metadata)

    return ClaudeApiSFTPreparedSample(
        sample_id=serialized.sample_id,
        sample_type=serialized.sample_type,
        source_type=serialized.source_type,
        task_id=serialized.task_id,
        tool_profile_id=serialized.tool_profile_id,
        loss_mask_policy=serialized.loss_mask_policy,
        text=serialized.text,
        segments=[segment.model_dump(mode="json") for segment in serialized.segments],
        character_mask=loss_mask.character_mask,
        spans=[span.model_dump(mode="json") for span in loss_mask.spans],
        trainable_char_count=loss_mask.trainable_char_count,
        metadata=metadata,
    )


def build_claude_api_sft_prepared_samples(
    samples: list[ClaudeApiSFTSample],
) -> list[ClaudeApiSFTPreparedSample]:
    """Build prepared Claude API SFT samples in deterministic order."""
    return [build_claude_api_sft_prepared_sample(sample) for sample in samples]


def write_claude_api_sft_prepared_samples(
    samples: list[ClaudeApiSFTPreparedSample],
    path: str | Path,
) -> None:
    """Write prepared Claude API SFT samples to JSONL."""
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


def read_claude_api_sft_prepared_samples(
    path: str | Path,
) -> list[ClaudeApiSFTPreparedSample]:
    """Read prepared Claude API SFT samples from JSONL."""
    path = Path(path)
    records: list[ClaudeApiSFTPreparedSample] = []
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            records.append(ClaudeApiSFTPreparedSample.model_validate(json.loads(line)))
    return records
