"""Mainline contract tests for the formal ``python -m pycodeagent`` CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pycodeagent import cli
from pycodeagent.application import cli_services


pytestmark = pytest.mark.mainline


def _service_result(
    tmp_path: Path,
    command: str,
    *,
    ok: bool = True,
) -> cli_services.ApplicationServiceResult:
    return cli_services.ApplicationServiceResult(
        command=command,
        ok=ok,
        status="succeeded" if ok else "contract_failed",
        output_root=str(tmp_path),
        manifest_path=str(tmp_path / "pycodeagent_cli_manifest.json"),
        task_ids=["task-a"],
        profile_modes=["base"],
        profile_seed_by_mode={"base": 0},
        family="native_claude",
        result_type="SyntheticResult",
        application_manifest_path=str(tmp_path / "application.json"),
        result={"status": "completed"},
    )


def test_command_tree_is_frozen_to_six_thin_services() -> None:
    help_text = cli._build_parser().format_help()

    assert set(cli._SERVICES) == {
        "run",
        "campaign",
        "export",
        "prep",
        "verify",
        "acceptance",
    }
    for command in cli._SERVICES:
        assert command in help_text
        assert cli._SERVICES[command].__module__ == (
            "pycodeagent.application.cli_services"
        )
    service_source = (
        Path(__file__).resolve().parents[1]
        / "pycodeagent/application/cli_services.py"
    ).read_text(encoding="utf-8")
    cli_source = (
        Path(__file__).resolve().parents[1] / "pycodeagent/cli.py"
    ).read_text(encoding="utf-8")
    for forbidden_route in (
        "pycodeagent.baselines",
        "pycodeagent.auxiliary",
        "archive.legacy",
    ):
        assert forbidden_route not in service_source
        assert forbidden_route not in cli_source


def test_module_entrypoint_exposes_the_formal_command_tree() -> None:
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "pycodeagent", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "{run,campaign,export,prep,verify,acceptance}" in completed.stdout


def test_config_is_overridden_by_explicit_cli_and_emits_stable_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "campaign.json"
    config_path.write_text(
        json.dumps(
            {
                "schema": cli.CLI_CONFIG_SCHEMA,
                "command": "campaign",
                "arguments": {
                    "kind": "behavior",
                    "output_root": "from-config",
                    "repeat_count": 1,
                    "profile_modes": ["base"],
                },
            }
        ),
        encoding="utf-8",
    )
    captured: dict = {}

    def fake_service(options):
        captured.update(options)
        return _service_result(tmp_path, "campaign")

    monkeypatch.setitem(cli._SERVICES, "campaign", fake_service)
    exit_code = cli.main(
        [
            "--config",
            str(config_path),
            "campaign",
            "--output-root",
            str(tmp_path / "from-cli"),
            "--repeat-count",
            "2",
        ]
    )

    assert exit_code == cli.EXIT_OK
    assert captured["output_root"] == tmp_path / "from-cli"
    assert captured["repeat_count"] == 2
    assert captured["family"] == "native_claude"
    assert captured["profile_seed_by_mode"] == {"base": 0}
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "schema": cli.CLI_RESULT_SCHEMA,
        "version": 1,
        "command": "campaign",
        "ok": True,
        "exit_code": 0,
        "manifest_path": str(tmp_path / "pycodeagent_cli_manifest.json"),
        "result": _service_result(
            tmp_path,
            "campaign",
        ).model_dump(mode="json"),
    }


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_kind"),
    [
        (FileNotFoundError("missing input"), cli.EXIT_INPUT, "input_error"),
        (RuntimeError("provider failed"), cli.EXIT_APPLICATION, "application_error"),
        (KeyboardInterrupt("stop"), cli.EXIT_INTERRUPTED, "interrupted"),
    ],
)
def test_machine_error_exit_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
    expected_code: int,
    expected_kind: str,
) -> None:
    def failing_service(_options):
        raise error

    monkeypatch.setitem(cli._SERVICES, "acceptance", failing_service)
    exit_code = cli.main(
        ["acceptance", "--local-only", "--output-root", str(tmp_path)]
    )

    assert exit_code == expected_code
    payload = json.loads(capsys.readouterr().err)
    assert payload["schema"] == cli.CLI_ERROR_SCHEMA
    assert payload["exit_code"] == expected_code
    assert payload["error"]["kind"] == expected_kind


def test_usage_and_contract_failure_exit_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["run"]) == cli.EXIT_USAGE
    usage_error = json.loads(capsys.readouterr().err)
    assert usage_error["error"]["kind"] == "usage_error"
    assert "task_id" in usage_error["error"]["message"]

    monkeypatch.setitem(
        cli._SERVICES,
        "acceptance",
        lambda _options: _service_result(tmp_path, "acceptance", ok=False),
    )
    assert cli.main(["acceptance", "--local-only"]) == cli.EXIT_CONTRACT_FAILED
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert result["exit_code"] == cli.EXIT_CONTRACT_FAILED


def test_config_rejects_unknown_arguments_before_dispatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "unsafe.json"
    config_path.write_text(
        json.dumps(
            {
                "schema": cli.CLI_CONFIG_SCHEMA,
                "command": "acceptance",
                "arguments": {"unowned_business_logic": True},
            }
        ),
        encoding="utf-8",
    )

    assert cli.main(
        ["--config", str(config_path), "acceptance"]
    ) == cli.EXIT_USAGE
    payload = json.loads(capsys.readouterr().err)
    assert "Unknown config arguments" in payload["error"]["message"]


def test_prep_service_writes_required_manifest_dimensions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application_manifest = tmp_path / "bundle_manifest.json"
    application_manifest.write_text("{}\n", encoding="utf-8")
    recommendation = SimpleNamespace(
        contract_ok=True,
        bundle_manifest_path=str(application_manifest),
        model_dump=lambda mode="json": {
            "contract_ok": True,
            "bundle_manifest_path": str(application_manifest),
        },
    )
    monkeypatch.setattr(
        cli_services,
        "prepare_slime_training_input",
        lambda *args, **kwargs: recommendation,
    )

    result = cli_services.prep_service(
        {
            "source_dir": tmp_path / "source",
            "output_dir": tmp_path / "prepared",
            "source_type": "batch",
            "include_failed": False,
            "verifier_passed": "any",
            "max_length": 256,
            "batch_size": 2,
            "learning_rate": 1e-4,
            "max_steps": 1,
            "seed": 7,
            "run_id": "formal_cli_test",
            "fake_tokenizer": True,
            "fake_vocab_size": 128,
            "fake_chars_per_token": 4,
        }
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["schema"] == cli_services.CLI_MANIFEST_SCHEMA
    assert manifest["version"] == 1
    assert manifest["status"] == "succeeded"
    assert manifest["task_ids"] == []
    assert manifest["profile"] == {"modes": [], "seed_by_mode": {}}
    assert manifest["family"] is None
    assert manifest["result_type"] == "SimpleNamespace"
    assert manifest["application_manifest_path"] == str(application_manifest)
