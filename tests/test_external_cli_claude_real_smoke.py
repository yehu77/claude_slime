"""Opt-in real Claude CLI smoke regression using invariant checks."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.traces import read_raw_trace

from run_external_agent_smoke import run_external_agent_smoke


_FIXTURE_DIR = Path("tests/fixtures/external_cli_claude_real_smoke")
_TEST_NAMESPACE = "external_cli_claude_real_smoke"
_DEFAULT_CLAUDE_EXE = (
    Path.home()
    / "AppData"
    / "Local"
    / "Microsoft"
    / "WinGet"
    / "Packages"
    / "Anthropic.ClaudeCode_Microsoft.Winget.Source_8wekyb3d8bbwe"
    / "claude.exe"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _real_claude_enabled() -> bool:
    return os.environ.get("PYCODEAGENT_RUN_REAL_CLAUDE_SMOKE") == "1"


def _resolve_claude_exe() -> Path:
    override = os.environ.get("PYCODEAGENT_CLAUDE_EXE")
    return Path(override) if override else _DEFAULT_CLAUDE_EXE


@pytest.mark.skipif(
    not _real_claude_enabled(),
    reason="set PYCODEAGENT_RUN_REAL_CLAUDE_SMOKE=1 to run real Claude smoke",
)
class TestExternalCliClaudeRealSmoke:
    def test_real_claude_smoke_matches_invariants(self) -> None:
        fixture = _load_json(_FIXTURE_DIR / "expected_invariants.json")
        claude_exe = _resolve_claude_exe()
        if not claude_exe.exists():
            pytest.skip(f"Claude executable not found: {claude_exe}")

        tmp = make_unique_test_dir(_TEST_NAMESPACE)
        try:
            result = run_external_agent_smoke(
                agent=fixture["agent"],
                repo_path=Path("examples/buggy_counter"),
                output_dir=tmp / "runs",
                prompt=fixture["prompt"],
                test_command=fixture["test_command"],
                command_prefix=[str(claude_exe), *fixture["command_flags"]],
                exec_subcommand=None,
                run_id="claude_real_smoke_invariant",
            )

            run_dir = Path(str(result["bundle_dir"]))
            raw_trace = read_raw_trace(
                run_dir / "raw_trace.jsonl",
                run_dir / "raw_trace_summary.json",
            )
            verifier = _load_json(run_dir / "verifier.json")
            adapter_metadata = _load_json(run_dir / "adapter_metadata.json")
            final_diff = (run_dir / "final.diff").read_text(encoding="utf-8")
            stdout_text = (run_dir / "stdout.log").read_text(encoding="utf-8")

            assert result["status"] == fixture["expected_status"]
            assert raw_trace.summary.status.value == fixture["expected_status"]
            assert raw_trace.summary.agent_name == fixture["agent"]
            assert raw_trace.summary.agent_version == fixture["agent_version"]
            assert raw_trace.summary.metadata["capture_mode"] == fixture["expected_capture_mode"]
            assert raw_trace.summary.metadata["returncode"] == 0

            assert verifier["passed"] is True
            assert verifier["score"] == 1.0
            assert "passed" in verifier["stdout"]

            assert adapter_metadata["status"] == fixture["expected_status"]
            assert adapter_metadata["returncode"] == 0
            assert adapter_metadata["sidecar_raw_trace_detected"] is fixture[
                "expected_sidecar_raw_trace_detected"
            ]
            assert adapter_metadata["sidecar_catalog_detected"] is fixture[
                "expected_sidecar_catalog_detected"
            ]
            assert Path(adapter_metadata["argv"][0]).name.lower() == "claude.exe"
            assert adapter_metadata["argv"][1:] == [
                *fixture["command_flags"],
                fixture["prompt"],
            ]

            assert [event.event_kind for event in raw_trace.events] == fixture[
                "expected_event_kinds"
            ]
            assert raw_trace.events[0].parsed_payload["content"] == fixture["prompt"]
            assert raw_trace.events[-1].parsed_payload["execution_status"] == fixture[
                "expected_status"
            ]
            assert raw_trace.events[-1].parsed_payload["final_status"] == fixture[
                "expected_status"
            ]

            assert stdout_text.strip()
            for expected in fixture["expected_diff_contains"]:
                assert expected in final_diff
        finally:
            cleanup_test_path(tmp)
