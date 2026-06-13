"""Tests for preparing recommended slime training inputs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pycodeagent.rl import build_native_transformed_sft_dataset
from pycodeagent.rl.train_config import TrainConfig
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.rl.training_prep import (
    prepare_native_transformed_sft_training_input,
    prepare_slime_training_input,
)
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.trajectory.schema import Message, Role, RunStatus, Trajectory, VerifyResult


_TEST_NAMESPACE = "training_prep"
_REAL_TOOL_USE_SESSION_PATH = Path("tests/fixtures/claude_api_tool_use_session.jsonl")


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
    return Trajectory(
        task_id=task_id,
        repo="examples/buggy_calc",
        tool_profile_id=tool_profile_id,
        messages=[
            Message(role=Role.SYSTEM, content="You are a coding agent."),
            Message(role=Role.USER, content="Fix the issue."),
            Message(role=Role.ASSISTANT, content="I will make the patch now."),
        ],
        final_diff="--- a/a.py\n+++ b/a.py\n@@\n-x=1\n+x=2\n",
        reward=reward,
        status=status,
        verifier=verifier,
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
        "e_base_111111",
        [
            make_trajectory(task_id="task_a", tool_profile_id="base"),
            make_trajectory(
                task_id="task_b",
                tool_profile_id="base",
                verifier=VerifyResult(passed=False, score=0.0),
                reward=0.1,
            ),
            make_trajectory(
                task_id="task_c",
                tool_profile_id="base",
                status=RunStatus.ERROR,
                verifier=VerifyResult(passed=False, score=0.0),
                reward=-0.2,
            ),
        ],
    )
    _make_experiment_dir(
        experiments_dir,
        "e_schema_222222",
        [make_trajectory(task_id="task_d", tool_profile_id="schema_only")],
    )
    return study_dir


class TestPrepareSlimeTrainingInput:
    def test_prepare_requires_explicit_tokenizer_selection(self):
        tmp = _get_test_dir()
        try:
            exp_dir = _make_experiment_dir(
                tmp,
                "experiment",
                [make_trajectory(task_id="task_1")],
            )
            output_dir = tmp / "prepared"

            with pytest.raises(ValueError, match="Explicit tokenizer selection is required"):
                prepare_slime_training_input(
                    exp_dir,
                    output_dir,
                    source_type="experiment",
                    max_length=2048,
                )
        finally:
            _cleanup(tmp)

    def test_prepare_study_defaults_exclude_non_completed_runs(self):
        tmp = _get_test_dir()
        try:
            study_dir = _make_study_dir(tmp)
            output_dir = tmp / "prepared"

            recommendation = prepare_slime_training_input(
                study_dir,
                output_dir,
                source_type="study",
                fake_tokenizer_config=FakeTokenizerConfig(),
                max_length=2048,
            )

            assert recommendation.contract_ok is True
            assert recommendation.include_failed is False
            assert recommendation.canonical_rollout_input == "rollouts.jsonl"
            assert recommendation.canonical_training_input == "tokenized.jsonl"
            assert recommendation.completed_run_count == 3
            assert recommendation.excluded_run_count == 1
            assert (output_dir / "rollouts.jsonl").exists()
            assert (output_dir / "samples.jsonl").exists()
            assert (output_dir / "tokenized.jsonl").exists()
            assert (output_dir / "training_prep.json").exists()
            assert (output_dir / "contract_report.json").exists()
        finally:
            _cleanup(tmp)


class TestPrepareNativeTransformedSFTTrainingInput:
    def test_prepare_validated_native_transformed_dataset(self):
        if not _REAL_TOOL_USE_SESSION_PATH.exists():
            pytest.skip(f"Missing real Claude tool-use fixture: {_REAL_TOOL_USE_SESSION_PATH}")
        tmp = _get_test_dir()
        try:
            source = tmp / "source"
            dataset_dir = tmp / "native_transformed"
            prepared_dir = tmp / "prepared"
            source.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_REAL_TOOL_USE_SESSION_PATH, source / _REAL_TOOL_USE_SESSION_PATH.name)
            build_native_transformed_sft_dataset(source, dataset_dir)

            recommendation = prepare_native_transformed_sft_training_input(
                dataset_dir,
                prepared_dir,
                fake_tokenizer_config=FakeTokenizerConfig(chars_per_token=1000),
                max_length=20000,
                batch_size=4,
                learning_rate=2e-5,
                run_id="native_prep_test",
            )

            assert recommendation.validation_ok is True
            assert recommendation.primary_sample_input == "train.jsonl"
            assert recommendation.primary_prepared_input == "samples.jsonl"
            assert recommendation.primary_training_input == "tokenized.jsonl"
            assert recommendation.raw_sample_count == recommendation.prepared_sample_count
            assert recommendation.tokenized_example_count == recommendation.prepared_sample_count
            assert (prepared_dir / "samples.jsonl").exists()
            assert (prepared_dir / "tokenized.jsonl").exists()
            assert (prepared_dir / "training_prep.json").exists()

            tokenizer_config = TokenizerConfig.load(prepared_dir / "tokenizer_config.yaml")
            train_config = TrainConfig.load(prepared_dir / "train_config.json")
            dataset = TrainDataset.from_jsonl(prepared_dir / "tokenized.jsonl")

            assert tokenizer_config.metadata["source_type"] == "native_transformed_claude_api_sft"
            assert tokenizer_config.metadata["primary_sample_input"] == "train.jsonl"
            assert train_config.run_id == "native_prep_test"
            assert train_config.batch_size == 4
            assert train_config.learning_rate == 2e-5
            assert len(dataset) == recommendation.tokenized_example_count
            assert dataset[0].metadata["sample_type"] == "claude_api_sft"
            assert dataset[0].metadata["source_type"] == "native_transformed_claude_api_sft"
            assert dataset[0].metadata["raw_source_type"] == "claude_api_trace"
            assert dataset[0].trainable_token_count > 0
        finally:
            _cleanup(tmp)

    def test_prepare_requires_exported_dataset_manifest(self):
        if not _REAL_TOOL_USE_SESSION_PATH.exists():
            pytest.skip(f"Missing real Claude tool-use fixture: {_REAL_TOOL_USE_SESSION_PATH}")
        tmp = _get_test_dir()
        try:
            source = tmp / "source"
            dataset_dir = tmp / "native_transformed"
            prepared_dir = tmp / "prepared"
            source.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_REAL_TOOL_USE_SESSION_PATH, source / _REAL_TOOL_USE_SESSION_PATH.name)
            build_native_transformed_sft_dataset(source, dataset_dir)
            (dataset_dir / "dataset_manifest.json").unlink()

            with pytest.raises(ValueError, match="failed validation"):
                prepare_native_transformed_sft_training_input(
                    dataset_dir,
                    prepared_dir,
                    fake_tokenizer_config=FakeTokenizerConfig(chars_per_token=1000),
                    max_length=20000,
                )
        finally:
            _cleanup(tmp)

    def test_prepare_writes_loadable_tokenizer_and_train_configs(self):
        tmp = _get_test_dir()
        try:
            exp_dir = _make_experiment_dir(
                tmp,
                "experiment",
                [make_trajectory(task_id="task_1"), make_trajectory(task_id="task_2")],
            )
            output_dir = tmp / "prepared"

            recommendation = prepare_slime_training_input(
                exp_dir,
                output_dir,
                source_type="experiment",
                fake_tokenizer_config=FakeTokenizerConfig(),
                max_length=2048,
                batch_size=16,
                learning_rate=5e-5,
                run_id="prep_test_run",
            )

            tokenizer_config = TokenizerConfig.load(output_dir / "tokenizer_config.yaml")
            train_config = TrainConfig.load(output_dir / "train_config.json")

            assert tokenizer_config.max_length == 2048
            assert train_config.run_id == "prep_test_run"
            assert train_config.batch_size == 16
            assert train_config.learning_rate == 5e-5
            assert train_config.dataset_path == str(output_dir / "tokenized.jsonl")
            assert recommendation.train_config_path == str(output_dir / "train_config.json")
        finally:
            _cleanup(tmp)

    def test_prepare_tokenized_dataset_is_loadable(self):
        tmp = _get_test_dir()
        try:
            exp_dir = _make_experiment_dir(
                tmp,
                "experiment",
                [make_trajectory(task_id="task_1", tool_profile_id="schema_only")],
            )
            output_dir = tmp / "prepared"

            prepare_slime_training_input(
                exp_dir,
                output_dir,
                source_type="experiment",
                fake_tokenizer_config=FakeTokenizerConfig(),
                max_length=2048,
            )

            dataset = TrainDataset.from_jsonl(output_dir / "tokenized.jsonl")
            assert len(dataset) == 1
            assert dataset[0].metadata["task_id"] == "task_1"
            assert dataset[0].metadata["tool_profile_id"] == "schema_only"
        finally:
            _cleanup(tmp)

    def test_include_failed_true_keeps_error_runs(self):
        tmp = _get_test_dir()
        try:
            study_dir = _make_study_dir(tmp)
            output_dir = tmp / "prepared"

            recommendation = prepare_slime_training_input(
                study_dir,
                output_dir,
                source_type="study",
                include_failed=True,
                fake_tokenizer_config=FakeTokenizerConfig(),
                max_length=2048,
            )

            report = json.loads((output_dir / "contract_report.json").read_text(encoding="utf-8"))
            assert recommendation.excluded_run_count == 0
            assert report["status_counts"]["error"] == 1
        finally:
            _cleanup(tmp)
