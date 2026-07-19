"""Context/compaction orchestration for runtime-owned request history.

This module keeps the request-time context selection and compaction planning
separate from history persistence. The shape is intentionally simpler than
codex-rs' full context/history subsystem, but it follows the same boundary:
history retention is one concern, and request-time context planning is another.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.agent.turn_state import (
    CarriedForwardState,
    CompactionArtifact,
    CompactionPlanningMetadata,
    ContextPolicyMode,
    ContextSelection,
    ContextSelectionResult,
    RuntimeSessionState,
    SummarySlot,
    TurnRangeSummary,
    estimate_message_tokens,
    estimate_messages_tokens,
)
from pycodeagent.trajectory.schema import Message
from pycodeagent.trajectory.schema import Role
from pycodeagent.trajectory.schema import ToolCall


COMPACTION_CONTRACT_VERSION = 1
CANONICAL_COMPACTION_OWNER = "pycodeagent.agent.compaction"
MODEL_BACKED_COMPACTION_BACKEND = "inline_model"
MODEL_BACKED_COMPACTION_FALLBACK_POLICY = "deterministic_compaction"
MODEL_BACKED_COMPACTION_FAILURE_KINDS = (
    "capability_unavailable",
    "provider_error",
    "structured_output_parse_error",
    "schema_validation_error",
    "compacted_span_mismatch",
)


class ContextSelectionPlan(BaseModel):
    """Formal request-time plan produced before building one model request."""

    turn_index: int
    policy_mode: str
    compaction_considered: bool = False
    compaction_considered_reason: str | None = None
    compaction_skip_reason: str | None = None
    trigger_message_overflow: bool = False
    trigger_token_overflow: bool = False
    request_history_item_count_before_snapshot: int
    selected_request_item_indices: list[int] = Field(default_factory=list)
    selected_message_count_after_selection: int = 0
    compaction_decision: str
    pinned_message_indices: list[int] = Field(default_factory=list)
    preserved_from_turn: int | None = None
    candidate_turn_indices: list[int] = Field(default_factory=list)
    compacted_turn_indices: list[int] = Field(default_factory=list)
    replacement_summary_planned: bool = False
    carried_forward_state_planned: bool = False
    context_selection: ContextSelection
    selected_messages: list[Message] = Field(default_factory=list)
    compaction_artifact: CompactionArtifact | None = None
    synthetic_summary_message: Message | None = None
    model_backed_requested: bool = False
    model_backed_used: bool = False
    compaction_backend_mode: str | None = None
    fallback_policy: str | None = None
    fallback_applied: bool = False
    fallback_reason: str | None = None
    compaction_backend_failure_kind: str | None = None


class ModelCompactedSpan(BaseModel):
    """Structured compacted-span metadata returned by the backend."""

    source_message_indices: list[int] = Field(default_factory=list)
    source_turn_indices: list[int] = Field(default_factory=list)
    pinned_message_indices: list[int] = Field(default_factory=list)
    replacement_summary_kind: str = "model_backed_compaction"


class ModelBackedCompactionOutput(BaseModel):
    """Structured output returned by the compaction backend."""

    summary_text: str
    carried_forward_state: CarriedForwardState
    compacted_span: ModelCompactedSpan


def normalize_model_backed_compaction_output_payload(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Normalize narrow provider drift before schema validation.

    This keeps the contract structured while absorbing common real-provider
    placement drift:
    - span metadata emitted at the top level instead of inside `compacted_span`
    - provider-chosen replacement summary kinds that should map back to the
      runtime-owned `model_backed_compaction` summary kind
    """

    if payload is None:
        return None

    normalized = dict(payload)
    span = normalized.get("compacted_span")
    if isinstance(span, dict):
        normalized_span = dict(span)
    else:
        normalized_span = {}

    for field_name in (
        "source_message_indices",
        "source_turn_indices",
        "pinned_message_indices",
        "replacement_summary_kind",
    ):
        top_level_value = normalized.get(field_name)
        span_value = normalized_span.get(field_name)
        if top_level_value is not None and span_value in (None, [], ""):
            normalized_span[field_name] = top_level_value

    replacement_summary_kind = normalized_span.get("replacement_summary_kind")
    if replacement_summary_kind not in (None, "", "model_backed_compaction"):
        normalized_span["replacement_summary_kind"] = "model_backed_compaction"

    normalized["compacted_span"] = normalized_span
    return normalized


