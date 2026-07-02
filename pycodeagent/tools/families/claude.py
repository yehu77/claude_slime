"""Strict Claude-family canonical tools."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from pycodeagent.env.path_policy import PathPolicyError, resolve_and_validate_path, resolve_and_validate_writable_path
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.execution_contract import build_execution_metadata
from pycodeagent.tools.registry import ToolRegistry
from pycodeagent.tools.shell_runtimes import ClaudeShellRuntime
from pycodeagent.tools.spec import CanonicalTool
from pycodeagent.trajectory.schema import ToolResult

_FAMILY = "claude"
_READ_STATE_KEY = "claude_read_paths"
_PDF_MAX_PAGES_PER_READ = 20
_MAX_TEXT_OUTPUT_CHARS = 50_000
_MAX_GLOB_RESULTS = 100
_DEFAULT_GREP_HEAD_LIMIT = 250
_IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache"}
_BINARY_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".so",
    ".o",
    ".exe",
    ".bin",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".zip",
    ".tar",
    ".gz",
    ".pdf",
}


def build_claude_canonical_tools(
    *,
    shell_runtime: ClaudeShellRuntime | None = None,
) -> list[CanonicalTool]:
    runtime = shell_runtime or ClaudeShellRuntime()

    def bash_handler(
        command: str,
        timeout: int | float | None = None,
        description: str | None = None,
        run_in_background: bool | None = None,
        dangerouslyDisableSandbox: bool | None = None,
        *,
        ctx: ToolContext | None = None,
    ) -> ToolResult:
        result = runtime.execute_bash(
            command,
            timeout=timeout,
            run_in_background=bool(run_in_background),
            ctx=ctx,
        )
        return _relabel_result(
            result,
            operation="Bash",
            command_family="Bash",
            family=_FAMILY,
            extra={
                "requested_description": description,
                "dangerously_disable_sandbox_requested": bool(
                    dangerouslyDisableSandbox
                ),
            },
        )

    tools = [
        CanonicalTool(
            canonical_name="Bash",
            description="Execute a shell command in Bash.",
            canonical_schema=_bash_schema(),
            handler=bash_handler,
            version="Bash_v1",
            metadata={
                "family": _FAMILY,
                "source_runtime": "claude_shell",
                "native_tool_name": "Bash",
            },
        ),
        CanonicalTool(
            canonical_name="Read",
            description="Read a file from the workspace using Claude-style semantics.",
            canonical_schema=_read_schema(),
            handler=_claude_read_handler,
            version="Read_v1",
            metadata={
                "family": _FAMILY,
                "source_runtime": "claude_file",
                "native_tool_name": "Read",
            },
        ),
        CanonicalTool(
            canonical_name="Edit",
            description="Edit a file by replacing exact text.",
            canonical_schema=_edit_schema(),
            handler=_claude_edit_handler,
            version="Edit_v1",
            metadata={
                "family": _FAMILY,
                "source_runtime": "claude_file",
                "native_tool_name": "Edit",
            },
        ),
        CanonicalTool(
            canonical_name="Write",
            description="Write full file contents.",
            canonical_schema=_write_schema(),
            handler=_claude_write_handler,
            version="Write_v1",
            metadata={
                "family": _FAMILY,
                "source_runtime": "claude_file",
                "native_tool_name": "Write",
            },
        ),
        CanonicalTool(
            canonical_name="Grep",
            description="Regex-aware code search with Claude-style parameters.",
            canonical_schema=_grep_schema(),
            handler=_claude_grep_handler,
            version="Grep_v1",
            metadata={
                "family": _FAMILY,
                "source_runtime": "claude_search",
                "native_tool_name": "Grep",
            },
        ),
        CanonicalTool(
            canonical_name="Glob",
            description="Match workspace paths with a glob pattern.",
            canonical_schema=_glob_schema(),
            handler=_claude_glob_handler,
            version="Glob_v1",
            metadata={
                "family": _FAMILY,
                "source_runtime": "claude_search",
                "native_tool_name": "Glob",
            },
        ),
    ]
    return tools


def build_claude_canonical_registry(
    *,
    shell_runtime: ClaudeShellRuntime | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in build_claude_canonical_tools(shell_runtime=shell_runtime):
        registry.register(tool)
    return registry


def _claude_read_handler(
    file_path: str,
    offset: int | None = None,
    limit: int | None = None,
    pages: str | None = None,
    *,
    ctx: ToolContext | None = None,
) -> ToolResult:
    operation = "Read"
    if ctx is None:
        return _missing_context_error(operation, execution_kind="file_read")

    pages_error = _validate_pages_parameter(pages)
    if pages_error is not None:
        return _validation_error(
            operation=operation,
            execution_kind="file_read",
            content=pages_error,
            error_type="invalid_pages",
            ctx=ctx,
            requested_path=file_path,
        )

    if offset is not None and offset < 0:
        return _validation_error(
            operation=operation,
            execution_kind="file_read",
            content="offset must be >= 0",
            error_type="invalid_offset",
            ctx=ctx,
            requested_path=file_path,
        )
    if limit is not None and limit <= 0:
        return _validation_error(
            operation=operation,
            execution_kind="file_read",
            content="limit must be > 0",
            error_type="invalid_limit",
            ctx=ctx,
            requested_path=file_path,
        )

    try:
        target = resolve_and_validate_path(
            file_path,
            ctx.workspace_root,
            allow_absolute=True,
            must_exist=True,
            must_be_file=True,
            check_allowed_fn=ctx.is_file_allowed,
        )
    except PathPolicyError as exc:
        return _path_policy_error(
            exc,
            operation=operation,
            execution_kind="file_read",
            requested_path=file_path,
            ctx=ctx,
        )

    if pages is not None and target.suffix.lower() != ".pdf":
        return _validation_error(
            operation=operation,
            execution_kind="file_read",
            content="pages is only supported for PDF files.",
            error_type="invalid_pages",
            ctx=ctx,
            requested_path=file_path,
            resolved_target_paths=[_to_workspace_relative(target, ctx.workspace_root)],
        )

    if target.suffix.lower() == ".pdf":
        return _validation_error(
            operation=operation,
            execution_kind="file_read",
            content="PDF reading is not supported in the local strict Claude runtime yet.",
            error_type="unsupported_file_type",
            ctx=ctx,
            requested_path=file_path,
            resolved_target_paths=[_to_workspace_relative(target, ctx.workspace_root)],
        )

    start_line = 1 if offset is None else offset
    start_index = 0 if start_line == 0 else max(0, start_line - 1)

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        total_lines = len(lines)
        if limit is None:
            selected_lines = lines[start_index:]
        else:
            selected_lines = lines[start_index : start_index + limit]

        if not selected_lines:
            if total_lines == 0:
                content = (
                    "<system-reminder>Warning: the file exists but the contents are "
                    "empty.</system-reminder>"
                )
            else:
                content = (
                    "<system-reminder>Warning: the file exists but is shorter than "
                    f"the provided offset ({start_line}). The file has {total_lines} "
                    "lines.</system-reminder>"
                )
        else:
            numbered = [
                f"{line_number:4d} | {line}"
                for line_number, line in enumerate(selected_lines, start=start_line)
            ]
            content = "\n".join(numbered)

        rendered_content, truncated = _truncate_text(content)
        _record_read_witness(
            ctx,
            target,
            text,
            offset=start_line,
            limit=limit,
        )
        relative_path = _to_workspace_relative(target, ctx.workspace_root)
        return ToolResult(
            ok=True,
            content=rendered_content,
            metadata=build_execution_metadata(
                operation=operation,
                execution_kind="file_read",
                execution_stage="result_finalize",
                policy_domain="filesystem",
                policy_decision="allow",
                dangerous=False,
                command_family=operation,
                workspace_root=ctx.workspace_root,
                resolved_target_paths=[relative_path],
                extra={
                    "family": _FAMILY,
                    "requested_path": file_path,
                    "workspace_relative_path": relative_path,
                    "resolved_path": str(target),
                    "offset": start_line,
                    "limit": limit,
                    "pages": pages,
                    "returned_line_count": len(selected_lines),
                    "total_line_count": total_lines,
                    "bytes_read": target.stat().st_size,
                    "truncated": truncated,
                },
            ),
        )
    except Exception as exc:
        return _execution_error(
            operation=operation,
            execution_kind="file_read",
            content=f"File read failed: {exc}",
            error_type="execution",
            ctx=ctx,
            requested_path=file_path,
            resolved_target_paths=[_to_workspace_relative(target, ctx.workspace_root)],
        )


def _claude_edit_handler(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool | None = None,
    *,
    ctx: ToolContext | None = None,
) -> ToolResult:
    operation = "Edit"
    if ctx is None:
        return _missing_context_error(operation, execution_kind="file_write")

    if old_string == new_string:
        return _validation_error(
            operation=operation,
            execution_kind="file_write",
            content="No changes to make: old_string and new_string are exactly the same.",
            error_type="no_op_edit",
            ctx=ctx,
            requested_path=file_path,
        )

    try:
        target = resolve_and_validate_writable_path(
            file_path,
            ctx.workspace_root,
            allow_absolute=True,
            must_be_file=True,
            check_allowed_fn=ctx.is_file_allowed,
        )
    except PathPolicyError as exc:
        return _path_policy_error(
            exc,
            operation=operation,
            execution_kind="file_write",
            requested_path=file_path,
            ctx=ctx,
        )

    target_exists = target.exists()
    replace_every = bool(replace_all)

    try:
        if not target_exists:
            if old_string != "":
                return _validation_error(
                    operation=operation,
                    execution_kind="file_write",
                    content="File does not exist. Use old_string=\"\" to create a new file.",
                    error_type="not_found",
                    ctx=ctx,
                    requested_path=file_path,
                    resolved_target_paths=[_to_workspace_relative(target, ctx.workspace_root)],
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new_string, encoding="utf-8")
            _record_read_witness(ctx, target, new_string, offset=1, limit=None)
            return _write_success_result(
                operation=operation,
                ctx=ctx,
                target=target,
                content=f"Created file: {_to_workspace_relative(target, ctx.workspace_root)}",
                created=True,
                content_delta_kind="create",
                extra={
                    "replace_all": replace_every,
                    "old_string_empty": True,
                },
            )

        current_content = target.read_text(encoding="utf-8", errors="replace")

        if old_string == "":
            if current_content.strip() != "":
                return _validation_error(
                    operation=operation,
                    execution_kind="file_write",
                    content="Cannot create new file - file already exists.",
                    error_type="already_exists",
                    ctx=ctx,
                    requested_path=file_path,
                    resolved_target_paths=[_to_workspace_relative(target, ctx.workspace_root)],
                )
            new_content = new_string
        else:
            witness_error = _require_unchanged_full_read(ctx, target)
            if witness_error is not None:
                return _validation_error(
                    operation=operation,
                    execution_kind="file_write",
                    content=witness_error,
                    error_type="stale_read_state",
                    ctx=ctx,
                    requested_path=file_path,
                    resolved_target_paths=[_to_workspace_relative(target, ctx.workspace_root)],
                )

            matches = current_content.count(old_string)
            if matches == 0:
                return _validation_error(
                    operation=operation,
                    execution_kind="file_write",
                    content=f"String to replace not found in file.\nString: {old_string}",
                    error_type="missing_match",
                    ctx=ctx,
                    requested_path=file_path,
                    resolved_target_paths=[_to_workspace_relative(target, ctx.workspace_root)],
                )
            if matches > 1 and not replace_every:
                return _validation_error(
                    operation=operation,
                    execution_kind="file_write",
                    content=(
                        f"Found {matches} matches of the string to replace, but "
                        "replace_all is false. To replace all occurrences, set "
                        "replace_all to true. To replace only one occurrence, "
                        "provide more context to uniquely identify the instance.\n"
                        f"String: {old_string}"
                    ),
                    error_type="non_unique_match",
                    ctx=ctx,
                    requested_path=file_path,
                    resolved_target_paths=[_to_workspace_relative(target, ctx.workspace_root)],
                )
            new_content = (
                current_content.replace(old_string, new_string)
                if replace_every
                else current_content.replace(old_string, new_string, 1)
            )

        target.write_text(new_content, encoding="utf-8")
        _record_read_witness(ctx, target, new_content, offset=1, limit=None)
        return _write_success_result(
            operation=operation,
            ctx=ctx,
            target=target,
            content=f"Edited file: {_to_workspace_relative(target, ctx.workspace_root)}",
            created=False,
            content_delta_kind="edit",
            extra={
                "replace_all": replace_every,
                "old_string_empty": old_string == "",
            },
        )
    except Exception as exc:
        return _execution_error(
            operation=operation,
            execution_kind="file_write",
            content=f"File edit failed: {exc}",
            error_type="execution",
            ctx=ctx,
            requested_path=file_path,
            resolved_target_paths=[_to_workspace_relative(target, ctx.workspace_root)],
        )


def _claude_write_handler(
    file_path: str,
    content: str,
    *,
    ctx: ToolContext | None = None,
) -> ToolResult:
    operation = "Write"
    if ctx is None:
        return _missing_context_error(operation, execution_kind="file_write")

    try:
        target = resolve_and_validate_writable_path(
            file_path,
            ctx.workspace_root,
            allow_absolute=True,
            must_be_file=True,
            check_allowed_fn=ctx.is_file_allowed,
        )
    except PathPolicyError as exc:
        return _path_policy_error(
            exc,
            operation=operation,
            execution_kind="file_write",
            requested_path=file_path,
            ctx=ctx,
        )

    target_exists = target.exists()
    try:
        if target_exists:
            witness_error = _require_unchanged_full_read(ctx, target)
            if witness_error is not None:
                return _validation_error(
                    operation=operation,
                    execution_kind="file_write",
                    content=witness_error,
                    error_type="stale_read_state",
                    ctx=ctx,
                    requested_path=file_path,
                    resolved_target_paths=[_to_workspace_relative(target, ctx.workspace_root)],
                )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)

        target.write_text(content, encoding="utf-8")
        _record_read_witness(ctx, target, content, offset=1, limit=None)
        return _write_success_result(
            operation=operation,
            ctx=ctx,
            target=target,
            content=(
                f"{'Created' if not target_exists else 'Wrote'} file: "
                f"{_to_workspace_relative(target, ctx.workspace_root)}"
            ),
            created=not target_exists,
            content_delta_kind="create" if not target_exists else "overwrite",
        )
    except Exception as exc:
        return _execution_error(
            operation=operation,
            execution_kind="file_write",
            content=f"File write failed: {exc}",
            error_type="execution",
            ctx=ctx,
            requested_path=file_path,
            resolved_target_paths=[_to_workspace_relative(target, ctx.workspace_root)],
        )


def _claude_grep_handler(
    pattern: str,
    path: str | None = None,
    glob: str | None = None,
    output_mode: str | None = None,
    *,
    ctx: ToolContext | None = None,
    **kwargs: Any,
) -> ToolResult:
    operation = "Grep"
    if ctx is None:
        return _missing_context_error(operation, execution_kind="file_search")

    if not pattern:
        return _validation_error(
            operation=operation,
            execution_kind="file_search",
            content="pattern must not be empty",
            error_type="invalid_pattern",
            ctx=ctx,
            requested_path=path or ".",
        )

    requested_path = path or "."
    try:
        root = resolve_and_validate_path(
            requested_path,
            ctx.workspace_root,
            allow_absolute=True,
            must_exist=True,
        )
    except PathPolicyError as exc:
        return _path_policy_error(
            exc,
            operation=operation,
            execution_kind="file_search",
            requested_path=requested_path,
            ctx=ctx,
        )

    selected_mode = output_mode or "files_with_matches"
    before_context = _optional_int(kwargs.get("-B"))
    after_context = _optional_int(kwargs.get("-A"))
    shared_context = _optional_int(kwargs.get("-C"))
    if shared_context is None:
        shared_context = _optional_int(kwargs.get("context"))
    show_line_numbers = True if kwargs.get("-n") is None else bool(kwargs.get("-n"))
    ignore_case = bool(kwargs.get("-i"))
    file_type = kwargs.get("type")
    head_limit_raw = kwargs.get("head_limit")
    head_limit = _DEFAULT_GREP_HEAD_LIMIT if head_limit_raw is None else max(
        0, _optional_int(head_limit_raw, default=0)
    )
    offset = max(0, _optional_int(kwargs.get("offset"), default=0))
    multiline = bool(kwargs.get("multiline"))

    try:
        entries, backend = _run_claude_grep(
            pattern=pattern,
            root=root,
            workspace_root=ctx.workspace_root,
            path_glob=glob,
            output_mode=selected_mode,
            before_context=before_context,
            after_context=after_context,
            shared_context=shared_context,
            show_line_numbers=show_line_numbers,
            ignore_case=ignore_case,
            file_type=file_type if isinstance(file_type, str) else None,
            multiline=multiline,
            ctx=ctx,
        )
        sliced_entries, truncated = _slice_entries(entries, offset=offset, head_limit=head_limit)
        relative_root = _to_workspace_relative(root, ctx.workspace_root)
        if not sliced_entries:
            return ToolResult(
                ok=True,
                content="No matches found.",
                metadata=build_execution_metadata(
                    operation=operation,
                    execution_kind="file_search",
                    execution_stage="result_finalize",
                    policy_domain="filesystem",
                    policy_decision="allow",
                    dangerous=False,
                    command_family=operation,
                    workspace_root=ctx.workspace_root,
                    resolved_target_paths=[relative_root],
                    extra={
                        "family": _FAMILY,
                        "pattern": pattern,
                        "requested_path": requested_path,
                        "glob": glob,
                        "output_mode": selected_mode,
                        "backend": backend,
                        "entry_count": 0,
                        "truncated": truncated,
                    },
                ),
            )

        return ToolResult(
            ok=True,
            content="\n".join(sliced_entries),
            metadata=build_execution_metadata(
                operation=operation,
                execution_kind="file_search",
                execution_stage="result_finalize",
                policy_domain="filesystem",
                policy_decision="allow",
                dangerous=False,
                command_family=operation,
                workspace_root=ctx.workspace_root,
                resolved_target_paths=[relative_root],
                extra={
                    "family": _FAMILY,
                    "pattern": pattern,
                    "requested_path": requested_path,
                    "glob": glob,
                    "output_mode": selected_mode,
                    "backend": backend,
                    "entry_count": len(sliced_entries),
                    "truncated": truncated,
                    "offset": offset,
                    "head_limit": head_limit,
                    "ignore_case": ignore_case,
                    "type": file_type,
                    "multiline": multiline,
                },
            ),
        )
    except Exception as exc:
        return _execution_error(
            operation=operation,
            execution_kind="file_search",
            content=f"Grep failed: {exc}",
            error_type="execution",
            ctx=ctx,
            requested_path=requested_path,
            resolved_target_paths=[_to_workspace_relative(root, ctx.workspace_root)],
        )


def _claude_glob_handler(
    pattern: str,
    path: str | None = None,
    *,
    ctx: ToolContext | None = None,
) -> ToolResult:
    operation = "Glob"
    if ctx is None:
        return _missing_context_error(operation, execution_kind="file_search")

    requested_path = path or "."
    try:
        root = resolve_and_validate_path(
            requested_path,
            ctx.workspace_root,
            allow_absolute=True,
            must_exist=True,
            must_be_dir=True,
        )
    except PathPolicyError as exc:
        return _path_policy_error(
            exc,
            operation=operation,
            execution_kind="file_search",
            requested_path=requested_path,
            ctx=ctx,
        )

    try:
        matches: list[str] = []
        for candidate in sorted(root.glob(pattern)):
            relative_path = _to_workspace_relative(candidate, ctx.workspace_root)
            if candidate.is_file():
                if not ctx.is_file_allowed(relative_path):
                    continue
            elif candidate.is_dir():
                if not _has_allowed_descendant(candidate, ctx):
                    continue
            matches.append(relative_path)

        truncated = len(matches) > _MAX_GLOB_RESULTS
        rendered_matches = matches[:_MAX_GLOB_RESULTS]
        content_lines = list(rendered_matches)
        if truncated:
            content_lines.append(
                "(Results are truncated. Consider using a more specific path or pattern.)"
            )
        return ToolResult(
            ok=True,
            content="\n".join(content_lines) if content_lines else "No files found.",
            metadata=build_execution_metadata(
                operation=operation,
                execution_kind="file_search",
                execution_stage="result_finalize",
                policy_domain="filesystem",
                policy_decision="allow",
                dangerous=False,
                command_family=operation,
                workspace_root=ctx.workspace_root,
                resolved_target_paths=[_to_workspace_relative(root, ctx.workspace_root)],
                extra={
                    "family": _FAMILY,
                    "pattern": pattern,
                    "requested_path": requested_path,
                    "num_files": len(rendered_matches),
                    "truncated": truncated,
                },
            ),
        )
    except Exception as exc:
        return _execution_error(
            operation=operation,
            execution_kind="file_search",
            content=f"Glob failed: {exc}",
            error_type="execution",
            ctx=ctx,
            requested_path=requested_path,
            resolved_target_paths=[_to_workspace_relative(root, ctx.workspace_root)],
        )


def _run_claude_grep(
    *,
    pattern: str,
    root: Path,
    workspace_root: Path,
    path_glob: str | None,
    output_mode: str,
    before_context: int | None,
    after_context: int | None,
    shared_context: int | None,
    show_line_numbers: bool,
    ignore_case: bool,
    file_type: str | None,
    multiline: bool,
    ctx: ToolContext,
) -> tuple[list[str], str]:
    candidates = _iter_search_candidates(root, ctx, path_glob)
    rg_executable = shutil.which("rg")
    if rg_executable and candidates:
        try:
            return (
                _search_with_rg(
                    pattern=pattern,
                    candidates=candidates,
                    workspace_root=workspace_root,
                    rg_executable=rg_executable,
                    output_mode=output_mode,
                    before_context=before_context,
                    after_context=after_context,
                    shared_context=shared_context,
                    show_line_numbers=show_line_numbers,
                    ignore_case=ignore_case,
                    file_type=file_type,
                    multiline=multiline,
                    path_glob=path_glob,
                ),
                "rg",
            )
        except (OSError, subprocess.SubprocessError):
            pass
    return (
        _search_with_python(
            pattern=pattern,
            candidates=candidates,
            output_mode=output_mode,
            ignore_case=ignore_case,
            multiline=multiline,
        ),
        "python",
    )


def _search_with_rg(
    *,
    pattern: str,
    candidates: list[tuple[Path, str]],
    workspace_root: Path,
    rg_executable: str,
    output_mode: str,
    before_context: int | None,
    after_context: int | None,
    shared_context: int | None,
    show_line_numbers: bool,
    ignore_case: bool,
    file_type: str | None,
    multiline: bool,
    path_glob: str | None,
) -> list[str]:
    args = [rg_executable, "--color", "never"]
    if output_mode == "files_with_matches":
        args.append("-l")
    elif output_mode == "count":
        args.append("-c")
    else:
        args.append("--with-filename")
        if show_line_numbers:
            args.append("-n")
        if shared_context is not None:
            args.extend(["-C", str(shared_context)])
        else:
            if before_context is not None:
                args.extend(["-B", str(before_context)])
            if after_context is not None:
                args.extend(["-A", str(after_context)])
    if ignore_case:
        args.append("-i")
    if file_type:
        args.extend(["--type", file_type])
    if multiline:
        args.extend(["-U", "--multiline-dotall"])
    if path_glob:
        args.extend(["--glob", path_glob])
    args.extend(["--", pattern])
    args.extend(rel_path for _, rel_path in candidates)
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=workspace_root,
    )
    if proc.returncode not in {0, 1}:
        raise OSError(proc.stderr.strip() or f"rg exited with code {proc.returncode}")
    return [line for line in proc.stdout.splitlines() if line]


def _search_with_python(
    *,
    pattern: str,
    candidates: list[tuple[Path, str]],
    output_mode: str,
    ignore_case: bool,
    multiline: bool,
) -> list[str]:
    flags = re.IGNORECASE if ignore_case else 0
    if multiline:
        flags |= re.DOTALL
    compiled = re.compile(pattern, flags)
    if output_mode == "files_with_matches":
        matches: list[str] = []
        for full_path, rel_path in candidates:
            text = full_path.read_text(encoding="utf-8", errors="replace")
            if compiled.search(text):
                matches.append(rel_path)
        return matches
    if output_mode == "count":
        counts: list[str] = []
        for full_path, rel_path in candidates:
            text = full_path.read_text(encoding="utf-8", errors="replace")
            count = len(list(compiled.finditer(text)))
            if count:
                counts.append(f"{rel_path}:{count}")
        return counts

    content_matches: list[str] = []
    for full_path, rel_path in candidates:
        lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line_number, line in enumerate(lines, start=1):
            if compiled.search(line):
                content_matches.append(f"{rel_path}:{line_number}: {line}")
    return content_matches


def _iter_search_candidates(
    root: Path,
    ctx: ToolContext,
    path_glob: str | None,
) -> list[tuple[Path, str]]:
    if root.is_file():
        relative = _to_workspace_relative(root, ctx.workspace_root)
        if ctx.is_file_allowed(relative) and (
            path_glob is None or Path(relative).match(path_glob)
        ):
            return [(root, relative)]
        return []

    candidates: list[tuple[Path, str]] = []
    for dir_path, dir_names, file_names in os.walk(root):
        dir_names[:] = sorted(d for d in dir_names if d not in _IGNORED_DIRS)
        for file_name in sorted(file_names):
            full_path = Path(dir_path) / file_name
            relative = _to_workspace_relative(full_path, ctx.workspace_root)
            if not ctx.is_file_allowed(relative):
                continue
            if path_glob and not Path(relative).match(path_glob):
                continue
            if full_path.suffix.lower() in _BINARY_SUFFIXES:
                continue
            candidates.append((full_path, relative))
    return candidates


def _slice_entries(
    entries: list[str],
    *,
    offset: int,
    head_limit: int,
) -> tuple[list[str], bool]:
    sliced = entries[offset:]
    if head_limit == 0:
        return sliced, False
    truncated = len(sliced) > head_limit
    return sliced[:head_limit], truncated


def _record_read_witness(
    ctx: ToolContext,
    target: Path,
    content: str,
    *,
    offset: int,
    limit: int | None,
) -> None:
    witnesses = ctx.tool_state.setdefault(_READ_STATE_KEY, {})
    witnesses[str(target.resolve())] = {
        "content": content,
        "timestamp": _mtime_ms(target),
        "offset": offset,
        "limit": limit,
        "is_partial_view": not (offset == 1 and limit is None),
    }


def _require_unchanged_full_read(ctx: ToolContext, target: Path) -> str | None:
    witness = ctx.tool_state.get(_READ_STATE_KEY, {}).get(str(target.resolve()))
    if not witness or witness.get("is_partial_view"):
        return "File has not been read yet. Read it first before writing to it."

    current_content = target.read_text(encoding="utf-8", errors="replace")
    current_mtime = _mtime_ms(target)
    if current_mtime > int(witness["timestamp"]) and current_content != str(
        witness["content"]
    ):
        return (
            "File has been modified since read, either by the user or by a "
            "linter. Read it again before attempting to write it."
        )
    return None


def _validate_pages_parameter(pages: str | None) -> str | None:
    if pages is None:
        return None
    match = re.fullmatch(r"\s*(\d+)(?:-(\d+))?\s*", pages)
    if match is None:
        return (
            f'Invalid pages parameter: "{pages}". Use formats like "1-5", "3", '
            'or "10-20". Pages are 1-indexed.'
        )
    first_page = int(match.group(1))
    last_page = int(match.group(2) or match.group(1))
    if first_page <= 0 or last_page < first_page:
        return (
            f'Invalid pages parameter: "{pages}". Use formats like "1-5", "3", '
            'or "10-20". Pages are 1-indexed.'
        )
    if last_page - first_page + 1 > _PDF_MAX_PAGES_PER_READ:
        return (
            f'Page range "{pages}" exceeds maximum of {_PDF_MAX_PAGES_PER_READ} '
            "pages per request. Please use a smaller range."
        )
    return None


def _write_success_result(
    *,
    operation: str,
    ctx: ToolContext,
    target: Path,
    content: str,
    created: bool,
    content_delta_kind: str,
    extra: dict[str, Any] | None = None,
) -> ToolResult:
    relative_path = _to_workspace_relative(target, ctx.workspace_root)
    return ToolResult(
        ok=True,
        content=content,
        metadata=build_execution_metadata(
            operation=operation,
            execution_kind="file_write",
            execution_stage="result_finalize",
            policy_domain="filesystem",
            policy_decision="allow",
            dangerous=False,
            command_family=operation,
            workspace_root=ctx.workspace_root,
            resolved_target_paths=[relative_path],
            extra={
                "family": _FAMILY,
                "workspace_relative_path": relative_path,
                "resolved_path": str(target),
                "created": created,
                "content_delta_kind": content_delta_kind,
                "files_modified": [relative_path],
                "change_applied": True,
                "change_summary_present": True,
                **(extra or {}),
            },
        ),
    )


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
            command_family=operation,
            extra={"family": _FAMILY, "error_type": "missing_context"},
        ),
    )


def _validation_error(
    *,
    operation: str,
    execution_kind: str,
    content: str,
    error_type: str,
    ctx: ToolContext | None,
    requested_path: str | None,
    resolved_target_paths: list[str] | None = None,
) -> ToolResult:
    return ToolResult(
        ok=False,
        content=content,
        is_error=True,
        metadata=build_execution_metadata(
            operation=operation,
            execution_kind=execution_kind,
            execution_stage="validate_input",
            policy_domain="filesystem",
            policy_decision="deny",
            policy_reason=content,
            policy_reason_code=error_type,
            dangerous=False,
            command_family=operation,
            workspace_root=None if ctx is None else ctx.workspace_root,
            resolved_target_paths=resolved_target_paths,
            extra={
                "family": _FAMILY,
                "error_type": error_type,
                "requested_path": requested_path,
            },
        ),
    )


def _path_policy_error(
    error: PathPolicyError,
    *,
    operation: str,
    execution_kind: str,
    requested_path: str,
    ctx: ToolContext,
) -> ToolResult:
    metadata = build_execution_metadata(
        operation=operation,
        execution_kind=execution_kind,
        execution_stage="validate_target",
        policy_domain=error.metadata.get("policy_domain", "filesystem"),
        policy_decision=error.metadata.get("policy_decision", "deny"),
        policy_reason=error.metadata.get("policy_reason", str(error)),
        policy_reason_code=error.metadata.get("policy_reason_code", error.error_type),
        dangerous=error.metadata.get(
            "dangerous",
            error.error_type in {"absolute_path", "workspace_escape", "protected_path"},
        ),
        command_family=operation,
        workspace_root=ctx.workspace_root,
        extra={
            "family": _FAMILY,
            "error_type": error.error_type,
            "requested_path": requested_path,
        },
    )
    for key, value in error.metadata.items():
        metadata.setdefault(key, value)
    return ToolResult(ok=False, content=str(error), is_error=True, metadata=metadata)


def _execution_error(
    *,
    operation: str,
    execution_kind: str,
    content: str,
    error_type: str,
    ctx: ToolContext,
    requested_path: str | None,
    resolved_target_paths: list[str] | None,
) -> ToolResult:
    return ToolResult(
        ok=False,
        content=content,
        is_error=True,
        metadata=build_execution_metadata(
            operation=operation,
            execution_kind=execution_kind,
            execution_stage="handler_execution",
            policy_domain="filesystem",
            policy_decision="allow",
            dangerous=False,
            command_family=operation,
            workspace_root=ctx.workspace_root,
            resolved_target_paths=resolved_target_paths,
            extra={
                "family": _FAMILY,
                "error_type": error_type,
                "requested_path": requested_path,
            },
        ),
    )


def _relabel_result(
    result: ToolResult,
    *,
    operation: str,
    command_family: str,
    family: str,
    extra: dict[str, Any] | None = None,
) -> ToolResult:
    metadata = dict(result.metadata)
    metadata["operation"] = operation
    metadata["command_family"] = command_family
    metadata["family"] = family
    if extra:
        metadata.update(extra)
    return ToolResult(
        ok=result.ok,
        content=result.content,
        metadata=metadata,
        is_error=result.is_error,
    )


def _truncate_text(text: str, limit: int = _MAX_TEXT_OUTPUT_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n... [truncated at {limit} chars]", True


def _optional_int(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def _mtime_ms(path: Path) -> int:
    return int(path.stat().st_mtime_ns / 1_000_000)


def _to_workspace_relative(full: Path, workspace_root: Path) -> str:
    rel = full.resolve().relative_to(workspace_root.resolve())
    return str(PurePosixPath(*rel.parts)) if rel.parts else "."


def _has_allowed_descendant(dir_path: Path, ctx: ToolContext) -> bool:
    for dir_path_str, dir_names, file_names in os.walk(dir_path):
        dir_names[:] = [d for d in dir_names if d not in _IGNORED_DIRS]
        for file_name in file_names:
            full_path = Path(dir_path_str) / file_name
            if ctx.is_file_allowed(_to_workspace_relative(full_path, ctx.workspace_root)):
                return True
    return False


def _bash_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "number"},
            "description": {"type": "string"},
            "run_in_background": {"type": "boolean"},
            "dangerouslyDisableSandbox": {"type": "boolean"},
        },
        "required": ["command"],
        "additionalProperties": False,
    }


def _read_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1},
            "pages": {"type": "string"},
        },
        "required": ["file_path"],
        "additionalProperties": False,
    }


def _edit_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean"},
        },
        "required": ["file_path", "old_string", "new_string"],
        "additionalProperties": False,
    }


def _write_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["file_path", "content"],
        "additionalProperties": False,
    }


def _grep_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
            "glob": {"type": "string"},
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_with_matches", "count"],
            },
            "-B": {"type": "number"},
            "-A": {"type": "number"},
            "-C": {"type": "number"},
            "context": {"type": "number"},
            "-n": {"type": "boolean"},
            "-i": {"type": "boolean"},
            "type": {"type": "string"},
            "head_limit": {"type": "number"},
            "offset": {"type": "number"},
            "multiline": {"type": "boolean"},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }


def _glob_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }
