"""Tests for the pycodeagent -> slime offline bridge."""

from __future__ import annotations

from pathlib import Path

import pytest

from pycodeagent.rl import (
    FakeTokenizerAdapter,
    FakeTokenizerConfig,
    build_tokenized_slime_train_samples,
    is_tokenized_training_path,
    load_bundle_tokenizer_config,
    load_prepared_rollout_bundle,
    map_run_status_to_slime_status,
    prepare_slime_training_input,
    resolve_tokenized_jsonl_path,
    rollout_to_slime_train_sample,
    tensorize_rollout,
    tokenized_example_to_slime_train_sample,
    trajectory_to_slime_rollout,
)
from pycodeagent.rl.tensorize import TokenizedExample
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.trajectory.schema import (
    Message,
    Role,
    RunStatus,
    ToolCall,
    ToolResult,
    Trajectory,
    VerifyResult,
)


_TEST_NAMESPACE = "slime_bridge"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def make_rollout(*, status: RunStatus = RunStatus.COMPLETED):
    traj = Trajectory(
        task_id="task_bridge",
        repo="examples/buggy_calc",
        tool_profile_id="base",
        reward=0.75,
        status=status,
        verifier=VerifyResult(passed=True, score=0.75),
    )
    traj.add_system("You are a coding agent.")
    traj.add_user("Fix the bug.")
    read_call = ToolCall(
        id="call_001",
        name="read_file",
        canonical_name="read_file",
        arguments={"path": "calc.py"},
    )
    traj.add_assistant("I will inspect the file.", tool_calls=[read_call])
    traj.add_tool_observation(
        call=read_call,
        result=ToolResult(ok=True, content="def add(a, b):\n    return a - b\n"),
    )
    patch_call = ToolCall(
        id="call_002",
        name="apply_patch",
        canonical_name="apply_patch",
        arguments={"patch": "--- a/calc.py\n+++ b/calc.py\n@@\n-return a - b\n+return a + b\n"},
    )
    traj.add_assistant("I found the bug and will patch it.", tool_calls=[patch_call])
    traj.add_tool_observation(
        call=patch_call,
        result=ToolResult(ok=True, content="Patch applied successfully."),
    )
    traj.add_assistant("The fix is complete.")
    return trajectory_to_slime_rollout(traj)


def make_non_trainable_rollout():
    traj = Trajectory(
        task_id="task_empty",
        repo="examples/buggy_calc",
        tool_profile_id="base",
        reward=0.0,
        status=RunStatus.COMPLETED,
        verifier=VerifyResult(passed=False, score=0.0),
        messages=[
            Message(role=Role.SYSTEM, content="sys"),
            Message(role=Role.USER, content="user"),
        ],
    )
    return trajectory_to_slime_rollout(traj)


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


