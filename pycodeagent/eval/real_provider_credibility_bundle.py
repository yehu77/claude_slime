"""Real-provider repeated-run credibility bundle orchestration."""

from __future__ import annotations

import json
from collections import Counter
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
from pycodeagent.eval.real_provider_behavior_baseline import (
    build_behavior_baseline_summary,
    build_failure_buckets_report,
    load_realistic_runtime_tasks,
)
from pycodeagent.eval.runtime_behavior_audit import (
    RuntimeBehaviorAudit,
    build_runtime_behavior_audit,
)
from pycodeagent.eval.run_campaign import execute_profile_run_campaigns
from pycodeagent.eval.runtime_observed_postrun import (
    RuntimeObservedStudyBundleResult,
    prepare_study_runtime_observed_bundle,
)
from pycodeagent.rl.dataset_manifest import FilterConfig
from pycodeagent.tools.bootstrap import ToolStackKind


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TASKS_PATH = _PROJECT_ROOT / "datasets" / "tasks" / "realistic_runtime_tasks.jsonl"
DEFAULT_CREDIBILITY_PROFILE_MODES: tuple[str, str, str, str] = (
    "base",
    "argument_rename",
    "schema_flat_to_nested",
    "tool_reorder",
)
DEFAULT_CREDIBILITY_PROFILE_SEED_BY_MODE: dict[str, int] = {
    "base": 0,
    "argument_rename": 0,
    "schema_flat_to_nested": 0,
    "tool_reorder": 0,
}
DEFAULT_CREDIBILITY_REPEAT_COUNT = 3


class CredibilityGateResult(BaseModel):
    """One top-level credibility gate result."""

    passed: bool
    detail: str


class RealProviderCredibilityBundleResult(BaseModel):
    """Top-level result for a real-provider repeated-run credibility bundle."""

    output_root: str
    source_runs_root: str
    tasks_path: str | None = None
    provider: dict[str, Any] = Field(default_factory=dict)
    tool_stack_kind: ToolStackKind
    profile_modes: list[str] = Field(default_factory=list)
    profile_seed_by_mode: dict[str, int] = Field(default_factory=dict)
    repeat_count: int
    total_source_run_count: int
    completed_source_run_count: int
    included_observed_run_count: int
    observed_sample_count: int
    trace_backed_sample_count: int
    trace_backed_sample_rate: float
    critical_reconciliation_error_count: int
    contract_ok: bool
    runtime_behavior_audit_path: str
    behavior_baseline_summary_path: str
    failure_buckets_path: str
    runtime_observed_bundle_root: str
    runtime_observed_bundle_path: str
    runtime_execution_reconciliation_path: str
    credibility_summary_path: str
    credibility_manifest_path: str
    credibility_gates_path: str
    campaign_group_spec_path: str | None = None
    campaign_group_manifest_path: str | None = None
    campaign_contract_ok: bool | None = None


def run_real_provider_credibility_bundle(
    provider_config: RuntimeProviderConfig | str | Path,
    output_root: str | Path,
    *,
    tasks_path: str | Path = _DEFAULT_TASKS_PATH,
    profile_modes: list[str] | tuple[str, ...] = DEFAULT_CREDIBILITY_PROFILE_MODES,
    profile_seed_by_mode: dict[str, int] | None = None,
    repeat_count: int = DEFAULT_CREDIBILITY_REPEAT_COUNT,
    tool_stack_kind: ToolStackKind,
    observed_filter_config: FilterConfig | None = None,
    split: str = "train",
    max_length: int = 2048,
    batch_size: int = 8,
    learning_rate: float = 1e-4,
    max_steps: int = 1000,
    seed: int = 42,
    tokenizer: Any | None = None,
    tokenizer_config: Any | None = None,
    fake_tokenizer_config: Any | None = None,
    run_id: str = "real_provider_credibility_bundle",
) -> RealProviderCredibilityBundleResult:
    """Run repeated real-provider source runs and build one credibility bundle."""
    resolved_provider_config = (
        provider_config
        if isinstance(provider_config, RuntimeProviderConfig)
        else resolve_runtime_provider_config(provider_config)
    )
    tasks = load_realistic_runtime_tasks(tasks_path)
    return run_provider_credibility_bundle(
        tasks,
        lambda _task, _mode, _repeat_index: build_llm_client(resolved_provider_config),
        output_root,
        tasks_path=tasks_path,
        provider=resolved_provider_config.runtime_provenance(),
        profile_modes=profile_modes,
        profile_seed_by_mode=profile_seed_by_mode,
        repeat_count=repeat_count,
        tool_stack_kind=tool_stack_kind,
        observed_filter_config=observed_filter_config,
        split=split,
        max_length=max_length,
        batch_size=batch_size,
        learning_rate=learning_rate,
        max_steps=max_steps,
        seed=seed,
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        fake_tokenizer_config=fake_tokenizer_config,
        run_id=run_id,
    )