def plan_request_context(
    request_messages: list[Message],
    *,
    policy_mode: ContextPolicyMode | str,
    max_messages: int | None,
    session_state,
    turn_index: int,
    context_max_tokens: int | None = None,
    tool_token_reserve: int = 0,
    response_token_reserve: int = 0,
) -> ContextSelectionPlan:
    """Plan request-time context selection independently from history mutation."""

    normalized_mode = (
        policy_mode.value
        if isinstance(policy_mode, ContextPolicyMode)
        else ContextPolicyMode(str(policy_mode)).value
    )
    effective_policy = (
        ContextPolicyMode.DETERMINISTIC_COMPACTION
        if normalized_mode == ContextPolicyMode.MODEL_BACKED_COMPACTION.value
        else policy_mode
    )
    selection_result = select_request_messages(
        request_messages,
        policy_mode=effective_policy,
        max_messages=max_messages,
        session_state=session_state,
        turn_index=turn_index,
        context_max_tokens=context_max_tokens,
        tool_token_reserve=tool_token_reserve,
        response_token_reserve=response_token_reserve,
    )
    selection_result.context_selection.policy_mode = normalized_mode
    planning = selection_result.planning_metadata
    return ContextSelectionPlan(
        turn_index=turn_index,
        policy_mode=normalized_mode,
        compaction_considered=planning.compaction_considered,
        compaction_considered_reason=planning.consideration_reason,
        compaction_skip_reason=planning.skip_reason,
        trigger_message_overflow=planning.trigger_message_overflow,
        trigger_token_overflow=planning.trigger_token_overflow,
        request_history_item_count_before_snapshot=len(request_messages),
        selected_request_item_indices=list(
            selection_result.context_selection.included_message_indices
        ),
        selected_message_count_after_selection=len(selection_result.selected_messages),
        compaction_decision=(
            "applied"
            if selection_result.context_selection.compaction_applied
            else "skipped"
        ),
        pinned_message_indices=list(planning.pinned_message_indices),
        preserved_from_turn=planning.preserved_from_turn,
        candidate_turn_indices=list(planning.candidate_turn_indices),
        compacted_turn_indices=list(planning.compacted_turn_indices),
        replacement_summary_planned=selection_result.synthetic_summary_message is not None,
        carried_forward_state_planned=(
            selection_result.compaction_artifact is not None
            and selection_result.compaction_artifact.carried_forward_state is not None
        ),
        context_selection=selection_result.context_selection,
        selected_messages=list(selection_result.selected_messages),
        compaction_artifact=selection_result.compaction_artifact,
        synthetic_summary_message=selection_result.synthetic_summary_message,
        model_backed_requested=(
            normalized_mode == ContextPolicyMode.MODEL_BACKED_COMPACTION.value
        ),
        model_backed_used=False,
        compaction_backend_mode=None,
        fallback_policy=(
            "deterministic_compaction"
            if normalized_mode == ContextPolicyMode.MODEL_BACKED_COMPACTION.value
            else None
        ),
        fallback_applied=False,
        fallback_reason=None,
        compaction_backend_failure_kind=None,
    )


def compacted_messages_for_plan(
    request_messages: list[Message],
    context_plan: ContextSelectionPlan,
) -> list[Message]:
    """Return the original messages that the plan marked for compaction."""

    artifact = context_plan.compaction_artifact
    if artifact is None:
        return []
    compacted_index_set = set(artifact.compacted_message_indices)
    return [
        message
        for index, message in enumerate(request_messages)
        if index in compacted_index_set
    ]


def apply_model_backed_compaction_output(
    context_plan: ContextSelectionPlan,
    *,
    output: ModelBackedCompactionOutput,
    backend_mode: str = "inline_model",
) -> ContextSelectionPlan:
    """Replace the deterministic summary/carryover with model-backed output."""

    if context_plan.compaction_artifact is None:
        return context_plan
    summary_slot = context_plan.compaction_artifact.summary_slot
    if summary_slot is None:
        summary_slot = SummarySlot(
            slot_id=f"summary_slot_turn_{context_plan.turn_index:03d}",
            status="materialized",
            source_message_indices=list(
                context_plan.compaction_artifact.compacted_message_indices
            ),
            rendered_text=output.summary_text,
            opened_at_turn=context_plan.turn_index,
            last_refreshed_turn=context_plan.turn_index,
            summary_kind="model_backed_compaction",
        )
    else:
        summary_slot = summary_slot.model_copy(
            update={
                "rendered_text": output.summary_text,
                "last_refreshed_turn": context_plan.turn_index,
                "summary_kind": "model_backed_compaction",
            }
        )
    updated_artifact = context_plan.compaction_artifact.model_copy(
        update={
            "policy_mode": ContextPolicyMode.MODEL_BACKED_COMPACTION.value,
            "summary_slot": summary_slot,
            "carried_forward_state": output.carried_forward_state,
        }
    )
    summary_message = Message(
        role=Role.SYSTEM,
        content=output.summary_text,
        metadata={
            "synthetic": True,
            "summary_kind": "model_backed_compaction",
            "summary_slot_id": summary_slot.slot_id,
            "source_message_indices": summary_slot.source_message_indices,
        },
    )
    updated_selection = context_plan.context_selection.model_copy(
        update={"policy_mode": ContextPolicyMode.MODEL_BACKED_COMPACTION.value}
    )
    return context_plan.model_copy(
        update={
            "policy_mode": ContextPolicyMode.MODEL_BACKED_COMPACTION.value,
            "context_selection": updated_selection,
            "compaction_artifact": updated_artifact,
            "synthetic_summary_message": summary_message,
            "model_backed_requested": True,
            "model_backed_used": True,
            "compaction_backend_mode": backend_mode,
            "fallback_applied": False,
            "fallback_reason": None,
            "compaction_backend_failure_kind": None,
        }
    )


