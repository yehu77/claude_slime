"""Path policy for workspace boundary enforcement.

This module provides centralized validation for all file paths used by
builtin tools, ensuring they stay within the workspace and respect task
constraints.
"""

from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pycodeagent.trajectory.schema import ToolResult


class PathPolicyError(Exception):
    """Raised when a path violates workspace or task constraints."""

    def __init__(self, message: str, error_type: str):
        super().__init__(message)
        self.error_type = error_type


def _attempts_workspace_escape(raw: Path) -> bool:
    """Return True when a relative path lexically escapes above workspace root.

    This is a conservative early check for obvious ``..`` traversal. Paths like
    ``subdir/../file.txt`` are allowed because they normalize within the
    workspace, while ``../file.txt`` and ``a/../../file.txt`` are rejected
    before filesystem resolution.
    """
    depth = 0
    for part in raw.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if depth == 0:
                return True
            depth -= 1
            continue
        depth += 1
    return False


def resolve_and_validate_path(
    raw_path: str,
    workspace_root: Path,
    *,
    allow_absolute: bool = False,
    must_exist: bool = False,
    must_be_file: bool = False,
    must_be_dir: bool = False,
    check_allowed_fn=None,
) -> Path:
    """Resolve a path within workspace and validate all constraints.

    Args:
        raw_path: The path string from the tool call.
        workspace_root: The workspace root directory (already resolved).
        allow_absolute: If True, absolute paths are allowed if they resolve
            inside workspace. Default False rejects absolute paths outright.
        must_exist: If True, the resolved path must exist.
        must_be_file: If True, the resolved path must be a file.
        must_be_dir: If True, the resolved path must be a directory.
        check_allowed_fn: Optional callable(str) -> bool for task-level
            allowed/forbidden checking.

    Returns:
        The resolved absolute Path within workspace.

    Raises:
        PathPolicyError: If any constraint is violated.
    """
    # Ensure workspace_root is resolved
    workspace_root = workspace_root.resolve()

    # Reject absolute paths unless explicitly allowed
    raw = Path(raw_path)
    if raw.is_absolute() and not allow_absolute:
        raise PathPolicyError(
            f"Absolute paths are not allowed: {raw_path}",
            error_type="absolute_path",
        )

    # Reject obvious path traversal before filesystem resolution. We still keep
    # the resolved-path boundary check below for symlink / normalization safety.
    if _attempts_workspace_escape(raw):
        raise PathPolicyError(
            f"Path traversal is not allowed: {raw_path}",
            error_type="workspace_escape",
        )

    # Resolve relative to workspace
    resolved = (workspace_root / raw_path).resolve()

    # Critical: verify resolved path is inside workspace
    try:
        resolved.relative_to(workspace_root)
    except ValueError:
        raise PathPolicyError(
            f"Path escapes workspace: {raw_path} resolves to {resolved}",
            error_type="workspace_escape",
        )

    # Task-level allowed/forbidden check
    if check_allowed_fn is not None:
        # Compute repo-relative path for pattern matching
        try:
            rel_path = resolved.relative_to(workspace_root)
            rel_str = str(PurePosixPath(*rel_path.parts))
        except ValueError:
            rel_str = str(resolved)

        if not check_allowed_fn(rel_str):
            raise PathPolicyError(
                f"Path is not allowed by task constraints: {rel_str}",
                error_type="forbidden_file",
            )

    # Existence checks
    if must_exist and not resolved.exists():
        raise PathPolicyError(
            f"Path does not exist: {raw_path}",
            error_type="not_found",
        )

    if must_be_file and resolved.exists() and not resolved.is_file():
        raise PathPolicyError(
            f"Not a file: {raw_path}",
            error_type="not_file",
        )

    if must_be_dir and resolved.exists() and not resolved.is_dir():
        raise PathPolicyError(
            f"Not a directory: {raw_path}",
            error_type="not_directory",
        )

    return resolved


def validate_cwd(
    raw_cwd: str | None,
    workspace_root: Path,
) -> Path:
    """Validate and resolve a working directory within workspace.

    If raw_cwd is None, returns workspace_root.
    Otherwise validates that raw_cwd resolves inside workspace.

    Returns:
        Resolved absolute Path for the working directory.

    Raises:
        PathPolicyError: If the path violates constraints.
    """
    workspace_root = workspace_root.resolve()

    if raw_cwd is None:
        return workspace_root

    return resolve_and_validate_path(
        raw_cwd,
        workspace_root,
        allow_absolute=False,
        must_exist=True,
        must_be_dir=True,
    )


def make_error_result(error: PathPolicyError) -> ToolResult:
    """Convert a PathPolicyError to a structured ToolResult."""
    from pycodeagent.trajectory.schema import ToolResult

    return ToolResult(
        ok=False,
        content=str(error),
        is_error=True,
        metadata={"error_type": error.error_type},
    )
