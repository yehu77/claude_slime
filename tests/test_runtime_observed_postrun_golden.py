from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.eval.runtime_observed_postrun import (
    prepare_study_runtime_observed_bundle,
)
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig
from pycodeagent.testing import (
    cleanup_test_path,
    make_runtime_observed_study_source,
    make_unique_test_dir,
)


_FIXTURE_DIR = Path("tests/fixtures/runtime_observed_study_bundle")
_TEST_NAMESPACE = "runtime_observed_postrun_g"


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
    study_root: Path,
    bundle_root: Path,
    raw_dataset_dir: Path,
    prepared_dir: Path,
) -> str:
    normalized = value.replace("\r\n", "\n")
    replacements = [
        (str(prepared_dir.resolve()), "<prepared_dir>"),
        (str(raw_dataset_dir.resolve()), "<raw_dataset_dir>"),
        (str(bundle_root.resolve()), "<bundle_root>"),
        (str(study_root.resolve()), "<study_root>"),
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
    study_root: Path,
    bundle_root: Path,
    raw_dataset_dir: Path,
    prepared_dir: Path,
):
    if isinstance(value, str):
        return _normalize_string(
            value,
            tmp_root=tmp_root,
            study_root=study_root,
            bundle_root=bundle_root,
            raw_dataset_dir=raw_dataset_dir,
            prepared_dir=prepared_dir,
        )
    if isinstance(value, list):
        return [
            _normalize_value(
                item,
                tmp_root=tmp_root,
                study_root=study_root,
                bundle_root=bundle_root,
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
                study_root=study_root,
                bundle_root=bundle_root,
                raw_dataset_dir=raw_dataset_dir,
                prepared_dir=prepared_dir,
            )
            for key, item in value.items()
        }
    return value


def test_runtime_observed_study_bundle_matches_fixture() -> None:
    tmp = make_unique_test_dir(_TEST_NAMESPACE)
    try:
        source = make_runtime_observed_study_source(tmp)
        bundle_root = tmp / "bundle"
        prepare_study_runtime_observed_bundle(
            source.study_root,
            bundle_root,
            source_type="study",
            max_length=2048,
            fake_tokenizer_config=FakeTokenizerConfig(),
            run_id="runtime_observed_study_golden_train",
        )

        raw_dataset_dir = bundle_root / "raw_dataset"
        prepared_dir = bundle_root / "prepared"

        for relative_path in [
            "runtime_observed_bundle.json",
            "training_prep.json",
            "study_observed_manifest.json",
            "study_observed_summary.json",
            "runtime_behavior_audit.json",
            "runtime_execution_reconciliation.json",
            "raw_dataset/dataset_manifest.json",
            "raw_dataset/profile_manifest.json",
            "raw_dataset/source_manifest.json",
            "raw_dataset/split_metrics.json",
            "prepared/contract_report.json",
            "prepared/train_config.json",
        ]:
            assert _normalize_value(
                _load_json(bundle_root / relative_path),
                tmp_root=tmp,
                study_root=source.study_root,
                bundle_root=bundle_root,
                raw_dataset_dir=raw_dataset_dir,
                prepared_dir=prepared_dir,
            ) == _load_json(_FIXTURE_DIR / relative_path)

        for relative_path in [
            "raw_dataset/train.jsonl",
            "prepared/samples.jsonl",
            "prepared/tokenized.jsonl",
        ]:
            assert _normalize_value(
                _load_jsonl(bundle_root / relative_path),
                tmp_root=tmp,
                study_root=source.study_root,
                bundle_root=bundle_root,
                raw_dataset_dir=raw_dataset_dir,
                prepared_dir=prepared_dir,
            ) == _load_jsonl(_FIXTURE_DIR / relative_path)

        assert _normalize_string(
            (prepared_dir / "tokenizer_config.yaml").read_text(encoding="utf-8"),
            tmp_root=tmp,
            study_root=source.study_root,
            bundle_root=bundle_root,
            raw_dataset_dir=raw_dataset_dir,
            prepared_dir=prepared_dir,
        ) == (_FIXTURE_DIR / "prepared" / "tokenizer_config.yaml").read_text(encoding="utf-8")
    finally:
        cleanup_test_path(tmp)
