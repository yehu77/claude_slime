"""Shared execution metadata helpers for builtin tool results."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_execution_metadata(
    *,
    operation: str,
    execution_kind: str,
    execution_stage: str,
    policy_decision: str | None = None,
    policy_reason: str | None = None,
    policy_reason_code: str | None = None,
    policy_domain: str | None = None,
    dangerous: bool | None = None,
    command_family: str | None = None,
    workspace_root: str | Path | None = None,
    resolved_target_paths: list[str] | None = None,
    resolved_cwd: str | Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable execution/policy metadata envelope."""
    metadata: dict[str, Any] = {
        "operation": operation,
        "execution_kind": execution_kind,
        "stage": execution_stage,
        "execution_stage": execution_stage,
    }
    if policy_decision is not None:
        metadata["policy_decision"] = policy_decision
    if policy_reason is not None:
        metadata["policy_reason"] = policy_reason
    if policy_reason_code is not None:
        metadata["policy_reason_code"] = policy_reason_code
    if policy_domain is not None:
        metadata["policy_domain"] = policy_domain
    if dangerous is not None:
        metadata["dangerous"] = dangerous
    if command_family is not None:
        metadata["command_family"] = command_family
    if workspace_root is not None:
        metadata["workspace_root"] = str(workspace_root)
    if resolved_target_paths is not None:
        metadata["resolved_target_paths"] = list(resolved_target_paths)
        metadata["target_file_count"] = len(resolved_target_paths)
    if resolved_cwd is not None:
        metadata["resolved_cwd"] = str(resolved_cwd)
    if extra:
        metadata.update(extra)
    return metadata
