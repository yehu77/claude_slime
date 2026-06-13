"""Coding task definition.

A CodingTask describes a unit of work for the agent: which repo to work on,
what to do, how to verify success, and what constraints to enforce.
"""

from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field


class CodingTask(BaseModel):
    """A single coding task for the agent to solve."""

    task_id: str
    repo_path: Path
    prompt: str
    test_command: str | list[str] = "pytest -q"
    max_turns: int = 12
    allowed_files: list[str] = Field(default_factory=list)
    forbidden_files: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def requires_runtime_validation_evidence(self) -> bool:
        """Whether runtime completion should be gated on successful validation."""
        return bool(self.metadata.get("require_runtime_validation_evidence", False))

    def normalize_repo_relative_path(self, file_path: str) -> str:
        """Normalize a path into a repo-relative POSIX path.

        The runtime should only operate on workspace-relative paths. This
        rejects absolute paths and directory traversal before pattern matching.
        """
        raw_path = Path(file_path)
        if raw_path.is_absolute():
            raise ValueError(f"Absolute paths are not allowed: {file_path}")

        posix_path = PurePosixPath(*raw_path.parts)
        if any(part == ".." for part in posix_path.parts):
            raise ValueError(f"Path escapes workspace: {file_path}")

        normalized = str(posix_path)
        if normalized in {"", "."}:
            return "."
        return normalized

    def is_file_allowed(self, file_path: str) -> bool:
        """Check whether a file path is within the allowed set and not forbidden."""
        import fnmatch

        try:
            normalized_path = self.normalize_repo_relative_path(file_path)
        except ValueError:
            return False

        for pattern in self.forbidden_files:
            if fnmatch.fnmatch(normalized_path, pattern):
                return False

        if not self.allowed_files:
            return True

        return any(
            fnmatch.fnmatch(normalized_path, pattern)
            for pattern in self.allowed_files
        )

    @classmethod
    def from_jsonl(cls, path: Path) -> list[CodingTask]:
        """Load tasks from a JSONL file."""
        tasks = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    tasks.append(cls.model_validate_json(line))
        return tasks
