"""Family-specific patch runtime for Codex-style patch application."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycodeagent.env.path_policy import PathPolicyError
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.execution_contract import build_execution_metadata
from pycodeagent.tools.patch_apply import (
    PatchApplyError,
    apply_strict_patch,
    apply_unified_diff,
    build_patch_result_metadata,
    collect_file_patches,
    collect_strict_target_file_candidates,
    collect_target_file_candidates,
)
from pycodeagent.trajectory.schema import ToolResult


def _missing_context_error(*, extra: dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(
        ok=False,
        content="ToolContext is required for workspace enforcement",
        is_error=True,
        metadata=build_execution_metadata(
            operation="codex_apply_patch",
            execution_kind="patch_apply",
            execution_stage="context_check",
            policy_domain="filesystem",
            policy_decision="deny",
            policy_reason="ToolContext is required for workspace enforcement",
            policy_reason_code="missing_context",
            dangerous=False,
            command_family="codex_apply_patch",
            resolved_target_paths=[],
            extra={"error_type": "missing_context", **(extra or {})},
        ),
    )


def _empty_patch_error(*, extra: dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(
        ok=False,
        content="Empty diff",
        is_error=True,
        metadata=build_execution_metadata(
            operation="codex_apply_patch",
            execution_kind="patch_apply",
            execution_stage="validate_input",
            policy_domain="filesystem",
            policy_decision="deny",
            policy_reason="Empty diff",
            policy_reason_code="empty_diff",
            dangerous=False,
            command_family="codex_apply_patch",
            resolved_target_paths=[],
            extra={
                "error_type": "empty_diff",
                "target_files": [],
                **(extra or {}),
            },
        ),
    )


def _path_policy_error_result(
    error: PathPolicyError,
    *,
    workspace_root: Path,
    target_files: list[str],
) -> ToolResult:
    metadata = build_execution_metadata(
        operation="codex_apply_patch",
        execution_kind="patch_apply",
        execution_stage="validate_target",
        policy_domain=error.metadata.get("policy_domain", "filesystem"),
        policy_decision=error.metadata.get("policy_decision", "deny"),
        policy_reason=error.metadata.get("policy_reason", str(error)),
        policy_reason_code=error.metadata.get("policy_reason_code", error.error_type),
        dangerous=error.metadata.get(
            "dangerous",
            error.error_type in {"absolute_path", "workspace_escape", "protected_path"},
        ),
        command_family="codex_apply_patch",
        workspace_root=workspace_root,
        resolved_target_paths=target_files,
        extra={
            "error_type": error.error_type,
            "target_files": target_files,
        },
    )
    for key, value in error.metadata.items():
        metadata.setdefault(key, value)
    return ToolResult(
        ok=False,
        content=str(error),
        is_error=True,
        metadata=metadata,
    )


def _patch_error_result(
    *,
    content: str,
    error_type: str,
    workspace_root: Path,
    target_files: list[str],
) -> ToolResult:
    return ToolResult(
        ok=False,
        content=content,
        is_error=True,
        metadata=build_execution_metadata(
            operation="codex_apply_patch",
            execution_kind="patch_apply",
            execution_stage="handler_execution",
            policy_domain="filesystem",
            policy_decision="allow",
            dangerous=False,
            command_family="codex_apply_patch",
            workspace_root=workspace_root,
            resolved_target_paths=target_files,
            extra={
                "error_type": error_type,
                "target_files": target_files,
            },
        ),
    )


def _patch_success_result(
    *,
    workspace_root: Path,
    applied_ops,
    hunks_applied: int,
) -> ToolResult:
    return ToolResult(
        ok=True,
        content="Patch applied successfully. Modified files:\n"
        + "\n".join(f"  - {path}" for path in [op.path for op in applied_ops]),
        metadata=build_execution_metadata(
            operation="codex_apply_patch",
            execution_kind="patch_apply",
            execution_stage="result_finalize",
            policy_domain="filesystem",
            policy_decision="allow",
            dangerous=False,
            command_family="codex_apply_patch",
            workspace_root=workspace_root,
            resolved_target_paths=[op.path for op in applied_ops],
            extra=build_patch_result_metadata(applied_ops, hunks_applied),
        ),
    )


class CodexApplyPatchRuntime:
    """Codex-style dedicated patch runtime."""

    def apply_patch(
        self,
        patch: str,
        *,
        ctx: ToolContext | None = None,
    ) -> ToolResult:
        if not patch or not patch.strip():
            return _empty_patch_error()

        if ctx is None:
            return _missing_context_error()

        target_files: list[str] = []
        is_strict_patch = patch.lstrip().startswith("*** Begin Patch")
        try:
            if is_strict_patch:
                target_files = collect_strict_target_file_candidates(patch)
                applied_ops, hunks_applied = apply_strict_patch(patch, ctx)
            else:
                file_patches = collect_file_patches(patch)
                target_files = [file_patch.target_path for file_patch in file_patches]
                applied_ops, hunks_applied = apply_unified_diff(patch, ctx)
        except PatchApplyError as exc:
            if not target_files:
                if is_strict_patch:
                    target_files = collect_strict_target_file_candidates(patch)
                else:
                    target_files = collect_target_file_candidates(patch)
            return _patch_error_result(
                content=f"Patch failed: {exc}",
                error_type="patch_apply",
                workspace_root=ctx.workspace_root,
                target_files=target_files,
            )
        except PathPolicyError as exc:
            return _path_policy_error_result(
                exc,
                workspace_root=ctx.workspace_root,
                target_files=target_files,
            )
        except Exception as exc:
            return _patch_error_result(
                content=f"Unexpected patch error: {exc}",
                error_type="patch_unexpected",
                workspace_root=ctx.workspace_root,
                target_files=target_files,
            )

        return _patch_success_result(
            workspace_root=ctx.workspace_root,
            applied_ops=applied_ops,
            hunks_applied=hunks_applied,
        )