def run_provider_credibility_bundle(
    tasks: list[CodingTask],
    client_factory: Callable[[CodingTask, str, int], BaseLLMClient],
    output_root: str | Path,
    *,
    tasks_path: str | Path | None = None,
    provider: dict[str, Any] | None = None,
    profile_modes: list[str] | tuple[str, ...] = DEFAULT_CREDIBILITY_PROFILE_MODES,
    profile_seed_by_mode: dict[str, int] | None = None,
    repeat_count: int = DEFAULT_CREDIBILITY_REPEAT_COUNT,
    tool_stack_kind: ToolStackKind,
    observed_filter_config: FilterConfig | None = None,
    split: str = "train",
    max_length: int = 2048,
    batch_size: int = 8,
    learning_rate: float = 1e-4,
    max_steps: int = 1000,
    seed: int = 42,
    tokenizer: Any | None = None,
    tokenizer_config: Any | None = None,
    fake_tokenizer_config: Any | None = None,
    run_id: str = "real_provider_credibility_bundle",
) -> RealProviderCredibilityBundleResult:
    """Run repeated source runs under fixed profile modes and build credibility reports."""
    output_root = Path(output_root)
    source_runs_root = output_root / "runs"
    source_runs_root.mkdir(parents=True, exist_ok=True)
    normalized_modes = [str(mode) for mode in profile_modes]
    normalized_profile_seeds = _normalized_profile_seed_by_mode(
        normalized_modes,
        profile_seed_by_mode,
    )
    campaign_result = execute_profile_run_campaigns(
        campaign_id="real_provider_credibility_bundle",
        tasks=tasks,
        client_factory=client_factory,
        output_root=source_runs_root,
        profile_seed_by_mode=normalized_profile_seeds,
        repeat_count=repeat_count,
        tool_stack_kind=tool_stack_kind,
        provider=provider,
    )
    return build_real_provider_credibility_bundle_from_runs(
        source_runs_root,
        output_root,
        tasks_path=tasks_path,
        provider=provider,
        profile_modes=profile_modes,
        profile_seed_by_mode=profile_seed_by_mode,
        repeat_count=repeat_count,
        tool_stack_kind=tool_stack_kind,
        observed_filter_config=observed_filter_config,
        split=split,
        max_length=max_length,
        batch_size=batch_size,
        learning_rate=learning_rate,
        max_steps=max_steps,
        seed=seed,
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        fake_tokenizer_config=fake_tokenizer_config,
        run_id=run_id,
        campaign_group_spec_path=campaign_result.spec_path,
        campaign_group_manifest_path=campaign_result.manifest_path,
        campaign_contract_ok=campaign_result.contract_ok,
    )


