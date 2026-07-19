"""Contract checks for the sanitized Claude API mini trace."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pycodeagent.auxiliary.claude_api.trace_extract import extract_claude_request_sample
from pycodeagent.auxiliary.claude_api.trace_loader import read_claude_api_session


_TRACE = Path("tests/fixtures/claude_api_tool_use_session.jsonl")
_REFERENCE = Path("references/claude-api-trace-local-reference.json")


def test_mini_trace_is_deterministic_sanitized_and_behavior_complete() -> None:
    trace_bytes = _TRACE.read_bytes()
    trace_text = trace_bytes.decode("utf-8")
    events = [json.loads(line) for line in trace_text.splitlines() if line.strip()]
    reference = json.loads(_REFERENCE.read_text(encoding="utf-8"))
    replacement = reference["replacement"]

    assert len(events) == replacement["line_count"] == 8
    assert len(trace_bytes) == replacement["bytes"] == 5318
    assert hashlib.sha256(trace_bytes).hexdigest() == replacement["sha256"]
    assert reference["original"]["bytes"] / len(trace_bytes) > 700
    assert reference["local_backup"]["storage_boundary"] == "local_git_worktree_external"
    assert reference["local_backup"]["tracked_or_published"] is False
    assert all(reference["local_backup"]["checks"].values())

    session = read_claude_api_session(_TRACE)
    assert session.session_id == "session_mini_sanitized"
    assert len(session.events) == 8
    assert len(session.message_requests) == replacement["message_request_count"] == 2
    assert not session.orphan_events

    first, second = session.message_requests
    assert [tool["name"] for tool in first.request_body["tools"]] == ["Read", "Bash"]
    first_sample = extract_claude_request_sample(first, include_incomplete=True)
    second_sample = extract_claude_request_sample(second, include_incomplete=True)
    assert first_sample is not None
    assert second_sample is not None
    assert first_sample.stop_reason == "tool_use"
    assert second_sample.stop_reason == "end_turn"

    tool_use_ids = {
        block.metadata["start_payload"]["content_block"]["id"]
        for block in first_sample.response_blocks
        if block.block_type == "tool_use"
    }
    tool_result_ids = {
        block["tool_use_id"]
        for message in second.request_body["messages"]
        if message.get("role") == "user" and isinstance(message.get("content"), list)
        for block in message["content"]
        if block.get("type") == "tool_result"
    }
    assert tool_use_ids == tool_result_ids == {"toolu_mini_read"}

    lowered = trace_text.lower()
    for forbidden in (
        "authorization",
        "x-api-key",
        "cookie",
        "device_id",
        "user_id",
        "account_id",
        "sk-ant-",
        "/home/",
        "\\users\\",
    ):
        assert forbidden not in lowered
