"""Pytest configuration for the tests directory.

Ensures pytest does not collect or retain files from repo-local temporary
workspaces created by tests.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).parent
_REPO_ROOT = _TESTS_DIR.parent.resolve()
_TEMP_DIR_PREFIXES = ("_",)
_TEMP_FILE_PREFIXES = ("pytest-cache-files-",)
_ARTIFACT_ROOT_ENV = "PYCODEAGENT_TEST_ARTIFACT_ROOT"
_ARTIFACT_BASE_ROOT = Path(tempfile.gettempdir()) / "pycodeagent-test-artifacts"
_SESSION_ARTIFACT_ROOT: Path | None = None

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Only ignore obvious cache directories here. Temporary test workspaces are
# handled in pytest_ignore_collect so nested pytest runs inside those
# workspaces can still collect their local tests.
collect_ignore_glob = [
    "__pycache__",
]


def pytest_addoption(parser) -> None:
    """Add repo-local test workflow flags."""
    parser.addoption(
        "--runslow",
        action="store_true",
        default=False,
        help="run tests marked as slow",
    )


def pytest_configure(config) -> None:
    """Point shared test artifact helpers at a managed session temp root."""
    global _SESSION_ARTIFACT_ROOT
    _ARTIFACT_BASE_ROOT.mkdir(parents=True, exist_ok=True)
    _SESSION_ARTIFACT_ROOT = _ARTIFACT_BASE_ROOT / f"run-{uuid.uuid4().hex[:8]}"
    _SESSION_ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    os.environ[_ARTIFACT_ROOT_ENV] = str(_SESSION_ARTIFACT_ROOT)


def _is_temp_test_path(path: Path) -> bool:
    """Return True when a path is a generated test artifact path."""
    for part in path.parts:
        if part.startswith(_TEMP_DIR_PREFIXES):
            return True
        if part.startswith(_TEMP_FILE_PREFIXES):
            return True
    return False


def _cleanup_stale_test_artifacts() -> None:
    """Best-effort cleanup of repo-local temporary test artifacts."""
    for child in _TESTS_DIR.iterdir():
        if child.name.startswith(_TEMP_DIR_PREFIXES):
            shutil.rmtree(child, ignore_errors=True)


def pytest_sessionstart(session) -> None:
    """Remove stale repo-local test artifacts before collection starts."""
    _cleanup_stale_test_artifacts()


def pytest_sessionfinish(session, exitstatus) -> None:
    """Remove the shared session artifact root after the run finishes."""
    if _SESSION_ARTIFACT_ROOT is not None and _SESSION_ARTIFACT_ROOT.exists():
        shutil.rmtree(_SESSION_ARTIFACT_ROOT, ignore_errors=True)


def pytest_collection_modifyitems(config, items) -> None:
    """Skip slow tests unless explicitly requested."""
    if config.getoption("--runslow"):
        return

    skip_slow = pytest.mark.skip(reason="need --runslow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


def _get_active_temp_root() -> Path | None:
    """Return the active temp test root for nested pytest runs, if any."""
    cwd = Path.cwd().resolve()
    for parent in (cwd, *cwd.parents):
        if parent.parent == _TESTS_DIR and parent.name.startswith(_TEMP_DIR_PREFIXES):
            return parent
    return None


def pytest_ignore_collect(collection_path: Path, config):
    """Ignore temporary test workspace directories during collection."""
    path = Path(collection_path).resolve()
    if not _is_temp_test_path(path):
        return None

    active_temp_root = _get_active_temp_root()
    if active_temp_root is not None:
        try:
            path.relative_to(active_temp_root)
            return None
        except ValueError:
            pass

    return True
