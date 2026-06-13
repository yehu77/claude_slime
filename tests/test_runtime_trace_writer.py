from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.runtime_trace import RuntimeTraceWriter
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def test_runtime_trace_writer_creates_manifest_and_event_log() -> None:
    tmp_path = make_unique_test_dir("runtime_trace_writer")
    try:
        writer = RuntimeTraceWriter.create(
            tmp_path,
            run_id="run_123",
            task_id="task_123",
            tool_profile_id="base",
            workspace_root=str(tmp_path / "workspace"),
        )

        manifest = _load_json(tmp_path / "runtime_trace_manifest.json")
        assert manifest["trace_id"] == "run_123__runtime_trace"
        assert manifest["run_id"] == "run_123"
        assert manifest["task_id"] == "task_123"
        assert manifest["tool_profile_id"] == "base"
        assert manifest["payload_dir"] == "payloads"
        assert manifest["event_log_path"] == "runtime_trace.jsonl"
        assert (tmp_path / "runtime_trace.jsonl").exists()
        assert (tmp_path / "payloads").is_dir()

        writer.append("run_started", data={"task_prompt": "hello"})
        writer.append("run_completed", data={"total_turns": 0, "final_status": "completed", "stop_reason": "", "stop_detail": ""})

        events = _load_jsonl(tmp_path / "runtime_trace.jsonl")
        assert [event["event_id"] for event in events] == [
            "runtime_event_000001",
            "runtime_event_000002",
        ]
        assert [event["seq"] for event in events] == [1, 2]
    finally:
        cleanup_test_path(tmp_path)


def test_runtime_trace_writer_payload_refs_and_finalize() -> None:
    tmp_path = make_unique_test_dir("runtime_trace_writer")
    try:
        writer = RuntimeTraceWriter.create(
            tmp_path,
            run_id="run_123",
            task_id="task_123",
            tool_profile_id="base",
            workspace_root=str(tmp_path / "workspace"),
        )

        payload_ref = writer.write_json_payload("model_request", {"messages": [], "tools": []})
        writer.append(
            "model_request_built",
            turn_index=1,
            data={"turn_index": 1, "message_count": 0},
            payload_refs=[payload_ref],
        )
        writer.finalize()

        payload_path = tmp_path / payload_ref.path
        assert payload_path.exists()
        payload = _load_json(payload_path)
        assert payload == {"messages": [], "tools": []}

        manifest = _load_json(tmp_path / "runtime_trace_manifest.json")
        assert isinstance(manifest["ended_at_unix_ms"], int)

        events = _load_jsonl(tmp_path / "runtime_trace.jsonl")
        assert events[0]["payload_refs"][0]["payload_id"] == payload_ref.payload_id
        assert events[0]["payload_refs"][0]["path"] == payload_ref.path
    finally:
        cleanup_test_path(tmp_path)
