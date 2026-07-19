"""Tests for real raw-artifact-capable external CLI adapters."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from pycodeagent.adapters import (
    ClaudeCodeAdapter,
    CodexCatalogProvider,
    CodexCliAdapter,
    KiloCodeAdapter,
)
from pycodeagent.adapters.external_cli_adapter import (
    ArtifactTruthConflictError,
    decode_subprocess_output,
    reconcile_sidecar_summary,
    resolve_command_argv,
)
from pycodeagent.env.task import CodingTask
from pycodeagent.harness import AgentHarness
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.traces import NoOpTraceNormalizer, read_raw_trace
from pycodeagent.trajectory.schema import RunStatus, VerifyResult


_TEST_NAMESPACE = "external_cli_adapters"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "README.md").write_text("# Repo\n", encoding="utf-8")
    (repo / "module.py").write_text("print('before')\n", encoding="utf-8")
    (repo / "test_smoke.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    return repo


def _make_task(repo: Path) -> CodingTask:
    return CodingTask(
        task_id="task_001",
        repo_path=repo,
        prompt="Inspect the repo and run tests.",
        test_command=[sys.executable, "-m", "pytest", "-q"],
    )


def _write_fake_external_cli_script(path: Path, *, write_sidecar: bool) -> None:
    script = f"""
import json
import os
from pathlib import Path

workspace = Path(os.environ["PYCODEAGENT_WORKSPACE_DIR"])
raw_trace_path = Path(os.environ["PYCODEAGENT_RAW_TRACE_PATH"])
summary_path = Path(os.environ["PYCODEAGENT_RAW_TRACE_SUMMARY_PATH"])
catalog_path = Path(os.environ["PYCODEAGENT_TOOL_CATALOG_PATH"])
agent_id = os.environ["PYCODEAGENT_AGENT_ID"]

(workspace / "module.py").write_text("print('after')\\n", encoding="utf-8")
print(f"{{agent_id}} fake run complete")

if {str(write_sidecar)}:
    raw_trace_path.write_text(
        json.dumps({{
            "event_id": "event_001",
            "seq": 1,
            "event_kind": "tool_call",
            "source": "agent",
            "visibility": "model",
            "evidence_level": "observed",
            "raw_payload": {{}},
            "parsed_payload": {{
                "tool_name": "local_shell",
                "arguments": {{"command": "pytest -q"}},
                "canonical_name": "run_command"
            }},
            "parent_event_id": None,
            "artifact_refs": [],
            "error": None,
            "metadata": {{}}
        }}) + "\\n",
        encoding="utf-8",
    )
    summary_path.write_text(json.dumps({{
        "schema_version": 1,
        "trace_id": f"{{agent_id}}_sidecar_trace",
        "agent_name": agent_id,
        "agent_version": "raw_trace_v1",
        "task_id": "task_001",
        "workspace_dir": str(workspace),
        "tool_catalog_id": f"{{agent_id}}_sidecar_catalog",
        "metadata": {{
            "capture_mode": "sidecar"
        }}
    }}, indent=2), encoding="utf-8")
    catalog_path.write_text(json.dumps({{
        "schema_version": 1,
        "catalog_id": f"{{agent_id}}_sidecar_catalog",
        "agent_name": agent_id,
        "agent_version": "raw_trace_v1",
        "capture_mode": "runtime_effective",
        "source_kind": "sidecar",
        "captured_at": None,
        "tools": [],
        "metadata": {{}}
    }}, indent=2), encoding="utf-8")
