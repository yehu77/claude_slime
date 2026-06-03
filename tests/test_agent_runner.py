"""Tests for the agent runner.

Covers:
- Running with fake client
- Assistant turns recorded in trajectory
- Tool calls executed
- Tool observations recorded
- Finish tool ends the run
- Parser failure handling
- Max turns stopping
- Integration with bootstrap from NS-02
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient
from pycodeagent.agent.runner import AgentRunner, run_agent_task
from pycodeagent.agent.stopping import StopReason
from pycodeagent.env.task import CodingTask
from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.testing import cleanup_test_path, get_managed_test_root, reset_test_root
from pycodeagent.tools.bootstrap import build_base_tool_runtime
from pycodeagent.tools.context import ToolContext
from pycodeagent.trajectory.schema import Role, RunStatus


# ---------------------------------------------------------------------------
# Test workspace setup
# ---------------------------------------------------------------------------

_TEST_WORKSPACE_NAMESPACE = "agent_runner"


@pytest.fixture(autouse=True)
def _clean_test_workspace():
    """Ensure a clean test workspace dir before/after each test."""
    reset_test_root(_TEST_WORKSPACE_NAMESPACE)
    yield
    cleanup_test_path(get_managed_test_root(_TEST_WORKSPACE_NAMESPACE))


def _make_workspace(suffix: str = "", files: dict[str, str] | None = None) -> Path:
    """Create a workspace directory with optional files."""
    workspace = get_managed_test_root(_TEST_WORKSPACE_NAMESPACE) / f"ws_{suffix}"
    workspace.mkdir(parents=True, exist_ok=True)
    if files:
        for rel, content in files.items():
            p = workspace / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
    return workspace


def _make_task(workspace: Path, prompt: str = "Test task") -> CodingTask:
    """Create a minimal CodingTask for testing."""
    return CodingTask(
        task_id="test_task",
        repo_path=workspace,
        prompt=prompt,
        max_turns=5,
    )


class RaisingClient:
    """LLM client that simulates a provider failure."""

    def generate(self, request):
        raise RuntimeError("provider disconnected")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunWithFakeClient:
    """Tests using FakeLLMClient for deterministic behavior."""

    def test_finish_ends_run(self):
        """Finish tool should end the run."""
        workspace = _make_workspace("finish")
        task = _make_task(workspace, prompt="Do nothing, just finish.")

        # Fake client returns a finish call
        client = FakeLLMClient(responses=[
            """<assistant>
Task is already complete.
</assistant>
<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Nothing to do"}}
<|end|>"""
        ])

        _, profile, runtime = build_base_tool_runtime()
        ctx = ToolContext(workspace_root=workspace)

        trajectory = run_agent_task(task, client, runtime, profile, ctx)

        assert trajectory.status == RunStatus.COMPLETED
        # Should have system, user, assistant messages
        assert len(trajectory.messages) >= 3
        # First message should be system
        assert trajectory.messages[0].role == Role.SYSTEM
        # Should have the assistant content
        assistant_msgs = [m for m in trajectory.messages if m.role == Role.ASSISTANT]
        assert len(assistant_msgs) == 1
        assert "complete" in assistant_msgs[0].content
        # Should have recorded the finish tool call
        assert len(trajectory.tool_calls) == 1
        assert trajectory.tool_calls[0].name == "finish"

    def test_mutated_finish_still_stops_run(self):
        """A renamed finish tool should still terminate the run."""
        workspace = _make_workspace("mutated_finish")
        task = _make_task(workspace, prompt="Complete the task.")

        _, _, runtime = build_base_tool_runtime()
        profile = ToolProfileSampler(seed=0).sample("name_only")

        finish_exposed = None
        for tool in profile.tools:
            if tool.canonical_name == "finish":
                finish_exposed = tool.exposed_name
                break

        assert finish_exposed is not None
        assert finish_exposed != "finish"

        client = FakeLLMClient(responses=[
            f"""<assistant>
