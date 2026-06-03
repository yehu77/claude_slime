"""Built-in file operation tools: list_files and read_file.

All paths are validated to stay within workspace and respect task constraints.
Output paths are always workspace-relative POSIX paths.
"""

from __future__ import annotations

import os
from pathlib import Path
from pathlib import PurePosixPath

from pycodeagent.env.path_policy import (
    PathPolicyError,
    make_error_result,
    resolve_and_validate_path,
)
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.spec import CanonicalTool
from pycodeagent.trajectory.schema import ToolResult

_MAX_OUTPUT_CHARS = 50_000
_IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache"}


def _trunc(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated at {limit} chars]"


def _to_workspace_relative(full: Path, workspace_root: Path) -> str:
    """Convert an absolute path to a workspace-relative POSIX string."""
    rel = full.relative_to(workspace_root)
    return str(PurePosixPath(*rel.parts)) if rel.parts else "."


def _line_range_error(message: str) -> ToolResult:
    """Return a structured read_file line-range validation error."""
    return ToolResult(
        ok=False,
        content=message,
        is_error=True,
        metadata={"error_type": "invalid_line_range"},
    )


def _has_allowed_descendant(dir_path: Path, workspace_root: Path, ctx: ToolContext) -> bool:
    """Check if a directory contains any allowed file (recursively).

    Used for non-recursive list_files to decide if a directory should be shown.
    """
    for dirpath, dirnames, filenames in os.walk(dir_path):
        # Prune ignored directories in-place
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
        for fname in filenames:
            full = Path(dirpath) / fname
            rel_path = _to_workspace_relative(full, workspace_root)
            if ctx.is_file_allowed(rel_path):
                return True
    return False


def _list_files_handler(
    path: str = ".",
    recursive: bool = True,
    *,
    ctx: ToolContext | None = None,
) -> ToolResult:
    """Return a list of workspace-relative file paths, ignoring common dirs."""
    if ctx is None:
        return ToolResult(
            ok=False,
            content="ToolContext is required for workspace enforcement",
            is_error=True,
            metadata={"error_type": "missing_context"},
        )

    try:
        root = resolve_and_validate_path(
            path,
            ctx.workspace_root,
            must_exist=True,
            must_be_dir=True,
        )
    except PathPolicyError as e:
        return make_error_result(e)

    try:
        entries: list[str] = []
        if recursive:
            for dirpath, dirnames, filenames in os.walk(root):
                # Prune ignored directories in-place so os.walk skips them.
                dirnames[:] = sorted(
                    d for d in dirnames if d not in _IGNORED_DIRS
                )
                for fname in sorted(filenames):
                    full = Path(dirpath) / fname
                    rel_path = _to_workspace_relative(full, ctx.workspace_root)
                    # Skip files not allowed by task constraints
                    if not ctx.is_file_allowed(rel_path):
                        continue
                    entries.append(rel_path)
        else:
            for item in sorted(root.iterdir()):
                if item.name in _IGNORED_DIRS:
                    continue
                rel_path = _to_workspace_relative(item, ctx.workspace_root)
                # For files: check is_file_allowed directly
                # For directories: show if they contain any allowed descendant
                if item.is_file():
                    if not ctx.is_file_allowed(rel_path):
                        continue
                else:  # directory
                    if not _has_allowed_descendant(item, ctx.workspace_root, ctx):
                        continue
                entries.append(rel_path)

        content = "\n".join(entries) if entries else "(empty directory)"
        return ToolResult(ok=True, content=_trunc(content))

    except Exception as exc:
        return ToolResult(ok=False, content=str(exc), is_error=True)


def _read_file_handler(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    *,
    ctx: ToolContext | None = None,
) -> ToolResult:
    """Read a file within workspace, optionally restricted to a line range."""
    if ctx is None:
        return ToolResult(
            ok=False,
            content="ToolContext is required for workspace enforcement",
            is_error=True,
            metadata={"error_type": "missing_context"},
        )

    try:
        target = resolve_and_validate_path(
            path,
            ctx.workspace_root,
            must_exist=True,
            must_be_file=True,
            check_allowed_fn=ctx.is_file_allowed,
        )
    except PathPolicyError as e:
        return make_error_result(e)

    try:
        with open(target, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total = len(lines)
        if start_line is not None and start_line < 1:
            return _line_range_error(
                f"start_line must be >= 1, got {start_line}"
            )
        if end_line is not None and end_line < 1:
            return _line_range_error(
                f"end_line must be >= 1, got {end_line}"
            )
        if (
            start_line is not None
            and end_line is not None
            and end_line < start_line
        ):
            return _line_range_error(
                f"end_line {end_line} is before start_line {start_line}"
            )

        lo = start_line or 1
        hi = min(total, end_line or total)

        if lo > total:
            return _line_range_error(
                f"start_line {lo} exceeds file length ({total} lines)"
            )

        numbered = [
            f"{i:4d} | {line.rstrip()}" for i, line in enumerate(lines[lo - 1 : hi], start=lo)
        ]
        content = "\n".join(numbered)
        return ToolResult(ok=True, content=_trunc(content))

    except Exception as exc:
        return ToolResult(ok=False, content=str(exc), is_error=True)


# --- CanonicalTool definitions ---

list_files_tool = CanonicalTool(
    canonical_name="list_files",
    description="List files in the workspace directory.",
    canonical_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Root directory to list (default '.')."},
            "recursive": {"type": "boolean", "description": "Recurse into subdirectories."},
        },
        "required": [],
    },
    handler=_list_files_handler,
)

read_file_tool = CanonicalTool(
    canonical_name="read_file",
    description="Read a file from the workspace.",
    canonical_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read."},
            "start_line": {"type": "integer", "description": "First line to include (1-based)."},
            "end_line": {"type": "integer", "description": "Last line to include (1-based)."},
        },
        "required": ["path"],
    },
    handler=_read_file_handler,
)
