"""Built-in apply_patch tool that applies unified diffs inside the workspace.

All target paths are validated to stay within workspace and respect task
constraints (allowed_files / forbidden_files).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath

from pycodeagent.env.path_policy import (
    PathPolicyError,
    make_error_result,
    resolve_and_validate_writable_path,
)
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.execution_contract import build_execution_metadata
from pycodeagent.tools.spec import CanonicalTool
from pycodeagent.trajectory.schema import ToolResult

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_HUNK_FUZZ_WINDOW = 3


def _apply_patch_handler(
    diff: str,
    *,
    ctx: ToolContext | None = None,
) -> ToolResult:
    """Parse a unified diff and apply it to workspace files."""
    if not diff or not diff.strip():
        return ToolResult(
            ok=False,
            content="Empty diff",
            is_error=True,
            metadata=build_execution_metadata(
                operation="apply_patch",
                execution_kind="patch_apply",
                execution_stage="validate_input",
                policy_domain="filesystem",
                policy_decision="deny",
                policy_reason="Empty diff",
                policy_reason_code="empty_diff",
                dangerous=False,
                resolved_target_paths=[],
                extra={
                    "error_type": "empty_diff",
                    "target_files": [],
                },
            ),
        )

    if ctx is None:
        return ToolResult(
            ok=False,
            content="ToolContext is required for workspace enforcement",
            is_error=True,
            metadata=build_execution_metadata(
                operation="apply_patch",
                execution_kind="patch_apply",
                execution_stage="context_check",
                policy_domain="filesystem",
                policy_decision="deny",
                policy_reason="ToolContext is required for workspace enforcement",
                policy_reason_code="missing_context",
                dangerous=False,
                resolved_target_paths=[],
                extra={
                    "error_type": "missing_context",
                    "target_files": [],
                },
            ),
        )

    target_files: list[str] = []
    try:
        file_patches = _collect_file_patches(diff)
        target_files = [file_patch.target_path for file_patch in file_patches]
        applied_ops, hunks_applied = _apply_unified_diff(diff, ctx)
    except _PatchError as exc:
        if not target_files:
            target_files = _collect_target_file_candidates(diff)
        return ToolResult(
            ok=False,
            content=f"Patch failed: {exc}",
            is_error=True,
            metadata=build_execution_metadata(
                operation="apply_patch",
                execution_kind="patch_apply",
                execution_stage="handler_execution",
                policy_domain="filesystem",
                policy_decision="allow",
                dangerous=False,
                workspace_root=ctx.workspace_root,
                resolved_target_paths=target_files,
                extra={
                    "error_type": "patch_apply",
                    "target_files": target_files,
                },
            ),
        )
    except PathPolicyError as exc:
        return make_error_result(
            exc,
            extra_metadata={
                "operation": "apply_patch",
                "execution_kind": "patch_apply",
                "stage": "validate_target",
                "execution_stage": "validate_target",
                "workspace_root": str(ctx.workspace_root),
                "target_files": target_files,
            },
        )
    except Exception as exc:
        return ToolResult(
            ok=False,
            content=f"Unexpected patch error: {exc}",
            is_error=True,
            metadata=build_execution_metadata(
                operation="apply_patch",
                execution_kind="patch_apply",
                execution_stage="handler_execution",
                policy_domain="filesystem",
                policy_decision="allow",
                dangerous=False,
                workspace_root=ctx.workspace_root,
                resolved_target_paths=target_files,
                extra={
                    "error_type": "patch_unexpected",
                    "target_files": target_files,
                },
            ),
        )

    return ToolResult(
        ok=True,
        content="Patch applied successfully. Modified files:\n"
        + "\n".join(f"  - {path}" for path in [op.path for op in applied_ops]),
        metadata=build_execution_metadata(
            operation="apply_patch",
            execution_kind="patch_apply",
            execution_stage="result_finalize",
            policy_domain="filesystem",
            policy_decision="allow",
            dangerous=False,
            workspace_root=ctx.workspace_root,
            resolved_target_paths=[op.path for op in applied_ops],
            extra=_build_patch_result_metadata(applied_ops, hunks_applied),
        ),
    )


class _PatchError(Exception):
    """Raised when a patch cannot be applied."""


@dataclass(frozen=True)
class _FilePatch:
    """One file-level patch entry from a unified diff."""

    operation: str
    old_path: str | None
    new_path: str | None
    target_path: str


@dataclass(frozen=True)
class _AppliedFileOperation:
    path: str
    operation: str
    hunks_applied: int


def _collect_file_patches(diff: str) -> list[_FilePatch]:
    """Parse diff headers into file-level patch operations."""
    lines = diff.splitlines(keepends=True)
    file_patches: list[_FilePatch] = []
    index = 0

    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue

        old_header = lines[index].rstrip("\n")
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise _PatchError(f"Expected +++ header after {old_header!r}")

        new_header = lines[index].rstrip("\n")
        index += 1
        file_patches.append(_parse_file_headers(old_header, new_header))

    return file_patches


def _collect_target_file_candidates(diff: str) -> list[str]:
    """Best-effort extraction of patch target files for early parse failures."""
    lines = diff.splitlines(keepends=False)
    targets: list[str] = []
    index = 0

    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        old_path = _extract_path(lines[index])
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            break
        new_path = _extract_path(lines[index])
        index += 1
        candidate = new_path if new_path not in {None, "/dev/null"} else old_path
        if candidate not in {None, "/dev/null"}:
            targets.append(candidate)

    return targets


def _build_patch_result_metadata(
    applied_ops: list[_AppliedFileOperation],
    total_hunks: int,
) -> dict[str, object]:
    target_files = [op.path for op in applied_ops]
    file_operations = [
        {
            "path": op.path,
            "operation": op.operation,
            "hunks_applied": op.hunks_applied,
        }
        for op in applied_ops
    ]
    created_count = sum(1 for op in applied_ops if op.operation == "create")
    modified_count = sum(1 for op in applied_ops if op.operation == "modify")
    deleted_count = sum(1 for op in applied_ops if op.operation == "delete")
    return {
        "files_modified": target_files,
        "target_files": target_files,
        "file_operations": file_operations,
        "patch_applied": True,
        "change_applied": True,
        "change_summary_present": True,
        "content_delta_kind": "patch",
        "operation_count": len(applied_ops),
        "hunks_applied": total_hunks,
        "created_count": created_count,
        "modified_count": modified_count,
        "deleted_count": deleted_count,
    }


def _apply_unified_diff(diff: str, ctx: ToolContext) -> tuple[list[_AppliedFileOperation], int]:
    """Apply a unified diff and return modified repo-relative file paths."""
    lines = diff.splitlines(keepends=True)
    applied_ops: list[_AppliedFileOperation] = []
    total_hunks = 0
    index = 0

    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue

        old_header = lines[index].rstrip("\n")
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise _PatchError(f"Expected +++ header after {old_header!r}")

        new_header = lines[index].rstrip("\n")
        index += 1

        file_patch = _parse_file_headers(old_header, new_header)
        target = _resolve_patch_target(file_patch, ctx)

        if file_patch.operation == "create":
            current_lines: list[str] = []
        else:
            current_lines = target.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines(keepends=True)

        line_offset = 0
        hunk_count = 0
        while index < len(lines) and lines[index].startswith("@@"):
            current_lines, index, line_offset = _apply_hunk(
                lines,
                index,
                current_lines,
                line_offset,
            )
            hunk_count += 1
            total_hunks += 1

        if file_patch.operation == "modify" and hunk_count == 0:
            raise _PatchError(f"No hunks found for file patch: {file_patch.target_path}")

        if file_patch.operation == "delete":
            if current_lines:
                raise _PatchError(
                    f"Deletion patch for {file_patch.target_path!r} did not remove all content"
                )
            _delete_file(target)
        else:
            if file_patch.operation == "create":
                target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("".join(current_lines), encoding="utf-8")

        rel_path = target.relative_to(ctx.workspace_root)
        applied_ops.append(
            _AppliedFileOperation(
                path=str(PurePosixPath(*rel_path.parts)),
                operation=file_patch.operation,
                hunks_applied=hunk_count,
            )
        )

    if not applied_ops:
        raise _PatchError("No valid file patches found in diff")

    return applied_ops, total_hunks


def _parse_file_headers(old_header: str, new_header: str) -> _FilePatch:
    """Resolve old/new headers into a concrete file operation."""
    old_path = _extract_path(old_header)
    new_path = _extract_path(new_header)

    if old_path is None or new_path is None:
        raise _PatchError(f"Malformed file headers: {old_header!r}, {new_header!r}")

    if old_path == "/dev/null" and new_path == "/dev/null":
        raise _PatchError("Patch cannot use /dev/null for both old and new paths")

    if old_path == "/dev/null":
        return _FilePatch(
            operation="create",
            old_path=None,
            new_path=new_path,
            target_path=new_path,
        )

    if new_path == "/dev/null":
        return _FilePatch(
            operation="delete",
            old_path=old_path,
            new_path=None,
            target_path=old_path,
        )

    if old_path != new_path:
        raise _PatchError(
            f"File rename patches are not supported: {old_path!r} -> {new_path!r}"
        )

    return _FilePatch(
        operation="modify",
        old_path=old_path,
        new_path=new_path,
        target_path=new_path,
    )


def _resolve_patch_target(file_patch: _FilePatch, ctx: ToolContext) -> Path:
    """Resolve and validate the concrete target path for a file patch."""
    if file_patch.operation == "create":
        return resolve_and_validate_writable_path(
            file_patch.target_path,
            ctx.workspace_root,
            check_allowed_fn=ctx.is_file_allowed,
        )

    return resolve_and_validate_writable_path(
        file_patch.target_path,
        ctx.workspace_root,
        must_exist=True,
        must_be_file=True,
        check_allowed_fn=ctx.is_file_allowed,
    )


def _delete_file(target: Path) -> None:
    """Delete a file, surfacing filesystem failures as patch errors."""
    try:
        try:
            target.chmod(target.stat().st_mode | 0o200)
        except OSError:
            pass
        target.unlink()
    except OSError as exc:
        raise _PatchError(f"Unable to delete file {target}: {exc}") from exc


def _extract_path(header_line: str) -> str | None:
    """Extract the file path from a ``---`` or ``+++`` header."""
    parts = header_line.split(None, 1)
    if len(parts) < 2:
        return None

    raw = parts[1].split("\t", 1)[0].strip()
    if raw.startswith("a/") or raw.startswith("b/"):
        raw = raw[2:]
    return raw


def _apply_hunk(
    lines: list[str],
    start: int,
    file_lines: list[str],
    line_offset: int,
) -> tuple[list[str], int, int]:
    """Apply a single hunk and return updated lines, next index, and offset."""
    header = lines[start].rstrip("\n")
    match = _HUNK_HEADER_RE.match(header)
    if not match:
        raise _PatchError(f"Malformed hunk header: {header!r}")

    old_start = int(match.group(1))
    old_count = int(match.group(2) or "1")
    new_count = int(match.group(4) or "1")
    index = start + 1

    old_segment: list[str] = []
    new_segment: list[str] = []
    consumed_old = 0
    consumed_new = 0
    last_kind: str | None = None

    while index < len(lines):
        line = lines[index]
        if line.startswith("@@") or line.startswith("--- "):
            break

        if line.startswith("\\"):
            if line.rstrip("\n") == "\\ No newline at end of file":
                if last_kind in {" ", "-"} and old_segment:
                    old_segment[-1] = old_segment[-1].rstrip("\n")
                if last_kind in {" ", "+"} and new_segment:
                    new_segment[-1] = new_segment[-1].rstrip("\n")
                index += 1
                continue
            raise _PatchError(f"Unsupported patch marker: {line.rstrip()!r}")

        if not line or line[0] not in {" ", "+", "-"}:
            break

        kind = line[0]
        payload = line[1:]
        if kind == " ":
            old_segment.append(payload)
            new_segment.append(payload)
            consumed_old += 1
            consumed_new += 1
        elif kind == "-":
            old_segment.append(payload)
            consumed_old += 1
        else:
            new_segment.append(payload)
            consumed_new += 1

        last_kind = kind
        index += 1

    if consumed_old != old_count or consumed_new != new_count:
        raise _PatchError(
            "Hunk line count mismatch: "
            f"expected -{old_count}/+{new_count}, got -{consumed_old}/+{consumed_new}"
        )

    suggested_index = max(0, old_start - 1 + line_offset)
    if old_segment:
        apply_index = _find_hunk_position(file_lines, old_segment, suggested_index)
    else:
        apply_index = min(suggested_index, len(file_lines))

    updated_lines = (
        file_lines[:apply_index]
        + new_segment
        + file_lines[apply_index + len(old_segment) :]
    )
    new_offset = line_offset + (apply_index - suggested_index) + (
        len(new_segment) - len(old_segment)
    )
    return updated_lines, index, new_offset


def _find_hunk_position(
    file_lines: list[str],
    expected_old: list[str],
    suggested_index: int,
) -> int:
    """Locate the best position for a hunk, allowing a small context shift."""
    if _segment_matches(file_lines, suggested_index, expected_old):
        return suggested_index

    max_index = len(file_lines) - len(expected_old)
    if max_index < 0:
        raise _PatchError("Hunk context extends beyond end of file")

    candidates: list[int] = []
    begin = max(0, suggested_index - _HUNK_FUZZ_WINDOW)
    end = min(max_index, suggested_index + _HUNK_FUZZ_WINDOW)
    for candidate in range(begin, end + 1):
        if _segment_matches(file_lines, candidate, expected_old):
            candidates.append(candidate)

    if not candidates:
        raise _PatchError(
            f"Hunk context mismatch near line {suggested_index + 1}"
        )

    if len(candidates) == 1:
        return candidates[0]

    ranked = sorted(candidates, key=lambda value: abs(value - suggested_index))
    if abs(ranked[0] - suggested_index) == abs(ranked[1] - suggested_index):
        raise _PatchError(
            f"Ambiguous hunk location near line {suggested_index + 1}"
        )
    return ranked[0]


def _segment_matches(
    file_lines: list[str],
    start: int,
    expected_old: list[str],
) -> bool:
    """Return True when a file segment matches the expected old hunk content."""
    end = start + len(expected_old)
    if start < 0 or end > len(file_lines):
        return False
    return file_lines[start:end] == expected_old


apply_patch_tool = CanonicalTool(
    canonical_name="apply_patch",
    description="Apply a unified diff patch to workspace files.",
    canonical_schema={
        "type": "object",
        "properties": {
            "diff": {
                "type": "string",
                "description": "Unified diff string to apply.",
            },
        },
        "required": ["diff"],
    },
    handler=_apply_patch_handler,
)
