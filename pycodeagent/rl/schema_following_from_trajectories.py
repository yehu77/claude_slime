"""Trajectory-derived schema-following dataset generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.rl.dataset_builder import discover_run_dirs
from pycodeagent.rl.dataset_manifest import FilterConfig
from pycodeagent.rl.schema_following import (
    SchemaFollowingMessage,
    SchemaFollowingSample,
)
from pycodeagent.rl.schema_following_dataset import write_schema_following_jsonl
from pycodeagent.rl.schema_following_generate import (
    SyntheticProfileManifestEntry,
    _group_profile_ids_by_split_role,
    _tool_manifest_entry,
    _write_json,
)
from pycodeagent.rl.schema_following_splits import (
    SCHEMA_FOLLOWING_SPLIT_ORDER,
    SyntheticProfileSpec,
    assign_synthetic_split,
    build_default_synthetic_profile_specs,
)
from pycodeagent.tools.bootstrap import build_builtin_registry
from pycodeagent.tools.profile_factory import build_base_tool_profile
from pycodeagent.tools.spec import ToolArgumentError, ToolProfile
from pycodeagent.trajectory.schema import Message, Role, RunStatus, Trajectory


class TrajectoryDerivedGenerationResult(BaseModel):
    """Summary of one trajectory-derived generation run."""

    output_dir: str
    sample_count: int
    source_dir: str
    source_type: str
    discovered_run_count: int
    included_run_count: int
    skipped_run_count: int
    split_counts: dict[str, int] = Field(default_factory=dict)
    profile_ids: list[str] = Field(default_factory=list)
    profile_manifest_path: str
    dataset_manifest_path: str
    source_manifest_path: str
    split_metrics_path: str
    present_splits: list[str] = Field(default_factory=list)


def _load_trajectory(run_dir: Path) -> Trajectory:
    """Load trajectory.json from a run directory."""
    trajectory_path = run_dir / "trajectory.json"
    if not trajectory_path.exists():
        raise FileNotFoundError(f"Missing trajectory artifact: {trajectory_path}")
    with open(trajectory_path, encoding="utf-8") as handle:
        data = json.load(handle)
    return Trajectory.model_validate(data)


def _load_tool_profile(run_dir: Path) -> ToolProfile:
    """Load tool_profile.json from a run directory."""
    profile_path = run_dir / "tool_profile.json"
    if not profile_path.exists():
        raise FileNotFoundError(f"Missing tool profile artifact: {profile_path}")
    with open(profile_path, encoding="utf-8") as handle:
        data = json.load(handle)
    return ToolProfile.model_validate(data)


def _passes_filters(trajectory: Trajectory, filter_config: FilterConfig) -> bool:
    """Apply standard run-level filters to a trajectory."""
    if filter_config.allowed_statuses is not None:
        if trajectory.status.value not in filter_config.allowed_statuses:
            return False

    if not filter_config.include_failed and trajectory.status != RunStatus.COMPLETED:
        return False

    verifier_passed = trajectory.verifier.passed if trajectory.verifier else False
    if filter_config.verifier_passed is not None:
        if verifier_passed != filter_config.verifier_passed:
            return False

    if filter_config.min_reward is not None and trajectory.reward < filter_config.min_reward:
        return False

    if filter_config.task_ids is not None and trajectory.task_id not in filter_config.task_ids:
        return False

    if (
        filter_config.profile_ids is not None
        and trajectory.tool_profile_id not in filter_config.profile_ids
    ):
        return False

    return True


def _message_to_schema_message(message: Message) -> SchemaFollowingMessage:
    """Convert one trajectory message to a schema-following message."""
    metadata: dict[str, Any] = {}
    if message.role == Role.TOOL:
        if message.tool_name is not None:
            metadata["tool_name"] = message.tool_name
        if message.tool_call_id is not None:
            metadata["tool_call_id"] = message.tool_call_id
        if message.canonical_name is not None:
            metadata["canonical_name"] = message.canonical_name
    return SchemaFollowingMessage(
        role=message.role.value,
        content=message.content,
        metadata=metadata,
    )


def _context_before_tool_call(
    trajectory: Trajectory,
    assistant_message_index: int,
) -> list[SchemaFollowingMessage]:
    """Extract prompt/history context immediately before an assistant tool call."""
    context = [
        _message_to_schema_message(message)
        for message in trajectory.messages[:assistant_message_index]
    ]
    assistant_message = trajectory.messages[assistant_message_index]
    if assistant_message.content:
        context.append(
            SchemaFollowingMessage(
                role=Role.ASSISTANT.value,
                content=assistant_message.content,
            )
        )
    return context


def _has_nested_values(value: Any) -> bool:
    """Return True when the projected argument object contains nested objects."""
    if isinstance(value, dict):
        return any(
            isinstance(child, dict) or _has_nested_values(child)
            for child in value.values()
        )
    if isinstance(value, list):
        return any(_has_nested_values(child) for child in value)
    return False


def _target_profiles(
    *,
    seed: int,
    profile_specs: list[SyntheticProfileSpec] | None = None,
) -> tuple[list[SyntheticProfileSpec], list[ToolProfile]]:
    """Build target profiles used for re-projection."""
    specs = profile_specs or build_default_synthetic_profile_specs(seed=seed)
    profiles: list[ToolProfile] = []
    for spec in specs:
        if spec.mode == "base":
            profiles.append(build_base_tool_profile(profile_id=f"schema_following_base_{spec.seed}"))
        else:
            from pycodeagent.mutations.profile_sampler import ToolProfileSampler

            profiles.append(ToolProfileSampler(seed=spec.seed).sample(spec.mode))
    return specs, profiles


def generate_schema_following_from_trajectories(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    source_type: str = "study",
    filter_config: FilterConfig | None = None,
    target_profile_specs: list[SyntheticProfileSpec] | None = None,
    seed: int = 42,
) -> TrajectoryDerivedGenerationResult:
    """Generate schema-following samples from existing run trajectories."""
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    filter_config = filter_config or FilterConfig(include_failed=False)
    run_dirs = discover_run_dirs(source_dir, source_type=source_type)
    target_specs, target_profiles = _target_profiles(
        seed=seed,
        profile_specs=target_profile_specs,
    )
    registry = build_builtin_registry()

    split_samples: dict[str, list[SchemaFollowingSample]] = {
        split: [] for split in SCHEMA_FOLLOWING_SPLIT_ORDER
    }
    source_runs: list[dict[str, Any]] = []
    included_run_count = 0
    skipped_run_count = 0

    for run_dir in run_dirs:
        trajectory = _load_trajectory(run_dir)
        source_profile = _load_tool_profile(run_dir)
        verifier_passed = trajectory.verifier.passed if trajectory.verifier else False
        run_metadata = {
            "run_dir": str(run_dir),
            "task_id": trajectory.task_id,
            "source_tool_profile_id": trajectory.tool_profile_id,
            "status": trajectory.status.value,
            "reward": trajectory.reward,
            "verifier_passed": verifier_passed,
            "tool_call_count": len(trajectory.tool_calls),
        }
        source_runs.append(run_metadata)

        if not _passes_filters(trajectory, filter_config):
            skipped_run_count += 1
            continue
        included_run_count += 1

        tool_call_step_index = 0
        for message_index, message in enumerate(trajectory.messages):
            if message.role != Role.ASSISTANT or not message.tool_calls:
                continue

            context_messages = _context_before_tool_call(trajectory, message_index)
            for call in message.tool_calls:
                tool_call_step_index += 1
                try:
                    source_view, canonical_args = source_profile.map_call_arguments(
                        call.name,
                        call.arguments,
                        canonical_tool=registry.get(call.canonical_name or source_profile.get_tool(call.name)[0].canonical_name),  # type: ignore[index]
                    )
                except (ToolArgumentError, KeyError, TypeError) as exc:
                    raise ValueError(
                        f"Unable to recover canonical intent from source call {call.id!r} "
                        f"in {run_dir}: {exc}"
                    ) from exc

                canonical_name = call.canonical_name or source_view.canonical_name
                canonical_tool = registry.get(canonical_name)

                for spec, target_profile in zip(target_specs, target_profiles, strict=True):
                    target_call = target_profile.project_canonical_call(
                        canonical_name,
                        canonical_args,
                        call_id="call_1",
                        canonical_tool=canonical_tool,
                    )
                    _, roundtrip = target_profile.map_call_arguments(
                        target_call.name,
                        target_call.arguments,
                        canonical_tool=canonical_tool,
                    )
                    if roundtrip != canonical_args:
                        raise ValueError(
                            "Trajectory-derived projection roundtrip mismatch for "
                            f"{target_profile.profile_id}/{canonical_name}"
                        )

                    requires_nested_args = _has_nested_values(target_call.arguments)
                    split = assign_synthetic_split(
                        spec,
                        split_key=f"{run_dir}:{call.id}:{target_profile.profile_id}",
                        requires_nested_args=requires_nested_args,
                    )
                    sample = SchemaFollowingSample(
                        sample_id=(
                            "sf__trajectory_derived__"
                            f"{run_dir.name}__{target_profile.profile_id}__step{tool_call_step_index:04d}"
                        ),
                        sample_type="schema_following",
                        source_type="trajectory_derived",
                        split=split,
                        task_id=trajectory.task_id,
                        tool_profile_id=target_profile.profile_id,
                        mutation_category=spec.category,
                        messages=context_messages,
                        canonical_intent={
                            "tool": canonical_name,
                            "arguments": canonical_args,
                        },
                        target_tool_call=target_call,
                        target_text=target_call.render_text(),
                        loss_mask_policy="assistant_tool_call_only",
                        metadata={
                            "source_run_dir": str(run_dir),
                            "source_type": source_type,
                            "source_tool_profile_id": trajectory.tool_profile_id,
                            "source_tool_name": call.name,
                            "source_tool_call_id": call.id,
                            "source_message_index": message_index,
                            "source_step_index": tool_call_step_index,
                            "source_status": trajectory.status.value,
                            "source_reward": trajectory.reward,
                            "source_verifier_passed": verifier_passed,
                            "canonical_tool_name": canonical_name,
                            "profile_mode": spec.mode,
                            "profile_seed": spec.seed,
                            "profile_split_role": spec.split_role,
                            "requires_nested_args": requires_nested_args,
                            "has_distractor_tools": False,
                            "tool_order_seed": 0,
                        },
                    )
                    split_samples[split].append(sample)

    for split_name, samples in split_samples.items():
        write_schema_following_jsonl(samples, output_dir / f"{split_name}.jsonl")

    profile_manifest = [
        SyntheticProfileManifestEntry(
            profile_id=profile.profile_id,
            category=spec.category,
            mode=spec.mode,
            seed=spec.seed,
            split_role=spec.split_role,
            tools=_tool_manifest_entry(profile),
        )
        for spec, profile in zip(target_specs, target_profiles, strict=True)
    ]
    split_counts = {split_name: len(samples) for split_name, samples in split_samples.items()}
    present_splits = [name for name, count in split_counts.items() if count > 0]
    profile_manifest_path = output_dir / "profile_manifest.json"
    dataset_manifest_path = output_dir / "dataset_manifest.json"
    source_manifest_path = output_dir / "source_manifest.json"
    split_metrics_path = output_dir / "split_metrics.json"

    _write_json(
        profile_manifest_path,
        {
            "version": 1,
            "seed": seed,
            "profiles": [entry.model_dump(mode="json") for entry in profile_manifest],
        },
    )
    _write_json(
        dataset_manifest_path,
        {
            "dataset_type": "schema_following_trajectory_derived",
            "version": 1,
            "seed": seed,
            "source_dir": str(source_dir),
            "source_type": source_type,
            "sample_count": sum(split_counts.values()),
            "loss_mask_policy": "assistant_tool_call_only",
            "present_splits": present_splits,
            "profile_ids": [entry.profile_id for entry in profile_manifest],
            "profile_manifest_path": profile_manifest_path.name,
            "source_manifest_path": source_manifest_path.name,
            "split_metrics_path": split_metrics_path.name,
        },
    )
    _write_json(
        source_manifest_path,
        {
            "version": 1,
            "source_dir": str(source_dir),
            "source_type": source_type,
            "discovered_run_count": len(run_dirs),
            "included_run_count": included_run_count,
            "skipped_run_count": skipped_run_count,
            "filter_config": filter_config.model_dump(mode="json"),
            "runs": source_runs,
        },
    )
    _write_json(
        split_metrics_path,
        {
            "version": 1,
            "seed": seed,
            "split_counts": split_counts,
            "profiles_by_split_role": _group_profile_ids_by_split_role(
                target_specs,
                profile_manifest,
            ),
        },
    )

    return TrajectoryDerivedGenerationResult(
        output_dir=str(output_dir),
        sample_count=sum(split_counts.values()),
        source_dir=str(source_dir),
        source_type=source_type,
        discovered_run_count=len(run_dirs),
        included_run_count=included_run_count,
        skipped_run_count=skipped_run_count,
        split_counts=split_counts,
        profile_ids=[entry.profile_id for entry in profile_manifest],
        profile_manifest_path=str(profile_manifest_path),
        dataset_manifest_path=str(dataset_manifest_path),
        source_manifest_path=str(source_manifest_path),
        split_metrics_path=str(split_metrics_path),
        present_splits=present_splits,
    )
