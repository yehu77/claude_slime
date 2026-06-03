"""Built-in finish tool — signals that the agent has completed the task."""

from __future__ import annotations

from pycodeagent.tools.spec import CanonicalTool
from pycodeagent.trajectory.schema import ToolResult


def _finish_handler(answer: str = "", summary: str = "") -> ToolResult:
    """Record a final answer and signal task completion."""
    parts: list[str] = []
    if answer:
        parts.append(answer)
    if summary:
        parts.append(summary)
    content = "\n".join(parts) if parts else "Task finished."
    return ToolResult(
        ok=True,
        content=content,
        metadata={"is_finish": True},
    )


finish_tool = CanonicalTool(
    canonical_name="finish",
    description="Signal task completion with an optional answer.",
    canonical_schema={
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "Final answer or description of what was done.",
            },
            "summary": {
                "type": "string",
                "description": "Optional summary of the solution.",
            },
        },
        "required": [],
    },
    handler=_finish_handler,
)