def build_real_provider_credibility_bundle_from_runs(
    source_runs_root: str | Path,
    output_root: str | Path,
    *,
    tasks_path: str | Path | None = None,
    provider: dict[str, Any] | None = None,
    profile_modes: list[str] | tuple[str, ...] = DEFAULT_CREDIBILITY_PROFILE_MODES,
    profile_seed_by_mode: dict[str, int] | None = None,
    repeat_count: int = DEFAULT_CREDIBILITY_REPEAT_COUNT,
    tool_stack_kind: ToolStackKind,
    observed_filter_config: FilterConfig | None = None,
    split: str = "train",
    max_length: int = 2048,
    batch_size: int = 8,
    learning_rate: float = 1e-4,
    max_steps: int = 1000,
    seed: int = 42,
    tokenizer: Any | None = None,
    tokenizer_config: Any | None = None,
    fake_tokenizer_config: Any | None = None,
    run_id: str = "real_provider_credibility_bundle",
    campaign_group_spec_path: str | Path | None = None,
    campaign_group_manifest_path: str | Path | None = None,
    campaign_contract_ok: bool | None = None,
) -> RealProviderCredibilityBundleResult:
    """Build credibility reports and nested observed bundle from existing source runs."""
    source_runs_root = Path(source_runs_root)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    normalized_modes = [str(mode) for mode in profile_modes]
    normalized_profile_seeds = _normalized_profile_seed_by_mode(
        normalized_modes,
        profile_seed_by_mode,
    )
    normalized_provider = dict(provider or {})

    audit_path = output_root / "runtime_behavior_audit.json"
    behavior_audit = build_runtime_behavior_audit(
        source_runs_root,
        audit_path,
        source_type="batch",
    )
    behavior_summary = build_behavior_baseline_summary(
        behavior_audit,
        profile_mode="+".join(normalized_modes),
        repeat_count=repeat_count,
        task_count=_count_unique_tasks(behavior_audit),
        tasks_path=tasks_path,
        provider=normalized_provider,
        tool_stack_kind=tool_stack_kind,
    )
    behavior_summary_path = output_root / "behavior_baseline_summary.json"
    _write_json(behavior_summary_path, behavior_summary.model_dump(mode="json"))

    failure_buckets = build_failure_buckets_report(behavior_audit)
    failure_buckets_path = output_root / "failure_buckets.json"
    _write_json(failure_buckets_path, failure_buckets.model_dump(mode="json"))

    runtime_observed_bundle_root = output_root / "runtime_observed_bundle"
    runtime_observed_bundle = prepare_study_runtime_observed_bundle(
        source_runs_root,
        runtime_observed_bundle_root,
        source_type="batch",
        filter_config=observed_filter_config,
        split=split,
        max_length=max_length,
        batch_size=batch_size,
        learning_rate=learning_rate,
        max_steps=max_steps,
        seed=seed,
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        fake_tokenizer_config=fake_tokenizer_config,
        run_id=run_id,
    )

    raw_source_manifest = _read_json(Path(runtime_observed_bundle.raw_source_manifest_path))
    source_run_count_by_mode = Counter(
        str(run.get("source_profile_mode", "unknown"))
        for run in raw_source_manifest.get("runs", [])
    )
    completed_source_run_count_by_mode = Counter(
        str(run.get("source_profile_mode", "unknown"))
        for run in raw_source_manifest.get("runs", [])
        if str(run.get("status")) == "completed"
    )

    gates = _build_credibility_gates(
        provider=normalized_provider,
        raw_source_manifest=raw_source_manifest,
        runtime_observed_bundle=runtime_observed_bundle,
        configured_modes=normalized_modes,
    )
    contract_ok = all(gate.passed for gate in gates.values()) and (
        campaign_contract_ok is not False
    )

    credibility_summary = {
        "version": 1,
        "tasks_path": str(tasks_path) if tasks_path is not None else None,
        "provider": normalized_provider,
        "profile_modes": normalized_modes,
        "profile_seed_by_mode": normalized_profile_seeds,
        "repeat_count": repeat_count,
        "tool_stack_kind": tool_stack_kind,
        "total_source_run_count": behavior_audit.run_count,
        "completed_source_run_count": behavior_audit.completed_run_count,
        "included_observed_run_count": runtime_observed_bundle.included_run_count,
        "observed_sample_count": runtime_observed_bundle.observed_sample_count,
        "trace_backed_sample_count": runtime_observed_bundle.trace_backed_sample_count,
        "trace_backed_sample_rate": runtime_observed_bundle.trace_backed_sample_rate,
        "reconciliation_ok_count": runtime_observed_bundle.reconciliation_ok_count,
        "reconciliation_error_count": runtime_observed_bundle.reconciliation_error_count,
        "critical_reconciliation_error_count": (
            runtime_observed_bundle.critical_reconciliation_error_count
        ),
        "task_count": behavior_summary.task_count,
        "source_run_count_by_mode": _sorted_mapping(source_run_count_by_mode),
        "completed_source_run_count_by_mode": _sorted_mapping(
            completed_source_run_count_by_mode
        ),
        "sample_count_by_mode": dict(runtime_observed_bundle.sample_count_by_mode),
        "sample_count_by_canonical_tool": dict(
            runtime_observed_bundle.sample_count_by_canonical_tool
        ),
        "sample_count_by_execution_kind": dict(
            runtime_observed_bundle.sample_count_by_execution_kind
        ),
        "sample_count_by_policy_decision": dict(
            runtime_observed_bundle.sample_count_by_policy_decision
        ),
        "deny_count_by_policy_reason_code": dict(
            runtime_observed_bundle.deny_count_by_policy_reason_code
        ),
        "runs_with_validation_failure": behavior_summary.runs_with_validation_failure,
        "runs_with_revision_after_failure": behavior_summary.runs_with_revision_after_failure,
        "runs_with_finish_blocked_by_validation": (
            behavior_summary.runs_with_finish_blocked_by_validation
        ),
        "runs_with_premature_finish": behavior_summary.runs_with_premature_finish,
        "runs_with_no_tool_progress": behavior_summary.runs_with_no_tool_progress,
        "runs_with_schema_malformed": behavior_summary.runs_with_schema_malformed,
        "runs_with_parse_error": behavior_summary.runs_with_parse_error,
        "campaign_group_spec_path": (
            str(campaign_group_spec_path)
            if campaign_group_spec_path is not None
            else None
        ),
        "campaign_group_manifest_path": (
            str(campaign_group_manifest_path)
            if campaign_group_manifest_path is not None
            else None
        ),
        "campaign_contract_ok": campaign_contract_ok,
        "contract_ok": contract_ok,
    }
    credibility_summary_path = output_root / "real_provider_credibility_summary.json"
    _write_json(credibility_summary_path, credibility_summary)

    credibility_manifest = {
        "version": 1,
        "bundle_type": "real_provider_credibility_bundle",
        "output_root": str(output_root),
        "source_runs_root": str(source_runs_root),
        "tasks_path": str(tasks_path) if tasks_path is not None else None,
        "provider": normalized_provider,
        "profile_modes": normalized_modes,
        "profile_seed_by_mode": normalized_profile_seeds,
        "repeat_count": repeat_count,
        "tool_stack_kind": tool_stack_kind,
        "contract_ok": contract_ok,
        "paths": {
            "runtime_behavior_audit_path": str(audit_path),
            "behavior_baseline_summary_path": str(behavior_summary_path),
            "failure_buckets_path": str(failure_buckets_path),
            "runtime_observed_bundle_root": str(runtime_observed_bundle_root),
            "runtime_observed_bundle_path": str(
                runtime_observed_bundle_root / "runtime_observed_bundle.json"
            ),
            "runtime_execution_reconciliation_path": (
                runtime_observed_bundle.runtime_execution_reconciliation_path
            ),
            "credibility_summary_path": str(credibility_summary_path),
            "credibility_gates_path": str(
                output_root / "real_provider_credibility_gates.json"
            ),
            "campaign_group_spec_path": (
                str(campaign_group_spec_path)
                if campaign_group_spec_path is not None
                else None
            ),
            "campaign_group_manifest_path": (
                str(campaign_group_manifest_path)
                if campaign_group_manifest_path is not None
                else None
            ),
        },
        "campaign_contract_ok": campaign_contract_ok,
    }
    credibility_manifest_path = output_root / "real_provider_credibility_manifest.json"
    _write_json(credibility_manifest_path, credibility_manifest)

    gates_payload = {
        "version": 1,
        "contract_ok": contract_ok,
        "gates": {
            gate_name: gate.model_dump(mode="json")
            for gate_name, gate in gates.items()
        },
    }
    credibility_gates_path = output_root / "real_provider_credibility_gates.json"
    _write_json(credibility_gates_path, gates_payload)

    return RealProviderCredibilityBundleResult(
        output_root=str(output_root),
        source_runs_root=str(source_runs_root),
        tasks_path=(str(tasks_path) if tasks_path is not None else None),
        provider=normalized_provider,
        tool_stack_kind=tool_stack_kind,
        profile_modes=normalized_modes,
        profile_seed_by_mode=normalized_profile_seeds,
        repeat_count=repeat_count,
        total_source_run_count=behavior_audit.run_count,
        completed_source_run_count=behavior_audit.completed_run_count,
        included_observed_run_count=runtime_observed_bundle.included_run_count,
        observed_sample_count=runtime_observed_bundle.observed_sample_count,
        trace_backed_sample_count=runtime_observed_bundle.trace_backed_sample_count,
        trace_backed_sample_rate=runtime_observed_bundle.trace_backed_sample_rate,
        critical_reconciliation_error_count=(
            runtime_observed_bundle.critical_reconciliation_error_count
        ),
        contract_ok=contract_ok,
        runtime_behavior_audit_path=str(audit_path),
        behavior_baseline_summary_path=str(behavior_summary_path),
        failure_buckets_path=str(failure_buckets_path),
        runtime_observed_bundle_root=str(runtime_observed_bundle_root),
        runtime_observed_bundle_path=str(
            runtime_observed_bundle_root / "runtime_observed_bundle.json"
        ),
        runtime_execution_reconciliation_path=(
            runtime_observed_bundle.runtime_execution_reconciliation_path
        ),
        credibility_summary_path=str(credibility_summary_path),
        credibility_manifest_path=str(credibility_manifest_path),
        credibility_gates_path=str(credibility_gates_path),
        campaign_group_spec_path=(
            str(campaign_group_spec_path)
            if campaign_group_spec_path is not None
            else None
        ),
        campaign_group_manifest_path=(
            str(campaign_group_manifest_path)
            if campaign_group_manifest_path is not None
            else None
        ),
        campaign_contract_ok=campaign_contract_ok,
    )


