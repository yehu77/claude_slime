"""Observed ToolView dataset generation from local runtime outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.rl.dataset_builder import discover_run_dirs
from pycodeagent.rl.dataset_manifest import FilterConfig
from pycodeagent.rl.schema_following import (
    CanonicalToolIntent,
    ExposedToolCallTarget,
    SchemaFollowingMessage,
    SchemaFollowingSample,
)
from pycodeagent.rl.schema_following_dataset import write_schema_following_jsonl
from pycodeagent.tools.bootstrap import build_builtin_registry
from pycodeagent.tools.spec import ToolArgumentError, ToolProfile
from pycodeagent.trajectory.schema import (
    Message,
    Role,
    RunStatus,
    ToolObservation,
    Trajectory,
)


class RuntimeObservedProfileManifestEntry(BaseModel):
    """One observed ToolProfile captured from local runtime outputs."""

    profile_id: str
    mode: str
    seed: int
    mutation_axes: list[str] = Field(default_factory=list)
    compat_mode: str | None = None
    mutation_manifest_version: int = 1
    reorder_anchor_policy: str = "finish_last"
    tool_order_seed: int | None = None
    schema_variant_categories: dict[str, str | None] = Field(default_factory=dict)
    selected_variant_ids: dict[str, dict[str, str | None]] = Field(default_factory=dict)
    tools: list[dict[str, Any]]


class RuntimeObservedGenerationResult(BaseModel):
    """Summary of one observed runtime export run."""

    output_dir: str
    sample_count: int
    source_dir: str
    source_type: str
    discovered_run_count: int
    included_run_count: int
    skipped_run_count: int
    skipped_observed_call_count: int = 0
    skipped_observed_call_counts_by_reason: dict[str, int] = Field(default_factory=dict)
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


def _load_runtime_trace_events(run_dir: Path) -> list[dict[str, Any]]:
    """Load runtime trace events when present."""
    trace_path = run_dir / "runtime_trace.jsonl"
    if not trace_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    return events


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


def _tool_manifest_entry(profile: ToolProfile) -> list[dict[str, Any]]:
    """Return manifest-friendly tool metadata for one observed profile."""
    items: list[dict[str, Any]] = []
    for tool in profile.tools:
        adapter = profile.adapters.get(tool.exposed_name)
        items.append(
            {
                "canonical_name": tool.canonical_name,
                "exposed_name": tool.exposed_name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "metadata": tool.metadata,
                "adapter": (
                    adapter.model_dump(mode="json")
                    if adapter is not None
                    else {"exposed_to_canonical": {}, "defaults": {}}
                ),
            }
        )
    return items


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def _skip_observed_call_record(
    *,
    call_id: str,
    exposed_tool_name: str,
    canonical_tool_name: str | None,
    message_index: int,
    step_index: int,
    reason: str,
    detail: str,
) -> dict[str, Any]:
    """Build a stable audit record for one skipped observed call."""
    return {
        "tool_call_id": call_id,
        "exposed_tool_name": exposed_tool_name,
        "canonical_tool_name": canonical_tool_name,
        "message_index": message_index,
        "step_index": step_index,
        "skip_reason": reason,
        "detail": detail,
    }


def _profile_mode(profile: ToolProfile) -> str:
    return str(profile.metadata.get("mode", "base"))


def _profile_seed(profile: ToolProfile) -> int:
    raw_value = profile.metadata.get("seed", 0)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0


def _profile_mutation_axes(profile: ToolProfile) -> list[str]:
    raw_value = profile.metadata.get("mutation_axes", [])
    if not isinstance(raw_value, list):
        return []
    return [str(item) for item in raw_value]


def _profile_tool_order_seed(profile: ToolProfile) -> int | None:
    raw_value = profile.metadata.get("tool_order_seed")
    if raw_value is None:
        return None


def _profile_mutation_manifest_version(profile: ToolProfile) -> int:
    raw_value = profile.metadata.get("mutation_manifest_version", 1)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 1
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _runtime_provider_metadata(trajectory: Trajectory) -> dict[str, Any]:
    raw_value = trajectory.metadata.get("provider", {})
    if not isinstance(raw_value, dict):
        return {}
    return dict(raw_value)


def _observation_index(trajectory: Trajectory) -> dict[str, ToolObservation]:
    """Index tool observations by tool_call_id."""
    return {observation.call.id: observation for observation in trajectory.observations}


def _runtime_trace_event_index(
    events: list[dict[str, Any]],
    event_kind: str,
) -> dict[str, dict[str, Any]]:
    """Index runtime trace events by tool_call_id for one event kind."""
    indexed: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("event_kind") != event_kind:
            continue
        tool_call_id = event.get("tool_call_id")
        if isinstance(tool_call_id, str) and tool_call_id:
            indexed[tool_call_id] = event
    return indexed


def _derive_execution_provenance(
    *,
    observation: ToolObservation | None,
    mapping_event: dict[str, Any] | None,
    execution_event: dict[str, Any] | None,
) -> dict[str, Any]:
    """Derive stable execution/policy provenance for one observed tool call."""
    result_metadata = observation.result.metadata if observation is not None else {}
    execution_data = execution_event.get("data", {}) if execution_event is not None else {}
    target_file_count = result_metadata.get("target_file_count")
    if target_file_count is None:
        target_paths = result_metadata.get("resolved_target_paths")
        if isinstance(target_paths, list):
            target_file_count = len(target_paths)
        else:
            target_file_count = execution_data.get("target_file_count")
    trace_turn_index = None
    if execution_event is not None:
        trace_turn_index = execution_event.get("turn_index")
    elif mapping_event is not None:
        trace_turn_index = mapping_event.get("turn_index")
    return {
        "source_execution_kind": result_metadata.get("execution_kind")
        or execution_data.get("execution_kind"),
        "source_policy_decision": result_metadata.get("policy_decision")
        or execution_data.get("policy_decision"),
        "source_policy_reason": result_metadata.get("policy_reason")
        or execution_data.get("policy_reason"),
        "source_policy_reason_code": result_metadata.get("policy_reason_code")
        or execution_data.get("policy_reason_code"),
        "source_policy_domain": result_metadata.get("policy_domain")
        or execution_data.get("policy_domain"),
        "source_execution_stage": result_metadata.get("execution_stage")
        or result_metadata.get("stage")
        or execution_data.get("execution_stage"),
        "source_command_family": result_metadata.get("command_family")
        or execution_data.get("command_family"),
        "source_tool_result_ok": observation.result.ok if observation is not None else None,
        "source_tool_result_is_error": (
            observation.result.is_error if observation is not None else None
        ),
        "source_target_file_count": target_file_count,
        "source_content_delta_kind": result_metadata.get("content_delta_kind"),
        "source_change_applied": result_metadata.get("change_applied"),
        "source_trace_turn_index": trace_turn_index,
        "source_trace_execution_event_kind": (
            execution_event.get("event_kind") if execution_event is not None else None
        ),
    }


def generate_schema_following_from_runtime_runs(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    source_type: str = "study",
    filter_config: FilterConfig | None = None,
    split_seed: int = 42,
) -> RuntimeObservedGenerationResult:
    """Generate observed ToolView samples from existing local runtime outputs."""
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    filter_config = filter_config or FilterConfig(include_failed=False)
    run_dirs = discover_run_dirs(source_dir, source_type=source_type)
    registry = build_builtin_registry()
    split_samples: dict[str, list[SchemaFollowingSample]] = {"train": []}
    source_runs: list[dict[str, Any]] = []
    profile_manifest: dict[str, RuntimeObservedProfileManifestEntry] = {}
    included_run_count = 0
    skipped_run_count = 0
    skipped_observed_call_count = 0
    skipped_observed_call_counts_by_reason: dict[str, int] = {}

    for run_dir in run_dirs:
        trajectory = _load_trajectory(run_dir)
        source_profile = _load_tool_profile(run_dir)
        runtime_trace_events = _load_runtime_trace_events(run_dir)
        observations_by_call_id = _observation_index(trajectory)
        mapping_events_by_call_id = _runtime_trace_event_index(
            runtime_trace_events,
            "tool_call_mapping_completed",
        )
        execution_events_by_call_id = {
            **_runtime_trace_event_index(runtime_trace_events, "tool_execution_completed"),
            **_runtime_trace_event_index(runtime_trace_events, "tool_execution_failed"),
        }
        profile_mode = _profile_mode(source_profile)
        profile_seed = _profile_seed(source_profile)
        mutation_axes = _profile_mutation_axes(source_profile)
        compat_mode = source_profile.metadata.get("compat_mode")
        mutation_manifest_version = _profile_mutation_manifest_version(source_profile)
        reorder_anchor_policy = str(
            source_profile.metadata.get("reorder_anchor_policy", "finish_last")
        )
        tool_order_seed = _profile_tool_order_seed(source_profile)
        schema_variant_categories = dict(
            source_profile.metadata.get("schema_variant_categories", {})
        )
        selected_variant_ids = dict(
            source_profile.metadata.get("selected_variant_ids", {})
        )
        runtime_trace_present = (run_dir / "runtime_trace.jsonl").exists()
        verifier_passed = trajectory.verifier.passed if trajectory.verifier else False
        provider_metadata = _runtime_provider_metadata(trajectory)
        run_observed_tool_call_count = 0
        run_exported_observed_tool_call_count = 0
        run_skipped_observed_tool_calls: list[dict[str, Any]] = []
        run_skipped_observed_tool_call_counts_by_reason: dict[str, int] = {}
        run_metadata = {
            "run_dir": str(run_dir),
            "task_id": trajectory.task_id,
            "source_tool_profile_id": trajectory.tool_profile_id,
            "source_profile_mode": profile_mode,
            "source_profile_seed": profile_seed,
            "mutation_axes": mutation_axes,
            "compat_mode": compat_mode,
            "mutation_manifest_version": mutation_manifest_version,
            "reorder_anchor_policy": reorder_anchor_policy,
            "tool_order_seed": tool_order_seed,
            "status": trajectory.status.value,
            "reward": trajectory.reward,
            "verifier_passed": verifier_passed,
            "tool_call_count": len(trajectory.tool_calls),
            "runtime_trace_present": runtime_trace_present,
            "provider_kind": provider_metadata.get("provider_kind"),
            "client_mode": provider_metadata.get("client_mode"),
            "model": provider_metadata.get("model"),
            "base_url": provider_metadata.get("base_url"),
            "api_key_env": provider_metadata.get("api_key_env"),
            "timeout_seconds": provider_metadata.get("timeout_seconds"),
            "max_retries": provider_metadata.get("max_retries"),
            "temperature": provider_metadata.get("temperature"),
            "max_output_tokens": provider_metadata.get("max_output_tokens"),
            "protocol_mode": provider_metadata.get("protocol_mode"),
            "supports_native_tools": provider_metadata.get("supports_native_tools"),
            "text_fallback_allowed": provider_metadata.get("text_fallback_allowed"),
            "structured_finish_mode": provider_metadata.get("structured_finish_mode"),
            "provider_family": provider_metadata.get("provider_family"),
            "provider_name": provider_metadata.get("provider_name"),
            "observed_tool_call_count": 0,
            "exported_observed_tool_call_count": 0,
            "skipped_observed_tool_call_count": 0,
            "skipped_observed_tool_call_counts_by_reason": {},
            "skipped_observed_tool_calls": [],
        }
        source_runs.append(run_metadata)

        if source_profile.profile_id not in profile_manifest:
            profile_manifest[source_profile.profile_id] = RuntimeObservedProfileManifestEntry(
                profile_id=source_profile.profile_id,
                mode=profile_mode,
                seed=profile_seed,
                mutation_axes=mutation_axes,
                compat_mode=(
                    str(compat_mode) if compat_mode is not None else None
                ),
                mutation_manifest_version=mutation_manifest_version,
                reorder_anchor_policy=reorder_anchor_policy,
                tool_order_seed=tool_order_seed,
                schema_variant_categories=schema_variant_categories,
                selected_variant_ids=selected_variant_ids,
                tools=_tool_manifest_entry(source_profile),
            )

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
                run_observed_tool_call_count += 1
                try:
                    resolved = source_profile.get_tool(call.name)
                except KeyError:
                    reason = "unknown_exposed_tool"
                    detail = f"Unknown exposed tool {call.name!r}"
                    run_skipped_observed_tool_calls.append(
                        _skip_observed_call_record(
                            call_id=call.id,
                            exposed_tool_name=call.name,
                            canonical_tool_name=call.canonical_name,
                            message_index=message_index,
                            step_index=tool_call_step_index,
                            reason=reason,
                            detail=detail,
                        )
                    )
                    run_skipped_observed_tool_call_counts_by_reason[reason] = (
                        run_skipped_observed_tool_call_counts_by_reason.get(reason, 0) + 1
                    )
                    skipped_observed_call_count += 1
                    skipped_observed_call_counts_by_reason[reason] = (
                        skipped_observed_call_counts_by_reason.get(reason, 0) + 1
                    )
                    continue

                source_view, _ = resolved
                canonical_name = call.canonical_name or source_view.canonical_name
                try:
                    canonical_tool = registry.get(canonical_name)
                except Exception as exc:
                    reason = "unknown_canonical_tool"
                    detail = str(exc)
                    run_skipped_observed_tool_calls.append(
                        _skip_observed_call_record(
                            call_id=call.id,
                            exposed_tool_name=call.name,
                            canonical_tool_name=canonical_name,
                            message_index=message_index,
                            step_index=tool_call_step_index,
                            reason=reason,
                            detail=detail,
                        )
                    )
                    run_skipped_observed_tool_call_counts_by_reason[reason] = (
                        run_skipped_observed_tool_call_counts_by_reason.get(reason, 0) + 1
                    )
                    skipped_observed_call_count += 1
                    skipped_observed_call_counts_by_reason[reason] = (
                        skipped_observed_call_counts_by_reason.get(reason, 0) + 1
                    )
                    continue
                source_tool_order_index = int(
                    source_view.metadata.get("tool_order_index_exposed", 0)
                )
                source_canonical_tool_order_index = int(
                    source_view.metadata.get("tool_order_index_base", 0)
                )
                schema_variant_category = source_view.metadata.get(
                    "schema_variant_category"
                )
                name_variant_id = source_view.metadata.get("name_variant_id")
                description_variant_id = source_view.metadata.get(
                    "description_variant_id"
                )
                schema_variant_id = source_view.metadata.get("schema_variant_id")
                tool_reordered = bool(source_view.metadata.get("tool_reordered", False))

                try:
                    _, canonical_args = source_profile.map_call_arguments(
                        call.name,
                        call.arguments,
                        canonical_tool=canonical_tool,
                    )
                except (ToolArgumentError, KeyError, TypeError) as exc:
                    reason = "canonical_intent_recovery_failed"
                    detail = str(exc)
                    run_skipped_observed_tool_calls.append(
                        _skip_observed_call_record(
                            call_id=call.id,
                            exposed_tool_name=call.name,
                            canonical_tool_name=canonical_name,
                            message_index=message_index,
                            step_index=tool_call_step_index,
                            reason=reason,
                            detail=detail,
                        )
                    )
                    run_skipped_observed_tool_call_counts_by_reason[reason] = (
                        run_skipped_observed_tool_call_counts_by_reason.get(reason, 0) + 1
                    )
                    skipped_observed_call_count += 1
                    skipped_observed_call_counts_by_reason[reason] = (
                        skipped_observed_call_counts_by_reason.get(reason, 0) + 1
                    )
                    continue

                roundtrip_call = source_profile.project_canonical_call(
                    canonical_name,
                    canonical_args,
                    call_id=call.id,
                    canonical_tool=canonical_tool,
                )
                if (
                    roundtrip_call.name != call.name
                    or roundtrip_call.arguments != call.arguments
                ):
                    reason = "roundtrip_mismatch"
                    detail = (
                        "Observed runtime call roundtrip mismatch: "
                        f"{(roundtrip_call.name, roundtrip_call.arguments)!r} "
                        f"!= {(call.name, call.arguments)!r}"
                    )
                    run_skipped_observed_tool_calls.append(
                        _skip_observed_call_record(
                            call_id=call.id,
                            exposed_tool_name=call.name,
                            canonical_tool_name=canonical_name,
                            message_index=message_index,
                            step_index=tool_call_step_index,
                            reason=reason,
                            detail=detail,
                        )
                    )
                    run_skipped_observed_tool_call_counts_by_reason[reason] = (
                        run_skipped_observed_tool_call_counts_by_reason.get(reason, 0) + 1
                    )
                    skipped_observed_call_count += 1
                    skipped_observed_call_counts_by_reason[reason] = (
                        skipped_observed_call_counts_by_reason.get(reason, 0) + 1
                    )
                    continue

                target_call = ExposedToolCallTarget(
                    call_id=call.id,
                    name=call.name,
                    arguments=call.arguments,
                )
                execution_provenance = _derive_execution_provenance(
                    observation=observations_by_call_id.get(call.id),
                    mapping_event=mapping_events_by_call_id.get(call.id),
                    execution_event=execution_events_by_call_id.get(call.id),
                )
                split_samples["train"].append(
                    SchemaFollowingSample(
                        sample_id=(
                            "sf__runtime_observed__"
                            f"{run_dir.name}__{source_profile.profile_id}__step{tool_call_step_index:04d}"
                        ),
                        sample_type="schema_following",
                        source_type="runtime_observed",
                        split="train",
                        task_id=trajectory.task_id,
                        tool_profile_id=source_profile.profile_id,
                        mutation_category=profile_mode,
                        messages=context_messages,
                        canonical_intent=CanonicalToolIntent(
                            tool=canonical_name,
                            arguments=canonical_args,
                        ),
                        target_tool_call=target_call,
                        target_text=target_call.render_text(),
                        loss_mask_policy="assistant_tool_call_only",
                        metadata={
                            "source_run_dir": str(run_dir),
                            "source_type": source_type,
                            "source_tool_profile_id": trajectory.tool_profile_id,
                            "source_profile_mode": profile_mode,
                            "source_profile_seed": profile_seed,
                            "mutation_axes": mutation_axes,
                            "compat_mode": compat_mode,
                            "mutation_manifest_version": mutation_manifest_version,
                            "source_reorder_anchor_policy": reorder_anchor_policy,
                            "tool_order_changed": source_tool_order_index != source_canonical_tool_order_index,
                            "source_tool_reordered": tool_reordered,
                            "source_name_variant_id": name_variant_id,
                            "source_description_variant_id": description_variant_id,
                            "source_schema_variant_id": schema_variant_id,
                            "schema_variant_category": schema_variant_category,
                            "source_exposed_tool_name": call.name,
                            "source_tool_call_id": call.id,
                            "source_message_index": message_index,
                            "source_step_index": tool_call_step_index,
                            "source_tool_order_index": source_tool_order_index,
                            "source_canonical_tool_order_index": source_canonical_tool_order_index,
                            "canonical_tool_name": canonical_name,
                            "source_status": trajectory.status.value,
                            "source_reward": trajectory.reward,
                            "source_verifier_passed": verifier_passed,
                            "source_runtime_trace_present": runtime_trace_present,
                            "source_provider_kind": provider_metadata.get("provider_kind"),
                            "source_client_mode": provider_metadata.get("client_mode"),
                            "source_model": provider_metadata.get("model"),
                            "source_base_url": provider_metadata.get("base_url"),
                            "source_api_key_env": provider_metadata.get("api_key_env"),
                            "source_timeout_seconds": provider_metadata.get("timeout_seconds"),
                            "source_max_retries": provider_metadata.get("max_retries"),
                            "source_temperature": provider_metadata.get("temperature"),
                            "source_max_output_tokens": provider_metadata.get("max_output_tokens"),
                            "source_protocol_mode": provider_metadata.get("protocol_mode"),
                            "source_supports_native_tools": provider_metadata.get("supports_native_tools"),
                            "source_text_fallback_allowed": provider_metadata.get("text_fallback_allowed"),
                            "source_structured_finish_mode": provider_metadata.get("structured_finish_mode"),
                            "source_provider_family": provider_metadata.get("provider_family"),
                            "source_provider_name": provider_metadata.get("provider_name"),
                            **execution_provenance,
                        },
                    )
                )
                run_exported_observed_tool_call_count += 1

        run_metadata["observed_tool_call_count"] = run_observed_tool_call_count
        run_metadata["exported_observed_tool_call_count"] = run_exported_observed_tool_call_count
        run_metadata["skipped_observed_tool_call_count"] = len(run_skipped_observed_tool_calls)
        run_metadata["skipped_observed_tool_call_counts_by_reason"] = (
            dict(sorted(run_skipped_observed_tool_call_counts_by_reason.items()))
        )
        run_metadata["skipped_observed_tool_calls"] = run_skipped_observed_tool_calls

    for split_name, samples in split_samples.items():
        write_schema_following_jsonl(samples, output_dir / f"{split_name}.jsonl")

    split_counts = {split_name: len(samples) for split_name, samples in split_samples.items()}
    present_splits = [name for name, count in split_counts.items() if count > 0]
    profile_manifest_path = output_dir / "profile_manifest.json"
    dataset_manifest_path = output_dir / "dataset_manifest.json"
    source_manifest_path = output_dir / "source_manifest.json"
    split_metrics_path = output_dir / "split_metrics.json"
    manifest_profiles = list(profile_manifest.values())

    _write_json(
        profile_manifest_path,
        {
            "version": 1,
            "profiles": [entry.model_dump(mode="json") for entry in manifest_profiles],
        },
    )
    _write_json(
        dataset_manifest_path,
        {
            "dataset_type": "schema_following_runtime_observed",
            "version": 1,
            "split_seed": split_seed,
            "source_dir": str(source_dir),
            "source_type": source_type,
            "sample_count": sum(split_counts.values()),
            "skipped_observed_call_count": skipped_observed_call_count,
            "skipped_observed_call_counts_by_reason": dict(
                sorted(skipped_observed_call_counts_by_reason.items())
            ),
            "loss_mask_policy": "assistant_tool_call_only",
            "present_splits": present_splits,
            "profile_ids": [entry.profile_id for entry in manifest_profiles],
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
            "exported_sample_count": sum(split_counts.values()),
            "skipped_observed_call_count": skipped_observed_call_count,
            "skipped_observed_call_counts_by_reason": dict(
                sorted(skipped_observed_call_counts_by_reason.items())
            ),
            "filter_config": filter_config.model_dump(mode="json"),
            "runs": source_runs,
        },
    )
    _write_json(
        split_metrics_path,
        {
            "version": 1,
            "split_seed": split_seed,
            "split_counts": split_counts,
        },
    )

    return RuntimeObservedGenerationResult(
        output_dir=str(output_dir),
        sample_count=sum(split_counts.values()),
        source_dir=str(source_dir),
        source_type=source_type,
        discovered_run_count=len(run_dirs),
        included_run_count=included_run_count,
        skipped_run_count=skipped_run_count,
        skipped_observed_call_count=skipped_observed_call_count,
        skipped_observed_call_counts_by_reason=dict(
            sorted(skipped_observed_call_counts_by_reason.items())
        ),
        split_counts=split_counts,
        profile_ids=[entry.profile_id for entry in manifest_profiles],
        profile_manifest_path=str(profile_manifest_path),
        dataset_manifest_path=str(dataset_manifest_path),
        source_manifest_path=str(source_manifest_path),
        split_metrics_path=str(split_metrics_path),
        present_splits=present_splits,
    )
