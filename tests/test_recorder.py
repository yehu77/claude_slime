"""Tests for the RunRecorder.

Covers:
- Run directory creation
- trajectory.json writing and re-reading
- tool_profile.json writing and re-reading
- verifier.json writing and re-reading
- final.patch writing and re-reading
- write_all convenience method
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.testing import cleanup_test_path, get_managed_test_root, reset_test_root
from pycodeagent.tools.spec import ToolAdapter, ToolProfile, ToolView
from pycodeagent.trajectory.recorder import RunRecorder
from pycodeagent.trajectory.schema import (
    Role,
    RunStatus,
    ToolCall,
    Trajectory,
    VerifyResult,
)


_TEST_WORKSPACE_NAMESPACE = "recorder"


@pytest.fixture(autouse=True)
def _clean_test_workspace():
    """Ensure a clean test workspace dir before/after each test."""
    reset_test_root(_TEST_WORKSPACE_NAMESPACE)
    yield
    cleanup_test_path(get_managed_test_root(_TEST_WORKSPACE_NAMESPACE))


def _workspace_root() -> Path:
    return get_managed_test_root(_TEST_WORKSPACE_NAMESPACE)


def _make_trajectory() -> Trajectory:
    """Create a minimal trajectory for testing."""
    t = Trajectory(
        task_id="test_task",
        repo="/tmp/test_repo",
        tool_profile_id="base",
        status=RunStatus.COMPLETED,
    )
    t.add_system("You are a coding agent.")
    t.add_user("Fix the bug.")
    t.add_assistant("I will fix it.", tool_calls=[
        ToolCall(id="c1", name="finish", arguments={"answer": "Done"}),
    ])
    t.metadata = {"total_turns": 1}
    return t


def _make_profile() -> ToolProfile:
    """Create a minimal tool profile for testing."""
    return ToolProfile(
        profile_id="base",
        tools=[
            ToolView(
                canonical_name="finish",
                exposed_name="finish",
                description="Finish the task.",
                input_schema={"type": "object", "properties": {}, "required": []},
                version="default",
            ),
        ],
        adapters={"finish": ToolAdapter()},
    )


class TestRunRecorderDirectory:
    """Tests for run directory management."""

    def test_ensure_dir_creates_directory(self):
        """ensure_dir should create the run directory."""
        run_dir = _workspace_root() / "run_001"
        recorder = RunRecorder(run_dir)
        recorder.ensure_dir()
        assert run_dir.exists()
        assert run_dir.is_dir()

    def test_ensure_dir_creates_parent_directories(self):
        """ensure_dir should create nested directories."""
        run_dir = _workspace_root() / "nested" / "deep" / "run_002"
        recorder = RunRecorder(run_dir)
        recorder.ensure_dir()
        assert run_dir.exists()

    def test_ensure_dir_idempotent(self):
        """ensure_dir should not fail if directory already exists."""
        run_dir = _workspace_root() / "run_003"
        recorder = RunRecorder(run_dir)
        recorder.ensure_dir()
        recorder.ensure_dir()  # Should not raise


class TestWriteTrajectory:
    """Tests for trajectory.json persistence."""

    def test_writes_trajectory_json(self):
        """Should write trajectory.json."""
        run_dir = _workspace_root() / "traj_test"
        recorder = RunRecorder(run_dir)
        trajectory = _make_trajectory()

        path = recorder.write_trajectory(trajectory)
        assert path == run_dir / "trajectory.json"
        assert path.exists()

    def test_trajectory_json_readable(self):
        """Written trajectory.json should be valid JSON with key fields."""
        run_dir = _workspace_root() / "traj_read"
        recorder = RunRecorder(run_dir)
        trajectory = _make_trajectory()
        recorder.write_trajectory(trajectory)

        data = json.loads((run_dir / "trajectory.json").read_text(encoding="utf-8"))
        assert data["task_id"] == "test_task"
        assert data["status"] == "completed"
        assert len(data["messages"]) >= 3  # system + user + assistant
        assert data["messages"][0]["role"] == "system"


class TestWriteToolProfile:
    """Tests for tool_profile.json persistence."""

    def test_writes_tool_profile_json(self):
        """Should write tool_profile.json."""
        run_dir = _workspace_root() / "profile_test"
        recorder = RunRecorder(run_dir)
        profile = _make_profile()

        path = recorder.write_tool_profile(profile)
        assert path == run_dir / "tool_profile.json"
        assert path.exists()

    def test_tool_profile_json_readable(self):
        """Written tool_profile.json should be valid JSON with key fields."""
        run_dir = _workspace_root() / "profile_read"
        recorder = RunRecorder(run_dir)
        profile = _make_profile()
        recorder.write_tool_profile(profile)

        data = json.loads((run_dir / "tool_profile.json").read_text(encoding="utf-8"))
        assert data["profile_id"] == "base"
        assert len(data["tools"]) == 1
        assert data["tools"][0]["canonical_name"] == "finish"


class TestWriteVerifierResult:
    """Tests for verifier.json persistence."""

    def test_writes_verifier_json(self):
        """Should write verifier.json."""
        run_dir = _workspace_root() / "verif_test"
        recorder = RunRecorder(run_dir)
        result = VerifyResult(passed=True, score=1.0, stdout="OK", stderr="")

        path = recorder.write_verifier_result(result)
        assert path == run_dir / "verifier.json"
        assert path.exists()

    def test_verifier_json_readable_passed(self):
        """Written verifier.json should contain correct pass status."""
        run_dir = _workspace_root() / "verif_read_pass"
        recorder = RunRecorder(run_dir)
        result = VerifyResult(passed=True, score=1.0, stdout="1 passed", stderr="")
        recorder.write_verifier_result(result)

        data = json.loads((run_dir / "verifier.json").read_text(encoding="utf-8"))
        assert data["passed"] is True
        assert data["score"] == 1.0
        assert data["stdout"] == "1 passed"

    def test_verifier_json_readable_failed(self):
        """Written verifier.json should contain correct fail status."""
        run_dir = _workspace_root() / "verif_read_fail"
        recorder = RunRecorder(run_dir)
        result = VerifyResult(passed=False, score=0.0, stdout="", stderr="FAILED")
        recorder.write_verifier_result(result)

        data = json.loads((run_dir / "verifier.json").read_text(encoding="utf-8"))
        assert data["passed"] is False
        assert data["score"] == 0.0


class TestWriteFinalPatch:
    """Tests for final.patch persistence."""

    def test_writes_final_patch(self):
        """Should write final.patch."""
        run_dir = _workspace_root() / "patch_test"
        recorder = RunRecorder(run_dir)
        patch_text = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n"

        path = recorder.write_final_patch(patch_text)
        assert path == run_dir / "final.patch"
        assert path.exists()

    def test_final_patch_content(self):
        """Written patch should have exact content."""
        run_dir = _workspace_root() / "patch_read"
        recorder = RunRecorder(run_dir)
        patch_text = "--- a/bar.py\n+++ b/bar.py\n"
        recorder.write_final_patch(patch_text)

        content = (run_dir / "final.patch").read_text(encoding="utf-8")
        assert content == patch_text

    def test_empty_patch(self):
        """Should handle empty patch."""
        run_dir = _workspace_root() / "patch_empty"
        recorder = RunRecorder(run_dir)
        recorder.write_final_patch("")

        content = (run_dir / "final.patch").read_text(encoding="utf-8")
        assert content == ""


class TestWriteAll:
    """Tests for the write_all convenience method."""

    def test_write_all_creates_all_artifacts(self):
        """write_all should create all artifact files."""
        run_dir = _workspace_root() / "all_test"
        recorder = RunRecorder(run_dir)
        trajectory = _make_trajectory()
        profile = _make_profile()
        verifier_result = VerifyResult(passed=True, score=1.0)
        patch_text = "--- a/a.py\n+++ b/a.py\n"

        paths = recorder.write_all(trajectory, profile, verifier_result, patch_text)

        assert "trajectory" in paths
        assert "tool_profile" in paths
        assert "verifier" in paths
        assert "patch" in paths
        assert paths["trajectory"].exists()
        assert paths["tool_profile"].exists()
        assert paths["verifier"].exists()
        assert paths["patch"].exists()
