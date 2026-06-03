"""Tests for the coding environment orchestration.

Covers:
- Workspace preparation (copy)
- Full run with fake client (verifier passing)
- Full run with fake client (verifier failing)
- Artifact persistence
- Reward computation
- Final patch generation
- Source repo not found error
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient
import pycodeagent.env.coding_env as coding_env_module
from pycodeagent.env.coding_env import (
    compute_diff,
    compute_reward,
    compute_reward_details,
    prepare_workspace,
    run_coding_task,
)
from pycodeagent.testing import cleanup_test_path, make_request_test_dir
from pycodeagent.trajectory.schema import (
    RunStatus,
    ToolCall,
    ToolResult,
    Trajectory,
    VerifyResult,
)


pytestmark = [pytest.mark.slow, pytest.mark.integration]


def _get_test_root(request: pytest.FixtureRequest) -> Path:
    """Get a unique test root directory for the current test."""
    return make_request_test_dir("coding_env", request)


@pytest.fixture
def test_root(request: pytest.FixtureRequest):
    """Create a clean isolated test directory for each test."""
    root = _get_test_root(request)
    yield root
    cleanup_test_path(root)


def _make_source_repo(test_root: Path, name: str, files: dict[str, str]) -> Path:
    """Create a source repo directory with files."""
    repo = test_root / "source" / name
    repo.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return repo


class RaisingClient:
    """LLM client that simulates a provider failure."""

    def generate(self, request):
        raise RuntimeError("provider disconnected")


class TestPrepareWorkspace:
    """Tests for workspace preparation."""

    def test_copies_source_repo(self, test_root):
        """Should copy source repo to workspace."""
        source = _make_source_repo(test_root, "copy_test", {"main.py": "print('hello')"})
        workspace_base = test_root / "workspaces"

        workspace = prepare_workspace(source, workspace_base)

        assert workspace.exists()
        assert (workspace / "main.py").exists()
        assert (workspace / "main.py").read_text(encoding="utf-8") == "print('hello')"
        # workspace should be under workspace_base
        assert workspace.parent == workspace_base

    def test_source_not_found_raises(self, test_root):
        """Should raise ValueError for non-existent source."""
        workspace_base = test_root / "workspaces"
        with pytest.raises(ValueError, match="does not exist"):
            prepare_workspace(test_root / "no_such_repo", workspace_base)

    def test_workspace_is_independent(self, test_root):
        """Workspace modifications should not affect source."""
        source = _make_source_repo(test_root, "independent", {"data.txt": "original"})
        workspace_base = test_root / "workspaces"

        workspace = prepare_workspace(source, workspace_base)

        # Modify workspace
        (workspace / "data.txt").write_text("modified", encoding="utf-8")

        # Source should be unchanged
        assert (source / "data.txt").read_text(encoding="utf-8") == "original"

    def test_multiple_workspaces_unique(self, test_root):
        """Multiple workspace creations should each get unique directories."""
        source = _make_source_repo(test_root, "multi", {"v1.txt": "version1"})
        workspace_base = test_root / "workspaces"

        ws1 = prepare_workspace(source, workspace_base)
        ws2 = prepare_workspace(source, workspace_base)

        # Each workspace is unique
        assert ws1 != ws2
        assert ws1.exists()
        assert ws2.exists()
        # Both have the content
        assert (ws1 / "v1.txt").read_text(encoding="utf-8") == "version1"
        assert (ws2 / "v1.txt").read_text(encoding="utf-8") == "version1"


class TestComputeDiff:
    """Tests for diff computation."""

    def test_no_changes_empty_diff(self, test_root):
        """No changes should produce empty diff."""
        source = _make_source_repo(test_root, "no_diff", {"a.py": "x = 1"})
        workspace_base = test_root / "workspaces"
        workspace = prepare_workspace(source, workspace_base)

        diff = compute_diff(source, workspace)
        assert diff == ""

    def test_file_modified_produces_diff(self, test_root):
        """Modified file should produce non-empty diff."""
        source = _make_source_repo(test_root, "has_diff", {"a.py": "x = 1"})
        workspace_base = test_root / "workspaces"
        workspace = prepare_workspace(source, workspace_base)

        # Modify file in workspace
        (workspace / "a.py").write_text("x = 2", encoding="utf-8")

        diff = compute_diff(source, workspace)
        assert len(diff) > 0
        assert "a.py" in diff

    def test_new_file_produces_diff(self, test_root):
        """New file in workspace should produce diff."""
        source = _make_source_repo(test_root, "new_file", {"a.py": "x = 1"})
        workspace_base = test_root / "workspaces"
        workspace = prepare_workspace(source, workspace_base)

        # Add new file in workspace
        (workspace / "b.py").write_text("y = 2", encoding="utf-8")

        diff = compute_diff(source, workspace)
        assert len(diff) > 0
        assert "b.py" in diff

    def test_deleted_file_produces_diff(self, test_root):
        """Deleted files should appear in fallback diffs for non-git repos."""
        source = _make_source_repo(test_root, "deleted_file", {"a.py": "x = 1\n", "b.py": "y = 2\n"})
        workspace = test_root / "workspace_deleted_file"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "a.py").write_text("x = 1\n", encoding="utf-8")

        diff = compute_diff(source, workspace)
        assert len(diff) > 0
        assert "b.py" in diff


class TestComputeReward:
    """Tests for reward computation."""

    def test_verifier_passed_reward_1(self, test_root):
        """Full pass should give reward 1.0."""
        result = VerifyResult(passed=True, score=1.0)
        trajectory = Trajectory(task_id="t", repo="r", tool_profile_id="p")
        reward = compute_reward(result, "some patch", trajectory)
        assert reward == 1.0

    def test_verifier_failed_with_patch_reward_01(self, test_root):
        """Verifier failed but patch exists should give 0.1."""
        result = VerifyResult(passed=False, score=0.0)
        trajectory = Trajectory(task_id="t", repo="r", tool_profile_id="p")
        reward = compute_reward(result, "--- a/a.py\n+++ b/a.py\n", trajectory)
        assert reward == 0.1

    def test_verifier_failed_no_patch_reward_0(self, test_root):
        """Verifier failed and no patch should give 0.0."""
        result = VerifyResult(passed=False, score=0.0)
        trajectory = Trajectory(task_id="t", repo="r", tool_profile_id="p")
        reward = compute_reward(result, "", trajectory)
        assert reward == 0.0

    def test_verifier_failed_whitespace_only_patch_reward_0(self, test_root):
        """Whitespace-only patch should be treated as no patch."""
        result = VerifyResult(passed=False, score=0.0)
        trajectory = Trajectory(task_id="t", repo="r", tool_profile_id="p")
        reward = compute_reward(result, "   \n  \n", trajectory)
        assert reward == 0.0

    def test_verifier_passed_but_failed_status_reward_05(self, test_root):
        """A solved workspace with a failed run should get partial credit."""
        result = VerifyResult(passed=True, score=1.0)
        trajectory = Trajectory(
            task_id="t",
            repo="r",
            tool_profile_id="p",
            status=RunStatus.FAILED,
        )
        reward, reason = compute_reward_details(result, "--- a/a.py\n+++ b/a.py\n", trajectory)
        assert reward == 0.5
        assert reason == "verifier_passed_but_run_not_completed"

    def test_parse_error_reward_negative_02(self, test_root):
        """Parse errors should be penalized explicitly."""
        result = VerifyResult(passed=False, score=0.0)
        trajectory = Trajectory(
            task_id="t",
            repo="r",
            tool_profile_id="p",
            status=RunStatus.ERROR,
        )
        trajectory.metadata["stop_reason"] = "parse_error"
        reward, reason = compute_reward_details(result, "", trajectory)
        assert reward == -0.2
        assert reason == "parse_error"

    def test_timeout_reward_negative_05(self, test_root):
        """Timeouts should receive the strongest negative reward."""
        result = VerifyResult(
            passed=False,
            score=0.0,
            stderr="Test command timed out after 120s",
        )
        trajectory = Trajectory(
            task_id="t",
            repo="r",
            tool_profile_id="p",
            status=RunStatus.TIMEOUT,
        )
        reward, reason = compute_reward_details(result, "", trajectory)
        assert reward == -0.5
        assert reason == "timeout"

    def test_command_policy_reward_negative_05(self, test_root):
        """Forbidden command policy violations should be penalized."""
        result = VerifyResult(passed=False, score=0.0)
        trajectory = Trajectory(
            task_id="t",
            repo="r",
            tool_profile_id="p",
            status=RunStatus.FAILED,
        )
        call = ToolCall(id="c1", name="run_command", arguments={"command": "curl x"})
        tool_result = ToolResult(
            ok=False,
            content="Command rejected by policy",
            is_error=True,
            metadata={"error_type": "command_policy"},
        )
        trajectory.add_tool_observation(call, tool_result)
        reward, reason = compute_reward_details(result, "", trajectory)
        assert reward == -0.5
        assert reason == "forbidden_command"


class TestRunCodingTask:
    """Integration tests for the full coding task flow."""

    def test_full_flow_verifier_passing(self, test_root):
        """Full flow with passing verifier."""
        source = _make_source_repo(test_root, "full_pass", {
            "test_ok.py": "def test_ok():\n    assert True\n",
        })
        output_dir = test_root / "output_pass"

        task = _make_task(source, prompt="Run the tests")

        # Fake client just finishes immediately
        client = FakeLLMClient(responses=[
            """<assistant>
