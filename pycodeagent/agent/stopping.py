"""Stopping conditions for the agent loop."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from pycodeagent.agent.recovery import (
    CompletionBlockFamily,
    ContinueReason,
    RuntimeRecoveryState,
    StopPolicyInputSnapshot,
    StopDecisionCode,
    assess_completion_block,
    continue_reason_for_turn,
    derive_stop_policy_input_snapshot,
    ensure_validation_issue_for_completion_block,
    parse_error_is_recoverable,
    stop_hook_reason_code_for_block_reason,
    validation_budget_exhaustion,
)
from pycodeagent.trajectory.schema import ToolCall


class StopReason(str, Enum):
    """Why the agent stopped."""

    FINISH = "finish"
    NO_TOOL_CALLS = "no_tool_calls"
    MAX_TURNS = "max_turns"
    PARSE_ERROR = "parse_error"
    VALIDATION_BUDGET_EXHAUSTED = "validation_budget_exhausted"
    REVISION_BUDGET_EXHAUSTED = "revision_budget_exhausted"
    FINISH_DEFERRAL_BUDGET_EXHAUSTED = "finish_deferral_budget_exhausted"


class StopPolicyMode(str, Enum):
    """Formal policy mode for the native-tools runtime stop hook."""

    NATIVE_TOOLS_LIGHT_STOP_HOOK = "native_tools_light_stop_hook"


class TurnPolicyFacts(BaseModel):
    """Typed end-of-turn facts consumed by the lightweight stop hook."""

    model_config = ConfigDict(protected_namespaces=())

    policy_mode: str = StopPolicyMode.NATIVE_TOOLS_LIGHT_STOP_HOOK.value
    model_needs_follow_up: bool = False
    runtime_needs_follow_up: bool = False
    finish_attempted: bool = False
    assistant_content_present: bool = False
    tool_call_count: int = 0
    pending_issue_kind: str | None = None
    active_validation_issue_kind: str | None = None
    completion_evidence_status: str | None = None
    completion_block_family: str = CompletionBlockFamily.NONE.value
    validation_phase: str | None = None
    recent_failure_kind: str | None = None
    meaningful_progress_observed: bool = False
    max_turn_reached: bool = False
    parse_error_present: bool = False
    llm_error_present: bool = False
    stop_hook_evaluated: bool = False
    stop_hook_blocked: bool = False
    stop_hook_reason: str | None = None
    stop_hook_reason_code: str = "none"


class StopDecision(BaseModel):
    """Decision about whether to stop the agent loop."""

    model_config = ConfigDict(protected_namespaces=())

    should_stop: bool
    reason: StopReason | None = None
    detail: str = ""
    decision_code: str = StopDecisionCode.CONTINUE_WITH_TOOL_CALLS.value
    continue_reason: str | None = None
    pending_issue_kind: str | None = None
    active_validation_issue_kind: str | None = None
    validation_attempt_count: int | None = None
    revision_attempt_count: int | None = None
    finish_deferral_count: int | None = None
    completion_evidence_status: str | None = None
    completion_block_family: str = CompletionBlockFamily.NONE.value
    validation_phase: str | None = None
    expected_next_step: str | None = None
    completion_gate_status: str | None = None
    active_validation_issue_id: str | None = None
    finish_blocked_by_policy: bool = False
    finish_block_reason: str | None = None
    finish_attempted: bool = False
    meaningful_progress_observed: bool = False
    recent_failure_kind: str | None = None
    completion_allowed: bool = True
    validation_evidence_fresh: bool = False
    active_failure_kind: str | None = None
    corrective_progress_after_failure: bool = False
    post_mutation_validation_pending: bool = False
    finish_gate_reason: str | None = None
    last_successful_validation_turn: int | None = None
    last_validation_attempt_turn: int | None = None
    last_validation_failure_turn: int | None = None
    last_mutation_turn: int | None = None
    policy_mode: str = StopPolicyMode.NATIVE_TOOLS_LIGHT_STOP_HOOK.value
    model_needs_follow_up: bool = False
    runtime_needs_follow_up: bool = False
    stop_hook_evaluated: bool = False
    stop_hook_blocked: bool = False
    stop_hook_reason: str | None = None
    stop_hook_reason_code: str = "none"


def check_finish_tool_called(tool_calls: list[ToolCall]) -> bool:
    return any((call.canonical_name or call.name) == "finish" for call in tool_calls)


def check_non_finish_tool_calls(tool_calls: list[ToolCall]) -> bool:
    return any((call.canonical_name or call.name) != "finish" for call in tool_calls)


def derive_turn_policy_facts(
    *,
    tool_calls: list[ToolCall],
    parse_errors: list[str],
    current_turn: int,
    max_turns: int,
    assistant_content: str,
    recovery_state: RuntimeRecoveryState,
    policy_input: StopPolicyInputSnapshot,
) -> TurnPolicyFacts:
    finish_called = check_finish_tool_called(tool_calls)
    assistant_content_present = bool(assistant_content.strip())
    implicit_finish_attempt = not tool_calls and assistant_content_present
    return TurnPolicyFacts(
        model_needs_follow_up=check_non_finish_tool_calls(tool_calls),
        runtime_needs_follow_up=False,
        finish_attempted=finish_called or implicit_finish_attempt,
        assistant_content_present=assistant_content_present,
        tool_call_count=len(tool_calls),
        pending_issue_kind=(
            recovery_state.pending_issue_kind.value
            if recovery_state.pending_issue_kind is not None
            else None
        ),
        active_validation_issue_kind=recovery_state.active_validation_issue_kind(),
        completion_evidence_status=recovery_state.refresh_completion_evidence_status().value,
        completion_block_family=policy_input.completion_block_family_hint.value,
        validation_phase=recovery_state.refresh_validation_phase().value,
        recent_failure_kind=policy_input.recent_failure_kind,
        meaningful_progress_observed=policy_input.meaningful_progress_observed,
        max_turn_reached=current_turn >= max_turns,
        parse_error_present=bool(parse_errors),
        llm_error_present=False,
    )


def should_stop(
    tool_calls: list[ToolCall],
    parse_errors: list[str],
    current_turn: int,
    max_turns: int,
    assistant_content: str = "",
    recovery_state: RuntimeRecoveryState | None = None,
    policy_input: StopPolicyInputSnapshot | None = None,
) -> StopDecision:
    recovery_state = recovery_state or RuntimeRecoveryState()
    policy_input = policy_input or derive_stop_policy_input_snapshot(
        object(),
        recovery_state,
        current_turn=current_turn,
    )
    finish_called = check_finish_tool_called(tool_calls)
    policy_facts = derive_turn_policy_facts(
        tool_calls=tool_calls,
        parse_errors=parse_errors,
        current_turn=current_turn,
        max_turns=max_turns,
        assistant_content=assistant_content,
        recovery_state=recovery_state,
        policy_input=policy_input,
    )

    budget_stop = validation_budget_exhaustion(recovery_state)
    if budget_stop is not None:
        decision_code, detail = budget_stop
        return _stop_decision_from_state(
            recovery_state,
            should_stop=True,
            reason=_stop_reason_for_budget(decision_code),
            detail=detail,
            decision_code=decision_code.value,
            policy_facts=policy_facts,
        )

    if policy_facts.max_turn_reached:
        return _stop_decision_from_state(
            recovery_state,
            should_stop=True,
            reason=StopReason.MAX_TURNS,
            detail=f"Reached max_turns={max_turns}",
            decision_code=StopDecisionCode.MAX_TURNS.value,
            policy_facts=policy_facts,
        )

    if parse_errors and not tool_calls:
        if parse_error_is_recoverable(recovery_state):
            policy_facts.runtime_needs_follow_up = True
            return _stop_decision_from_state(
                recovery_state,
                should_stop=False,
                reason=None,
                detail=f"Recoverable parse errors: {parse_errors}",
                decision_code=StopDecisionCode.RECOVERABLE_PARSE_ERROR.value,
                continue_reason=ContinueReason.RECOVERABLE_PARSE_ERROR.value,
                policy_facts=policy_facts,
            )
        return _stop_decision_from_state(
            recovery_state,
            should_stop=True,
            reason=StopReason.PARSE_ERROR,
            detail=f"Parse errors: {parse_errors}",
            decision_code=StopDecisionCode.PARSE_ERROR.value,
            policy_facts=policy_facts,
        )

    if policy_facts.model_needs_follow_up:
        continue_reason = continue_reason_for_turn(
            recovery_state,
            tool_calls_present=bool(tool_calls),
            parse_errors=parse_errors,
            completion_blocked=False,
        )
        return _stop_decision_from_state(
            recovery_state,
            should_stop=False,
            reason=None,
            detail="",
            decision_code=StopDecisionCode.CONTINUE_WITH_TOOL_CALLS.value,
            continue_reason=continue_reason.value if continue_reason is not None else None,
            policy_facts=policy_facts,
        )

    completion_block_assessment = assess_completion_block(
        recovery_state,
        meaningful_progress_observed=policy_input.meaningful_progress_observed,
        progress_gate_applicable=policy_input.progress_gate_applicable,
        recent_failure_kind=policy_input.recent_failure_kind,
    )
    completion_blocked_detail = completion_block_assessment.detail if completion_block_assessment.blocked else None
    policy_facts.completion_block_family = (
        completion_block_assessment.completion_block_family.value
    )
    if policy_facts.finish_attempted or not tool_calls:
        policy_facts.stop_hook_evaluated = True

    if finish_called:
        if completion_blocked_detail:
            policy_facts.runtime_needs_follow_up = True
            policy_facts.stop_hook_blocked = True
            policy_facts.stop_hook_reason = completion_block_assessment.block_reason
            policy_facts.stop_hook_reason_code = stop_hook_reason_code_for_block_reason(
                completion_block_assessment.block_reason
            )
            ensure_validation_issue_for_completion_block(
                recovery_state,
                turn_index=current_turn,
            )
            recovery_state.note_finish_deferral(turn_index=current_turn)
            budget_stop = validation_budget_exhaustion(recovery_state)
            if budget_stop is not None:
                decision_code, detail = budget_stop
                return _stop_decision_from_state(
                    recovery_state,
                    should_stop=True,
                    reason=_stop_reason_for_budget(decision_code),
                    detail=detail,
                    decision_code=decision_code.value,
                    policy_facts=policy_facts,
                )

            if completion_block_assessment.block_reason in {
                "recent_recoverable_failure",
                "unresolved_validation_failure",
                "no_corrective_progress_after_failure",
                "no_meaningful_progress",
            }:
                decision_code = StopDecisionCode.DEFER_FINISH_PENDING_ISSUE.value
                continue_reason = ContinueReason.DEFER_COMPLETION_PENDING_ISSUE.value
            else:
                decision_code = (
                    StopDecisionCode.DEFER_FINISH_MISSING_COMPLETION_EVIDENCE.value
                )
                continue_reason = (
                    ContinueReason.DEFER_COMPLETION_MISSING_COMPLETION_EVIDENCE.value
                )
            return _stop_decision_from_state(
                recovery_state,
                should_stop=False,
                reason=None,
                detail=completion_blocked_detail,
                decision_code=decision_code,
                continue_reason=continue_reason,
                finish_blocked_by_policy=True,
                finish_block_reason=completion_block_assessment.block_reason,
                expected_next_step_override=(
                    completion_block_assessment.expected_next_step.value
                    if completion_block_assessment.expected_next_step is not None
                    else None
                ),
                completion_block_assessment=completion_block_assessment,
                policy_facts=policy_facts,
            )
        return _stop_decision_from_state(
            recovery_state,
            should_stop=True,
            reason=StopReason.FINISH,
            detail="Agent called finish tool",
            decision_code=StopDecisionCode.FINISH.value,
            policy_facts=policy_facts,
        )

    if not tool_calls:
        if completion_blocked_detail:
            policy_facts.runtime_needs_follow_up = True
            policy_facts.stop_hook_blocked = True
            policy_facts.stop_hook_reason = completion_block_assessment.block_reason
            policy_facts.stop_hook_reason_code = stop_hook_reason_code_for_block_reason(
                completion_block_assessment.block_reason
            )
            ensure_validation_issue_for_completion_block(
                recovery_state,
                turn_index=current_turn,
            )
            recovery_state.note_finish_deferral(turn_index=current_turn)
            budget_stop = validation_budget_exhaustion(recovery_state)
            if budget_stop is not None:
                decision_code, detail = budget_stop
                return _stop_decision_from_state(
                    recovery_state,
                    should_stop=True,
                    reason=_stop_reason_for_budget(decision_code),
                    detail=detail,
                    decision_code=decision_code.value,
                    policy_facts=policy_facts,
                )

            if completion_block_assessment.block_reason in {
                "recent_recoverable_failure",
                "unresolved_validation_failure",
                "no_corrective_progress_after_failure",
                "no_meaningful_progress",
            }:
                decision_code = StopDecisionCode.DEFER_NO_TOOL_CALLS_PENDING_ISSUE.value
                continue_reason = ContinueReason.DEFER_COMPLETION_PENDING_ISSUE.value
            else:
                decision_code = (
                    StopDecisionCode.DEFER_NO_TOOL_CALLS_MISSING_COMPLETION_EVIDENCE.value
                )
                continue_reason = (
                    ContinueReason.DEFER_COMPLETION_MISSING_COMPLETION_EVIDENCE.value
                )
            return _stop_decision_from_state(
                recovery_state,
                should_stop=False,
                reason=None,
                detail=completion_blocked_detail,
                decision_code=decision_code,
                continue_reason=continue_reason,
                finish_blocked_by_policy=True,
                finish_block_reason=completion_block_assessment.block_reason,
                expected_next_step_override=(
                    completion_block_assessment.expected_next_step.value
                    if completion_block_assessment.expected_next_step is not None
                    else None
                ),
                completion_block_assessment=completion_block_assessment,
                policy_facts=policy_facts,
            )
        return _stop_decision_from_state(
            recovery_state,
            should_stop=True,
            reason=StopReason.NO_TOOL_CALLS,
            detail=(
                "Agent provided final answer without tool calls"
                if assistant_content.strip()
                else "Assistant produced no tool calls"
            ),
            decision_code=StopDecisionCode.NO_TOOL_CALLS.value,
            policy_facts=policy_facts,
        )


def _stop_decision_from_state(
    recovery_state: RuntimeRecoveryState,
    *,
    should_stop: bool,
    reason: StopReason | None,
    detail: str,
    decision_code: str,
    policy_facts: TurnPolicyFacts,
    continue_reason: str | None = None,
    finish_blocked_by_policy: bool = False,
    finish_block_reason: str | None = None,
    expected_next_step_override: str | None = None,
    completion_block_assessment=None,
) -> StopDecision:
    issue = recovery_state.current_or_last_validation_issue()
    expected_next_step = (
        expected_next_step_override
        if expected_next_step_override is not None
        else recovery_state.expected_next_step().value
    )
    completion_gate_status = recovery_state.completion_gate_status().value
    active_failure_kind = recovery_state.active_failure_kind
    corrective_progress_after_failure = recovery_state.corrective_progress_after_failure
    post_mutation_validation_pending = recovery_state.post_mutation_validation_pending
    validation_evidence_fresh = recovery_state.validation_evidence_fresh()
    completion_allowed = True
    finish_gate_reason = None
    if completion_block_assessment is not None:
        active_failure_kind = completion_block_assessment.active_failure_kind
        corrective_progress_after_failure = (
            completion_block_assessment.corrective_progress_after_failure
        )
        post_mutation_validation_pending = (
            completion_block_assessment.post_mutation_validation_pending
        )
        validation_evidence_fresh = (
            completion_block_assessment.validation_evidence_fresh
        )
        completion_allowed = completion_block_assessment.completion_allowed
        finish_gate_reason = completion_block_assessment.block_reason
    elif finish_blocked_by_policy:
        completion_allowed = False
        finish_gate_reason = finish_block_reason
    return StopDecision(
        should_stop=should_stop,
        reason=reason,
        detail=detail,
        decision_code=decision_code,
        continue_reason=continue_reason,
        pending_issue_kind=(
            recovery_state.pending_issue_kind.value
            if recovery_state.pending_issue_kind is not None
            else None
        ),
        active_validation_issue_kind=(
            issue.kind.value if issue is not None else None
        ),
        validation_attempt_count=(
            issue.validation_attempt_count if issue is not None else None
        ),
        revision_attempt_count=(
            issue.revision_attempt_count if issue is not None else None
        ),
        finish_deferral_count=(
            issue.finish_deferral_count if issue is not None else None
        ),
        completion_evidence_status=policy_facts.completion_evidence_status,
        completion_block_family=policy_facts.completion_block_family,
        validation_phase=policy_facts.validation_phase,
        expected_next_step=expected_next_step,
        completion_gate_status=completion_gate_status,
        active_validation_issue_id=recovery_state.active_issue_id(),
        finish_blocked_by_policy=finish_blocked_by_policy,
        finish_block_reason=finish_block_reason,
        finish_attempted=policy_facts.finish_attempted,
        meaningful_progress_observed=policy_facts.meaningful_progress_observed,
        recent_failure_kind=policy_facts.recent_failure_kind,
        completion_allowed=completion_allowed,
        validation_evidence_fresh=validation_evidence_fresh,
        active_failure_kind=active_failure_kind,
        corrective_progress_after_failure=corrective_progress_after_failure,
        post_mutation_validation_pending=post_mutation_validation_pending,
        finish_gate_reason=finish_gate_reason,
        last_successful_validation_turn=recovery_state.last_successful_validation_turn,
        last_validation_attempt_turn=recovery_state.last_validation_attempt_turn,
        last_validation_failure_turn=recovery_state.last_validation_failure_turn,
        last_mutation_turn=recovery_state.last_mutation_turn,
        policy_mode=policy_facts.policy_mode,
        model_needs_follow_up=policy_facts.model_needs_follow_up,
        runtime_needs_follow_up=policy_facts.runtime_needs_follow_up,
        stop_hook_evaluated=policy_facts.stop_hook_evaluated,
        stop_hook_blocked=policy_facts.stop_hook_blocked,
        stop_hook_reason=policy_facts.stop_hook_reason,
        stop_hook_reason_code=policy_facts.stop_hook_reason_code,
    )


def _stop_reason_for_budget(decision_code: StopDecisionCode) -> StopReason:
    if decision_code == StopDecisionCode.VALIDATION_BUDGET_EXHAUSTED:
        return StopReason.VALIDATION_BUDGET_EXHAUSTED
    if decision_code == StopDecisionCode.REVISION_BUDGET_EXHAUSTED:
        return StopReason.REVISION_BUDGET_EXHAUSTED
    return StopReason.FINISH_DEFERRAL_BUDGET_EXHAUSTED
