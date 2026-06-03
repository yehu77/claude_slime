"""End-to-end smoke test for the main coding agent pipeline.

This test verifies that the entire pipeline works end-to-end:
1. Workspace preparation (copy from toy repo)
2. Agent execution with fake LLM
3. File read / patch apply / finish
4. Verifier execution
5. Reward computation
6. Artifact persistence
7. Source repo isolation
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.testing import cleanup_test_path, make_request_test_dir
from pycodeagent.trajectory.schema import RunStatus


pytestmark = [pytest.mark.slow, pytest.mark.integration]


# Path to the toy repo (relative to project root)
_PROJECT_ROOT = Path(__file__).parent.parent
_TOY_REPO_PATH = _PROJECT_ROOT / "examples" / "buggy_calculator"
_TASK_DATA_PATH = _PROJECT_ROOT / "datasets" / "tasks" / "toy_tasks.jsonl"


def _get_test_root(request: pytest.FixtureRequest) -> Path:
    """Get a unique test root directory for the current test."""
    return make_request_test_dir("e2e_smoke", request)


@pytest.fixture
def test_root(request: pytest.FixtureRequest):
    """Create a clean isolated test directory for each test."""
    root = _get_test_root(request)
    yield root
    cleanup_test_path(root)


def _load_toy_task() -> CodingTask:
    """Load the toy task from JSONL file."""
    with open(_TASK_DATA_PATH, encoding="utf-8") as f:
        line = f.readline().strip()
        data = json.loads(line)

    # Convert repo_path to absolute path
    repo_path = _PROJECT_ROOT / data["repo_path"]

    return CodingTask(
        task_id=data["task_id"],
        repo_path=repo_path,
        prompt=data["prompt"],
        test_command=data["test_command"],
        max_turns=data["max_turns"],
        allowed_files=data.get("allowed_files", []),
        forbidden_files=data.get("forbidden_files", []),
        metadata=data.get("metadata", {}),
    )


def _make_fake_client_responses() -> list[str]:
    """Create the fake LLM response sequence for fixing the bug.

    The sequence is:
    1. read_file("calculator.py") - read the buggy source
    2. apply_patch(...) - fix the bug (change - to +)
    3. finish(...) - complete the task
    """
    return [
        # Step 1: Read the buggy file
        """<|tool|>
{"id":"c1","name":"read_file","arguments":{"path":"calculator.py"}}
<|end|>""",
        # Step 2: Apply the fix patch
        """<assistant>
