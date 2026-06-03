"""Single-task agent runner for text-mode execution.

Implements the minimal agent loop:
1. Build initial prompt with task and tool specs
2. Call LLM client
3. Parse response
4. Execute tool calls
5. Record observations
6. Check stopping conditions
7. Repeat until done

This runner does NOT handle:
- Verifier execution
- Reward computation
- Artifact persistence
- Workspace copying
- Batch execution
"""

from __future__ import annotations

from typing import Any

from pycodeagent.agent.llm_client import BaseLLMClient, GenerateRequest
from pycodeagent.agent.parser import parse_assistant_response
from pycodeagent.agent.prompt import build_initial_messages
from pycodeagent.agent.stopping import StopReason, should_stop
from pycodeagent.env.task import CodingTask
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.runtime import ToolRuntime
from pycodeagent.tools.spec import ToolProfile
from pycodeagent.trajectory.schema import Message, Role, RunStatus, Trajectory


def run_agent_task(
    task: CodingTask,
    client: BaseLLMClient,
    runtime: ToolRuntime,
    profile: ToolProfile,
    ctx: ToolContext,
) -> Trajectory:
    """Run the agent on a single coding task.

    Args:
        task: The coding task to solve.
        client: LLM client for generating responses.
        runtime: Tool runtime for executing tool calls.
        profile: Tool profile defining available tools.
        ctx: Execution context with workspace and task constraints.

    Returns:
        A Trajectory recording the full execution history.
    """
    # Initialize trajectory
    trajectory = Trajectory(
        task_id=task.task_id,
        repo=str(task.repo_path),
        tool_profile_id=profile.profile_id,
        status=RunStatus.COMPLETED,
    )

    # Register tool versions
    trajectory.register_tool_versions(profile.get_tool_versions())

    # Build initial messages
    tool_specs = profile.get_exposed_specs()
    messages = build_initial_messages(task.prompt, tool_specs)

    # Add to trajectory
    trajectory.add_system(messages[0]["content"])
    trajectory.add_user(messages[1]["content"])

    # Main loop
    current_turn = 0
    stop_detail = ""
    stop_reason = ""

    while current_turn < task.max_turns:
        current_turn += 1

        # Prepare request for LLM
        request_messages = [_message_to_dict(m) for m in trajectory.messages]
        request = GenerateRequest(messages=request_messages, tools=tool_specs)

        # Call LLM. A provider/network failure should fail this run, not the
        # whole batch/study process that owns it.
        try:
            response = client.generate(request)
        except Exception as e:
            trajectory.status = RunStatus.ERROR
            stop_detail = f"LLM error: {type(e).__name__}: {e}"
            stop_reason = "llm_error"
            trajectory.metadata = {
                "total_turns": current_turn,
                "stop_detail": stop_detail,
                "stop_reason": stop_reason,
                "llm_error": str(e),
                "llm_error_type": type(e).__name__,
            }
            return trajectory

        # Parse response
        parsed = parse_assistant_response(response.text)

        # Record assistant turn in trajectory
        trajectory.add_assistant(
            parsed.assistant_content,
            tool_calls=parsed.tool_calls if parsed.has_tool_calls else None,
        )

        # Execute all tool calls and record observations
        for call in parsed.tool_calls:
            result = runtime.execute(call, profile, ctx=ctx)
            # Get tool version from the profile's ToolView, not from canonical_name
            tool_version: str | None = None
            resolved = profile.get_tool(call.name)
            if resolved is not None:
                tool_version = resolved[0].version
            trajectory.add_tool_observation(
                call,
                result,
                tool_version=tool_version,
            )

        # Check stopping conditions AFTER executing tool calls
        stop_decision = should_stop(
            tool_calls=parsed.tool_calls,
            parse_errors=parsed.parse_errors,
            current_turn=current_turn,
            max_turns=task.max_turns,
        )

        if stop_decision.should_stop:
            stop_detail = stop_decision.detail
            stop_reason = (
                stop_decision.reason.value
                if stop_decision.reason is not None
                else ""
            )
            if stop_decision.reason == StopReason.PARSE_ERROR:
                trajectory.status = RunStatus.ERROR
            elif stop_decision.reason == StopReason.MAX_TURNS:
                trajectory.status = RunStatus.FAILED
            break

    # Set final status based on stop reason
    if (
        trajectory.status == RunStatus.COMPLETED
        and current_turn >= task.max_turns
        and not stop_detail
    ):
        stop_detail = f"Reached max_turns={task.max_turns}"
        stop_reason = StopReason.MAX_TURNS.value
        trajectory.status = RunStatus.FAILED

    # Store any additional metadata about the run
    trajectory.metadata = {
        "total_turns": current_turn,
        "stop_detail": stop_detail,
        "stop_reason": stop_reason,
    }

    return trajectory


def _message_to_dict(msg: Message) -> dict[str, Any]:
    """Convert a Message to a dict for the LLM request.

    Args:
        msg: The message to convert.

    Returns:
        A dict suitable for the LLM client.
    """
    result: dict[str, Any] = {
        "role": msg.role.value,
        "content": msg.content,
    }
    if msg.tool_calls:
        result["tool_calls"] = [tc.model_dump() for tc in msg.tool_calls]
    if msg.tool_call_id:
        result["tool_call_id"] = msg.tool_call_id
    if msg.tool_name:
        result["tool_name"] = msg.tool_name
    return result


class AgentRunner:
    """Alternative class-based interface for running agents.

    Provides a stateless wrapper around run_agent_task for cases where
    a class-based API is preferred.
    """

    def __init__(
        self,
        client: BaseLLMClient,
        runtime: ToolRuntime,
        profile: ToolProfile,
    ) -> None:
        """Initialize the runner.

        Args:
            client: LLM client for generating responses.
            runtime: Tool runtime for executing tools.
            profile: Tool profile defining available tools.
        """
        self.client = client
        self.runtime = runtime
        self.profile = profile

    def run(self, task: CodingTask, ctx: ToolContext) -> Trajectory:
        """Run the agent on a task.

        Args:
            task: The coding task to solve.
            ctx: Execution context.

        Returns:
            The execution trajectory.
        """
        return run_agent_task(
            task=task,
            client=self.client,
            runtime=self.runtime,
            profile=self.profile,
            ctx=ctx,
        )