def apply_model_backed_fallback(
    context_plan: ContextSelectionPlan,
    *,
    backend_mode: str,
    fallback_policy: str,
    fallback_reason: str,
    failure_kind: str,
) -> ContextSelectionPlan:
    """Freeze one explicit fallback decision on top of the deterministic plan."""

    if backend_mode != MODEL_BACKED_COMPACTION_BACKEND:
        raise ValueError(f"Unsupported model-backed compaction backend: {backend_mode}")
    if fallback_policy != MODEL_BACKED_COMPACTION_FALLBACK_POLICY:
        raise ValueError(f"Unsupported compaction fallback policy: {fallback_policy}")
    if failure_kind not in MODEL_BACKED_COMPACTION_FAILURE_KINDS:
        raise ValueError(f"Unsupported compaction failure kind: {failure_kind}")

    return context_plan.model_copy(
        update={
            "model_backed_requested": True,
            "model_backed_used": False,
            "compaction_backend_mode": backend_mode,
            "fallback_policy": fallback_policy,
            "fallback_applied": True,
            "fallback_reason": fallback_reason,
            "compaction_backend_failure_kind": failure_kind,
        }
    )


def select_request_messages(
    messages: list[Message],
    *,
    policy_mode: ContextPolicyMode | str,
    max_messages: int | None,
    session_state: RuntimeSessionState | None = None,
    turn_index: int | None = None,
    context_max_tokens: int | None = None,
    tool_token_reserve: int = 0,
    response_token_reserve: int = 0,
) -> ContextSelectionResult:
    """Select request-visible messages under one formal compaction policy."""

    normalized_mode = _normalize_policy_mode(policy_mode)
    if normalized_mode == ContextPolicyMode.FULL_HISTORY:
        return _select_full_history(
            messages,
            max_messages=max_messages,
            context_max_tokens=context_max_tokens,
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
        )
    if normalized_mode == ContextPolicyMode.TAIL_WINDOW:
        return _select_tail_window(
            messages,
            max_messages=max_messages,
            context_max_tokens=context_max_tokens,
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
        )
    if normalized_mode == ContextPolicyMode.MODEL_BACKED_COMPACTION:
        result = _select_deterministic_compaction(
            messages,
            max_messages=max_messages,
            session_state=session_state,
            turn_index=turn_index,
            context_max_tokens=context_max_tokens,
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
        )
        updated_artifact = (
            result.compaction_artifact.model_copy(
                update={"policy_mode": ContextPolicyMode.MODEL_BACKED_COMPACTION.value}
            )
            if result.compaction_artifact is not None
            else None
        )
        return result.model_copy(
            update={
                "context_selection": result.context_selection.model_copy(
                    update={"policy_mode": ContextPolicyMode.MODEL_BACKED_COMPACTION.value}
                ),
                "compaction_artifact": updated_artifact,
            }
        )
    return _select_deterministic_compaction(
        messages,
        max_messages=max_messages,
        session_state=session_state,
        turn_index=turn_index,
        context_max_tokens=context_max_tokens,
        tool_token_reserve=tool_token_reserve,
        response_token_reserve=response_token_reserve,
    )


def structured_output_schema_for_compaction() -> dict[str, Any]:
    """Return the provider-facing structured schema for model-backed compaction."""

    return ModelBackedCompactionOutput.model_json_schema()


def _normalize_policy_mode(policy_mode: ContextPolicyMode | str) -> ContextPolicyMode:
    if isinstance(policy_mode, ContextPolicyMode):
        return policy_mode
    return ContextPolicyMode(str(policy_mode))


def _select_full_history(
    messages: list[Message],
    *,
    max_messages: int | None,
    context_max_tokens: int | None,
    tool_token_reserve: int,
    response_token_reserve: int,
) -> ContextSelectionResult:
    included_indices = list(range(len(messages)))
    selection = _build_context_selection(
        messages,
        selected_messages=list(messages),
        policy_mode=ContextPolicyMode.FULL_HISTORY.value,
        max_messages=max_messages,
        context_max_tokens=context_max_tokens,
        included_indices=included_indices,
        compaction_applied=False,
        compaction_reason=None,
        compacted_message_count=0,
        tool_token_reserve=tool_token_reserve,
        response_token_reserve=response_token_reserve,
    )
    return ContextSelectionResult(
        selected_messages=list(messages),
        context_selection=selection,
        planning_metadata=CompactionPlanningMetadata(
            compaction_considered=False,
            consideration_reason="full_history_policy",
        ),
    )


