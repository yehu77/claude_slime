"""Serialization for auxiliary Claude API SFT samples."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.auxiliary.claude_api.sft import ClaudeApiSFTSample
from pycodeagent.rl.serializer import (
    SerializedSegment,
    _render_assistant_segment,
    _render_system_segment,
    _render_tool_call_payload,
    _render_tool_result_segment,
    _render_tool_specs_user_segment,
    _render_user_segment,
)


class SerializedClaudeApiSFTSample(BaseModel):
    """Serialized Claude API SFT sample with deterministic segments."""

    sample_id: str
    sample_type: str
    source_type: str
    task_id: str
    tool_profile_id: str
    loss_mask_policy: str
    segments: list[SerializedSegment]
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


def serialize_claude_api_sft_sample(
    sample: ClaudeApiSFTSample,
) -> SerializedClaudeApiSFTSample:
    """Serialize a Claude API SFT sample using shared segment kinds."""
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
            raise ValueError(f"Unsupported Claude API SFT message role: {message.role}")

    if sample.tool_specs:
        segments.append(
            SerializedSegment(
                kind="user",
                text=_render_tool_specs_user_segment(sample.tool_specs),
                trainable=False,
                metadata={"source": "tool_specs", "tool_count": len(sample.tool_specs)},
            )
        )

    for block in sample.target_blocks:
        if block.block_type == "text":
            segments.append(
                SerializedSegment(
                    kind="assistant",
                    text=_render_assistant_segment(block.text or ""),
                    trainable=False,
                    metadata=dict(block.metadata),
                )
            )
            continue
        tool_call = block.tool_call
        if tool_call is None:
            raise ValueError("tool_use target block missing tool_call")
        segments.append(
            SerializedSegment(
                kind="assistant_tool_call",
                text=_render_tool_call_payload(
                    call_id=tool_call.call_id,
                    name=tool_call.name,
                    arguments=tool_call.arguments,
                ),
                trainable=True,
                metadata={
                    **block.metadata,
                    "tool_call_id": tool_call.call_id,
                    "tool_name": tool_call.name,
                },
            )
        )

    return SerializedClaudeApiSFTSample(
        sample_id=sample.sample_id,
        sample_type=sample.sample_type,
        source_type=sample.source_type,
        task_id=sample.task_id,
        tool_profile_id=sample.tool_profile_id,
        loss_mask_policy=sample.loss_mask_policy,
        segments=segments,
        text="".join(segment.text for segment in segments),
        metadata=dict(sample.metadata),
    )
