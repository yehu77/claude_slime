"""Auxiliary conservative SFT samples derived from Claude API traces."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from pycodeagent.auxiliary.claude_api.trace_extract import (
    ClaudeExtractedBlock,
    ClaudeExtractedRequestSample,
    ClaudeExtractedSession,
)


ClaudeApiSFTMessageRole = Literal["system", "user", "assistant", "tool"]
ClaudeApiSFTTargetBlockType = Literal["text", "tool_use"]
ClaudeApiSFTLossMaskPolicy = Literal["assistant_selected_blocks_only"]


class ClaudeApiSFTMessage(BaseModel):
    """One non-trainable context message for Claude API SFT."""

    role: ClaudeApiSFTMessageRole
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClaudeApiSFTToolCallTarget(BaseModel):
    """One assistant tool call target rendered under the native trace schema."""

    call_id: str
    name: str
    arguments: dict[str, Any]


class ClaudeApiSFTTargetBlock(BaseModel):
    """One trainable assistant target block."""

    block_type: ClaudeApiSFTTargetBlockType
    text: str | None = None
    tool_call: ClaudeApiSFTToolCallTarget | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_shape(self) -> "ClaudeApiSFTTargetBlock":
        if self.block_type == "text":
            if not isinstance(self.text, str) or not self.text:
                raise ValueError("text target block requires non-empty text")
            if self.tool_call is not None:
                raise ValueError("text target block must not include tool_call")
            return self
        if self.tool_call is None:
            raise ValueError("tool_use target block requires tool_call")
        if self.text is not None:
            raise ValueError("tool_use target block must not include text")
        return self


class ClaudeApiSFTSample(BaseModel):
    """One conservative SFT sample derived from a Claude API request."""

    sample_id: str
    sample_type: Literal["claude_api_sft"]
    source_type: Literal["claude_api_trace"]
    task_id: str
    tool_profile_id: str
    messages: list[ClaudeApiSFTMessage] = Field(min_length=1)
    tool_specs: list[dict[str, Any]] = Field(default_factory=list)
    target_blocks: list[ClaudeApiSFTTargetBlock] = Field(min_length=1)
    loss_mask_policy: ClaudeApiSFTLossMaskPolicy
    metadata: dict[str, Any] = Field(default_factory=dict)


def _render_content_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
            parts.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
        return "\n".join(part for part in parts if part)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _build_system_messages(sample: ClaudeExtractedRequestSample) -> list[ClaudeApiSFTMessage]:
    messages: list[ClaudeApiSFTMessage] = []
    for index, item in enumerate(sample.request_system):
        messages.append(
            ClaudeApiSFTMessage(
                role="system",
                content=_render_content_value(item),
                metadata={"source": "request_system", "index": index, "raw": item},
            )
        )
    return messages


def _build_request_messages(sample: ClaudeExtractedRequestSample) -> list[ClaudeApiSFTMessage]:
    messages: list[ClaudeApiSFTMessage] = []
    for index, item in enumerate(sample.request_messages):
        if not isinstance(item, dict):
            role: ClaudeApiSFTMessageRole = "user"
            content = _render_content_value(item)
            raw = item
        else:
            raw_role = item.get("role")
            role = raw_role if raw_role in {"system", "user", "assistant", "tool"} else "user"
            content = _render_content_value(item.get("content"))
            raw = item
        messages.append(
            ClaudeApiSFTMessage(
                role=role,
                content=content,
                metadata={"source": "request_messages", "index": index, "raw": raw},
            )
        )
    return messages


def _tool_call_from_block(block: ClaudeExtractedBlock) -> ClaudeApiSFTToolCallTarget | None:
    start_payload = block.metadata.get("start_payload")
    if not isinstance(start_payload, dict):
        return None
    content_block = start_payload.get("content_block")
    if not isinstance(content_block, dict):
        return None
    call_id = content_block.get("id")
    name = content_block.get("name")
    arguments = content_block.get("input", content_block.get("arguments"))
    if not isinstance(call_id, str) or not call_id:
        return None
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(arguments, dict):
        return None
    return ClaudeApiSFTToolCallTarget(
        call_id=call_id,
        name=name,
        arguments=arguments,
    )


def build_claude_api_sft_sample(
    extracted: ClaudeExtractedRequestSample,
    *,
    source_trace_path: str | None = None,
) -> ClaudeApiSFTSample | None:
    """Build one conservative SFT sample from one extracted Claude request."""
    if extracted.error is not None:
        return None

    context_messages = _build_system_messages(extracted) + _build_request_messages(extracted)

    target_blocks: list[ClaudeApiSFTTargetBlock] = []
    dropped_tool_use_blocks = 0
    for block in extracted.response_blocks:
        if block.block_type == "text":
            text = "".join(fragment for fragment in block.text_fragments if fragment)
            if not text:
                continue
            target_blocks.append(
                ClaudeApiSFTTargetBlock(
                    block_type="text",
                    text=text,
                    metadata={"index": block.index},
                )
            )
            continue
        if block.block_type == "tool_use":
            tool_call = _tool_call_from_block(block)
            if tool_call is None:
                dropped_tool_use_blocks += 1
                continue
            target_blocks.append(
                ClaudeApiSFTTargetBlock(
                    block_type="tool_use",
                    tool_call=tool_call,
                    metadata={"index": block.index},
                )
            )

    if not target_blocks:
        return None

    return ClaudeApiSFTSample(
        sample_id=extracted.sample_id,
        sample_type="claude_api_sft",
        source_type="claude_api_trace",
        task_id=extracted.request_id,
        tool_profile_id="claude_api_trace_native",
        messages=context_messages,
        tool_specs=[
            dict(tool_spec)
            for tool_spec in extracted.request_tools
            if isinstance(tool_spec, dict)
        ],
        target_blocks=target_blocks,
        loss_mask_policy="assistant_selected_blocks_only",
        metadata={
            "session_id": extracted.session_id,
            "request_id": extracted.request_id,
            "model": extracted.model,
            "stop_reason": extracted.stop_reason,
            "usage": extracted.usage,
            "request_tools": extracted.request_tools,
            "request_metadata": extracted.request_metadata,
            "response_status_code": extracted.metadata.get("response_status_code"),
            "dropped_tool_use_blocks": dropped_tool_use_blocks,
            "source_trace_path": source_trace_path
            if source_trace_path is not None
            else str(extracted.metadata.get("source_trace_path", "")),
            "source_session_id": extracted.session_id,
            "source_request_id": extracted.request_id,
        },
    )


def build_claude_api_sft_samples(
    extracted_session: ClaudeExtractedSession,
    *,
    source_trace_path: str | None = None,
) -> list[ClaudeApiSFTSample]:
    """Build SFT samples for one extracted Claude session."""
    samples: list[ClaudeApiSFTSample] = []
    for extracted in extracted_session.samples:
        sample = build_claude_api_sft_sample(
            extracted,
            source_trace_path=source_trace_path,
        )
        if sample is not None:
            samples.append(sample)
    return samples