def _select_tail_window(
    messages: list[Message],
    *,
    max_messages: int | None,
    context_max_tokens: int | None,
    tool_token_reserve: int,
    response_token_reserve: int,
) -> ContextSelectionResult:
    pinned_indices = [
        index
        for index, message in enumerate(messages)
        if message.role in {Role.SYSTEM, Role.USER}
    ]
    non_pinned_indices = [
        index
        for index, message in enumerate(messages)
        if message.role not in {Role.SYSTEM, Role.USER}
    ]

    if max_messages is None and context_max_tokens is None:
        selected_messages = list(messages)
        selection = _build_context_selection(
            messages,
            selected_messages=selected_messages,
            policy_mode=ContextPolicyMode.TAIL_WINDOW.value,
            max_messages=max_messages,
            context_max_tokens=context_max_tokens,
            included_indices=list(range(len(messages))),
            compaction_applied=False,
            compaction_reason=None,
            compacted_message_count=0,
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
        )
        return ContextSelectionResult(
            selected_messages=selected_messages,
            context_selection=selection,
            planning_metadata=CompactionPlanningMetadata(
                compaction_considered=False,
                consideration_reason="tail_window_without_limits",
                pinned_message_indices=pinned_indices,
            ),
        )

    selected_non_pinned: list[int] = []
    remaining_capacity = None
    if max_messages is not None:
        remaining_capacity = max(max_messages - len(pinned_indices), 0)

    for index in reversed(non_pinned_indices):
        candidate_non_pinned = [index, *selected_non_pinned]
        if remaining_capacity is not None and len(candidate_non_pinned) > remaining_capacity:
            continue
        candidate_indices = sorted(set(pinned_indices) | set(candidate_non_pinned))
        candidate_messages = [messages[i] for i in candidate_indices]
        if not _token_budget_allows(
            candidate_messages,
            context_max_tokens=context_max_tokens,
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
        ):
            continue
        selected_non_pinned = candidate_non_pinned

    included_indices = sorted(set(pinned_indices) | set(selected_non_pinned))
    selected_messages = [messages[index] for index in included_indices]
    reason = None
    if len(included_indices) < len(messages):
        reason = "tail_window_truncation"

    selection = _build_context_selection(
        messages,
        selected_messages=selected_messages,
        policy_mode=ContextPolicyMode.TAIL_WINDOW.value,
        max_messages=max_messages,
        context_max_tokens=context_max_tokens,
        included_indices=included_indices,
        compaction_applied=len(included_indices) < len(messages),
        compaction_reason=reason,
        compacted_message_count=max(len(messages) - len(included_indices), 0),
        tool_token_reserve=tool_token_reserve,
        response_token_reserve=response_token_reserve,
    )
    if (
        context_max_tokens is not None
        and not selection.token_budget_satisfied
        and len(included_indices) == len(pinned_indices)
    ):
        selection.compaction_reason = "pinned_token_overflow"
    return ContextSelectionResult(
        selected_messages=selected_messages,
        context_selection=selection,
        planning_metadata=CompactionPlanningMetadata(
            compaction_considered=True,
            consideration_reason=(
                "tail_window_limit_exceeded"
                if len(included_indices) < len(messages)
                else "tail_window_limit_not_triggered"
            ),
            skip_reason=(
                None if len(included_indices) < len(messages) else "all_messages_retained"
            ),
            trigger_message_overflow=(max_messages is not None and len(messages) > max_messages),
            trigger_token_overflow=(
                context_max_tokens is not None
                and not _token_budget_allows(
                    messages,
                    context_max_tokens=context_max_tokens,
                    tool_token_reserve=tool_token_reserve,
                    response_token_reserve=response_token_reserve,
                )
            ),
            pinned_message_indices=pinned_indices,
        ),
    )


