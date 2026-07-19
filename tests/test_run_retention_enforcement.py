from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pycodeagent.adapters import MockTraceNormalizer
from pycodeagent.adapters.mock_adapter import MockAdapter
from pycodeagent.env.task import CodingTask
from pycodeagent.harness import AgentHarness
from pycodeagent.runtime_trace import (
    RunRetentionError,
    RuntimeTraceWriter,
    build_cleanup_plan,
    verify_run_retention,
)
from pycodeagent.runtime_trace.retention import (
    RETENTION_EVENT_LOG_NAME,
    RETENTION_INDEX_NAME,
    RETENTION_MANIFEST_NAME,
    RunRetentionTracker,
    main,
)


pytestmark = pytest.mark.mainline


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_runtime_writer_emits_and_seals_fail_closed_retention_metadata(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    writer = RuntimeTraceWriter.create(
        run_dir,
        run_id="retained-run",
        task_id="task-1",
        tool_profile_id="base",
        workspace_root=str(tmp_path / "workspace"),
    )
    writer.append("run_started", data={})
    writer.finalize()

    runtime_manifest = _json(run_dir / "runtime_trace_manifest.json")
    retention_manifest = _json(run_dir / RETENTION_MANIFEST_NAME)
    index = _jsonl(run_dir / RETENTION_INDEX_NAME)

    assert runtime_manifest["schema_version"] == 2
    assert runtime_manifest["retention"]["purpose_class"] == "unclassified_hold"
    assert runtime_manifest["retention"]["sensitivity"] == "restricted"
    assert retention_manifest["lifecycle"]["state"] == "finalized"
    assert retention_manifest["retention"]["expires_at"] is None
    assert retention_manifest["retention"]["quarantine_until"] is None
    assert retention_manifest["deletion_authorization_id"] is None
    assert index[1]["purpose_class"] == "unclassified_hold"
    assert index[1]["disposition"] == "manual_review_hold"
    assert index[0]["inventory_state_fingerprint"] == (
        retention_manifest["checksums"]["source"]
    )
    assert verify_run_retention(run_dir) == {
        "run_id": "retained-run",
        "purpose_class": "unclassified_hold",
        "sensitivity": "restricted",
        "lifecycle_state": "finalized",
        "indexed": True,
        "checksum_status": "verified",
        "deletion_authorized": False,
    }


def test_multi_agent_harness_seals_workspace_and_raw_trace_retention(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# retained\n", encoding="utf-8")
    task = CodingTask(
        task_id="harness-task",
        repo_path=repo,
        prompt="Inspect README.md.",
    )
    result = AgentHarness(
        adapter=MockAdapter(),
        normalizer=MockTraceNormalizer(),
    ).run_task(
        task,
        output_dir=tmp_path / "runs",
        run_id="harness-run",
        retention_class="unique_research_evidence",
    )

    manifest = _json(result.bundle_paths.run_dir / RETENTION_MANIFEST_NAME)
    assert manifest["purpose_class"] == "unique_research_evidence"
    assert manifest["lifecycle"]["state"] == "finalized"
    assert manifest["retention"]["expires_at"] is None
    assert manifest["risk_labels"] == [
        "raw_provider_content",
        "raw_trace_content",
        "workspace_snapshot_content",
    ]
    assert verify_run_retention(result.bundle_paths.run_dir)[
        "checksum_status"
    ] == "verified"


def test_unknown_retention_class_fails_before_run_artifacts_exist(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "unknown"

    with pytest.raises(RunRetentionError, match="Unknown run retention class"):
        RuntimeTraceWriter.create(
            run_dir,
            run_id="unknown-run",
            task_id="task-1",
            tool_profile_id="base",
            workspace_root=str(tmp_path / "workspace"),
            retention_class="future-implicit-delete",
        )

    assert not run_dir.exists()


def test_crash_resume_preserves_window_index_and_append_ordinals(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "resumed"
    clock_value = datetime(2026, 7, 18, tzinfo=timezone.utc)
    first = RunRetentionTracker.create_or_resume(
        run_dir,
        run_id="resumed-run",
        task_id="task-1",
        purpose_class="debug",
        clock=lambda: clock_value,
    )
    first_window = dict(first.manifest["retention"])
    (run_dir / "crash-artifact.txt").write_text("preserve", encoding="utf-8")

    resumed = RunRetentionTracker.create_or_resume(
        run_dir,
        run_id="resumed-run",
        task_id="task-1",
        purpose_class="debug",
        clock=lambda: datetime(2027, 1, 1, tzinfo=timezone.utc),
    )

    assert resumed.manifest["retention"] == first_window
    assert resumed.manifest["lifecycle"]["resume_count"] == 1
    assert (run_dir / RETENTION_INDEX_NAME).is_file()
    assert [event["event_kind"] for event in _jsonl(
        run_dir / RETENTION_EVENT_LOG_NAME
    )] == ["created", "resumed"]
    assert verify_run_retention(run_dir)["checksum_status"] == "verified"

    trace_dir = tmp_path / "trace-resume"
    writer = RuntimeTraceWriter.create(
        trace_dir,
        run_id="trace-resume",
        task_id="task-1",
        tool_profile_id="base",
        workspace_root=str(tmp_path / "workspace"),
    )
    writer.append("run_started", data={})
    writer.write_json_payload("request", {"turn": 1})
    resumed_writer = RuntimeTraceWriter.create(
        trace_dir,
        run_id="trace-resume",
        task_id="task-1",
        tool_profile_id="base",
        workspace_root=str(tmp_path / "workspace"),
    )
    event = resumed_writer.append("run_completed", data={})
    payload = resumed_writer.write_json_payload("request", {"turn": 2})
    resumed_writer.finalize()

    assert event.seq == 2
    assert payload.path == "payloads/000002.json"


def test_resume_rejects_retention_reclassification(tmp_path: Path) -> None:
    run_dir = tmp_path / "mismatch"
    RunRetentionTracker.create_or_resume(
        run_dir,
        run_id="mismatch-run",
        task_id="task-1",
        purpose_class="debug",
    )

    with pytest.raises(RunRetentionError, match="purpose_class"):
        RunRetentionTracker.create_or_resume(
            run_dir,
            run_id="mismatch-run",
            task_id="task-1",
            purpose_class="duplicate",
        )


def test_resume_reconciles_interrupted_finalization(tmp_path: Path) -> None:
    run_dir = tmp_path / "interrupted-finalize"
    writer = RuntimeTraceWriter.create(
        run_dir,
        run_id="interrupted-run",
        task_id="task-1",
        tool_profile_id="base",
        workspace_root=str(tmp_path / "workspace"),
    )
    writer.append("run_started", data={})
    runtime_manifest_path = run_dir / "runtime_trace_manifest.json"
    runtime_manifest = _json(runtime_manifest_path)
    runtime_manifest["ended_at_unix_ms"] = 123
    runtime_manifest_path.write_text(
        json.dumps(runtime_manifest),
        encoding="utf-8",
    )

    with pytest.raises(RunRetentionError, match="reconciled"):
        RuntimeTraceWriter.create(
            run_dir,
            run_id="interrupted-run",
            task_id="task-1",
            tool_profile_id="base",
            workspace_root=str(tmp_path / "workspace"),
        )

    assert _json(run_dir / RETENTION_MANIFEST_NAME)["lifecycle"]["state"] == (
        "finalized"
    )
    assert verify_run_retention(run_dir)["checksum_status"] == "verified"


def test_cleanup_is_dry_run_and_execute_is_rejected(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "cleanup"
    writer = RuntimeTraceWriter.create(
        run_dir,
        run_id="cleanup-run",
        task_id="task-1",
        tool_profile_id="base",
        workspace_root=str(tmp_path / "workspace"),
        retention_class="duplicate",
    )
    writer.append("run_started", data={})
    writer.finalize()
    protected_trace = (run_dir / "runtime_trace.jsonl").read_bytes()

    plan = build_cleanup_plan(
        [run_dir],
        as_of=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )

    assert plan["mode"] == "dry_run"
    assert plan["delete_count"] == 0
    assert plan["items"][0]["action"] == "retain_and_report"
    assert "archive_checksum_missing" in plan["items"][0]["reasons"]
    assert "exact_batch_authorization_missing" in plan["items"][0]["reasons"]
    assert main(["cleanup", "--execute", str(run_dir)]) == 1
    assert (run_dir / "runtime_trace.jsonl").read_bytes() == protected_trace


def test_finalized_checksum_drift_fails_verification(tmp_path: Path) -> None:
    run_dir = tmp_path / "drift"
    writer = RuntimeTraceWriter.create(
        run_dir,
        run_id="drift-run",
        task_id="task-1",
        tool_profile_id="base",
        workspace_root=str(tmp_path / "workspace"),
    )
    writer.append("run_started", data={})
    writer.finalize()
    with open(run_dir / "runtime_trace.jsonl", "a", encoding="utf-8") as handle:
        handle.write("{}\n")

    with pytest.raises(RunRetentionError, match="checksum drift"):
        verify_run_retention(run_dir)
