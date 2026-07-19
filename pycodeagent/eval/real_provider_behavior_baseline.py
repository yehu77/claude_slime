"""Repeated-run behavior baselines for realistic local-runtime workloads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from pycodeagent.agent.llm_client import BaseLLMClient
from pycodeagent.agent.provider_runtime import (
    RuntimeProviderConfig,
    build_llm_client,
    resolve_runtime_provider_config,
)
from pycodeagent.env.task import CodingTask
from pycodeagent.eval.run_campaign import execute_profile_run_campaigns
from pycodeagent.eval.runtime_behavior_audit import (
    RunBehaviorSummary,
    RuntimeBehaviorAudit,
    build_runtime_behavior_audit,
)
from pycodeagent.tools.bootstrap import ToolStackKind


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TASKS_PATH = _PROJECT_ROOT / "datasets" / "tasks" / "realistic_runtime_tasks.jsonl"


class PromotionGateResult(BaseModel):
    passed: bool
    detail: str


class PerTaskBehaviorBaseline(BaseModel):
    task_id: str
    run_count: int = 0
    completed_run_count: int = 0
    passed_run_count: int = 0
    runs_with_validation_failure: int = 0
    runs_with_revision_after_failure: int = 0
    runs_with_finish_blocked_by_validation: int = 0
    runs_with_premature_finish: int = 0
    runs_with_finish_without_progress: int = 0
    runs_with_finish_after_recent_failure: int = 0
    runs_with_parse_error: int = 0
    runs_with_llm_error: int = 0
    runs_with_no_tool_progress: int = 0
    runs_with_empty_turn_no_tool_no_content: int = 0
    runs_with_recovered_format_drift: int = 0
    runs_with_compat_leak: int = 0
    runs_with_truncated_tool_block: int = 0
    runs_with_unrecovered_validation_failure: int = 0
    runs_with_tool_execution_failure_unrecovered: int = 0


class FailureBucketDetail(BaseModel):
    run_count: int
    run_dirs: list[str] = Field(default_factory=list)


class FailureBucketsReport(BaseModel):
    version: int = 1
    source_type: str
    source_path: str
    run_count: int
    buckets: dict[str, FailureBucketDetail]


class BehaviorBaselineSummary(BaseModel):
    version: int = 1
    source_type: str
    source_path: str
    tasks_path: str | None = None
    tool_stack_kind: ToolStackKind
    profile_mode: str
    repeat_count: int
    task_count: int
    run_count: int
    completed_run_count: int
    pass_count: int
    failed_run_count: int
    pass_rate: float
    provider: dict[str, Any] = Field(default_factory=dict)
    runs_with_validation_failure: int = 0
    runs_with_revision_after_failure: int = 0
    runs_with_finish_blocked_by_validation: int = 0
    runs_with_premature_finish: int = 0
    runs_with_finish_without_progress: int = 0
    runs_with_finish_after_recent_failure: int = 0
    runs_with_parse_error: int = 0
    runs_with_llm_error: int = 0
    runs_with_no_tool_progress: int = 0
    runs_with_no_progress_after_validation_failure: int = 0
    runs_with_tool_progress_stall: int = 0
    runs_with_empty_turn_no_tool_no_content: int = 0
    runs_with_schema_malformed: int = 0
    runs_with_recovered_format_drift: int = 0
    runs_with_compat_leak: int = 0
    runs_with_truncated_tool_block: int = 0
    runs_with_unrecovered_validation_failure: int = 0
    runs_with_tool_execution_failure_unrecovered: int = 0
    per_task: dict[str, PerTaskBehaviorBaseline] = Field(default_factory=dict)
    promotion_gates: dict[str, PromotionGateResult] = Field(default_factory=dict)


class BehaviorBaselineResult(BaseModel):
    output_root: str
    runs_root: str
    runtime_behavior_audit_path: str
    behavior_baseline_summary_path: str
    failure_buckets_path: str
    campaign_group_spec_path: str
    campaign_group_manifest_path: str
    campaign_contract_ok: bool
    provider: dict[str, Any] = Field(default_factory=dict)
    tool_stack_kind: ToolStackKind
    task_count: int
    run_count: int
    repeat_count: int
    profile_mode: str
    summary: BehaviorBaselineSummary
    audit: RuntimeBehaviorAudit
    failure_buckets: FailureBucketsReport


def load_realistic_runtime_tasks(tasks_path: str | Path = _DEFAULT_TASKS_PATH) -> list[CodingTask]:
    tasks_path = Path(tasks_path)
    tasks = CodingTask.from_jsonl(tasks_path)
    resolved_tasks: list[CodingTask] = []
    for task in tasks:
        repo_path = task.repo_path
        if not repo_path.is_absolute():
            repo_path = (_PROJECT_ROOT / repo_path).resolve()
        resolved_tasks.append(task.model_copy(update={"repo_path": repo_path}))
    return resolved_tasks


def run_behavior_baseline(
    tasks: list[CodingTask],
    client_factory: Callable[[CodingTask, int], BaseLLMClient],
    output_root: str | Path,
    *,
    repeat_count: int = 3,
    profile_mode: str = "base",
    source_type: str = "batch",
    tasks_path: str | Path | None = None,
    provider: dict[str, Any] | None = None,
    tool_stack_kind: ToolStackKind,
) -> BehaviorBaselineResult:
    output_root = Path(output_root)
    runs_root = output_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    campaign_result = execute_profile_run_campaigns(
        campaign_id="real_provider_behavior_baseline",
        tasks=tasks,
        client_factory=(
            lambda task, _mode, repeat_index: client_factory(task, repeat_index)
        ),
        output_root=runs_root,
        profile_seed_by_mode={profile_mode: 0},
        repeat_count=repeat_count,
        tool_stack_kind=tool_stack_kind,
        provider=provider,
    )

    audit_path = output_root / "runtime_behavior_audit.json"
    audit = build_runtime_behavior_audit(
        runs_root,
        audit_path,
        source_type=source_type,
    )
    summary = build_behavior_baseline_summary(
        audit,
        profile_mode=profile_mode,
        repeat_count=repeat_count,
        task_count=len(tasks),
        tasks_path=tasks_path,
        provider=provider,
        tool_stack_kind=tool_stack_kind,
    )
    summary_path = output_root / "behavior_baseline_summary.json"
    _write_json(summary_path, summary.model_dump(mode="json"))

    failure_buckets = build_failure_buckets_report(audit)
    failure_buckets_path = output_root / "failure_buckets.json"
    _write_json(failure_buckets_path, failure_buckets.model_dump(mode="json"))

    return BehaviorBaselineResult(
        output_root=str(output_root),
        runs_root=str(runs_root),
        runtime_behavior_audit_path=str(audit_path),
        behavior_baseline_summary_path=str(summary_path),
        failure_buckets_path=str(failure_buckets_path),
        campaign_group_spec_path=campaign_result.spec_path,
        campaign_group_manifest_path=campaign_result.manifest_path,
        campaign_contract_ok=campaign_result.contract_ok,
        provider=dict(provider or {}),
        tool_stack_kind=tool_stack_kind,
        task_count=len(tasks),
        run_count=audit.run_count,
        repeat_count=repeat_count,
        profile_mode=profile_mode,
        summary=summary,
        audit=audit,
        failure_buckets=failure_buckets,
    )


def run_real_provider_behavior_baseline(
    provider_config: RuntimeProviderConfig | str | Path,
    output_root: str | Path,
    *,
    tasks_path: str | Path = _DEFAULT_TASKS_PATH,
    repeat_count: int = 3,
    profile_mode: str = "base",
    tool_stack_kind: ToolStackKind,
) -> BehaviorBaselineResult:
    resolved_provider_config = (
        provider_config
        if isinstance(provider_config, RuntimeProviderConfig)
        else resolve_runtime_provider_config(provider_config)
    )
    tasks = load_realistic_runtime_tasks(tasks_path)
    return run_behavior_baseline(
        tasks,
        lambda _task, _repeat_index: build_llm_client(resolved_provider_config),
        output_root,
        repeat_count=repeat_count,
        profile_mode=profile_mode,
        tasks_path=tasks_path,
        provider=resolved_provider_config.runtime_provenance(),
        tool_stack_kind=tool_stack_kind,
    )


def build_behavior_baseline_summary(
    audit: RuntimeBehaviorAudit,
    *,
    profile_mode: str,
    repeat_count: int,
    task_count: int,
    tasks_path: str | Path | None = None,
    provider: dict[str, Any] | None = None,
    tool_stack_kind: ToolStackKind,
) -> BehaviorBaselineSummary:
    failed_run_count = audit.run_count - audit.passed_run_count
    per_task = _build_per_task_baseline(audit.per_run)
    promotion_gates = _build_promotion_gates(audit.per_run, failed_run_count)
    return BehaviorBaselineSummary(
        source_type=audit.source_type,
        source_path=audit.source_path,
        tasks_path=str(tasks_path) if tasks_path is not None else None,
        tool_stack_kind=tool_stack_kind,
        profile_mode=profile_mode,
        repeat_count=repeat_count,
        task_count=task_count,
        run_count=audit.run_count,
        completed_run_count=audit.completed_run_count,
        pass_count=audit.passed_run_count,
        failed_run_count=failed_run_count,
        pass_rate=round(audit.passed_run_count / audit.run_count, 4) if audit.run_count else 0.0,
        provider=dict(provider or {}),
        runs_with_validation_failure=audit.runs_with_validation_failure,
        runs_with_revision_after_failure=audit.runs_with_revision_after_failure,
        runs_with_finish_blocked_by_validation=audit.runs_with_finish_blocked_by_validation,
        runs_with_premature_finish=audit.runs_with_premature_finish,
        runs_with_finish_without_progress=audit.runs_with_finish_without_progress,
        runs_with_finish_after_recent_failure=audit.runs_with_finish_after_recent_failure,
        runs_with_parse_error=audit.runs_with_parse_error,
        runs_with_llm_error=audit.runs_with_llm_error,
        runs_with_no_tool_progress=audit.runs_with_no_tool_progress,
        runs_with_no_progress_after_validation_failure=(
            audit.runs_with_no_progress_after_validation_failure
        ),
        runs_with_tool_progress_stall=audit.runs_with_tool_progress_stall,
        runs_with_empty_turn_no_tool_no_content=audit.runs_with_empty_turn_no_tool_no_content,
        runs_with_schema_malformed=audit.runs_with_schema_malformed,
        runs_with_recovered_format_drift=audit.runs_with_recovered_format_drift,
        runs_with_compat_leak=audit.runs_with_compat_leak,
        runs_with_truncated_tool_block=audit.runs_with_truncated_tool_block,
        runs_with_unrecovered_validation_failure=(
            audit.runs_with_unrecovered_validation_failure
        ),
        runs_with_tool_execution_failure_unrecovered=(
            audit.runs_with_tool_execution_failure_unrecovered
        ),
        per_task=per_task,
        promotion_gates=promotion_gates,
    )


def build_failure_buckets_report(audit: RuntimeBehaviorAudit) -> FailureBucketsReport:
    return FailureBucketsReport(
        source_type=audit.source_type,
        source_path=audit.source_path,
        run_count=audit.run_count,
        buckets={
            "premature_finish": _bucket_from_runs(audit.per_run, lambda run: run.saw_premature_finish),
            "finish_without_progress": _bucket_from_runs(
                audit.per_run,
                lambda run: run.saw_finish_without_progress,
            ),
            "finish_after_recent_failure": _bucket_from_runs(
                audit.per_run,
                lambda run: run.saw_finish_after_recent_failure,
            ),
            "no_progress_after_validation_failure": _bucket_from_runs(
                audit.per_run,
                lambda run: run.saw_no_progress_after_validation_failure,
            ),
            "tool_progress_stall": _bucket_from_runs(
                audit.per_run,
                lambda run: run.saw_tool_progress_stall,
            ),
            "empty_turn_no_tool_no_content": _bucket_from_runs(
                audit.per_run,
                lambda run: run.saw_empty_turn_no_tool_no_content,
            ),
            "schema_malformed": _bucket_from_runs(
                audit.per_run,
                lambda run: run.saw_schema_malformed,
            ),
            "recovered_format_drift": _bucket_from_runs(
                audit.per_run,
                lambda run: run.saw_recovered_format_drift,
            ),
            "compat_leak": _bucket_from_runs(
                audit.per_run,
                lambda run: run.saw_compat_leak,
            ),
            "truncated_tool_block": _bucket_from_runs(
                audit.per_run,
                lambda run: run.saw_truncated_tool_block,
            ),
            "unrecovered_validation_failure": _bucket_from_runs(
                audit.per_run,
                lambda run: run.saw_unrecovered_validation_failure,
            ),
            "tool_execution_failure_unrecovered": _bucket_from_runs(
                audit.per_run,
                lambda run: run.saw_tool_execution_failure_unrecovered,
            ),
            "parse_error": _bucket_from_runs(audit.per_run, lambda run: run.saw_parse_error),
            "llm_error": _bucket_from_runs(audit.per_run, lambda run: run.saw_llm_error),
            "no_tool_progress": _bucket_from_runs(
                audit.per_run,
                lambda run: run.saw_no_tool_progress,
            ),
        },
    )


def _build_per_task_baseline(
    per_run: list[RunBehaviorSummary],
) -> dict[str, PerTaskBehaviorBaseline]:
    grouped: dict[str, PerTaskBehaviorBaseline] = {}
    for run in per_run:
        summary = grouped.setdefault(run.task_id, PerTaskBehaviorBaseline(task_id=run.task_id))
        summary.run_count += 1
        if run.status == "completed":
            summary.completed_run_count += 1
        if run.passed:
            summary.passed_run_count += 1
        if run.saw_validation_failure:
            summary.runs_with_validation_failure += 1
        if run.saw_revision_after_failure:
            summary.runs_with_revision_after_failure += 1
        if run.saw_finish_blocked_by_validation:
            summary.runs_with_finish_blocked_by_validation += 1
        if run.saw_premature_finish:
            summary.runs_with_premature_finish += 1
        if run.saw_finish_without_progress:
            summary.runs_with_finish_without_progress += 1
        if run.saw_finish_after_recent_failure:
            summary.runs_with_finish_after_recent_failure += 1
        if run.saw_parse_error:
            summary.runs_with_parse_error += 1
        if run.saw_llm_error:
            summary.runs_with_llm_error += 1
        if run.saw_no_tool_progress:
            summary.runs_with_no_tool_progress += 1
        if run.saw_empty_turn_no_tool_no_content:
            summary.runs_with_empty_turn_no_tool_no_content += 1
        if run.saw_recovered_format_drift:
            summary.runs_with_recovered_format_drift += 1
        if run.saw_compat_leak:
            summary.runs_with_compat_leak += 1
        if run.saw_truncated_tool_block:
            summary.runs_with_truncated_tool_block += 1
        if run.saw_unrecovered_validation_failure:
            summary.runs_with_unrecovered_validation_failure += 1
        if run.saw_tool_execution_failure_unrecovered:
            summary.runs_with_tool_execution_failure_unrecovered += 1
    return {task_id: grouped[task_id] for task_id in sorted(grouped)}


def _build_promotion_gates(
    per_run: list[RunBehaviorSummary],
    failed_run_count: int,
) -> dict[str, PromotionGateResult]:
    has_revision_revalidation_success = any(
        run.saw_validation_failure
        and run.saw_revision_after_failure
        and run.revalidation_turn_count > 0
        and run.passed
        for run in per_run
    )
    finish_not_dominant_in_failures = (
        failed_run_count == 0
        or sum(1 for run in per_run if run.saw_premature_finish and not run.passed) < failed_run_count
    )
    validation_gated_not_fake_complete = not any(
        run.status == "completed" and run.final_validation_phase not in {None, "validated", "idle"}
        for run in per_run
    )
    parse_malformed_not_dominant = (
        failed_run_count == 0
        or sum(1 for run in per_run if run.saw_parse_error) < failed_run_count
    )
    not_all_collapsed_to_single_step_finish = any(
        run.non_finish_tool_call_count > 1 for run in per_run
    )

    return {
        "revision_revalidation_finish_pattern_present": PromotionGateResult(
            passed=has_revision_revalidation_success,
            detail=(
                "At least one run reached validation_failed -> revise -> revalidate "
                "-> validated -> finish."
            ),
        ),
        "finish_not_dominant_in_failures": PromotionGateResult(
            passed=finish_not_dominant_in_failures,
            detail=(
                "Premature finish should not dominate failed runs."
            ),
        ),
        "premature_finish_not_dominant_after_protocol_first": PromotionGateResult(
            passed=finish_not_dominant_in_failures,
            detail=(
                "After protocol-first response handling, premature finish should not dominate failed runs."
            ),
        ),
        "validation_gated_runs_not_fake_completed": PromotionGateResult(
            passed=validation_gated_not_fake_complete,
            detail=(
                "Completed runs should not remain stuck in mutated_unvalidated or validation_failed."
            ),
        ),
        "parse_malformed_not_dominant_failure_mode": PromotionGateResult(
            passed=parse_malformed_not_dominant,
            detail=(
                "Parse or malformed-turn failures should not dominate failed runs."
            ),
        ),
        "not_all_runs_collapsed_to_single_step_finish": PromotionGateResult(
            passed=not_all_collapsed_to_single_step_finish,
            detail=(
                "Repeated runs should not all collapse to zero or one non-finish tool call."
            ),
        ),
    }


def _bucket_from_runs(
    per_run: list[RunBehaviorSummary],
    predicate: Callable[[RunBehaviorSummary], bool],
) -> FailureBucketDetail:
    runs = [run.run_dir for run in per_run if predicate(run)]
    return FailureBucketDetail(run_count=len(runs), run_dirs=sorted(runs))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
