"""Shared patch-application primitives for legacy and family runtimes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath

from pycodeagent.env.path_policy import resolve_and_validate_writable_path
from pycodeagent.tools.context import ToolContext

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_HUNK_FUZZ_WINDOW = 3
_STRICT_PATCH_BEGIN = "*** Begin Patch"
_STRICT_PATCH_END = "*** End Patch"
_STRICT_ENVIRONMENT_PREFIX = "*** Environment ID: "
_STRICT_ADD_FILE_PREFIX = "*** Add File: "
_STRICT_DELETE_FILE_PREFIX = "*** Delete File: "
_STRICT_UPDATE_FILE_PREFIX = "*** Update File: "
_STRICT_MOVE_TO_PREFIX = "*** Move to: "
_STRICT_END_OF_FILE = "*** End of File"


class PatchApplyError(Exception):
    """Raised when a patch cannot be applied."""


@dataclass(frozen=True)
class FilePatch:
    """One file-level patch entry from a unified diff."""

    operation: str
    old_path: str | None
    new_path: str | None
    target_path: str


@dataclass(frozen=True)
class AppliedFileOperation:
    """One successful file mutation produced by patch application."""

    path: str
    operation: str
    hunks_applied: int


@dataclass(frozen=True)
class StrictPatchChunk:
    """One Codex-style update chunk inside a freeform apply_patch body."""

    change_context: str | None
    old_lines: tuple[str, ...]
    new_lines: tuple[str, ...]
    is_end_of_file: bool = False


@dataclass(frozen=True)
class StrictPatchOperation:
    """One Codex-style file operation parsed from a freeform apply_patch body."""

    operation: str
    path: str
    move_path: str | None = None
    add_lines: tuple[str, ...] = ()
    chunks: tuple[StrictPatchChunk, ...] = ()


def collect_file_patches(diff: str) -> list[FilePatch]:
    """Parse diff headers into file-level patch operations."""
    lines = diff.splitlines(keepends=True)
    file_patches: list[FilePatch] = []
    index = 0

    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue

        old_header = lines[index].rstrip("\n")
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise PatchApplyError(f"Expected +++ header after {old_header!r}")

        new_header = lines[index].rstrip("\n")
        index += 1
        file_patches.append(_parse_file_headers(old_header, new_header))

    return file_patches


def collect_target_file_candidates(diff: str) -> list[str]:
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


def collect_strict_target_file_candidates(patch: str) -> list[str]:
    """Best-effort extraction of strict apply_patch target paths."""
    targets: list[str] = []
    for raw_line in patch.splitlines(keepends=False):
        line = raw_line.strip()
        if line.startswith(_STRICT_ADD_FILE_PREFIX):
            targets.append(line[len(_STRICT_ADD_FILE_PREFIX) :])
        elif line.startswith(_STRICT_DELETE_FILE_PREFIX):
            targets.append(line[len(_STRICT_DELETE_FILE_PREFIX) :])
        elif line.startswith(_STRICT_UPDATE_FILE_PREFIX):
            targets.append(line[len(_STRICT_UPDATE_FILE_PREFIX) :])
        elif line.startswith(_STRICT_MOVE_TO_PREFIX):
            targets.append(line[len(_STRICT_MOVE_TO_PREFIX) :])
    return _dedupe_preserve_order(targets)


def build_patch_result_metadata(
    applied_ops: list[AppliedFileOperation],
    total_hunks: int,
) -> dict[str, object]:
    """Build stable success metadata for a patch application."""
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


def parse_strict_patch(patch: str) -> list[StrictPatchOperation]:
    """Parse a Codex-style freeform apply_patch body."""
    lines = patch.splitlines(keepends=False)
    if not lines or lines[0] != _STRICT_PATCH_BEGIN:
        raise PatchApplyError("Patch must start with *** Begin Patch")

    index = 1
    if index < len(lines) and lines[index].startswith(_STRICT_ENVIRONMENT_PREFIX):
        index += 1

    operations: list[StrictPatchOperation] = []
    while index < len(lines):
        line = lines[index]
        if line == _STRICT_PATCH_END:
            if not operations:
                raise PatchApplyError("No valid file patches found in diff")
            trailing = [extra for extra in lines[index + 1 :] if extra.strip()]
            if trailing:
                raise PatchApplyError("Unexpected content after *** End Patch")
            return operations

        if line.startswith(_STRICT_ADD_FILE_PREFIX):
            operations.append(_parse_strict_add_operation(lines, index))
            index = _advance_strict_add(lines, index)
            continue

        if line.startswith(_STRICT_DELETE_FILE_PREFIX):
            operations.append(
                StrictPatchOperation(
                    operation="delete",
                    path=line[len(_STRICT_DELETE_FILE_PREFIX) :],
                )
            )
            index += 1
            continue

        if line.startswith(_STRICT_UPDATE_FILE_PREFIX):
            operation, index = _parse_strict_update_operation(lines, index)
            operations.append(operation)
            continue

        raise PatchApplyError(f"Unexpected patch directive: {line!r}")

    raise PatchApplyError("Patch is missing *** End Patch")


def apply_strict_patch(
    patch: str,
    ctx: ToolContext,
) -> tuple[list[AppliedFileOperation], int]:
    """Apply a Codex-style freeform apply_patch body."""
    operations = parse_strict_patch(patch)
    applied_ops: list[AppliedFileOperation] = []
    total_hunks = 0

    for operation in operations:
        applied_op, hunks_applied = _apply_strict_operation(operation, ctx)
        applied_ops.append(applied_op)
        total_hunks += hunks_applied

    if not applied_ops:
        raise PatchApplyError("No valid file patches found in diff")

    return applied_ops, total_hunks


def apply_unified_diff(
    diff: str,
    ctx: ToolContext,
) -> tuple[list[AppliedFileOperation], int]:
    """Apply a unified diff and return modified repo-relative file paths."""
    lines = diff.splitlines(keepends=True)
    applied_ops: list[AppliedFileOperation] = []
    total_hunks = 0
    index = 0

    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue

        old_header = lines[index].rstrip("\n")
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise PatchApplyError(f"Expected +++ header after {old_header!r}")

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
            raise PatchApplyError(f"No hunks found for file patch: {file_patch.target_path}")

        if file_patch.operation == "delete":
            if current_lines:
                raise PatchApplyError(
                    f"Deletion patch for {file_patch.target_path!r} did not remove all content"
                )
            _delete_file(target)
        else:
            if file_patch.operation == "create":
                target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("".join(current_lines), encoding="utf-8")

        rel_path = target.relative_to(ctx.workspace_root)
        applied_ops.append(
            AppliedFileOperation(
                path=str(PurePosixPath(*rel_path.parts)),
                operation=file_patch.operation,
                hunks_applied=hunk_count,
            )
        )

    if not applied_ops:
        raise PatchApplyError("No valid file patches found in diff")

    return applied_ops, total_hunks


def _parse_file_headers(old_header: str, new_header: str) -> FilePatch:
    """Resolve old/new headers into a concrete file operation."""
    old_path = _extract_path(old_header)
    new_path = _extract_path(new_header)

    if old_path is None or new_path is None:
        raise PatchApplyError(f"Malformed file headers: {old_header!r}, {new_header!r}")

    if old_path == "/dev/null" and new_path == "/dev/null":
        raise PatchApplyError("Patch cannot use /dev/null for both old and new paths")

    if old_path == "/dev/null":
        return FilePatch(
            operation="create",
            old_path=None,
            new_path=new_path,
            target_path=new_path,
        )

    if new_path == "/dev/null":
        return FilePatch(
            operation="delete",
            old_path=old_path,
            new_path=None,
            target_path=old_path,
        )

    if old_path != new_path:
        raise PatchApplyError(
            f"File rename patches are not supported: {old_path!r} -> {new_path!r}"
        )

    return FilePatch(
        operation="modify",
        old_path=old_path,
        new_path=new_path,
        target_path=new_path,
    )


def _resolve_patch_target(file_patch: FilePatch, ctx: ToolContext) -> Path:
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
        raise PatchApplyError(f"Unable to delete file {target}: {exc}") from exc


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
        raise PatchApplyError(f"Malformed hunk header: {header!r}")

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
            raise PatchApplyError(f"Unsupported patch marker: {line.rstrip()!r}")

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
        raise PatchApplyError(
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
        raise PatchApplyError("Hunk context extends beyond end of file")

    candidates: list[int] = []
    begin = max(0, suggested_index - _HUNK_FUZZ_WINDOW)
    end = min(max_index, suggested_index + _HUNK_FUZZ_WINDOW)
    for candidate in range(begin, end + 1):
        if _segment_matches(file_lines, candidate, expected_old):
            candidates.append(candidate)

    if not candidates:
        raise PatchApplyError(
            f"Hunk context mismatch near line {suggested_index + 1}"
        )

    if len(candidates) == 1:
        return candidates[0]

    ranked = sorted(candidates, key=lambda value: abs(value - suggested_index))
    if abs(ranked[0] - suggested_index) == abs(ranked[1] - suggested_index):
        raise PatchApplyError(
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


def _parse_strict_add_operation(
    lines: list[str],
    start: int,
) -> StrictPatchOperation:
    path = lines[start][len(_STRICT_ADD_FILE_PREFIX) :]
    index = start + 1
    add_lines: list[str] = []
    while index < len(lines) and not lines[index].startswith("*** "):
        line = lines[index]
        if not line.startswith("+"):
            raise PatchApplyError(
                f"Add File patch for {path!r} contains a non-add line: {line!r}"
            )
        add_lines.append(line[1:])
        index += 1
    if not add_lines:
        raise PatchApplyError(f"Add File patch for {path!r} is missing content")
    return StrictPatchOperation(
        operation="add",
        path=path,
        add_lines=tuple(add_lines),
    )


def _advance_strict_add(lines: list[str], start: int) -> int:
    index = start + 1
    while index < len(lines) and not lines[index].startswith("*** "):
        index += 1
    return index


def _parse_strict_update_operation(
    lines: list[str],
    start: int,
) -> tuple[StrictPatchOperation, int]:
    path = lines[start][len(_STRICT_UPDATE_FILE_PREFIX) :]
    index = start + 1
    move_path: str | None = None
    if index < len(lines) and lines[index].startswith(_STRICT_MOVE_TO_PREFIX):
        move_path = lines[index][len(_STRICT_MOVE_TO_PREFIX) :]
        index += 1

    chunks: list[StrictPatchChunk] = []
    while index < len(lines) and not lines[index].startswith("*** "):
        chunk, index = _parse_strict_update_chunk(lines, index, path)
        chunks.append(chunk)

    if not chunks and move_path is None:
        raise PatchApplyError(f"Update File patch for {path!r} is missing changes")

    return (
        StrictPatchOperation(
            operation="update",
            path=path,
            move_path=move_path,
            chunks=tuple(chunks),
        ),
        index,
    )


def _parse_strict_update_chunk(
    lines: list[str],
    start: int,
    path: str,
) -> tuple[StrictPatchChunk, int]:
    index = start
    change_context: str | None = None
    if lines[index].startswith("@@"):
        header = lines[index]
        if header == "@@":
            change_context = None
        elif header.startswith("@@ "):
            change_context = header[3:]
        else:
            raise PatchApplyError(f"Malformed strict patch chunk header: {header!r}")
        index += 1

    old_lines: list[str] = []
    new_lines: list[str] = []
    saw_change_line = False
    end_of_file = False

    while index < len(lines):
        line = lines[index]
        if line == _STRICT_END_OF_FILE:
            end_of_file = True
            index += 1
            break
        if line.startswith("@@") or line.startswith("*** "):
            break
        if not line or line[0] not in {" ", "+", "-"}:
            raise PatchApplyError(
                f"Update File patch for {path!r} contains an invalid line: {line!r}"
            )

        payload = line[1:]
        if line[0] in {" ", "-"}:
            old_lines.append(payload)
        if line[0] in {" ", "+"}:
            new_lines.append(payload)
        saw_change_line = True
        index += 1

    if not saw_change_line and not end_of_file:
        raise PatchApplyError(f"Update File patch for {path!r} is missing change lines")

    return (
        StrictPatchChunk(
            change_context=change_context,
            old_lines=tuple(old_lines),
            new_lines=tuple(new_lines),
            is_end_of_file=end_of_file,
        ),
        index,
    )


def _apply_strict_operation(
    operation: StrictPatchOperation,
    ctx: ToolContext,
) -> tuple[AppliedFileOperation, int]:
    if operation.operation == "add":
        return _apply_strict_add_file(operation, ctx)
    if operation.operation == "delete":
        return _apply_strict_delete_file(operation, ctx)
    if operation.operation == "update":
        return _apply_strict_update_file(operation, ctx)
    raise PatchApplyError(f"Unsupported strict patch operation: {operation.operation!r}")


def _apply_strict_add_file(
    operation: StrictPatchOperation,
    ctx: ToolContext,
) -> tuple[AppliedFileOperation, int]:
    target = resolve_and_validate_writable_path(
        operation.path,
        ctx.workspace_root,
        check_allowed_fn=ctx.is_file_allowed,
    )
    if target.exists() and not target.is_file():
        raise PatchApplyError(f"Target path is not a file: {operation.path!r}")

    rendered = _render_strict_text(list(operation.add_lines), trailing_newline=True)
    file_operation = "modify" if target.exists() else "create"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")

    return (
        AppliedFileOperation(
            path=_workspace_relative_path(target, ctx),
            operation=file_operation,
            hunks_applied=1,
        ),
        1,
    )


def _apply_strict_delete_file(
    operation: StrictPatchOperation,
    ctx: ToolContext,
) -> tuple[AppliedFileOperation, int]:
    target = resolve_and_validate_writable_path(
        operation.path,
        ctx.workspace_root,
        must_exist=True,
        must_be_file=True,
        check_allowed_fn=ctx.is_file_allowed,
    )
    rel_path = _workspace_relative_path(target, ctx)
    _delete_file(target)
    return (
        AppliedFileOperation(
            path=rel_path,
            operation="delete",
            hunks_applied=1,
        ),
        1,
    )


def _apply_strict_update_file(
    operation: StrictPatchOperation,
    ctx: ToolContext,
) -> tuple[AppliedFileOperation, int]:
    source = resolve_and_validate_writable_path(
        operation.path,
        ctx.workspace_root,
        must_exist=True,
        must_be_file=True,
        check_allowed_fn=ctx.is_file_allowed,
    )
    destination = source
    if operation.move_path is not None:
        destination = resolve_and_validate_writable_path(
            operation.move_path,
            ctx.workspace_root,
            check_allowed_fn=ctx.is_file_allowed,
        )
        if destination.exists() and destination.resolve() != source.resolve():
            raise PatchApplyError(
                f"Move destination already exists: {operation.move_path!r}"
            )

    original_text = source.read_text(encoding="utf-8", errors="replace")
    current_lines = original_text.splitlines()
    trailing_newline = original_text.endswith("\n")

    for chunk in operation.chunks:
        current_lines, touched_eof = _apply_strict_chunk(
            current_lines,
            chunk,
            path=operation.path,
        )
        if chunk.is_end_of_file:
            trailing_newline = False
        elif not current_lines:
            trailing_newline = False
        elif touched_eof:
            trailing_newline = True

    rendered = _render_strict_text(current_lines, trailing_newline=trailing_newline)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    if destination.resolve() != source.resolve():
        _delete_file(source)

    return (
        AppliedFileOperation(
            path=_workspace_relative_path(destination, ctx),
            operation="modify",
            hunks_applied=len(operation.chunks),
        ),
        len(operation.chunks),
    )


def _apply_strict_chunk(
    file_lines: list[str],
    chunk: StrictPatchChunk,
    *,
    path: str,
) -> tuple[list[str], bool]:
    old_segment = list(chunk.old_lines)
    new_segment = list(chunk.new_lines)
    if not old_segment:
        insert_index = len(file_lines)
        updated_lines = file_lines[:insert_index] + new_segment + file_lines[insert_index:]
        return updated_lines, True

    apply_index = _find_unique_segment_position(
        file_lines,
        old_segment,
        path=path,
        change_context=chunk.change_context,
    )
    touched_eof = apply_index + len(old_segment) == len(file_lines)
    updated_lines = (
        file_lines[:apply_index]
        + new_segment
        + file_lines[apply_index + len(old_segment) :]
    )
    return updated_lines, touched_eof


def _find_unique_segment_position(
    file_lines: list[str],
    expected_old: list[str],
    *,
    path: str,
    change_context: str | None,
) -> int:
    max_index = len(file_lines) - len(expected_old)
    if max_index < 0:
        raise PatchApplyError(f"Patch context extends beyond end of file for {path!r}")

    matches = [
        index
        for index in range(max_index + 1)
        if _segment_matches(file_lines, index, expected_old)
    ]
    if not matches:
        context_suffix = f" ({change_context})" if change_context else ""
        raise PatchApplyError(
            f"Patch context mismatch in {path!r}{context_suffix}"
        )
    if len(matches) > 1:
        context_suffix = f" ({change_context})" if change_context else ""
        raise PatchApplyError(
            f"Patch context is ambiguous in {path!r}{context_suffix}"
        )
    return matches[0]


def _render_strict_text(
    lines: list[str],
    *,
    trailing_newline: bool,
) -> str:
    if not lines:
        return ""
    rendered = "\n".join(lines)
    if trailing_newline:
        rendered += "\n"
    return rendered


def _workspace_relative_path(target: Path, ctx: ToolContext) -> str:
    rel_path = target.relative_to(ctx.workspace_root)
    return str(PurePosixPath(*rel_path.parts))


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