The tests should pass already.
</assistant>
<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Tests pass"}}
<|end|>"""
        ])

        trajectory = run_coding_task(task, client, output_dir)

        # Verify trajectory
        assert trajectory.task_id == "test_verify"
        assert trajectory.verifier is not None
        assert trajectory.verifier.passed
        assert trajectory.reward == 1.0

        # Verify artifacts on disk
        assert (output_dir / "trajectory.json").exists()
        assert (output_dir / "tool_profile.json").exists()
        assert (output_dir / "verifier.json").exists()
        assert (output_dir / "final.patch").exists()

        # Verify trajectory.json is valid
        traj_data = json.loads((output_dir / "trajectory.json").read_text(encoding="utf-8"))
        assert traj_data["task_id"] == "test_verify"

    def test_full_flow_verifier_failing(self, test_root):
        """Full flow with failing verifier."""
        source = _make_source_repo(test_root, "full_fail", {
            "test_bad.py": "def test_bad():\n    assert False\n",
        })
        output_dir = test_root / "output_fail"

        task = _make_task(source, prompt="Fix the failing test")

        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Can't fix"}}
<|end|>"""
        ])

        trajectory = run_coding_task(task, client, output_dir)

        assert trajectory.verifier is not None
        assert not trajectory.verifier.passed
        assert trajectory.status == RunStatus.FAILED
        assert trajectory.reward == 0.0  # No patch + failed

    def test_verifier_timeout_sets_timeout_status(self, test_root, monkeypatch):
        """Verifier timeouts should map to timeout run status."""
        source = _make_source_repo(test_root, "verifier_timeout", {
            "main.py": "print('hello')\n",
        })
        output_dir = test_root / "output_timeout"

        task = _make_task(source, prompt="Run the tests")
        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
        ])

        def _fake_run_verifier(task, workspace_root):
            return VerifyResult(
                passed=False,
                score=0.0,
                stdout="",
                stderr="Test command timed out after 1s",
            )

        monkeypatch.setattr(coding_env_module, "run_verifier", _fake_run_verifier)

        trajectory = run_coding_task(task, client, output_dir)

        assert trajectory.status == RunStatus.TIMEOUT
        assert trajectory.reward == -0.5
        assert trajectory.metadata["reward_reason"] == "timeout"

    def test_workspace_is_copy_not_original(self, test_root):
        """Agent should run on workspace copy, not on source repo."""
        source = _make_source_repo(test_root, "ws_copy", {
            "main.py": "x = 1\n",
        })
        output_dir = test_root / "output_ws_copy"

        task = _make_task(source, prompt="Read main.py")

        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"read_file","arguments":{"path":"main.py"}}