class TestSlimeBridge:
    def test_rollout_to_slime_train_sample_matches_tensorized_suffix(self):
        rollout = make_rollout()
        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=5))
        from pycodeagent.rl.tokenizer_config import TokenizerConfig

        config = TokenizerConfig(tokenizer_name="fake", max_length=2048)
        tokenized = tensorize_rollout(rollout, tokenizer, config)
        converted = rollout_to_slime_train_sample(
            rollout,
            tokenizer,
            max_length=config.max_length,
        )

        first_trainable = next(
            i for i, value in enumerate(tokenized.token_train_mask) if value == 1
        )
        assert converted.tokens == tokenized.input_ids
        assert converted.response_length == len(tokenized.input_ids) - first_trainable
        assert converted.loss_mask == tokenized.token_train_mask[first_trainable:]
        assert sum(converted.loss_mask) == tokenized.trainable_token_count
        assert 0 < converted.response_length < len(converted.tokens)
        assert 0 in converted.loss_mask

    def test_rollout_without_trainable_tokens_raises(self):
        rollout = make_non_trainable_rollout()
        tokenizer = FakeTokenizerAdapter()
        with pytest.raises(ValueError, match="no trainable tokens"):
            rollout_to_slime_train_sample(rollout, tokenizer, max_length=2048)

    def test_tokenized_example_to_slime_train_sample_uses_existing_ids_and_mask(self):
        example = TokenizedExample(
            input_ids=[10, 11, 12, 13, 14],
            attention_mask=[1, 1, 1, 1, 1],
            labels=[-100, -100, 12, -100, 14],
            token_train_mask=[0, 0, 1, 0, 1],
            metadata={
                "sample_id": "sample_1",
                "source_type": "native_transformed_claude_api_sft",
                "task_id": "task_1",
                "tool_profile_id": "profile_1",
            },
        )

        converted = tokenized_example_to_slime_train_sample(example)

        assert converted.tokens == example.input_ids
        assert converted.response_length == 3
        assert converted.loss_mask == [1, 0, 1]
        assert converted.reward == 0.0
        assert converted.status == "completed"
        assert converted.metadata["sample_id"] == "sample_1"
        assert converted.metadata["source_type"] == "native_transformed_claude_api_sft"
        assert converted.metadata["tool_profile_id"] == "profile_1"
        assert converted.metadata["trainable_token_count"] == 2
        assert converted.train_metadata["sample_id"] == "sample_1"

    def test_tokenized_example_without_trainable_tokens_raises(self):
        example = TokenizedExample(
            input_ids=[10, 11],
            attention_mask=[1, 1],
            labels=[-100, -100],
            token_train_mask=[0, 0],
            metadata={"sample_id": "sample_empty"},
        )

        with pytest.raises(ValueError, match="no trainable tokens"):
            tokenized_example_to_slime_train_sample(example)

    def test_loads_tokenized_jsonl_from_file_and_directory(self):
        tmp = _get_test_dir()
        try:
            train_dir = tmp / "train"
            example = TokenizedExample(
                input_ids=[1, 2, 3],
                attention_mask=[1, 1, 1],
                labels=[-100, 2, 3],
                token_train_mask=[0, 1, 1],
                metadata={
                    "sample_id": "sample_1",
                    "source_type": "native_transformed_claude_api_sft",
                    "tool_profile_id": "profile_1",
                },
            )
            TrainDataset.from_examples([example]).save_jsonl(
                train_dir / "smoke_tokenized.jsonl"
            )

            assert is_tokenized_training_path(train_dir) is True
            assert resolve_tokenized_jsonl_path(train_dir) == train_dir / "smoke_tokenized.jsonl"
            assert is_tokenized_training_path(train_dir / "smoke_tokenized.jsonl") is True

            from_dir = build_tokenized_slime_train_samples(train_dir)
            from_file = build_tokenized_slime_train_samples(
                train_dir / "smoke_tokenized.jsonl"
            )

            assert len(from_dir) == 1
            assert len(from_file) == 1
            assert from_dir[0].tokens == [1, 2, 3]
            assert from_file[0].loss_mask == [1, 1]
        finally:
            _cleanup(tmp)

    def test_rollouts_jsonl_takes_precedence_over_tokenized_in_directory(self):
        tmp = _get_test_dir()
        try:
            prepared_dir = tmp / "prepared"
            prepared_dir.mkdir(parents=True)
            (prepared_dir / "rollouts.jsonl").write_text("", encoding="utf-8")
            (prepared_dir / "tokenized.jsonl").write_text("", encoding="utf-8")

            assert is_tokenized_training_path(prepared_dir) is False
        finally:
            _cleanup(tmp)

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("completed", "completed"),
            ("failed", "failed"),
            ("error", "failed"),
            ("timeout", "failed"),
            ("unknown", "pending"),
        ],
    )
    def test_status_mapping(self, status: str, expected: str):
        assert map_run_status_to_slime_status(status) == expected

    def test_load_prepared_bundle_from_dir_and_file(self):
        tmp = _get_test_dir()
        try:
            traj = Trajectory(
                task_id="task_1",
                repo="examples/buggy_calc",
                tool_profile_id="base",
                messages=[
                    Message(role=Role.SYSTEM, content="system"),
                    Message(role=Role.USER, content="user"),
                    Message(role=Role.ASSISTANT, content="assistant"),
                ],
                reward=1.0,
                status=RunStatus.COMPLETED,
                verifier=VerifyResult(passed=True, score=1.0),
            )
            exp_dir = _make_experiment_dir(tmp, "experiment", [traj])
            output_dir = tmp / "prepared"
            prepare_slime_training_input(
                exp_dir,
                output_dir,
                source_type="experiment",
                fake_tokenizer_config=FakeTokenizerConfig(),
                max_length=2048,
            )

            from_dir = load_prepared_rollout_bundle(output_dir)
            from_file = load_prepared_rollout_bundle(output_dir / "rollouts.jsonl")
            tokenizer_config = load_bundle_tokenizer_config(output_dir)

            assert len(from_dir.rollouts) == 1
            assert len(from_file.rollouts) == 1
            assert from_dir.rollouts_path == str(output_dir / "rollouts.jsonl")
            assert tokenizer_config is not None
            assert tokenizer_config.max_length == 2048
        finally:
            _cleanup(tmp)
