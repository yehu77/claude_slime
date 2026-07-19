"""Tests for root-level CLI entrypoints."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

import export_native_transformed_sft_dataset as native_transformed_sft_export_cli
import generate_schema_following_data as schema_following_cli
import export_claude_api_sft_dataset as claude_api_sft_export_cli
import prepare_native_transformed_sft_training_data as prepare_native_transformed_sft_cli
import prepare_schema_following_training_data as prepare_schema_following_cli
import run_native_transformed_sft_smoke as native_transformed_sft_smoke_cli
import run_external_agent_smoke as external_agent_smoke_cli
import validate_native_transformed_sft_dataset as native_transformed_sft_validate_cli
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig


class _ModelDumpResult:
    def __init__(self, payload: dict, *, ok: bool = True) -> None:
        self._payload = payload
        self.ok = ok

    def model_dump(self, mode: str = "json") -> dict:
        return dict(self._payload)


class TestGenerateSchemaFollowingDataCli:
    def test_synthetic_subcommand_passes_arguments(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}

        def fake_generate(output_dir, **kwargs):
            captured["output_dir"] = str(output_dir)
            captured.update(kwargs)
            return _ModelDumpResult({"generated": True})

        monkeypatch.setattr(
            schema_following_cli,
            "generate_synthetic_schema_following_data",
            fake_generate,
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "generate_schema_following_data.py",
                "synthetic",
                "outputs/schema_following/v1/synthetic",
                "--num-intents",
                "240",
                "--seed",
                "123",
            ],
        )

        assert schema_following_cli.main() == 0
        assert Path(captured["output_dir"]).as_posix().endswith(
            "outputs/schema_following/v1/synthetic"
        )
        assert captured["num_intents"] == 240
        assert captured["seed"] == 123

    def test_trajectory_derived_subcommand_reports_not_implemented(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}

        def fake_generate(source_dir, output_dir, **kwargs):
            captured["source_dir"] = str(source_dir)
            captured["output_dir"] = str(output_dir)
            captured.update(kwargs)
            return _ModelDumpResult({"generated": True})

        monkeypatch.setattr(
            schema_following_cli,
            "generate_schema_following_from_trajectories",
            fake_generate,
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "generate_schema_following_data.py",
                "trajectory-derived",
                "runs/studies/example",
                "outputs/schema_following/v1/trajectory_derived",
                "--source-type",
                "study",
                "--include-failed",
                "--verifier-passed",
                "false",
                "--min-reward",
                "0.25",
                "--seed",
                "123",
            ],
        )
        assert schema_following_cli.main() == 0
        assert Path(captured["source_dir"]).as_posix().endswith("runs/studies/example")
        assert Path(captured["output_dir"]).as_posix().endswith(
            "outputs/schema_following/v1/trajectory_derived"
        )
        assert captured["source_type"] == "study"
        assert captured["seed"] == 123
        assert captured["filter_config"].include_failed is True
        assert captured["filter_config"].verifier_passed is False
        assert captured["filter_config"].min_reward == 0.25


class TestPrepareSchemaFollowingTrainingDataCli:
    def test_fake_tokenizer_path_passes_explicit_fake_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}

        def fake_prepare(source_dir, output_dir, **kwargs):
            captured.update(kwargs)
            return _ModelDumpResult({"prepared": True})

        monkeypatch.setattr(
            prepare_schema_following_cli,
            "prepare_schema_following_training_input",
            fake_prepare,
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prepare_schema_following_training_data.py",
                "outputs/schema_following/v1/synthetic",
                "outputs/schema_following/v1/prepared",
                "--split",
                "train",
                "--fake-tokenizer",
                "--fake-vocab-size",
                "2048",
            ],
        )

        assert prepare_schema_following_cli.main() == 0
        assert captured["split"] == "train"
        assert isinstance(captured["tokenizer_config"], TokenizerConfig)
        assert captured["tokenizer_config"].tokenizer_name == "fake"
        assert isinstance(captured["fake_tokenizer_config"], FakeTokenizerConfig)
        assert captured["fake_tokenizer_config"].vocab_size == 2048


class TestRunExternalAgentSmokeCli:
    def test_codex_cli_passes_expected_arguments(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}

        def fake_run(**kwargs):
            captured.update(kwargs)
            return {"ok": True}

        monkeypatch.setattr(
            external_agent_smoke_cli,
            "run_external_agent_smoke",
            fake_run,
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run_external_agent_smoke.py",
                "codex_cli",
                "examples/buggy_counter",
                "runs/external_smoke",
                "--prompt",
                "Inspect the repo and run tests.",
                "--command-prefix",
                "python",
                "wrapper.py",
                "--exec-subcommand",
                "exec",
                "--run-id",
                "codex_smoke_001",
            ],
        )

        assert external_agent_smoke_cli.main() == 0
        assert captured["agent"] == "codex_cli"
        assert Path(str(captured["repo_path"])).as_posix().endswith("examples/buggy_counter")
        assert Path(str(captured["output_dir"])).as_posix().endswith("runs/external_smoke")
        assert captured["command_prefix"] == ["python", "wrapper.py"]
        assert captured["exec_subcommand"] == "exec"
        assert captured["run_id"] == "codex_smoke_001"

    def test_claude_cli_allows_optional_catalog_manifest(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}

        def fake_run(**kwargs):
            captured.update(kwargs)
            return {"ok": True}

        monkeypatch.setattr(
            external_agent_smoke_cli,
            "run_external_agent_smoke",
            fake_run,
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run_external_agent_smoke.py",
                "claude_code",
                "examples/buggy_counter",
                "runs/external_smoke",
                "--prompt",
                "Inspect the repo and run tests.",
                "--command-prefix",
                "python",
                "wrapper.py",
                "--catalog-manifest",
                "configs/agent_catalogs/codex_cli_public_catalog_v1.json",
            ],
        )

        assert external_agent_smoke_cli.main() == 0
        assert captured["agent"] == "claude_code"
        assert Path(str(captured["catalog_manifest"])).as_posix().endswith(
            "configs/agent_catalogs/codex_cli_public_catalog_v1.json"
        )

    def test_kilo_cli_passes_expected_arguments(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}

        def fake_run(**kwargs):
            captured.update(kwargs)
            return {"ok": True}

        monkeypatch.setattr(
            external_agent_smoke_cli,
            "run_external_agent_smoke",
            fake_run,
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run_external_agent_smoke.py",
                "kilo_code",
                "examples/buggy_counter",
                "runs/external_smoke",
                "--prompt",
                "Inspect the repo and run tests.",
                "--command-prefix",
                "python",
                "wrapper.py",
                "--timeout-seconds",
                "321",
                "--run-id",
                "kilo_smoke_001",
            ],
        )

        assert external_agent_smoke_cli.main() == 0
        assert captured["agent"] == "kilo_code"
        assert captured["command_prefix"] == ["python", "wrapper.py"]
        assert captured["timeout_seconds"] == 321
        assert captured["run_id"] == "kilo_smoke_001"


class TestExportClaudeApiSftDatasetCli:
    def test_passes_expected_arguments(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}

        def fake_build(source_dir, output_dir, **kwargs):
            captured["source_dir"] = str(source_dir)
            captured["output_dir"] = str(output_dir)
            captured.update(kwargs)
            return _ModelDumpResult({"exported": True})

        monkeypatch.setattr(
            claude_api_sft_export_cli,
            "build_claude_api_sft_dataset",
            fake_build,
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "export_claude_api_sft_dataset.py",
                "runs/claude_gateway_traces",
                "outputs/claude_api_sft/v1",
                "--no-strict",
                "--include-incomplete",
                "--continue-on-error",
            ],
        )

        assert claude_api_sft_export_cli.main() == 0
        assert Path(captured["source_dir"]).as_posix().endswith("runs/claude_gateway_traces")
        assert Path(captured["output_dir"]).as_posix().endswith("outputs/claude_api_sft/v1")
        assert captured["strict"] is False
        assert captured["include_incomplete"] is True
        assert captured["continue_on_error"] is True


class TestExportNativeTransformedSftDatasetCli:
    def test_passes_expected_arguments(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}

        def fake_build(source_dir, output_dir, **kwargs):
            captured["source_dir"] = str(source_dir)
            captured["output_dir"] = str(output_dir)
            captured.update(kwargs)
            return _ModelDumpResult({"exported": True})

        monkeypatch.setattr(
            native_transformed_sft_export_cli,
            "build_native_transformed_sft_dataset",
            fake_build,
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "export_native_transformed_sft_dataset.py",
                "runs/claude_gateway_traces",
                "outputs/native_transformed_sft/v1",
                "--no-strict",
                "--continue-on-error",
            ],
        )

        assert native_transformed_sft_export_cli.main() == 0
        assert Path(captured["source_dir"]).as_posix().endswith("runs/claude_gateway_traces")
        assert Path(captured["output_dir"]).as_posix().endswith(
            "outputs/native_transformed_sft/v1"
        )
        assert captured["strict"] is False
        assert captured["continue_on_error"] is True


class TestValidateNativeTransformedSftDatasetCli:
    def test_passes_expected_arguments_and_exit_code(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}

        def fake_validate(dataset_dir):
            captured["dataset_dir"] = str(dataset_dir)
            return _ModelDumpResult({"ok": False}, ok=False)

        monkeypatch.setattr(
            native_transformed_sft_validate_cli,
            "validate_native_transformed_sft_dataset",
            fake_validate,
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "validate_native_transformed_sft_dataset.py",
                "outputs/native_transformed_sft/v1",
            ],
        )

        assert native_transformed_sft_validate_cli.main() == 1
        assert Path(captured["dataset_dir"]).as_posix().endswith(
            "outputs/native_transformed_sft/v1"
        )


class TestPrepareNativeTransformedSftTrainingDataCli:
    def test_fake_tokenizer_path_passes_expected_arguments(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}

        def fake_prepare(source_dir, output_dir, **kwargs):
            captured["source_dir"] = str(source_dir)
            captured["output_dir"] = str(output_dir)
            captured.update(kwargs)
            return _ModelDumpResult({"prepared": True})

        monkeypatch.setattr(
            prepare_native_transformed_sft_cli,
            "prepare_native_transformed_sft_training_input",
            fake_prepare,
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prepare_native_transformed_sft_training_data.py",
                "outputs/native_transformed_sft/v1",
                "outputs/native_transformed_sft/prepared",
                "--fake-tokenizer",
                "--fake-vocab-size",
                "2048",
                "--fake-chars-per-token",
                "7",
                "--batch-size",
                "4",
                "--learning-rate",
                "2e-5",
                "--run-id",
                "native_prep",
            ],
        )

        assert prepare_native_transformed_sft_cli.main() == 0
        assert Path(captured["source_dir"]).as_posix().endswith(
            "outputs/native_transformed_sft/v1"
        )
        assert Path(captured["output_dir"]).as_posix().endswith(
            "outputs/native_transformed_sft/prepared"
        )
        assert isinstance(captured["tokenizer_config"], TokenizerConfig)
        assert captured["tokenizer_config"].tokenizer_name == "fake"
        assert isinstance(captured["fake_tokenizer_config"], FakeTokenizerConfig)
        assert captured["fake_tokenizer_config"].vocab_size == 2048
        assert captured["fake_tokenizer_config"].chars_per_token == 7
        assert captured["batch_size"] == 4
        assert captured["learning_rate"] == 2e-5
        assert captured["run_id"] == "native_prep"


class TestRunNativeTransformedSftSmokeCli:
    def test_passes_expected_arguments_and_controls_exit_code(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}

        def fake_run(dataset_dir, prepared_dir, output_dir, **kwargs):
            captured["dataset_dir"] = str(dataset_dir)
            captured["prepared_dir"] = str(prepared_dir)
            captured["output_dir"] = str(output_dir)
            captured.update(kwargs)
            return SimpleNamespace(
                success=True,
                model_dump=lambda mode="json": {"success": True},
            )

        monkeypatch.setattr(
            native_transformed_sft_smoke_cli,
            "run_native_transformed_sft_smoke",
            fake_run,
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run_native_transformed_sft_smoke.py",
                "outputs/native_transformed_sft/v1",
                "outputs/native_transformed_sft/prepared",
                "outputs/native_transformed_sft/smoke",
                "--model-name-or-path",
                "models/tiny",
                "--tokenizer-name-or-path",
                "models/tokenizer",
                "--device",
                "cpu",
                "--max-steps",
                "4",
                "--batch-size",
                "2",
                "--learning-rate",
                "2e-5",
                "--seed",
                "7",
                "--per-mode-probe-count",
                "3",
                "--max-new-tokens",
                "64",
                "--smoke-max-length",
                "4096",
                "--allow-remote-files",
            ],
        )

        assert native_transformed_sft_smoke_cli.main() == 0
        assert Path(captured["dataset_dir"]).as_posix().endswith(
            "outputs/native_transformed_sft/v1"
        )
        assert Path(captured["prepared_dir"]).as_posix().endswith(
            "outputs/native_transformed_sft/prepared"
        )
        assert Path(captured["output_dir"]).as_posix().endswith(
            "outputs/native_transformed_sft/smoke"
        )
        assert Path(captured["model_name_or_path"]).as_posix() == "models/tiny"
        assert Path(captured["tokenizer_name_or_path"]).as_posix() == "models/tokenizer"
        assert captured["max_steps"] == 4
        assert captured["batch_size"] == 2
        assert captured["learning_rate"] == 2e-5
        assert captured["seed"] == 7
        assert captured["per_mode_probe_count"] == 3
        assert captured["max_new_tokens"] == 64
        assert captured["smoke_max_length"] == 4096
        assert captured["local_files_only"] is False
