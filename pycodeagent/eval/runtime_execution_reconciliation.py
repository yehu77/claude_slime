"""Reconcile observed runtime samples against trajectory and runtime trace."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from pycodeagent.rl.dataset_builder import discover_run_dirs
from pycodeagent.rl.schema_following_dataset import read_schema_following_jsonl
from pycodeagent.trajectory.schema import ToolObservation, Trajectory


CRITICAL_MISMATCH_KINDS = {
    "missing_tool_call",
    "missing_mapping_event",
    "missing_execution_event",
    "exposed_name_mismatch",
    "canonical_name_mismatch",
    "tool_result_status_mismatch",
}


class RuntimeExecutionSampleFinding(BaseModel):
    """One observed sample reconciliation result."""

    sample_id: str
    source_run_dir: str
    tool_call_id: str
    exposed_tool_name: str
    canonical_tool_name: str
    execution_kind: str | None = None
    policy_decision: str | None = None
    trace_present: bool = False
    trace_backed: bool = False
    reconciliation_status: Literal["ok", "error"]
    mismatch_reasons: list[str] = Field(default_factory=list)
    critical_mismatch_reasons: list[str] = Field(default_factory=list)


class RuntimeExecutionRunSummary(BaseModel):
    """Per-run reconciliation summary."""

    run_dir: str
    profile_mode: str | None = None
    profile_seed: int | None = None
    sample_count: int
    trace_present: bool
    trace_backed_sample_count: int
    execution_coverage_rate: float
    reconciliation_ok_count: int
    reconciliation_error_count: int
    critical_reconciliation_error_count: int
    mismatch_counts: dict[str, int] = Field(default_factory=dict)


class RuntimeExecutionReconciliationResult(BaseModel):
    """Top-level reconciliation report."""

    source_dir: str
    raw_dataset_dir: str
    source_type: str
    summary: dict[str, Any]
    per_run: list[RuntimeExecutionRunSummary] = Field(default_factory=list)
    per_sample: list[RuntimeExecutionSampleFinding] = Field(default_factory=list)


def reconcile_runtime_execution(
    source_dir: str | Path,
    raw_dataset_dir: str | Path,
    output_path: str | Path,
    *,
    source_type: str = "study",
) -> RuntimeExecutionReconciliationResult:
    """Reconcile runtime-observed samples against trajectory and runtime trace."""
    source_dir = Path(source_dir)
    raw_dataset_dir = Path(raw_dataset_dir)
    output_path = Path(output_path)

    run_dirs = discover_run_dirs(source_dir, source_type=source_type)
    run_dirs_by_key = {str(run_dir): run_dir for run_dir in run_dirs}
    samples = read_schema_following_jsonl(raw_dataset_dir / "train.jsonl")
    samples_by_run: dict[str, list[Any]] = defaultdict(list)
    for sample in samples:
        run_dir = str(sample.metadata.get("source_run_dir"))
        if run_dir:
            samples_by_run[run_dir].append(sample)

    per_run: list[RuntimeExecutionRunSummary] = []
    per_sample: list[RuntimeExecutionSampleFinding] = []
    execution_kind_counts: Counter[str] = Counter()
    policy_decision_counts: Counter[str] = Counter()
    policy_reason_code_denials: Counter[str] = Counter()
    content_delta_kind_counts: Counter[str] = Counter()
    trace_backed_sample_count = 0
    reconciliation_ok_count = 0
    reconciliation_error_count = 0
    critical_reconciliation_error_count = 0
    runs_with_reconciliation_errors = 0

    for run_dir_str, run_samples in sorted(samples_by_run.items()):
        run_dir = run_dirs_by_key.get(run_dir_str, Path(run_dir_str))
        trajectory = _load_trajectory(run_dir)
        trace_events = _load_runtime_trace_events(run_dir)
        trace_present = bool(trace_events)
        tool_calls_by_id = {call.id: call for call in trajectory.tool_calls}
        observations_by_id = _observation_index(trajectory)
        mapping_events_by_id = _trace_event_index(trace_events, "tool_call_mapping_completed")
        execution_events_by_id = {
            **_trace_event_index(trace_events, "tool_execution_completed"),
            **_trace_event_index(trace_events, "tool_execution_failed"),
        }
        run_mismatch_counts: Counter[str] = Counter()
        run_trace_backed_count = 0
        run_ok_count = 0
        run_error_count = 0
        run_critical_error_count = 0

        for sample in run_samples:
            finding = _reconcile_sample(
                sample=sample,
                trajectory=trajectory,
                tool_calls_by_id=tool_calls_by_id,
                observations_by_id=observations_by_id,
                mapping_events_by_id=mapping_events_by_id,
                execution_events_by_id=execution_events_by_id,
                trace_present=trace_present,
            )
            per_sample.append(finding)
            for reason in finding.mismatch_reasons:
                run_mismatch_counts[reason] += 1
            if finding.trace_backed:
                trace_backed_sample_count += 1
                run_trace_backed_count += 1
            if finding.reconciliation_status == "ok":
                reconciliation_ok_count += 1
                run_ok_count += 1
            else:
                reconciliation_error_count += 1
                run_error_count += 1
            if finding.critical_mismatch_reasons:
                critical_reconciliation_error_count += 1
                run_critical_error_count += 1

            execution_kind = sample.metadata.get("source_execution_kind")
            if execution_kind is not None:
                execution_kind_counts[str(execution_kind)] += 1
            policy_decision = sample.metadata.get("source_policy_decision")
            if policy_decision is not None:
                policy_decision_counts[str(policy_decision)] += 1
                if str(policy_decision) == "deny":
                    reason_code = sample.metadata.get("source_policy_reason_code")
                    if reason_code is not None:
                        policy_reason_code_denials[str(reason_code)] += 1
            content_delta_kind = sample.metadata.get("source_content_delta_kind")
            if content_delta_kind is not None:
                content_delta_kind_counts[str(content_delta_kind)] += 1

        if run_error_count > 0:
            runs_with_reconciliation_errors += 1
        per_run.append(
            RuntimeExecutionRunSummary(
                run_dir=str(run_dir),
                profile_mode=_sample_metadata_value(run_samples, "source_profile_mode"),
                profile_seed=_sample_metadata_int(run_samples, "source_profile_seed"),
                sample_count=len(run_samples),
                trace_present=trace_present,
                trace_backed_sample_count=run_trace_backed_count,
                execution_coverage_rate=(
                    run_trace_backed_count / len(run_samples) if run_samples else 0.0
                ),
                reconciliation_ok_count=run_ok_count,
                reconciliation_error_count=run_error_count,
                critical_reconciliation_error_count=run_critical_error_count,
                mismatch_counts=_sorted_mapping(run_mismatch_counts),
            )
        )

    result = RuntimeExecutionReconciliationResult(
        source_dir=str(source_dir),
        raw_dataset_dir=str(raw_dataset_dir),
        source_type=source_type,
        summary={
            "discovered_run_count": len(run_dirs),
            "included_run_count": len(samples_by_run),
            "sampled_tool_call_count": len(samples),
            "trace_backed_sample_count": trace_backed_sample_count,
            "reconciliation_ok_count": reconciliation_ok_count,
            "reconciliation_error_count": reconciliation_error_count,
            "critical_reconciliation_error_count": critical_reconciliation_error_count,
            "runs_with_reconciliation_errors": runs_with_reconciliation_errors,
            "sample_count_by_execution_kind": _sorted_mapping(execution_kind_counts),
            "sample_count_by_policy_decision": _sorted_mapping(policy_decision_counts),
            "deny_count_by_policy_reason_code": _sorted_mapping(policy_reason_code_denials),
            "sample_count_by_content_delta_kind": _sorted_mapping(
                content_delta_kind_counts
            ),
        },
        per_run=per_run,
        per_sample=per_sample,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return result


def _reconcile_sample(
    *,
    sample: Any,
    trajectory: Trajectory,
    tool_calls_by_id: dict[str, Any],
    observations_by_id: dict[str, ToolObservation],
    mapping_events_by_id: dict[str, dict[str, Any]],
    execution_events_by_id: dict[str, dict[str, Any]],
    trace_present: bool,
) -> RuntimeExecutionSampleFinding:
    tool_call_id = str(sample.metadata.get("source_tool_call_id"))
    mismatch_reasons: list[str] = []
    critical_reasons: list[str] = []
    tool_call = tool_calls_by_id.get(tool_call_id)
    observation = observations_by_id.get(tool_call_id)
    mapping_event = mapping_events_by_id.get(tool_call_id)
    execution_event = execution_events_by_id.get(tool_call_id)
    provider_metadata = _provider_metadata(trajectory)

    if tool_call is None:
        _record_mismatch("missing_tool_call", mismatch_reasons, critical_reasons)
    if observation is None:
        _record_mismatch("missing_observation", mismatch_reasons, critical_reasons)
    if trace_present and mapping_event is None:
        _record_mismatch("missing_mapping_event", mismatch_reasons, critical_reasons)
    if trace_present and execution_event is None:
        _record_mismatch("missing_execution_event", mismatch_reasons, critical_reasons)

    if mapping_event is not None:
        mapping_data = mapping_event.get("data", {})
        if sample.target_tool_call.name != mapping_data.get("exposed_tool_name"):
            _record_mismatch("exposed_name_mismatch", mismatch_reasons, critical_reasons)
        if sample.canonical_intent.tool != mapping_data.get("canonical_tool_name"):
            _record_mismatch("canonical_name_mismatch", mismatch_reasons, critical_reasons)

    if execution_event is not None:
        execution_data = execution_event.get("data", {})
        if sample.canonical_intent.tool != execution_data.get("canonical_tool_name"):
            _record_mismatch("canonical_name_mismatch", mismatch_reasons, critical_reasons)

    if observation is not None:
        result_metadata = observation.result.metadata or {}
        if sample.metadata.get("source_execution_kind") != result_metadata.get("execution_kind"):
            _record_mismatch("execution_kind_mismatch", mismatch_reasons, critical_reasons)
        if sample.metadata.get("source_policy_decision") != result_metadata.get("policy_decision"):
            _record_mismatch("policy_decision_mismatch", mismatch_reasons, critical_reasons)
        if sample.metadata.get("source_policy_reason_code") != result_metadata.get(
            "policy_reason_code"
        ):
            _record_mismatch("policy_reason_code_mismatch", mismatch_reasons, critical_reasons)
        if (
            sample.metadata.get("source_tool_result_ok") != observation.result.ok
            or sample.metadata.get("source_tool_result_is_error") != observation.result.is_error
        ):
            _record_mismatch("tool_result_status_mismatch", mismatch_reasons, critical_reasons)

    if _provider_mismatch(sample.metadata, provider_metadata):
        _record_mismatch("provider_metadata_mismatch", mismatch_reasons, critical_reasons)

    return RuntimeExecutionSampleFinding(
        sample_id=sample.sample_id,
        source_run_dir=str(sample.metadata.get("source_run_dir")),
        tool_call_id=tool_call_id,
        exposed_tool_name=str(sample.target_tool_call.name),
        canonical_tool_name=str(sample.canonical_intent.tool),
        execution_kind=_nullable_str(sample.metadata.get("source_execution_kind")),
        policy_decision=_nullable_str(sample.metadata.get("source_policy_decision")),
        trace_present=trace_present,
        trace_backed=bool(trace_present and mapping_event is not None and execution_event is not None),
        reconciliation_status="error" if mismatch_reasons else "ok",
        mismatch_reasons=mismatch_reasons,
        critical_mismatch_reasons=critical_reasons,
    )


def _record_mismatch(
    reason: str,
    mismatch_reasons: list[str],
    critical_reasons: list[str],
) -> None:
    if reason not in mismatch_reasons:
        mismatch_reasons.append(reason)
    if reason in CRITICAL_MISMATCH_KINDS and reason not in critical_reasons:
        critical_reasons.append(reason)


def _load_trajectory(run_dir: Path) -> Trajectory:
    return Trajectory.model_validate(
        json.loads((run_dir / "trajectory.json").read_text(encoding="utf-8"))
    )


def _load_runtime_trace_events(run_dir: Path) -> list[dict[str, Any]]:
    trace_path = run_dir / "runtime_trace.jsonl"
    if not trace_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    return events


def _observation_index(trajectory: Trajectory) -> dict[str, ToolObservation]:
    return {observation.call.id: observation for observation in trajectory.observations}


def _trace_event_index(
    events: list[dict[str, Any]],
    event_kind: str,
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("event_kind") != event_kind:
            continue
        tool_call_id = event.get("tool_call_id")
        if isinstance(tool_call_id, str) and tool_call_id:
            indexed[tool_call_id] = event
    return indexed


def _provider_metadata(trajectory: Trajectory) -> dict[str, Any]:
    raw = trajectory.metadata.get("provider", {})
    return dict(raw) if isinstance(raw, dict) else {}


def _provider_mismatch(sample_metadata: dict[str, Any], provider_metadata: dict[str, Any]) -> bool:
    comparisons = [
        ("source_provider_kind", "provider_kind"),
        ("source_client_mode", "client_mode"),
        ("source_model", "model"),
        ("source_base_url", "base_url"),
        ("source_api_key_env", "api_key_env"),
        ("source_protocol_mode", "protocol_mode"),
        ("source_provider_family", "provider_family"),
        ("source_provider_name", "provider_name"),
    ]
    for sample_key, provider_key in comparisons:
        if sample_metadata.get(sample_key) != provider_metadata.get(provider_key):
            return True
    return False


def _sample_metadata_value(samples: list[Any], key: str) -> str | None:
    if not samples:
        return None
    value = samples[0].metadata.get(key)
    if value is None:
        return None
    return str(value)


def _sample_metadata_int(samples: list[Any], key: str) -> int | None:
    if not samples:
        return None
    value = samples[0].metadata.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nullable_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _sorted_mapping(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}