I see the bug: the add function uses subtraction instead of addition. I'll fix it.
</assistant>
<|tool|>
{"id":"c2","name":"apply_patch","arguments":{"diff":"--- a/calculator.py\\n+++ b/calculator.py\\n@@ -1,3 +1,3 @@\\n def add(a: int, b: int) -> int:\\n-    return a - b\\n+    return a + b\\n"}}
<|end|>""",
        # Step 3: Finish the task
        """<|tool|>
{"id":"c3","name":"finish","arguments":{"answer":"Fixed the add function by changing subtraction to addition."}}
<|end|>""",
    ]


class TestBuggyCalculatorE2E:
    """End-to-end test for the buggy calculator toy example."""

    def test_buggy_calculator_e2e_passes(self, test_root):
        """Full e2e test: fake LLM fixes the bug, verifier passes, artifacts saved."""
        # Load task
        task = _load_toy_task()

        # Verify toy repo exists and has the expected bug
        assert _TOY_REPO_PATH.exists(), f"Toy repo not found: {_TOY_REPO_PATH}"
        calculator_src = _TOY_REPO_PATH / "calculator.py"
        assert calculator_src.exists()
        original_content = calculator_src.read_text(encoding="utf-8")
        assert "return a - b" in original_content, "Toy repo should have the bug"

        # Create output directory
        output_dir = test_root / "output"

        # Create fake client with deterministic responses
        responses = _make_fake_client_responses()
        client = FakeLLMClient(responses=responses)

        # Run the coding task
        trajectory = run_coding_task(task, client, output_dir)

        # === Assertions ===

        # 1. Trajectory status is not error
        assert trajectory.status != RunStatus.ERROR, f"Trajectory error: {trajectory.metadata}"

        # 2. Verifier passed
        assert trajectory.verifier is not None, "Verifier result should be set"
        assert trajectory.verifier.passed, f"Verifier should pass. stdout={trajectory.verifier.stdout}, stderr={trajectory.verifier.stderr}"

        # 3. Reward is 1.0
        assert trajectory.reward == 1.0, f"Reward should be 1.0 for passing verifier, got {trajectory.reward}"

        # 4. Patch is non-empty
        assert len(trajectory.final_diff) > 0, "Final diff should be non-empty"
        assert "calculator.py" in trajectory.final_diff, "Patch should mention calculator.py"

        # 5. trajectory.repo points to workspace, not source repo
        assert trajectory.repo != str(task.repo_path), "trajectory.repo should not be source repo"
        workspaces_dir = output_dir / "w"
        assert workspaces_dir.exists(), "workspace directory should exist"

        # 6. Artifacts exist on disk
        assert (output_dir / "trajectory.json").exists(), "trajectory.json should exist"
        assert (output_dir / "verifier.json").exists(), "verifier.json should exist"
        assert (output_dir / "tool_profile.json").exists(), "tool_profile.json should exist"
        assert (output_dir / "final.patch").exists(), "final.patch should exist"

        # 7. Verify artifact contents
        traj_data = json.loads((output_dir / "trajectory.json").read_text(encoding="utf-8"))
        assert traj_data["task_id"] == "buggy_calculator_001"
        assert traj_data["reward"] == 1.0
        assert traj_data["status"] == "completed"

        verif_data = json.loads((output_dir / "verifier.json").read_text(encoding="utf-8"))
        assert verif_data["passed"] is True
        assert verif_data["score"] == 1.0

        # 8. Source repo is NOT polluted
        current_source_content = calculator_src.read_text(encoding="utf-8")
        assert current_source_content == original_content, "Source repo should not be modified"
        assert "return a - b" in current_source_content, "Bug should still exist in source repo"

        # 9. Workspace has the fix
        workspace_dirs = list(workspaces_dir.iterdir())
        assert len(workspace_dirs) == 1, "Should have exactly one workspace"
        workspace = workspace_dirs[0]
        workspace_calculator = workspace / "calculator.py"
        assert workspace_calculator.exists(), "calculator.py should exist in workspace"
        workspace_content = workspace_calculator.read_text(encoding="utf-8")
        # The add function should now use + (the fix)
        assert "return a + b" in workspace_content, "Bug should be fixed in workspace (add function)"
        # The add function should no longer have the bug (check specific pattern)
        # Note: subtract function still uses a - b, which is correct
        lines = workspace_content.splitlines()
        add_line_idx = None
        for i, line in enumerate(lines):
            if "def add" in line:
                add_line_idx = i
                break
        assert add_line_idx is not None, "add function should exist"
        # The return statement after add should be a + b, not a - b
        for j in range(add_line_idx + 1, min(add_line_idx + 5, len(lines))):
            if "return" in lines[j]:
                assert "+" in lines[j], f"add function's return should use +, got: {lines[j]}"
                break

    def test_toy_repo_tests_fail_before_fix(self, test_root):
        """Verify that the toy repo tests actually fail before any fix.

        Runs in an independent copy of the toy repo to avoid polluting
        the source repo with .pytest_cache / __pycache__ artifacts.
        """
        import subprocess

        # Copy toy repo to an isolated location
        isolated_repo = test_root / "toy_repo_copy"
        shutil.copytree(_TOY_REPO_PATH, isolated_repo)

        result = subprocess.run(
            ["pytest", "-q", "-p", "no:cacheprovider"],
            cwd=isolated_repo,
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Tests should fail
        assert result.returncode != 0, "Toy repo tests should fail before fix"
        assert "failed" in result.stdout.lower() or "failed" in result.stderr.lower()

    def test_setup_copy_failure_returns_error_trajectory(self, test_root):
        """When workspace copy fails, run_coding_task should return error trajectory with artifacts."""
        # Create a task pointing to a repo that will cause copy to fail
        # Use a path that exists but contains locked/invalid files
        # Simplest: point to a non-existent repo (triggers ValueError in prepare_workspace)
        import subprocess

        from pycodeagent.env.coding_env import prepare_workspace

        bad_repo = test_root / "nonexistent_repo"
        output_dir = test_root / "output_bad"
        task = CodingTask(
            task_id="test_setup_fail",
            repo_path=bad_repo,
            prompt="Test",
            max_turns=5,
        )

        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
        ])

        trajectory = run_coding_task(task, client, output_dir)

        # Should get error trajectory, not an unhandled exception
        assert trajectory.status == RunStatus.ERROR
        assert "setup_error" in trajectory.metadata

        # Artifacts should still be persisted
        assert (output_dir / "trajectory.json").exists()
        assert (output_dir / "verifier.json").exists()
        assert (output_dir / "final.patch").exists()