def _select_deterministic_compaction(
    messages: list[Message],
    *,
    max_messages: int | None,
    session_state: RuntimeSessionState | None,
    turn_index: int | None,
    context_max_tokens: int | None,
    tool_token_reserve: int,
    response_token_reserve: int,
) -> ContextSelectionResult:
    all_messages_fit = _message_count_allows(messages, max_messages=max_messages) and _token_budget_allows(
        messages,
        context_max_tokens=context_max_tokens,
        tool_token_reserve=tool_token_reserve,
        response_token_reserve=response_token_reserve,
    )
    before_message_overflow = max_messages is not None and len(messages) > max_messages
    before_token_overflow = (
        context_max_tokens is not None
        and not _token_budget_allows(
            messages,
            context_max_tokens=context_max_tokens,
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
        )
    )
    if session_state is None or turn_index is None or all_messages_fit:
        selection = _build_context_selection(
            messages,
            selected_messages=list(messages),
            policy_mode=ContextPolicyMode.DETERMINISTIC_COMPACTION.value,
            max_messages=max_messages,
            context_max_tokens=context_max_tokens,
            included_indices=list(range(len(messages))),
            compaction_applied=False,
            compaction_reason=None,
            compacted_message_count=0,
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
        )
        return ContextSelectionResult(
            selected_messages=list(messages),
            context_selection=selection,
            planning_metadata=CompactionPlanningMetadata(
                compaction_considered=not all_messages_fit,
                consideration_reason=(
                    "within_limits"
                    if all_messages_fit
                    else "missing_session_state_for_compaction"
                ),
                skip_reason=(
                    None if all_messages_fit else "missing_session_state_or_turn_index"
                ),
                trigger_message_overflow=before_message_overflow,
                trigger_token_overflow=before_token_overflow,
            ),
        )

    pinned_indices = [
        index
        for index, message in enumerate(messages)
        if message.role in {Role.SYSTEM, Role.USER}
    ]
    turn_ranges = _build_turn_ranges(messages)
    if not turn_ranges:
        selection = _build_context_selection(
            messages,
            selected_messages=list(messages),
            policy_mode=ContextPolicyMode.DETERMINISTIC_COMPACTION.value,
            max_messages=max_messages,
            context_max_tokens=context_max_tokens,
            included_indices=list(range(len(messages))),
            compaction_applied=False,
            compaction_reason=None,
            compacted_message_count=0,
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
        )
        return ContextSelectionResult(
            selected_messages=list(messages),
            context_selection=selection,
            planning_metadata=CompactionPlanningMetadata(
                compaction_considered=True,
                consideration_reason="deterministic_compaction_candidate_search",
                skip_reason="no_turn_ranges_available",
                trigger_message_overflow=before_message_overflow,
                trigger_token_overflow=before_token_overflow,
                pinned_message_indices=pinned_indices,
            ),
        )

    preserve_from_turn = _preserve_from_turn(session_state)
    candidate_ranges = [
        turn_range
        for turn_range in turn_ranges
        if preserve_from_turn is None or turn_range.turn_index < preserve_from_turn
    ]
    if not candidate_ranges:
        selection = _build_context_selection(
            messages,
            selected_messages=list(messages),
            policy_mode=ContextPolicyMode.DETERMINISTIC_COMPACTION.value,
            max_messages=max_messages,
            context_max_tokens=context_max_tokens,
            included_indices=list(range(len(messages))),
            compaction_applied=False,
            compaction_reason=None,
            compacted_message_count=0,
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
        )
        return ContextSelectionResult(
            selected_messages=list(messages),
            context_selection=selection,
            planning_metadata=CompactionPlanningMetadata(
                compaction_considered=True,
                consideration_reason="deterministic_compaction_candidate_search",
                skip_reason="candidate_turns_preserved",
                trigger_message_overflow=before_message_overflow,
                trigger_token_overflow=before_token_overflow,
                pinned_message_indices=pinned_indices,
                preserved_from_turn=preserve_from_turn,
                candidate_turn_indices=[],
            ),
        )

    compacted_ranges: list[TurnRangeSummary] = []
    compacted_indices: list[int] = []
    selected_messages: list[Message] = list(messages)
    summary_slot: SummarySlot | None = None
    carried_forward_state: CarriedForwardState | None = None
    synthetic_summary_message: Message | None = None
    overflow_reason: str | None = None

    estimated_before = estimate_messages_tokens(messages)
    token_budget_target = _message_token_budget(
        context_max_tokens=context_max_tokens,
        tool_token_reserve=tool_token_reserve,
        response_token_reserve=response_token_reserve,
    )

    for candidate in candidate_ranges:
        compacted_ranges.append(candidate)
        compacted_indices.extend(candidate.message_indices)
        compacted_index_set = set(compacted_indices)
        carried_forward_state = _build_carried_forward_state(session_state, compacted_ranges)
        summary_text = _render_deterministic_summary(
            compacted_ranges=compacted_ranges,
            carried_forward_state=carried_forward_state,
        )
        summary_slot = SummarySlot(
            slot_id=f"summary_slot_turn_{turn_index:03d}",
            status="materialized",
            source_message_indices=sorted(compacted_index_set),
            rendered_text=summary_text,
            opened_at_turn=compacted_ranges[0].turn_index,
            last_refreshed_turn=turn_index,
            summary_kind="deterministic_turn_compaction",
        )
        synthetic_summary_message = Message(
            role=Role.SYSTEM,
            content=summary_text,
            metadata={
                "synthetic": True,
                "summary_kind": summary_slot.summary_kind,
                "summary_slot_id": summary_slot.slot_id,
                "source_message_indices": summary_slot.source_message_indices,
            },
        )
        selected_messages = []
        summary_inserted = False
        for index, message in enumerate(messages):
            if index in compacted_index_set:
                if not summary_inserted:
                    selected_messages.append(synthetic_summary_message)
                    summary_inserted = True
                continue
            selected_messages.append(message)

        if _message_count_allows(selected_messages, max_messages=max_messages) and _token_budget_allows(
            selected_messages,
            context_max_tokens=context_max_tokens,
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
        ):
            break

    compacted_index_set = set(compacted_indices)
    if not compacted_index_set or summary_slot is None or carried_forward_state is None:
        selection = _build_context_selection(
            messages,
            selected_messages=list(messages),
            policy_mode=ContextPolicyMode.DETERMINISTIC_COMPACTION.value,
            max_messages=max_messages,
            context_max_tokens=context_max_tokens,
            included_indices=list(range(len(messages))),
            compaction_applied=False,
            compaction_reason=None,
            compacted_message_count=0,
            tool_token_reserve=tool_token_reserve,
            response_token_reserve=response_token_reserve,
        )
        return ContextSelectionResult(
            selected_messages=list(messages),
            context_selection=selection,
            planning_metadata=CompactionPlanningMetadata(
                compaction_considered=True,
                consideration_reason="deterministic_compaction_candidate_search",
                skip_reason="unable_to_materialize_compaction_artifact",
                trigger_message_overflow=before_message_overflow,
                trigger_token_overflow=before_token_overflow,
                pinned_message_indices=pinned_indices,
                preserved_from_turn=preserve_from_turn,
                candidate_turn_indices=[candidate.turn_index for candidate in candidate_ranges],
            ),
        )

    estimated_after = estimate_messages_tokens(selected_messages)
    token_budget_satisfied = _token_budget_allows(
        selected_messages,
        context_max_tokens=context_max_tokens,
        tool_token_reserve=tool_token_reserve,
        response_token_reserve=response_token_reserve,
    )
    if not token_budget_satisfied:
        overflow_reason = "token_budget_unsatisfied_after_compaction"
        if len(selected_messages) <= len(pinned_indices):
            overflow_reason = "pinned_token_overflow"

    compaction_reason = "deterministic_turn_compaction"
    artifact_reason = "message_limit_exceeded"
    if before_message_overflow and before_token_overflow:
        artifact_reason = "message_and_token_limit_exceeded"
    elif before_token_overflow:
        artifact_reason = "token_budget_exceeded"

    compaction_artifact = CompactionArtifact(
        policy_mode=ContextPolicyMode.DETERMINISTIC_COMPACTION.value,
        turn_index=turn_index,
        pinned_message_indices=pinned_indices,
        compacted_message_indices=sorted(compacted_index_set),
        retained_message_indices=[
            index for index in range(len(messages)) if index not in compacted_index_set
        ],
        candidate_turn_ranges=compacted_ranges,
        summary_slot=summary_slot,
        carried_forward_state=carried_forward_state,
        reason=artifact_reason,
        estimated_tokens_before=estimated_before,
        estimated_tokens_after=estimated_after,
        token_budget_target=token_budget_target,
        token_budget_satisfied=token_budget_satisfied,
        overflow_reason=overflow_reason,
    )

    included_indices = [
        index for index in range(len(messages)) if index not in compacted_index_set
    ]
    selection = _build_context_selection(
        messages,
        selected_messages=selected_messages,
        policy_mode=ContextPolicyMode.DETERMINISTIC_COMPACTION.value,
        max_messages=max_messages,
        context_max_tokens=context_max_tokens,
        included_indices=included_indices,
        compaction_applied=True,
        compaction_reason=compaction_reason,
        compacted_message_count=len(compacted_index_set),
        tool_token_reserve=tool_token_reserve,
        response_token_reserve=response_token_reserve,
    )
    if overflow_reason is not None and selection.compaction_reason == compaction_reason:
        selection.compaction_reason = overflow_reason
    return ContextSelectionResult(
        selected_messages=selected_messages,
        context_selection=selection,
        compaction_artifact=compaction_artifact,
        synthetic_summary_message=synthetic_summary_message,
        planning_metadata=CompactionPlanningMetadata(
            compaction_considered=True,
            consideration_reason=artifact_reason,
            trigger_message_overflow=before_message_overflow,
            trigger_token_overflow=before_token_overflow,
            pinned_message_indices=pinned_indices,
            preserved_from_turn=preserve_from_turn,
            candidate_turn_indices=[candidate.turn_index for candidate in candidate_ranges],
            compacted_turn_indices=[
                compacted_range.turn_index for compacted_range in compacted_ranges
            ],
        ),
    )


