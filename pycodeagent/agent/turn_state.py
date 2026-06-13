"""Formal runtime turn state and explicit context selection contracts."""

from __future__ import annotations

import json
import math
from typing import Any

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from pycodeagent.trajectory.schema import Message, Role, ToolCall


class ContextPolicyMode(str, Enum):
    """Supported request-time context selection policies."""

    FULL_HISTORY = "full_history"
    TAIL_WINDOW = "tail_window"
    DETERMINISTIC_COMPACTION = "deterministic_compaction"
    MODEL_BACKED_COMPACTION = "model_backed_compaction"


class ContextSelection(BaseModel):
    """Audit record describing which trajectory messages entered a request."""

    policy_mode: str
    max_messages: int | None = None
    context_max_tokens: int | None = None
    included_message_indices: list[int] = Field(default_factory=list)
    omitted_message_count: int = 0
    compacted_message_count: int = 0
    first_included_index: int | None = None
    last_included_index: int | None = None
    included_role_counts: dict[str, int] = Field(default_factory=dict)
    compaction_applied: bool = False
    compaction_reason: str | None = None
    estimated_selected_tokens: int = 0
    estimated_omitted_tokens: int = 0
    tool_token_reserve: int = 0
    response_token_reserve: int = 0
    token_budget_satisfied: bool = True
    token_overflow: int = 0


class PendingIssueRecord(BaseModel):
    """Turn-scoped fact for a runtime issue that stays active across turns."""

    issue_id: str | None = None
    kind: str
    detail: str
    opened_at_turn: int
    last_observed_turn: int
    cleared_at_turn: int | None = None
    resolution_trigger: str | None = None


class TurnLifecyclePhase(str, Enum):
    """Explicit lifecycle boundary for one runtime turn."""

    TURN_STARTED = "turn_started"
    REQUEST_BUILT = "request_built"
    PROVIDER_RESPONSE_RECEIVED = "provider_response_received"
    RESPONSE_INTERPRETED = "response_interpreted"
    ASSISTANT_PARSED = "assistant_parsed"
    TOOL_DISPATCH = "tool_dispatch"
    POST_TOOL_OBSERVATION = "post_tool_observation"
    STOP_DECIDED = "stop_decided"
    TURN_COMPLETED = "turn_completed"


class ContinuationDecisionKind(str, Enum):
    """Typed outcome for the end of one turn."""

    CONTINUE_WITH_TOOL_CALLS = "continue_with_tool_calls"
    CONTINUE_AFTER_RECOVERABLE_FAILURE = "continue_after_recoverable_failure"
    CONTINUE_AFTER_BLOCKED_FINISH = "continue_after_blocked_finish"
    STOP_FINISH = "stop_finish"
    STOP_NO_TOOL_CALLS = "stop_no_tool_calls"
    STOP_MAX_TURNS = "stop_max_turns"
    STOP_PARSE_ERROR = "stop_parse_error"
    STOP_LLM_ERROR = "stop_llm_error"
    STOP_VALIDATION_BUDGET_EXHAUSTED = "stop_validation_budget_exhausted"
    STOP_REVISION_BUDGET_EXHAUSTED = "stop_revision_budget_exhausted"
    STOP_FINISH_DEFERRAL_BUDGET_EXHAUSTED = "stop_finish_deferral_budget_exhausted"


class SessionTerminationKind(str, Enum):
    """Typed run termination taxonomy for the session state."""

    RUNNING = "running"
    COMPLETED = "completed"
    MAX_TURNS = "max_turns"
    NO_TOOL_CALLS = "no_tool_calls"
    PARSE_ERROR = "parse_error"
    LLM_ERROR = "llm_error"
    VALIDATION_BUDGET_EXHAUSTED = "validation_budget_exhausted"
    REVISION_BUDGET_EXHAUSTED = "revision_budget_exhausted"
    FINISH_DEFERRAL_BUDGET_EXHAUSTED = "finish_deferral_budget_exhausted"


