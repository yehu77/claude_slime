"""Prompt construction for runtime execution."""

from __future__ import annotations

import json
from typing import Any

from pycodeagent.agent.turn_state import CarriedForwardState, CompactionArtifact
from pycodeagent.tools.contracts import (
    ToolContractKind,
    tool_spec_input_format,
    tool_spec_input_schema,
    tool_spec_kind,
)
from pycodeagent.trajectory.schema import Message


NATIVE_TOOL_CALLING_SYSTEM_PROMPT = """You are a coding agent working inside a repository workspace.

The available tools are provided through the runtime's native tool-calling interface.
Use only the exact tool names and argument shapes from those provided tools.

Operating rules:
1. When you need to inspect files, edit the workspace, run validation, or finish the task, call the appropriate native tool directly.
2. Do not emit literal <|tool|>, <|end|>, <tool_call>, or <tool_result> tags in assistant text.
3. If a tool call is rejected or malformed, issue a corrected native tool call instead of stopping.
4. If a validation or test-running action fails, inspect the returned output, revise the workspace, and rerun validation before signaling completion.
5. Do not claim success or completion unless the relevant tool result has already been returned by the environment.
6. If a task requires validation evidence, do not call finish until a successful validation result has already been returned.
7. If you include normal assistant text, use it only to explain the next concrete action.
"""

COMPACTION_SYSTEM_PROMPT = """You are compacting runtime conversation history for a follow-up coding-agent turn.

Return only JSON matching the requested schema.
Do not call tools.
Do not explain the schema.
Write a compact but faithful summary of the compacted history span.
Preserve unresolved issues, validation state, and important tool outcomes needed for follow-up turns.
Put all span metadata inside `compacted_span`, not at the top level.
Set `compacted_span.replacement_summary_kind` to exactly `model_backed_compaction`.
Copy the provided pinned message indices exactly into `compacted_span.pinned_message_indices`.
"""


def build_system_message(
) -> dict[str, Any]:
    """Build the system message for the conversation."""
    return {"role": "system", "content": NATIVE_TOOL_CALLING_SYSTEM_PROMPT}


def build_compaction_system_message() -> dict[str, Any]:
    """Build the system message for model-backed compaction."""
    return {"role": "system", "content": COMPACTION_SYSTEM_PROMPT}


def build_user_task_message(task_prompt: str) -> dict[str, Any]:
    """Build the user message containing the task description.

    Args:
        task_prompt: The task description from CodingTask.prompt.

    Returns:
        A message dict with role='user' and the task content.
    """
    return {"role": "user", "content": task_prompt}


def build_tool_specs_section(tool_specs: list[dict[str, Any]]) -> str:
    """Build a text representation of available tools.

    This is appended to the prompt in text mode so the model knows what
    tools are available and their schemas.

    Args:
        tool_specs: Output from ToolProfile.get_exposed_specs().

    Returns:
        A formatted string describing available tools.
    """
    lines = ["<tools>"]
    for spec in tool_specs:
        name = spec.get("name", "unknown")
        desc = spec.get("description", "")
        lines.append(f"  {name}: {desc}")
        if tool_spec_kind(spec) == ToolContractKind.FREEFORM:
            input_format = tool_spec_input_format(spec) or {}
            format_type = input_format.get("type", "freeform")
            syntax = input_format.get("syntax")
            syntax_suffix = f", syntax={syntax}" if syntax else ""
            lines.append(f"    - input: {format_type}{syntax_suffix}")
            continue

        schema = tool_spec_input_schema(spec) or {}
        if schema.get("properties"):
            props = schema["properties"]
            required = set(schema.get("required", []))
            for prop_name, prop_spec in props.items():
                prop_type = prop_spec.get("type", "any")
                prop_desc = prop_spec.get("description", "")
                req_marker = " (required)" if prop_name in required else ""
                lines.append(f"    - {prop_name}: {prop_type}{req_marker} - {prop_desc}")
    lines.append("</tools>")
    return "\n".join(lines)


