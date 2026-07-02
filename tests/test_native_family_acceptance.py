from __future__ import annotations

import json
import sys
from pathlib import Path

from pycodeagent.eval.native_family_acceptance import (
    CommandResult,
    _run_entrypoint_checks,
    _run_generation_smokes,
    _run_native_codex_direct_flow,
    run_native_family_acceptance,
)


def test_run_entrypoint_checks_match_strict_family_tool_sets() -> None:
    checks = _run_entrypoint_checks()

    by_name = {check.name: check for check in checks}

    assert by_name["build_native_claude_runtime"].passed is True
    assert by_name["build_native_claude_runtime"].tool_names == [
        "Bash",
        "Read",
        "Edit",
        "Write",
        "Grep",
        "Glob",
    ]
    assert by_name["build_native_codex_runtime"].passed is True
    assert by_name["build_native_codex_runtime"].tool_names == [
        "exec_command",
        "write_stdin",
        "apply_patch",
    ]


def test_native_codex_direct_flow_covers_exec_write_stdin_and_apply_patch(
    tmp_path: Path,
) -> None:
    result = _run_native_codex_direct_flow(tmp_path / "direct_flow")

    assert result.passed is True
    assert result.tool_results["exec_command"]["ok"] is True
    assert result.tool_results["write_stdin"]["ok"] is True
    assert result.tool_results["apply_patch"]["ok"] is True
    assert (
        Path(result.workspace_root) / "calc.py"
    ).read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"


def test_generation_smokes_preserve_family_contract_distinctions(
    tmp_path: Path,
) -> None:
    results = _run_generation_smokes(tmp_path / "generation", Path(sys.executable))
    by_family = {result.family: result for result in results}

    assert by_family["claude"].passed is True
    assert by_family["claude"].sample_count_by_family == {"claude": 4}
    assert by_family["claude"].sample_count_by_contract_kind == {"function": 4}

    assert by_family["codex"].passed is True
    assert by_family["codex"].sample_count_by_family == {"codex": 4}
    assert by_family["codex"].sample_count_by_contract_kind == {"freeform": 4}


def test_run_native_family_acceptance_local_only_writes_stabilized_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def _fake_pytest_suite(
        name: str,
        test_paths: list[str],
        logs_root: Path,
        python_executable: Path,
    ) -> CommandResult:
        logs_root.mkdir(parents=True, exist_ok=True)
        stdout_path = logs_root / f"{name}.stdout.log"
        stderr_path = logs_root / f"{name}.stderr.log"
        stdout_path.write_text("ok\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return CommandResult(
            name=name,
            command=[str(python_executable), "-m", "pytest", "-q", *test_paths],
            exit_code=0,
            duration_seconds=0.0,
            passed=True,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )

    monkeypatch.setattr(
        "pycodeagent.eval.native_family_acceptance._run_pytest_suite",
        _fake_pytest_suite,
    )

    report = run_native_family_acceptance(
        tmp_path / "acceptance",
        include_real_provider=False,
    )

    report_path = Path(report.output_root) / "native_family_acceptance_report.json"
    saved = json.loads(report_path.read_text(encoding="utf-8"))

    assert report.stabilized is True
    assert report.codex_real_provider_transport_limited is True
    assert report.real_provider_tasks == []
    assert all(result.passed for result in report.generation_smokes)
    assert saved["stabilized"] is True
    assert saved["codex_real_provider_transport_limited"] is True