Task is already complete.
</assistant>
<|tool|>
{{"id":"c1","name":"{finish_exposed}","arguments":{{"answer":"Nothing to do"}}}}
<|end|>"""
        ])

        ctx = ToolContext(workspace_root=workspace, task=task)
        trajectory = run_agent_task(task, client, runtime, profile, ctx)

        assert trajectory.status == RunStatus.COMPLETED
        assert trajectory.metadata["total_turns"] == 1
        assert trajectory.metadata["stop_reason"] == StopReason.FINISH.value
        assert trajectory.tool_calls[0].canonical_name == "finish"

    def test_tool_call_execution(self):
        """Tool calls should be executed and results recorded."""
        workspace = _make_workspace("tool_exec", {"test.txt": "hello world"})
        task = _make_task(workspace, prompt="Read the file test.txt")

        # First response: read_file, Second response: finish
        client = FakeLLMClient(responses=[
            """<assistant>
I will read the file.
</assistant>
<|tool|>
{"id":"c1","name":"read_file","arguments":{"path":"test.txt"}}
<|end|>""",
            """<assistant>
The file contains 'hello world'.
</assistant>
<|tool|>
{"id":"c2","name":"finish","arguments":{"answer":"Read the file"}}
<|end|>"""
        ])

        _, profile, runtime = build_base_tool_runtime()
        ctx = ToolContext(workspace_root=workspace, task=task)

        trajectory = run_agent_task(task, client, runtime, profile, ctx)

        # Should have executed read_file
        assert len(trajectory.tool_calls) == 2  # read_file + finish
        assert trajectory.tool_calls[0].name == "read_file"
        assert trajectory.tool_calls[1].name == "finish"

        # Should have observations
        assert len(trajectory.observations) == 2
        # First observation should contain file content
        assert "hello world" in trajectory.observations[0].result.content

    def test_compat_tool_call_execution(self):
        """Compatibility <tool_call> blocks should still execute tools."""
        workspace = _make_workspace("compat_tool_exec", {"test.txt": "hello world"})
        task = _make_task(workspace, prompt="Read the file test.txt")

        client = FakeLLMClient(responses=[
            """<tool_call>
{"name":"read_file","arguments":{"path":"test.txt"}}
</tool_call>""",
            """<tool_call>
{"name":"finish","arguments":{"answer":"Read the file"}}
</tool_call>"""
        ])

        _, profile, runtime = build_base_tool_runtime()
        ctx = ToolContext(workspace_root=workspace, task=task)

        trajectory = run_agent_task(task, client, runtime, profile, ctx)

        assert len(trajectory.tool_calls) == 2
        assert trajectory.tool_calls[0].name == "read_file"
        assert trajectory.tool_calls[1].name == "finish"
        assert len(trajectory.observations) == 2
        assert "hello world" in trajectory.observations[0].result.content

    def test_no_tool_calls_ends_run(self):
        """No tool calls should end the run (final answer)."""
        workspace = _make_workspace("no_tools")
        task = _make_task(workspace, prompt="Just say hello")

        client = FakeLLMClient(responses=[
            """<assistant>
