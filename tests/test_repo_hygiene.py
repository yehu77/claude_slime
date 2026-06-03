"""Tests for repository hygiene scanning and cleanup."""

from __future__ import annotations

from pathlib import Path

from pycodeagent.dev.repo_hygiene import (
    clean_hygiene_findings,
    discover_hygiene_findings,
    discover_local_resource_findings,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


def _make_file(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_repo_root() -> Path:
    return make_unique_test_dir("repo_hygiene", prefix="repo")


def test_discover_hygiene_findings_detects_known_artifacts():
    repo_root = _make_repo_root()
    try:
        _make_file(repo_root / "module.pyc")
        _make_file(repo_root / "__pycache__" / "module.cpython-312.pyc")
        _make_file(repo_root / "tests" / "_generated" / "data.json")
        _make_file(repo_root / "tests" / "tmp_case" / "log.txt")
        _make_file(repo_root / "runs" / "run_001" / "trajectory.json")
        _make_file(repo_root / "tmp_debug_single_run" / "note.txt")
        _make_file(repo_root / "slime-main" / "pytest-cache-files-abc123" / "cache.bin")

        findings = discover_hygiene_findings(repo_root)
        relative_paths = {finding.path.relative_to(repo_root).as_posix() for finding in findings}

        assert "module.pyc" in relative_paths
        assert "__pycache__" in relative_paths
        assert "tests/_generated" in relative_paths
        assert "tests/tmp_case" in relative_paths
        assert "runs" in relative_paths
        assert "tmp_debug_single_run" in relative_paths
        assert "slime-main/pytest-cache-files-abc123" in relative_paths
    finally:
        cleanup_test_path(repo_root)


def test_clean_hygiene_findings_removes_detected_artifacts():
    repo_root = _make_repo_root()
    try:
        _make_file(repo_root / "tests" / "_generated" / "data.json")
        _make_file(repo_root / "tmp_cache" / "value.txt")
        _make_file(repo_root / "__pycache__" / "module.cpython-312.pyc")

        removed = clean_hygiene_findings(repo_root)
        removed_paths = {path.relative_to(repo_root).as_posix() for path in removed}

        assert "tests/_generated" in removed_paths
        assert "tmp_cache" in removed_paths
        assert "__pycache__" in removed_paths
        assert not (repo_root / "tests" / "_generated").exists()
        assert not (repo_root / "tmp_cache").exists()
        assert not (repo_root / "__pycache__").exists()
    finally:
        cleanup_test_path(repo_root)


def test_discover_local_resource_findings_detects_repo_local_models_and_secrets():
    repo_root = _make_repo_root()
    try:
        _make_file(
            repo_root / "configs" / "local" / "mimo_v25pro.local.json",
            """
            {
              "api_key": "secret-value",
              "base_url": "https://example.invalid/v1"
            }
            """.strip(),
        )
        _make_file(repo_root / "models" / "Qwen3-0.6B" / "model.safetensors")
        _make_file(repo_root / "models" / "Qwen3-0.6B" / ".cache" / "huggingface" / "CACHEDIR.TAG")
        _make_file(repo_root / ".hf-cache" / "cache.bin")

        findings = discover_local_resource_findings(repo_root)
        categories_by_path: dict[str, set[str]] = {}
        for finding in findings:
            relative_path = finding.path.relative_to(repo_root).as_posix()
            categories_by_path.setdefault(relative_path, set()).add(finding.category)
        categories = {finding.category for finding in findings}

        assert categories_by_path["configs/local/mimo_v25pro.local.json"] == {
            "repo_local_config",
            "inline_secret",
        }
        assert "repo_model_weight" in categories
        assert "repo_hf_cache" in categories
        assert "inline_secret" in categories
    finally:
        cleanup_test_path(repo_root)
