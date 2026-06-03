"""Shared helpers for pytest-managed temporary artifact roots."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

_ARTIFACT_ROOT_ENV = "PYCODEAGENT_TEST_ARTIFACT_ROOT"
_FALLBACK_ROOT_NAME = "pycodeagent-test-artifacts"
_INVALID_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


def _sanitize_component(value: str) -> str:
    cleaned = _INVALID_CHARS.sub("_", value).strip("._-")
    return cleaned or "test"


def _fallback_artifact_root() -> Path:
    return Path(tempfile.gettempdir()) / _FALLBACK_ROOT_NAME


def get_test_artifact_root() -> Path:
    """Return the session artifact root outside the repository tree."""
    raw_root = os.environ.get(_ARTIFACT_ROOT_ENV)
    root = Path(raw_root) if raw_root else _fallback_artifact_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_managed_test_root(name: str) -> Path:
    """Return a stable per-module artifact root under the session temp root."""
    root = get_test_artifact_root() / _sanitize_component(name)
    root.mkdir(parents=True, exist_ok=True)
    return root


def reset_test_root(name: str) -> Path:
    """Delete and recreate a per-module artifact root."""
    root = get_managed_test_root(name)
    cleanup_test_path(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def make_unique_test_dir(name: str, *, prefix: str | None = None) -> Path:
    """Create a unique artifact directory under a managed module root."""
    root = get_managed_test_root(name)
    stem = _sanitize_component(prefix or name)
    path = root / f"{stem}_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_request_test_dir(name: str, request: object) -> Path:
    """Create a unique artifact directory keyed by the current test name."""
    node_name = getattr(getattr(request, "node", None), "name", "test")
    return make_unique_test_dir(name, prefix=node_name)


def cleanup_test_path(path: Path) -> None:
    """Best-effort recursive removal for temporary test directories."""
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
