"""Built-in file operation tools.

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
    resolve_and_validate_writable_path,
)
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.execution_contract import build_execution_metadata
from pycodeagent.tools.spec import CanonicalTool
from pycodeagent.trajectory.schema import ToolResult

_MAX_OUTPUT_CHARS = 50_000
_IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache"}


def _truncate_text(text: str, limit: int = _MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n... [truncated at {limit} chars]", True


def _to_workspace_relative(full: Path, workspace_root: Path) -> str:
    """Convert an absolute path to a workspace-relative POSIX string."""
    rel = full.relative_to(workspace_root)
    return str(PurePosixPath(*rel.parts)) if rel.parts else "."


def _count_written_lines(content: str) -> int:
    if not content:
        return 0
    return content.count("\n") + (0 if content.endswith("\n") else 1)


def _missing_context_error(operation: str, *, execution_kind: str) -> ToolResult:
    return ToolResult(
        ok=False,
        content="ToolContext is required for workspace enforcement",
        is_error=True,
        metadata=build_execution_metadata(
            operation=operation,
            execution_kind=execution_kind,
            execution_stage="context_check",
            policy_domain="filesystem",
            policy_decision="deny",
            policy_reason="ToolContext is required for workspace enforcement",
            policy_reason_code="missing_context",
            dangerous=False,
            extra={"error_type": "missing_context"},
        ),
    )


def _line_range_error(message: str, *, requested_path: str) -> ToolResult:
    """Return a structured read_file line-range validation error."""
    return ToolResult(
        ok=False,
        content=message,
        is_error=True,
        metadata=build_execution_metadata(
            operation="read_file",
            execution_kind="file_read",
            execution_stage="validate_input",
            policy_domain="filesystem",
            policy_decision="deny",
            policy_reason=message,
            policy_reason_code="invalid_line_range",
            dangerous=False,
            extra={
                "error_type": "invalid_line_range",
                "requested_path": requested_path,
            },
        ),
    )


def _execution_error(
    *,
    operation: str,
    execution_kind: str,
    requested_path: str,
    message: str,
    exc: Exception,
    ctx: ToolContext | None = None,
    target: Path | None = None,
) -> ToolResult:
    resolved_target_paths: list[str] | None = None
    if target is not None and ctx is not None:
        resolved_target_paths = [_to_workspace_relative(target, ctx.workspace_root)]
    return ToolResult(
        ok=False,
        content=f"{message}: {exc}",
        is_error=True,
        metadata=build_execution_metadata(
            operation=operation,
            execution_kind=execution_kind,
            execution_stage="handler_execution",
            policy_domain="filesystem",
            policy_decision="allow",
            policy_reason=None,
            policy_reason_code=None,
            dangerous=False,
            workspace_root=None if ctx is None else ctx.workspace_root,
            resolved_target_paths=resolved_target_paths,
            extra={
                "error_type": "execution",
                "requested_path": requested_path,
            },
        ),
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
        return _missing_context_error("list_files", execution_kind="file_list")

    try:
        root = resolve_and_validate_path(
            path,
            ctx.workspace_root,
            must_exist=True,
            must_be_dir=True,
        )
    except PathPolicyError as e:
        return make_error_result(
            e,
            extra_metadata={
                "operation": "list_files",
                "execution_kind": "file_list",
                "stage": "validate_target",
                "execution_stage": "validate_target",
                "workspace_root": str(ctx.workspace_root),
                "requested_path": path,
            },
        )

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
        rendered_content, truncated = _truncate_text(content)
        return ToolResult(
            ok=True,
            content=rendered_content,
            metadata=build_execution_metadata(
                operation="list_files",
                execution_kind="file_list",
                execution_stage="result_finalize",
                policy_domain="filesystem",
                policy_decision="allow",
                dangerous=False,
                workspace_root=ctx.workspace_root,
                resolved_target_paths=[
                    _to_workspace_relative(root, ctx.workspace_root)
                ],
                extra={
                    "requested_path": path,
                    "workspace_relative_root": _to_workspace_relative(
                        root, ctx.workspace_root
                    ),
                    "resolved_path": str(root),
                    "recursive": recursive,
                    "entry_count": len(entries),
                    "truncated": truncated,
                },
            ),
        )

    except Exception as exc:
        return _execution_error(
            operation="list_files",
            execution_kind="file_list",
            requested_path=path,
            message="File listing failed",
            exc=exc,
            ctx=ctx,
            target=root,
        )


def _read_file_handler(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    *,
    ctx: ToolContext | None = None,
) -> ToolResult:
    """Read a file within workspace, optionally restricted to a line range."""
    if ctx is None:
        return _missing_context_error("read_file", execution_kind="file_read")

    try:
        target = resolve_and_validate_path(
            path,
            ctx.workspace_root,
            must_exist=True,
            must_be_file=True,
            check_allowed_fn=ctx.is_file_allowed,
        )
    except PathPolicyError as e:
        return make_error_result(
            e,
            extra_metadata={
                "operation": "read_file",
                "execution_kind": "file_read",
                "stage": "validate_target",
                "execution_stage": "validate_target",
                "workspace_root": str(ctx.workspace_root),
                "requested_path": path,
            },
        )

    try:
        with open(target, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total = len(lines)
        if start_line is not None and start_line < 1:
            return _line_range_error(
                f"start_line must be >= 1, got {start_line}",
                requested_path=path,
            )
        if end_line is not None and end_line < 1:
            return _line_range_error(
                f"end_line must be >= 1, got {end_line}",
                requested_path=path,
            )
        if (
            start_line is not None
            and end_line is not None
            and end_line < start_line
        ):
            return _line_range_error(
                f"end_line {end_line} is before start_line {start_line}",
                requested_path=path,
            )

        lo = start_line or 1
        hi = min(total, end_line or total)

        if lo > total:
            return _line_range_error(
                f"start_line {lo} exceeds file length ({total} lines)",
                requested_path=path,
            )

        numbered = [
            f"{i:4d} | {line.rstrip()}" for i, line in enumerate(lines[lo - 1 : hi], start=lo)
        ]
        content = "\n".join(numbered)
        rendered_content, truncated = _truncate_text(content)
        return ToolResult(
            ok=True,
            content=rendered_content,
            metadata=build_execution_metadata(
                operation="read_file",
                execution_kind="file_read",
                execution_stage="result_finalize",
                policy_domain="filesystem",
                policy_decision="allow",
                dangerous=False,
                workspace_root=ctx.workspace_root,
                resolved_target_paths=[
                    _to_workspace_relative(target, ctx.workspace_root)
                ],
                extra={
                    "requested_path": path,
                    "workspace_relative_path": _to_workspace_relative(
                        target, ctx.workspace_root
                    ),
                    "resolved_path": str(target),
                    "start_line": lo,
                    "end_line": hi,
                    "returned_line_count": len(numbered),
                    "total_line_count": total,
                    "bytes_read": target.stat().st_size,
                    "truncated": truncated,
                },
            ),
        )

    except Exception as exc:
        return _execution_error(
            operation="read_file",
            execution_kind="file_read",
            requested_path=path,
            message="File read failed",
            exc=exc,
            ctx=ctx,
            target=target,
        )


def _write_file_handler(
    path: str,
    content: str,
    *,
    ctx: ToolContext | None = None,
) -> ToolResult:
    """Write text to an existing workspace file."""
    if ctx is None:
        return _missing_context_error("write_file", execution_kind="file_write")

    try:
        target = resolve_and_validate_writable_path(
            path,
            ctx.workspace_root,
            must_exist=True,
            must_be_file=True,
            check_allowed_fn=ctx.is_file_allowed,
        )
    except PathPolicyError as e:
        return make_error_result(
            e,
            extra_metadata={
                "operation": "write_file",
                "execution_kind": "file_write",
                "stage": "validate_target",
                "execution_stage": "validate_target",
                "workspace_root": str(ctx.workspace_root),
                "requested_path": path,
            },
        )

    try:
        target.write_text(content, encoding="utf-8")
        relative_path = _to_workspace_relative(target, ctx.workspace_root)
        return ToolResult(
            ok=True,
            content=f"Wrote file: {relative_path}",
            metadata=build_execution_metadata(
                operation="write_file",
                execution_kind="file_write",
                execution_stage="result_finalize",
                policy_domain="filesystem",
                policy_decision="allow",
                dangerous=False,
                workspace_root=ctx.workspace_root,
                resolved_target_paths=[relative_path],
                extra={
                    "requested_path": path,
                    "workspace_relative_path": relative_path,
                    "resolved_path": str(target),
                    "bytes_written": len(content.encode("utf-8")),
                    "line_count_written": _count_written_lines(content),
                    "newline_terminated": bool(content.endswith("\n")),
                    "created": False,
                    "content_delta_kind": "overwrite",
                    "files_modified": [relative_path],
                    "change_applied": True,
                    "change_summary_present": True,
                },
            ),
        )
    except Exception as exc:
        return _execution_error(
            operation="write_file",
            execution_kind="file_write",
            requested_path=path,
            message="File write failed",
            exc=exc,
            ctx=ctx,
            target=target,
        )


def _create_file_handler(
    path: str,
    content: str = "",
    *,
    ctx: ToolContext | None = None,
) -> ToolResult:
    """Create a new workspace file, optionally creating parent directories."""
    if ctx is None:
        return _missing_context_error("create_file", execution_kind="file_create")

    try:
        target = resolve_and_validate_writable_path(
            path,
            ctx.workspace_root,
            must_be_file=True,
            check_allowed_fn=ctx.is_file_allowed,
        )
    except PathPolicyError as e:
        return make_error_result(
            e,
            extra_metadata={
                "operation": "create_file",
                "execution_kind": "file_create",
                "stage": "validate_target",
                "execution_stage": "validate_target",
                "workspace_root": str(ctx.workspace_root),
                "requested_path": path,
            },
        )

    if target.exists():
        return ToolResult(
            ok=False,
            content=f"File already exists: {_to_workspace_relative(target, ctx.workspace_root)}",
            is_error=True,
            metadata=build_execution_metadata(
                operation="create_file",
                execution_kind="file_create",
                execution_stage="validate_target",
                policy_domain="filesystem",
                policy_decision="deny",
                policy_reason=(
                    f"File already exists: {_to_workspace_relative(target, ctx.workspace_root)}"
                ),
                policy_reason_code="already_exists",
                dangerous=False,
                workspace_root=ctx.workspace_root,
                resolved_target_paths=[
                    _to_workspace_relative(target, ctx.workspace_root)
                ],
                extra={
                    "error_type": "already_exists",
                    "requested_path": path,
                },
            ),
        )

    try:
        parent_directories_created = not target.parent.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        relative_path = _to_workspace_relative(target, ctx.workspace_root)
        return ToolResult(
            ok=True,
            content=f"Created file: {relative_path}",
            metadata=build_execution_metadata(
                operation="create_file",
                execution_kind="file_create",
                execution_stage="result_finalize",
                policy_domain="filesystem",
                policy_decision="allow",
                dangerous=False,
                workspace_root=ctx.workspace_root,
                resolved_target_paths=[relative_path],
                extra={
                    "requested_path": path,
                    "workspace_relative_path": relative_path,
                    "resolved_path": str(target),
                    "bytes_written": len(content.encode("utf-8")),
                    "line_count_written": _count_written_lines(content),
                    "newline_terminated": bool(content.endswith("\n")),
                    "created": True,
                    "parent_directories_created": parent_directories_created,
                    "content_delta_kind": "create",
                    "files_modified": [relative_path],
                    "change_applied": True,
                    "change_summary_present": True,
                },
            ),
        )
    except Exception as exc:
        return _execution_error(
            operation="create_file",
            execution_kind="file_create",
            requested_path=path,
            message="File creation failed",
            exc=exc,
            ctx=ctx,
            target=target,
        )


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

write_file_tool = CanonicalTool(
    canonical_name="write_file",
    description="Write text to an existing file in the workspace.",
    canonical_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Existing file path to overwrite."},
            "content": {"type": "string", "description": "Full replacement file content."},
        },
        "required": ["path", "content"],
    },
    handler=_write_file_handler,
)

create_file_tool = CanonicalTool(
    canonical_name="create_file",
    description="Create a new file in the workspace.",
    canonical_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "New file path to create."},
            "content": {"type": "string", "description": "Initial file content."},
        },
        "required": ["path"],
    },
    handler=_create_file_handler,
)
