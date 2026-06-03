"""Tests for the root-level MIMO study entrypoints."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import run_first_study_mimo
import run_schema_attribution_mimo


def _fake_result(study_id: str = "study_x", output_dir: str = "runs/out"):
    comparison = SimpleNamespace(
        mode="base",
        pass_at_1=1.0,
        delta_pass_at_1=0.0,
        avg_reward=1.0,
        delta_avg_reward=0.0,
        entered_execution_rate=1.0,
        clean_run_pass_at_1=1.0,
        verifier_failed_rate=0.0,
    )
    return SimpleNamespace(
        config=SimpleNamespace(study_id=study_id),
        output_dir=output_dir,
        task_count=1,
        mode_comparisons=[comparison],
    )


def test_run_first_study_main_dispatches_with_loaded_config(monkeypatch):
    captured: dict = {}

    monkeypatch.setattr(
        run_first_study_mimo,
        "_load_local_config",
        lambda: {
            "resolved_api_key": "secret",
            "api_key_env": "MIMO_API_KEY",
            "base_url": "https://example.invalid/v1",
            "study_config_path": "configs/studies/first_mutation_sensitivity.json",
            "output_dir": "runs/studies/first",
        },
    )
    monkeypatch.setattr(
        run_first_study_mimo,
        "run_study_from_config",
        lambda study_config_path, client_factory, output_dir: captured.update(
            {
                "study_config_path": study_config_path,
                "output_dir": output_dir,
                "client_factory": client_factory,
            }
        )
        or _fake_result(output_dir=output_dir),
    )

    run_first_study_mimo.main()

    assert captured["study_config_path"] == "configs/studies/first_mutation_sensitivity.json"
    assert captured["output_dir"] == "runs/studies/first"
    assert callable(captured["client_factory"])


def test_run_schema_main_dispatches_with_schema_specific_fields(monkeypatch):
    captured: dict = {}

    monkeypatch.setattr(
        run_schema_attribution_mimo,
        "_load_local_config",
        lambda: {
            "resolved_api_key": "secret",
            "api_key_env": "MIMO_API_KEY",
            "base_url": "https://example.invalid/v1",
            "schema_study_config_path": "configs/studies/schema_failure_attribution_v1.json",
            "schema_output_dir": "runs/studies/schema",
        },
    )
    monkeypatch.setattr(
        run_schema_attribution_mimo,
        "run_study_from_config",
        lambda study_config_path, client_factory, output_dir: captured.update(
            {
                "study_config_path": study_config_path,
                "output_dir": output_dir,
                "client_factory": client_factory,
            }
        )
        or _fake_result(output_dir=output_dir),
    )

    run_schema_attribution_mimo.main()

    assert captured["study_config_path"] == "configs/studies/schema_failure_attribution_v1.json"
    assert captured["output_dir"] == "runs/studies/schema"
    assert callable(captured["client_factory"])


def test_run_first_study_loader_uses_resolved_local_config_path(monkeypatch):
    captured: dict = {}

    monkeypatch.setattr(
        run_first_study_mimo,
        "resolve_local_config_path",
        lambda filename, repo_fallback: captured.update(
            {"filename": filename, "repo_fallback": str(repo_fallback)}
        )
        or Path("C:/local/configs/mimo_v25pro.local.json"),
    )
    monkeypatch.setattr(
        run_first_study_mimo,
        "load_mimo_local_config",
        lambda path, example_path, default_api_key_env: captured.update(
            {
                "path": str(path),
                "example_path": str(example_path),
                "default_api_key_env": default_api_key_env,
            }
        )
        or {"base_url": "https://example.invalid/v1", "resolved_api_key": "x", "api_key_env": "MIMO_API_KEY"},
    )

    run_first_study_mimo._load_local_config()

    assert captured["filename"] == "mimo_v25pro.local.json"
    assert captured["repo_fallback"] == "configs\\local\\mimo_v25pro.local.json"
    assert captured["path"] == "C:\\local\\configs\\mimo_v25pro.local.json"
    assert captured["example_path"] == "configs\\local\\mimo_v25pro.local.example.json"
    assert captured["default_api_key_env"] == "MIMO_API_KEY"