Hello! The task is done.
</assistant>"""
        ])

        _, profile, runtime = build_base_tool_runtime()
        ctx = ToolContext(workspace_root=workspace)

        trajectory = run_agent_task(task, client, runtime, profile, ctx)

        assert trajectory.status == RunStatus.COMPLETED
        # Should have recorded the assistant message
        assistant_msgs = [m for m in trajectory.messages if m.role == Role.ASSISTANT]
        assert len(assistant_msgs) == 1
        assert "Hello" in assistant_msgs[0].content
        # No tool calls
        assert len(trajectory.tool_calls) == 0

    def test_max_turns_stops_run(self):
        """Max turns should stop the run."""
        workspace = _make_workspace("max_turns")
        task = _make_task(workspace, prompt="Keep going")
        task.max_turns = 2  # Very low limit

        # Client keeps returning tool calls
        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"list_files","arguments":{"path":"."}}
<|end|>""",
            """<|tool|>
{"id":"c2","name":"list_files","arguments":{"path":"."}}
<|end|>""",
            """<|tool|>
{"id":"c3","name":"list_files","arguments":{"path":"."}}
<|end|>"""
        ])

        _, profile, runtime = build_base_tool_runtime()
        ctx = ToolContext(workspace_root=workspace)

        trajectory = run_agent_task(task, client, runtime, profile, ctx)

        # Should have stopped due to max_turns
        assert trajectory.metadata.get("total_turns") == 2
        assert trajectory.metadata.get("stop_reason") == StopReason.MAX_TURNS.value
        assert trajectory.status == RunStatus.FAILED

    def test_parse_error_handling(self):
        """Parse errors should not crash the runner."""
        workspace = _make_workspace("parse_error")
        task = _make_task(workspace, prompt="Test parse error")

        # Invalid tool call JSON
        client = FakeLLMClient(responses=[
            """<assistant>
Trying to call a tool.
</assistant>
<|tool|>
{"id":"c1","name":"bad_tool","arguments":{broken_json}}
<|end|>"""
        ])

        _, profile, runtime = build_base_tool_runtime()
        ctx = ToolContext(workspace_root=workspace)

        trajectory = run_agent_task(task, client, runtime, profile, ctx)

        # Should have recorded the assistant message
        assistant_msgs = [m for m in trajectory.messages if m.role == Role.ASSISTANT]
        assert len(assistant_msgs) == 1
        # No tool calls should have been executed
        assert len(trajectory.tool_calls) == 0
        # Status should indicate error
        assert trajectory.status == RunStatus.ERROR

    def test_llm_error_returns_error_trajectory(self):
        """LLM provider errors should fail the run without raising."""
        workspace = _make_workspace("llm_error")
        task = _make_task(workspace, prompt="Test provider failure")

        _, profile, runtime = build_base_tool_runtime()
        ctx = ToolContext(workspace_root=workspace)

        trajectory = run_agent_task(task, RaisingClient(), runtime, profile, ctx)

        assert trajectory.status == RunStatus.ERROR
        assert trajectory.metadata["llm_error_type"] == "RuntimeError"
        assert "provider disconnected" in trajectory.metadata["llm_error"]
        assert "LLM error" in trajectory.metadata["stop_detail"]
        assert trajectory.metadata["stop_reason"] == "llm_error"
        assert trajectory.metadata["total_turns"] == 1
        assert len(trajectory.tool_calls) == 0


class TestTrajectoryRecording:
    """Tests for trajectory content."""

    def test_system_and_user_messages_recorded(self):
        """System and user prompts should be in trajectory."""
        workspace = _make_workspace("messages")
        task = _make_task(workspace, prompt="Fix the bug")

        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
        ])

        _, profile, runtime = build_base_tool_runtime()
        ctx = ToolContext(workspace_root=workspace)

        trajectory = run_agent_task(task, client, runtime, profile, ctx)

        # First message: system
        assert trajectory.messages[0].role == Role.SYSTEM
        assert "coding agent" in trajectory.messages[0].content.lower()

        # Second message: user with task
        assert trajectory.messages[1].role == Role.USER
        assert "Fix the bug" in trajectory.messages[1].content

    def test_tool_observations_recorded(self):
        """Tool results should be recorded as observations."""
        workspace = _make_workspace("observations", {"file.py": "x = 1"})
        task = _make_task(workspace, prompt="Read file.py")

        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"read_file","arguments":{"path":"file.py"}}
<|end|>""",
            """<|tool|>
{"id":"c2","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
        ])

        _, profile, runtime = build_base_tool_runtime()
        ctx = ToolContext(workspace_root=workspace, task=task)

        trajectory = run_agent_task(task, client, runtime, profile, ctx)

        # Should have two observations
        assert len(trajectory.observations) == 2

        # First observation: read_file result
        obs1 = trajectory.observations[0]
        assert obs1.tool_name == "read_file"
        assert obs1.result.ok
        assert "x = 1" in obs1.result.content

        # Second observation: finish result
        obs2 = trajectory.observations[1]
        assert obs2.tool_name == "finish"

    def test_tool_versions_recorded(self):
        """Tool versions should be in trajectory."""
        workspace = _make_workspace("versions")
        task = _make_task(workspace, prompt="Test")

        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"finish","arguments":{}}
<|end|>"""
        ])

        _, profile, runtime = build_base_tool_runtime()
        ctx = ToolContext(workspace_root=workspace)

        trajectory = run_agent_task(task, client, runtime, profile, ctx)

        # Should have tool versions recorded
        assert len(trajectory.tool_versions) > 0
        assert "finish" in trajectory.tool_versions


class TestAgentRunnerClass:
    """Tests for the AgentRunner class interface."""

    def test_runner_class_interface(self):
        """AgentRunner should provide class-based interface."""
        workspace = _make_workspace("runner_class")
        task = _make_task(workspace, prompt="Test")

        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"OK"}}
<|end|>"""
        ])

        _, profile, runtime = build_base_tool_runtime()
        ctx = ToolContext(workspace_root=workspace)

        runner = AgentRunner(client=client, runtime=runtime, profile=profile)
        trajectory = runner.run(task, ctx)

        assert trajectory.status == RunStatus.COMPLETED
        assert len(trajectory.tool_calls) == 1


