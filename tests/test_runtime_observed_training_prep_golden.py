from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.rl.training_prep import (
    prepare_runtime_observed_schema_following_training_input,
)
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig
from pycodeagent.testing import (
    cleanup_test_path,
    make_runtime_observed_batch_source,
    make_unique_test_dir,
)


_FIXTURE_DIR = Path("tests/fixtures/runtime_observed_training_prep_bundle")
_TEST_NAMESPACE = "runtime_observed_training_prep_golden"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _normalize_string(
    value: str,
    *,
    tmp_root: Path,
    batch_root: Path,
    batch_run_dir: Path,
    prepared_root: Path,
    raw_dataset_dir: Path,
    prepared_dir: Path,
) -> str:
    normalized = value.replace("\r\n", "\n")
    replacements = [
        (str(prepared_dir.resolve()), "<prepared_dir>"),
        (str(raw_dataset_dir.resolve()), "<raw_dataset_dir>"),
        (str(prepared_root.resolve()), "<prepared_root>"),
        (str(batch_run_dir.resolve()), "<batch_run_dir>"),
        (str(batch_root.resolve()), "<batch_root>"),
        (str(tmp_root.resolve()), "<tmp_root>"),
    ]
    for source, target in replacements:
        normalized = normalized.replace(source, target)
        normalized = normalized.replace(source.replace("\\", "/"), target)
    return normalized


def _normalize_value(
    value,
    *,
    tmp_root: Path,
    batch_root: Path,
    batch_run_dir: Path,
    prepared_root: Path,
    raw_dataset_dir: Path,
    prepared_dir: Path,
):
    if isinstance(value, str):
        return _normalize_string(
            value,
            tmp_root=tmp_root,
            batch_root=batch_root,
            batch_run_dir=batch_run_dir,
            prepared_root=prepared_root,
            raw_dataset_dir=raw_dataset_dir,
            prepared_dir=prepared_dir,
        )
    if isinstance(value, list):
        return [
            _normalize_value(
                item,
                tmp_root=tmp_root,
                batch_root=batch_root,
                batch_run_dir=batch_run_dir,
                prepared_root=prepared_root,
                raw_dataset_dir=raw_dataset_dir,
                prepared_dir=prepared_dir,
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
                prepared_root=prepared_root,
                raw_dataset_dir=raw_dataset_dir,
                prepared_dir=prepared_dir,
            )
            for key, item in value.items()
        }
    return value


def test_runtime_observed_training_prep_bundle_matches_fixture() -> None:
    tmp = make_unique_test_dir(_TEST_NAMESPACE)
    try:
        source = make_runtime_observed_batch_source(
            tmp,
            task_id="observed_mutated_task",
            task_prompt="Inspect main.py and finish.",
            profile_mode="name_description_schema",
            profile_seed=0,
        )
        prepared_root = tmp / "prepared_bundle"
        prepare_runtime_observed_schema_following_training_input(
            source.batch_root,
            prepared_root,
            source_type="batch",
            max_length=2048,
            fake_tokenizer_config=FakeTokenizerConfig(),
            run_id="runtime_observed_golden_train",
        )

        raw_dataset_dir = prepared_root / "raw_dataset"
        prepared_dir = prepared_root / "prepared"

        for relative_path in [
            "training_prep.json",
            "raw_dataset/dataset_manifest.json",
            "raw_dataset/profile_manifest.json",
            "raw_dataset/source_manifest.json",
            "raw_dataset/split_metrics.json",
            "prepared/contract_report.json",
            "prepared/train_config.json",
        ]:
            assert _normalize_value(
                _load_json(prepared_root / relative_path),
                tmp_root=tmp,
                batch_root=source.batch_root,
                batch_run_dir=source.batch_run_dir,
                prepared_root=prepared_root,
                raw_dataset_dir=raw_dataset_dir,
                prepared_dir=prepared_dir,
            ) == _load_json(_FIXTURE_DIR / relative_path)

        for relative_path in [
            "raw_dataset/train.jsonl",
            "prepared/samples.jsonl",
            "prepared/tokenized.jsonl",
        ]:
            assert _normalize_value(
                _load_jsonl(prepared_root / relative_path),
                tmp_root=tmp,
                batch_root=source.batch_root,
                batch_run_dir=source.batch_run_dir,
                prepared_root=prepared_root,
                raw_dataset_dir=raw_dataset_dir,
                prepared_dir=prepared_dir,
            ) == _load_jsonl(_FIXTURE_DIR / relative_path)

        assert _normalize_string(
            (prepared_dir / "tokenizer_config.yaml").read_text(encoding="utf-8"),
            tmp_root=tmp,
            batch_root=source.batch_root,
            batch_run_dir=source.batch_run_dir,
            prepared_root=prepared_root,
            raw_dataset_dir=raw_dataset_dir,
            prepared_dir=prepared_dir,
        ) == (_FIXTURE_DIR / "prepared" / "tokenizer_config.yaml").read_text(encoding="utf-8")

        dataset = TrainDataset.from_jsonl(prepared_dir / "tokenized.jsonl")
        assert len(dataset) == 2
    finally:
        cleanup_test_path(tmp)
