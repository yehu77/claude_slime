"""Built-in search_code tool with an rg-first backend and Python fallback.

All paths are validated to stay within workspace and respect task constraints.
Output paths are always workspace-relative POSIX paths.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from pathlib import PurePosixPath

from pycodeagent.env.path_policy import (
    PathPolicyError,
    make_error_result,
    resolve_and_validate_path,
)
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.execution_contract import build_execution_metadata
from pycodeagent.tools.spec import CanonicalTool
from pycodeagent.trajectory.schema import ToolResult

_MAX_MATCHES = 200
_MAX_LINE_CHARS = 300
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
    ".gif",
    ".zip",
    ".tar",
    ".gz",
}
_RG_BATCH_SIZE = 100
_RG_BATCH_PATH_CHARS = 8_000


def _to_workspace_relative(full: Path, workspace_root: Path) -> str:
    """Convert an absolute path to a workspace-relative POSIX string."""
    rel = full.relative_to(workspace_root)
    return str(PurePosixPath(*rel.parts)) if rel.parts else "."


def _iter_search_candidates(
    root: Path,
    ctx: ToolContext,
    glob_pattern: str | None,
) -> list[tuple[Path, str]]:
    """Return searchable files as ``(absolute_path, workspace_relative_path)``."""
    candidates: list[tuple[Path, str]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _IGNORED_DIRS)
        for fname in sorted(filenames):
            full = Path(dirpath) / fname
            rel_path = _to_workspace_relative(full, ctx.workspace_root)
            if not ctx.is_file_allowed(rel_path):
                continue
            if glob_pattern and not Path(rel_path).match(glob_pattern):
                continue
            if full.suffix.lower() in _BINARY_SUFFIXES:
                continue
            candidates.append((full, rel_path))

    return candidates


def _format_search_match(rel_path: str, lineno: int, line: str) -> str:
    """Format one search hit in the stable tool output form."""
    display_line = line.rstrip()
    if len(display_line) > _MAX_LINE_CHARS:
        display_line = display_line[:_MAX_LINE_CHARS] + "..."
    return f"{rel_path}:{lineno}: {display_line}"


def _search_with_python(
    query: str,
    candidates: list[tuple[Path, str]],
) -> tuple[list[str], bool]:
    """Search candidates with the legacy Python fallback backend."""
    matches: list[str] = []
    query_lower = query.lower()

    for full, rel_path in candidates:
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, start=1):
                    if query_lower in line.lower():
                        matches.append(_format_search_match(rel_path, lineno, line))
                        if len(matches) >= _MAX_MATCHES:
                            return matches, True
        except (OSError, UnicodeDecodeError):
            continue

    return matches, False


def _iter_rg_batches(rel_paths: list[str]):
    """Yield workspace-relative file batches sized for safe command lines."""
    batch: list[str] = []
    batch_chars = 0

    for rel_path in rel_paths:
        rel_chars = len(rel_path) + 1
        if batch and (
            len(batch) >= _RG_BATCH_SIZE
            or batch_chars + rel_chars > _RG_BATCH_PATH_CHARS
        ):
            yield batch
            batch = []
            batch_chars = 0

        batch.append(rel_path)
        batch_chars += rel_chars

    if batch:
        yield batch


def _search_with_rg(
    query: str,
    candidates: list[tuple[Path, str]],
    workspace_root: Path,
    rg_executable: str,
) -> tuple[list[str], bool]:
    """Search candidates with ripgrep, returning matches and truncation flag."""
    matches: list[str] = []
    rel_paths = [rel_path for _, rel_path in candidates]

    for batch in _iter_rg_batches(rel_paths):
        proc = subprocess.run(
            [
                rg_executable,
                "--line-number",
                "--with-filename",
                "--color",
                "never",
                "--fixed-strings",
                "--ignore-case",
                "--",
                query,
                *batch,
            ],
            capture_output=True,
            text=True,
            cwd=workspace_root,
        )
        if proc.returncode not in {0, 1}:
            raise OSError(proc.stderr.strip() or f"rg exited with code {proc.returncode}")

        for raw_line in proc.stdout.splitlines():
            try:
                rel_path, lineno_text, line = raw_line.split(":", 2)
                lineno = int(lineno_text)
            except ValueError:
                continue
            matches.append(_format_search_match(rel_path, lineno, line))
            if len(matches) >= _MAX_MATCHES:
                return matches, True

    return matches, False


def _search_code_handler(
    query: str,
    path: str = ".",
    glob_pattern: str | None = None,
    *,
    ctx: ToolContext | None = None,
) -> ToolResult:
    """Search for *query* in text files under *path* within workspace."""
    if not query:
        return ToolResult(
            ok=False,
            content="query must not be empty",
            is_error=True,
            metadata=build_execution_metadata(
                operation="search_code",
                execution_kind="file_search",
                execution_stage="validate_input",
                policy_domain="filesystem",
                policy_decision="deny",
                policy_reason="query must not be empty",
                policy_reason_code="invalid_query",
                dangerous=False,
                extra={
                    "error_type": "invalid_query",
                    "requested_path": path,
                    "query": query,
                },
            ),
        )

    if ctx is None:
        return ToolResult(
            ok=False,
            content="ToolContext is required for workspace enforcement",
            is_error=True,
            metadata=build_execution_metadata(
                operation="search_code",
                execution_kind="file_search",
                execution_stage="context_check",
                policy_domain="filesystem",
                policy_decision="deny",
                policy_reason="ToolContext is required for workspace enforcement",
                policy_reason_code="missing_context",
                dangerous=False,
                extra={"error_type": "missing_context"},
            ),
        )

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
                "operation": "search_code",
                "execution_kind": "file_search",
                "stage": "validate_target",
                "execution_stage": "validate_target",
                "workspace_root": str(ctx.workspace_root),
                "requested_path": path,
                "query": query,
                "glob_pattern": glob_pattern,
            },
        )

    try:
        candidates = _iter_search_candidates(root, ctx, glob_pattern)
        rg_executable = shutil.which("rg")
        backend = "python"
        truncated = False

        if rg_executable:
            try:
                matches, truncated = _search_with_rg(
                    query,
                    candidates,
                    ctx.workspace_root,
                    rg_executable,
                )
                backend = "rg"
            except (OSError, subprocess.SubprocessError):
                matches, truncated = _search_with_python(query, candidates)
        else:
            matches, truncated = _search_with_python(query, candidates)

        metadata = {
            "query": query,
            "requested_path": path,
            "workspace_relative_root": _to_workspace_relative(root, ctx.workspace_root),
            "resolved_path": str(root),
            "glob_pattern": glob_pattern,
            "backend": backend,
            "candidate_file_count": len(candidates),
            "match_count": len(matches),
            "truncated": truncated,
        }

        if not matches:
            return ToolResult(
                ok=True,
                content="No matches found.",
                metadata=build_execution_metadata(
                    operation="search_code",
                    execution_kind="file_search",
                    execution_stage="result_finalize",
                    policy_domain="filesystem",
                    policy_decision="allow",
                    dangerous=False,
                    workspace_root=ctx.workspace_root,
                    resolved_target_paths=[
                        _to_workspace_relative(root, ctx.workspace_root)
                    ],
                    extra=metadata,
                ),
            )

        content = "\n".join(matches)
        if truncated:
            content += f"\n... [stopped at {_MAX_MATCHES} matches]"
        return ToolResult(
            ok=True,
            content=content,
            metadata=build_execution_metadata(
                operation="search_code",
                execution_kind="file_search",
                execution_stage="result_finalize",
                policy_domain="filesystem",
                policy_decision="allow",
                dangerous=False,
                workspace_root=ctx.workspace_root,
                resolved_target_paths=[
                    _to_workspace_relative(root, ctx.workspace_root)
                ],
                extra=metadata,
            ),
        )

    except Exception as exc:
        return ToolResult(
            ok=False,
            content=f"Search failed: {exc}",
            is_error=True,
            metadata=build_execution_metadata(
                operation="search_code",
                execution_kind="file_search",
                execution_stage="handler_execution",
                policy_domain="filesystem",
                policy_decision="allow",
                dangerous=False,
                workspace_root=ctx.workspace_root,
                resolved_target_paths=[
                    _to_workspace_relative(root, ctx.workspace_root)
                ],
                extra={
                    "error_type": "execution",
                    "requested_path": path,
                    "query": query,
                    "glob_pattern": glob_pattern,
                },
            ),
        )


search_code_tool = CanonicalTool(
    canonical_name="search_code",
    description="Search for text in workspace files.",
    canonical_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Text to search for."},
            "path": {"type": "string", "description": "Root directory to search (default '.')."},
            "glob_pattern": {
                "type": "string",
                "description": "Optional glob to filter filenames (e.g. '*.py').",
            },
        },
        "required": ["query"],
    },
    handler=_search_code_handler,
)
