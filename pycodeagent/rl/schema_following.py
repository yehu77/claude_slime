"""First-class schema-following sample models.

These models represent schema-following source data before it is transformed
into tokenized or packed training artifacts.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


SchemaFollowingSourceType = Literal["synthetic", "trajectory_derived", "hard_negative"]
SchemaFollowingSplit = Literal[
    "train",
    "eval_seen",
    "eval_unseen_name",
    "eval_unseen_description",
    "eval_unseen_schema",
    "eval_nested",
    "eval_distractor",
]
SchemaFollowingLossMaskPolicy = Literal["assistant_tool_call_only"]
SchemaFollowingMessageRole = Literal["system", "user", "assistant", "tool"]


def _require_non_empty_text(value: str, field_name: str) -> str:
    """Require a non-empty string while preserving the original value."""
    if not value or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def render_exposed_tool_call_text(
    call_id: str,
    name: str,
    arguments: dict[str, Any],
) -> str:
    """Render a schema-following target tool call using the canonical contract."""
    payload = {
        "arguments": arguments,
        "id": call_id,
        "name": name,
    }
    return f"<|tool|>\n{json.dumps(payload, sort_keys=True, ensure_ascii=False)}\n<|end|>\n"


class CanonicalToolIntent(BaseModel):
    """Canonical backend tool intent."""

    tool: str
    arguments: dict[str, Any]

    @field_validator("tool")
    @classmethod
    def _validate_tool(cls, value: str) -> str:
        return _require_non_empty_text(value, "tool")


class ExposedToolCallTarget(BaseModel):
    """Assistant target call under the currently exposed ToolView."""

    call_id: str
    name: str
    arguments: dict[str, Any]

    @field_validator("call_id", "name")
    @classmethod
    def _validate_non_empty_fields(cls, value: str, info: Any) -> str:
        return _require_non_empty_text(value, str(info.field_name))

    def to_payload(self) -> dict[str, Any]:
        """Return the deterministic JSON payload for this call."""
        return {
            "id": self.call_id,
            "name": self.name,
            "arguments": self.arguments,
        }

    def render_text(self) -> str:
        """Render the call using the canonical <|tool|> contract."""
        return render_exposed_tool_call_text(
            call_id=self.call_id,
            name=self.name,
            arguments=self.arguments,
        )


class SchemaFollowingMessage(BaseModel):
    """Message context preceding the target tool call."""

    role: SchemaFollowingMessageRole
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SchemaFollowingSample(BaseModel):
    """A first-class schema-following training/eval sample."""

    sample_id: str
    sample_type: Literal["schema_following"]
    source_type: SchemaFollowingSourceType
    split: SchemaFollowingSplit
    task_id: str
    tool_profile_id: str
    mutation_category: str
    messages: list[SchemaFollowingMessage] = Field(min_length=1)
    canonical_intent: CanonicalToolIntent
    target_tool_call: ExposedToolCallTarget
    target_text: str
    loss_mask_policy: SchemaFollowingLossMaskPolicy
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sample_id", "task_id", "tool_profile_id", "mutation_category")
    @classmethod
    def _validate_required_ids(cls, value: str, info: Any) -> str:
        return _require_non_empty_text(value, str(info.field_name))

    @field_validator("target_text")
    @classmethod
    def _validate_target_text_non_empty(cls, value: str) -> str:
        return _require_non_empty_text(value, "target_text")

    @model_validator(mode="after")
    def _validate_target_text_matches_target(self) -> SchemaFollowingSample:
        expected = self.target_tool_call.render_text()
        if self.target_text != expected:
            raise ValueError(
                "target_text does not match target_tool_call rendered with the "
                "canonical <|tool|> contract"
            )
        return self