def _build_context_selection(
    messages: list[Message],
    *,
    selected_messages: list[Message],
    policy_mode: str,
    max_messages: int | None,
    context_max_tokens: int | None,
    included_indices: list[int],
    compaction_applied: bool,
    compaction_reason: str | None,
    compacted_message_count: int,
    tool_token_reserve: int,
    response_token_reserve: int,
) -> ContextSelection:
    included_role_counts: dict[str, int] = {}
    for index in included_indices:
        role = messages[index].role.value
        included_role_counts[role] = included_role_counts.get(role, 0) + 1

    omitted_indices = [
        index for index in range(len(messages)) if index not in set(included_indices)
    ]
    estimated_selected_tokens = estimate_messages_tokens(selected_messages)
    estimated_omitted_tokens = sum(
        estimate_message_tokens(messages[index]) for index in omitted_indices
    )
    token_overflow = _token_overflow(
        selected_messages,
        context_max_tokens=context_max_tokens,
        tool_token_reserve=tool_token_reserve,
        response_token_reserve=response_token_reserve,
    )

    return ContextSelection(
        policy_mode=policy_mode,
        max_messages=max_messages,
        context_max_tokens=context_max_tokens,
        included_message_indices=included_indices,
        omitted_message_count=max(len(messages) - len(included_indices), 0),
        compacted_message_count=compacted_message_count,
        first_included_index=(included_indices[0] if included_indices else None),
        last_included_index=(included_indices[-1] if included_indices else None),
        included_role_counts=included_role_counts,
        compaction_applied=compaction_applied,
        compaction_reason=compaction_reason,
        estimated_selected_tokens=estimated_selected_tokens,
        estimated_omitted_tokens=estimated_omitted_tokens,
        tool_token_reserve=tool_token_reserve,
        response_token_reserve=response_token_reserve,
        token_budget_satisfied=token_overflow == 0,
        token_overflow=token_overflow,
    )


