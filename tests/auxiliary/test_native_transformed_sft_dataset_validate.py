"""Tests for transformed native SFT dataset validation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pycodeagent.auxiliary.claude_api.sft_dataset_io import (
    read_claude_api_sft_jsonl,
    write_claude_api_sft_jsonl,
)
from pycodeagent.auxiliary.native_transformed.sft_dataset import (
    build_native_transformed_sft_dataset,
)
from pycodeagent.auxiliary.native_transformed.sft_dataset_validate import (
    validate_native_transformed_sft_dataset,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "native_transformed_sft_dataset_validate"
_REAL_TOOL_USE_SESSION_PATH = Path("tests/fixtures/claude_api_tool_use_session.jsonl")


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _build_real_dataset(output_root: Path) -> Path:
    source = output_root / "source"
    dataset_dir = output_root / "dataset"
    source.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_REAL_TOOL_USE_SESSION_PATH, source / _REAL_TOOL_USE_SESSION_PATH.name)
    build_native_transformed_sft_dataset(source, dataset_dir)
    return dataset_dir


class TestNativeTransformedSFTDatasetValidate:
    def test_valid_dataset_passes_and_writes_report(self) -> None:
        if not _REAL_TOOL_USE_SESSION_PATH.exists():
            pytest.skip(f"Missing real Claude tool-use fixture: {_REAL_TOOL_USE_SESSION_PATH}")
        tmp = _get_test_dir()
        try:
            dataset_dir = _build_real_dataset(tmp)
            report = validate_native_transformed_sft_dataset(dataset_dir)

            assert report.ok is True
            assert report.sample_count >= 4
            assert report.valid_sample_count == report.sample_count
            assert report.invalid_sample_count == 0
            assert (dataset_dir / "validation_report.json").exists()
        finally:
            _cleanup(tmp)

    def test_tool_call_name_not_in_visible_specs_is_reported(self) -> None:
        if not _REAL_TOOL_USE_SESSION_PATH.exists():
            pytest.skip(f"Missing real Claude tool-use fixture: {_REAL_TOOL_USE_SESSION_PATH}")
        tmp = _get_test_dir()
        try:
            dataset_dir = _build_real_dataset(tmp)
            samples = read_claude_api_sft_jsonl(dataset_dir / "train.jsonl")
            mutated = samples[0].model_copy(deep=True)
            for block in mutated.target_blocks:
                if block.block_type == "tool_use" and block.tool_call is not None:
                    block.tool_call.name = "DefinitelyNotVisible"
                    break
            else:
                raise AssertionError("Expected at least one tool_use block")
            samples[0] = mutated
            write_claude_api_sft_jsonl(samples, dataset_dir / "train.jsonl")

            report = validate_native_transformed_sft_dataset(dataset_dir)

            assert report.ok is False
            assert report.invalid_sample_count == 1
            assert report.invalid_reasons["tool_call_name_not_in_visible_specs"] == 1
        finally:
            _cleanup(tmp)

    def test_missing_source_metadata_is_reported(self) -> None:
        if not _REAL_TOOL_USE_SESSION_PATH.exists():
            pytest.skip(f"Missing real Claude tool-use fixture: {_REAL_TOOL_USE_SESSION_PATH}")
        tmp = _get_test_dir()
        try:
            dataset_dir = _build_real_dataset(tmp)
            samples = read_claude_api_sft_jsonl(dataset_dir / "train.jsonl")
            mutated = samples[0].model_copy(deep=True)
            mutated.metadata.pop("source_catalog_id", None)
            samples[0] = mutated
            write_claude_api_sft_jsonl(samples, dataset_dir / "train.jsonl")

            report = validate_native_transformed_sft_dataset(dataset_dir)

            assert report.ok is False
            assert report.invalid_sample_count == 1
            assert report.invalid_reasons["missing_source_metadata"] == 1
        finally:
            _cleanup(tmp)

    def test_forbidden_thinking_or_tool_result_target_is_reported(self) -> None:
        if not _REAL_TOOL_USE_SESSION_PATH.exists():
            pytest.skip(f"Missing real Claude tool-use fixture: {_REAL_TOOL_USE_SESSION_PATH}")
        tmp = _get_test_dir()
        try:
            dataset_dir = _build_real_dataset(tmp)
            train_path = dataset_dir / "train.jsonl"
            records = [json.loads(line) for line in train_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            records[0]["target_blocks"] = [
                {
                    "block_type": "thinking",
                    "text": "chain of thought",
                    "metadata": {},
                }
            ]
            train_path.write_text(
                "\n".join(json.dumps(record, sort_keys=True, ensure_ascii=False) for record in records) + "\n",
                encoding="utf-8",
            )

            report = validate_native_transformed_sft_dataset(dataset_dir)

            assert report.ok is False
            assert report.invalid_sample_count == 1
            assert report.invalid_reasons["forbidden_target_block_type"] == 1
            assert report.invalid_reasons["parse_error"] == 1
        finally:
            _cleanup(tmp)
