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
import shutil
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.rl.schema_following_dataset import read_schema_following_jsonl
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig
from pycodeagent.rl.train_dataset import TrainDataset
from pycodeagent.rl.training_prep import (
    prepare_runtime_observed_schema_following_training_input,
)
from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.testing import cleanup_test_path, make_request_test_dir
from pycodeagent.tools.bootstrap import build_builtin_registry
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
{"id":"c2","name":"apply_patch","arguments":{"diff":"--- a/calculator.py\\n+++ b/calculator.py\\n@@ -1,2 +1,2 @@\\n def add(a: int, b: int) -> int:\\n-    return a - b\\n+    return a + b\\n"}}
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


class TestStructuredToolLoopE2E:
    """End-to-end smoke for create/write/python_run tool flow."""

    def test_create_write_python_run_loop_passes(self, test_root):
        repo = test_root / "structured_repo"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "test_generated.py").write_text(
            "from generated import add_one\n\n"
            "def test_add_one():\n"
            "    assert add_one(1) == 2\n",
            encoding="utf-8",
        )
        task = CodingTask(
            task_id="structured_tool_loop",
            repo_path=repo,
            prompt="Create the missing generated.py implementation and verify it with pytest.",
            test_command="pytest -q -p no:cacheprovider",
            max_turns=6,
        )
        client = FakeLLMClient(
            responses=[
                """<|tool|>
{"id":"c1","name":"create_file","arguments":{"path":"generated.py","content":""}}
<|end|>""",
                """<|tool|>
{"id":"c2","name":"write_file","arguments":{"path":"generated.py","content":"def add_one(x):\\n    return x + 1\\n"}}
<|end|>""",
                """<|tool|>
{"id":"c3","name":"python_run","arguments":{"target":"pytest","run_as_module":true,"args":["-q","-p","no:cacheprovider","test_generated.py"]}}
<|end|>""",
                """<|tool|>
{"id":"c4","name":"finish","arguments":{"answer":"Created generated.py and verified the test passes."}}
<|end|>""",
            ]
        )
        output_dir = test_root / "structured_output"

        trajectory = run_coding_task(task, client, output_dir)

        assert trajectory.status != RunStatus.ERROR, trajectory.metadata
        assert trajectory.verifier is not None
        assert trajectory.verifier.passed, trajectory.verifier.stderr
        assert trajectory.reward == 1.0

        tool_names = [call.name for call in trajectory.tool_calls]
        assert tool_names == ["create_file", "write_file", "python_run", "finish"]

        workspaces_dir = output_dir / "w"
        workspace_dirs = list(workspaces_dir.iterdir())
        assert len(workspace_dirs) == 1
        workspace = workspace_dirs[0]
        generated = workspace / "generated.py"
        assert generated.exists()
        assert generated.read_text(encoding="utf-8") == "def add_one(x):\n    return x + 1\n"

        traj_data = json.loads((output_dir / "trajectory.json").read_text(encoding="utf-8"))
        assert traj_data["status"] == "completed"
        assert [call["name"] for call in traj_data["tool_calls"]] == tool_names

    def test_patch_first_python_run_loop_preserves_traceable_metadata(self, test_root):
        repo = test_root / "patch_loop_repo"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "calculator.py").write_text(
            "def add(a, b):\n    return a - b\n",
            encoding="utf-8",
        )
        (repo / "test_calculator.py").write_text(
            "from calculator import add\n\n"
            "def test_add():\n"
            "    assert add(1, 2) == 3\n",
            encoding="utf-8",
        )
        task = CodingTask(
            task_id="patch_first_python_run_loop",
            repo_path=repo,
            prompt="Read calculator.py, patch the bug, run pytest, and then finish.",
            test_command="pytest -q -p no:cacheprovider",
            max_turns=6,
        )
        client = FakeLLMClient(
            responses=[
                """<|tool|>
{"id":"c1","name":"read_file","arguments":{"path":"calculator.py"}}
<|end|>""",
                """<|tool|>
{"id":"c2","name":"apply_patch","arguments":{"diff":"--- a/calculator.py\\n+++ b/calculator.py\\n@@ -1,2 +1,2 @@\\n def add(a, b):\\n-    return a - b\\n+    return a + b\\n"}}
<|end|>""",
                """<|tool|>
{"id":"c3","name":"python_run","arguments":{"target":"pytest","run_as_module":true,"args":["-q","-p","no:cacheprovider","test_calculator.py"]}}
<|end|>""",
                """<|tool|>
{"id":"c4","name":"finish","arguments":{"answer":"Fixed calculator.py and verified pytest passes."}}
<|end|>""",
            ]
        )
        output_dir = test_root / "patch_loop_output"

        trajectory = run_coding_task(task, client, output_dir)

        assert trajectory.status == RunStatus.COMPLETED, trajectory.metadata
        assert trajectory.verifier is not None
        assert trajectory.verifier.passed, trajectory.verifier.stderr
        assert trajectory.reward == 1.0
        assert [call.name for call in trajectory.tool_calls] == [
            "read_file",
            "apply_patch",
            "python_run",
            "finish",
        ]

        workspace = next((output_dir / "w").iterdir())
        assert (workspace / "calculator.py").read_text(encoding="utf-8") == (
            "def add(a, b):\n    return a + b\n"
        )

        runtime_events = [
            json.loads(line)
            for line in (output_dir / "runtime_trace.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        patch_execution = next(
            event
            for event in runtime_events
            if event["event_kind"] == "tool_execution_completed" and event["tool_call_id"] == "c2"
        )
        patch_payload = None
        for payload_ref in patch_execution["payload_refs"]:
            if payload_ref["kind"] == "tool_result":
                patch_payload = json.loads(
                    (output_dir / payload_ref["path"]).read_text(encoding="utf-8")
                )
        assert patch_payload is not None
        assert patch_payload["metadata"]["operation"] == "apply_patch"
        assert patch_payload["metadata"]["file_operations"] == [
            {"path": "calculator.py", "operation": "modify", "hunks_applied": 1}
        ]

        python_execution = next(
            event
            for event in runtime_events
            if event["event_kind"] == "tool_execution_completed" and event["tool_call_id"] == "c3"
        )
        python_payload = None
        for payload_ref in python_execution["payload_refs"]:
            if payload_ref["kind"] == "tool_result":
                python_payload = json.loads(
                    (output_dir / payload_ref["path"]).read_text(encoding="utf-8")
                )
        assert python_payload is not None
        assert python_payload["metadata"]["operation"] == "python_run"
        assert python_payload["metadata"]["execution_kind"] == "pytest_module"
        assert python_payload["metadata"]["target_kind"] == "module"

    def test_blocked_command_then_structured_recovery_still_completes(self, test_root):
        repo = test_root / "blocked_command_recovery_repo"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "test_generated.py").write_text(
            "from generated import add_one\n\n"
            "def test_add_one():\n"
            "    assert add_one(1) == 2\n",
            encoding="utf-8",
        )
        task = CodingTask(
            task_id="blocked_command_then_structured_recovery",
            repo_path=repo,
            prompt="Try a command if needed, but recover with structured tools and finish only after validation passes.",
            test_command="pytest -q -p no:cacheprovider",
            max_turns=7,
        )
        client = FakeLLMClient(
            responses=[
                """<|tool|>
{"id":"c1","name":"run_command","arguments":{"command":"python generated.py"}}
<|end|>""",
                """<|tool|>
{"id":"c2","name":"create_file","arguments":{"path":"generated.py","content":"def add_one(x):\\n    return x + 1\\n"}}
<|end|>""",
                """<|tool|>
{"id":"c3","name":"python_run","arguments":{"target":"pytest","run_as_module":true,"args":["-q","-p","no:cacheprovider","test_generated.py"]}}
<|end|>""",
                """<|tool|>
{"id":"c4","name":"finish","arguments":{"answer":"Recovered from blocked command and verified the structured fix."}}
<|end|>""",
            ]
        )
        output_dir = test_root / "blocked_command_recovery_output"

        trajectory = run_coding_task(task, client, output_dir)

        assert trajectory.status == RunStatus.COMPLETED, trajectory.metadata
        assert trajectory.verifier is not None
        assert trajectory.verifier.passed, trajectory.verifier.stderr
        assert trajectory.reward == 1.0
        assert [call.name for call in trajectory.tool_calls] == [
            "run_command",
            "create_file",
            "python_run",
            "finish",
        ]

        first_result = trajectory.observations[0].result
        assert first_result.is_error
        assert first_result.metadata["error_type"] == "command_policy"
        assert first_result.metadata["policy_domain"] == "command"
        assert first_result.metadata["policy_decision"] == "deny"

        runtime_events = [
            json.loads(line)
            for line in (output_dir / "runtime_trace.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        blocked_execution = next(
            event
            for event in runtime_events
            if event["event_kind"] == "tool_execution_failed" and event["tool_call_id"] == "c1"
        )
        assert blocked_execution["data"]["canonical_tool_name"] == "run_command"
        assert blocked_execution["data"]["error_type"] == "command_policy"

    def test_revise_after_failed_python_run_requires_recovery_before_finish(self, test_root):
        """A failed test run should require revision before finish can stop the runtime."""
        repo = test_root / "revise_loop_repo"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "test_generated.py").write_text(
            "from generated import add_one\n\n"
            "def test_add_one():\n"
            "    assert add_one(1) == 2\n",
            encoding="utf-8",
        )
        task = CodingTask(
            task_id="revise_after_failed_python_run",
            repo_path=repo,
            prompt=(
                "Create generated.py, run the test, fix any failure you see, "
                "rerun the test, and then finish."
            ),
            test_command="pytest -q -p no:cacheprovider",
            max_turns=8,
        )
        client = FakeLLMClient(
            responses=[
                """<|tool|>
{"id":"c1","name":"create_file","arguments":{"path":"generated.py","content":"def add_one(x):\\n    return x + 2\\n"}}
<|end|>""",
                """<|tool|>
{"id":"c2","name":"python_run","arguments":{"target":"pytest","run_as_module":true,"args":["-q","-p","no:cacheprovider","test_generated.py"]}}
<|end|>""",
                """<|tool|>
{"id":"c3","name":"finish","arguments":{"answer":"Done"}}
<|end|>""",
                """<|tool|>
{"id":"c4","name":"write_file","arguments":{"path":"generated.py","content":"def add_one(x):\\n    return x + 1\\n"}}
<|end|>""",
                """<|tool|>
{"id":"c5","name":"python_run","arguments":{"target":"pytest","run_as_module":true,"args":["-q","-p","no:cacheprovider","test_generated.py"]}}
<|end|>""",
                """<|tool|>
{"id":"c6","name":"finish","arguments":{"answer":"Created generated.py, fixed the failing implementation, and verified the test passes."}}
<|end|>""",
            ]
        )
        output_dir = test_root / "revise_loop_output"

        trajectory = run_coding_task(task, client, output_dir)

        assert trajectory.status == RunStatus.COMPLETED, trajectory.metadata
        assert trajectory.verifier is not None
        assert trajectory.verifier.passed, trajectory.verifier.stderr
        assert trajectory.reward == 1.0
        assert [call.name for call in trajectory.tool_calls] == [
            "create_file",
            "python_run",
            "finish",
            "write_file",
            "python_run",
            "finish",
        ]

        first_test_result = trajectory.observations[1].result
        assert first_test_result.ok is False
        assert "exit_code" in first_test_result.metadata

        workspaces_dir = output_dir / "w"
        workspace = next(workspaces_dir.iterdir())
        generated = workspace / "generated.py"
        assert generated.read_text(encoding="utf-8") == "def add_one(x):\n    return x + 1\n"

        runtime_events = [
            json.loads(line)
            for line in (output_dir / "runtime_trace.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        deferred_finish_event = next(
            event
            for event in runtime_events
            if event["event_kind"] == "turn_stop_decision"
            and event["turn_index"] == 3
        )
        assert deferred_finish_event["data"]["should_stop"] is False
        assert deferred_finish_event["data"]["decision_code"] == "defer_finish_pending_issue"
        assert deferred_finish_event["data"]["continue_reason"] == "defer_completion_pending_issue"
        assert deferred_finish_event["data"]["pending_issue_kind"] == "validation_failure"
        assert "Completion deferred" in deferred_finish_event["data"]["detail"]

    def test_profile_mode_entry_runs_sampled_read_then_finish(self, test_root):
        """Formal runtime profile_mode entry should support sampled tool views."""
        repo = test_root / "sampled_profile_repo"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
        (repo / "test_ok.py").write_text(
            "def test_ok():\n    assert True\n",
            encoding="utf-8",
        )
        task = CodingTask(
            task_id="sampled_profile_mode_loop",
            repo_path=repo,
            prompt="Read main.py and finish.",
            test_command="pytest -q -p no:cacheprovider",
            max_turns=4,
        )
        registry = build_builtin_registry()
        profile = ToolProfileSampler(seed=0).sample("name_description_schema")
        read_call = profile.project_canonical_call(
            "read_file",
            {"path": "main.py"},
            call_id="c1",
            canonical_tool=registry.get("read_file"),
        )
        finish_call = profile.project_canonical_call(
            "finish",
            {"answer": "Done"},
            call_id="c2",
            canonical_tool=registry.get("finish"),
        )
        client = FakeLLMClient(
            responses=[
                (
                    "<|tool|>\n"
                    + json.dumps(
                        {
                            "id": read_call.call_id,
                            "name": read_call.name,
                            "arguments": read_call.arguments,
                        },
                        ensure_ascii=False,
                    )
                    + "\n<|end|>"
                ),
                (
                    "<|tool|>\n"
                    + json.dumps(
                        {
                            "id": finish_call.call_id,
                            "name": finish_call.name,
                            "arguments": finish_call.arguments,
                        },
                        ensure_ascii=False,
                    )
                    + "\n<|end|>"
                ),
            ]
        )
        output_dir = test_root / "sampled_profile_output"

        trajectory = run_coding_task(
            task,
            client,
            output_dir,
            profile_mode="name_description_schema",
            profile_seed=0,
        )

        assert trajectory.status != RunStatus.ERROR, trajectory.metadata
        assert trajectory.verifier is not None
        assert trajectory.verifier.passed, trajectory.verifier.stderr
        assert trajectory.tool_profile_id == profile.profile_id
        assert [call.name for call in trajectory.tool_calls] == [
            read_call.name,
            finish_call.name,
        ]

        tool_profile = json.loads((output_dir / "tool_profile.json").read_text(encoding="utf-8"))
        assert tool_profile["metadata"]["mode"] == "name_description_schema"
        assert tool_profile["metadata"]["seed"] == 0

    def test_multi_profile_runtime_smoke_preserves_exposed_to_canonical_mapping(self, test_root):
        """The same canonical intent should run under all supported profile modes."""
        repo = test_root / "multi_profile_repo"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
        (repo / "test_ok.py").write_text(
            "def test_ok():\n    assert True\n",
            encoding="utf-8",
        )
        registry = build_builtin_registry()
        supported_modes = [
            "base",
            "name_only",
            "description_only",
            "argument_rename",
            "schema_flat_to_nested",
            "tool_reorder",
            "schema_only",
            "name_description_schema",
        ]

        for mode in supported_modes:
            task = CodingTask(
                task_id=f"multi_profile_{mode}",
                repo_path=repo,
                prompt="Read main.py and finish.",
                test_command="pytest -q -p no:cacheprovider",
                max_turns=4,
            )
            profile = ToolProfileSampler(seed=0).sample(mode)
            read_call = profile.project_canonical_call(
                "read_file",
                {"path": "main.py"},
                call_id="c1",
                canonical_tool=registry.get("read_file"),
            )
            finish_call = profile.project_canonical_call(
                "finish",
                {"answer": "Done"},
                call_id="c2",
                canonical_tool=registry.get("finish"),
            )
            client = FakeLLMClient(
                responses=[
                    (
                        "<|tool|>\n"
                        + json.dumps(
                            {
                                "id": read_call.call_id,
                                "name": read_call.name,
                                "arguments": read_call.arguments,
                            },
                            ensure_ascii=False,
                        )
                        + "\n<|end|>"
                    ),
                    (
                        "<|tool|>\n"
                        + json.dumps(
                            {
                                "id": finish_call.call_id,
                                "name": finish_call.name,
                                "arguments": finish_call.arguments,
                            },
                            ensure_ascii=False,
                        )
                        + "\n<|end|>"
                    ),
                ]
            )
            output_dir = test_root / f"multi_profile_output_{mode}"

            trajectory = run_coding_task(
                task,
                client,
                output_dir,
                profile_mode=mode,
                profile_seed=0,
            )

            assert trajectory.status != RunStatus.ERROR, (mode, trajectory.metadata)
            assert trajectory.verifier is not None
            assert trajectory.verifier.passed, (mode, trajectory.verifier.stderr)
            assert trajectory.tool_profile_id == profile.profile_id
            assert [call.name for call in trajectory.tool_calls] == [
                read_call.name,
                finish_call.name,
            ]

            tool_profile = json.loads(
                (output_dir / "tool_profile.json").read_text(encoding="utf-8")
            )
            assert tool_profile["profile_id"] == profile.profile_id
            assert tool_profile["metadata"]["mode"] == mode
            assert tool_profile["metadata"]["seed"] == 0
            assert "mutation_axes" in tool_profile["metadata"]

            runtime_events = [
                json.loads(line)
                for line in (output_dir / "runtime_trace.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            tool_profile_event = next(
                event for event in runtime_events if event["event_kind"] == "tool_profile_exposed"
            )
            assert tool_profile_event["data"]["tool_order"] == [
                tool.exposed_name for tool in profile.tools
            ]
            assert tool_profile_event["data"]["mutation_axes"] == tool_profile["metadata"]["mutation_axes"]
            assert tool_profile_event["data"]["compat_mode"] == tool_profile["metadata"]["compat_mode"]
            assert tool_profile_event["data"]["schema_variant_categories"] == tool_profile["metadata"]["schema_variant_categories"]

            mapping_events = [
                event for event in runtime_events if event["event_kind"] == "tool_call_mapping_completed"
            ]
            read_mapping = next(event for event in mapping_events if event["tool_call_id"] == "c1")
            finish_mapping = next(event for event in mapping_events if event["tool_call_id"] == "c2")
            assert read_mapping["data"]["exposed_tool_name"] == read_call.name
            assert read_mapping["data"]["canonical_tool_name"] == "read_file"
            assert finish_mapping["data"]["exposed_tool_name"] == finish_call.name
            assert finish_mapping["data"]["canonical_tool_name"] == "finish"

    def test_deep_toolview_modes_support_read_write_python_run_bugfix_loop(self, test_root):
        """Deep mutation modes should support a realistic short bugfix loop."""
        repo = test_root / "deep_toolview_repo"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "calculator.py").write_text(
            "def add(a, b):\n    return a - b\n",
            encoding="utf-8",
        )
        (repo / "test_calculator.py").write_text(
            "from calculator import add\n\n"
            "def test_add():\n"
            "    assert add(1, 2) == 3\n",
            encoding="utf-8",
        )
        registry = build_builtin_registry()

        for mode in ["argument_rename", "schema_flat_to_nested", "tool_reorder"]:
            task = CodingTask(
                task_id=f"deep_toolview_{mode}",
                repo_path=repo,
                prompt="Read calculator.py, fix it, run pytest, and then finish.",
                test_command="pytest -q -p no:cacheprovider",
                max_turns=6,
            )
            profile = ToolProfileSampler(seed=0).sample(mode)
            read_call = profile.project_canonical_call(
                "read_file",
                {"path": "calculator.py"},
                call_id="c1",
                canonical_tool=registry.get("read_file"),
            )
            write_call = profile.project_canonical_call(
                "write_file",
                {"path": "calculator.py", "content": "def add(a, b):\n    return a + b\n"},
                call_id="c2",
                canonical_tool=registry.get("write_file"),
            )
            python_call = profile.project_canonical_call(
                "python_run",
                {
                    "target": "pytest",
                    "run_as_module": True,
                    "args": ["-q", "-p", "no:cacheprovider", "test_calculator.py"],
                },
                call_id="c3",
                canonical_tool=registry.get("python_run"),
            )
            finish_call = profile.project_canonical_call(
                "finish",
                {"answer": "Done"},
                call_id="c4",
                canonical_tool=registry.get("finish"),
            )
            client = FakeLLMClient(
                responses=[
                    (
                        "<|tool|>\n"
                        + json.dumps(
                            {
                                "id": read_call.call_id,
                                "name": read_call.name,
                                "arguments": read_call.arguments,
                            },
                            ensure_ascii=False,
                        )
                        + "\n<|end|>"
                    ),
                    (
                        "<|tool|>\n"
                        + json.dumps(
                            {
                                "id": write_call.call_id,
                                "name": write_call.name,
                                "arguments": write_call.arguments,
                            },
                            ensure_ascii=False,
                        )
                        + "\n<|end|>"
                    ),
                    (
                        "<|tool|>\n"
                        + json.dumps(
                            {
                                "id": python_call.call_id,
                                "name": python_call.name,
                                "arguments": python_call.arguments,
                            },
                            ensure_ascii=False,
                        )
                        + "\n<|end|>"
                    ),
                    (
                        "<|tool|>\n"
                        + json.dumps(
                            {
                                "id": finish_call.call_id,
                                "name": finish_call.name,
                                "arguments": finish_call.arguments,
                            },
                            ensure_ascii=False,
                        )
                        + "\n<|end|>"
                    ),
                ]
            )
            output_dir = test_root / f"deep_toolview_output_{mode}"

            trajectory = run_coding_task(
                task,
                client,
                output_dir,
                profile_mode=mode,
                profile_seed=0,
            )

            assert trajectory.status == RunStatus.COMPLETED, (mode, trajectory.metadata)
            assert trajectory.verifier is not None
            assert trajectory.verifier.passed, (mode, trajectory.verifier.stderr)
            assert [call.name for call in trajectory.tool_calls] == [
                read_call.name,
                write_call.name,
                python_call.name,
                finish_call.name,
            ]

            workspace = next((output_dir / "w").iterdir())
            assert (workspace / "calculator.py").read_text(encoding="utf-8") == (
                "def add(a, b):\n    return a + b\n"
            )

            tool_profile = json.loads(
                (output_dir / "tool_profile.json").read_text(encoding="utf-8")
            )
            assert tool_profile["metadata"]["reorder_anchor_policy"] == "finish_last"
            assert "selected_variant_ids" in tool_profile["metadata"]

            runtime_events = [
                json.loads(line)
                for line in (output_dir / "runtime_trace.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            tool_profile_event = next(
                event for event in runtime_events if event["event_kind"] == "tool_profile_exposed"
            )
            assert tool_profile_event["data"]["selected_variant_ids"] == tool_profile["metadata"]["selected_variant_ids"]

            mapping_events = [
                event for event in runtime_events if event["event_kind"] == "tool_call_mapping_completed"
            ]
            assert next(event for event in mapping_events if event["tool_call_id"] == "c2")["data"]["canonical_tool_name"] == "write_file"
            assert next(event for event in mapping_events if event["tool_call_id"] == "c3")["data"]["canonical_tool_name"] == "python_run"

    def test_runtime_observed_training_prep_smoke_preserves_mutated_target_call(self, test_root):
        """A sampled local runtime run should export observed ToolView samples end-to-end."""
        repo = test_root / "runtime_observed_repo"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
        (repo / "test_ok.py").write_text(
            "def test_ok():\n    assert True\n",
            encoding="utf-8",
        )
        task = CodingTask(
            task_id="runtime_observed_smoke",
            repo_path=repo,
            prompt="Read main.py and finish.",
            test_command="pytest -q -p no:cacheprovider",
            max_turns=4,
        )
        registry = build_builtin_registry()
        profile = ToolProfileSampler(seed=0).sample("name_description_schema")
        read_call = profile.project_canonical_call(
            "read_file",
            {"path": "main.py"},
            call_id="c1",
            canonical_tool=registry.get("read_file"),
        )
        finish_call = profile.project_canonical_call(
            "finish",
            {"answer": "Done"},
            call_id="c2",
            canonical_tool=registry.get("finish"),
        )
        client = FakeLLMClient(
            responses=[
                (
                    "<|tool|>\n"
                    + json.dumps(
                        {
                            "id": read_call.call_id,
                            "name": read_call.name,
                            "arguments": read_call.arguments,
                        },
                        ensure_ascii=False,
                    )
                    + "\n<|end|>"
                ),
                (
                    "<|tool|>\n"
                    + json.dumps(
                        {
                            "id": finish_call.call_id,
                            "name": finish_call.name,
                            "arguments": finish_call.arguments,
                        },
                        ensure_ascii=False,
                    )
                    + "\n<|end|>"
                ),
            ]
        )
        batch_root = test_root / "runtime_observed_batch"
        output_dir = test_root / "runtime_observed_output"

        trajectory = run_coding_task(
            task,
            client,
            output_dir,
            profile_mode="name_description_schema",
            profile_seed=0,
        )

        assert trajectory.status != RunStatus.ERROR, trajectory.metadata
        assert trajectory.verifier is not None
        assert trajectory.verifier.passed, trajectory.verifier.stderr
        assert (output_dir / "trajectory.json").exists()
        assert (output_dir / "tool_profile.json").exists()
        assert (output_dir / "runtime_trace.jsonl").exists()

        batch_run_dir = batch_root / f"{task.task_id}__{profile.profile_id}"
        shutil.copytree(output_dir, batch_run_dir)

        prepared_dir = test_root / "runtime_observed_prepared"
        recommendation = prepare_runtime_observed_schema_following_training_input(
            batch_root,
            prepared_dir,
            source_type="batch",
            fake_tokenizer_config=FakeTokenizerConfig(),
            max_length=2048,
            run_id="runtime_observed_smoke_train",
        )

        assert recommendation.contract_ok is True
        raw_samples = read_schema_following_jsonl(prepared_dir / "raw_dataset" / "train.jsonl")
        tokenized_dataset = TrainDataset.from_jsonl(prepared_dir / "prepared" / "tokenized.jsonl")
        read_sample = next(
            sample for sample in raw_samples if sample.canonical_intent.tool == "read_file"
        )

        assert read_sample.target_tool_call.name == read_call.name
        assert read_sample.target_tool_call.name != "read_file"
        assert read_sample.canonical_intent.tool == "read_file"
        assert read_sample.metadata["source_profile_mode"] == "name_description_schema"
        assert len(tokenized_dataset) == recommendation.tokenized_example_count