def _build_turn_ranges(messages: list[Message]) -> list[TurnRangeSummary]:
    turn_ranges: list[TurnRangeSummary] = []
    current_turn: dict[str, Any] | None = None
    turn_index = 0
    for index, message in enumerate(messages):
        if message.role == Role.ASSISTANT:
            if current_turn is not None:
                turn_ranges.append(_finalize_turn_range(current_turn))
            turn_index += 1
            current_turn = {
                "turn_index": turn_index,
                "message_indices": [index],
                "tool_names": [
                    tool_call.name
                    for tool_call in message.tool_calls
                    if isinstance(tool_call, ToolCall)
                ],
                "tool_call_ids": [
                    tool_call.id
                    for tool_call in message.tool_calls
                    if isinstance(tool_call, ToolCall)
                ],
            }
            continue
        if current_turn is not None and message.role == Role.TOOL:
            current_turn["message_indices"].append(index)

    if current_turn is not None:
        turn_ranges.append(_finalize_turn_range(current_turn))
    return turn_ranges


def _finalize_turn_range(turn_data: dict[str, Any]) -> TurnRangeSummary:
    indices = list(turn_data["message_indices"])
    return TurnRangeSummary(
        turn_index=int(turn_data["turn_index"]),
        message_indices=indices,
        start_index=indices[0],
        end_index=indices[-1],
        tool_names=list(turn_data.get("tool_names", [])),
        tool_call_ids=list(turn_data.get("tool_call_ids", [])),
    )


def _preserve_from_turn(session_state: RuntimeSessionState) -> int | None:
    preserve_candidates: list[int] = []
    if session_state.active_pending_issue is not None:
        preserve_candidates.append(session_state.active_pending_issue.opened_at_turn)

    recovery_state = session_state.recovery_state
    last_successful_validation_turn = getattr(
        recovery_state,
        "last_successful_validation_turn",
        None,
    )
    if last_successful_validation_turn is not None:
        preserve_candidates.append(last_successful_validation_turn)

    if not preserve_candidates:
        return None
    return min(preserve_candidates)


