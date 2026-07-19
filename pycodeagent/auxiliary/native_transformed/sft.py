"""Build auxiliary transformed SFT samples from Claude tool-use traces."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.auxiliary.claude_api.sft import (
    ClaudeApiSFTMessage,
    ClaudeApiSFTSample,
    ClaudeApiSFTTargetBlock,
    ClaudeApiSFTToolCallTarget,
)
from pycodeagent.tools.spec import ToolProfile
from pycodeagent.auxiliary.claude_api.trace import ClaudeApiSession
from pycodeagent.auxiliary.claude_api.trace_extract import (
    ClaudeExtractedBlock,
    ClaudeExtractedRequestSample,
)
from pycodeagent.traces.tool_catalog import AgentToolCatalog


class ToolUseRemapEntry(BaseModel):
    native_tool_name: str
    transformed_tool_name: str | None = None
    input_preserved: bool = True
    status: str
    reason: str | None = None
    tool_use_id: str | None = None


class ToolUseRemapReport(BaseModel):
    entries: list[ToolUseRemapEntry] = Field(default_factory=list)
    unmapped_tool_uses: int = 0
    dropped_tool_uses: int = 0


class TransformedNativeSFTBuildResult(BaseModel):
    sample: ClaudeApiSFTSample | None = None
    remap_report: ToolUseRemapReport
    audit: dict[str, Any] = Field(default_factory=dict)


def build_transformed_native_sft_sample(
    extracted: ClaudeExtractedRequestSample,
    *,
    source_catalog: AgentToolCatalog,
    base_profile: ToolProfile,
    target_profile: ToolProfile,
    session: ClaudeApiSession | None = None,
) -> TransformedNativeSFTBuildResult:
    """Build one transformed native SFT sample from one extracted request."""
    report = ToolUseRemapReport()
    if extracted.error is not None:
        return TransformedNativeSFTBuildResult(
            sample=None,
            remap_report=report,
            audit={"error": extracted.error},
        )

    native_name_to_transformed = {
        str(tool.metadata.get("native_name", tool.exposed_name)): tool.exposed_name
        for tool in target_profile.tools
    }
    context_messages = _build_system_messages(extracted) + _build_request_messages(extracted)
    target_blocks: list[ClaudeApiSFTTargetBlock] = []

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

        if block.block_type != "tool_use":
            continue

        raw_tool_call = _tool_call_from_block(block)
        if raw_tool_call is None:
            report.dropped_tool_uses += 1
            report.entries.append(
                ToolUseRemapEntry(
                    native_tool_name=_native_name_from_block(block),
                    transformed_tool_name=None,
                    status="dropped",
                    reason="invalid_tool_use_block",
                    tool_use_id=_tool_use_id_from_block(block),
                )
            )
            continue

        transformed_tool_name = native_name_to_transformed.get(raw_tool_call.name)
        if transformed_tool_name is None:
            report.unmapped_tool_uses += 1
            report.dropped_tool_uses += 1
            report.entries.append(
                ToolUseRemapEntry(
                    native_tool_name=raw_tool_call.name,
                    transformed_tool_name=None,
                    status="unmapped",
                    reason="missing_target_profile_mapping",
                    tool_use_id=raw_tool_call.call_id,
                )
            )
            continue

        target_blocks.append(
            ClaudeApiSFTTargetBlock(
                block_type="tool_use",
                tool_call=ClaudeApiSFTToolCallTarget(
                    call_id=raw_tool_call.call_id,
                    name=transformed_tool_name,
                    arguments=raw_tool_call.arguments,
                ),
                metadata={"index": block.index},
            )
        )
        report.entries.append(
            ToolUseRemapEntry(
                native_tool_name=raw_tool_call.name,
                transformed_tool_name=transformed_tool_name,
                input_preserved=True,
                status="mapped",
                tool_use_id=raw_tool_call.call_id,
            )
        )

    audit = _build_followup_tool_result_audit(
        session=session,
        request_id=extracted.request_id,
        tool_use_ids=[
            entry.tool_use_id
            for entry in report.entries
            if entry.status == "mapped" and entry.tool_use_id is not None
        ],
    )

    if not target_blocks:
        return TransformedNativeSFTBuildResult(
            sample=None,
            remap_report=report,
            audit=audit,
        )

    sample = ClaudeApiSFTSample(
        sample_id=f"{extracted.sample_id}::{target_profile.profile_id}",
        sample_type="claude_api_sft",
        source_type="claude_api_trace",
        task_id=extracted.request_id,
        tool_profile_id=target_profile.profile_id,
        messages=context_messages,
        tool_specs=target_profile.get_exposed_specs(),
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
            "source_trace_path": str(extracted.metadata.get("source_trace_path", "")),
            "source_session_id": extracted.session_id,
            "source_request_id": extracted.request_id,
            "source_catalog_id": source_catalog.catalog_id,
            "base_profile_id": base_profile.profile_id,
            "target_profile_id": target_profile.profile_id,
            "transformation_mode": target_profile.metadata.get("transformation_mode"),
            "tool_use_remap_report": report.model_dump(mode="json"),
            "followup_tool_result_audit": audit,
        },
    )
    return TransformedNativeSFTBuildResult(
        sample=sample,
        remap_report=report,
        audit=audit,
    )


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
            role = "user"
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


def _render_content_value(value: Any) -> str:
    import json

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


def _native_name_from_block(block: ClaudeExtractedBlock) -> str:
    start_payload = block.metadata.get("start_payload")
    if isinstance(start_payload, dict):
        content_block = start_payload.get("content_block")
        if isinstance(content_block, dict):
            name = content_block.get("name")
            if isinstance(name, str) and name:
                return name
    return "unknown_tool"


def _tool_use_id_from_block(block: ClaudeExtractedBlock) -> str | None:
    start_payload = block.metadata.get("start_payload")
    if isinstance(start_payload, dict):
        content_block = start_payload.get("content_block")
        if isinstance(content_block, dict):
            value = content_block.get("id")
            if isinstance(value, str) and value:
                return value
    return None


def _build_followup_tool_result_audit(
    *,
    session: ClaudeApiSession | None,
    request_id: str,
    tool_use_ids: list[str],
) -> dict[str, Any]:
    if session is None or not tool_use_ids:
        return {
            "matched_tool_result_count": 0,
            "matched_tool_result_request_ids": [],
            "matched_tool_use_ids": [],
        }

    tool_use_id_set = set(tool_use_ids)
    request_ids = [request.request_id for request in session.message_requests]
    try:
        request_index = request_ids.index(request_id)
    except ValueError:
        return {
            "matched_tool_result_count": 0,
            "matched_tool_result_request_ids": [],
            "matched_tool_use_ids": [],
        }

    matched_request_ids: list[str] = []
    matched_tool_use_ids: list[str] = []
    for request in session.message_requests[request_index + 1 :]:
        matched_in_request = False
        for message in request.request_body.get("messages", []):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                tool_use_id = block.get("tool_use_id")
                if isinstance(tool_use_id, str) and tool_use_id in tool_use_id_set:
                    matched_tool_use_ids.append(tool_use_id)
                    matched_in_request = True
        if matched_in_request:
            matched_request_ids.append(request.request_id)

    return {
        "matched_tool_result_count": len(matched_tool_use_ids),
        "matched_tool_result_request_ids": matched_request_ids,
        "matched_tool_use_ids": matched_tool_use_ids,
    }
