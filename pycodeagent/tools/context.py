"""Tool execution context.

Provides workspace and task context to builtin tools, enabling them to
enforce workspace boundaries and task-level file constraints.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pycodeagent.env.task import CodingTask


class ToolContext(BaseModel):
    """Context passed to builtin tool handlers.

    This is the minimal context needed for workspace enforcement.
    Future sandbox integration can extend this.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    workspace_root: Path
    task: CodingTask | None = None

    def is_file_allowed(self, rel_path: str) -> bool:
        """Check if a repo-relative path is allowed by task constraints."""
        if self.task is None:
            return True
        return self.task.is_file_allowed(rel_path)
