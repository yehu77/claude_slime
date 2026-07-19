"""Trajectory serialization for training data preparation.

Converts Trajectory objects into a structured text representation suitable
for tokenization and training.

Serialization format:
- Structured segment list preserving message order
- Each segment has: kind, text, trainable
- Deterministic output (stable ordering, no unstable dict iteration)

Segment kinds:
- "system": System prompt content (not trainable)
- "user": User task content (not trainable)
- "assistant": Assistant natural language content (not trainable)
- "assistant_tool_call": Assistant tool call JSON (trainable)
- "tool": Tool observation content (not trainable)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from pycodeagent.agent.prompt import build_tool_specs_section
from pycodeagent.tools.contracts import ToolPayloadKind

if TYPE_CHECKING:
    from pycodeagent.rl.schema_following import SchemaFollowingSample
    from pycodeagent.trajectory.schema import Trajectory


class SerializedSegment(BaseModel):
    """A single segment in the serialized trajectory.

    Attributes:
        kind: Segment type (system, user, assistant, assistant_tool_call, tool)
        text: The text content of this segment
        trainable: Whether this segment should be included in loss computation
        metadata: Optional metadata (e.g., tool_call_id, tool_name)
    """

    kind: str
    text: str
    trainable: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class SerializedTrajectory(BaseModel):
    """Serialized trajectory with segments and metadata.

    Attributes:
        task_id: Task identifier
        tool_profile_id: Tool profile used for this run
        segments: Ordered list of serialized segments
        text: Full concatenated text (all segments in order)
        reward: Final reward value
        status: Run status (completed, error, timeout, etc.)
        verifier_passed: Whether verification passed
        verifier_score: Verification score
        metadata: Additional run metadata
    """

    task_id: str
    tool_profile_id: str
    segments: list[SerializedSegment]
    text: str
    reward: float
    status: str
    verifier_passed: bool
    verifier_score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class SerializedSchemaFollowingSample(BaseModel):
    """Serialized schema-following sample with deterministic segments."""

    sample_id: str
    sample_type: str
    source_type: str
    split: str
    task_id: str
    tool_profile_id: str
    mutation_category: str
    loss_mask_policy: str
    segments: list[SerializedSegment]
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


def _serialize_tool_call(call: Any) -> str:
    """Serialize a tool call to deterministic JSON string.

    Ensures stable key ordering for reproducibility.

    Args:
        call: ToolCall object

    Returns:
        JSON string representation
    """
    data = {
        "id": call.id,
        "name": call.name,
    }
    if getattr(call, "input_text", None) is not None:
        data["payload_kind"] = ToolPayloadKind.INPUT_TEXT.value
        data["input_text"] = call.input_text
    else:
        data["arguments"] = call.arguments
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def _wrap_tagged_segment(tag: str, content: str) -> str:
    """Wrap segment content in a deterministic tagged block."""
    return f"<{tag}>\n{content}\n</{tag}>\n"


def _render_system_segment(content: str) -> str:
    return _wrap_tagged_segment("system", content)


def _render_user_segment(content: str) -> str:
    return _wrap_tagged_segment("user", content)


def _render_assistant_segment(content: str) -> str:
    return _wrap_tagged_segment("assistant", content)


def _render_tool_call_segment(call: Any) -> str:
    """Render a tool call using the same structural markers as the agent contract."""
    return f"<|tool|>\n{_serialize_tool_call(call)}\n<|end|>\n"


def _render_tool_call_payload(
    *,
    call_id: str,
    name: str,
    arguments: dict[str, Any] | None = None,
    input_text: str | None = None,
) -> str:
    """Render a native tool-call payload without requiring a trajectory ToolCall object."""
    payload: dict[str, Any] = {
        "id": call_id,
        "name": name,
    }
    if input_text is not None:
        payload["payload_kind"] = ToolPayloadKind.INPUT_TEXT.value
        payload["input_text"] = input_text
    else:
        payload["arguments"] = arguments or {}
    return f"<|tool|>\n{json.dumps(payload, sort_keys=True, ensure_ascii=False)}\n<|end|>\n"


def _render_tool_result_segment(content: str, tool_name: str | None) -> str:
    """Render a tool result block with an explicit tool name."""
    name = tool_name or "tool"
    return f"<tool_result name=\"{name}\">\n{content}\n</tool_result>\n"


def _render_tool_specs_user_segment(tool_specs: list[dict[str, Any]]) -> str:
    """Render visible tool specs as a non-trainable user-context block."""
    tool_section = build_tool_specs_section(tool_specs)
    content = (
        "Use only the exact tool names and argument shapes listed below.\n\n"
        f"{tool_section}"
    )
    return _render_user_segment(content)


def serialize_trajectory(trajectory: Trajectory) -> SerializedTrajectory:
    """Serialize a trajectory into structured segments.

    Converts the message history into an ordered list of segments,
    each with a kind, text, and trainability flag.

    Trainability policy:
    - system content: NOT trainable (masked out)
    - user content: NOT trainable (masked out)
    - assistant content: NOT trainable (masked out)
    - assistant tool calls: TRAINABLE
    - tool observations: NOT trainable

    Args:
        trajectory: The trajectory to serialize

    Returns:
        SerializedTrajectory with segments and full text
    """
    segments: list[SerializedSegment] = []

    for message in trajectory.messages:
        role = message.role.value

        if role == "system":
            segments.append(
                SerializedSegment(
                    kind="system",
                    text=_render_system_segment(message.content),
                    trainable=False,
                )
            )

        elif role == "user":
            segments.append(
                SerializedSegment(
                    kind="user",
                    text=_render_user_segment(message.content),
                    trainable=False,
                )
            )

        elif role == "assistant":
            # Assistant natural language content
            if message.content:
                segments.append(
                    SerializedSegment(
                        kind="assistant",
                        text=_render_assistant_segment(message.content),
                        trainable=False,
                    )
                )

            # Assistant tool calls
            for call in message.tool_calls:
                segments.append(
                    SerializedSegment(
                        kind="assistant_tool_call",
                        text=_render_tool_call_segment(call),
                        trainable=True,
                        metadata={
                            "tool_call_id": call.id,
                            "tool_name": call.name,
                            "canonical_name": call.canonical_name,
                        },
                    )
                )

        elif role == "tool":
            segments.append(
                SerializedSegment(
                    kind="tool",
                    text=_render_tool_result_segment(
                        message.content,
                        message.tool_name,
                    ),
                    trainable=False,
                    metadata={
                        "tool_call_id": message.tool_call_id,
                        "tool_name": message.tool_name,
                        "canonical_name": message.canonical_name,
                    },
                )
            )

    # Concatenate all segments into full text
    full_text = "".join(seg.text for seg in segments)

    # Extract verifier info
    verifier_passed = trajectory.verifier.passed if trajectory.verifier else False
    verifier_score = trajectory.verifier.score if trajectory.verifier else 0.0

    return SerializedTrajectory(
        task_id=trajectory.task_id,
        tool_profile_id=trajectory.tool_profile_id,
        segments=segments,
        text=full_text,
        reward=trajectory.reward,
        status=trajectory.status.value,
        verifier_passed=verifier_passed,
        verifier_score=verifier_score,
        metadata={
            "repo": trajectory.repo,
            "final_diff": trajectory.final_diff,
            "tool_versions": trajectory.tool_versions,
        },
    )

def serialize_schema_following_sample(
    sample: SchemaFollowingSample,
) -> SerializedSchemaFollowingSample:
    """Serialize a schema-following sample using the shared segment format."""
    segments: list[SerializedSegment] = []

    for message in sample.messages:
        if message.role == "system":
            segments.append(
                SerializedSegment(
                    kind="system",
                    text=_render_system_segment(message.content),
                    trainable=False,
                    metadata=dict(message.metadata),
                )
            )
        elif message.role == "user":
            segments.append(
                SerializedSegment(
                    kind="user",
                    text=_render_user_segment(message.content),
                    trainable=False,
                    metadata=dict(message.metadata),
                )
            )
        elif message.role == "assistant":
            segments.append(
                SerializedSegment(
                    kind="assistant",
                    text=_render_assistant_segment(message.content),
                    trainable=False,
                    metadata=dict(message.metadata),
                )
            )
        elif message.role == "tool":
            segments.append(
                SerializedSegment(
                    kind="tool",
                    text=_render_tool_result_segment(
                        message.content,
                        message.metadata.get("tool_name"),
                    ),
                    trainable=False,
                    metadata=dict(message.metadata),
                )
            )
        else:
            raise ValueError(f"Unsupported schema-following message role: {message.role}")

    segments.append(
        SerializedSegment(
            kind="assistant_tool_call",
            text=sample.target_text,
            trainable=True,
            metadata={
                "tool_call_id": sample.target_tool_call.call_id,
                "tool_name": sample.target_tool_call.name,
                "canonical_name": sample.canonical_intent.tool,
            },
        )
    )

    return SerializedSchemaFollowingSample(
        sample_id=sample.sample_id,
        sample_type=sample.sample_type,
        source_type=sample.source_type,
        split=sample.split,
        task_id=sample.task_id,
        tool_profile_id=sample.tool_profile_id,
        mutation_category=sample.mutation_category,
        loss_mask_policy=sample.loss_mask_policy,
        segments=segments,
        text="".join(segment.text for segment in segments),
        metadata={
            **sample.metadata,
            "canonical_intent": sample.canonical_intent.model_dump(mode="json"),
            "target_tool_call": sample.target_tool_call.to_payload(),
        },
    )
