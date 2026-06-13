"""Contract tests for multi-agent scaffold trace artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.traces import (
    RawAgentTrace,
    RawEvent,
    RawTraceSummary,
    read_raw_trace,
    write_raw_trace,
)
from pycodeagent.trajectory.schema import RunStatus, VerifyResult


_TEST_NAMESPACE = "multi_agent_scaffold_contracts"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


class TestRawTraceContracts:
    def test_command_exec_requires_command_role(self) -> None:
        with pytest.raises(ValueError, match="command_role"):
            RawEvent(
                event_id="event_001",
                seq=1,
                event_kind="command_exec",
                source="agent",
                visibility="harness",
                evidence_level="synthetic",
                parsed_payload={"command": "pytest -q"},
            )

    def test_raw_trace_jsonl_and_summary_roundtrip(self) -> None:
        tmp = _get_test_dir()
        try:
            trace = RawAgentTrace(
                summary=RawTraceSummary(
                    trace_id="trace_001",
                    agent_name="mock_agent",
                    agent_version="v1",
                    task_id="task_001",
                    workspace_dir=str(tmp / "workspace"),
                    tool_catalog_id="catalog_001",
                    status=RunStatus.COMPLETED,
                    final_diff="",
                    verifier_result=VerifyResult(passed=True, score=1.0),
                    metadata={"source_type": "synthetic"},
                ),
                events=[
                    RawEvent(
                        event_id="event_001",
                        seq=1,
                        event_kind="message",
                        source="harness",
                        visibility="model",
                        evidence_level="synthetic",
                        parsed_payload={"role": "user", "content": "Inspect README.md."},
                    ),
                    RawEvent(
                        event_id="event_002",
                        seq=2,
                        event_kind="command_exec",
                        source="agent",
                        visibility="harness",
                        evidence_level="synthetic",
                        parsed_payload={
                            "command": "pytest -q",
                            "argv": ["pytest -q"],
                            "cwd": ".",
                            "command_role": "agent_command",
                        },
                    ),
                ],
            )
            events_path = tmp / "raw_trace.jsonl"
            summary_path = tmp / "raw_trace_summary.json"
            write_raw_trace(trace, events_path, summary_path)

            loaded = read_raw_trace(events_path, summary_path)

            assert loaded.summary.schema_version == 1
            assert loaded.trace_id == "trace_001"
            assert len(loaded.events) == 2
            assert loaded.events[1].parsed_payload["command_role"] == "agent_command"
        finally:
            _cleanup(tmp)
