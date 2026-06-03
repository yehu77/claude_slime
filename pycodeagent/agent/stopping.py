"""Stopping conditions for the agent loop.

Determines when the agent should stop executing:
1. The agent called the 'finish' tool
2. The agent produced no tool calls (gave a final answer)
3. Maximum turns exceeded
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from pycodeagent.trajectory.schema import ToolCall


class StopReason(str, Enum):
    """Why the agent stopped."""

    FINISH = "finish"  # Agent called finish tool
    NO_TOOL_CALLS = "no_tool_calls"  # Agent gave final answer without tools
    MAX_TURNS = "max_turns"  # Exceeded turn limit
    PARSE_ERROR = "parse_error"  # Parsing failed repeatedly


class StopDecision(BaseModel):
    """Decision about whether to stop the agent loop."""

    should_stop: bool
    reason: StopReason | None = None
    detail: str = ""


def check_finish_tool_called(tool_calls: list[ToolCall]) -> bool:
    """Check if any of the tool calls is the finish tool.

    Args:
        tool_calls: List of tool calls from the assistant.

    Returns:
        True if finish was called, False otherwise.
    """
    return any(
        (call.canonical_name or call.name) == "finish"
        for call in tool_calls
    )


def should_stop(
    tool_calls: list[ToolCall],
    parse_errors: list[str],
    current_turn: int,
    max_turns: int,
) -> StopDecision:
    """Determine if the agent loop should stop.

    Args:
        tool_calls: Tool calls from the current assistant turn.
        parse_errors: Parse errors from the current turn.
        current_turn: Current turn number (1-indexed).
        max_turns: Maximum allowed turns.

    Returns:
        StopDecision indicating whether and why to stop.
    """
    # Check for finish tool
    if check_finish_tool_called(tool_calls):
        return StopDecision(
            should_stop=True,
            reason=StopReason.FINISH,
            detail="Agent called finish tool",
        )

    # Check for max turns
    if current_turn >= max_turns:
        return StopDecision(
            should_stop=True,
            reason=StopReason.MAX_TURNS,
            detail=f"Reached max_turns={max_turns}",
        )

    # Check for parse errors with no tool calls
    if parse_errors and not tool_calls:
        return StopDecision(
            should_stop=True,
            reason=StopReason.PARSE_ERROR,
            detail=f"Parse errors: {parse_errors}",
        )

    # Check for no tool calls (final answer)
    if not tool_calls:
        return StopDecision(
            should_stop=True,
            reason=StopReason.NO_TOOL_CALLS,
            detail="Agent provided final answer without tool calls",
        )

    # Continue execution
    return StopDecision(
        should_stop=False,
        reason=None,
        detail="",
    )
