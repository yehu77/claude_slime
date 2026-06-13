"""Tests for schema-following training preparation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.rl.schema_following import (
    CanonicalToolIntent,
    ExposedToolCallTarget,
    SchemaFollowingMessage,
    SchemaFollowingSample,
)
from pycodeagent.rl.schema_following_dataset import write_schema_following_jsonl
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig
from pycodeagent.rl.train_config import TrainConfig
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.rl.training_prep import prepare_schema_following_training_input
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "schema_following_training_prep"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _make_sample() -> SchemaFollowingSample:
    target = ExposedToolCallTarget(
        call_id="call_1",
        name="inspect_file",
        arguments={"path": "src/app.py"},
    )
    return SchemaFollowingSample(
        sample_id="sf__sample__001",
        sample_type="schema_following",
        source_type="synthetic",
        split="train",
        task_id="task_001",
        tool_profile_id="schema_only",
        mutation_category="schema_flat_to_nested",
        messages=[
            SchemaFollowingMessage(role="system", content="You are a coding agent."),
            SchemaFollowingMessage(role="user", content="Inspect src/app.py."),
        ],
        canonical_intent=CanonicalToolIntent(
            tool="read_file",
            arguments={"path": "src/app.py"},
        ),
        target_tool_call=target,
        target_text=target.render_text(),
        loss_mask_policy="assistant_tool_call_only",
    )


def _write_dataset(dataset_dir: Path) -> None:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    write_schema_following_jsonl([_make_sample()], dataset_dir / "train.jsonl")
    (dataset_dir / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "dataset_type": "schema_following_synthetic",
                "version": 1,
                "sample_count": 1,
                "loss_mask_policy": "assistant_tool_call_only",
                "present_splits": ["train"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (dataset_dir / "split_metrics.json").write_text(
        json.dumps({"version": 1, "split_counts": {"train": 1}}, indent=2),
        encoding="utf-8",
    )


class TestPrepareSchemaFollowingTrainingInput:
    def test_prepare_requires_explicit_tokenizer_selection(self) -> None:
        tmp = _get_test_dir()
        try:
            source_dir = tmp / "schema_dataset"
            output_dir = tmp / "prepared"
            _write_dataset(source_dir)

            with pytest.raises(ValueError, match="Explicit tokenizer selection is required"):
                prepare_schema_following_training_input(source_dir, output_dir)
        finally:
            _cleanup(tmp)

    def test_prepare_writes_loadable_training_bundle(self) -> None:
        tmp = _get_test_dir()
        try:
            source_dir = tmp / "schema_dataset"
            output_dir = tmp / "prepared"
            _write_dataset(source_dir)

            recommendation = prepare_schema_following_training_input(
                source_dir,
                output_dir,
                split="train",
                fake_tokenizer_config=FakeTokenizerConfig(),
                max_length=128,
                batch_size=16,
                learning_rate=5e-5,
                run_id="schema_train_run",
            )

            assert recommendation.contract_ok is True
            assert recommendation.prepared_sample_count == 1
            assert (output_dir / "samples.jsonl").exists()
            assert (output_dir / "tokenized.jsonl").exists()
            assert (output_dir / "contract_report.json").exists()
            assert (output_dir / "training_prep.json").exists()

            dataset = TrainDataset.from_jsonl(output_dir / "tokenized.jsonl")
            tokenizer_config = TokenizerConfig.load(output_dir / "tokenizer_config.yaml")
            train_config = TrainConfig.load(output_dir / "train_config.json")

            assert len(dataset) == 1
            assert dataset[0].metadata["sample_id"] == "sf__sample__001"
            assert tokenizer_config.max_length == 128
            assert train_config.run_id == "schema_train_run"
            assert train_config.batch_size == 16
            assert train_config.learning_rate == 5e-5
        finally:
            _cleanup(tmp)
