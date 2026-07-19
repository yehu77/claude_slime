"""Contract checks for the read-only, content-redacted runs inventory."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pycodeagent.dev.runs_inventory import (
    RUNS_INVENTORY_RECORD_SCHEMA,
    RUNS_INVENTORY_SCHEMA,
    RunsInventoryError,
    load_and_validate_inventory,
    scan_runs,
    verify_inventory_against_runs,
    write_inventory,
)


pytestmark = pytest.mark.mainline

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATH = ROOT / "references/runs-inventory.summary.json"
INVENTORY_PATH = ROOT / "references/runs-inventory.jsonl"
SCHEMA_PATH = ROOT / "references/runs-inventory.schema.json"
METADATA_KEYS = {
    "run_id",
    "task_id",
    "profile_id",
    "family",
    "status",
    "schema_version",
}


def _file_snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    snapshot: dict[str, tuple[int, int, str]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        payload = path.read_bytes()
        file_stat = path.stat()
        snapshot[path.relative_to(root).as_posix()] = (
            file_stat.st_size,
            file_stat.st_mtime_ns,
            hashlib.sha256(payload).hexdigest(),
        )
    return snapshot


def _write_synthetic_runs(repo_root: Path) -> None:
    good_run = repo_root / "runs/campaign-a/good-run"
    payload_dir = good_run / "payloads"
    payload_dir.mkdir(parents=True)
    trace = (
        '{"run_id":"run-1","task_id":"task-1",'
        '"tool_profile_id":"native-codex","tool_stack_kind":"native-codex",'
        '"status":"completed","schema_version":1,'
        '"authorization":"Bearer SUPER_SECRET_TOKEN"}\n'
    )
    (good_run / "runtime_trace.jsonl").write_text(trace, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "run_id": "run-1",
        "task_id": "task-1",
        "tool_profile_id": "native-codex",
        "tool_stack_kind": "native-codex",
        "status": "completed",
        "event_log_path": "runtime_trace.jsonl",
        "payload_dir": "payloads",
    }
    (good_run / "runtime_trace_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    duplicate_payload = b'{"authorization":{"redacted":true}}\n'
    (payload_dir / "000001.json").write_bytes(duplicate_payload)
    (payload_dir / "000002.json").write_bytes(duplicate_payload)

    broken = repo_root / "runs/campaign-a/broken-run"
    broken.mkdir(parents=True)
    (broken / "broken_manifest.json").write_text("{", encoding="utf-8")

    orphan = repo_root / "runs/campaign-b/orphan"
    orphan.mkdir(parents=True)
    (orphan / "notes.txt").write_text(
        "api_key=DO_NOT_SERIALIZE /home/alice/private\n",
        encoding="utf-8",
    )
    (orphan / "metadata.json").write_text(
        '{"task_id":"/home/alice/private","run_id":"alice@example.com"}\n',
        encoding="utf-8",
    )

    workspace = repo_root / "runs/campaign-b/workspace-run/workspace"
    workspace.mkdir(parents=True)
    (workspace / "code.py").write_text("answer = 42\n", encoding="utf-8")


def test_tracked_inventory_is_complete_and_content_redacted() -> None:
    inventory = load_and_validate_inventory(
        summary_path=SUMMARY_PATH,
        inventory_path=INVENTORY_PATH,
    )
    summary = inventory.summary

    assert summary["inventory_schema"] == RUNS_INVENTORY_SCHEMA
    assert summary["runs_root"] == "runs"
    assert summary["classification_status"] == "complete"
    assert summary["artifact_count"] == len(inventory.artifacts)
    assert summary["artifact_group_count"] == len(inventory.groups)
    assert summary["classified_artifact_count"] == len(inventory.artifacts)
    assert summary["classified_group_count"] == len(inventory.groups)
    assert sum(summary["artifact_class_counts"].values()) == len(
        inventory.artifacts
    )
    assert sum(summary["group_class_counts"].values()) == len(inventory.groups)
    assert summary["duplicate_group_count"] > 0
    assert summary["duplicate_file_count"] > summary["duplicate_group_count"]
    assert all(
        set(record["metadata"]) == METADATA_KEYS
        for record in (*inventory.groups, *inventory.artifacts)
    )
    for record in (*inventory.groups, *inventory.artifacts):
        for value in record["metadata"].values():
            if isinstance(value, str):
                assert "@" not in value
                assert not value.startswith(("/home/", "/Users/"))

    serialized = INVENTORY_PATH.read_text(encoding="utf-8")
    for forbidden_field in (
        '"content":',
        '"payload_text":',
        '"secret_value":',
        '"tool_arguments":',
        '"tool_results":',
    ):
        assert forbidden_field not in serialized


def test_inventory_schema_covers_all_record_types_and_redacted_metadata() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["$schema"].endswith("2020-12/schema")
    assert set(schema["$defs"]) >= {
        "inventory_record",
        "artifact_group_record",
        "artifact_record",
        "metadata",
        "redacted_scalar",
    }
    assert set(schema["$defs"]["metadata"]["required"]) == METADATA_KEYS
    assert schema["$defs"]["artifact_record"]["properties"]["schema"] == {
        "const": RUNS_INVENTORY_RECORD_SCHEMA
    }
    assert schema["$defs"]["summary"]["properties"]["inventory_schema"] == {
        "const": RUNS_INVENTORY_SCHEMA
    }


def test_scan_is_deterministic_read_only_and_reports_failures(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _write_synthetic_runs(repo_root)
    before = _file_snapshot(repo_root / "runs")

    first = scan_runs(repo_root)
    second = scan_runs(repo_root)

    assert first == second
    assert _file_snapshot(repo_root / "runs") == before
    assert first.summary["classification_status"] == "complete"
    assert first.summary["artifact_count"] == 8
    assert first.summary["classified_artifact_count"] == 8
    assert first.summary["duplicate_group_count"] == 1
    assert first.summary["duplicate_file_count"] == 2
    assert first.summary["manifest_status_counts"]["valid"] == 1
    assert first.summary["manifest_status_counts"]["invalid_json"] == 1
    assert all(
        record["classification_status"] == "classified"
        for record in (*first.groups, *first.artifacts)
    )
    assert any(
        record["manifest_status"] == "absent" for record in first.groups
    )

    trace_record = next(
        record
        for record in first.artifacts
        if record["path"].endswith("runtime_trace.jsonl")
    )
    assert trace_record["metadata"] == {
        "run_id": "run-1",
        "task_id": "task-1",
        "profile_id": "native-codex",
        "family": "native-codex",
        "status": "completed",
        "schema_version": 1,
    }
    assert "potential_authorization_material" in (
        trace_record["sensitive_risk_labels"]
    )
    orphan_record = next(
        record
        for record in first.artifacts
        if record["path"].endswith("notes.txt")
    )
    assert set(orphan_record["sensitive_risk_labels"]) >= {
        "absolute_user_path",
        "potential_authorization_material",
    }

    serialized = json.dumps(list(first.records()), sort_keys=True)
    assert "SUPER_SECRET_TOKEN" not in serialized
    assert "DO_NOT_SERIALIZE" not in serialized
    assert "/home/alice/private" not in serialized
    assert "alice@example.com" not in serialized


def test_written_inventory_validates_and_verify_detects_drift(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _write_synthetic_runs(repo_root)
    summary_path = repo_root / "references/runs-inventory.summary.json"
    inventory_path = repo_root / "references/runs-inventory.jsonl"
    scanned = scan_runs(repo_root)
    write_inventory(
        scanned,
        summary_path=summary_path,
        inventory_path=inventory_path,
    )

    loaded = load_and_validate_inventory(
        summary_path=summary_path,
        inventory_path=inventory_path,
    )
    verified = verify_inventory_against_runs(
        repo_root,
        summary_path=summary_path,
        inventory_path=inventory_path,
    )
    assert loaded == scanned
    assert verified == scanned

    added = repo_root / "runs/campaign-b/orphan/new.txt"
    added.write_text("drift\n", encoding="utf-8")
    with pytest.raises(RunsInventoryError, match="drift"):
        verify_inventory_against_runs(
            repo_root,
            summary_path=summary_path,
            inventory_path=inventory_path,
        )
