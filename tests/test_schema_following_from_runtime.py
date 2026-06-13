"""Tests for observed ToolView dataset generation from local runtime outputs."""

from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.rl.dataset_manifest import FilterConfig
from pycodeagent.rl.schema_following_dataset import read_schema_following_jsonl
from pycodeagent.rl.schema_following_from_runtime import (
    generate_schema_following_from_runtime_runs,
)
from pycodeagent.testing import (
    cleanup_test_path,
    make_runtime_observed_batch_source,
    make_unique_test_dir,
)
from pycodeagent.tools.bootstrap import build_base_tool_profile, build_builtin_registry
from pycodeagent.trajectory.schema import (
    Message,
    Role,
    RunStatus,
    ToolCall,
    ToolObservation,
    ToolResult,
    Trajectory,
    VerifyResult,
)


_TEST_NAMESPACE = "schema_following_from_runtime"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _write_run(run_dir: Path, trajectory: Trajectory, profile, *, with_runtime_trace: bool) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "trajectory.json").write_text(
        trajectory.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (run_dir / "tool_profile.json").write_text(
        profile.model_dump_json(indent=2),
        encoding="utf-8",
    )
    if with_runtime_trace:
        (run_dir / "runtime_trace.jsonl").write_text("{}\n", encoding="utf-8")


def _make_profile(mode: str = "base", seed: int = 0):
    if mode == "base":
        return build_base_tool_profile()
    return ToolProfileSampler(seed=seed).sample(mode)


def _make_observed_trajectory(
    profile,
    *,
    task_id: str = "task_001",
    status: RunStatus = RunStatus.COMPLETED,
    reward: float = 1.0,
    verifier_passed: bool = True,
    provider_metadata: dict | None = None,
) -> Trajectory:
    registry = build_builtin_registry()
    read_target = profile.project_canonical_call(
        "read_file",
        {"path": "src/calculator.py", "start_line": 1, "end_line": 80},
        call_id="source_call_1",
        canonical_tool=registry.get("read_file"),
    )
    finish_target = profile.project_canonical_call(
        "finish",
        {"answer": "Updated calculator.py and tests now pass."},
        call_id="source_call_2",
        canonical_tool=registry.get("finish"),
    )
    read_call = ToolCall(
        id=read_target.call_id,
        name=read_target.name,
        canonical_name="read_file",
        arguments=read_target.arguments,
    )
    finish_call = ToolCall(
        id=finish_target.call_id,
        name=finish_target.name,
        canonical_name="finish",
        arguments=finish_target.arguments,
    )
    trajectory = Trajectory(
        task_id=task_id,
        repo="examples/buggy_calc",
        tool_profile_id=profile.profile_id,
        messages=[
            Message(role=Role.SYSTEM, content="You are a coding agent."),
            Message(
                role=Role.USER,
                content="Read src/calculator.py and then summarize the fix.",
            ),
            Message(
                role=Role.ASSISTANT,
                content="I will inspect the calculator file first.",
                tool_calls=[read_call],
            ),
            Message(
                role=Role.TOOL,
                content="   1 | def add(a, b):\n   2 |     return a - b",
                tool_call_id=read_call.id,
                tool_name=read_call.name,
                canonical_name=read_call.canonical_name,
            ),
            Message(
                role=Role.ASSISTANT,
                content="I found the issue and can now summarize it.",
                tool_calls=[finish_call],
            ),
        ],
        tool_calls=[read_call, finish_call],
        observations=[
            ToolObservation(
                call=read_call,
                result=ToolResult(ok=True, content="read ok"),
                tool_name=read_call.name,
                canonical_name=read_call.canonical_name,
            )
        ],
        verifier=VerifyResult(passed=verifier_passed, score=1.0 if verifier_passed else 0.0),
        reward=reward,
        status=status,
    )
    if provider_metadata is not None:
        trajectory.metadata["provider"] = provider_metadata
    return trajectory


def _make_batch_source(base: Path, *, mode: str = "base", seed: int = 0) -> tuple[Path, object]:
    batch_dir = base / "batch"
    profile = _make_profile(mode, seed)
    _write_run(
        batch_dir / f"task_001__{profile.profile_id}",
        _make_observed_trajectory(profile),
        profile,
        with_runtime_trace=True,
    )
    _write_run(
        batch_dir / f"task_002__{profile.profile_id}",
        _make_observed_trajectory(
            profile,
            task_id="task_002",
            status=RunStatus.FAILED,
            reward=0.0,
            verifier_passed=False,
        ),
        profile,
        with_runtime_trace=False,
    )
    return batch_dir, profile


def _make_experiment_source(base: Path) -> Path:
    exp_dir = base / "experiment"
    profile = _make_profile("base", 0)
    _write_run(
        exp_dir / "runs" / "seed_0" / "base" / f"task_001__{profile.profile_id}",
        _make_observed_trajectory(profile),
        profile,
        with_runtime_trace=True,
    )
    return exp_dir


def _make_study_source(base: Path) -> Path:
    study_dir = base / "study"
    base_profile = _make_profile("base", 0)
    mutated_profile = _make_profile("name_description_schema", 0)
    _write_run(
        study_dir / "experiments" / "exp_a" / "runs" / "seed_0" / "base" / f"task_001__{base_profile.profile_id}",
        _make_observed_trajectory(base_profile),
        base_profile,
        with_runtime_trace=True,
    )
    _write_run(
        study_dir / "experiments" / "exp_b" / "runs" / "seed_0" / "name_description_schema" / f"task_002__{mutated_profile.profile_id}",
        _make_observed_trajectory(mutated_profile, task_id="task_002"),
        mutated_profile,
        with_runtime_trace=True,
    )
    return study_dir


class TestSchemaFollowingFromRuntime:
    def test_generates_from_batch_outputs(self):
        tmp = _get_test_dir()
        try:
            source_dir, _ = _make_batch_source(tmp)
            output_dir = tmp / "output"
            result = generate_schema_following_from_runtime_runs(
                source_dir,
                output_dir,
                source_type="batch",
                filter_config=FilterConfig(include_failed=False),
                split_seed=42,
            )

            assert result.discovered_run_count == 2
            assert result.included_run_count == 1
            assert result.sample_count == 2
            assert result.present_splits == ["train"]
            assert (output_dir / "source_manifest.json").exists()
        finally:
            _cleanup(tmp)

    def test_generates_from_experiment_outputs(self):
        tmp = _get_test_dir()
        try:
            source_dir = _make_experiment_source(tmp)
            output_dir = tmp / "output"
            result = generate_schema_following_from_runtime_runs(
                source_dir,
                output_dir,
                source_type="experiment",
                split_seed=42,
            )
            assert result.discovered_run_count == 1
            assert result.sample_count == 2
        finally:
            _cleanup(tmp)

    def test_generates_from_study_outputs(self):
        tmp = _get_test_dir()
        try:
            source_dir = _make_study_source(tmp)
            output_dir = tmp / "output"
            result = generate_schema_following_from_runtime_runs(
                source_dir,
                output_dir,
                source_type="study",
                split_seed=42,
            )
            assert result.discovered_run_count == 2
            assert result.sample_count == 4
        finally:
            _cleanup(tmp)

    def test_preserves_provider_provenance_from_source_run(self):
        tmp = _get_test_dir()
        try:
            source_dir = tmp / "batch"
            profile = _make_profile("name_description_schema", 0)
            _write_run(
                source_dir / f"task_001__{profile.profile_id}",
                _make_observed_trajectory(
                    profile,
                    provider_metadata={
                        "provider_kind": "mimo",
                        "client_mode": "mimo_native_tools",
                        "model": "mimo-v2.5-pro",
                        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                        "api_key_env": "PYCODEAGENT_API_KEY",
                        "timeout_seconds": 120.0,
                        "max_retries": 3,
                        "temperature": None,
                        "max_output_tokens": None,
                        "protocol_mode": "native_tool_calling",
                        "supports_native_tools": True,
                        "text_fallback_allowed": False,
                        "structured_finish_mode": "finish_tool_call",
                        "provider_family": "openai_chat_completions",
                        "provider_name": "mimo",
                    },
                ),
                profile,
                with_runtime_trace=True,
            )
            output_dir = tmp / "output"
            generate_schema_following_from_runtime_runs(
                source_dir,
                output_dir,
                source_type="batch",
                split_seed=42,
            )

            samples = read_schema_following_jsonl(output_dir / "train.jsonl")
            read_sample = next(sample for sample in samples if sample.canonical_intent.tool == "read_file")
            assert read_sample.metadata["source_provider_kind"] == "mimo"
            assert read_sample.metadata["source_client_mode"] == "mimo_native_tools"
            assert read_sample.metadata["source_model"] == "mimo-v2.5-pro"
            assert read_sample.metadata["source_base_url"] == "https://token-plan-cn.xiaomimimo.com/v1"
            assert read_sample.metadata["source_api_key_env"] == "PYCODEAGENT_API_KEY"
            assert read_sample.metadata["source_protocol_mode"] == "native_tool_calling"
            assert read_sample.metadata["source_supports_native_tools"] is True
            assert read_sample.metadata["source_text_fallback_allowed"] is False
            assert read_sample.metadata["source_structured_finish_mode"] == "finish_tool_call"
            assert read_sample.metadata["source_provider_family"] == "openai_chat_completions"
            assert read_sample.metadata["source_provider_name"] == "mimo"

            source_manifest = json.loads((output_dir / "source_manifest.json").read_text(encoding="utf-8"))
            assert source_manifest["runs"][0]["provider_kind"] == "mimo"
            assert source_manifest["runs"][0]["client_mode"] == "mimo_native_tools"
            assert source_manifest["runs"][0]["protocol_mode"] == "native_tool_calling"
            assert source_manifest["runs"][0]["supports_native_tools"] is True
            assert source_manifest["runs"][0]["text_fallback_allowed"] is False
        finally:
            _cleanup(tmp)

    def test_preserves_observed_target_call_for_mutated_profile(self):
        tmp = _get_test_dir()
        try:
            source_dir, profile = _make_batch_source(
                tmp,
                mode="name_description_schema",
                seed=0,
            )
            output_dir = tmp / "output"
            generate_schema_following_from_runtime_runs(
                source_dir,
                output_dir,
                source_type="batch",
                filter_config=FilterConfig(include_failed=False),
                split_seed=42,
            )
            samples = read_schema_following_jsonl(output_dir / "train.jsonl")
            read_sample = next(
                sample for sample in samples if sample.canonical_intent.tool == "read_file"
            )
            assert read_sample.source_type == "runtime_observed"
            assert read_sample.target_tool_call.name != "read_file"
            assert read_sample.target_tool_call.name == profile.tools[1].exposed_name
            assert read_sample.metadata["source_profile_mode"] == "name_description_schema"
            assert read_sample.metadata["source_profile_seed"] == 0
            assert read_sample.metadata["mutation_axes"] == ["name", "description", "schema"]
            assert read_sample.metadata["compat_mode"] == "name_description_schema"
            assert read_sample.metadata["mutation_manifest_version"] == 1
            assert read_sample.metadata["source_reorder_anchor_policy"] == "finish_last"
            assert read_sample.metadata["schema_variant_category"] == profile.tools[1].metadata["schema_variant_category"]
            assert read_sample.metadata["source_name_variant_id"] == profile.tools[1].metadata["name_variant_id"]
            assert read_sample.metadata["source_description_variant_id"] == profile.tools[1].metadata["description_variant_id"]
            assert read_sample.metadata["source_schema_variant_id"] == profile.tools[1].metadata["schema_variant_id"]
            assert read_sample.metadata["source_tool_reordered"] is False
            assert read_sample.metadata["source_exposed_tool_name"] == read_sample.target_tool_call.name
            assert read_sample.metadata["canonical_tool_name"] == "read_file"
            assert read_sample.metadata["source_runtime_trace_present"] is True
            assert read_sample.mutation_category == "name_description_schema"
        finally:
            _cleanup(tmp)

    def test_manifest_uses_runtime_observed_identity_and_train_only_split(self):
        tmp = _get_test_dir()
        try:
            source_dir, _ = _make_batch_source(tmp)
            output_dir = tmp / "output"
            generate_schema_following_from_runtime_runs(
                source_dir,
                output_dir,
                source_type="batch",
                filter_config=FilterConfig(include_failed=False),
                split_seed=42,
            )
            manifest = json.loads((output_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
            assert manifest["dataset_type"] == "schema_following_runtime_observed"
            assert manifest["present_splits"] == ["train"]
            assert (output_dir / "train.jsonl").exists()
            assert not (output_dir / "eval_seen.jsonl").exists()
        finally:
            _cleanup(tmp)

    def test_observed_samples_audit_against_runtime_trace_for_mutated_run(self):
        tmp = _get_test_dir()
        try:
            source = make_runtime_observed_batch_source(
                tmp,
                task_id="observed_mutated_task",
                task_prompt="Inspect main.py and finish.",
                profile_mode="name_description_schema",
                profile_seed=0,
            )
            output_dir = tmp / "output_audit"
            generate_schema_following_from_runtime_runs(
                source.batch_root,
                output_dir,
                source_type="batch",
                split_seed=42,
            )

            samples = read_schema_following_jsonl(output_dir / "train.jsonl")
            read_sample = next(
                sample for sample in samples if sample.canonical_intent.tool == "read_file"
            )
            profile_manifest = json.loads(
                (output_dir / "profile_manifest.json").read_text(encoding="utf-8")
            )
            source_manifest = json.loads(
                (output_dir / "source_manifest.json").read_text(encoding="utf-8")
            )
            runtime_events = [
                json.loads(line)
                for line in (source.batch_run_dir / "runtime_trace.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

            tool_profile_event = next(
                event for event in runtime_events if event["event_kind"] == "tool_profile_exposed"
            )
            mapping_event = next(
                event
                for event in runtime_events
                if event["event_kind"] == "tool_call_mapping_completed"
                and event["tool_call_id"] == "c1"
            )
            execution_event = next(
                event
                for event in runtime_events
                if event["event_kind"] == "tool_execution_completed"
                and event["tool_call_id"] == "c1"
            )

            assert read_sample.metadata["source_profile_mode"] == tool_profile_event["data"]["profile_mode"]
            assert read_sample.metadata["source_profile_seed"] == tool_profile_event["data"]["profile_seed"]
            assert read_sample.metadata["mutation_axes"] == tool_profile_event["data"]["mutation_axes"]
            assert read_sample.metadata["compat_mode"] == tool_profile_event["data"]["compat_mode"]
            assert read_sample.metadata["mutation_manifest_version"] == tool_profile_event["data"]["mutation_manifest_version"]
            assert read_sample.metadata["source_reorder_anchor_policy"] == tool_profile_event["data"]["reorder_anchor_policy"]
            assert read_sample.target_tool_call.name == mapping_event["data"]["exposed_tool_name"]
            assert read_sample.canonical_intent.tool == mapping_event["data"]["canonical_tool_name"]
            assert read_sample.metadata["source_execution_kind"] == "file_read"
            assert read_sample.metadata["source_policy_decision"] == "allow"
            assert read_sample.metadata["source_policy_domain"] == "filesystem"
            assert read_sample.metadata["source_execution_stage"] == "result_finalize"
            assert read_sample.metadata["source_tool_result_ok"] is True
            assert read_sample.metadata["source_tool_result_is_error"] is False
            assert read_sample.metadata["source_target_file_count"] == 1
            assert read_sample.metadata["source_trace_turn_index"] == execution_event["turn_index"]
            assert (
                read_sample.metadata["source_trace_execution_event_kind"]
                == execution_event["event_kind"]
            )
            assert profile_manifest["profiles"][0]["profile_id"] == source.profile.profile_id
            assert [
                tool["exposed_name"] for tool in profile_manifest["profiles"][0]["tools"]
            ] == tool_profile_event["data"]["tool_order"]
            assert profile_manifest["profiles"][0]["schema_variant_categories"] == tool_profile_event["data"]["schema_variant_categories"]
            assert profile_manifest["profiles"][0]["selected_variant_ids"] == tool_profile_event["data"]["selected_variant_ids"]
            assert source_manifest["runs"][0]["runtime_trace_present"] is True
            assert read_sample.metadata["source_runtime_trace_present"] is True
            assert read_sample.metadata["source_run_dir"] == source_manifest["runs"][0]["run_dir"]
        finally:
            _cleanup(tmp)

    def test_tool_reorder_observed_metadata_preserves_order_indices(self):
        tmp = _get_test_dir()
        try:
            source_dir, profile = _make_batch_source(
                tmp,
                mode="tool_reorder",
                seed=0,
            )
            output_dir = tmp / "output_reorder"
            generate_schema_following_from_runtime_runs(
                source_dir,
                output_dir,
                source_type="batch",
                filter_config=FilterConfig(include_failed=False),
                split_seed=42,
            )
            samples = read_schema_following_jsonl(output_dir / "train.jsonl")
            read_sample = next(
                sample for sample in samples if sample.canonical_intent.tool == "read_file"
            )
            read_view = next(
                tool for tool in profile.tools if tool.canonical_name == "read_file"
            )

            assert read_sample.metadata["mutation_axes"] == ["tool_reorder"]
            assert read_sample.metadata["tool_order_changed"] is True
            assert read_sample.metadata["source_tool_reordered"] is True
            assert read_sample.metadata["source_reorder_anchor_policy"] == "finish_last"
            assert read_sample.metadata["source_tool_order_index"] == read_view.metadata["tool_order_index_exposed"]
            assert read_sample.metadata["source_canonical_tool_order_index"] == read_view.metadata["tool_order_index_base"]
        finally:
            _cleanup(tmp)

    def test_skips_malformed_observed_call_and_exports_corrected_followup(self):
        tmp = _get_test_dir()
        try:
            source_dir = tmp / "batch"
            profile = _make_profile("schema_flat_to_nested", 0)
            registry = build_builtin_registry()
            valid_target = profile.project_canonical_call(
                "search_code",
                {"query": "def test"},
                call_id="source_call_valid",
                canonical_tool=registry.get("search_code"),
            )
            malformed_call = ToolCall(
                id="source_call_bad",
                name=valid_target.name,
                canonical_name="search_code",
                arguments={"pattern": "def test"},
            )
            valid_call = ToolCall(
                id=valid_target.call_id,
                name=valid_target.name,
                canonical_name="search_code",
                arguments=valid_target.arguments,
            )
            trajectory = Trajectory(
                task_id="task_malformed_nested",
                repo="examples/buggy_calc",
                tool_profile_id=profile.profile_id,
                messages=[
                    Message(role=Role.SYSTEM, content="You are a coding agent."),
                    Message(role=Role.USER, content="Search for tests."),
                    Message(role=Role.ASSISTANT, content="", tool_calls=[malformed_call]),
                    Message(
                        role=Role.TOOL,
                        content="Exposed schema validation failed: exposed schema violation at $.pattern: expected object",
                        tool_call_id=malformed_call.id,
                        tool_name=malformed_call.name,
                        canonical_name=malformed_call.canonical_name,
                    ),
                    Message(role=Role.ASSISTANT, content="", tool_calls=[valid_call]),
                    Message(
                        role=Role.TOOL,
                        content="No matches found.",
                        tool_call_id=valid_call.id,
                        tool_name=valid_call.name,
                        canonical_name=valid_call.canonical_name,
                    ),
                ],
                tool_calls=[malformed_call, valid_call],
                observations=[
                    ToolObservation(
                        call=malformed_call,
                        result=ToolResult(
                            ok=False,
                            content="Exposed schema validation failed: exposed schema violation at $.pattern: expected object",
                            metadata={
                                "error_type": "schema_validation",
                                "stage": "validate_exposed_arguments",
                            },
                            is_error=True,
                        ),
                        tool_name=malformed_call.name,
                        canonical_name=malformed_call.canonical_name,
                    ),
                    ToolObservation(
                        call=valid_call,
                        result=ToolResult(
                            ok=True,
                            content="No matches found.",
                            metadata={
                                "execution_kind": "file_search",
                                "policy_decision": "allow",
                                "policy_domain": "filesystem",
                                "execution_stage": "result_finalize",
                            },
                        ),
                        tool_name=valid_call.name,
                        canonical_name=valid_call.canonical_name,
                    ),
                ],
                verifier=VerifyResult(passed=True, score=1.0),
                reward=1.0,
                status=RunStatus.COMPLETED,
            )
            _write_run(
                source_dir / f"task_malformed_nested__{profile.profile_id}",
                trajectory,
                profile,
                with_runtime_trace=False,
            )
            output_dir = tmp / "output_malformed_nested"
            result = generate_schema_following_from_runtime_runs(
                source_dir,
                output_dir,
                source_type="batch",
                split_seed=42,
            )

            assert result.sample_count == 1
            assert result.skipped_observed_call_count == 1
            assert result.skipped_observed_call_counts_by_reason == {
                "canonical_intent_recovery_failed": 1
            }

            samples = read_schema_following_jsonl(output_dir / "train.jsonl")
            assert len(samples) == 1
            assert samples[0].target_tool_call.call_id == "source_call_valid"
            assert samples[0].canonical_intent.tool == "search_code"

            source_manifest = json.loads(
                (output_dir / "source_manifest.json").read_text(encoding="utf-8")
            )
            assert source_manifest["exported_sample_count"] == 1
            assert source_manifest["skipped_observed_call_count"] == 1
            assert source_manifest["skipped_observed_call_counts_by_reason"] == {
                "canonical_intent_recovery_failed": 1
            }
            run_entry = source_manifest["runs"][0]
            assert run_entry["observed_tool_call_count"] == 2
            assert run_entry["exported_observed_tool_call_count"] == 1
            assert run_entry["skipped_observed_tool_call_count"] == 1
            assert run_entry["skipped_observed_tool_call_counts_by_reason"] == {
                "canonical_intent_recovery_failed": 1
            }
            assert run_entry["skipped_observed_tool_calls"][0]["tool_call_id"] == "source_call_bad"
            assert run_entry["skipped_observed_tool_calls"][0]["skip_reason"] == (
                "canonical_intent_recovery_failed"
            )
        finally:
            _cleanup(tmp)
