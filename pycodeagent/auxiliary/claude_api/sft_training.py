"""Prepared training artifacts for auxiliary Claude API SFT samples."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycodeagent.auxiliary.claude_api.sft import ClaudeApiSFTSample
from pycodeagent.rl.loss_mask import build_loss_mask
from pycodeagent.auxiliary.claude_api.serializer import serialize_claude_api_sft_sample
from pycodeagent.rl.prepared_sample import (
    PreparedSample,
    read_prepared_samples,
    write_prepared_samples,
)


# Compatibility name for auxiliary callers predating the unified contract.
ClaudeApiSFTPreparedSample = PreparedSample


def build_claude_api_sft_prepared_sample(
    sample: ClaudeApiSFTSample,
    *,
    extra_metadata: dict[str, Any] | None = None,
) -> ClaudeApiSFTPreparedSample:
    """Build a prepared Claude API SFT sample from the raw SFT sample."""
    serialized = serialize_claude_api_sft_sample(sample)
    loss_mask = build_loss_mask(serialized)
    metadata = dict(serialized.metadata)
    metadata["source_loss_mask_policy"] = serialized.loss_mask_policy
    if extra_metadata:
        metadata.update(extra_metadata)

    return ClaudeApiSFTPreparedSample(
        sample_id=serialized.sample_id,
        sample_type=serialized.sample_type,
        source_type=serialized.source_type,
        split="train",
        task_id=serialized.task_id,
        tool_profile_id=serialized.tool_profile_id,
        mutation_category=metadata.get("transformation_mode"),
        loss_mask_policy="assistant_tool_call_only",
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
    write_prepared_samples(samples, path)


def read_claude_api_sft_prepared_samples(
    path: str | Path,
) -> list[ClaudeApiSFTPreparedSample]:
    """Read prepared Claude API SFT samples from JSONL."""
    return read_prepared_samples(path)