def _build_carried_forward_state(
    session_state: RuntimeSessionState,
    compacted_ranges: list[TurnRangeSummary],
) -> CarriedForwardState:
    recovery_state = session_state.recovery_state
    recent_compacted_tool_outcomes: list[dict[str, Any]] = []
    prior_turn_states = {
        turn_state.turn_index: turn_state for turn_state in session_state.turn_states
    }
    for compacted_range in compacted_ranges:
        prior_turn_state = prior_turn_states.get(compacted_range.turn_index)
        recent_compacted_tool_outcomes.append(
            {
                "turn_index": compacted_range.turn_index,
                "tool_names": compacted_range.tool_names,
                "tool_call_ids": compacted_range.tool_call_ids,
                "stop_decision_code": (
                    prior_turn_state.stop_decision_code if prior_turn_state is not None else ""
                ),
            }
        )

    notes = [
        f"Compacted turns {compacted_ranges[0].turn_index}-{compacted_ranges[-1].turn_index}"
    ]
    if session_state.active_pending_issue is not None:
        notes.append(
            "Pending issue remains active and was preserved outside the compacted range"
        )
    if getattr(recovery_state, "last_successful_validation_turn", None) is not None:
        notes.append(
            "Recent validated context was retained without compacting post-validation turns"
        )

    return CarriedForwardState(
        pending_issue_kind=(
            session_state.active_pending_issue.kind
            if session_state.active_pending_issue is not None
            else None
        ),
        pending_issue_detail=(
            session_state.active_pending_issue.detail
            if session_state.active_pending_issue is not None
            else ""
        ),
        completion_evidence_status=getattr(
            recovery_state,
            "completion_evidence_status",
            None,
        ).value
        if getattr(recovery_state, "completion_evidence_status", None) is not None
        else None,
        validation_phase=getattr(recovery_state, "validation_phase", None).value
        if getattr(recovery_state, "validation_phase", None) is not None
        else None,
        last_successful_validation_turn=getattr(
            recovery_state,
            "last_successful_validation_turn",
            None,
        ),
        last_validation_attempt_turn=getattr(
            recovery_state,
            "last_validation_attempt_turn",
            None,
        ),
        last_validation_failure_turn=getattr(
            recovery_state,
            "last_validation_failure_turn",
            None,
        ),
        last_mutation_turn=getattr(recovery_state, "last_mutation_turn", None),
        recent_compacted_tool_outcomes=recent_compacted_tool_outcomes,
        carried_notes=notes,
    )


def _render_deterministic_summary(
    *,
    compacted_ranges: list[TurnRangeSummary],
    carried_forward_state: CarriedForwardState,
) -> str:
    lines = [
        "[compacted runtime context]",
        (
            f"covered_turns={compacted_ranges[0].turn_index}-"
            f"{compacted_ranges[-1].turn_index}"
        ),
        (
            "completion_evidence_status="
            f"{carried_forward_state.completion_evidence_status or 'unknown'}"
        ),
        (
            "validation_phase="
            f"{carried_forward_state.validation_phase or 'unknown'}"
        ),
        (
            "pending_issue="
            f"{carried_forward_state.pending_issue_kind or 'none'}"
        ),
    ]

    if carried_forward_state.last_successful_validation_turn is not None:
        lines.append(
            "last_successful_validation_turn="
            f"{carried_forward_state.last_successful_validation_turn}"
        )
    if carried_forward_state.last_validation_failure_turn is not None:
        lines.append(
            "last_validation_failure_turn="
            f"{carried_forward_state.last_validation_failure_turn}"
        )
    if carried_forward_state.last_mutation_turn is not None:
        lines.append(f"last_mutation_turn={carried_forward_state.last_mutation_turn}")

    for outcome in carried_forward_state.recent_compacted_tool_outcomes:
        tool_names = ",".join(outcome.get("tool_names", [])) or "none"
        lines.append(
            "turn="
            f"{outcome['turn_index']}:tools={tool_names}:stop={outcome.get('stop_decision_code', '')}"
        )

    for note in carried_forward_state.carried_notes:
        lines.append(f"note={note}")
    return "\n".join(lines)


def _message_count_allows(
    messages: list[Message],
    *,
    max_messages: int | None,
) -> bool:
    return max_messages is None or len(messages) <= max_messages


def _message_token_budget(
    *,
    context_max_tokens: int | None,
    tool_token_reserve: int,
    response_token_reserve: int,
) -> int | None:
    if context_max_tokens is None:
        return None
    return max(context_max_tokens - tool_token_reserve - response_token_reserve, 0)


def _token_budget_allows(
    messages: list[Message],
    *,
    context_max_tokens: int | None,
    tool_token_reserve: int,
    response_token_reserve: int,
) -> bool:
    if context_max_tokens is None:
        return True
    return (
        estimate_messages_tokens(messages) + tool_token_reserve + response_token_reserve
        <= context_max_tokens
    )


def _token_overflow(
    messages: list[Message],
    *,
    context_max_tokens: int | None,
    tool_token_reserve: int,
    response_token_reserve: int,
) -> int:
    if context_max_tokens is None:
        return 0
    total = (
        estimate_messages_tokens(messages) + tool_token_reserve + response_token_reserve
    )
    return max(total - context_max_tokens, 0)