def build_initial_messages(
    task_prompt: str,
    tool_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the initial message list for a new task.

    Args:
        task_prompt: The task description.
        tool_specs: Available tool definitions.

    Returns:
        A list of message dicts: [system, user_with_tools_or_native_task]
    """
    return [
        build_system_message(),
        {"role": "user", "content": task_prompt},
    ]


def build_compaction_messages(
    *,
    compacted_messages: list[Message],
    pinned_messages: list[Message],
    compaction_artifact: CompactionArtifact,
    carried_forward_state: CarriedForwardState | None,
) -> list[dict[str, Any]]:
    """Build structured compaction prompt messages for model-backed compaction."""

    payload = {
        "task": "compact_runtime_history",
        "turn_index": compaction_artifact.turn_index,
        "compaction_reason": compaction_artifact.reason,
        "compacted_message_indices": list(compaction_artifact.compacted_message_indices),
        "retained_message_indices": list(compaction_artifact.retained_message_indices),
        "pinned_message_indices": list(compaction_artifact.pinned_message_indices),
        "candidate_turn_ranges": [
            turn_range.model_dump(mode="json")
            for turn_range in compaction_artifact.candidate_turn_ranges
        ],
        "existing_carried_forward_state": (
            carried_forward_state.model_dump(mode="json")
            if carried_forward_state is not None
            else None
        ),
        "pinned_context_messages": [
            {
                "role": message.role.value,
                "content": message.content,
                "tool_name": message.tool_name,
                "tool_call_id": message.tool_call_id,
                "canonical_name": message.canonical_name,
                "tool_calls": [
                    tool_call.model_dump(mode="json") for tool_call in message.tool_calls
                ],
                "metadata": dict(message.metadata),
            }
            for message in pinned_messages
        ],
        "messages_to_compact": [
            {
                "role": message.role.value,
                "content": message.content,
                "tool_name": message.tool_name,
                "tool_call_id": message.tool_call_id,
                "canonical_name": message.canonical_name,
                "tool_calls": [
                    tool_call.model_dump(mode="json") for tool_call in message.tool_calls
                ],
                "metadata": dict(message.metadata),
            }
            for message in compacted_messages
        ],
        "required_output_contract": {
            "summary_text": "string",
            "carried_forward_state": "object",
            "compacted_span": {
                "source_message_indices": "array[int]",
                "source_turn_indices": "array[int]",
                "pinned_message_indices": "array[int]",
                "replacement_summary_kind": "string",
            },
        },
        "important_output_rules": [
            "Do not put pinned_message_indices at the top level.",
            "All span metadata must be nested inside compacted_span.",
            "compacted_span.replacement_summary_kind must be model_backed_compaction.",
        ],
    }
    return [
        build_compaction_system_message(),
        {
            "role": "user",
            "content": (
                "Compact the following runtime history span into a compact summary "
                "and structured carried-forward state.\n"
                f"{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}"
            ),
        },
    ]




def build_parse_repair_message(parse_errors: list[str]) -> str:
    return build_parse_repair_message_for_transport(parse_errors)


def build_parse_repair_message_for_transport(
    parse_errors: list[str],
) -> str:
    detail = "; ".join(parse_errors) if parse_errors else "previous response was malformed"
    return (
        "Your previous response contained an invalid or malformed native tool call.\n"
        f"Parse issue: {detail}\n"
        "Issue a corrected native tool call directly instead of stopping.\n"
        "Do not emit literal <|tool|>, <|end|>, <tool_call>, or <tool_result> tags in assistant text.\n"
        "If you include assistant text, keep it brief and explain only the next concrete action."
    )


def build_validation_repair_message(
    detail: str,
    *,
    expected_next_step: str | None,
) -> str:
    next_step = expected_next_step or "validate"
    return (
        "Completion is blocked until validation evidence is available.\n"
        f"Reason: {detail}\n"
        f"Expected next step: {next_step}\n"
        "Do not repeat finish. Run the required validation or revalidation tool call next."
    )


def build_correction_repair_message(
    detail: str,
    *,
    expected_next_step: str | None,
) -> str:
    next_step = expected_next_step or "continue"
    return (
        "Completion is blocked by a recoverable runtime issue.\n"
        f"Reason: {detail}\n"
        f"Expected next step: {next_step}\n"
        "Do not repeat finish. Correct the issue or make another concrete tool call next."
    )


def build_completion_repair_message(
    detail: str,
    *,
    expected_next_step: str | None,
    block_reason: str | None = None,
) -> str:
    if block_reason in {
        "missing_validation_evidence",
        "post_mutation_validation_pending",
    }:
        return build_validation_repair_message(
            detail,
            expected_next_step=expected_next_step,
        )
    return build_correction_repair_message(
        detail,
        expected_next_step=expected_next_step,
    )
