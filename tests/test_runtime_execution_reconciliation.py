from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.eval.runtime_execution_reconciliation import (
    reconcile_runtime_execution,
)
from pycodeagent.rl.schema_following_from_runtime import (
    generate_schema_following_from_runtime_runs,
)
from pycodeagent.testing import (
    cleanup_test_path,
    make_runtime_observed_batch_source,
    make_unique_test_dir,
)


_TEST_NAMESPACE = "runtime_execution_reconciliation"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _prepare_raw_dataset(tmp: Path):
    source = make_runtime_observed_batch_source(tmp)
    raw_dataset_dir = tmp / "raw_dataset"
    generate_schema_following_from_runtime_runs(
        source.batch_root,
        raw_dataset_dir,
        source_type="batch",
    )
    return source, raw_dataset_dir


def test_runtime_execution_reconciliation_happy_path() -> None:
    tmp = _get_test_dir()
    try:
        source, raw_dataset_dir = _prepare_raw_dataset(tmp)
        report = reconcile_runtime_execution(
            source.batch_root,
            raw_dataset_dir,
            tmp / "runtime_execution_reconciliation.json",
            source_type="batch",
        )

        assert report.summary["sampled_tool_call_count"] == 2
        assert report.summary["trace_backed_sample_count"] == 2
        assert report.summary["reconciliation_ok_count"] == 2
        assert report.summary["reconciliation_error_count"] == 0
        assert report.summary["critical_reconciliation_error_count"] == 0
        assert report.summary["sample_count_by_execution_kind"] == {
            "file_read": 1,
            "finish_signal": 1,
        }
        assert report.summary["sample_count_by_policy_decision"] == {
            "allow": 2,
        }
        assert report.per_sample[0].reconciliation_status == "ok"
        assert report.per_run[0].trace_present is True
    finally:
        cleanup_test_path(tmp)


def test_runtime_execution_reconciliation_allows_trace_missing() -> None:
    tmp = _get_test_dir()
    try:
        source = make_runtime_observed_batch_source(tmp)
        (source.batch_run_dir / "runtime_trace.jsonl").unlink()
        raw_dataset_dir = tmp / "raw_dataset"
        generate_schema_following_from_runtime_runs(
            source.batch_root,
            raw_dataset_dir,
            source_type="batch",
        )

        report = reconcile_runtime_execution(
            source.batch_root,
            raw_dataset_dir,
            tmp / "runtime_execution_reconciliation.json",
            source_type="batch",
        )

        assert report.summary["trace_backed_sample_count"] == 0
        assert report.summary["reconciliation_error_count"] == 0
        assert report.per_run[0].trace_present is False
    finally:
        cleanup_test_path(tmp)


def test_runtime_execution_reconciliation_detects_mapping_mismatch() -> None:
    tmp = _get_test_dir()
    try:
        source, raw_dataset_dir = _prepare_raw_dataset(tmp)
        rows = _load_jsonl(raw_dataset_dir / "train.jsonl")
        read_row = next(row for row in rows if row["canonical_intent"]["tool"] == "read_file")
        read_row["target_tool_call"]["name"] = "wrong_read_name"
        payload = read_row["target_tool_call"]
        read_row["target_text"] = (
            "<|tool|>\n"
            + json.dumps(
                {
                    "arguments": payload["arguments"],
                    "id": payload["call_id"],
                    "name": payload["name"],
                },
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n<|end|>\n"
        )
        _write_jsonl(raw_dataset_dir / "train.jsonl", rows)

        report = reconcile_runtime_execution(
            source.batch_root,
            raw_dataset_dir,
            tmp / "runtime_execution_reconciliation.json",
            source_type="batch",
        )

        read_finding = next(
            finding for finding in report.per_sample if finding.canonical_tool_name == "read_file"
        )
        assert read_finding.reconciliation_status == "error"
        assert "exposed_name_mismatch" in read_finding.mismatch_reasons
        assert "exposed_name_mismatch" in read_finding.critical_mismatch_reasons
        assert report.summary["critical_reconciliation_error_count"] == 1
    finally:
        cleanup_test_path(tmp)


def test_runtime_execution_reconciliation_detects_missing_execution_event_and_provider_mismatch() -> None:
    tmp = _get_test_dir()
    try:
        source, raw_dataset_dir = _prepare_raw_dataset(tmp)
        trace_path = source.batch_run_dir / "runtime_trace.jsonl"
        trace_rows = _load_jsonl(trace_path)
        trace_rows = [
            row
            for row in trace_rows
            if not (
                row.get("event_kind") == "tool_execution_completed"
                and row.get("tool_call_id") == "c1"
            )
        ]
        _write_jsonl(trace_path, trace_rows)

        rows = _load_jsonl(raw_dataset_dir / "train.jsonl")
        read_row = next(row for row in rows if row["canonical_intent"]["tool"] == "read_file")
        read_row["metadata"]["source_model"] = "wrong-model"
        _write_jsonl(raw_dataset_dir / "train.jsonl", rows)

        report = reconcile_runtime_execution(
            source.batch_root,
            raw_dataset_dir,
            tmp / "runtime_execution_reconciliation.json",
            source_type="batch",
        )

        read_finding = next(
            finding for finding in report.per_sample if finding.canonical_tool_name == "read_file"
        )
        assert "missing_execution_event" in read_finding.mismatch_reasons
        assert "provider_metadata_mismatch" in read_finding.mismatch_reasons
        assert "missing_execution_event" in read_finding.critical_mismatch_reasons
        assert report.summary["reconciliation_error_count"] == 1
        assert report.summary["critical_reconciliation_error_count"] == 1
    finally:
        cleanup_test_path(tmp)