<|end|>""",
            """<|tool|>
{"id":"c2","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
        ])

        trajectory = run_coding_task(task, client, output_dir)

        # Source should be untouched
        assert (source / "main.py").read_text(encoding="utf-8") == "x = 1\n"
        # Workspace should exist under short workspace directory
        workspaces_dir = output_dir / "w"
        assert workspaces_dir.exists()
        # There should be a workspace with main.py
        workspace_dirs = list(workspaces_dir.iterdir())
        assert len(workspace_dirs) == 1
        assert (workspace_dirs[0] / "main.py").exists()

    def test_source_repo_not_found(self, test_root):
        """Should handle missing source repo gracefully."""
        output_dir = test_root / "output_missing"
        task = _make_task(
            test_root / "nonexistent_source",
            prompt="Test",
        )

        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
        ])

        trajectory = run_coding_task(task, client, output_dir)

        assert trajectory.status == RunStatus.ERROR
        assert "setup_error" in trajectory.metadata
        assert trajectory.reward == -0.2
        assert trajectory.metadata["failure_reason"] == "setup_error"

        # NS-04 rework: artifacts should still be written to disk
        assert (output_dir / "trajectory.json").exists()
        assert (output_dir / "tool_profile.json").exists()
        assert (output_dir / "verifier.json").exists()
        assert (output_dir / "final.patch").exists()

        # Verify trajectory.json has the error info
        traj_data = json.loads((output_dir / "trajectory.json").read_text(encoding="utf-8"))
        assert traj_data["status"] == "error"
        assert "setup_error" in traj_data["metadata"]

    def test_trajectory_repo_points_to_workspace(self, test_root):
        """trajectory.repo should point to workspace, not source repo."""
        source = _make_source_repo(test_root, "repo_check", {"main.py": "x = 1\n"})
        output_dir = test_root / "output_repo_check"

        task = _make_task(source, prompt="Test")

        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
        ])

        trajectory = run_coding_task(task, client, output_dir)

        # trajectory.repo should point to the actual workspace where agent ran
        # It should be under output_dir / "w" / <short uuid>
        workspaces_dir = output_dir / "w"
        assert workspaces_dir.exists()
        workspace_dirs = list(workspaces_dir.iterdir())
        assert len(workspace_dirs) == 1
        actual_workspace = workspace_dirs[0]
        # trajectory.repo should match the actual workspace path
        assert trajectory.repo == str(actual_workspace)

    def test_llm_error_still_persists_artifacts(self, test_root):
        """LLM provider failures should be captured as run artifacts."""
        source = _make_source_repo(test_root, "llm_error", {
            "test_ok.py": "def test_ok():\n    assert True\n",
        })
        output_dir = test_root / "output_llm_error"
        task = _make_task(source, prompt="Test provider failure")

        trajectory = run_coding_task(task, RaisingClient(), output_dir)

        assert trajectory.status == RunStatus.ERROR
        assert trajectory.metadata["llm_error_type"] == "RuntimeError"
        assert "provider disconnected" in trajectory.metadata["llm_error"]
        assert (output_dir / "trajectory.json").exists()
        assert (output_dir / "tool_profile.json").exists()
        assert (output_dir / "verifier.json").exists()
        assert (output_dir / "final.patch").exists()

    def test_artifacts_contain_verifier_info(self, test_root):
        """verifier.json should reflect actual test results."""
        source = _make_source_repo(test_root, "verif_info", {
            "test_simple.py": "def test_one():\n    assert 1 == 1\n",
        })
        output_dir = test_root / "output_verif"

        task = _make_task(source, prompt="Test")

        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"OK"}}