"""
    path.write_text(script, encoding="utf-8")


def _copy_repo(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        destination = target / child.name
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            destination.write_text(child.read_text(encoding="utf-8"), encoding="utf-8")


class TestExternalCliAdapters:
    def test_command_resolution_and_decode_helpers_are_windows_safe(self) -> None:
        resolved = resolve_command_argv(["python", "--version"])
        assert resolved[0].lower().endswith((".exe", "python"))
        assert resolved[1:] == ["--version"]
        assert decode_subprocess_output(b"ok\xffdone") == "ok�done"
        assert decode_subprocess_output(None) == ""

    def test_sidecar_summary_conflict_fails_loudly(self) -> None:
        fixture = Path(
            "tests/fixtures/external_cli_wrapper_conflict_negative/"
            "raw_trace_summary.json"
        )
        verifier = {
            "passed": False,
            "score": 0.0,
            "stdout": "one failing test",
            "stderr": "",
        }

        with pytest.raises(
            ArtifactTruthConflictError,
            match="verifier_result",
        ):
            reconcile_sidecar_summary(
                sidecar_summary_path=fixture,
                execution_status=RunStatus.COMPLETED,
                final_diff="",
                verifier=VerifyResult.model_validate(verifier),
            )

    def test_codex_adapter_uses_sidecar_raw_trace_when_present(self) -> None:
        tmp = _get_test_dir()
        try:
            repo = _make_repo(tmp)
            task = _make_task(repo)
            script = tmp / "fake_codex.py"
            _write_fake_external_cli_script(script, write_sidecar=True)
            adapter = CodexCliAdapter(
                command_prefix=[sys.executable, str(script)],
                exec_subcommand=None,
            )
            harness = AgentHarness(
                adapter=adapter,
                normalizer=NoOpTraceNormalizer("codex_cli"),
                tool_catalog_provider=CodexCatalogProvider(),
            )

            result = harness.run_task(task, output_dir=tmp / "runs", run_id="run_001")

            raw_trace = read_raw_trace(
                result.run_artifacts.raw_trace_path,
                result.run_artifacts.raw_trace_summary_path,
            )
            assert raw_trace.summary.metadata["capture_mode"] == "sidecar"
            assert raw_trace.summary.agent_name == "codex_cli"
            assert raw_trace.summary.final_diff
            assert raw_trace.summary.verifier_result is not None
            assert raw_trace.summary.verifier_result.passed
            assert raw_trace.summary.status == RunStatus.COMPLETED
            assert raw_trace.summary.metadata["execution_status"] == "completed"
            assert raw_trace.summary.metadata["final_status"] == "completed"
            assert raw_trace.summary.metadata["reward"] == 1.0
            assert result.run_artifacts.tool_catalog_path is not None
            assert result.tool_catalog is not None
            assert result.tool_catalog.source_kind == "sidecar"
        finally:
            _cleanup(tmp)

    def test_claude_adapter_falls_back_to_observed_trace_when_no_sidecar(self) -> None:
        tmp = _get_test_dir()
        try:
            repo = _make_repo(tmp)
            task = _make_task(repo)
            script = tmp / "fake_claude.py"
            _write_fake_external_cli_script(script, write_sidecar=False)
            adapter = ClaudeCodeAdapter(
                command_prefix=[sys.executable, str(script)],
                exec_subcommand=None,
            )

            run_dir = tmp / "run_dir"
            workspace = tmp / "workspace_copy"
            from pycodeagent.adapters.base import AgentRunContext

            _copy_repo(repo, workspace)
            run_dir.mkdir(parents=True, exist_ok=True)
            context = AgentRunContext(
                run_id="run_001",
                task_id=task.task_id,
                agent_id=adapter.agent_id(),
                run_dir=run_dir,
                workspace_dir=workspace,
                stdout_path=run_dir / "stdout.log",
                stderr_path=run_dir / "stderr.log",
            )
            result = adapter.run_task(task, context)
            raw_trace = read_raw_trace(result.raw_trace_path, result.raw_trace_summary_path)
            metadata = json.loads((run_dir / "adapter_metadata.json").read_text(encoding="utf-8"))

            assert result.tool_catalog_path is None
            assert raw_trace.summary.metadata["capture_mode"] == "observed_fallback"
            assert raw_trace.summary.agent_name == "claude_code"
            assert any(event.event_kind == "stdout_capture" for event in raw_trace.events)
            assert raw_trace.status == RunStatus.COMPLETED
            assert "module.py" in Path(result.final_diff_path).read_text(encoding="utf-8")
            assert metadata["sidecar_protocol_env"]["PYCODEAGENT_AGENT_ID"] == "claude_code"
        finally:
            _cleanup(tmp)

    def test_kilo_adapter_produces_complete_bundle_via_harness(self) -> None:
        tmp = _get_test_dir()
        try:
            repo = _make_repo(tmp)
            task = _make_task(repo)
            script = tmp / "fake_kilo.py"
            _write_fake_external_cli_script(script, write_sidecar=False)
            adapter = KiloCodeAdapter(
                command_prefix=[sys.executable, str(script)],
                exec_subcommand=None,
            )
            harness = AgentHarness(
                adapter=adapter,
                normalizer=NoOpTraceNormalizer("kilo_code"),
                tool_catalog_provider=None,
            )

            result = harness.run_task(task, output_dir=tmp / "runs", run_id="run_kilo_001")

            raw_trace = read_raw_trace(
                result.run_artifacts.raw_trace_path,
                result.run_artifacts.raw_trace_summary_path,
            )
            metadata = json.loads(
                (result.bundle_paths.adapter_metadata_path).read_text(encoding="utf-8")
            )

            assert result.run_artifacts.tool_catalog_path is None
            assert raw_trace.summary.agent_name == "kilo_code"
            assert raw_trace.summary.metadata["capture_mode"] == "observed_fallback"
            assert result.run_artifacts.stdout_path is not None
            assert result.run_artifacts.stderr_path is not None
            assert result.run_artifacts.final_diff_path is not None
            assert result.run_artifacts.verifier_result_path is not None
            assert Path(result.run_artifacts.final_diff_path).read_text(encoding="utf-8")
            assert Path(result.run_artifacts.verifier_result_path).exists()
            assert metadata["sidecar_protocol_env"]["PYCODEAGENT_AGENT_ID"] == "kilo_code"
            assert raw_trace.events[-1].event_kind == "run_end"
            assert raw_trace.status == RunStatus.COMPLETED
        finally:
            _cleanup(tmp)
