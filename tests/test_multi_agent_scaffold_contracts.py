"""Contract tests for multi-agent scaffold trace artifacts."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.testing.multi_agent_mock_golden import (
    DEFAULT_GOLDEN_DIR,
    MultiAgentMockGoldenError,
    check_multi_agent_mock_golden,
    verify_multi_agent_mock_golden,
)
from pycodeagent.traces import (
    RawAgentTrace,
    RawEvent,
    RawTraceSummary,
    read_canonical_trace,
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


class TestPhaseOneMultiAgentGolden:
    @pytest.mark.mainline
    def test_checked_in_golden_is_native_and_regenerable(self) -> None:
        manifest = check_multi_agent_mock_golden(DEFAULT_GOLDEN_DIR)
        canonical_trace = read_canonical_trace(DEFAULT_GOLDEN_DIR / "canonical_trace.json")

        assert manifest["contract"]["family"] == "claude"
        assert manifest["contract"]["native_profile_kind"] == "native_claude"
        assert manifest["contract"]["canonical_capabilities"] == ["READ", "BASH"]
        assert [action.capability for action in canonical_trace.actions] == ["READ", "BASH"]
        assert canonical_trace.actions[1].raw_event_refs == ["event_007", "event_008"]

    def test_manifest_checksum_rejects_manual_artifact_drift(self) -> None:
        tmp = _get_test_dir()
        try:
            copied_golden = tmp / "golden"
            shutil.copytree(DEFAULT_GOLDEN_DIR, copied_golden)
            raw_trace_path = copied_golden / "raw_trace.jsonl"
            raw_trace_path.write_text(
                raw_trace_path.read_text(encoding="utf-8").replace(
                    "event_001",
                    "event_901",
                    1,
                ),
                encoding="utf-8",
            )

            with pytest.raises(MultiAgentMockGoldenError, match="sha256 drift"):
                verify_multi_agent_mock_golden(copied_golden)
        finally:
            _cleanup(tmp)
