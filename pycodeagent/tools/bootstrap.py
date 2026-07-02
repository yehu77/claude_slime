"""Bootstrap layer for strict native family tool stacks."""

from __future__ import annotations

from typing import Literal

from pycodeagent.tools.families import (
    build_claude_canonical_registry,
    build_codex_canonical_registry,
)
from pycodeagent.tools.profile_factory import (
    build_native_claude_profile,
    build_native_codex_profile,
)
from pycodeagent.tools.registry import ToolRegistry
from pycodeagent.tools.runtime import ToolRuntime
from pycodeagent.tools.spec import ToolProfile

ToolStackKind = Literal["native_claude", "native_codex"]


def build_native_claude_runtime(
    *,
    profile_id: str = "native_claude",
) -> tuple[ToolRegistry, ToolProfile, ToolRuntime]:
    """Assemble the strict Claude-family runtime stack."""
    return _build_tool_stack("native_claude", profile_id=profile_id)


def build_native_codex_runtime(
    *,
    profile_id: str = "native_codex",
) -> tuple[ToolRegistry, ToolProfile, ToolRuntime]:
    """Assemble the strict Codex-family runtime stack."""
    return _build_tool_stack("native_codex", profile_id=profile_id)


def _build_tool_stack(
    kind: ToolStackKind,
    *,
    profile_id: str | None = None,
) -> tuple[ToolRegistry, ToolProfile, ToolRuntime]:
    """Assemble one complete tool stack for the requested family."""
    if kind == "native_claude":
        registry = build_claude_canonical_registry()
        profile = build_native_claude_profile(
            profile_id=profile_id or "native_claude"
        )
    elif kind == "native_codex":
        registry = build_codex_canonical_registry()
        profile = build_native_codex_profile(profile_id=profile_id or "native_codex")
    else:
        raise ValueError(f"Unknown tool stack kind: {kind!r}")

    runtime = ToolRuntime(registry)
    return registry, profile, runtime


def _infer_tool_stack_kind_from_profile(
    profile: ToolProfile,
) -> ToolStackKind | None:
    """Best-effort inference of the runtime family implied by one profile."""
    native_profile_kind = profile.metadata.get("native_profile_kind")
    if native_profile_kind == "native_claude":
        return "native_claude"
    if native_profile_kind == "native_codex":
        return "native_codex"

    family = profile.metadata.get("family")
    if family == "claude":
        return "native_claude"
    if family == "codex":
        return "native_codex"
    return None
