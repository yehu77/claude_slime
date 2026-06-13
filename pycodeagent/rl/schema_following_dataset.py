"""JSONL helpers for schema-following datasets."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from pycodeagent.rl.schema_following import SchemaFollowingSample


class SchemaFollowingDatasetError(ValueError):
    """Raised when a schema-following dataset file is malformed."""


def write_schema_following_jsonl(
    samples: list[SchemaFollowingSample],
    path: str | Path,
) -> None:
    """Write schema-following samples to a deterministic JSONL file."""
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


def read_schema_following_jsonl(path: str | Path) -> list[SchemaFollowingSample]:
    """Read and validate schema-following samples from JSONL."""
    path = Path(path)
    samples: list[SchemaFollowingSample] = []
    with open(path, encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SchemaFollowingDatasetError(
                    f"Invalid JSON on line {line_no} of {path}: {exc}"
                ) from exc

            try:
                samples.append(SchemaFollowingSample.model_validate(data))
            except ValidationError as exc:
                raise SchemaFollowingDatasetError(
                    f"Invalid schema-following sample on line {line_no} of {path}: {exc}"
                ) from exc
    return samples


def validate_schema_following_jsonl(path: str | Path) -> None:
    """Validate a schema-following JSONL file."""
    read_schema_following_jsonl(path)
