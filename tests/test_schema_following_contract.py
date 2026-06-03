"""Tests for schema-following contract verification."""

from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.rl.contract import (
    verify_schema_following_contract,
    verify_schema_following_dataset_dir,
)
from pycodeagent.rl.schema_following import (
    CanonicalToolIntent,
    ExposedToolCallTarget,
    SchemaFollowingMessage,
    SchemaFollowingSample,
)
from pycodeagent.rl.schema_following_dataset import write_schema_following_jsonl
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "schema_following_contract"


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
    sample = _make_sample()
    dataset_dir.mkdir(parents=True, exist_ok=True)
    write_schema_following_jsonl([sample], dataset_dir / "train.jsonl")
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
        json.dumps(
            {
                "version": 1,
                "split_counts": {"train": 1},
            },
            indent=2,
        ),
        encoding="utf-8",
    )


class TestVerifySchemaFollowingContract:
    def test_verify_dataset_dir_success(self) -> None:
        tmp = _get_test_dir()
        try:
            dataset_dir = tmp / "schema_dataset"
            _write_dataset(dataset_dir)

            result = verify_schema_following_dataset_dir(
                dataset_dir,
                split="train",
                fake_tokenizer_config=FakeTokenizerConfig(),
                pack_max_length=128,
            )

            assert result.ok is True
            assert result.sample_count == 1
            assert result.rollout_count == 0
            assert result.tokenized_count == 1
            assert result.task_ids == ["task_001"]
            assert result.profile_ids == ["schema_only"]
        finally:
            _cleanup(tmp)

    def test_verify_contract_can_materialize_tokenized_and_report(self) -> None:
        tmp = _get_test_dir()
        try:
            dataset_dir = tmp / "schema_dataset"
            output_dir = tmp / "verified"
            _write_dataset(dataset_dir)

            result = verify_schema_following_contract(
                dataset_dir,
                output_dir,
                split="train",
                fake_tokenizer_config=FakeTokenizerConfig(),
                pack_max_length=128,
                materialize_tokenized=True,
                write_report=True,
            )

            assert result.ok is True
            assert (output_dir / "tokenized.jsonl").exists()
            assert (output_dir / "contract_report.json").exists()
        finally:
            _cleanup(tmp)

    def test_verify_dataset_dir_flags_split_count_mismatch(self) -> None:
        tmp = _get_test_dir()
        try:
            dataset_dir = tmp / "schema_dataset"
            _write_dataset(dataset_dir)
            (dataset_dir / "split_metrics.json").write_text(
                json.dumps({"version": 1, "split_counts": {"train": 2}}, indent=2),
                encoding="utf-8",
            )

            result = verify_schema_following_dataset_dir(
                dataset_dir,
                split="train",
                fake_tokenizer_config=FakeTokenizerConfig(),
                pack_max_length=128,
            )

            assert result.ok is False
            assert any(
                issue.code == "schema_following_split_count_mismatch"
                for issue in result.issues
            )
        finally:
            _cleanup(tmp)
