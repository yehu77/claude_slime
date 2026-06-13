"""Study-scale post-run bundle generation for runtime-observed datasets."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.eval.runtime_behavior_audit import build_runtime_behavior_audit
from pycodeagent.eval.runtime_execution_reconciliation import (
    RuntimeExecutionReconciliationResult,
    reconcile_runtime_execution,
)
from pycodeagent.rl.dataset_manifest import FilterConfig
from pycodeagent.rl.schema_following_dataset import read_schema_following_jsonl
from pycodeagent.rl.training_prep import (
    RuntimeObservedSchemaFollowingTrainingPrepRecommendation,
    prepare_runtime_observed_schema_following_training_input,
)


class RuntimeObservedStudyBundleResult(BaseModel):
    """Top-level bundle result for study/experiment runtime-observed outputs."""

    source_type: str
    source_path: str
    split: str
    bundle_root: str
    raw_dataset_dir: str
    prepared_dataset_dir: str
    canonical_sample_input: str
    canonical_training_input: str
    discovered_run_count: int
    included_run_count: int
    skipped_run_count: int
    observed_sample_count: int
    tokenized_example_count: int
    profile_modes: list[str] = Field(default_factory=list)
    seeds: list[int] = Field(default_factory=list)
    task_count: int
    run_count_by_mode: dict[str, int] = Field(default_factory=dict)
    sample_count_by_mode: dict[str, int] = Field(default_factory=dict)
    trainable_sample_count_by_mode: dict[str, int] = Field(default_factory=dict)
    sample_count_by_seed: dict[str, int] = Field(default_factory=dict)
    sample_count_by_canonical_tool: dict[str, int] = Field(default_factory=dict)
    sample_count_by_mode_and_canonical_tool: dict[str, dict[str, int]] = Field(
        default_factory=dict
    )
    schema_variant_category_counts: dict[str, int] = Field(default_factory=dict)
    sample_count_by_mode_and_schema_variant_category: dict[str, dict[str, int]] = Field(
        default_factory=dict
    )
    sample_count_by_tool_reordered: dict[str, int] = Field(default_factory=dict)
    tool_reorder_changed_count: int
    runtime_trace_present_count: int
    runtime_trace_coverage_rate: float
    completed_run_count: int
    verifier_passed_run_count: int
    contract_ok: bool
    raw_dataset_manifest_path: str
    raw_source_manifest_path: str
    prepared_contract_report_path: str
    tokenizer_config_path: str
    train_config_path: str
    study_observed_manifest_path: str
    study_observed_summary_path: str
    runtime_behavior_audit_path: str
    runtime_execution_reconciliation_path: str
    trace_backed_sample_count: int
    trace_backed_sample_rate: float
    reconciliation_ok_count: int
    reconciliation_error_count: int
    critical_reconciliation_error_count: int
    sample_count_by_execution_kind: dict[str, int] = Field(default_factory=dict)
    sample_count_by_policy_decision: dict[str, int] = Field(default_factory=dict)
    deny_count_by_policy_reason_code: dict[str, int] = Field(default_factory=dict)
    sample_count_by_content_delta_kind: dict[str, int] = Field(default_factory=dict)
    validation_turn_count: int
    revalidation_turn_count: int
    revision_turn_count: int
    finish_deferred_count: int
    compaction_turn_count: int
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
    mean_validation_attempts_per_issue: float
    mean_revision_attempts_per_issue: float
    notes: list[str] = Field(default_factory=list)


def prepare_study_runtime_observed_bundle(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    source_type: str = "study",
    filter_config: FilterConfig | None = None,
    split: str = "train",
    max_length: int = 2048,
    batch_size: int = 8,
    learning_rate: float = 1e-4,
    max_steps: int = 1000,
    seed: int = 42,
    tokenizer: Any | None = None,
    tokenizer_config: Any | None = None,
    fake_tokenizer_config: Any | None = None,
    run_id: str = "runtime_observed_study_train",
) -> RuntimeObservedStudyBundleResult:
    """Build a study-scale observed bundle from runtime outputs."""
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    prep = prepare_runtime_observed_schema_following_training_input(
        source_dir,
        output_dir,
        source_type=source_type,
        filter_config=filter_config,
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

    raw_dataset_dir = output_dir / "raw_dataset"
    prepared_dataset_dir = output_dir / "prepared"
    source_manifest = _read_json(raw_dataset_dir / "source_manifest.json")
    raw_samples = read_schema_following_jsonl(raw_dataset_dir / f"{split}.jsonl")
    behavior_audit = build_runtime_behavior_audit(
        source_dir,
        output_dir / "runtime_behavior_audit.json",
        source_type=source_type,
    )
    reconciliation = reconcile_runtime_execution(
        source_dir,
        raw_dataset_dir,
        output_dir / "runtime_execution_reconciliation.json",
        source_type=source_type,
    )

    summary_payload = _build_study_observed_summary(
        source_manifest=source_manifest,
        raw_samples=raw_samples,
        behavior_audit=behavior_audit.model_dump(mode="json"),
        reconciliation=reconciliation,
    )
    manifest_payload = _build_study_observed_manifest(
        prep=prep,
        bundle_root=output_dir,
        summary_payload=summary_payload,
        split=split,
    )

    study_observed_manifest_path = output_dir / "study_observed_manifest.json"
    study_observed_summary_path = output_dir / "study_observed_summary.json"
    _write_json(study_observed_manifest_path, manifest_payload)
    _write_json(study_observed_summary_path, summary_payload)

    result = RuntimeObservedStudyBundleResult(
        source_type=source_type,
        source_path=str(source_dir),
        split=split,
        bundle_root=str(output_dir),
        raw_dataset_dir=prep.raw_dataset_dir,
        prepared_dataset_dir=prep.prepared_dataset_dir,
        canonical_sample_input=prep.canonical_sample_input,
        canonical_training_input=prep.canonical_training_input,
        discovered_run_count=prep.discovered_run_count,
        included_run_count=prep.included_run_count,
        skipped_run_count=prep.discovered_run_count - prep.included_run_count,
        observed_sample_count=prep.observed_sample_count,
        tokenized_example_count=prep.tokenized_example_count,
        profile_modes=summary_payload["profile_modes"],
        seeds=summary_payload["seeds"],
        task_count=summary_payload["task_count"],
        run_count_by_mode=summary_payload["run_count_by_mode"],
        sample_count_by_mode=summary_payload["sample_count_by_mode"],
        trainable_sample_count_by_mode=summary_payload["trainable_sample_count_by_mode"],
        sample_count_by_seed=summary_payload["sample_count_by_seed"],
        sample_count_by_canonical_tool=summary_payload["sample_count_by_canonical_tool"],
        sample_count_by_mode_and_canonical_tool=summary_payload[
            "sample_count_by_mode_and_canonical_tool"
        ],
        schema_variant_category_counts=summary_payload["schema_variant_category_counts"],
        sample_count_by_mode_and_schema_variant_category=summary_payload[
            "sample_count_by_mode_and_schema_variant_category"
        ],
        sample_count_by_tool_reordered=summary_payload["sample_count_by_tool_reordered"],
        tool_reorder_changed_count=summary_payload["tool_reorder_changed_count"],
        runtime_trace_present_count=summary_payload["runtime_trace_present_count"],
        runtime_trace_coverage_rate=summary_payload["runtime_trace_coverage_rate"],
        trace_backed_sample_count=summary_payload["trace_backed_sample_count"],
        trace_backed_sample_rate=summary_payload["trace_backed_sample_rate"],
        completed_run_count=summary_payload["completed_run_count"],
        verifier_passed_run_count=summary_payload["verifier_passed_run_count"],
        contract_ok=(
            prep.contract_ok
            and summary_payload["critical_reconciliation_error_count"] == 0
        ),
        raw_dataset_manifest_path=prep.raw_dataset_manifest_path,
        raw_source_manifest_path=prep.raw_source_manifest_path,
        prepared_contract_report_path=prep.prepared_contract_report_path,
        tokenizer_config_path=prep.tokenizer_config_path,
        train_config_path=prep.train_config_path,
        study_observed_manifest_path=str(study_observed_manifest_path),
        study_observed_summary_path=str(study_observed_summary_path),
        runtime_behavior_audit_path=str(output_dir / "runtime_behavior_audit.json"),
        runtime_execution_reconciliation_path=str(
            output_dir / "runtime_execution_reconciliation.json"
        ),
        reconciliation_ok_count=summary_payload["reconciliation_ok_count"],
        reconciliation_error_count=summary_payload["reconciliation_error_count"],
        critical_reconciliation_error_count=summary_payload[
            "critical_reconciliation_error_count"
        ],
        sample_count_by_execution_kind=summary_payload["sample_count_by_execution_kind"],
        sample_count_by_policy_decision=summary_payload["sample_count_by_policy_decision"],
        deny_count_by_policy_reason_code=summary_payload["deny_count_by_policy_reason_code"],
        sample_count_by_content_delta_kind=summary_payload[
            "sample_count_by_content_delta_kind"
        ],
        validation_turn_count=summary_payload["validation_turn_count"],
        revalidation_turn_count=summary_payload["revalidation_turn_count"],
        revision_turn_count=summary_payload["revision_turn_count"],
        finish_deferred_count=summary_payload["finish_deferred_count"],
        compaction_turn_count=summary_payload["compaction_turn_count"],
        validation_issue_count=summary_payload["validation_issue_count"],
        validation_retry_count=summary_payload["validation_retry_count"],
        revision_after_validation_failure_count=summary_payload[
            "revision_after_validation_failure_count"
        ],
        token_budget_compaction_turn_count=summary_payload[
            "token_budget_compaction_turn_count"
        ],
        runs_with_validation_failure=summary_payload["runs_with_validation_failure"],
        runs_with_revision_after_failure=summary_payload["runs_with_revision_after_failure"],
        runs_with_finish_deferred=summary_payload["runs_with_finish_deferred"],
        runs_with_compaction=summary_payload["runs_with_compaction"],
        runs_with_validation_budget_exhausted=summary_payload[
            "runs_with_validation_budget_exhausted"
        ],
        runs_with_revision_budget_exhausted=summary_payload[
            "runs_with_revision_budget_exhausted"
        ],
        runs_with_finish_blocked_by_validation=summary_payload[
            "runs_with_finish_blocked_by_validation"
        ],
        runs_with_token_overflow=summary_payload["runs_with_token_overflow"],
        mean_validation_attempts_per_issue=summary_payload[
            "mean_validation_attempts_per_issue"
        ],
        mean_revision_attempts_per_issue=summary_payload[
            "mean_revision_attempts_per_issue"
        ],
        notes=[
            "This bundle is a study-scale post-run wrapper over the runtime-observed exporter and existing schema-following training-prep path.",
            "Run-level summary counts are derived from runs that emitted at least one observed assistant tool call sample.",
            "runtime_trace remains an audit artifact; observed samples are still sourced from trajectory.json + tool_profile.json.",
            "runtime_behavior_audit.json summarizes repeated-run behavior facts directly from runtime trace bundles.",
            "runtime_execution_reconciliation.json reconciles observed sample execution/policy provenance back to trajectory observations and runtime trace events.",
        ],
    )
    _write_json(
        output_dir / "runtime_observed_bundle.json",
        result.model_dump(mode="json"),
    )
    return result


def _build_study_observed_manifest(
    *,
    prep: RuntimeObservedSchemaFollowingTrainingPrepRecommendation,
    bundle_root: Path,
    summary_payload: dict[str, Any],
    split: str,
) -> dict[str, Any]:
    return {
        "bundle_type": "runtime_observed_study_bundle",
        "version": 1,
        "source_type": prep.source_type,
        "source_path": prep.source_path,
        "split": split,
        "bundle_root": str(bundle_root),
        "raw_dataset_dir": prep.raw_dataset_dir,
        "prepared_dataset_dir": prep.prepared_dataset_dir,
        "canonical_sample_input": prep.canonical_sample_input,
        "canonical_training_input": prep.canonical_training_input,
        "discovered_run_count": prep.discovered_run_count,
        "included_run_count": prep.included_run_count,
        "skipped_run_count": prep.discovered_run_count - prep.included_run_count,
        "observed_sample_count": prep.observed_sample_count,
        "tokenized_example_count": prep.tokenized_example_count,
        "profile_modes": summary_payload["profile_modes"],
        "seeds": summary_payload["seeds"],
        "task_count": summary_payload["task_count"],
        "contract_ok": (
            prep.contract_ok
            and summary_payload["critical_reconciliation_error_count"] == 0
        ),
        "paths": {
            "raw_dataset_manifest_path": prep.raw_dataset_manifest_path,
            "raw_source_manifest_path": prep.raw_source_manifest_path,
            "prepared_contract_report_path": prep.prepared_contract_report_path,
            "tokenizer_config_path": prep.tokenizer_config_path,
            "train_config_path": prep.train_config_path,
            "training_prep_path": str(bundle_root / "training_prep.json"),
            "summary_path": str(bundle_root / "study_observed_summary.json"),
            "runtime_behavior_audit_path": str(bundle_root / "runtime_behavior_audit.json"),
            "runtime_execution_reconciliation_path": str(
                bundle_root / "runtime_execution_reconciliation.json"
            ),
        },
    }


def _build_study_observed_summary(
    *,
    source_manifest: dict[str, Any],
    raw_samples: list[Any],
    behavior_audit: dict[str, Any],
    reconciliation: RuntimeExecutionReconciliationResult,
) -> dict[str, Any]:
    sample_run_dirs = {
        str(sample.metadata.get("source_run_dir"))
        for sample in raw_samples
        if sample.metadata.get("source_run_dir")
    }
    selected_runs = [
        run
        for run in source_manifest.get("runs", [])
        if str(run.get("run_dir")) in sample_run_dirs
    ]

    run_count_by_mode = Counter(str(run.get("source_profile_mode", "unknown")) for run in selected_runs)
    sample_count_by_mode = Counter(
        str(sample.metadata.get("source_profile_mode", "unknown")) for sample in raw_samples
    )
    sample_count_by_seed = Counter(
        str(sample.metadata.get("source_profile_seed", 0)) for sample in raw_samples
    )
    sample_count_by_canonical_tool = Counter(
        str(sample.canonical_intent.tool) for sample in raw_samples
    )
    sample_count_by_mode_and_canonical_tool: dict[str, Counter[str]] = {}
    sample_count_by_mode_and_schema_variant_category: dict[str, Counter[str]] = {}
    schema_variant_category_counts = Counter(
        str(sample.metadata.get("schema_variant_category"))
        for sample in raw_samples
        if sample.metadata.get("schema_variant_category") is not None
    )
    sample_count_by_tool_reordered = Counter()

    for sample in raw_samples:
        mode = str(sample.metadata.get("source_profile_mode", "unknown"))
        canonical_tool = str(sample.canonical_intent.tool)
        sample_count_by_mode_and_canonical_tool.setdefault(mode, Counter())[canonical_tool] += 1

        schema_variant_category = sample.metadata.get("schema_variant_category")
        if schema_variant_category is not None:
            sample_count_by_mode_and_schema_variant_category.setdefault(mode, Counter())[
                str(schema_variant_category)
            ] += 1

        reordered = bool(sample.metadata.get("tool_order_changed")) or bool(
            sample.metadata.get("source_tool_reordered")
        )
        sample_count_by_tool_reordered["true" if reordered else "false"] += 1

    runtime_trace_present_count = sum(
        1 for run in selected_runs if bool(run.get("runtime_trace_present", False))
    )
    completed_run_count = sum(
        1 for run in selected_runs if str(run.get("status")) == "completed"
    )
    verifier_passed_run_count = sum(
        1 for run in selected_runs if bool(run.get("verifier_passed", False))
    )
    tool_reorder_changed_count = sum(
        1
        for sample in raw_samples
        if bool(sample.metadata.get("tool_order_changed"))
        or bool(sample.metadata.get("source_tool_reordered"))
    )

    selected_modes = sorted({str(run.get("source_profile_mode", "unknown")) for run in selected_runs})
    selected_seeds = sorted(
        {
            _safe_int(run.get("source_profile_seed"))
            for run in selected_runs
            if run.get("source_profile_seed") is not None
        }
    )
    task_count = len({str(run.get("task_id")) for run in selected_runs if run.get("task_id")})
    runtime_trace_coverage_rate = (
        runtime_trace_present_count / len(selected_runs)
        if selected_runs
        else 0.0
    )
    reconciliation_summary = reconciliation.summary
    trace_backed_sample_count = int(reconciliation_summary.get("trace_backed_sample_count", 0))
    trace_backed_sample_rate = (
        trace_backed_sample_count / len(raw_samples)
        if raw_samples
        else 0.0
    )

    return {
        "version": 1,
        "profile_modes": selected_modes,
        "seeds": selected_seeds,
        "task_count": task_count,
        "run_count_by_mode": _sorted_mapping(run_count_by_mode),
        "sample_count_by_mode": _sorted_mapping(sample_count_by_mode),
        "trainable_sample_count_by_mode": _sorted_mapping(sample_count_by_mode),
        "sample_count_by_seed": _sorted_mapping(sample_count_by_seed),
        "sample_count_by_canonical_tool": _sorted_mapping(sample_count_by_canonical_tool),
        "sample_count_by_mode_and_canonical_tool": {
            mode: _sorted_mapping(counter)
            for mode, counter in sorted(sample_count_by_mode_and_canonical_tool.items())
        },
        "schema_variant_category_counts": _sorted_mapping(schema_variant_category_counts),
        "sample_count_by_mode_and_schema_variant_category": {
            mode: _sorted_mapping(counter)
            for mode, counter in sorted(sample_count_by_mode_and_schema_variant_category.items())
        },
        "sample_count_by_tool_reordered": _sorted_mapping(sample_count_by_tool_reordered),
        "tool_reorder_changed_count": tool_reorder_changed_count,
        "runtime_trace_present_count": runtime_trace_present_count,
        "runtime_trace_coverage_rate": runtime_trace_coverage_rate,
        "trace_backed_sample_count": trace_backed_sample_count,
        "trace_backed_sample_rate": trace_backed_sample_rate,
        "completed_run_count": completed_run_count,
        "verifier_passed_run_count": verifier_passed_run_count,
        "selected_run_count": len(selected_runs),
        "observed_sample_count": len(raw_samples),
        "reconciliation_ok_count": int(
            reconciliation_summary.get("reconciliation_ok_count", 0)
        ),
        "reconciliation_error_count": int(
            reconciliation_summary.get("reconciliation_error_count", 0)
        ),
        "runs_with_reconciliation_errors": int(
            reconciliation_summary.get("runs_with_reconciliation_errors", 0)
        ),
        "critical_reconciliation_error_count": int(
            reconciliation_summary.get("critical_reconciliation_error_count", 0)
        ),
        "sample_count_by_execution_kind": dict(
            reconciliation_summary.get("sample_count_by_execution_kind", {})
        ),
        "sample_count_by_policy_decision": dict(
            reconciliation_summary.get("sample_count_by_policy_decision", {})
        ),
        "deny_count_by_policy_reason_code": dict(
            reconciliation_summary.get("deny_count_by_policy_reason_code", {})
        ),
        "sample_count_by_content_delta_kind": dict(
            reconciliation_summary.get("sample_count_by_content_delta_kind", {})
        ),
        "validation_turn_count": int(behavior_audit.get("validation_turn_count", 0)),
        "revalidation_turn_count": int(behavior_audit.get("revalidation_turn_count", 0)),
        "revision_turn_count": int(behavior_audit.get("revision_turn_count", 0)),
        "finish_deferred_count": int(behavior_audit.get("finish_deferred_count", 0)),
        "compaction_turn_count": int(behavior_audit.get("compaction_turn_count", 0)),
        "validation_issue_count": int(behavior_audit.get("validation_issue_count", 0)),
        "validation_retry_count": int(behavior_audit.get("validation_retry_count", 0)),
        "revision_after_validation_failure_count": int(
            behavior_audit.get("revision_after_validation_failure_count", 0)
        ),
        "token_budget_compaction_turn_count": int(
            behavior_audit.get("token_budget_compaction_turn_count", 0)
        ),
        "runs_with_validation_failure": int(
            behavior_audit.get("runs_with_validation_failure", 0)
        ),
        "runs_with_revision_after_failure": int(
            behavior_audit.get("runs_with_revision_after_failure", 0)
        ),
        "runs_with_finish_deferred": int(
            behavior_audit.get("runs_with_finish_deferred", 0)
        ),
        "runs_with_compaction": int(behavior_audit.get("runs_with_compaction", 0)),
        "runs_with_validation_budget_exhausted": int(
            behavior_audit.get("runs_with_validation_budget_exhausted", 0)
        ),
        "runs_with_revision_budget_exhausted": int(
            behavior_audit.get("runs_with_revision_budget_exhausted", 0)
        ),
        "runs_with_finish_blocked_by_validation": int(
            behavior_audit.get("runs_with_finish_blocked_by_validation", 0)
        ),
        "runs_with_token_overflow": int(behavior_audit.get("runs_with_token_overflow", 0)),
        "mean_validation_attempts_per_issue": float(
            behavior_audit.get("mean_validation_attempts_per_issue", 0.0)
        ),
        "mean_revision_attempts_per_issue": float(
            behavior_audit.get("mean_revision_attempts_per_issue", 0.0)
        ),
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _sorted_mapping(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
