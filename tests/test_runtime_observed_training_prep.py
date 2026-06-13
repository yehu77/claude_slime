"""Tests for runtime-observed schema-following training preparation."""

from __future__ import annotations

from pathlib import Path

from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.rl.schema_following_dataset import read_schema_following_jsonl
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.rl.training_prep import (
    prepare_runtime_observed_schema_following_training_input,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.tools.bootstrap import build_builtin_registry
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


_TEST_NAMESPACE = "runtime_observed_training_prep"


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
    (run_dir / "runtime_trace.jsonl").write_text("{}\n", encoding="utf-8")


def _make_runtime_observed_source(base: Path) -> tuple[Path, object]:
    source_dir = base / "batch"
    profile = ToolProfileSampler(seed=0).sample("name_description_schema")
    registry = build_builtin_registry()
    read_target = profile.project_canonical_call(
        "read_file",
        {"path": "main.py"},
        call_id="call_1",
        canonical_tool=registry.get("read_file"),
    )
    finish_target = profile.project_canonical_call(
        "finish",
        {"answer": "Done"},
        call_id="call_2",
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
        task_id="runtime_observed_task",
        repo="examples/runtime_observed",
        tool_profile_id=profile.profile_id,
        messages=[
            Message(role=Role.SYSTEM, content="You are a coding agent."),
            Message(role=Role.USER, content="Read main.py and finish."),
            Message(role=Role.ASSISTANT, content="I will read the file first.", tool_calls=[read_call]),
            Message(
                role=Role.TOOL,
                content="1 | print('hello')",
                tool_call_id=read_call.id,
                tool_name=read_call.name,
                canonical_name=read_call.canonical_name,
            ),
            Message(role=Role.ASSISTANT, content="I can finish now.", tool_calls=[finish_call]),
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
        verifier=VerifyResult(passed=True, score=1.0),
        reward=1.0,
        status=RunStatus.COMPLETED,
    )
    _write_run(source_dir / f"runtime_observed_task__{profile.profile_id}", trajectory, profile)
    return source_dir, profile


class TestRuntimeObservedTrainingPrep:
    def test_prepare_runtime_observed_writes_loadable_bundle(self) -> None:
        tmp = _get_test_dir()
        try:
            source_dir, _ = _make_runtime_observed_source(tmp)
            output_dir = tmp / "prepared"

            recommendation = prepare_runtime_observed_schema_following_training_input(
                source_dir,
                output_dir,
                source_type="batch",
                fake_tokenizer_config=FakeTokenizerConfig(),
                max_length=128,
                batch_size=16,
                learning_rate=5e-5,
                run_id="runtime_observed_train",
            )

            assert recommendation.contract_ok is True
            assert recommendation.discovered_run_count == 1
            assert recommendation.included_run_count == 1
            assert recommendation.observed_sample_count == 2
            assert (output_dir / "raw_dataset" / "train.jsonl").exists()
            assert (output_dir / "prepared" / "samples.jsonl").exists()
            assert (output_dir / "prepared" / "tokenized.jsonl").exists()
            assert (output_dir / "prepared" / "contract_report.json").exists()
            assert (output_dir / "training_prep.json").exists()

            raw_samples = read_schema_following_jsonl(output_dir / "raw_dataset" / "train.jsonl")
            dataset = TrainDataset.from_jsonl(output_dir / "prepared" / "tokenized.jsonl")

            assert len(raw_samples) == 2
            assert raw_samples[0].source_type == "runtime_observed"
            assert recommendation.tokenized_example_count == len(dataset)
            assert recommendation.canonical_sample_input == "raw_dataset/train.jsonl"
            assert recommendation.canonical_training_input == "prepared/tokenized.jsonl"
        finally:
            _cleanup(tmp)