<|end|>"""
        ])

        run_coding_task(task, client, output_dir)

        verif_data = json.loads((output_dir / "verifier.json").read_text(encoding="utf-8"))
        assert verif_data["passed"] is True
        assert verif_data["score"] == 1.0

    def test_patch_with_file_modification(self, test_root):
        """Modified file should produce non-empty patch."""
        source = _make_source_repo(test_root, "patch_mod", {
            "calc.py": "def add(a, b):\n    return a - b  # bug\n",
            "test_calc.py": "from calc import add\ndef test_add():\n    assert add(1, 2) == 3\n",
        })
        output_dir = test_root / "output_patch"

        task = _make_task(source, prompt="Fix the add function")

        # First read, then modify, then finish
        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"read_file","arguments":{"path":"calc.py"}}
<|end|>""",
            """<assistant>
I need to fix the add function.
</assistant>
<|tool|>
{"id":"c2","name":"apply_patch","arguments":{"diff":"--- a/calc.py\\n+++ b/calc.py\\n@@ -1,2 +1,2 @@\\n def add(a, b):\\n-    return a - b  # bug\\n+    return a + b\\n"}}
<|end|>""",
            """<|tool|>
{"id":"c3","name":"finish","arguments":{"answer":"Fixed the add function"}}
<|end|>"""
        ])

        trajectory = run_coding_task(task, client, output_dir)

        # Should have a non-empty patch
        assert len(trajectory.final_diff) > 0
        assert "calc.py" in trajectory.final_diff
        # Patch file should exist on disk
        patch_content = (output_dir / "final.patch").read_text(encoding="utf-8")
        assert len(patch_content) > 0

    def test_reward_written_to_trajectory(self, test_root):
        """Reward should be written to trajectory after run."""
        source = _make_source_repo(test_root, "reward_traj", {
            "test_ok.py": "def test_ok():\n    assert True\n",
        })
        output_dir = test_root / "output_reward"

        task = _make_task(source, prompt="Test")
        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"OK"}}
<|end|>"""
        ])

        trajectory = run_coding_task(task, client, output_dir)

        # Reward should be set
        assert trajectory.reward == 1.0
        # And persisted in trajectory.json
        traj_data = json.loads((output_dir / "trajectory.json").read_text(encoding="utf-8"))
        assert traj_data["reward"] == 1.0


# Helper used by test_coding_env
def _make_task(repo_path: Path, prompt: str = "Test task") -> "CodingTask":
    from pycodeagent.env.task import CodingTask
    return CodingTask(
        task_id="test_verify",
        repo_path=repo_path,
        prompt=prompt,
        max_turns=5,
    )
