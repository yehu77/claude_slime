"""Tests for slime-compatible data contract verification."""

from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.rl.contract import verify_dataset_dir, verify_slime_contract
from pycodeagent.rl.dataset_builder import RolloutDatasetBuilder
from pycodeagent.rl.dataset_manifest import FilterConfig
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig
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


_TEST_NAMESPACE = "contract"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def make_trajectory(
    *,
    task_id: str = "task_001",
    tool_profile_id: str = "base",
    reward: float = 1.0,
    status: RunStatus = RunStatus.COMPLETED,
    verifier: VerifyResult | None = None,
) -> Trajectory:
    if verifier is None:
        verifier = VerifyResult(passed=True, score=1.0)

    call = ToolCall(
        id="call_1",
        name="read_file",
        canonical_name="read_file",
        arguments={"path": "src/app.py"},
    )
    result = ToolResult(ok=True, content="def buggy():\n    return 1\n")

    return Trajectory(
        task_id=task_id,
        repo="examples/buggy_calc",
        tool_profile_id=tool_profile_id,
        messages=[
            Message(role=Role.SYSTEM, content="You are a coding agent."),
            Message(role=Role.USER, content="Fix the failing tests."),
            Message(
                role=Role.ASSISTANT,
                content="I will inspect the file first.",
                tool_calls=[call],
            ),
            Message(
                role=Role.TOOL,
                content=result.content,
                tool_call_id=call.id,
                tool_name=call.name,
                canonical_name=call.canonical_name,
            ),
            Message(role=Role.ASSISTANT, content="I found the bug and will patch it."),
        ],
        tool_calls=[call],
        observations=[
            ToolObservation(
                call=call,
                result=result,
                tool_name=call.name,
                canonical_name=call.canonical_name,
                tool_version="base.v1",
            )
        ],
        final_diff="--- a/src/app.py\n+++ b/src/app.py\n@@\n-return 1\n+return 2\n",
        reward=reward,
        status=status,
        verifier=verifier,
        metadata={"seed": 0, "mode": tool_profile_id},
    )


def _write_trajectory(run_dir: Path, trajectory: Trajectory) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "trajectory.json").write_text(
        trajectory.model_dump_json(),
        encoding="utf-8",
    )


def _make_experiment_dir(base: Path, name: str, trajectories: list[Trajectory]) -> Path:
    exp_dir = base / name
    for trajectory in trajectories:
        run_dir = (
            exp_dir
            / "runs"
            / "seed_0"
            / trajectory.tool_profile_id
            / f"{trajectory.task_id}__{trajectory.tool_profile_id}"
        )
        _write_trajectory(run_dir, trajectory)
    return exp_dir


def _make_study_dir(base: Path) -> Path:
    study_dir = base / "study"
    experiments_dir = study_dir / "experiments"
    _make_experiment_dir(
        experiments_dir,
        "e_base_123456",
        [
            make_trajectory(task_id="task_a", tool_profile_id="base"),
            make_trajectory(
                task_id="task_b",
                tool_profile_id="base",
                status=RunStatus.FAILED,
                verifier=VerifyResult(passed=False, score=0.0),
                reward=0.1,
            ),
        ],
    )
    _make_experiment_dir(
        experiments_dir,
        "e_schema_654321",
        [
            make_trajectory(task_id="task_c", tool_profile_id="schema_only"),
        ],
    )
    return study_dir


