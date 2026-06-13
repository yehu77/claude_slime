"""Formal runtime session and turn context contracts."""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.agent.turn_state import (
    ContextSelection,
    RuntimeSessionState,
    RuntimeTurnState,
)
from pycodeagent.env.task import CodingTask
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.spec import ToolProfile
from pycodeagent.trajectory.schema import Message


class RuntimeSessionContext(BaseModel):
    """Stable runtime facts shared across turns in one local run."""

    task_id: str
    workspace_root: str
    tool_profile_id: str
    tool_specs: list[dict[str, Any]] = Field(default_factory=list)
    tool_names: list[str] = Field(default_factory=list)
    tool_order: list[str] = Field(default_factory=list)
    canonical_tool_order: list[str] = Field(default_factory=list)
    provider_provenance: dict[str, Any] = Field(default_factory=dict)
    runtime_capabilities: dict[str, Any] = Field(default_factory=dict)
    context_policy_mode: str
    context_max_messages: int | None = None
    context_max_tokens: int | None = None
    tool_token_reserve: int = 0
    response_token_reserve: int = 0
    requires_validation_evidence: bool = False
    system_prompt_text: str = ""
    system_prompt_fingerprint: str = ""
    user_prompt_text: str = ""
    session_state: RuntimeSessionState


class RuntimeTurnContext(BaseModel):
    """Turn-scoped runtime facts needed to build and interpret one request."""

    turn_index: int
    session: RuntimeSessionContext
    message_count_before_turn: int
    selected_messages: list[Message] = Field(default_factory=list)
    request_messages: list[dict[str, Any]] = Field(default_factory=list)
    context_selection: ContextSelection
    turn_state: RuntimeTurnState
    validation_phase_before_turn: str | None = None
    active_validation_issue_kind_before_turn: str | None = None
    completion_evidence_status_before_turn: str | None = None


def build_runtime_session_context(
    task: CodingTask,
    ctx: ToolContext,
    profile: ToolProfile,
    session_state: RuntimeSessionState,
    *,
    tool_specs: list[dict[str, Any]],
    provider_provenance: dict[str, Any],
    runtime_capabilities: dict[str, Any],
    context_policy_mode: str,
    context_max_messages: int | None,
    context_max_tokens: int | None,
    tool_token_reserve: int,
    response_token_reserve: int,
    system_prompt_text: str,
    user_prompt_text: str,
) -> RuntimeSessionContext:
    """Construct the formal per-run runtime context."""

    return RuntimeSessionContext(
        task_id=task.task_id,
        workspace_root=str(ctx.workspace_root),
        tool_profile_id=profile.profile_id,
        tool_specs=list(tool_specs),
        tool_names=[spec.get("name", "") for spec in tool_specs],
        tool_order=[tool.exposed_name for tool in profile.tools],
        canonical_tool_order=[tool.canonical_name for tool in profile.tools],
        provider_provenance=dict(provider_provenance),
        runtime_capabilities=dict(runtime_capabilities),
        context_policy_mode=context_policy_mode,
        context_max_messages=context_max_messages,
        context_max_tokens=context_max_tokens,
        tool_token_reserve=tool_token_reserve,
        response_token_reserve=response_token_reserve,
        requires_validation_evidence=task.requires_runtime_validation_evidence(),
        system_prompt_text=system_prompt_text,
        system_prompt_fingerprint=_fingerprint_text(system_prompt_text),
        user_prompt_text=user_prompt_text,
        session_state=session_state,
    )


def build_runtime_turn_context(
    session_context: RuntimeSessionContext,
    trajectory_messages: list[Message],
    *,
    turn_index: int,
    pending_issue_kind_before_turn: str | None,
    active_validation_issue_kind_before_turn: str | None,
    active_validation_issue_id_before_turn: str | None,
    completion_evidence_status_before_turn: str | None,
    validation_phase_before_turn: str | None,
    expected_next_step_before_turn: str | None,
    completion_gate_status_before_turn: str | None,
) -> RuntimeTurnContext:
    """Construct the formal per-turn runtime context."""

    session_state = session_context.session_state
    turn_state = RuntimeTurnState(
        turn_index=turn_index,
        message_count_before_turn=len(trajectory_messages),
        context_selection=ContextSelection(
            policy_mode=session_context.context_policy_mode,
            max_messages=session_context.context_max_messages,
            context_max_tokens=session_context.context_max_tokens,
        ),
        pending_issue_id_before_turn=(
            session_state.active_pending_issue.issue_id
            if session_state.active_pending_issue is not None
            else None
        ),
        pending_issue_kind_before_turn=pending_issue_kind_before_turn,
        active_validation_issue_kind_before_turn=active_validation_issue_kind_before_turn,
        active_validation_issue_id_before_turn=active_validation_issue_id_before_turn,
        completion_evidence_status_before_turn=completion_evidence_status_before_turn,
        validation_phase_before_turn=validation_phase_before_turn,
        expected_next_step_before_turn=expected_next_step_before_turn,
        completion_gate_status_before_turn=completion_gate_status_before_turn,
        summary_slot_status_before_turn=(
            session_state.summary_slot.status
            if session_state.summary_slot is not None
            else None
        ),
        carried_forward_state_present_before_turn=(
            session_state.carried_forward_state is not None
        ),
    )
    return RuntimeTurnContext(
        turn_index=turn_index,
        session=session_context,
        message_count_before_turn=len(trajectory_messages),
        context_selection=turn_state.context_selection,
        turn_state=turn_state,
        validation_phase_before_turn=validation_phase_before_turn,
        active_validation_issue_kind_before_turn=active_validation_issue_kind_before_turn,
        completion_evidence_status_before_turn=completion_evidence_status_before_turn,
    )


def _fingerprint_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
