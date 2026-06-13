"""Tests for the verifier.

Covers:
- Verifier passes on a workspace with passing tests
- Verifier fails on a workspace with failing tests
- stdout/stderr are recorded
- Workspace not found error
- No external network dependency
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pycodeagent.env.task import CodingTask
from pycodeagent.env.verifier import run_verifier
from pycodeagent.testing import cleanup_test_path, make_request_test_dir


pytestmark = [pytest.mark.slow, pytest.mark.integration]


def _get_test_root(request: pytest.FixtureRequest) -> Path:
    """Get a unique test root directory for the current test."""
    return make_request_test_dir("verifier", request)


@pytest.fixture
def test_root(request: pytest.FixtureRequest):
    """Create a clean isolated test directory for each test."""
    root = _get_test_root(request)
    yield root
    cleanup_test_path(root)


def _make_workspace(test_root: Path, name: str, files: dict[str, str]) -> Path:
    """Create a workspace directory with files."""
    workspace = test_root / name
    workspace.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = workspace / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return workspace


def _make_task(
    workspace: Path,
    test_command: str | list[str] = "pytest -q",
) -> CodingTask:
    """Create a CodingTask for testing."""
    return CodingTask(
        task_id="test_verify",
        repo_path=workspace,
        prompt="Test task",
        test_command=test_command,
    )


class TestVerifierPassing:
    """Tests for verifier on passing test suites."""

    def test_passing_tests(self, test_root):
        """Verifier should return passed=True for passing tests."""
        workspace = _make_workspace(test_root, "passing", {
            "test_pass.py": "def test_ok():\n    assert 1 + 1 == 2\n",
        })
        task = _make_task(workspace)

        result = run_verifier(task, workspace)

        assert result.passed
        assert result.score == 1.0
        assert "1 passed" in result.stdout or "passed" in result.stdout.lower()

    def test_stdout_recorded(self, test_root):
        """Verifier should record stdout."""
        workspace = _make_workspace(test_root, "stdout_test", {
            "test_simple.py": "def test_true():\n    assert True\n",
        })
        task = _make_task(workspace)

        result = run_verifier(task, workspace)

        # stdout should contain something (at minimum pytest output)
        assert result.passed
        # stdout should not be empty for a passing test run
        assert len(result.stdout) > 0


class TestVerifierFailing:
    """Tests for verifier on failing test suites."""

    def test_failing_tests(self, test_root):
        """Verifier should return passed=False for failing tests."""
        workspace = _make_workspace(test_root, "failing", {
            "test_fail.py": "def test_bad():\n    assert 1 + 1 == 3\n",
        })
        task = _make_task(workspace)

        result = run_verifier(task, workspace)

        assert not result.passed
        assert result.score == 0.0

    def test_stderr_or_stdout_on_failure(self, test_root):
        """Verifier should capture output on failure."""
        workspace = _make_workspace(test_root, "fail_output", {
            "test_err.py": "def test_wrong():\n    assert False, 'expected failure'\n",
        })
        task = _make_task(workspace)

        result = run_verifier(task, workspace)

        assert not result.passed
        # At least one of stdout/stderr should have content
        assert len(result.stdout) > 0 or len(result.stderr) > 0


class TestVerifierEdgeCases:
    """Tests for verifier edge cases."""

    def test_missing_workspace(self, test_root):
        """Verifier should return failure for non-existent workspace."""
        workspace = test_root / "nonexistent_dir"
        task = _make_task(workspace)

        result = run_verifier(task, workspace)

        assert not result.passed
        assert "does not exist" in result.stderr

    def test_custom_test_command(self, test_root):
        """Verifier should respect custom test_command."""
        workspace = _make_workspace(test_root, "custom_cmd", {
            "check.py": "print('check passed')\n",
        })
        task = _make_task(workspace, test_command=[sys.executable, "check.py"])

        result = run_verifier(task, workspace)

        assert result.passed
        assert "check passed" in result.stdout

    def test_shell_syntax_in_test_command_rejected(self, test_root):
        """Verifier should reject string commands that rely on shell operators."""
        workspace = _make_workspace(test_root, "bad_shell", {
            "test_ok.py": "def test_ok():\n    assert True\n",
        })
        task = _make_task(workspace, test_command="pytest -q && echo hacked")

        result = run_verifier(task, workspace)

        assert not result.passed
        assert "unsupported shell syntax" in result.stderr
