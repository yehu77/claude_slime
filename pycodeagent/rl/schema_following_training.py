"""Prepared training artifacts for schema-following datasets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.rl.loss_mask import build_loss_mask
from pycodeagent.rl.schema_following import SchemaFollowingSample
from pycodeagent.rl.schema_following_dataset import read_schema_following_jsonl
from pycodeagent.rl.serializer import serialize_schema_following_sample


class SchemaFollowingPreparedSample(BaseModel):
    """Schema-following sample after serialization and mask construction."""

    sample_id: str
    sample_type: str
    source_type: str
    split: str
    task_id: str
    tool_profile_id: str
    mutation_category: str
    loss_mask_policy: str
    text: str
    segments: list[dict[str, Any]]
    character_mask: list[int]
    spans: list[dict[str, Any]]
    trainable_char_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


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
        loss_mask_policy=serialized.loss_mask_policy,
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


def read_schema_following_prepared_samples(
    path: str | Path,
) -> list[SchemaFollowingPreparedSample]:
    """Read prepared schema-following samples from JSONL."""
    path = Path(path)
    records: list[SchemaFollowingPreparedSample] = []
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            records.append(SchemaFollowingPreparedSample.model_validate(json.loads(line)))
    return records
