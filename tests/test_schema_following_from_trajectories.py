"""Tests for trajectory-derived schema-following dataset generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.rl.dataset_manifest import FilterConfig
from pycodeagent.rl.schema_following_dataset import read_schema_following_jsonl
from pycodeagent.rl.schema_following_from_trajectories import (
    generate_schema_following_from_trajectories,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
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


_TEST_NAMESPACE = "schema_following_from_trajectories"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _write_run(run_dir: Path, trajectory: Trajectory, profile) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "trajectory.json").write_text(
        trajectory.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (run_dir / "tool_profile.json").write_text(
        profile.model_dump_json(indent=2),
        encoding="utf-8",
    )


def _make_base_profile():
    return build_base_tool_profile()


def _make_trajectory(
    *,
    task_id: str = "task_001",
    tool_profile_id: str = "base",
    status: RunStatus = RunStatus.COMPLETED,
    reward: float = 1.0,
    verifier_passed: bool = True,
) -> Trajectory:
    read_call = ToolCall(
        id="source_call_1",
        name="read_file",
        canonical_name="read_file",
        arguments={"path": "src/calculator.py", "start_line": 1, "end_line": 80},
    )
    finish_call = ToolCall(
        id="source_call_2",
        name="finish",
        canonical_name="finish",
        arguments={"answer": "Updated calculator.py and tests now pass."},
    )
    return Trajectory(
        task_id=task_id,
        repo="examples/buggy_calc",
        tool_profile_id=tool_profile_id,
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


def _make_batch_source(base: Path) -> Path:
    batch_dir = base / "batch"
    _write_run(batch_dir / "task_001__base", _make_trajectory(), _make_base_profile())
    _write_run(
        batch_dir / "task_002__base",
        _make_trajectory(
            task_id="task_002",
            status=RunStatus.FAILED,
            reward=0.0,
            verifier_passed=False,
        ),
        _make_base_profile(),
    )
    return batch_dir


def _make_experiment_source(base: Path) -> Path:
    exp_dir = base / "experiment"
    _write_run(
        exp_dir / "runs" / "seed_0" / "base" / "task_001__base",
        _make_trajectory(),
        _make_base_profile(),
    )
    return exp_dir


def _make_study_source(base: Path) -> Path:
    study_dir = base / "study"
    exp_a = study_dir / "experiments" / "exp_a"
    _write_run(
        exp_a / "runs" / "seed_0" / "base" / "task_001__base",
        _make_trajectory(),
        _make_base_profile(),
    )
    exp_b = study_dir / "experiments" / "exp_b"
    _write_run(
        exp_b / "runs" / "seed_0" / "base" / "task_002__base",
        _make_trajectory(task_id="task_002"),
        _make_base_profile(),
    )
    return study_dir


class TestSchemaFollowingFromTrajectories:
    def test_generates_from_batch_outputs(self):
        tmp = _get_test_dir()
        try:
            source_dir = _make_batch_source(tmp)
            output_dir = tmp / "output"
            result = generate_schema_following_from_trajectories(
                source_dir,
                output_dir,
                source_type="batch",
                filter_config=FilterConfig(include_failed=False),
                seed=42,
            )

            assert result.discovered_run_count == 2
            assert result.included_run_count == 1
            assert result.sample_count > 0
            assert (output_dir / "source_manifest.json").exists()
        finally:
            _cleanup(tmp)

    def test_generates_from_experiment_outputs(self):
        tmp = _get_test_dir()
        try:
            source_dir = _make_experiment_source(tmp)
            output_dir = tmp / "output"
            result = generate_schema_following_from_trajectories(
                source_dir,
                output_dir,
                source_type="experiment",
                seed=42,
            )
            assert result.discovered_run_count == 1
            assert result.sample_count > 0
        finally:
            _cleanup(tmp)

    def test_generates_from_study_outputs(self):
        tmp = _get_test_dir()
        try:
            source_dir = _make_study_source(tmp)
            output_dir = tmp / "output"
            result = generate_schema_following_from_trajectories(
                source_dir,
                output_dir,
                source_type="study",
                seed=42,
            )
            assert result.discovered_run_count == 2
            assert result.sample_count > 0
        finally:
            _cleanup(tmp)

    def test_preserves_source_metadata_and_context(self):
        tmp = _get_test_dir()
        try:
            source_dir = _make_batch_source(tmp)
            output_dir = tmp / "output"
            generate_schema_following_from_trajectories(
                source_dir,
                output_dir,
                source_type="batch",
                filter_config=FilterConfig(include_failed=False),
                seed=42,
            )
            samples = read_schema_following_jsonl(output_dir / "train.jsonl")
            sample = samples[0]
            assert sample.source_type == "trajectory_derived"
            assert "source_run_dir" in sample.metadata
            assert "source_tool_call_id" in sample.metadata
            assert sample.messages[0].role == "system"
            assert sample.messages[1].role == "user"
            assert sample.messages[-1].role == "assistant"
        finally:
            _cleanup(tmp)

    def test_reprojected_targets_roundtrip_to_canonical(self):
        tmp = _get_test_dir()
        try:
            source_dir = _make_batch_source(tmp)
            output_dir = tmp / "output"
            generate_schema_following_from_trajectories(
                source_dir,
                output_dir,
                source_type="batch",
                filter_config=FilterConfig(include_failed=False),
                seed=42,
            )
            registry = build_builtin_registry()
            profile_manifest = json.loads(
                (output_dir / "profile_manifest.json").read_text(encoding="utf-8")
            )
            profiles = {}
            for entry in profile_manifest["profiles"]:
                if entry["mode"] == "base":
                    profiles[entry["profile_id"]] = build_base_tool_profile(
                        profile_id=entry["profile_id"]
                    )
                else:
                    profiles[entry["profile_id"]] = ToolProfileSampler(seed=entry["seed"]).sample(
                        entry["mode"]
                    )

            for split_name in ("train", "eval_seen", "eval_unseen_name", "eval_unseen_description", "eval_unseen_schema", "eval_nested"):
                for sample in read_schema_following_jsonl(output_dir / f"{split_name}.jsonl"):
                    profile = profiles[sample.tool_profile_id]
                    canonical_tool = registry.get(sample.canonical_intent.tool)
                    _, canonical_args = profile.map_call_arguments(
                        sample.target_tool_call.name,
                        sample.target_tool_call.arguments,
                        canonical_tool=canonical_tool,
                    )
                    assert canonical_args == sample.canonical_intent.arguments
        finally:
            _cleanup(tmp)

    def test_include_failed_policy_is_explicit(self):
        tmp = _get_test_dir()
        try:
            source_dir = _make_batch_source(tmp)
            output_a = tmp / "output_a"
            output_b = tmp / "output_b"
            result_excluding = generate_schema_following_from_trajectories(
                source_dir,
                output_a,
                source_type="batch",
                filter_config=FilterConfig(include_failed=False),
                seed=42,
            )
            result_including = generate_schema_following_from_trajectories(
                source_dir,
                output_b,
                source_type="batch",
                filter_config=FilterConfig(include_failed=True),
                seed=42,
            )
            assert result_excluding.included_run_count == 1
            assert result_including.included_run_count == 2
            assert result_including.sample_count > result_excluding.sample_count
        finally:
            _cleanup(tmp)
