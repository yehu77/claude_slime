"""Versioned prepared-text contract shared by every training-data source."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PREPARED_SAMPLE_SCHEMA_VERSION = 1
ASSISTANT_TOOL_CALL_ONLY = "assistant_tool_call_only"


class PreparedSample(BaseModel):
    """Validated source-neutral input to tokenization and packing."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = PREPARED_SAMPLE_SCHEMA_VERSION
    sample_id: str
    sample_type: str
    source_type: str
    split: str = "train"
    task_id: str
    tool_profile_id: str
    mutation_category: str | None = None
    loss_mask_policy: Literal["assistant_tool_call_only"] = ASSISTANT_TOOL_CALL_ONLY
    text: str
    segments: list[dict[str, Any]]
    character_mask: list[int]
    spans: list[dict[str, Any]]
    trainable_char_count: int
    reward: float | None = None
    status: str | None = None
    verifier_passed: bool | None = None
    verifier_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_contract(self) -> "PreparedSample":
        for field_name in (
            "sample_id",
            "sample_type",
            "source_type",
            "split",
            "task_id",
            "tool_profile_id",
        ):
            value = getattr(self, field_name)
            if not value or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")

        if len(self.text) != len(self.character_mask):
            raise ValueError(
                "PreparedSample character_mask length must match serialized text"
            )
        if any(value not in {0, 1} for value in self.character_mask):
            raise ValueError("PreparedSample character_mask must contain only 0 or 1")
        if sum(self.character_mask) != self.trainable_char_count:
            raise ValueError(
                "PreparedSample trainable_char_count must equal character_mask sum"
            )
        if len(self.segments) != len(self.spans):
            raise ValueError("PreparedSample segments and spans must have equal length")

        reconstructed: list[str] = []
        expected_mask: list[int] = []
        offset = 0
        for index, (segment, span) in enumerate(
            zip(self.segments, self.spans, strict=True)
        ):
            kind = segment.get("kind")
            segment_text = segment.get("text")
            trainable = segment.get("trainable")
            if not isinstance(kind, str) or not kind:
                raise ValueError(f"PreparedSample segment {index} has invalid kind")
            if not isinstance(segment_text, str):
                raise ValueError(f"PreparedSample segment {index} has invalid text")
            if not isinstance(trainable, bool):
                raise ValueError(
                    f"PreparedSample segment {index} has invalid trainable flag"
                )
            if trainable and kind != "assistant_tool_call":
                raise ValueError(
                    "PreparedSample only permits assistant_tool_call segments "
                    "to be trainable"
                )

            end = offset + len(segment_text)
            if (
                span.get("start") != offset
                or span.get("end") != end
                or span.get("trainable") != trainable
            ):
                raise ValueError(
                    f"PreparedSample span {index} does not match its segment"
                )
            reconstructed.append(segment_text)
            expected_mask.extend([1 if trainable else 0] * len(segment_text))
            offset = end

        if "".join(reconstructed) != self.text:
            raise ValueError(
                "PreparedSample segments must reconstruct serialized text"
            )
        if expected_mask != self.character_mask:
            raise ValueError(
                "PreparedSample character_mask must match segment trainability"
            )

        outcome_fields = (
            self.reward,
            self.status,
            self.verifier_passed,
            self.verifier_score,
        )
        if any(value is not None for value in outcome_fields) and any(
            value is None for value in outcome_fields
        ):
            raise ValueError(
                "PreparedSample run outcome fields must be all present or all absent"
            )
        return self


def write_prepared_samples(
    samples: list[PreparedSample],
    path: str | Path,
) -> None:
    """Write validated prepared samples as deterministic JSONL."""
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


def read_prepared_samples(path: str | Path) -> list[PreparedSample]:
    """Read prepared JSONL and fail loudly on unknown or malformed contracts."""
    path = Path(path)
    samples: list[PreparedSample] = []
    with open(path, encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                samples.append(PreparedSample.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid PreparedSample on line {line_no} of {path}: {exc}"
                ) from exc
    return samples