class TestVerifySlimeContract:
    def test_verify_experiment_contract_success(self):
        tmp = _get_test_dir()
        try:
            exp_dir = _make_experiment_dir(
                tmp,
                "experiment",
                [
                    make_trajectory(task_id="task_1", tool_profile_id="base"),
                    make_trajectory(
                        task_id="task_2",
                        tool_profile_id="schema_only",
                        status=RunStatus.FAILED,
                        verifier=VerifyResult(passed=False, score=0.0),
                        reward=0.1,
                    ),
                    make_trajectory(
                        task_id="task_3",
                        tool_profile_id="description_only",
                        status=RunStatus.ERROR,
                        verifier=VerifyResult(passed=False, score=0.0),
                        reward=-0.2,
                    ),
                ],
            )
            output_dir = tmp / "verified"

            result = verify_slime_contract(
                exp_dir,
                output_dir,
                source_type="experiment",
                filter_config=FilterConfig(include_failed=True),
                fake_tokenizer_config=FakeTokenizerConfig(),
                pack_max_length=128,
            )

            assert result.ok is True
            assert result.sample_count == 3
            assert result.rollout_count == 3
            assert result.tokenized_count == 3
            assert result.loaded_example_count == 3
            assert result.status_counts == {
                "completed": 1,
                "error": 1,
                "failed": 1,
            }
            assert sorted(result.profile_ids) == [
                "base",
                "description_only",
                "schema_only",
            ]
            assert (output_dir / "dataset_manifest.json").exists()
            assert (output_dir / "rollouts.jsonl").exists()
            assert (output_dir / "samples.jsonl").exists()
            assert not (output_dir / "tokenized.jsonl").exists()
            assert not (output_dir / "contract_report.json").exists()
        finally:
            _cleanup(tmp)

    def test_verify_dataset_dir_requires_explicit_tokenizer_selection(self):
        tmp = _get_test_dir()
        try:
            exp_dir = _make_experiment_dir(
                tmp,
                "experiment",
                [make_trajectory(task_id="task_1")],
            )
            dataset_dir = tmp / "dataset"

            builder = RolloutDatasetBuilder(dataset_id="requires_tokenizer_ds")
            builder.build_from_experiment(
                exp_dir,
                dataset_dir,
                filter_config=FilterConfig(include_failed=True),
            )

            try:
                verify_dataset_dir(dataset_dir, pack_max_length=64)
            except ValueError as exc:
                assert "Explicit tokenizer selection is required" in str(exc)
            else:
                raise AssertionError("verify_dataset_dir should require explicit tokenizer selection")
        finally:
            _cleanup(tmp)

    def test_verify_dataset_dir_detects_corruption(self):
        tmp = _get_test_dir()
        try:
            exp_dir = _make_experiment_dir(
                tmp,
                "experiment",
                [make_trajectory(task_id="task_1")],
            )
            dataset_dir = tmp / "dataset"

            builder = RolloutDatasetBuilder(dataset_id="corrupt_ds")
            builder.build_from_experiment(
                exp_dir,
                dataset_dir,
                filter_config=FilterConfig(include_failed=True),
            )

            samples_path = dataset_dir / "samples.jsonl"
            lines = samples_path.read_text(encoding="utf-8").splitlines()
            bad_sample = json.loads(lines[0])
            bad_sample["character_mask"] = bad_sample["character_mask"][:-1]
            lines[0] = json.dumps(bad_sample, ensure_ascii=False)
            samples_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            result = verify_dataset_dir(
                dataset_dir,
                fake_tokenizer_config=FakeTokenizerConfig(),
                pack_max_length=64,
            )

            assert result.ok is False
            assert any(
                issue.code == "sample_mask_length_mismatch"
                for issue in result.issues
            )
        finally:
            _cleanup(tmp)

    def test_verify_study_contract_aggregates_child_experiments(self):
        tmp = _get_test_dir()
        try:
            study_dir = _make_study_dir(tmp)
            output_dir = tmp / "study_verified"

            result = verify_slime_contract(
                study_dir,
                output_dir,
                source_type="study",
                filter_config=FilterConfig(include_failed=True),
                fake_tokenizer_config=FakeTokenizerConfig(),
                pack_max_length=128,
                write_report=True,
            )

            assert result.ok is True
            assert len(result.children) == 2
            assert result.sample_count == 3
            assert result.rollout_count == 3
            assert result.tokenized_count == 3
            assert sorted(result.task_ids) == ["task_a", "task_b", "task_c"]
            assert (output_dir / "contract_report.json").exists()
            assert (output_dir / "e_base_123456" / "contract_report.json").exists()
            assert (output_dir / "e_schema_654321" / "contract_report.json").exists()
        finally:
            _cleanup(tmp)

    def test_tokenized_dataset_written_and_loadable(self):
        tmp = _get_test_dir()
        try:
            exp_dir = _make_experiment_dir(
                tmp,
                "experiment",
                [
                    make_trajectory(task_id="task_1"),
                    make_trajectory(task_id="task_2", tool_profile_id="schema_only"),
                ],
            )
            output_dir = tmp / "verified"

            result = verify_slime_contract(
                exp_dir,
                output_dir,
                source_type="experiment",
                filter_config=FilterConfig(include_failed=True),
                fake_tokenizer_config=FakeTokenizerConfig(),
                pack_max_length=128,
                materialize_tokenized=True,
                write_report=True,
            )

            dataset = TrainDataset.from_jsonl(output_dir / "tokenized.jsonl")
            assert len(dataset) == result.tokenized_count
            assert dataset[0].metadata["task_id"] == "task_1"
            assert dataset[1].metadata["tool_profile_id"] == "schema_only"
            assert (output_dir / "contract_report.json").exists()
        finally:
            _cleanup(tmp)

    def test_verify_contract_flags_when_truncation_drops_all_trainable_tokens(self):
        tmp = _get_test_dir()
        try:
            exp_dir = _make_experiment_dir(
                tmp,
                "experiment",
                [make_trajectory(task_id="task_1")],
            )
            output_dir = tmp / "verified"

            result = verify_slime_contract(
                exp_dir,
                output_dir,
                source_type="experiment",
                filter_config=FilterConfig(include_failed=True),
                fake_tokenizer_config=FakeTokenizerConfig(),
                pack_max_length=1,
            )

            assert result.ok is False
            assert any(
                issue.code == "tokenized_no_trainable_tokens"
                for issue in result.issues
            )
        finally:
            _cleanup(tmp)
