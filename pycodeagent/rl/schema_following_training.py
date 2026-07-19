"""Prepared training artifacts for schema-following datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycodeagent.rl.loss_mask import build_loss_mask
from pycodeagent.rl.prepared_sample import (
    PreparedSample,
    read_prepared_samples,
    write_prepared_samples,
)
from pycodeagent.rl.schema_following import SchemaFollowingSample
from pycodeagent.rl.schema_following_dataset import read_schema_following_jsonl
from pycodeagent.rl.serializer import serialize_schema_following_sample


# Compatibility name for callers that predate the unified RC-041 contract.
SchemaFollowingPreparedSample = PreparedSample


def load_schema_following_split(
    dataset_dir: str | Path,
    *,
    split: str = "train",
) -> list[SchemaFollowingSample]:
    """Load one schema-following split file from a dataset directory."""
    dataset_dir = Path(dataset_dir)
    return read_schema_following_jsonl(dataset_dir / f"{split}.jsonl")


def build_schema_following_prepared_sample(
    sample: SchemaFollowingSample,
    *,
    extra_metadata: dict[str, Any] | None = None,
) -> SchemaFollowingPreparedSample:
    """Build a prepared schema-following sample from the raw dataset sample."""
    serialized = serialize_schema_following_sample(sample)
    loss_mask = build_loss_mask(serialized)
    metadata = dict(serialized.metadata)
    if extra_metadata:
        metadata.update(extra_metadata)

    return SchemaFollowingPreparedSample(
        sample_id=serialized.sample_id,
        sample_type=serialized.sample_type,
        source_type=serialized.source_type,
        split=serialized.split,
        task_id=serialized.task_id,
        tool_profile_id=serialized.tool_profile_id,
        mutation_category=serialized.mutation_category,
        loss_mask_policy="assistant_tool_call_only",
        text=serialized.text,
        segments=[segment.model_dump(mode="json") for segment in serialized.segments],
        character_mask=loss_mask.character_mask,
        spans=[span.model_dump(mode="json") for span in loss_mask.spans],
        trainable_char_count=loss_mask.trainable_char_count,
        metadata=metadata,
    )


def build_schema_following_prepared_samples(
    samples: list[SchemaFollowingSample],
) -> list[SchemaFollowingPreparedSample]:
    """Build prepared samples for one split in deterministic order."""
    return [build_schema_following_prepared_sample(sample) for sample in samples]


def write_schema_following_prepared_samples(
    samples: list[SchemaFollowingPreparedSample],
    path: str | Path,
) -> None:
    """Write prepared schema-following samples to JSONL."""
    write_prepared_samples(samples, path)


def read_schema_following_prepared_samples(
    path: str | Path,
) -> list[SchemaFollowingPreparedSample]:
    """Read prepared schema-following samples from JSONL."""
    return read_prepared_samples(path)
