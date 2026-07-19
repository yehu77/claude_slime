from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from pycodeagent.eval.native_family_acceptance import (
    _REGRESSION_NATIVE_RUNTIME,
    _REGRESSION_RUNTIME_OBSERVED,
    _run_entrypoint_checks,
    _run_generation_smokes,
    _run_native_codex_direct_flow,
    _validate_regression_test_paths,
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

    for family, expected_stack in (
        ("claude", "native_claude"),
        ("codex", "native_codex"),
    ):
        output_root = Path(by_family[family].output_root)
        manifest = json.loads(
            (output_root / "toolview_mutation_data_generation_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        summary = json.loads(
            (output_root / "toolview_mutation_data_generation_summary.json").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["tool_stack_kind"] == expected_stack
        assert summary["tool_stack_kind"] == expected_stack


def test_mainline_regression_paths_are_checked_in_files() -> None:
    configured_paths = [
        *_REGRESSION_NATIVE_RUNTIME,
        *_REGRESSION_RUNTIME_OBSERVED,
    ]

    assert "tests/test_task_pack_integrity.py" in configured_paths
    assert "tests/test_realistic_task_consumers.py" in configured_paths
    assert "tests/test_route_boundaries.py" in configured_paths
    assert _validate_regression_test_paths(configured_paths) == configured_paths
    assert all(
        (Path(__file__).resolve().parents[1] / path).is_file()
        for path in configured_paths
    )


def test_mainline_regression_path_validation_rejects_missing_file() -> None:
    with pytest.raises(FileNotFoundError, match="regression paths do not exist"):
        _validate_regression_test_paths(["tests/test_missing_mainline_gate.py"])


def test_run_native_family_acceptance_local_only_writes_stabilized_report(
    tmp_path: Path,
) -> None:
    report = run_native_family_acceptance(
        tmp_path / "acceptance",
        include_real_provider=False,
    )

    report_path = Path(report.output_root) / "native_family_acceptance_report.json"
    saved = json.loads(report_path.read_text(encoding="utf-8"))

    assert report.stabilized is True
    assert report.codex_real_provider_transport_limited is True
    assert report.real_provider_tasks == []
    assert [result.name for result in report.regression_commands] == [
        "native_runtime_mainline",
        "runtime_observed_mainline",
    ]
    assert all(result.passed for result in report.regression_commands)
    assert all("mainline" in result.command for result in report.regression_commands)
    assert all(result.passed for result in report.generation_smokes)
    assert saved["stabilized"] is True
    assert saved["codex_real_provider_transport_limited"] is True
