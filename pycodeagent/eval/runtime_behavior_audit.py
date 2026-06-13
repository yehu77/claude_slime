"""Aggregate behavior-level audit summaries from local runtime runs."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from pycodeagent.rl.dataset_builder import discover_run_dirs


class RunBehaviorSummary(BaseModel):
    run_dir: str
    task_id: str
    profile_id: str
    status: str
    passed: bool
    turn_count: int
    stop_reason: str | None = None
    stop_decision_code: str | None = None
    final_validation_phase: str | None = None
    completion_evidence_status: str | None = None
    final_expected_next_step: str | None = None
    final_completion_gate_status: str | None = None
    parse_error_count: int = 0
    llm_error_type: str | None = None
    tool_call_count: int = 0
    non_finish_tool_call_count: int = 0
    validation_turn_count: int = 0
    revalidation_turn_count: int = 0
    revision_turn_count: int = 0
    finish_deferred_count: int = 0
    finish_attempt_count: int = 0
    finish_blocked_count: int = 0
    compaction_turn_count: int = 0
    premature_finish_count: int = 0
    finish_without_progress_count: int = 0
    finish_after_recent_failure_count: int = 0
    finish_blocked_recent_failure_count: int = 0
    finish_blocked_post_edit_validation_missing_count: int = 0
    finish_attempt_before_revalidation_count: int = 0
    failure_then_no_corrective_progress_count: int = 0
    failure_then_successful_revalidation_count: int = 0
    finish_after_tool_execution_failure_count: int = 0
    finish_after_validation_failure_without_revision_count: int = 0
    no_progress_after_validation_failure_count: int = 0
    tool_progress_stall_count: int = 0
    empty_turn_no_tool_no_content_count: int = 0
    schema_malformed_turn_count: int = 0
    recovered_format_drift_count: int = 0
    compat_leak_count: int = 0
    truncated_tool_block_count: int = 0
    unrecovered_validation_failure_count: int = 0
    tool_execution_failure_unrecovered_count: int = 0
    validation_issue_count: int = 0
    validation_retry_count: int = 0
    revision_after_validation_failure_count: int = 0
    token_budget_compaction_turn_count: int = 0
    mean_validation_attempts_per_issue: float = 0.0
    mean_revision_attempts_per_issue: float = 0.0
    saw_validation_failure: bool = False
    saw_revision_after_failure: bool = False
    saw_finish_deferred: bool = False
    saw_compaction: bool = False
    saw_validation_budget_exhausted: bool = False
    saw_revision_budget_exhausted: bool = False
    saw_finish_blocked_by_validation: bool = False
    saw_token_overflow: bool = False
    saw_premature_finish: bool = False
    saw_finish_without_progress: bool = False
    saw_finish_after_recent_failure: bool = False
    saw_finish_blocked_recent_failure: bool = False
    saw_finish_blocked_post_edit_validation_missing: bool = False
    saw_finish_attempt_before_revalidation: bool = False
    saw_failure_then_no_corrective_progress: bool = False
    saw_failure_then_successful_revalidation: bool = False
    saw_finish_after_tool_execution_failure: bool = False
    saw_finish_after_validation_failure_without_revision: bool = False
    saw_no_progress_after_validation_failure: bool = False
    saw_tool_progress_stall: bool = False
    saw_empty_turn_no_tool_no_content: bool = False
    saw_schema_malformed: bool = False
    saw_recovered_format_drift: bool = False
    saw_compat_leak: bool = False
    saw_truncated_tool_block: bool = False
    saw_unrecovered_validation_failure: bool = False
    saw_tool_execution_failure_unrecovered: bool = False
    saw_parse_error: bool = False
    saw_llm_error: bool = False
    saw_no_tool_progress: bool = False
    context_policy_modes: list[str] = Field(default_factory=list)
    observed_failure_buckets: list[str] = Field(default_factory=list)


class RuntimeBehaviorAudit(BaseModel):
    source_type: str
    source_path: str
    run_count: int
    completed_run_count: int
    passed_run_count: int
    validation_turn_count: int
    revalidation_turn_count: int
    revision_turn_count: int
    finish_deferred_count: int
    finish_attempt_count: int
    finish_blocked_count: int
    compaction_turn_count: int
    premature_finish_count: int
    finish_without_progress_count: int
    finish_after_recent_failure_count: int
    finish_blocked_recent_failure_count: int
    finish_blocked_post_edit_validation_missing_count: int
    finish_attempt_before_revalidation_count: int
    failure_then_no_corrective_progress_count: int
    failure_then_successful_revalidation_count: int
    finish_after_tool_execution_failure_count: int
    finish_after_validation_failure_without_revision_count: int
    no_progress_after_validation_failure_count: int
    tool_progress_stall_count: int
    empty_turn_no_tool_no_content_count: int
    schema_malformed_turn_count: int
    recovered_format_drift_count: int
    compat_leak_count: int
    truncated_tool_block_count: int
    unrecovered_validation_failure_count: int
    tool_execution_failure_unrecovered_count: int
    validation_issue_count: int
    validation_retry_count: int
    revision_after_validation_failure_count: int
    token_budget_compaction_turn_count: int
    runs_with_validation_failure: int
    runs_with_revision_after_failure: int
    runs_with_finish_deferred: int
    runs_with_compaction: int
    runs_with_validation_budget_exhausted: int
    runs_with_revision_budget_exhausted: int
    runs_with_finish_blocked_by_validation: int
    runs_with_token_overflow: int
    runs_with_premature_finish: int
    runs_with_finish_without_progress: int
    runs_with_finish_after_recent_failure: int
    runs_with_finish_blocked_recent_failure: int
    runs_with_finish_blocked_post_edit_validation_missing: int
    runs_with_finish_attempt_before_revalidation: int
    runs_with_failure_then_no_corrective_progress: int
    runs_with_failure_then_successful_revalidation: int
    runs_with_finish_after_tool_execution_failure: int
    runs_with_finish_after_validation_failure_without_revision: int
    runs_with_no_progress_after_validation_failure: int
    runs_with_tool_progress_stall: int
    runs_with_empty_turn_no_tool_no_content: int
    runs_with_schema_malformed: int
    runs_with_recovered_format_drift: int
    runs_with_compat_leak: int
    runs_with_truncated_tool_block: int
    runs_with_unrecovered_validation_failure: int
    runs_with_tool_execution_failure_unrecovered: int
    runs_with_parse_error: int
    runs_with_llm_error: int
    runs_with_no_tool_progress: int
    mean_validation_attempts_per_issue: float
    mean_revision_attempts_per_issue: float
    per_run: list[RunBehaviorSummary]


def build_runtime_behavior_audit(
    source_dir: str | Path,
    output_path: str | Path,
    *,
    source_type: str = "batch",
) -> RuntimeBehaviorAudit:
    source_dir = Path(source_dir)
    output_path = Path(output_path)
    run_dirs = discover_run_dirs(source_dir, source_type=source_type)

    per_run = [_summarize_run(run_dir) for run_dir in run_dirs]
    validation_issue_denominator = max(
        sum(run.validation_issue_count for run in per_run),
        1,
    )
    audit = RuntimeBehaviorAudit(
        source_type=source_type,
        source_path=str(source_dir),
        run_count=len(per_run),
        completed_run_count=sum(1 for run in per_run if run.status == "completed"),
        passed_run_count=sum(1 for run in per_run if run.passed),
        validation_turn_count=sum(run.validation_turn_count for run in per_run),
        revalidation_turn_count=sum(run.revalidation_turn_count for run in per_run),
        revision_turn_count=sum(run.revision_turn_count for run in per_run),
        finish_deferred_count=sum(run.finish_deferred_count for run in per_run),
        finish_attempt_count=sum(run.finish_attempt_count for run in per_run),
        finish_blocked_count=sum(run.finish_blocked_count for run in per_run),
        compaction_turn_count=sum(run.compaction_turn_count for run in per_run),
        premature_finish_count=sum(run.premature_finish_count for run in per_run),
        finish_without_progress_count=sum(
            run.finish_without_progress_count for run in per_run
        ),
        finish_after_recent_failure_count=sum(
            run.finish_after_recent_failure_count for run in per_run
        ),
        finish_blocked_recent_failure_count=sum(
            run.finish_blocked_recent_failure_count for run in per_run
        ),
        finish_blocked_post_edit_validation_missing_count=sum(
            run.finish_blocked_post_edit_validation_missing_count for run in per_run
        ),
        finish_attempt_before_revalidation_count=sum(
            run.finish_attempt_before_revalidation_count for run in per_run
        ),
        failure_then_no_corrective_progress_count=sum(
            run.failure_then_no_corrective_progress_count for run in per_run
        ),
        failure_then_successful_revalidation_count=sum(
            run.failure_then_successful_revalidation_count for run in per_run
        ),
        finish_after_tool_execution_failure_count=sum(
            run.finish_after_tool_execution_failure_count for run in per_run
        ),
        finish_after_validation_failure_without_revision_count=sum(
            run.finish_after_validation_failure_without_revision_count
            for run in per_run
        ),
        no_progress_after_validation_failure_count=sum(
            run.no_progress_after_validation_failure_count for run in per_run
        ),
        tool_progress_stall_count=sum(run.tool_progress_stall_count for run in per_run),
        empty_turn_no_tool_no_content_count=sum(
            run.empty_turn_no_tool_no_content_count for run in per_run
        ),
        schema_malformed_turn_count=sum(
            run.schema_malformed_turn_count for run in per_run
        ),
        recovered_format_drift_count=sum(
            run.recovered_format_drift_count for run in per_run
        ),
        compat_leak_count=sum(run.compat_leak_count for run in per_run),
        truncated_tool_block_count=sum(
            run.truncated_tool_block_count for run in per_run
        ),
        unrecovered_validation_failure_count=sum(
            run.unrecovered_validation_failure_count for run in per_run
        ),
        tool_execution_failure_unrecovered_count=sum(
            run.tool_execution_failure_unrecovered_count for run in per_run
        ),
        validation_issue_count=sum(run.validation_issue_count for run in per_run),
        validation_retry_count=sum(run.validation_retry_count for run in per_run),
        revision_after_validation_failure_count=sum(
            run.revision_after_validation_failure_count for run in per_run
        ),
        token_budget_compaction_turn_count=sum(
            run.token_budget_compaction_turn_count for run in per_run
        ),
        runs_with_validation_failure=sum(1 for run in per_run if run.saw_validation_failure),
        runs_with_revision_after_failure=sum(
            1 for run in per_run if run.saw_revision_after_failure
        ),
        runs_with_finish_deferred=sum(1 for run in per_run if run.saw_finish_deferred),
        runs_with_compaction=sum(1 for run in per_run if run.saw_compaction),
        runs_with_validation_budget_exhausted=sum(
            1 for run in per_run if run.saw_validation_budget_exhausted
        ),
        runs_with_revision_budget_exhausted=sum(
            1 for run in per_run if run.saw_revision_budget_exhausted
        ),
        runs_with_finish_blocked_by_validation=sum(
            1 for run in per_run if run.saw_finish_blocked_by_validation
        ),
        runs_with_token_overflow=sum(
            1 for run in per_run if run.saw_token_overflow
        ),
        runs_with_premature_finish=sum(1 for run in per_run if run.saw_premature_finish),
        runs_with_finish_without_progress=sum(
            1 for run in per_run if run.saw_finish_without_progress
        ),
        runs_with_finish_after_recent_failure=sum(
            1 for run in per_run if run.saw_finish_after_recent_failure
        ),
        runs_with_finish_blocked_recent_failure=sum(
            1 for run in per_run if run.saw_finish_blocked_recent_failure
        ),
        runs_with_finish_blocked_post_edit_validation_missing=sum(
            1
            for run in per_run
            if run.saw_finish_blocked_post_edit_validation_missing
        ),
        runs_with_finish_attempt_before_revalidation=sum(
            1 for run in per_run if run.saw_finish_attempt_before_revalidation
        ),
        runs_with_failure_then_no_corrective_progress=sum(
            1 for run in per_run if run.saw_failure_then_no_corrective_progress
        ),
        runs_with_failure_then_successful_revalidation=sum(
            1 for run in per_run if run.saw_failure_then_successful_revalidation
        ),
        runs_with_finish_after_tool_execution_failure=sum(
            1 for run in per_run if run.saw_finish_after_tool_execution_failure
        ),
        runs_with_finish_after_validation_failure_without_revision=sum(
            1
            for run in per_run
            if run.saw_finish_after_validation_failure_without_revision
        ),
        runs_with_no_progress_after_validation_failure=sum(
            1 for run in per_run if run.saw_no_progress_after_validation_failure
        ),
        runs_with_tool_progress_stall=sum(
            1 for run in per_run if run.saw_tool_progress_stall
        ),
        runs_with_empty_turn_no_tool_no_content=sum(
            1 for run in per_run if run.saw_empty_turn_no_tool_no_content
        ),
        runs_with_schema_malformed=sum(
            1 for run in per_run if run.saw_schema_malformed
        ),
        runs_with_recovered_format_drift=sum(
            1 for run in per_run if run.saw_recovered_format_drift
        ),
        runs_with_compat_leak=sum(1 for run in per_run if run.saw_compat_leak),
        runs_with_truncated_tool_block=sum(
            1 for run in per_run if run.saw_truncated_tool_block
        ),
        runs_with_unrecovered_validation_failure=sum(
            1 for run in per_run if run.saw_unrecovered_validation_failure
        ),
        runs_with_tool_execution_failure_unrecovered=sum(
            1 for run in per_run if run.saw_tool_execution_failure_unrecovered
        ),
        runs_with_parse_error=sum(1 for run in per_run if run.saw_parse_error),
        runs_with_llm_error=sum(1 for run in per_run if run.saw_llm_error),
        runs_with_no_tool_progress=sum(1 for run in per_run if run.saw_no_tool_progress),
        mean_validation_attempts_per_issue=round(
            sum(run.mean_validation_attempts_per_issue * run.validation_issue_count for run in per_run)
            / validation_issue_denominator,
            4,
        ),
        mean_revision_attempts_per_issue=round(
            sum(run.mean_revision_attempts_per_issue * run.validation_issue_count for run in per_run)
            / validation_issue_denominator,
            4,
        ),
        per_run=per_run,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(audit.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    return audit


def _summarize_run(run_dir: Path) -> RunBehaviorSummary:
    trajectory = json.loads((run_dir / "trajectory.json").read_text(encoding="utf-8"))
    trace_path = run_dir / "runtime_trace.jsonl"
    if trace_path.exists():
        events = [
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
        events = []

    validation_turn_count = 0
    revalidation_turn_count = 0
    revision_turn_count = 0
    finish_deferred_count = 0
    finish_attempt_count = 0
    finish_blocked_count = 0
    compaction_turn_count = 0
    premature_finish_count = 0
    finish_without_progress_count = 0
    finish_after_recent_failure_count = 0
    finish_blocked_recent_failure_count = 0
    finish_blocked_post_edit_validation_missing_count = 0
    finish_attempt_before_revalidation_count = 0
    failure_then_no_corrective_progress_count = 0
    failure_then_successful_revalidation_count = 0
    finish_after_tool_execution_failure_count = 0
    finish_after_validation_failure_without_revision_count = 0
    no_progress_after_validation_failure_count = 0
    tool_progress_stall_count = 0
    empty_turn_no_tool_no_content_count = 0
    schema_malformed_turn_count = 0
    recovered_format_drift_count = 0
    compat_leak_count = 0
    truncated_tool_block_count = 0
    unrecovered_validation_failure_count = 0
    tool_execution_failure_unrecovered_count = 0
    validation_issue_count = 0
    validation_retry_count = 0
    revision_after_validation_failure_count = 0
    token_budget_compaction_turn_count = 0
    saw_validation_failure = False
    saw_finish_deferred = False
    saw_compaction = False
    saw_failure_before_revision = False
    saw_revision_after_failure = False
    saw_validation_budget_exhausted = False
    saw_revision_budget_exhausted = False
    saw_finish_blocked_by_validation = False
    saw_token_overflow = False
    saw_premature_finish = False
    saw_finish_without_progress = False
    saw_finish_after_recent_failure = False
    saw_finish_blocked_recent_failure = False
    saw_finish_blocked_post_edit_validation_missing = False
    saw_finish_attempt_before_revalidation = False
    saw_failure_then_no_corrective_progress = False
    saw_failure_then_successful_revalidation = False
    saw_finish_after_tool_execution_failure = False
    saw_finish_after_validation_failure_without_revision = False
    saw_no_progress_after_validation_failure = False
    saw_tool_progress_stall = False
    saw_empty_turn_no_tool_no_content = False
    saw_schema_malformed = False
    saw_recovered_format_drift = False
    saw_compat_leak = False
    saw_truncated_tool_block = False
    saw_unrecovered_validation_failure = False
    saw_tool_execution_failure_unrecovered = False
    context_policy_modes: set[str] = set()
    issue_ids: set[str] = set()
    validation_attempt_counts: list[int] = []
    revision_attempt_counts: list[int] = []
    saw_recovery_after_validation_failure = False

    for event in events:
        if event["event_kind"] == "turn_started":
            mode = event["data"].get("context_policy_mode")
            if mode:
                context_policy_modes.add(mode)
            continue

        if event["event_kind"] == "model_request_built":
            if event["data"].get("compaction_applied"):
                compaction_turn_count += 1
                saw_compaction = True
            if event["data"].get("token_overflow", 0) > 0:
                saw_token_overflow = True
            if event["data"].get("compaction_applied") and event["data"].get("context_max_tokens") is not None:
                token_budget_compaction_turn_count += 1
            continue

        if event["event_kind"] == "assistant_parse_completed":
            parse_errors = event["data"].get("parse_errors") or []
            parse_status = event["data"].get("parse_status") or (
                "fatal" if parse_errors else "ok"
            )
            recovery_warnings = event["data"].get("recovery_warnings") or []
            if parse_errors:
                schema_malformed_turn_count += 1
                saw_schema_malformed = True
            if parse_status == "recovered":
                recovered_format_drift_count += 1
                saw_recovered_format_drift = True
            if "stray_compat_tag_removed" in recovery_warnings:
                compat_leak_count += 1
                saw_compat_leak = True
            if "recovered_missing_tool_end" in recovery_warnings or any(
                "Unclosed tool block" in error for error in parse_errors
            ):
                truncated_tool_block_count += 1
                saw_truncated_tool_block = True
            if (
                not event["data"].get("assistant_content_present", False)
                and int(event["data"].get("tool_call_count", 0) or 0) == 0
            ):
                empty_turn_no_tool_no_content_count += 1
                saw_empty_turn_no_tool_no_content = True
            continue

        if event["event_kind"] != "turn_stop_decision":
            continue

        action = event["data"].get("turn_action")
        outcome = event["data"].get("turn_outcome")
        completion_block_family = str(
            event["data"].get("completion_block_family") or "none"
        )
        if event["data"].get("finish_attempted"):
            finish_attempt_count += 1
        if event["data"].get("finish_blocked_by_policy"):
            finish_blocked_count += 1
        stop_hook_reason_code = str(
            event["data"].get("stop_hook_reason_code") or "none"
        )
        finish_block_reason = event["data"].get("finish_block_reason")
        if stop_hook_reason_code == "pending_issue" or completion_block_family == "pending_issue":
            finish_blocked_recent_failure_count += 1
            saw_finish_blocked_recent_failure = True
        elif (
            stop_hook_reason_code == "validation_required"
            or completion_block_family == "validation_evidence"
            or finish_block_reason == "missing_validation_evidence"
        ):
            finish_blocked_post_edit_validation_missing_count += 1
            saw_finish_blocked_post_edit_validation_missing = True
        issue_kind = event["data"].get("active_validation_issue_kind")
        if issue_kind:
            issue_key = f"{issue_kind}:{event.get('turn_index')}"
            if event["data"].get("validation_attempt_count") in {0, None}:
                issue_key = issue_kind
            if issue_key not in issue_ids:
                issue_ids.add(issue_key)
                validation_issue_count += 1
            if event["data"].get("validation_attempt_count") is not None:
                validation_attempt_counts.append(int(event["data"]["validation_attempt_count"]))
            if event["data"].get("revision_attempt_count") is not None:
                revision_attempt_counts.append(int(event["data"]["revision_attempt_count"]))

        if action in {"validate", "revalidate", "mixed", "revision_and_revalidation"}:
            validation_turn_count += 1
        if action == "revalidate":
            revalidation_turn_count += 1
            validation_retry_count += 1
        if action in {"revise", "revision_and_revalidation"}:
            revision_turn_count += 1
            if saw_validation_failure:
                saw_recovery_after_validation_failure = True
            if saw_failure_before_revision:
                saw_revision_after_failure = True
                revision_after_validation_failure_count += 1
        if action == "revalidate" and saw_validation_failure:
            saw_recovery_after_validation_failure = True
        if outcome == "validation_failed":
            saw_validation_failure = True
            saw_failure_before_revision = True
        if outcome == "validation_passed" and saw_validation_failure:
            saw_recovery_after_validation_failure = True
            failure_then_successful_revalidation_count += 1
            saw_failure_then_successful_revalidation = True
        if outcome in {"finish_deferred", "finish_blocked_by_validation"}:
            finish_deferred_count += 1
            saw_finish_deferred = True
        if outcome == "finish_blocked_by_validation":
            saw_finish_blocked_by_validation = True
            if action == "finish_attempt":
                premature_finish_count += 1
                saw_premature_finish = True
                tool_progress_stall_count += 1
                saw_tool_progress_stall = True
        if (
            stop_hook_reason_code == "no_progress"
            and finish_block_reason == "no_meaningful_progress"
        ) or (
            completion_block_family == "progress_gate"
            and finish_block_reason == "no_meaningful_progress"
        ) or (
            not event["data"].get("meaningful_progress_observed", True)
            and event["data"].get("finish_attempted")
        ):
            finish_without_progress_count += 1
            saw_finish_without_progress = True
        if event["data"].get("recent_failure_kind") and event["data"].get("finish_attempted"):
            finish_after_recent_failure_count += 1
            saw_finish_after_recent_failure = True
        if (
            event["data"].get("finish_attempted")
            and event["data"].get("expected_next_step") == "revalidate"
        ):
            finish_attempt_before_revalidation_count += 1
            saw_finish_attempt_before_revalidation = True
        if (
            event["data"].get("active_failure_kind") is not None
            and completion_block_family == "progress_gate"
            and not event["data"].get("corrective_progress_after_failure", True)
        ):
            failure_then_no_corrective_progress_count += 1
            saw_failure_then_no_corrective_progress = True
        if (
            event["data"].get("finish_attempted")
            and event["data"].get("recent_failure_kind") == "tool_failure"
        ):
            finish_after_tool_execution_failure_count += 1
            saw_finish_after_tool_execution_failure = True
        if (
            event["data"].get("finish_attempted")
            and event["data"].get("recent_failure_kind") == "validation_failure"
            and revision_turn_count == 0
        ):
            finish_after_validation_failure_without_revision_count += 1
            saw_finish_after_validation_failure_without_revision = True
        if outcome == "validation_budget_exhausted":
            saw_validation_budget_exhausted = True
        if outcome == "revision_budget_exhausted":
            saw_revision_budget_exhausted = True
        if (
            action == "none"
            and not event["data"].get("should_stop", False)
            and event["data"].get("decision_code", "").startswith("defer_no_tool_calls")
        ):
            tool_progress_stall_count += 1
            saw_tool_progress_stall = True

    verifier = trajectory.get("verifier") or {}
    metadata = trajectory.get("metadata", {})
    tool_calls = trajectory.get("tool_calls") or []
    non_finish_tool_call_count = sum(
        1
        for call in tool_calls
        if str(call.get("canonical_name") or call.get("name") or "") != "finish"
    )
    parse_error_count = int(metadata.get("parse_errors", 0) or 0)
    llm_error_type = metadata.get("llm_error_type")
    final_validation_phase = metadata.get("validation_phase")
    observed_failure_buckets = sorted(
        str(bucket)
        for bucket in (metadata.get("observed_failure_buckets") or [])
    )
    if saw_validation_failure and not saw_recovery_after_validation_failure:
        no_progress_after_validation_failure_count = 1
        saw_no_progress_after_validation_failure = True
    if saw_validation_failure and final_validation_phase != "validated":
        unrecovered_validation_failure_count = 1
        saw_unrecovered_validation_failure = True
    for index, observation in enumerate(trajectory.get("observations") or []):
        tool_name = str(
            observation.get("canonical_name")
            or observation.get("tool_name")
            or observation.get("call", {}).get("canonical_name")
            or observation.get("call", {}).get("name")
            or ""
        )
        result = observation.get("result") or {}
        if tool_name == "finish":
            continue
        if bool(result.get("ok")) and not bool(result.get("is_error")):
            continue
        later_success = False
        for later in (trajectory.get("observations") or [])[index + 1 :]:
            later_tool_name = str(
                later.get("canonical_name")
                or later.get("tool_name")
                or later.get("call", {}).get("canonical_name")
                or later.get("call", {}).get("name")
                or ""
            )
            later_result = later.get("result") or {}
            if later_tool_name == "finish":
                continue
            if bool(later_result.get("ok")) and not bool(later_result.get("is_error")):
                later_success = True
                break
        if not later_success:
            tool_execution_failure_unrecovered_count = 1
            saw_tool_execution_failure_unrecovered = True
            break
    mean_validation_attempts = (
        round(sum(validation_attempt_counts) / len(validation_attempt_counts), 4)
        if validation_attempt_counts
        else 0.0
    )
    mean_revision_attempts = (
        round(sum(revision_attempt_counts) / len(revision_attempt_counts), 4)
        if revision_attempt_counts
        else 0.0
    )
    return RunBehaviorSummary(
        run_dir=str(run_dir),
        task_id=trajectory["task_id"],
        profile_id=trajectory["tool_profile_id"],
        status=trajectory["status"],
        passed=bool(verifier.get("passed", False)),
        turn_count=int(trajectory.get("metadata", {}).get("total_turns", 0)),
        stop_reason=metadata.get("stop_reason"),
        stop_decision_code=metadata.get("stop_decision_code"),
        final_validation_phase=final_validation_phase,
        completion_evidence_status=metadata.get("completion_evidence_status"),
        final_expected_next_step=metadata.get("expected_next_step"),
        final_completion_gate_status=metadata.get("completion_gate_status"),
        parse_error_count=parse_error_count,
        llm_error_type=llm_error_type,
        tool_call_count=len(tool_calls),
        non_finish_tool_call_count=non_finish_tool_call_count,
        validation_turn_count=validation_turn_count,
        revalidation_turn_count=revalidation_turn_count,
        revision_turn_count=revision_turn_count,
        finish_deferred_count=finish_deferred_count,
        finish_attempt_count=finish_attempt_count,
        finish_blocked_count=finish_blocked_count,
        compaction_turn_count=compaction_turn_count,
        premature_finish_count=premature_finish_count,
        finish_without_progress_count=finish_without_progress_count,
        finish_after_recent_failure_count=finish_after_recent_failure_count,
        finish_blocked_recent_failure_count=finish_blocked_recent_failure_count,
        finish_blocked_post_edit_validation_missing_count=(
            finish_blocked_post_edit_validation_missing_count
        ),
        finish_attempt_before_revalidation_count=(
            finish_attempt_before_revalidation_count
        ),
        failure_then_no_corrective_progress_count=(
            failure_then_no_corrective_progress_count
        ),
        failure_then_successful_revalidation_count=(
            failure_then_successful_revalidation_count
        ),
        finish_after_tool_execution_failure_count=(
            finish_after_tool_execution_failure_count
        ),
        finish_after_validation_failure_without_revision_count=(
            finish_after_validation_failure_without_revision_count
        ),
        no_progress_after_validation_failure_count=no_progress_after_validation_failure_count,
        tool_progress_stall_count=tool_progress_stall_count,
        empty_turn_no_tool_no_content_count=empty_turn_no_tool_no_content_count,
        schema_malformed_turn_count=schema_malformed_turn_count,
        recovered_format_drift_count=recovered_format_drift_count,
        compat_leak_count=compat_leak_count,
        truncated_tool_block_count=truncated_tool_block_count,
        unrecovered_validation_failure_count=unrecovered_validation_failure_count,
        tool_execution_failure_unrecovered_count=tool_execution_failure_unrecovered_count,
        validation_issue_count=validation_issue_count,
        validation_retry_count=validation_retry_count,
        revision_after_validation_failure_count=revision_after_validation_failure_count,
        token_budget_compaction_turn_count=token_budget_compaction_turn_count,
        mean_validation_attempts_per_issue=mean_validation_attempts,
        mean_revision_attempts_per_issue=mean_revision_attempts,
        saw_validation_failure=saw_validation_failure,
        saw_revision_after_failure=saw_revision_after_failure,
        saw_finish_deferred=saw_finish_deferred,
        saw_compaction=saw_compaction,
        saw_validation_budget_exhausted=saw_validation_budget_exhausted,
        saw_revision_budget_exhausted=saw_revision_budget_exhausted,
        saw_finish_blocked_by_validation=saw_finish_blocked_by_validation,
        saw_token_overflow=saw_token_overflow,
        saw_premature_finish=saw_premature_finish,
        saw_finish_without_progress=saw_finish_without_progress,
        saw_finish_after_recent_failure=saw_finish_after_recent_failure,
        saw_finish_blocked_recent_failure=saw_finish_blocked_recent_failure,
        saw_finish_blocked_post_edit_validation_missing=(
            saw_finish_blocked_post_edit_validation_missing
        ),
        saw_finish_attempt_before_revalidation=(
            saw_finish_attempt_before_revalidation
        ),
        saw_failure_then_no_corrective_progress=(
            saw_failure_then_no_corrective_progress
        ),
        saw_failure_then_successful_revalidation=(
            saw_failure_then_successful_revalidation
        ),
        saw_finish_after_tool_execution_failure=(
            saw_finish_after_tool_execution_failure
        ),
        saw_finish_after_validation_failure_without_revision=(
            saw_finish_after_validation_failure_without_revision
        ),
        saw_no_progress_after_validation_failure=saw_no_progress_after_validation_failure,
        saw_tool_progress_stall=saw_tool_progress_stall,
        saw_empty_turn_no_tool_no_content=saw_empty_turn_no_tool_no_content,
        saw_schema_malformed=saw_schema_malformed or parse_error_count > 0,
        saw_recovered_format_drift=saw_recovered_format_drift,
        saw_compat_leak=saw_compat_leak,
        saw_truncated_tool_block=saw_truncated_tool_block,
        saw_unrecovered_validation_failure=saw_unrecovered_validation_failure,
        saw_tool_execution_failure_unrecovered=saw_tool_execution_failure_unrecovered,
        saw_parse_error=(parse_error_count > 0) or saw_schema_malformed,
        saw_llm_error=bool(llm_error_type),
        saw_no_tool_progress=non_finish_tool_call_count == 0,
        context_policy_modes=sorted(context_policy_modes),
        observed_failure_buckets=observed_failure_buckets,
    )
