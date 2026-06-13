from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.rl.schema_following_from_runtime import (
    generate_schema_following_from_runtime_runs,
)
from pycodeagent.testing import (
    cleanup_test_path,
    make_runtime_observed_batch_source,
    make_unique_test_dir,
)


_FIXTURE_DIR = Path("tests/fixtures/runtime_observed_dataset_bundle")
_MUTATED_FIXTURE_DIR = Path("tests/fixtures/runtime_observed_dataset_bundle_mutated")
_REORDER_FIXTURE_DIR = Path("tests/fixtures/runtime_observed_dataset_bundle_tool_reorder")
_TEST_NAMESPACE = "schema_following_from_runtime_golden"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _normalize_string(value: str, *, tmp_root: Path, batch_root: Path, batch_run_dir: Path) -> str:
    normalized = value.replace("\r\n", "\n")
    replacements = [
        (str(batch_run_dir.resolve()), "<batch_run_dir>"),
        (str(batch_root.resolve()), "<batch_root>"),
        (str(tmp_root.resolve()), "<tmp_root>"),
    ]
    for source, target in replacements:
        normalized = normalized.replace(source, target)
        normalized = normalized.replace(source.replace("\\", "/"), target)
    return normalized


def _normalize_value(value, *, tmp_root: Path, batch_root: Path, batch_run_dir: Path):
    if isinstance(value, str):
        return _normalize_string(
            value,
            tmp_root=tmp_root,
            batch_root=batch_root,
            batch_run_dir=batch_run_dir,
        )
    if isinstance(value, list):
        return [
            _normalize_value(
                item,
                tmp_root=tmp_root,
                batch_root=batch_root,
                batch_run_dir=batch_run_dir,
            )
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: _normalize_value(
                item,
                tmp_root=tmp_root,
                batch_root=batch_root,
                batch_run_dir=batch_run_dir,
            )
            for key, item in value.items()
        }
    return value


def _assert_bundle_matches_fixture(
    *,
    fixture_dir: Path,
    actual_dir: Path,
    tmp_root: Path,
    batch_root: Path,
    batch_run_dir: Path,
) -> None:
    for relative_path in [
        "dataset_manifest.json",
        "profile_manifest.json",
        "source_manifest.json",
        "split_metrics.json",
    ]:
        assert _normalize_value(
            _load_json(actual_dir / relative_path),
            tmp_root=tmp_root,
            batch_root=batch_root,
            batch_run_dir=batch_run_dir,
        ) == _load_json(fixture_dir / relative_path)

    assert _normalize_value(
        _load_jsonl(actual_dir / "train.jsonl"),
        tmp_root=tmp_root,
        batch_root=batch_root,
        batch_run_dir=batch_run_dir,
    ) == _load_jsonl(fixture_dir / "train.jsonl")


def test_runtime_observed_base_bundle_matches_fixture() -> None:
    tmp = make_unique_test_dir(_TEST_NAMESPACE)
    try:
        source = make_runtime_observed_batch_source(
            tmp,
            task_id="observed_base_task",
            task_prompt="Inspect main.py and finish.",
        )
        output_dir = tmp / "observed_output"
        generate_schema_following_from_runtime_runs(
            source.batch_root,
            output_dir,
            source_type="batch",
            split_seed=42,
        )
        _assert_bundle_matches_fixture(
            fixture_dir=_FIXTURE_DIR,
            actual_dir=output_dir,
            tmp_root=tmp,
            batch_root=source.batch_root,
            batch_run_dir=source.batch_run_dir,
        )
    finally:
        cleanup_test_path(tmp)


def test_runtime_observed_mutated_bundle_matches_fixture() -> None:
    tmp = make_unique_test_dir(_TEST_NAMESPACE)
    try:
        source = make_runtime_observed_batch_source(
            tmp,
            task_id="observed_mutated_task",
            task_prompt="Inspect main.py and finish.",
            profile_mode="name_description_schema",
            profile_seed=0,
        )
        output_dir = tmp / "observed_output_mutated"
        generate_schema_following_from_runtime_runs(
            source.batch_root,
            output_dir,
            source_type="batch",
            split_seed=42,
        )
        _assert_bundle_matches_fixture(
            fixture_dir=_MUTATED_FIXTURE_DIR,
            actual_dir=output_dir,
            tmp_root=tmp,
            batch_root=source.batch_root,
            batch_run_dir=source.batch_run_dir,
        )
    finally:
        cleanup_test_path(tmp)


def test_runtime_observed_tool_reorder_bundle_matches_fixture() -> None:
    tmp = make_unique_test_dir(_TEST_NAMESPACE)
    try:
        source = make_runtime_observed_batch_source(
            tmp,
            task_id="observed_reorder_task",
            task_prompt="Inspect main.py and finish.",
            profile_mode="tool_reorder",
            profile_seed=0,
        )
        output_dir = tmp / "observed_output_reorder"
        generate_schema_following_from_runtime_runs(
            source.batch_root,
            output_dir,
            source_type="batch",
            split_seed=42,
        )
        _assert_bundle_matches_fixture(
            fixture_dir=_REORDER_FIXTURE_DIR,
            actual_dir=output_dir,
            tmp_root=tmp,
            batch_root=source.batch_root,
            batch_run_dir=source.batch_run_dir,
        )
    finally:
        cleanup_test_path(tmp)