class TestBootstrapIntegration:
    """Tests verifying NS-02 and NS-03 integration."""

    def test_full_bootstrap_integration(self):
        """Should work with full bootstrap from NS-02."""
        workspace = _make_workspace("bootstrap", {"main.py": "print('hello')"})
        task = _make_task(workspace, prompt="Read main.py and finish")

        # Use all bootstrap components
        registry, profile, runtime = build_base_tool_runtime()

        # Verify registry has all tools
        assert registry.has("list_files")
        assert registry.has("read_file")
        assert registry.has("finish")

        client = FakeLLMClient(responses=[
            """<assistant>
Reading main.py
</assistant>
<|tool|>
{"id":"c1","name":"read_file","arguments":{"path":"main.py"}}
<|end|>""",
            """<assistant>
File read successfully.
</assistant>
<|tool|>
{"id":"c2","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
        ])

        ctx = ToolContext(workspace_root=workspace, task=task)
        trajectory = run_agent_task(task, client, runtime, profile, ctx)

        # Verify full execution
        assert trajectory.status == RunStatus.COMPLETED
        assert len(trajectory.observations) == 2
        assert "hello" in trajectory.observations[0].result.content


class TestToolVersionRecording:
    """Tests for correct tool_version recording in trajectory."""

    def test_observation_tool_version_from_profile(self):
        """Observation tool_version should come from ToolView.version, not canonical_name."""
        workspace = _make_workspace("tool_version", {"file.py": "x = 1"})
        task = _make_task(workspace, prompt="Read file.py")

        _, profile, runtime = build_base_tool_runtime()

        # Get the expected version from the profile
        resolved = profile.get_tool("read_file")
        assert resolved is not None
        expected_version = resolved[0].version

        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"read_file","arguments":{"path":"file.py"}}
<|end|>""",
            """<|tool|>
{"id":"c2","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
        ])

        ctx = ToolContext(workspace_root=workspace, task=task)
        trajectory = run_agent_task(task, client, runtime, profile, ctx)

        # Check observation tool_version
        assert len(trajectory.observations) == 2
        obs1 = trajectory.observations[0]
        assert obs1.tool_name == "read_file"
        assert obs1.tool_version == expected_version
        # Should NOT be the canonical_name (which would be "read_file")
        # version should be different from the tool name
        # In base profile, version is typically "default"
        assert obs1.tool_version is not None

    def test_tool_message_version_from_profile(self):
        """Tool message tool_version should come from ToolView.version."""
        workspace = _make_workspace("msg_version")
        task = _make_task(workspace, prompt="Test")

        _, profile, runtime = build_base_tool_runtime()

        # Get expected version
        resolved = profile.get_tool("finish")
        assert resolved is not None
        expected_version = resolved[0].version

        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"finish","arguments":{"answer":"OK"}}
<|end|>"""
        ])

        ctx = ToolContext(workspace_root=workspace)
        trajectory = run_agent_task(task, client, runtime, profile, ctx)

        # Find tool message
        tool_messages = [m for m in trajectory.messages if m.role == Role.TOOL]
        assert len(tool_messages) == 1
        tool_msg = tool_messages[0]
        assert tool_msg.tool_version == expected_version

    def test_tool_version_not_canonical_name(self):
        """tool_version should not be set to canonical_name."""
        workspace = _make_workspace("not_canonical")
        task = _make_task(workspace, prompt="Test")

        _, profile, runtime = build_base_tool_runtime()

        client = FakeLLMClient(responses=[
            """<|tool|>
{"id":"c1","name":"list_files","arguments":{"path":"."}}
<|end|>""",
            """<|tool|>
{"id":"c2","name":"finish","arguments":{"answer":"Done"}}
<|end|>"""
        ])

        ctx = ToolContext(workspace_root=workspace)
        trajectory = run_agent_task(task, client, runtime, profile, ctx)

        # Check that tool_version is from profile, not canonical_name
        # In base profile, version is "default", not the tool name
        for obs in trajectory.observations:
            if obs.tool_name == "list_files":
                # version should be "default", not "list_files"
                assert obs.tool_version != "list_files"
                assert obs.tool_version == "default"
