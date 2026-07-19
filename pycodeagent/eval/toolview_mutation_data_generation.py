"""Narrow real-provider ToolView-mutation data-generation orchestration."""

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
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.eval.real_provider_behavior_baseline import load_realistic_runtime_tasks
from pycodeagent.eval.run_campaign import execute_profile_run_campaigns
from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.rl.dataset_manifest import FilterConfig
from pycodeagent.rl.schema_following_dataset import read_schema_following_jsonl
from pycodeagent.rl.schema_following_from_runtime import (
    RuntimeObservedGenerationResult,
    generate_schema_following_from_runtime_runs,
)
from pycodeagent.rl.tokenizer import BaseTokenizerAdapter
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig
from pycodeagent.rl.training_prep import (
    SchemaFollowingTrainingPrepRecommendation,
    prepare_schema_following_training_input,
)
from pycodeagent.tools.bootstrap import (
    ToolStackKind,
    build_native_claude_runtime,
    build_native_codex_runtime,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TASKS_PATH = _PROJECT_ROOT / "datasets" / "tasks" / "realistic_runtime_tasks.jsonl"
_DEFAULT_NATIVE_FAMILY_MUTATION_CONFIG = (
    _PROJECT_ROOT / "configs" / "tools" / "native_family_mutation_v1.yaml"
)
DEFAULT_MUTATION_DATA_PROFILE_MODES: tuple[str, str, str, str] = (
    "base",
    "argument_rename",
    "schema_flat_to_nested",
    "tool_reorder",
)
DEFAULT_MUTATION_DATA_PROFILE_SEED_BY_MODE: dict[str, int] = {
    "base": 0,
    "argument_rename": 0,
    "schema_flat_to_nested": 0,
    "tool_reorder": 0,
}
DEFAULT_MUTATION_DATA_REPEAT_COUNT = 1


class ToolViewMutationDataGenerationResult(BaseModel):
    """Top-level result for the mutation-first data-generation path."""

    output_root: str
    source_runs_root: str
    raw_dataset_dir: str
    prepared_dataset_dir: str | None = None
    tasks_path: str | None = None
    provider: dict[str, Any] = Field(default_factory=dict)
    tool_stack_kind: ToolStackKind
    profile_modes: list[str] = Field(default_factory=list)
    profile_seed_by_mode: dict[str, int] = Field(default_factory=dict)
    repeat_count: int
    discovered_run_count: int
    included_run_count: int
    skipped_run_count: int
    observed_sample_count: int
    source_run_count_by_mode: dict[str, int] = Field(default_factory=dict)
    completed_run_count_by_mode: dict[str, int] = Field(default_factory=dict)
    sample_count_by_mode: dict[str, int] = Field(default_factory=dict)
    training_prep_enabled: bool
    training_prep_contract_ok: bool | None = None
    contract_ok: bool
    raw_dataset_manifest_path: str
    raw_source_manifest_path: str
    training_prep_path: str | None = None
    acceptance_report_path: str
    generation_summary_path: str
    generation_manifest_path: str
    campaign_group_spec_path: str | None = None
    campaign_group_manifest_path: str | None = None
    campaign_contract_ok: bool | None = None


def run_real_provider_toolview_mutation_data_generation(
    provider_config: RuntimeProviderConfig | str | Path,
    output_root: str | Path,
    *,
    tasks_path: str | Path = _DEFAULT_TASKS_PATH,
    profile_modes: list[str] | tuple[str, ...] = DEFAULT_MUTATION_DATA_PROFILE_MODES,
    profile_seed_by_mode: dict[str, int] | None = None,
    repeat_count: int = DEFAULT_MUTATION_DATA_REPEAT_COUNT,
    tool_stack_kind: ToolStackKind,
    mutation_config_path: str | Path | None = None,
    filter_config: FilterConfig | None = None,
    prepare_training_input: bool = True,
    split: str = "train",
    max_length: int = 2048,
    batch_size: int = 8,
    learning_rate: float = 1e-4,
    max_steps: int = 1000,
    seed: int = 42,
    tokenizer: BaseTokenizerAdapter | None = None,
    tokenizer_config: TokenizerConfig | None = None,
    fake_tokenizer_config: FakeTokenizerConfig | None = None,
    run_id: str = "toolview_mutation_data_generation",
) -> ToolViewMutationDataGenerationResult:
    """Run repeated real-provider source runs and export mutation-first data."""
    resolved_provider_config = (
        provider_config
        if isinstance(provider_config, RuntimeProviderConfig)
        else resolve_runtime_provider_config(provider_config)
    )
    tasks = load_realistic_runtime_tasks(tasks_path)
    return run_toolview_mutation_data_generation(
        tasks,
        lambda _task, _mode, _repeat_index: build_llm_client(resolved_provider_config),
        output_root,
        tasks_path=tasks_path,
        provider=resolved_provider_config.runtime_provenance(),
        profile_modes=profile_modes,
        profile_seed_by_mode=profile_seed_by_mode,
        repeat_count=repeat_count,
        tool_stack_kind=tool_stack_kind,
        mutation_config_path=mutation_config_path,
        filter_config=filter_config,
        prepare_training_input=prepare_training_input,
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


def run_toolview_mutation_data_generation(
    tasks: list[CodingTask],
    client_factory: Callable[[CodingTask, str, int], BaseLLMClient],
    output_root: str | Path,
    *,
    tasks_path: str | Path | None = None,
    provider: dict[str, Any] | None = None,
    profile_modes: list[str] | tuple[str, ...] = DEFAULT_MUTATION_DATA_PROFILE_MODES,
    profile_seed_by_mode: dict[str, int] | None = None,
    repeat_count: int = DEFAULT_MUTATION_DATA_REPEAT_COUNT,
    tool_stack_kind: ToolStackKind,
    mutation_config_path: str | Path | None = None,
    filter_config: FilterConfig | None = None,
    prepare_training_input: bool = True,
    split: str = "train",
    max_length: int = 2048,
    batch_size: int = 8,
    learning_rate: float = 1e-4,
    max_steps: int = 1000,
    seed: int = 42,
    tokenizer: BaseTokenizerAdapter | None = None,
    tokenizer_config: TokenizerConfig | None = None,
    fake_tokenizer_config: FakeTokenizerConfig | None = None,
    run_id: str = "toolview_mutation_data_generation",
) -> ToolViewMutationDataGenerationResult:
    """Generate observed data from explicit tasks and a client factory."""
    output_root = Path(output_root)
    source_runs_root = output_root / "runs"
    source_runs_root.mkdir(parents=True, exist_ok=True)
    normalized_modes = [str(mode) for mode in profile_modes]
    normalized_profile_seeds = _normalized_profile_seed_by_mode(
        normalized_modes,
        profile_seed_by_mode,
    )
    _, base_profile, runtime = _build_source_stack(tool_stack_kind)
    resolved_mutation_config = _resolve_mutation_config_path(
        tool_stack_kind,
        mutation_config_path,
    )
    profiles = {
        mode: ToolProfileSampler(
            seed=normalized_profile_seeds[mode],
            mutation_config_path=resolved_mutation_config,
            base_profile=base_profile,
        ).sample(mode)
        for mode in normalized_modes
    }

    def run_mutation_case(task, client, attempt_root, case, _campaign):
        expected_profile = profiles[case.profile_mode]
        trajectory = run_coding_task(
            task,
            client,
            attempt_root,
            runtime=runtime,
            profile=expected_profile,
            tool_stack_kind=tool_stack_kind,
        )
        if trajectory.tool_profile_id != expected_profile.profile_id:
            raise ValueError(
                "Runtime returned unexpected tool_profile_id for mutation "
                "data generation run: "
                f"expected {expected_profile.profile_id}, "
                f"got {trajectory.tool_profile_id}"
            )
        return trajectory

    campaign_result = execute_profile_run_campaigns(
        campaign_id="toolview_mutation_data_generation",
        tasks=tasks,
        client_factory=client_factory,
        output_root=source_runs_root,
        profile_seed_by_mode=normalized_profile_seeds,
        repeat_count=repeat_count,
        tool_stack_kind=tool_stack_kind,
        provider=provider,
        run_executor=run_mutation_case,
    )
    return build_toolview_mutation_data_generation_from_runs(
        source_runs_root,
        output_root,
        tasks_path=tasks_path,
        provider=provider,
        profile_modes=profile_modes,
        profile_seed_by_mode=profile_seed_by_mode,
        repeat_count=repeat_count,
        tool_stack_kind=tool_stack_kind,
        filter_config=filter_config,
        prepare_training_input=prepare_training_input,
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


def build_toolview_mutation_data_generation_from_runs(
    source_runs_root: str | Path,
    output_root: str | Path,
    *,
    tasks_path: str | Path | None = None,
    provider: dict[str, Any] | None = None,
    profile_modes: list[str] | tuple[str, ...] = DEFAULT_MUTATION_DATA_PROFILE_MODES,
    profile_seed_by_mode: dict[str, int] | None = None,
    repeat_count: int = DEFAULT_MUTATION_DATA_REPEAT_COUNT,
    tool_stack_kind: ToolStackKind,
    filter_config: FilterConfig | None = None,
    prepare_training_input: bool = True,
    split: str = "train",
    max_length: int = 2048,
    batch_size: int = 8,
    learning_rate: float = 1e-4,
    max_steps: int = 1000,
    seed: int = 42,
    tokenizer: BaseTokenizerAdapter | None = None,
    tokenizer_config: TokenizerConfig | None = None,
    fake_tokenizer_config: FakeTokenizerConfig | None = None,
    run_id: str = "toolview_mutation_data_generation",
    campaign_group_spec_path: str | Path | None = None,
    campaign_group_manifest_path: str | Path | None = None,
    campaign_contract_ok: bool | None = None,
) -> ToolViewMutationDataGenerationResult:
    """Build raw observed exports and optional training prep from source runs."""
    if split != "train":
        raise ValueError("ToolView mutation data generation currently supports split='train'")

    source_runs_root = Path(source_runs_root)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    normalized_modes = [str(mode) for mode in profile_modes]
    normalized_profile_seeds = _normalized_profile_seed_by_mode(
        normalized_modes,
        profile_seed_by_mode,
    )
    normalized_provider = dict(provider or {})

    raw_dataset_dir = output_root / "runtime_observed_raw"
    export_result = generate_schema_following_from_runtime_runs(
        source_runs_root,
        raw_dataset_dir,
        source_type="batch",
        filter_config=filter_config,
        split_seed=seed,
    )
    raw_source_manifest = _read_json(raw_dataset_dir / "source_manifest.json")
    raw_samples = read_schema_following_jsonl(raw_dataset_dir / "train.jsonl")

    source_run_count_by_mode = _count_source_runs_by_mode(raw_source_manifest.get("runs", []))
    completed_run_count_by_mode = _count_completed_runs_by_mode(raw_source_manifest.get("runs", []))
    sample_count_by_mode = _count_samples_by_mode(raw_samples)

    prepared_dataset_dir: Path | None = None
    training_prep_path: Path | None = None
    prepared_recommendation: SchemaFollowingTrainingPrepRecommendation | None = None
    if prepare_training_input:
        prepared_dataset_dir = output_root / "training_prep"
        prepared_recommendation = prepare_schema_following_training_input(
            raw_dataset_dir,
            prepared_dataset_dir,
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
        training_prep_path = prepared_dataset_dir / "training_prep.json"

    contract_ok = export_result.sample_count > 0 and (
        not prepare_training_input
        or bool(prepared_recommendation and prepared_recommendation.contract_ok)
    ) and campaign_contract_ok is not False
    acceptance_report = _build_acceptance_report(
        configured_modes=normalized_modes,
        source_run_count_by_mode=source_run_count_by_mode,
        completed_run_count_by_mode=completed_run_count_by_mode,
        sample_count_by_mode=sample_count_by_mode,
        raw_samples=raw_samples,
        training_prep_enabled=prepare_training_input,
        training_prep_contract_ok=(
            prepared_recommendation.contract_ok if prepared_recommendation is not None else None
        ),
    )
    contract_ok = contract_ok and bool(acceptance_report["contract_ok"])
    acceptance_report_path = output_root / "toolview_mutation_data_generation_acceptance.json"
    _write_json(acceptance_report_path, acceptance_report)

    generation_summary = {
        "version": 1,
        "tasks_path": str(tasks_path) if tasks_path is not None else None,
        "provider": normalized_provider,
        "profile_modes": normalized_modes,
        "profile_seed_by_mode": normalized_profile_seeds,
        "repeat_count": repeat_count,
        "tool_stack_kind": tool_stack_kind,
        "source_runs_root": str(source_runs_root),
        "raw_dataset_dir": str(raw_dataset_dir),
        "prepared_dataset_dir": str(prepared_dataset_dir) if prepared_dataset_dir else None,
        "discovered_run_count": export_result.discovered_run_count,
        "included_run_count": export_result.included_run_count,
        "skipped_run_count": export_result.skipped_run_count,
        "observed_sample_count": export_result.sample_count,
        "source_run_count_by_mode": source_run_count_by_mode,
        "completed_run_count_by_mode": completed_run_count_by_mode,
        "sample_count_by_mode": sample_count_by_mode,
        "training_prep_enabled": prepare_training_input,
        "training_prep_contract_ok": (
            prepared_recommendation.contract_ok if prepared_recommendation is not None else None
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
        "campaign_contract_ok": campaign_contract_ok,
        "contract_ok": contract_ok,
    }
    generation_summary_path = output_root / "toolview_mutation_data_generation_summary.json"
    _write_json(generation_summary_path, generation_summary)

    generation_manifest = {
        "version": 1,
        "bundle_type": "toolview_mutation_data_generation",
        "output_root": str(output_root),
        "source_runs_root": str(source_runs_root),
        "tasks_path": str(tasks_path) if tasks_path is not None else None,
        "provider": normalized_provider,
        "profile_modes": normalized_modes,
        "profile_seed_by_mode": normalized_profile_seeds,
        "repeat_count": repeat_count,
        "tool_stack_kind": tool_stack_kind,
        "training_prep_enabled": prepare_training_input,
        "contract_ok": contract_ok,
        "paths": {
            "raw_dataset_dir": str(raw_dataset_dir),
            "raw_dataset_manifest_path": str(raw_dataset_dir / "dataset_manifest.json"),
            "raw_source_manifest_path": str(raw_dataset_dir / "source_manifest.json"),
            "prepared_dataset_dir": (
                str(prepared_dataset_dir) if prepared_dataset_dir is not None else None
            ),
            "training_prep_path": str(training_prep_path) if training_prep_path else None,
            "acceptance_report_path": str(acceptance_report_path),
            "generation_summary_path": str(generation_summary_path),
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
    generation_manifest_path = output_root / "toolview_mutation_data_generation_manifest.json"
    _write_json(generation_manifest_path, generation_manifest)

    return ToolViewMutationDataGenerationResult(
        output_root=str(output_root),
        source_runs_root=str(source_runs_root),
        raw_dataset_dir=str(raw_dataset_dir),
        prepared_dataset_dir=(str(prepared_dataset_dir) if prepared_dataset_dir else None),
        tasks_path=(str(tasks_path) if tasks_path is not None else None),
        provider=normalized_provider,
        tool_stack_kind=tool_stack_kind,
        profile_modes=normalized_modes,
        profile_seed_by_mode=normalized_profile_seeds,
        repeat_count=repeat_count,
        discovered_run_count=export_result.discovered_run_count,
        included_run_count=export_result.included_run_count,
        skipped_run_count=export_result.skipped_run_count,
        observed_sample_count=export_result.sample_count,
        source_run_count_by_mode=source_run_count_by_mode,
        completed_run_count_by_mode=completed_run_count_by_mode,
        sample_count_by_mode=sample_count_by_mode,
        training_prep_enabled=prepare_training_input,
        training_prep_contract_ok=(
            prepared_recommendation.contract_ok if prepared_recommendation is not None else None
        ),
        contract_ok=contract_ok,
        raw_dataset_manifest_path=str(raw_dataset_dir / "dataset_manifest.json"),
        raw_source_manifest_path=str(raw_dataset_dir / "source_manifest.json"),
        training_prep_path=(str(training_prep_path) if training_prep_path else None),
        acceptance_report_path=str(acceptance_report_path),
        generation_summary_path=str(generation_summary_path),
        generation_manifest_path=str(generation_manifest_path),
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


def _build_source_stack(tool_stack_kind: ToolStackKind):
    if tool_stack_kind == "native_claude":
        return build_native_claude_runtime()
    if tool_stack_kind == "native_codex":
        return build_native_codex_runtime()
    raise ValueError(f"Unknown tool_stack_kind: {tool_stack_kind!r}")


def _resolve_mutation_config_path(
    tool_stack_kind: ToolStackKind,
    mutation_config_path: str | Path | None,
) -> Path | None:
    if mutation_config_path is not None:
        return Path(mutation_config_path)
    return _DEFAULT_NATIVE_FAMILY_MUTATION_CONFIG


def _normalized_profile_seed_by_mode(
    profile_modes: list[str],
    profile_seed_by_mode: dict[str, int] | None,
) -> dict[str, int]:
    mapping = dict(DEFAULT_MUTATION_DATA_PROFILE_SEED_BY_MODE)
    if profile_seed_by_mode:
        for mode, seed in profile_seed_by_mode.items():
            mapping[str(mode)] = int(seed)
    return {mode: int(mapping.get(mode, 0)) for mode in profile_modes}


def _count_source_runs_by_mode(runs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for run in runs:
        mode = str(run.get("source_profile_mode", "unknown"))
        counts[mode] = counts.get(mode, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _count_completed_runs_by_mode(runs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for run in runs:
        if str(run.get("status")) != "completed":
            continue
        mode = str(run.get("source_profile_mode", "unknown"))
        counts[mode] = counts.get(mode, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _count_samples_by_mode(raw_samples: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in raw_samples:
        mode = str(sample.metadata.get("source_profile_mode", "unknown"))
        counts[mode] = counts.get(mode, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _build_acceptance_report(
    *,
    configured_modes: list[str],
    source_run_count_by_mode: dict[str, int],
    completed_run_count_by_mode: dict[str, int],
    sample_count_by_mode: dict[str, int],
    raw_samples: list[Any],
    training_prep_enabled: bool,
    training_prep_contract_ok: bool | None,
) -> dict[str, Any]:
    source_profile_mode_present = all(
        bool(sample.metadata.get("source_profile_mode")) for sample in raw_samples
    )
    family_metadata_present = all(
        bool(sample.metadata.get("source_family")) for sample in raw_samples
    )
    contract_kind_metadata_present = all(
        bool(sample.metadata.get("source_contract_kind")) for sample in raw_samples
    )
    schema_variant_metadata_ok = True
    reorder_metadata_ok = True
    target_call_preserved = True
    freeform_payload_preserved = True
    for sample in raw_samples:
        mode = str(sample.metadata.get("source_profile_mode", ""))
        source_contract_kind = str(sample.metadata.get("source_contract_kind", "function"))
        if mode in {"argument_rename", "schema_flat_to_nested"}:
            category = sample.metadata.get("schema_variant_category")
            if (
                source_contract_kind != "freeform"
                and category not in {"argument_rename", "schema_flat_to_nested"}
            ):
                schema_variant_metadata_ok = False
        if mode == "tool_reorder":
            if "tool_order_changed" not in sample.metadata or "source_tool_reordered" not in sample.metadata:
                reorder_metadata_ok = False
        if str(sample.target_tool_call.name) != str(sample.metadata.get("source_exposed_tool_name")):
            target_call_preserved = False
        if source_contract_kind == "freeform":
            if sample.target_tool_call.input_text is None:
                freeform_payload_preserved = False

    completed_run_coverage_ok = all(
        completed_run_count_by_mode.get(mode, 0) > 0 for mode in configured_modes
    )
    observed_sample_coverage_ok = all(
        sample_count_by_mode.get(mode, 0) > 0 for mode in configured_modes
    )
    training_prep_ok = (
        (training_prep_contract_ok is True) if training_prep_enabled else True
    )

    gates = {
        "completed_run_coverage_ok": {
            "passed": completed_run_coverage_ok,
            "detail": "Each configured mode must produce at least one completed run.",
        },
        "observed_sample_coverage_ok": {
            "passed": observed_sample_coverage_ok,
            "detail": "Each configured mode must produce at least one observed sample.",
        },
        "source_profile_mode_present": {
            "passed": source_profile_mode_present,
            "detail": "Observed sample metadata must preserve source_profile_mode.",
        },
        "family_metadata_present": {
            "passed": family_metadata_present,
            "detail": "Observed sample metadata must preserve source_family.",
        },
        "contract_kind_metadata_present": {
            "passed": contract_kind_metadata_present,
            "detail": "Observed sample metadata must preserve source_contract_kind.",
        },
        "schema_variant_metadata_ok": {
            "passed": schema_variant_metadata_ok,
            "detail": "Rename/nested modes must preserve schema_variant_category on observed samples.",
        },
        "reorder_metadata_ok": {
            "passed": reorder_metadata_ok,
            "detail": "Tool-reorder samples must preserve reorder-related flags in metadata.",
        },
        "target_call_preserved": {
            "passed": target_call_preserved,
            "detail": "Observed target_tool_call.name must match source_exposed_tool_name.",
        },
        "freeform_payload_preserved": {
            "passed": freeform_payload_preserved,
            "detail": "Freeform observed samples must preserve input_text payloads.",
        },
        "training_prep_ok": {
            "passed": training_prep_ok,
            "detail": "Training prep must succeed when enabled.",
        },
    }
    return {
        "version": 1,
        "configured_modes": configured_modes,
        "source_run_count_by_mode": source_run_count_by_mode,
        "completed_run_count_by_mode": completed_run_count_by_mode,
        "sample_count_by_mode": sample_count_by_mode,
        "training_prep_enabled": training_prep_enabled,
        "training_prep_contract_ok": training_prep_contract_ok,
        "contract_ok": all(bool(gate["passed"]) for gate in gates.values()),
        "gates": gates,
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
