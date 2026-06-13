"""Runtime recovery and validation policy for the local native-tools agent loop.

This module centralizes the rules for:
- when a parse/tool failure is recoverable
- what pending issue should block completion
- how validation issues are tracked across turns
- how retry/revise budgets are enforced
- how continuation reasons and turn taxonomy are classified
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pycodeagent.agent.parser import ParseResult
from pycodeagent.trajectory.schema import ToolCall, ToolResult

_VALIDATION_TOOLS = {"python_run"}
_MUTATION_TOOLS = {"write_file", "create_file", "apply_patch"}
_RECOVERABLE_RUNTIME_ERROR_TYPES = {
    "unknown_tool",
    "schema_validation",
    "argument_mapping",
    "argument_mapping_unexpected",
    "execution",
    "timeout",
    "invalid_query",
    "empty_diff",
    "invalid_line_range",
    "patch_apply",
    "patch_unexpected",
    "invalid_module",
    "invalid_target",
    "already_exists",
    "not_found",
}
_RECOVERABLE_RUNTIME_STAGES = {
    "resolve_exposed_call",
    "validate_exposed_arguments",
    "map_arguments",
}
_MAX_CONSECUTIVE_PARSE_ERROR_TURNS = 2


class PendingIssueKind(str, Enum):
    PARSE_ERROR = "parse_error"
    TOOL_FAILURE = "tool_failure"
    VALIDATION_FAILURE = "validation_failure"


class ContinueReason(str, Enum):
    TOOL_CALLS_PRESENT = "tool_calls_present"
    RECOVERABLE_PARSE_ERROR = "recoverable_parse_error"
    RECOVERABLE_TOOL_FAILURE = "recoverable_tool_failure"
    RECOVERABLE_VALIDATION_FAILURE = "recoverable_validation_failure"
    AWAITING_REVISION_AFTER_VALIDATION_FAILURE = (
        "awaiting_revision_after_validation_failure"
    )
    AWAITING_REVALIDATION_AFTER_REVISION = (
        "awaiting_revalidation_after_revision"
    )
    DEFER_COMPLETION_PENDING_ISSUE = "defer_completion_pending_issue"
    DEFER_COMPLETION_MISSING_COMPLETION_EVIDENCE = (
        "defer_completion_missing_completion_evidence"
    )


class ExpectedNextStep(str, Enum):
    NONE = "none"
    VALIDATE = "validate"
    REVISE = "revise"
    REVALIDATE = "revalidate"
    RETRY_PARSE_OR_TOOL = "retry_parse_or_tool"
    FINISH_ALLOWED = "finish_allowed"


class CompletionGateStatus(str, Enum):
    OPEN = "open"
    BLOCKED_MISSING_VALIDATION = "blocked_missing_validation"
    BLOCKED_PENDING_ISSUE = "blocked_pending_issue"


class CompletionBlockFamily(str, Enum):
    NONE = "none"
    PENDING_ISSUE = "pending_issue"
    VALIDATION_EVIDENCE = "validation_evidence"
    PROGRESS_GATE = "progress_gate"


class ValidationPhase(str, Enum):
    IDLE = "idle"
    MUTATED_UNVALIDATED = "mutated_unvalidated"
    VALIDATION_FAILED = "validation_failed"
    VALIDATED = "validated"


class ValidationIssueKind(str, Enum):
    VALIDATION_COMMAND_FAILED = "validation_command_failed"
    VALIDATION_COMMAND_NONZERO_EXIT = "validation_command_nonzero_exit"
    VALIDATION_TIMEOUT = "validation_timeout"
    STALE_VALIDATION_EVIDENCE = "stale_validation_evidence"
    FINISH_WITHOUT_REQUIRED_VALIDATION = "finish_without_required_validation"


class TurnAction(str, Enum):
    NONE = "none"
    INSPECT = "inspect"
    MUTATE = "mutate"
    VALIDATE = "validate"
    REVISE = "revise"
    REVALIDATE = "revalidate"
    REVISION_AND_REVALIDATION = "revision_and_revalidation"
    FINISH_ATTEMPT = "finish_attempt"
    FINISH_BLOCKED = "finish_blocked"
    MIXED = "mixed"


class TurnOutcome(str, Enum):
    NONE = "none"
    AWAITING_VALIDATION = "awaiting_validation"
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_FAILED = "validation_failed"
    VALIDATION_RETRY_SCHEDULED = "validation_retry_scheduled"
    REVISION_REQUIRED = "revision_required"
    REVISION_APPLIED = "revision_applied"
    FINISH_DEFERRED = "finish_deferred"
    FINISH_BLOCKED_BY_VALIDATION = "finish_blocked_by_validation"
    FINISH_ACCEPTED = "finish_accepted"
    VALIDATION_BUDGET_EXHAUSTED = "validation_budget_exhausted"
    REVISION_BUDGET_EXHAUSTED = "revision_budget_exhausted"
    FINISH_DEFERRAL_BUDGET_EXHAUSTED = "finish_deferral_budget_exhausted"


class StopDecisionCode(str, Enum):
    FINISH = "finish"
    NO_TOOL_CALLS = "no_tool_calls"
    MAX_TURNS = "max_turns"
    PARSE_ERROR = "parse_error"
    LLM_ERROR = "llm_error"
    CONTINUE_WITH_TOOL_CALLS = "continue_with_tool_calls"
    RECOVERABLE_PARSE_ERROR = "recoverable_parse_error"
    DEFER_FINISH_PENDING_ISSUE = "defer_finish_pending_issue"
    DEFER_NO_TOOL_CALLS_PENDING_ISSUE = "defer_no_tool_calls_pending_issue"
    DEFER_FINISH_MISSING_COMPLETION_EVIDENCE = (
        "defer_finish_missing_completion_evidence"
    )
    DEFER_NO_TOOL_CALLS_MISSING_COMPLETION_EVIDENCE = (
        "defer_no_tool_calls_missing_completion_evidence"
    )
    VALIDATION_BUDGET_EXHAUSTED = "validation_budget_exhausted"
    REVISION_BUDGET_EXHAUSTED = "revision_budget_exhausted"
    FINISH_DEFERRAL_BUDGET_EXHAUSTED = "finish_deferral_budget_exhausted"


class CompletionEvidenceStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    MISSING = "missing"
    STALE = "stale"
    VALIDATED = "validated"


@dataclass(frozen=True)
class RecoveryUpdate:
    recoverable: bool
    pending_issue_kind: PendingIssueKind | None = None
    pending_issue_detail: str = ""
    continue_reason: ContinueReason | None = None
    pending_issue_cleared: bool = False


@dataclass(frozen=True)
class CompletionBlockAssessment:
    blocked: bool
    completion_block_family: CompletionBlockFamily = CompletionBlockFamily.NONE
    block_reason: str | None = None
    detail: str = ""
    expected_next_step: ExpectedNextStep | None = None
    recent_failure_kind: str | None = None
    active_failure_kind: str | None = None
    corrective_progress_after_failure: bool = False
    post_mutation_validation_pending: bool = False
    validation_evidence_fresh: bool = False
    completion_allowed: bool = True


@dataclass(frozen=True)
class ValidationPolicyConfig:
    max_validation_attempts_per_issue: int = 2
    max_revision_attempts_per_issue: int = 2
    max_finish_deferrals_per_issue: int = 2
    require_successful_validation_after_mutation: bool = True


@dataclass(frozen=True)
class StopPolicyInputSnapshot:
    meaningful_progress_observed: bool
    progress_gate_applicable: bool
    recent_failure_kind: str | None
    validation_required_for_completion: bool
    completion_block_family_hint: CompletionBlockFamily = CompletionBlockFamily.NONE


@dataclass
class ValidationIssueRecord:
    issue_id: str
    kind: ValidationIssueKind
    detail: str
    opened_at_turn: int
    last_observed_turn: int
    last_failure_tool_name: str | None = None
    last_failure_tool_call_id: str | None = None
    validation_attempt_count: int = 0
    revision_attempt_count: int = 0
    finish_deferral_count: int = 0
    resolved_at_turn: int | None = None
    resolution_reason: str | None = None


@dataclass
class RuntimeRecoveryState:
    parse_error_count: int = 0
    consecutive_parse_error_turns: int = 0
    pending_issue_kind: PendingIssueKind | None = None
    pending_issue_detail: str = ""
    pending_issue_cleared: bool = False
    last_cleared_issue_kind: PendingIssueKind | None = None
    requires_validation_evidence: bool = False
    completion_evidence_status: CompletionEvidenceStatus = (
        CompletionEvidenceStatus.NOT_REQUIRED
    )
    validation_phase: ValidationPhase = ValidationPhase.IDLE
    last_successful_validation_turn: int | None = None
    last_validation_attempt_turn: int | None = None
    last_validation_failure_turn: int | None = None
    last_mutation_turn: int | None = None
    validation_failure_count: int = 0
    active_validation_issue: ValidationIssueRecord | None = None
    last_resolved_validation_issue: ValidationIssueRecord | None = None
    validation_policy_config: ValidationPolicyConfig = field(
        default_factory=ValidationPolicyConfig
    )
    last_revision_attempt_turn: int | None = None
    last_finish_deferral_turn: int | None = None
    active_failure_kind: str | None = None
    active_failure_turn: int | None = None
    corrective_progress_after_failure: bool = False
    post_mutation_validation_pending: bool = False
    validation_required_for_completion: bool = False
    finish_gate_reason: str | None = None

    def __post_init__(self) -> None:
        self.validation_required_for_completion = self.requires_validation_evidence
        self.refresh_validation_phase()

    @property
    def has_pending_issue(self) -> bool:
        return self.pending_issue_kind is not None

    def clear_pending_issue(self) -> bool:
        if self.pending_issue_kind is None:
            return False
        self.last_cleared_issue_kind = self.pending_issue_kind
        self.pending_issue_kind = None
        self.pending_issue_detail = ""
        self.pending_issue_cleared = True
        return True

    def set_pending_issue(self, kind: PendingIssueKind, detail: str) -> None:
        self.pending_issue_kind = kind
        self.pending_issue_detail = detail

    def active_validation_issue_kind(self) -> str | None:
        if self.active_validation_issue is None:
            return None
        return self.active_validation_issue.kind.value

    def active_issue_id(self) -> str | None:
        if self.active_validation_issue is None:
            return None
        return self.active_validation_issue.issue_id

    def current_or_last_validation_issue(self) -> ValidationIssueRecord | None:
        if self.active_validation_issue is not None:
            return self.active_validation_issue
        return self.last_resolved_validation_issue

    def refresh_completion_evidence_status(self) -> CompletionEvidenceStatus:
        if not self.requires_validation_evidence:
            self.completion_evidence_status = CompletionEvidenceStatus.NOT_REQUIRED
            self.post_mutation_validation_pending = False
            return self.completion_evidence_status

        if self.last_successful_validation_turn is None:
            self.completion_evidence_status = CompletionEvidenceStatus.MISSING
            self.post_mutation_validation_pending = self.last_mutation_turn is not None
            return self.completion_evidence_status

        if (
            self.last_mutation_turn is not None
            and self.last_mutation_turn > self.last_successful_validation_turn
        ):
            self.completion_evidence_status = CompletionEvidenceStatus.STALE
            self.post_mutation_validation_pending = True
            return self.completion_evidence_status

        self.completion_evidence_status = CompletionEvidenceStatus.VALIDATED
        self.post_mutation_validation_pending = False
        return self.completion_evidence_status

    def refresh_validation_phase(self) -> ValidationPhase:
        if self.pending_issue_kind == PendingIssueKind.VALIDATION_FAILURE:
            self.validation_phase = ValidationPhase.VALIDATION_FAILED
            return self.validation_phase

        if self.last_mutation_turn is None and self.last_successful_validation_turn is None:
            self.validation_phase = ValidationPhase.IDLE
            return self.validation_phase

        if (
            self.last_successful_validation_turn is not None
            and (
                self.last_mutation_turn is None
                or self.last_successful_validation_turn >= self.last_mutation_turn
            )
        ):
            self.validation_phase = ValidationPhase.VALIDATED
            return self.validation_phase

        self.validation_phase = ValidationPhase.MUTATED_UNVALIDATED
        return self.validation_phase

    def open_or_update_validation_issue(
        self,
        *,
        kind: ValidationIssueKind,
        detail: str,
        turn_index: int,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        increment_validation_attempt: bool = False,
    ) -> ValidationIssueRecord:
        active = self.active_validation_issue
        if active is None or active.kind != kind:
            active = ValidationIssueRecord(
                issue_id=f"validation_issue_{turn_index:03d}",
                kind=kind,
                detail=detail,
                opened_at_turn=turn_index,
                last_observed_turn=turn_index,
                last_failure_tool_name=tool_name,
                last_failure_tool_call_id=tool_call_id,
                validation_attempt_count=1 if increment_validation_attempt else 0,
            )
            self.active_validation_issue = active
            return active

        active.detail = detail
        active.last_observed_turn = turn_index
        if tool_name is not None:
            active.last_failure_tool_name = tool_name
        if tool_call_id is not None:
            active.last_failure_tool_call_id = tool_call_id
        if increment_validation_attempt:
            active.validation_attempt_count += 1
        return active

    def resolve_active_validation_issue(
        self,
        *,
        turn_index: int,
        resolution_reason: str,
    ) -> ValidationIssueRecord | None:
        if self.active_validation_issue is None:
            return None
        resolved = ValidationIssueRecord(**self.active_validation_issue.__dict__)
        resolved.last_observed_turn = turn_index
        resolved.resolved_at_turn = turn_index
        resolved.resolution_reason = resolution_reason
        self.last_resolved_validation_issue = resolved
        self.active_validation_issue = None
        return resolved

    def note_revision_attempt(self, *, turn_index: int) -> None:
        if self.active_validation_issue is None:
            return
        if self.last_revision_attempt_turn == turn_index:
            return
        self.active_validation_issue.revision_attempt_count += 1
        self.active_validation_issue.last_observed_turn = turn_index
        self.last_revision_attempt_turn = turn_index

    def note_finish_deferral(self, *, turn_index: int) -> None:
        if self.active_validation_issue is None:
            return
        if self.last_finish_deferral_turn == turn_index:
            return
        self.active_validation_issue.finish_deferral_count += 1
        self.active_validation_issue.last_observed_turn = turn_index
        self.last_finish_deferral_turn = turn_index

    def note_active_failure(self, *, kind: str, turn_index: int) -> None:
        self.active_failure_kind = kind
        self.active_failure_turn = turn_index
        self.corrective_progress_after_failure = False

    def note_corrective_progress(self, *, turn_index: int) -> None:
        if self.active_failure_kind is None:
            return
        if self.active_failure_turn is None or turn_index >= self.active_failure_turn:
            self.corrective_progress_after_failure = True

    def clear_active_failure(self) -> None:
        self.active_failure_kind = None
        self.active_failure_turn = None
        self.corrective_progress_after_failure = False

    def validation_evidence_fresh(self) -> bool:
        return self.refresh_completion_evidence_status() in {
            CompletionEvidenceStatus.NOT_REQUIRED,
            CompletionEvidenceStatus.VALIDATED,
        }

    def completion_gate_status(self) -> CompletionGateStatus:
        if self.has_pending_issue:
            return CompletionGateStatus.BLOCKED_PENDING_ISSUE
        evidence_status = self.refresh_completion_evidence_status()
        if evidence_status in {
            CompletionEvidenceStatus.MISSING,
            CompletionEvidenceStatus.STALE,
        }:
            return CompletionGateStatus.BLOCKED_MISSING_VALIDATION
        return CompletionGateStatus.OPEN

    def expected_next_step(self) -> ExpectedNextStep:
        if self.pending_issue_kind in {
            PendingIssueKind.PARSE_ERROR,
            PendingIssueKind.TOOL_FAILURE,
        }:
            return ExpectedNextStep.RETRY_PARSE_OR_TOOL

        if (
            not self.requires_validation_evidence
            and self.completion_gate_status() == CompletionGateStatus.OPEN
        ):
            return ExpectedNextStep.FINISH_ALLOWED

        validation_phase = self.refresh_validation_phase()
        if validation_phase == ValidationPhase.MUTATED_UNVALIDATED:
            return ExpectedNextStep.VALIDATE
        if validation_phase == ValidationPhase.VALIDATION_FAILED:
            if (
                self.last_revision_attempt_turn is None
                or self.last_validation_failure_turn is None
                or self.last_revision_attempt_turn <= self.last_validation_failure_turn
            ):
                return ExpectedNextStep.REVISE
            return ExpectedNextStep.REVALIDATE

        if self.completion_gate_status() == CompletionGateStatus.OPEN:
            return ExpectedNextStep.FINISH_ALLOWED
        return ExpectedNextStep.NONE


def canonical_tool_name(call: ToolCall) -> str:
    return call.canonical_name or call.name


def is_validation_tool(call: ToolCall) -> bool:
    return canonical_tool_name(call) in _VALIDATION_TOOLS


def is_mutation_tool(call: ToolCall) -> bool:
    return canonical_tool_name(call) in _MUTATION_TOOLS


def record_parse_result(
    state: RuntimeRecoveryState,
    parsed: ParseResult,
    *,
    turn_index: int | None = None,
) -> RecoveryUpdate:
    state.parse_error_count += len(parsed.parse_errors)

    if parsed.parse_errors and not parsed.tool_calls:
        state.consecutive_parse_error_turns += 1
        if turn_index is not None:
            state.note_active_failure(kind=PendingIssueKind.PARSE_ERROR.value, turn_index=turn_index)
        detail = (
            "Completion deferred: parse errors need recovery "
            f"({'; '.join(parsed.parse_errors)})"
        )
        state.set_pending_issue(PendingIssueKind.PARSE_ERROR, detail)
        recoverable = state.consecutive_parse_error_turns < _MAX_CONSECUTIVE_PARSE_ERROR_TURNS
        return RecoveryUpdate(
            recoverable=recoverable,
            pending_issue_kind=PendingIssueKind.PARSE_ERROR,
            pending_issue_detail=detail,
            continue_reason=(
                ContinueReason.RECOVERABLE_PARSE_ERROR if recoverable else None
            ),
        )

    state.consecutive_parse_error_turns = 0
    if not parsed.parse_errors and state.pending_issue_kind == PendingIssueKind.PARSE_ERROR:
        cleared = state.clear_pending_issue()
        return RecoveryUpdate(
            recoverable=False,
            pending_issue_cleared=cleared,
        )

    return RecoveryUpdate(recoverable=False)


def record_tool_result(
    state: RuntimeRecoveryState,
    call: ToolCall,
    result: ToolResult,
    *,
    turn_index: int,
) -> RecoveryUpdate:
    tool_name = canonical_tool_name(call)
    if tool_name == "finish":
        return RecoveryUpdate(recoverable=False)

    if is_mutation_tool(call) and state.active_validation_issue is not None:
        state.note_revision_attempt(turn_index=turn_index)
    if is_mutation_tool(call):
        state.last_mutation_turn = turn_index
        state.post_mutation_validation_pending = state.requires_validation_evidence
        if state.active_failure_kind is not None:
            state.note_corrective_progress(turn_index=turn_index)

    if result.ok and not result.is_error:
        if is_validation_tool(call):
            if state.active_validation_issue is not None:
                state.active_validation_issue.validation_attempt_count += 1
                state.active_validation_issue.last_observed_turn = turn_index
            state.last_validation_attempt_turn = turn_index
            state.last_successful_validation_turn = turn_index
            state.post_mutation_validation_pending = False
            state.resolve_active_validation_issue(
                turn_index=turn_index,
                resolution_reason="validation_passed",
            )
            state.clear_active_failure()
        elif state.pending_issue_kind in {
            PendingIssueKind.PARSE_ERROR,
            PendingIssueKind.TOOL_FAILURE,
        }:
            state.clear_active_failure()
        elif state.active_failure_kind is not None:
            state.note_corrective_progress(turn_index=turn_index)

        state.refresh_completion_evidence_status()
        state.refresh_validation_phase()
        if is_validation_tool(call):
            cleared = state.clear_pending_issue()
            state.refresh_validation_phase()
            return RecoveryUpdate(
                recoverable=False,
                pending_issue_cleared=cleared,
            )
        if state.pending_issue_kind in {
            PendingIssueKind.PARSE_ERROR,
            PendingIssueKind.TOOL_FAILURE,
        }:
            cleared = state.clear_pending_issue()
            state.refresh_validation_phase()
            return RecoveryUpdate(
                recoverable=False,
                pending_issue_cleared=cleared,
            )
        return RecoveryUpdate(recoverable=False)

    if not is_recoverable_tool_result(call, result):
        return RecoveryUpdate(recoverable=False)

    if is_validation_tool(call):
        state.last_validation_attempt_turn = turn_index
        state.last_validation_failure_turn = turn_index
        state.validation_failure_count += 1
        state.note_active_failure(
            kind=PendingIssueKind.VALIDATION_FAILURE.value,
            turn_index=turn_index,
        )
        kind = PendingIssueKind.VALIDATION_FAILURE
        continue_reason = ContinueReason.RECOVERABLE_VALIDATION_FAILURE
        validation_issue_kind = _classify_validation_issue(result)
        detail = _describe_pending_tool_issue(call, result)
        state.set_pending_issue(kind, detail)
        state.open_or_update_validation_issue(
            kind=validation_issue_kind,
            detail=detail,
            turn_index=turn_index,
            tool_name=tool_name,
            tool_call_id=call.id,
            increment_validation_attempt=True,
        )
    else:
        state.note_active_failure(
            kind=PendingIssueKind.TOOL_FAILURE.value,
            turn_index=turn_index,
        )
        kind = PendingIssueKind.TOOL_FAILURE
        continue_reason = ContinueReason.RECOVERABLE_TOOL_FAILURE
        detail = _describe_pending_tool_issue(call, result)
        state.set_pending_issue(kind, detail)

    state.refresh_completion_evidence_status()
    state.refresh_validation_phase()
    return RecoveryUpdate(
        recoverable=True,
        pending_issue_kind=kind,
        pending_issue_detail=detail,
        continue_reason=continue_reason,
    )


def ensure_validation_issue_for_completion_block(
    state: RuntimeRecoveryState,
    *,
    turn_index: int,
) -> ValidationIssueRecord | None:
    if state.active_validation_issue is not None:
        state.active_validation_issue.last_observed_turn = turn_index
        return state.active_validation_issue

    evidence_status = state.refresh_completion_evidence_status()
    if evidence_status == CompletionEvidenceStatus.NOT_REQUIRED:
        return None
    if evidence_status == CompletionEvidenceStatus.VALIDATED:
        return state.active_validation_issue
    if evidence_status == CompletionEvidenceStatus.STALE:
        return state.open_or_update_validation_issue(
            kind=ValidationIssueKind.STALE_VALIDATION_EVIDENCE,
            detail=(
                "Completion deferred: validation evidence is stale because the "
                "workspace changed after the last successful validation"
            ),
            turn_index=turn_index,
        )
    return state.open_or_update_validation_issue(
        kind=ValidationIssueKind.FINISH_WITHOUT_REQUIRED_VALIDATION,
        detail=(
            "Completion deferred: validation has not succeeded yet for a task "
            "that requires runtime validation evidence"
        ),
        turn_index=turn_index,
    )


def validation_budget_exhaustion(
    state: RuntimeRecoveryState,
) -> tuple[StopDecisionCode, str] | None:
    issue = state.active_validation_issue
    if issue is None:
        return None

    config = state.validation_policy_config
    if issue.validation_attempt_count > config.max_validation_attempts_per_issue:
        return (
            StopDecisionCode.VALIDATION_BUDGET_EXHAUSTED,
            (
                "Validation budget exhausted for "
                f"{issue.kind.value} after {issue.validation_attempt_count} validation "
                f"attempts (last_failure_tool={issue.last_failure_tool_name or 'unknown'})"
            ),
        )
    if issue.revision_attempt_count > config.max_revision_attempts_per_issue:
        return (
            StopDecisionCode.REVISION_BUDGET_EXHAUSTED,
            (
                "Revision budget exhausted for "
                f"{issue.kind.value} after {issue.revision_attempt_count} revision attempts"
            ),
        )
    if issue.finish_deferral_count > config.max_finish_deferrals_per_issue:
        return (
            StopDecisionCode.FINISH_DEFERRAL_BUDGET_EXHAUSTED,
            (
                "Finish deferral budget exhausted for "
                f"{issue.kind.value} after {issue.finish_deferral_count} blocked completion attempts"
            ),
        )
    return None


def assess_completion_block(
    state: RuntimeRecoveryState,
    *,
    meaningful_progress_observed: bool,
    progress_gate_applicable: bool = False,
    recent_failure_kind: str | None = None,
) -> CompletionBlockAssessment:
    evidence_status = state.refresh_completion_evidence_status()
    validation_evidence_fresh = state.validation_evidence_fresh()
    active_failure_kind = state.active_failure_kind or recent_failure_kind
    post_mutation_validation_pending = state.post_mutation_validation_pending
    corrective_progress_after_failure = state.corrective_progress_after_failure

    if state.pending_issue_kind == PendingIssueKind.VALIDATION_FAILURE:
        state.finish_gate_reason = "unresolved_validation_failure"
        return CompletionBlockAssessment(
            blocked=True,
            completion_block_family=CompletionBlockFamily.PENDING_ISSUE,
            block_reason="unresolved_validation_failure",
            detail=(
                state.pending_issue_detail
                or "Completion deferred: validation failed and has not been recovered yet"
            ),
            expected_next_step=state.expected_next_step(),
            recent_failure_kind=recent_failure_kind,
            active_failure_kind=active_failure_kind,
            corrective_progress_after_failure=corrective_progress_after_failure,
            post_mutation_validation_pending=post_mutation_validation_pending,
            validation_evidence_fresh=validation_evidence_fresh,
            completion_allowed=False,
        )
    if state.pending_issue_kind in {
        PendingIssueKind.PARSE_ERROR,
        PendingIssueKind.TOOL_FAILURE,
    }:
        state.finish_gate_reason = "recent_recoverable_failure"
        return CompletionBlockAssessment(
            blocked=True,
            completion_block_family=CompletionBlockFamily.PENDING_ISSUE,
            block_reason="recent_recoverable_failure",
            detail=(
                state.pending_issue_detail
                or "Completion deferred: a recoverable issue is still pending"
            ),
            expected_next_step=state.expected_next_step(),
            recent_failure_kind=recent_failure_kind,
            active_failure_kind=active_failure_kind,
            corrective_progress_after_failure=corrective_progress_after_failure,
            post_mutation_validation_pending=post_mutation_validation_pending,
            validation_evidence_fresh=validation_evidence_fresh,
            completion_allowed=False,
        )
    if post_mutation_validation_pending and evidence_status in {
        CompletionEvidenceStatus.MISSING,
        CompletionEvidenceStatus.STALE,
    }:
        state.finish_gate_reason = "post_mutation_validation_pending"
        return CompletionBlockAssessment(
            blocked=True,
            completion_block_family=CompletionBlockFamily.VALIDATION_EVIDENCE,
            block_reason="post_mutation_validation_pending",
            detail=(
                "Completion deferred: workspace changes still need fresh validation "
                "before finish is allowed"
            ),
            expected_next_step=ExpectedNextStep.VALIDATE,
            recent_failure_kind=recent_failure_kind,
            active_failure_kind=active_failure_kind,
            corrective_progress_after_failure=corrective_progress_after_failure,
            post_mutation_validation_pending=post_mutation_validation_pending,
            validation_evidence_fresh=validation_evidence_fresh,
            completion_allowed=False,
        )
    if (
        active_failure_kind is not None
        and not corrective_progress_after_failure
        and evidence_status == CompletionEvidenceStatus.VALIDATED
    ):
        state.finish_gate_reason = "no_corrective_progress_after_failure"
        return CompletionBlockAssessment(
            blocked=True,
            completion_block_family=CompletionBlockFamily.PROGRESS_GATE,
            block_reason="no_corrective_progress_after_failure",
            detail=(
                "Completion deferred: a recent failure has not been followed by a "
                "corrective revision or successful retry yet"
            ),
            expected_next_step=state.expected_next_step(),
            recent_failure_kind=recent_failure_kind,
            active_failure_kind=active_failure_kind,
            corrective_progress_after_failure=corrective_progress_after_failure,
            post_mutation_validation_pending=post_mutation_validation_pending,
            validation_evidence_fresh=validation_evidence_fresh,
            completion_allowed=False,
        )
    if evidence_status == CompletionEvidenceStatus.MISSING:
        state.finish_gate_reason = "missing_validation_evidence"
        return CompletionBlockAssessment(
            blocked=True,
            completion_block_family=CompletionBlockFamily.VALIDATION_EVIDENCE,
            block_reason="missing_validation_evidence",
            detail=(
                "Completion deferred: validation has not succeeded yet for a task "
                "that requires runtime validation evidence"
            ),
            expected_next_step=ExpectedNextStep.VALIDATE,
            recent_failure_kind=recent_failure_kind,
            active_failure_kind=active_failure_kind,
            corrective_progress_after_failure=corrective_progress_after_failure,
            post_mutation_validation_pending=post_mutation_validation_pending,
            validation_evidence_fresh=validation_evidence_fresh,
            completion_allowed=False,
        )
    if evidence_status == CompletionEvidenceStatus.STALE:
        state.finish_gate_reason = "post_mutation_validation_pending"
        return CompletionBlockAssessment(
            blocked=True,
            completion_block_family=CompletionBlockFamily.VALIDATION_EVIDENCE,
            block_reason="post_mutation_validation_pending",
            detail=(
                "Completion deferred: validation evidence is stale because the "
                "workspace changed after the last successful validation"
            ),
            expected_next_step=ExpectedNextStep.VALIDATE,
            recent_failure_kind=recent_failure_kind,
            active_failure_kind=active_failure_kind,
            corrective_progress_after_failure=corrective_progress_after_failure,
            post_mutation_validation_pending=post_mutation_validation_pending,
            validation_evidence_fresh=validation_evidence_fresh,
            completion_allowed=False,
        )
    if progress_gate_applicable and not meaningful_progress_observed:
        detail = "Completion deferred: runtime has not observed meaningful non-finish progress yet"
        if recent_failure_kind is not None:
            detail += f" after recent {recent_failure_kind}"
        state.finish_gate_reason = "no_meaningful_progress"
        return CompletionBlockAssessment(
            blocked=True,
            completion_block_family=CompletionBlockFamily.PROGRESS_GATE,
            block_reason="no_meaningful_progress",
            detail=detail,
            expected_next_step=ExpectedNextStep.RETRY_PARSE_OR_TOOL,
            recent_failure_kind=recent_failure_kind,
            active_failure_kind=active_failure_kind,
            corrective_progress_after_failure=corrective_progress_after_failure,
            post_mutation_validation_pending=post_mutation_validation_pending,
            validation_evidence_fresh=validation_evidence_fresh,
            completion_allowed=False,
        )
    state.finish_gate_reason = None
    return CompletionBlockAssessment(
        blocked=False,
        completion_block_family=CompletionBlockFamily.NONE,
        recent_failure_kind=recent_failure_kind,
        active_failure_kind=active_failure_kind,
        corrective_progress_after_failure=corrective_progress_after_failure,
        post_mutation_validation_pending=post_mutation_validation_pending,
        validation_evidence_fresh=validation_evidence_fresh,
        completion_allowed=True,
    )


def completion_block_reason(
    state: RuntimeRecoveryState,
    *,
    meaningful_progress_observed: bool = True,
    progress_gate_applicable: bool = False,
    recent_failure_kind: str | None = None,
) -> str | None:
    assessment = assess_completion_block(
        state,
        meaningful_progress_observed=meaningful_progress_observed,
        progress_gate_applicable=progress_gate_applicable,
        recent_failure_kind=recent_failure_kind,
    )
    if not assessment.blocked:
        return None
    return assessment.detail


def completion_block_family_for_reason(
    block_reason: str | None,
) -> CompletionBlockFamily:
    if block_reason in {
        "unresolved_validation_failure",
        "recent_recoverable_failure",
    }:
        return CompletionBlockFamily.PENDING_ISSUE
    if block_reason in {
        "post_mutation_validation_pending",
        "missing_validation_evidence",
    }:
        return CompletionBlockFamily.VALIDATION_EVIDENCE
    if block_reason in {
        "no_corrective_progress_after_failure",
        "no_meaningful_progress",
    }:
        return CompletionBlockFamily.PROGRESS_GATE
    return CompletionBlockFamily.NONE


def stop_hook_reason_code_for_block_reason(block_reason: str | None) -> str:
    """Map detailed completion-block reasons into a minimal stop-hook taxonomy."""

    family = completion_block_family_for_reason(block_reason)
    if family == CompletionBlockFamily.PENDING_ISSUE:
        return "pending_issue"
    if family == CompletionBlockFamily.VALIDATION_EVIDENCE:
        return "validation_required"
    if family == CompletionBlockFamily.PROGRESS_GATE:
        return "no_progress"
    return "none"


def derive_stop_policy_input_snapshot(
    session_state: Any,
    recovery_state: RuntimeRecoveryState,
    *,
    current_turn: int,
) -> StopPolicyInputSnapshot:
    meaningful_progress = (
        getattr(session_state, "non_finish_tool_call_count", 0) > 0
        and (
            bool(getattr(session_state, "saw_mutation_progress", False))
            or bool(getattr(session_state, "saw_validation_progress", False))
            or len(getattr(session_state, "distinct_non_finish_tool_names", [])) > 1
        )
    )
    successful_non_finish = int(
        getattr(session_state, "successful_non_finish_tool_call_count", 0) or 0
    )
    progress_gate_applicable = successful_non_finish > 1 and not meaningful_progress
    recent_failure_kind = None
    recent_failure = getattr(session_state, "recent_failure_kind", None)
    recent_failure_turn = getattr(session_state, "recent_failure_turn", None)
    if recent_failure is not None and recent_failure_turn is not None:
        if current_turn - int(recent_failure_turn) <= 2:
            recent_failure_kind = str(recent_failure)
    assessment = assess_completion_block(
        recovery_state,
        meaningful_progress_observed=meaningful_progress,
        progress_gate_applicable=progress_gate_applicable,
        recent_failure_kind=recent_failure_kind,
    )
    return StopPolicyInputSnapshot(
        meaningful_progress_observed=meaningful_progress,
        progress_gate_applicable=progress_gate_applicable,
        recent_failure_kind=recent_failure_kind,
        validation_required_for_completion=bool(
            recovery_state.validation_required_for_completion
        ),
        completion_block_family_hint=assessment.completion_block_family,
    )


def continue_reason_for_turn(
    state: RuntimeRecoveryState,
    *,
    tool_calls_present: bool,
    parse_errors: list[str],
    completion_blocked: bool,
) -> ContinueReason | None:
    if parse_errors and not tool_calls_present and parse_error_is_recoverable(state):
        return ContinueReason.RECOVERABLE_PARSE_ERROR

    if completion_blocked:
        if state.pending_issue_kind is not None:
            return ContinueReason.DEFER_COMPLETION_PENDING_ISSUE
        return ContinueReason.DEFER_COMPLETION_MISSING_COMPLETION_EVIDENCE

    if state.pending_issue_kind == PendingIssueKind.VALIDATION_FAILURE:
        if (
            state.last_mutation_turn is not None
            and state.last_validation_failure_turn is not None
            and state.last_mutation_turn > state.last_validation_failure_turn
        ):
            return ContinueReason.AWAITING_REVALIDATION_AFTER_REVISION
        return ContinueReason.AWAITING_REVISION_AFTER_VALIDATION_FAILURE

    if state.pending_issue_kind == PendingIssueKind.TOOL_FAILURE:
        return ContinueReason.RECOVERABLE_TOOL_FAILURE

    if tool_calls_present:
        return ContinueReason.TOOL_CALLS_PRESENT

    return None


def classify_turn_action(
    tool_calls: list[ToolCall],
    *,
    phase_before: ValidationPhase | str,
) -> TurnAction:
    normalized_phase = ValidationPhase(str(phase_before))
    if not tool_calls:
        return TurnAction.NONE

    has_finish = any(canonical_tool_name(call) == "finish" for call in tool_calls)
    has_validation = any(is_validation_tool(call) for call in tool_calls)
    has_mutation = any(is_mutation_tool(call) for call in tool_calls)

    if has_finish and len(tool_calls) == 1 and not has_validation and not has_mutation:
        return TurnAction.FINISH_ATTEMPT

    if has_mutation and has_validation:
        if normalized_phase == ValidationPhase.VALIDATION_FAILED:
            return TurnAction.REVISION_AND_REVALIDATION
        return TurnAction.MIXED

    if has_validation:
        if normalized_phase == ValidationPhase.VALIDATION_FAILED:
            return TurnAction.REVALIDATE
        return TurnAction.VALIDATE

    if has_mutation:
        if normalized_phase == ValidationPhase.VALIDATION_FAILED:
            return TurnAction.REVISE
        return TurnAction.MUTATE

    if has_finish:
        return TurnAction.MIXED

    return TurnAction.INSPECT


def classify_turn_outcome(
    *,
    phase_before: ValidationPhase | str,
    phase_after: ValidationPhase | str,
    action: TurnAction | str,
    tool_results: list[tuple[ToolCall, ToolResult]],
    stop_decision_code: str,
    stop_reason: str | None,
) -> TurnOutcome:
    normalized_action = (
        action if isinstance(action, TurnAction) else TurnAction(str(action))
    )
    normalized_phase_after = (
        phase_after
        if isinstance(phase_after, ValidationPhase)
        else ValidationPhase(str(phase_after))
    )

    if stop_reason == StopDecisionCode.FINISH.value or stop_reason == "finish":
        return TurnOutcome.FINISH_ACCEPTED

    if stop_decision_code == StopDecisionCode.VALIDATION_BUDGET_EXHAUSTED.value:
        return TurnOutcome.VALIDATION_BUDGET_EXHAUSTED
    if stop_decision_code == StopDecisionCode.REVISION_BUDGET_EXHAUSTED.value:
        return TurnOutcome.REVISION_BUDGET_EXHAUSTED
    if stop_decision_code == StopDecisionCode.FINISH_DEFERRAL_BUDGET_EXHAUSTED.value:
        return TurnOutcome.FINISH_DEFERRAL_BUDGET_EXHAUSTED

    if stop_decision_code.startswith("defer_finish") or stop_decision_code.startswith(
        "defer_no_tool_calls"
    ):
        if normalized_action == TurnAction.FINISH_ATTEMPT:
            return TurnOutcome.FINISH_BLOCKED_BY_VALIDATION
        return TurnOutcome.FINISH_DEFERRED

    validation_results = [
        result
        for call, result in tool_results
        if is_validation_tool(call)
    ]
    if validation_results:
        if any(result.ok and not result.is_error for result in validation_results):
            return TurnOutcome.VALIDATION_PASSED
        if any((not result.ok) or result.is_error for result in validation_results):
            return TurnOutcome.VALIDATION_FAILED

    if normalized_action in {
        TurnAction.REVISE,
        TurnAction.REVISION_AND_REVALIDATION,
    }:
        return TurnOutcome.REVISION_APPLIED

    if normalized_phase_after == ValidationPhase.MUTATED_UNVALIDATED:
        return TurnOutcome.AWAITING_VALIDATION

    return TurnOutcome.NONE


def parse_error_is_recoverable(state: RuntimeRecoveryState) -> bool:
    return state.consecutive_parse_error_turns < _MAX_CONSECUTIVE_PARSE_ERROR_TURNS


def is_recoverable_tool_result(call: ToolCall, result: ToolResult) -> bool:
    if result.ok and not result.is_error:
        return False

    error_type = str(result.metadata.get("error_type") or "")
    stage = str(result.metadata.get("stage") or "")

    if error_type in {
        "command_policy",
        "protected_path",
        "missing_context",
        "canonical_tool_lookup",
        "missing_canonical_tool",
    }:
        return False

    if is_validation_tool(call) and "exit_code" in result.metadata:
        return True

    if error_type in _RECOVERABLE_RUNTIME_ERROR_TYPES:
        return True

    if stage in _RECOVERABLE_RUNTIME_STAGES:
        return True

    return False


def _classify_validation_issue(result: ToolResult) -> ValidationIssueKind:
    error_type = str(result.metadata.get("error_type") or "")
    if error_type == "timeout":
        return ValidationIssueKind.VALIDATION_TIMEOUT
    if "exit_code" in result.metadata:
        return ValidationIssueKind.VALIDATION_COMMAND_NONZERO_EXIT
    return ValidationIssueKind.VALIDATION_COMMAND_FAILED


def _describe_pending_tool_issue(call: ToolCall, result: ToolResult) -> str:
    tool_name = canonical_tool_name(call)
    error_type = str(result.metadata.get("error_type") or "")

    if is_validation_tool(call) and "exit_code" in result.metadata:
        exit_code = result.metadata.get("exit_code")
        return (
            "Completion deferred: validation tool "
            f"{tool_name!r} did not succeed (exit_code={exit_code})"
        )

    if error_type:
        return (
            "Completion deferred: recoverable tool issue in "
            f"{tool_name!r} ({error_type})"
        )

    return f"Completion deferred: recoverable tool issue in {tool_name!r}"