def _normalized_profile_seed_by_mode(
    profile_modes: list[str],
    profile_seed_by_mode: dict[str, int] | None,
) -> dict[str, int]:
    mapping = dict(DEFAULT_CREDIBILITY_PROFILE_SEED_BY_MODE)
    if profile_seed_by_mode:
        for mode, seed in profile_seed_by_mode.items():
            mapping[str(mode)] = int(seed)
    return {mode: int(mapping.get(mode, 0)) for mode in profile_modes}


def _build_credibility_gates(
    *,
    provider: dict[str, Any],
    raw_source_manifest: dict[str, Any],
    runtime_observed_bundle: RuntimeObservedStudyBundleResult,
    configured_modes: list[str],
) -> dict[str, CredibilityGateResult]:
    runs = raw_source_manifest.get("runs", [])
    provider_fields = [
        "provider_kind",
        "client_mode",
        "model",
        "base_url",
        "api_key_env",
    ]
    provider_complete = all(provider.get(field) not in {None, ""} for field in provider_fields) and all(
        all(run.get(field) not in {None, ""} for field in provider_fields) for run in runs
    )
    source_run_count_by_mode = Counter(
        str(run.get("source_profile_mode", "unknown")) for run in runs
    )
    mode_coverage_ok = all(source_run_count_by_mode.get(mode, 0) > 0 for mode in configured_modes)
    runtime_trace_coverage_ok = (
        runtime_observed_bundle.included_run_count == 0
        or runtime_observed_bundle.runtime_trace_present_count
        == runtime_observed_bundle.included_run_count
    )
    trace_backed_samples_present = runtime_observed_bundle.trace_backed_sample_count > 0
    reconciliation_critical_ok = (
        runtime_observed_bundle.critical_reconciliation_error_count == 0
    )
    mutated_modes = [mode for mode in configured_modes if mode != "base"]
    mutated_mode_samples_present = all(
        runtime_observed_bundle.sample_count_by_mode.get(mode, 0) > 0
        for mode in mutated_modes
    )
    training_prep_contract_ok = runtime_observed_bundle.contract_ok

    return {
        "provider_provenance_complete": CredibilityGateResult(
            passed=provider_complete,
            detail=(
                "Top-level provider provenance and per-run source-manifest provider fields must be present."
            ),
        ),
        "mode_coverage_ok": CredibilityGateResult(
            passed=mode_coverage_ok,
            detail="All configured modes must produce repeated source runs.",
        ),
        "runtime_trace_coverage_ok": CredibilityGateResult(
            passed=runtime_trace_coverage_ok,
            detail="All observed-included runs must retain runtime traces.",
        ),
        "trace_backed_samples_present": CredibilityGateResult(
            passed=trace_backed_samples_present,
            detail="At least one observed sample must be trace-backed.",
        ),
        "reconciliation_critical_ok": CredibilityGateResult(
            passed=reconciliation_critical_ok,
            detail="Critical execution reconciliation mismatches must be zero.",
        ),
        "mutated_mode_samples_present": CredibilityGateResult(
            passed=mutated_mode_samples_present,
            detail="Each configured mutated mode must produce at least one observed sample.",
        ),
        "training_prep_contract_ok": CredibilityGateResult(
            passed=training_prep_contract_ok,
            detail="Nested runtime-observed bundle contract_ok must be true.",
        ),
    }


def _count_unique_tasks(audit: RuntimeBehaviorAudit) -> int:
    return len({run.task_id for run in audit.per_run})


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sorted_mapping(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