class SessionStopStatus(str, Enum):
    """High-level run status for the local runtime state machine."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ERROR = "error"


class SessionOutcomeRecord(BaseModel):
    """Frozen session-level outcome for one completed local runtime run."""

    total_turns: int
    final_status: str | None = None
    session_stop_status: str
    session_termination_kind: str
    stop_reason: str
    stop_detail: str
    stop_decision_code: str


class SessionBudgetSnapshot(BaseModel):
    """Stable view of retry and validation budgets at a session boundary."""

    validation_budget_total: int | None = None
    validation_budget_remaining: int | None = None
    validation_budget_used: int = 0
    revision_budget_total: int | None = None
    revision_budget_remaining: int | None = None
    revision_budget_used: int = 0
    finish_deferral_budget_total: int | None = None
    finish_deferral_budget_remaining: int | None = None
    finish_deferral_budget_used: int = 0


class TurnContinuationRecord(BaseModel):
    """Append-only continuation or termination fact for one completed turn."""

    model_config = ConfigDict(protected_namespaces=())

    turn_index: int
    decision_code: str
    continuation_decision_kind: str | None = None
    termination_kind: str | None = None
    continue_reason: str | None = None
    blocked_reason: str | None = None
    pending_issue_id: str | None = None
    pending_issue_kind: str | None = None
    active_validation_issue_id: str | None = None
    active_validation_issue_kind: str | None = None
    completion_block_family: str | None = None
    completion_gate_status: str | None = None
    expected_next_step: str | None = None
    completion_evidence_status: str | None = None
    validation_phase: str | None = None
    meaningful_progress_observed: bool = False
    recent_failure_kind: str | None = None
    active_failure_kind: str | None = None
    corrective_progress_after_failure: bool = False
    post_mutation_validation_pending: bool = False
    finish_blocked_by_policy: bool = False
    finish_gate_reason: str | None = None
    completion_allowed: bool = True
    model_needs_follow_up: bool = False
    runtime_needs_follow_up: bool = False
    stop_hook_evaluated: bool = False
    stop_hook_blocked: bool = False
    stop_hook_reason: str | None = None
    stop_hook_reason_code: str = "none"
    policy_mode: str | None = None


class SummarySlot(BaseModel):
    """Deterministic carryover summary materialized from compacted turns."""

    slot_id: str
    status: str
    source_message_indices: list[int] = Field(default_factory=list)
    rendered_text: str = ""
    opened_at_turn: int
    last_refreshed_turn: int
    summary_kind: str


class CarriedForwardState(BaseModel):
    """Structured facts carried across a compacted request boundary."""

    pending_issue_kind: str | None = None
    pending_issue_detail: str = ""
    completion_evidence_status: str | None = None
    validation_phase: str | None = None
    last_successful_validation_turn: int | None = None
    last_validation_attempt_turn: int | None = None
    last_validation_failure_turn: int | None = None
    last_mutation_turn: int | None = None
    recent_compacted_tool_outcomes: list[dict[str, Any]] = Field(default_factory=list)
    carried_notes: list[str] = Field(default_factory=list)


class TurnRangeSummary(BaseModel):
    """Compact summary of one prior turn eligible for compaction."""

    turn_index: int
    message_indices: list[int] = Field(default_factory=list)
    start_index: int
    end_index: int
    tool_names: list[str] = Field(default_factory=list)
    tool_call_ids: list[str] = Field(default_factory=list)


class CompactionArtifact(BaseModel):
    """Deterministic record of one request-time compaction decision."""

    artifact_version: int = 1
    policy_mode: str
    turn_index: int
    pinned_message_indices: list[int] = Field(default_factory=list)
    compacted_message_indices: list[int] = Field(default_factory=list)
    retained_message_indices: list[int] = Field(default_factory=list)
    candidate_turn_ranges: list[TurnRangeSummary] = Field(default_factory=list)
    summary_slot: SummarySlot | None = None
    carried_forward_state: CarriedForwardState | None = None
    reason: str
    estimated_tokens_before: int = 0
    estimated_tokens_after: int = 0
    token_budget_target: int | None = None
    token_budget_satisfied: bool = True
    overflow_reason: str | None = None


class CompactionPlanningMetadata(BaseModel):
    """Explicit planning facts behind one request-time selection decision."""

    compaction_considered: bool = False
    consideration_reason: str | None = None
    skip_reason: str | None = None
    trigger_message_overflow: bool = False
    trigger_token_overflow: bool = False
    pinned_message_indices: list[int] = Field(default_factory=list)
    preserved_from_turn: int | None = None
    candidate_turn_indices: list[int] = Field(default_factory=list)
    compacted_turn_indices: list[int] = Field(default_factory=list)


class RuntimeTurnState(BaseModel):
    """Per-turn runtime snapshot."""

    model_config = ConfigDict(protected_namespaces=())

    turn_index: int
    message_count_before_turn: int
    lifecycle_phase: str = TurnLifecyclePhase.TURN_STARTED.value
    phases_reached: list[str] = Field(default_factory=list)
    request_history_item_count_before_turn: int = 0
    request_history_item_count_after_snapshot: int = 0
    context_selection: ContextSelection
    pending_issue_id_before_turn: str | None = None
    pending_issue_kind_before_turn: str | None = None
    pending_issue_id_after_turn: str | None = None
    pending_issue_kind_after_turn: str | None = None
    active_validation_issue_kind_before_turn: str | None = None
    active_validation_issue_kind_after_turn: str | None = None
    completion_evidence_status_before_turn: str | None = None
    completion_evidence_status_after_turn: str | None = None
    completion_block_family_after_turn: str | None = None
    validation_phase_before_turn: str | None = None
    validation_phase_after_turn: str | None = None
    expected_next_step_before_turn: str | None = None
    expected_next_step_after_turn: str | None = None
    completion_gate_status_before_turn: str | None = None
    completion_gate_status_after_turn: str | None = None
    active_validation_issue_id_before_turn: str | None = None
    active_validation_issue_id_after_turn: str | None = None
    parse_errors: list[str] = Field(default_factory=list)
    tool_call_ids: list[str] = Field(default_factory=list)
    request_history_item_ids: list[str] = Field(default_factory=list)
    request_history_item_kinds: list[str] = Field(default_factory=list)
    request_history_source_indices: list[int] = Field(default_factory=list)
    requested_tool_call_count: int = 0
    executed_tool_call_count: int = 0
    successful_tool_call_count: int = 0
    turn_action: str | None = None
    turn_outcome: str | None = None
    stop_decision_code: str = ""
    continuation_decision_kind: str | None = None
    termination_kind: str | None = None
    continue_reason: str | None = None
    model_needs_follow_up: bool = False
    runtime_needs_follow_up: bool = False
    stop_hook_evaluated: bool = False
    stop_hook_blocked: bool = False
    stop_hook_reason: str | None = None
    stop_hook_reason_code: str = "none"
    policy_mode: str | None = None
    recent_failure_kind_after_turn: str | None = None
    summary_slot_status_before_turn: str | None = None
    summary_slot_status_after_turn: str | None = None
    carried_forward_state_present_before_turn: bool = False
    carried_forward_state_present_after_turn: bool = False
    replacement_history_active_before_turn: bool = False
    replacement_history_active_after_turn: bool = False
    replacement_history_record_id: str | None = None
    compaction_artifact_ref: str | None = None
    validation_attempt_count_after_turn: int = 0
    revision_attempt_count_after_turn: int = 0
    finish_deferral_count_after_turn: int = 0
    context_token_budget: int | None = None
    selected_context_tokens: int = 0
    token_budget_satisfied: bool = True
    token_overflow_reason: str | None = None
    request_built: bool = False
    provider_response_received: bool = False
    response_interpreted: bool = False
    assistant_parse_completed: bool = False
    tool_dispatch_entered: bool = False
    tool_observation_completed: bool = False
    stop_decision_frozen: bool = False
    turn_completed: bool = False


class RuntimeSessionState(BaseModel):
    """Cross-turn runtime state owned by the local runner."""

    recovery_state: object
    context_policy_mode: str = ContextPolicyMode.FULL_HISTORY.value
    context_max_messages: int | None = None
    context_max_tokens: int | None = None
    tool_token_reserve: int = 0
    response_token_reserve: int = 0
    turn_states: list[RuntimeTurnState] = Field(default_factory=list)
    active_pending_issue: PendingIssueRecord | None = None
    last_cleared_pending_issue: PendingIssueRecord | None = None
    resolved_pending_issues: list[PendingIssueRecord] = Field(default_factory=list)
    summary_slot: SummarySlot | None = None
    carried_forward_state: CarriedForwardState | None = None
    last_compaction_artifact: CompactionArtifact | None = None
    compaction_count: int = 0
    session_stop_status: str = SessionStopStatus.RUNNING.value
    session_termination_kind: str = SessionTerminationKind.RUNNING.value
    total_turns_started: int = 0
    total_turns_completed: int = 0
    parse_recovery_warning_count: int = 0
    recovered_parse_turn_count: int = 0
    finish_attempt_count: int = 0
    finish_blocked_count: int = 0
    finish_block_reason: str | None = None
    finish_gate_reason: str | None = None
    blocked_finish_pending_issue_count: int = 0
    blocked_finish_validation_evidence_count: int = 0
    blocked_finish_progress_gate_count: int = 0
    finish_block_reason_counts: dict[str, int] = Field(default_factory=dict)
    finish_without_progress_count: int = 0
    finish_after_recent_failure_count: int = 0
    unrecovered_failure_turn_count: int = 0
    empty_turn_no_tool_no_content_count: int = 0
    non_finish_tool_call_count: int = 0
    successful_non_finish_tool_call_count: int = 0
    distinct_non_finish_tool_names: list[str] = Field(default_factory=list)
    saw_mutation_progress: bool = False
    saw_validation_progress: bool = False
    recent_failure_kind: str | None = None
    recent_failure_turn: int | None = None
    observed_failure_buckets: list[str] = Field(default_factory=list)
    consecutive_no_progress_turns: int = 0
    consecutive_parse_failure_turns: int = 0
    validation_budget_total: int | None = None
    validation_budget_remaining: int | None = None
    revision_budget_total: int | None = None
    revision_budget_remaining: int | None = None
    finish_deferral_budget_total: int | None = None
    finish_deferral_budget_remaining: int | None = None
    budget_snapshot: SessionBudgetSnapshot | None = None
    final_status: str | None = None
    stop_reason: str = ""
    stop_detail: str = ""
    stop_decision_code: str = ""
    finish_blocked_by_policy: bool = False
    last_continue_reason: str | None = None
    blocked_reason: str | None = None
    last_turn_continuation: TurnContinuationRecord | None = None
    continuation_ledger: list[TurnContinuationRecord] = Field(default_factory=list)
    session_outcome: SessionOutcomeRecord | None = None


class ContextSelectionResult(BaseModel):
    """Internal helper return type for message selection."""

    selected_messages: list[Message]
    context_selection: ContextSelection
    compaction_artifact: CompactionArtifact | None = None
    synthetic_summary_message: Message | None = None
    planning_metadata: CompactionPlanningMetadata = Field(
        default_factory=CompactionPlanningMetadata
    )


def initialize_session_budgets(session_state: RuntimeSessionState) -> None:
    """Seed session-visible retry/validation budgets from recovery policy config."""

    config = getattr(session_state.recovery_state, "validation_policy_config", None)
    if config is None:
        return
    session_state.validation_budget_total = config.max_validation_attempts_per_issue
    session_state.validation_budget_remaining = config.max_validation_attempts_per_issue
    session_state.revision_budget_total = config.max_revision_attempts_per_issue
    session_state.revision_budget_remaining = config.max_revision_attempts_per_issue
    session_state.finish_deferral_budget_total = config.max_finish_deferrals_per_issue
    session_state.finish_deferral_budget_remaining = config.max_finish_deferrals_per_issue
    _refresh_budget_snapshots(session_state)


def begin_turn(session_state: RuntimeSessionState, turn_state: RuntimeTurnState) -> None:
    """Mark a new turn as formally started."""

    session_state.total_turns_started += 1
    mark_turn_phase(turn_state, TurnLifecyclePhase.TURN_STARTED)


def mark_turn_phase(turn_state: RuntimeTurnState, phase: TurnLifecyclePhase | str) -> None:
    """Update the explicit lifecycle phase for the turn."""

    phase_value = phase.value if isinstance(phase, TurnLifecyclePhase) else str(phase)
    turn_state.lifecycle_phase = phase_value
    if phase_value not in turn_state.phases_reached:
        turn_state.phases_reached.append(phase_value)

    if phase_value == TurnLifecyclePhase.REQUEST_BUILT.value:
        turn_state.request_built = True
    elif phase_value == TurnLifecyclePhase.PROVIDER_RESPONSE_RECEIVED.value:
        turn_state.provider_response_received = True
    elif phase_value == TurnLifecyclePhase.RESPONSE_INTERPRETED.value:
        turn_state.response_interpreted = True
    elif phase_value == TurnLifecyclePhase.ASSISTANT_PARSED.value:
        turn_state.assistant_parse_completed = True
    elif phase_value == TurnLifecyclePhase.TOOL_DISPATCH.value:
        turn_state.tool_dispatch_entered = True
    elif phase_value == TurnLifecyclePhase.POST_TOOL_OBSERVATION.value:
        turn_state.tool_observation_completed = True
    elif phase_value == TurnLifecyclePhase.STOP_DECIDED.value:
        turn_state.stop_decision_frozen = True
    elif phase_value == TurnLifecyclePhase.TURN_COMPLETED.value:
        turn_state.turn_completed = True


def note_parse_diagnostics(
    session_state: RuntimeSessionState,
    *,
    recovery_warning_count: int,
    parse_status: str,
    tool_call_count: int,
    assistant_content_present: bool,
) -> None:
    """Record parse-layer diagnostics at the session level."""

    session_state.parse_recovery_warning_count += recovery_warning_count
    if parse_status == "recovered":
        session_state.recovered_parse_turn_count += 1
    if tool_call_count == 0 and not assistant_content_present:
        session_state.empty_turn_no_tool_no_content_count += 1
        _add_failure_bucket(session_state, "empty_turn_no_tool_no_content")
    if parse_status == "fatal":
        session_state.consecutive_parse_failure_turns += 1
    else:
        session_state.consecutive_parse_failure_turns = 0


def note_protocol_or_parse_failure(
    session_state: RuntimeSessionState,
    *,
    failure_kind: str,
    turn_index: int,
) -> None:
    """Record a recent parse/protocol failure window."""

    session_state.recent_failure_kind = failure_kind
    session_state.recent_failure_turn = turn_index
    _add_failure_bucket(session_state, "protocol_malformed_turn")


def note_tool_execution(
    session_state: RuntimeSessionState,
    *,
    canonical_name: str,
    result_ok: bool,
    result_is_error: bool,
    error_type: str | None,
    turn_index: int,
) -> None:
    """Record one non-finish tool execution outcome into session state."""

    if canonical_name == "finish":
        return
    session_state.non_finish_tool_call_count += 1
    if canonical_name not in session_state.distinct_non_finish_tool_names:
        session_state.distinct_non_finish_tool_names.append(canonical_name)
        session_state.distinct_non_finish_tool_names.sort()
    if result_ok and not result_is_error:
        session_state.successful_non_finish_tool_call_count += 1
        if canonical_name in {"write_file", "create_file", "apply_patch"}:
            session_state.saw_mutation_progress = True
        if canonical_name in {"python_run"}:
            session_state.saw_validation_progress = True
        if session_state.recent_failure_kind == "validation_failure":
            session_state.recent_failure_kind = None
            session_state.recent_failure_turn = None
        elif session_state.recent_failure_kind in {
            "parse_error",
            "protocol_error",
            "tool_failure",
        }:
            session_state.recent_failure_kind = None
            session_state.recent_failure_turn = None
        return

    if error_type == "completion_blocked":
        return
    if canonical_name in {"python_run"}:
        session_state.recent_failure_kind = "validation_failure"
    else:
        session_state.recent_failure_kind = "tool_failure"
    session_state.recent_failure_turn = turn_index


def meaningful_progress_observed(session_state: RuntimeSessionState) -> bool:
    """Session-wide progress signal used by stop-policy hooks."""

    return session_state.non_finish_tool_call_count > 0 and (
        session_state.saw_mutation_progress
        or session_state.saw_validation_progress
        or len(session_state.distinct_non_finish_tool_names) > 1
    )


def active_recent_failure_kind(
    session_state: RuntimeSessionState,
    *,
    current_turn: int,
) -> str | None:
    """Return a recent failure kind only while it is still in scope."""

    if (
        session_state.recent_failure_kind is None
        or session_state.recent_failure_turn is None
    ):
        return None
    if current_turn - session_state.recent_failure_turn > 2:
        return None
    return session_state.recent_failure_kind


def sync_pending_issue_record(
    session_state: RuntimeSessionState,
    *,
    turn_index: int,
    resolution_trigger: str,
) -> None:
    """Mirror recovery pending-issue state into formal session records."""

    recovery_state = session_state.recovery_state
    current_kind = _enum_value(getattr(recovery_state, "pending_issue_kind", None))
    current_detail = str(getattr(recovery_state, "pending_issue_detail", "") or "")
    current_issue_id = str(getattr(recovery_state, "active_issue_id", lambda: None)() or "")
    active = session_state.active_pending_issue

    if current_kind is None:
        if active is None:
            return
        cleared_issue = active.model_copy(deep=True)
        cleared_issue.last_observed_turn = turn_index
        cleared_issue.cleared_at_turn = turn_index
        cleared_issue.resolution_trigger = resolution_trigger
        session_state.last_cleared_pending_issue = cleared_issue
        session_state.resolved_pending_issues.append(cleared_issue)
        session_state.active_pending_issue = None
        return

    if active is not None and active.kind == current_kind:
        active.detail = current_detail
        active.last_observed_turn = turn_index
        if current_issue_id:
            active.issue_id = current_issue_id
        return

    if active is not None:
        replaced_issue = active.model_copy(deep=True)
        replaced_issue.last_observed_turn = turn_index
        replaced_issue.cleared_at_turn = turn_index
        replaced_issue.resolution_trigger = "replaced_by_pending_issue"
        session_state.last_cleared_pending_issue = replaced_issue
        session_state.resolved_pending_issues.append(replaced_issue)

    session_state.active_pending_issue = PendingIssueRecord(
        issue_id=current_issue_id or None,
        kind=current_kind,
        detail=current_detail,
        opened_at_turn=turn_index,
        last_observed_turn=turn_index,
    )


def note_stop_decision(
    session_state: RuntimeSessionState,
    *,
    stop_decision: Any,
    turn_index: int,
) -> None:
    """Update session aggregates from one turn-level stop decision."""

    continuation_record = _build_turn_continuation_record(
        session_state,
        stop_decision=stop_decision,
        turn_index=turn_index,
    )
    session_state.last_turn_continuation = continuation_record
    session_state.continuation_ledger.append(continuation_record)
    session_state.last_continue_reason = getattr(stop_decision, "continue_reason", None)
    session_state.finish_blocked_by_policy = bool(
        getattr(stop_decision, "finish_blocked_by_policy", False)
    )
    session_state.blocked_reason = continuation_record.blocked_reason
    if getattr(stop_decision, "finish_attempted", False):
        session_state.finish_attempt_count += 1
    if getattr(stop_decision, "finish_blocked_by_policy", False):
        session_state.finish_blocked_count += 1
        session_state.finish_block_reason = getattr(stop_decision, "finish_block_reason", None)
        session_state.finish_gate_reason = getattr(stop_decision, "finish_gate_reason", None)
        block_reason = getattr(stop_decision, "finish_block_reason", None)
        if block_reason:
            session_state.finish_block_reason_counts[block_reason] = (
                session_state.finish_block_reason_counts.get(block_reason, 0) + 1
            )
            _add_failure_bucket(session_state, block_reason)
        completion_block_family = str(
            getattr(stop_decision, "completion_block_family", "none") or "none"
        )
        if completion_block_family == "pending_issue":
            session_state.blocked_finish_pending_issue_count += 1
        elif completion_block_family == "validation_evidence":
            session_state.blocked_finish_validation_evidence_count += 1
        elif completion_block_family == "progress_gate":
            session_state.blocked_finish_progress_gate_count += 1
    if getattr(stop_decision, "finish_attempted", False) and not bool(
        getattr(stop_decision, "meaningful_progress_observed", False)
    ):
        session_state.finish_without_progress_count += 1
        _add_failure_bucket(session_state, "finish_without_progress")
    if getattr(stop_decision, "finish_attempted", False) and getattr(
        stop_decision, "recent_failure_kind", None
    ) is not None:
        session_state.finish_after_recent_failure_count += 1
        _add_failure_bucket(session_state, "finish_after_recent_failure")

    if getattr(stop_decision, "meaningful_progress_observed", False):
        session_state.consecutive_no_progress_turns = 0
    else:
        session_state.consecutive_no_progress_turns += 1

    if str(getattr(stop_decision, "completion_block_family", "none") or "none") in {
        "pending_issue",
        "progress_gate",
    }:
        if getattr(stop_decision, "active_failure_kind", None) is not None or getattr(
            stop_decision, "pending_issue_kind", None
        ) is not None:
            session_state.unrecovered_failure_turn_count += 1

    _refresh_budget_snapshots(session_state)


def finalize_turn(
    session_state: RuntimeSessionState,
    turn_state: RuntimeTurnState,
) -> None:
    """Append a completed turn into the canonical session history."""

    mark_turn_phase(turn_state, TurnLifecyclePhase.TURN_COMPLETED)
    session_state.turn_states.append(turn_state)
    session_state.total_turns_completed = len(session_state.turn_states)


def finalize_session(
    session_state: RuntimeSessionState,
    *,
    total_turns: int,
    final_status: str | None,
    stop_reason: str,
    stop_detail: str,
    stop_decision_code: str,
) -> None:
    """Freeze final typed session termination facts."""

    session_state.total_turns_completed = max(
        session_state.total_turns_completed,
        total_turns,
    )
    session_state.final_status = final_status
    session_state.stop_reason = stop_reason
    session_state.stop_detail = stop_detail
    session_state.stop_decision_code = stop_decision_code
    session_state.session_termination_kind = _termination_kind_from_stop_reason(
        stop_reason=stop_reason,
        stop_decision_code=stop_decision_code,
    )
    session_state.session_stop_status = _session_stop_status_from_final_status(
        final_status
    )
    _refresh_budget_snapshots(session_state)
    session_state.session_outcome = SessionOutcomeRecord(
        total_turns=session_state.total_turns_completed,
        final_status=session_state.final_status,
        session_stop_status=session_state.session_stop_status,
        session_termination_kind=session_state.session_termination_kind,
        stop_reason=session_state.stop_reason,
        stop_detail=session_state.stop_detail,
        stop_decision_code=session_state.stop_decision_code,
    )


def build_session_metadata(session_state: RuntimeSessionState, *, total_turns: int) -> dict[str, Any]:
    """Render run metadata from the canonical session state."""

    return extract_runtime_session_summary(session_state, total_turns=total_turns)


def extract_runtime_session_summary(
    session_state: RuntimeSessionState,
    *,
    total_turns: int,
) -> dict[str, Any]:
    """Render a stable post-run session summary from typed session state."""

    recovery_state = session_state.recovery_state
    validation_issue = getattr(
        recovery_state,
        "current_or_last_validation_issue",
        lambda: None,
    )()
    decision_kind_counts = _count_nonempty_values(
        turn_state.continuation_decision_kind
        for turn_state in session_state.turn_states
    )
    turn_action_counts = _count_nonempty_values(
        turn_state.turn_action for turn_state in session_state.turn_states
    )
    turn_outcome_counts = _count_nonempty_values(
        turn_state.turn_outcome for turn_state in session_state.turn_states
    )
    return {
        "total_turns": total_turns,
        "final_status": session_state.final_status,
        "session_stop_status": session_state.session_stop_status,
        "session_termination_kind": session_state.session_termination_kind,
        "stop_detail": session_state.stop_detail,
        "stop_reason": session_state.stop_reason,
        "stop_decision_code": session_state.stop_decision_code or "max_turns",
        "parse_errors": getattr(recovery_state, "parse_error_count", 0),
        "parse_recovery_warnings": session_state.parse_recovery_warning_count,
        "recovered_parse_turns": session_state.recovered_parse_turn_count,
        "pending_issue_kind": _enum_value(getattr(recovery_state, "pending_issue_kind", None)),
        "pending_issue_cleared": bool(getattr(recovery_state, "pending_issue_cleared", False)),
        "last_cleared_issue_kind": _enum_value(
            getattr(recovery_state, "last_cleared_issue_kind", None)
        ),
        "completion_evidence_status": _enum_value(
            getattr(recovery_state, "completion_evidence_status", None)
        ),
        "completion_block_family": (
            session_state.last_turn_continuation.completion_block_family
            if session_state.last_turn_continuation is not None
            else "none"
        ),
        "validation_phase": _enum_value(
            getattr(recovery_state, "refresh_validation_phase", lambda: None)()
        ),
        "expected_next_step": _enum_value(
            getattr(recovery_state, "expected_next_step", lambda: None)()
        ),
        "completion_gate_status": _enum_value(
            getattr(recovery_state, "completion_gate_status", lambda: None)()
        ),
        "active_validation_issue_kind": getattr(
            recovery_state,
            "active_validation_issue_kind",
            lambda: None,
        )(),
        "active_validation_issue_id": getattr(
            recovery_state,
            "active_issue_id",
            lambda: None,
        )(),
        "active_failure_kind": getattr(recovery_state, "active_failure_kind", None),
        "active_failure_turn": getattr(recovery_state, "active_failure_turn", None),
        "corrective_progress_after_failure": bool(
            getattr(recovery_state, "corrective_progress_after_failure", False)
        ),
        "post_mutation_validation_pending": bool(
            getattr(recovery_state, "post_mutation_validation_pending", False)
        ),
        "validation_required_for_completion": bool(
            getattr(recovery_state, "validation_required_for_completion", False)
        ),
        "finish_blocked_by_policy": session_state.finish_blocked_by_policy,
        "finish_attempt_count": session_state.finish_attempt_count,
        "finish_blocked_count": session_state.finish_blocked_count,
        "finish_block_reason": session_state.finish_block_reason,
        "finish_gate_reason": session_state.finish_gate_reason,
        "blocked_finish_pending_issue_count": (
            session_state.blocked_finish_pending_issue_count
        ),
        "blocked_finish_validation_evidence_count": (
            session_state.blocked_finish_validation_evidence_count
        ),
        "blocked_finish_progress_gate_count": (
            session_state.blocked_finish_progress_gate_count
        ),
        "finish_block_reason_counts": dict(
            sorted(session_state.finish_block_reason_counts.items())
        ),
        "finish_without_progress_count": session_state.finish_without_progress_count,
        "finish_after_recent_failure_count": session_state.finish_after_recent_failure_count,
        "unrecovered_failure_turn_count": (
            session_state.unrecovered_failure_turn_count
        ),
        "empty_turn_no_tool_no_content_count": (
            session_state.empty_turn_no_tool_no_content_count
        ),
        "meaningful_progress_observed": meaningful_progress_observed(session_state),
        "observed_failure_buckets": sorted(session_state.observed_failure_buckets),
        "last_successful_validation_turn": getattr(
            recovery_state, "last_successful_validation_turn", None
        ),
        "last_validation_attempt_turn": getattr(
            recovery_state, "last_validation_attempt_turn", None
        ),
        "last_validation_failure_turn": getattr(
            recovery_state, "last_validation_failure_turn", None
        ),
        "last_mutation_turn": getattr(recovery_state, "last_mutation_turn", None),
        "validation_failure_count": getattr(recovery_state, "validation_failure_count", 0),
        "validation_attempt_count": (
            validation_issue.validation_attempt_count
            if validation_issue is not None
            else 0
        ),
        "revision_attempt_count": (
            validation_issue.revision_attempt_count
            if validation_issue is not None
            else 0
        ),
        "finish_deferral_count": (
            validation_issue.finish_deferral_count
            if validation_issue is not None
            else 0
        ),
        "validation_budget_remaining": session_state.validation_budget_remaining,
        "revision_budget_remaining": session_state.revision_budget_remaining,
        "finish_deferral_budget_remaining": (
            session_state.finish_deferral_budget_remaining
        ),
        "resolved_pending_issue_count": len(session_state.resolved_pending_issues),
        "continuation_decision_counts": decision_kind_counts,
        "turn_action_counts": turn_action_counts,
        "turn_outcome_counts": turn_outcome_counts,
        "session_outcome": (
            session_state.session_outcome.model_dump(mode="json")
            if session_state.session_outcome is not None
            else None
        ),
        "budget_snapshot": (
            session_state.budget_snapshot.model_dump(mode="json")
            if session_state.budget_snapshot is not None
            else None
        ),
        "last_turn_continuation": (
            session_state.last_turn_continuation.model_dump(mode="json")
            if session_state.last_turn_continuation is not None
            else None
        ),
    }


def _refresh_budget_snapshots(session_state: RuntimeSessionState) -> None:
    issue = getattr(
        session_state.recovery_state,
        "current_or_last_validation_issue",
        lambda: None,
    )()
    if session_state.validation_budget_total is not None:
        used = issue.validation_attempt_count if issue is not None else 0
        session_state.validation_budget_remaining = max(
            session_state.validation_budget_total - used,
            0,
        )
    if session_state.revision_budget_total is not None:
        used = issue.revision_attempt_count if issue is not None else 0
        session_state.revision_budget_remaining = max(
            session_state.revision_budget_total - used,
            0,
        )
    if session_state.finish_deferral_budget_total is not None:
        used = issue.finish_deferral_count if issue is not None else 0
        session_state.finish_deferral_budget_remaining = max(
            session_state.finish_deferral_budget_total - used,
            0,
        )
    session_state.budget_snapshot = _build_budget_snapshot(session_state)


def derive_continuation_decision_kind(stop_decision: Any) -> str:
    """Map one stop decision into the formal continuation taxonomy."""

    if stop_decision.should_stop:
        if stop_decision.decision_code == "finish":
            return ContinuationDecisionKind.STOP_FINISH.value
        if stop_decision.decision_code == "max_turns":
            return ContinuationDecisionKind.STOP_MAX_TURNS.value
        if stop_decision.decision_code == "no_tool_calls":
            return ContinuationDecisionKind.STOP_NO_TOOL_CALLS.value
        if stop_decision.decision_code == "parse_error":
            return ContinuationDecisionKind.STOP_PARSE_ERROR.value
        if stop_decision.decision_code == "llm_error":
            return ContinuationDecisionKind.STOP_LLM_ERROR.value
        if stop_decision.decision_code == "validation_budget_exhausted":
            return ContinuationDecisionKind.STOP_VALIDATION_BUDGET_EXHAUSTED.value
        if stop_decision.decision_code == "revision_budget_exhausted":
            return ContinuationDecisionKind.STOP_REVISION_BUDGET_EXHAUSTED.value
        if stop_decision.decision_code == "finish_deferral_budget_exhausted":
            return ContinuationDecisionKind.STOP_FINISH_DEFERRAL_BUDGET_EXHAUSTED.value
        return f"stop_{stop_decision.decision_code}"
    if stop_decision.finish_blocked_by_policy:
        return ContinuationDecisionKind.CONTINUE_AFTER_BLOCKED_FINISH.value
    if stop_decision.decision_code == "continue_with_tool_calls":
        return ContinuationDecisionKind.CONTINUE_WITH_TOOL_CALLS.value
    return ContinuationDecisionKind.CONTINUE_AFTER_RECOVERABLE_FAILURE.value


def derive_termination_kind(stop_decision: Any) -> str | None:
    """Map a stop decision into the formal session termination taxonomy."""

    if not stop_decision.should_stop:
        return None
    if stop_decision.decision_code == "finish":
        return SessionTerminationKind.COMPLETED.value
    if stop_decision.decision_code == "max_turns":
        return SessionTerminationKind.MAX_TURNS.value
    if stop_decision.decision_code == "no_tool_calls":
        return SessionTerminationKind.NO_TOOL_CALLS.value
    if stop_decision.decision_code == "parse_error":
        return SessionTerminationKind.PARSE_ERROR.value
    if stop_decision.decision_code == "llm_error":
        return SessionTerminationKind.LLM_ERROR.value
    if stop_decision.decision_code == "validation_budget_exhausted":
        return SessionTerminationKind.VALIDATION_BUDGET_EXHAUSTED.value
    if stop_decision.decision_code == "revision_budget_exhausted":
        return SessionTerminationKind.REVISION_BUDGET_EXHAUSTED.value
    if stop_decision.decision_code == "finish_deferral_budget_exhausted":
        return SessionTerminationKind.FINISH_DEFERRAL_BUDGET_EXHAUSTED.value
    return SessionTerminationKind.RUNNING.value


def _build_budget_snapshot(session_state: RuntimeSessionState) -> SessionBudgetSnapshot:
    issue = getattr(
        session_state.recovery_state,
        "current_or_last_validation_issue",
        lambda: None,
    )()
    return SessionBudgetSnapshot(
        validation_budget_total=session_state.validation_budget_total,
        validation_budget_remaining=session_state.validation_budget_remaining,
        validation_budget_used=(
            issue.validation_attempt_count if issue is not None else 0
        ),
        revision_budget_total=session_state.revision_budget_total,
        revision_budget_remaining=session_state.revision_budget_remaining,
        revision_budget_used=(
            issue.revision_attempt_count if issue is not None else 0
        ),
        finish_deferral_budget_total=session_state.finish_deferral_budget_total,
        finish_deferral_budget_remaining=session_state.finish_deferral_budget_remaining,
        finish_deferral_budget_used=(
            issue.finish_deferral_count if issue is not None else 0
        ),
    )


def _build_turn_continuation_record(
    session_state: RuntimeSessionState,
    *,
    stop_decision: Any,
    turn_index: int,
) -> TurnContinuationRecord:
    return TurnContinuationRecord(
        turn_index=turn_index,
        decision_code=str(getattr(stop_decision, "decision_code", "") or ""),
        continuation_decision_kind=derive_continuation_decision_kind(stop_decision),
        termination_kind=derive_termination_kind(stop_decision),
        continue_reason=getattr(stop_decision, "continue_reason", None),
        blocked_reason=getattr(stop_decision, "finish_block_reason", None),
        pending_issue_id=(
            session_state.active_pending_issue.issue_id
            if session_state.active_pending_issue is not None
            else None
        ),
        pending_issue_kind=getattr(stop_decision, "pending_issue_kind", None),
        active_validation_issue_id=getattr(stop_decision, "active_validation_issue_id", None),
        active_validation_issue_kind=getattr(
            stop_decision, "active_validation_issue_kind", None
        ),
        completion_block_family=getattr(
            stop_decision, "completion_block_family", None
        ),
        completion_gate_status=getattr(stop_decision, "completion_gate_status", None),
        expected_next_step=getattr(stop_decision, "expected_next_step", None),
        completion_evidence_status=getattr(
            stop_decision, "completion_evidence_status", None
        ),
        validation_phase=getattr(stop_decision, "validation_phase", None),
        meaningful_progress_observed=bool(
            getattr(stop_decision, "meaningful_progress_observed", False)
        ),
        recent_failure_kind=getattr(stop_decision, "recent_failure_kind", None),
        active_failure_kind=getattr(stop_decision, "active_failure_kind", None),
        corrective_progress_after_failure=bool(
            getattr(stop_decision, "corrective_progress_after_failure", False)
        ),
        post_mutation_validation_pending=bool(
            getattr(stop_decision, "post_mutation_validation_pending", False)
        ),
        finish_blocked_by_policy=bool(
            getattr(stop_decision, "finish_blocked_by_policy", False)
        ),
        finish_gate_reason=getattr(stop_decision, "finish_gate_reason", None),
        completion_allowed=bool(getattr(stop_decision, "completion_allowed", True)),
        model_needs_follow_up=bool(
            getattr(stop_decision, "model_needs_follow_up", False)
        ),
        runtime_needs_follow_up=bool(
            getattr(stop_decision, "runtime_needs_follow_up", False)
        ),
        stop_hook_evaluated=bool(
            getattr(stop_decision, "stop_hook_evaluated", False)
        ),
        stop_hook_blocked=bool(
            getattr(stop_decision, "stop_hook_blocked", False)
        ),
        stop_hook_reason=getattr(stop_decision, "stop_hook_reason", None),
        stop_hook_reason_code=str(
            getattr(stop_decision, "stop_hook_reason_code", "none") or "none"
        ),
        policy_mode=getattr(stop_decision, "policy_mode", None),
    )


def _count_nonempty_values(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
    return dict(sorted(counts.items()))


def _termination_kind_from_stop_reason(
    *,
    stop_reason: str,
    stop_decision_code: str,
) -> str:
    if stop_reason == "finish":
        return SessionTerminationKind.COMPLETED.value
    if stop_reason == "max_turns":
        return SessionTerminationKind.MAX_TURNS.value
    if stop_reason == "no_tool_calls":
        return SessionTerminationKind.NO_TOOL_CALLS.value
    if stop_reason == "parse_error":
        return SessionTerminationKind.PARSE_ERROR.value
    if stop_reason == "llm_error":
        return SessionTerminationKind.LLM_ERROR.value
    if stop_reason == "validation_budget_exhausted":
        return SessionTerminationKind.VALIDATION_BUDGET_EXHAUSTED.value
    if stop_reason == "revision_budget_exhausted":
        return SessionTerminationKind.REVISION_BUDGET_EXHAUSTED.value
    if stop_reason == "finish_deferral_budget_exhausted":
        return SessionTerminationKind.FINISH_DEFERRAL_BUDGET_EXHAUSTED.value
    if stop_decision_code == "llm_error":
        return SessionTerminationKind.LLM_ERROR.value
    return SessionTerminationKind.RUNNING.value


def _session_stop_status_from_final_status(final_status: str | None) -> str:
    if final_status == "completed":
        return SessionStopStatus.COMPLETED.value
    if final_status == "error":
        return SessionStopStatus.ERROR.value
    if final_status:
        return SessionStopStatus.FAILED.value
    return SessionStopStatus.RUNNING.value


def _add_failure_bucket(session_state: RuntimeSessionState, bucket: str) -> None:
    if bucket not in session_state.observed_failure_buckets:
        session_state.observed_failure_buckets.append(bucket)
        session_state.observed_failure_buckets.sort()


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "value", str(value))


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
    """Select request-visible messages under an explicit context policy."""

    from pycodeagent.agent.compaction import (
        select_request_messages as _select_request_messages_runtime,
    )

    return _select_request_messages_runtime(
        messages,
        policy_mode=policy_mode,
        max_messages=max_messages,
        session_state=session_state,
        turn_index=turn_index,
        context_max_tokens=context_max_tokens,
        tool_token_reserve=tool_token_reserve,
        response_token_reserve=response_token_reserve,
    )


def _normalize_policy_mode(policy_mode: ContextPolicyMode | str) -> ContextPolicyMode:
    if isinstance(policy_mode, ContextPolicyMode):
        return policy_mode
    return ContextPolicyMode(str(policy_mode))


def estimate_message_tokens(message: Message) -> int:
    """Deterministic provider-agnostic token estimate for one request message."""

    parts = [message.role.value, message.content or ""]
    if message.tool_calls:
        parts.append(
            json.dumps(
                [tool_call.model_dump(mode="json") for tool_call in message.tool_calls],
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    if message.tool_call_id:
        parts.append(str(message.tool_call_id))
    if message.tool_name:
        parts.append(str(message.tool_name))
    return max(1, math.ceil(len(" ".join(parts).encode("utf-8")) / 4))


def estimate_messages_tokens(messages: list[Message]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


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
            trigger_message_overflow=(
                max_messages is not None and len(messages) > max_messages
            ),
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
    before_message_overflow = (
        max_messages is not None and len(messages) > max_messages
    )
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
                    None
                    if all_messages_fit
                    else "missing_session_state_or_turn_index"
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
        carried_forward_state = _build_carried_forward_state(
            session_state,
            compacted_ranges,
        )
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
                candidate_turn_indices=[
                    candidate.turn_index for candidate in candidate_ranges
                ],
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
            candidate_turn_indices=[
                candidate.turn_index for candidate in candidate_ranges
            ],
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
    total = estimate_messages_tokens(messages) + tool_token_reserve + response_token_reserve
    return max(total - context_max_tokens, 0)
