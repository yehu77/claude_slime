"""Tests for tool bootstrap and profile factory.

Covers:
- build_builtin_registry() creates registry with all builtin tools
- build_base_tool_profile() creates valid base profile
- build_base_tool_runtime() assembles working runtime
- Builder isolation (no shared mutable state)
- Runtime smoke test with finish tool
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pycodeagent.tools.builtin import ALL_BUILTIN_TOOLS
from pycodeagent.tools.bootstrap import (
    build_base_tool_runtime,
    build_builtin_registry,
)
from pycodeagent.tools.profile_factory import build_base_tool_profile
from pycodeagent.tools.registry import ToolRegistry
from pycodeagent.tools.runtime import ToolRuntime
from pycodeagent.tools.spec import ToolProfile
from pycodeagent.trajectory.schema import ToolCall


# Expected builtin tool canonical names
EXPECTED_BUILTIN_TOOLS = {tool.canonical_name for tool in ALL_BUILTIN_TOOLS}


class TestBuildBuiltinRegistry:
    """Tests for build_builtin_registry()."""

    def test_returns_tool_registry(self):
        """Must return a ToolRegistry instance."""
        registry = build_builtin_registry()
        assert isinstance(registry, ToolRegistry)

    def test_contains_all_builtin_tools(self):
        """Registry must contain all Phase 1-2 builtin tools."""
        registry = build_builtin_registry()
        registered_names = {t.canonical_name for t in registry.list()}
        assert registered_names == EXPECTED_BUILTIN_TOOLS

    def test_has_list_files(self):
        registry = build_builtin_registry()
        assert registry.has("list_files")
        tool = registry.get("list_files")
        assert tool.canonical_name == "list_files"

    def test_has_read_file(self):
        registry = build_builtin_registry()
        assert registry.has("read_file")
        tool = registry.get("read_file")
        assert tool.canonical_name == "read_file"

    def test_has_search_code(self):
        registry = build_builtin_registry()
        assert registry.has("search_code")
        tool = registry.get("search_code")
        assert tool.canonical_name == "search_code"

    def test_has_apply_patch(self):
        registry = build_builtin_registry()
        assert registry.has("apply_patch")
        tool = registry.get("apply_patch")
        assert tool.canonical_name == "apply_patch"

    def test_has_run_command(self):
        registry = build_builtin_registry()
        assert registry.has("run_command")
        tool = registry.get("run_command")
        assert tool.canonical_name == "run_command"

    def test_has_finish(self):
        registry = build_builtin_registry()
        assert registry.has("finish")
        tool = registry.get("finish")
        assert tool.canonical_name == "finish"

    def test_repeated_calls_return_independent_instances(self):
        """Each call must return a fresh registry with no shared state."""
        registry1 = build_builtin_registry()
        registry2 = build_builtin_registry()
        # They should not be the same object
        assert registry1 is not registry2
        # Both should have the same tools independently
        assert registry1.has("finish")
        assert registry2.has("finish")


class TestBuildBaseToolProfile:
    """Tests for build_base_tool_profile()."""

    def test_returns_tool_profile(self):
        """Must return a ToolProfile instance."""
        profile = build_base_tool_profile()
        assert isinstance(profile, ToolProfile)

    def test_default_profile_id_is_base(self):
        """Default profile_id must be 'base'."""
        profile = build_base_tool_profile()
        assert profile.profile_id == "base"

    def test_custom_profile_id(self):
        """Must accept custom profile_id."""
        profile = build_base_tool_profile(profile_id="custom_v1")
        assert profile.profile_id == "custom_v1"

    def test_tools_count_matches_builtins(self):
        """Profile must have one ToolView per builtin tool."""
        profile = build_base_tool_profile()
        assert len(profile.tools) == len(EXPECTED_BUILTIN_TOOLS)

    def test_exposed_name_equals_canonical_name(self):
        """Base profile uses identity mapping for names."""
        profile = build_base_tool_profile()
        for view in profile.tools:
            assert view.exposed_name == view.canonical_name

    def test_all_builtins_present(self):
        """All builtin tools must have a ToolView."""
        profile = build_base_tool_profile()
        exposed_names = {tv.exposed_name for tv in profile.tools}
        assert exposed_names == EXPECTED_BUILTIN_TOOLS

    def test_profile_views_match_builtin_metadata(self):
        """Base profile metadata should come directly from builtin tool definitions."""
        profile = build_base_tool_profile()
        profile_tools = {tool.canonical_name: tool for tool in profile.tools}
        builtin_tools = {tool.canonical_name: tool for tool in ALL_BUILTIN_TOOLS}

        assert set(profile_tools) == set(builtin_tools)

        for canonical_name, builtin_tool in builtin_tools.items():
            view = profile_tools[canonical_name]
            assert view.description == builtin_tool.description
            assert view.input_schema == builtin_tool.canonical_schema

    def test_get_exposed_specs_returns_list(self):
        """get_exposed_specs() must return list of dicts with name/description/schema."""
        profile = build_base_tool_profile()
        specs = profile.get_exposed_specs()
        assert isinstance(specs, list)
        assert len(specs) == len(EXPECTED_BUILTIN_TOOLS)
        for spec in specs:
            assert "name" in spec
            assert "description" in spec
            assert "input_schema" in spec
            assert isinstance(spec["input_schema"], dict)

    def test_get_exposed_specs_names_match_exposed_names(self):
        """Spec names must match ToolView.exposed_name."""
        profile = build_base_tool_profile()
        specs = profile.get_exposed_specs()
        spec_names = {s["name"] for s in specs}
        exposed_names = {tv.exposed_name for tv in profile.tools}
        assert spec_names == exposed_names

    def test_get_tool_versions_returns_dict(self):
        """get_tool_versions() must return dict suitable for trajectory logging."""
        profile = build_base_tool_profile()
        versions = profile.get_tool_versions()
        assert isinstance(versions, dict)
        assert set(versions.keys()) == EXPECTED_BUILTIN_TOOLS
        for name, info in versions.items():
            assert "canonical_name" in info
            assert "version" in info
            assert info["canonical_name"] == name  # identity mapping

    def test_repeated_calls_return_independent_instances(self):
        """Each call must return a fresh profile."""
        profile1 = build_base_tool_profile()
        profile2 = build_base_tool_profile()
        assert profile1 is not profile2
        # Modifying one should not affect the other
        assert profile1.profile_id == profile2.profile_id


class TestBuildBaseToolRuntime:
    """Tests for build_base_tool_runtime()."""

    def test_returns_triple(self):
        """Must return (registry, profile, runtime) triple."""
        registry, profile, runtime = build_base_tool_runtime()
        assert isinstance(registry, ToolRegistry)
        assert isinstance(profile, ToolProfile)
        assert isinstance(runtime, ToolRuntime)

    def test_registry_has_all_builtins(self):
        """Returned registry must have all builtin tools."""
        registry, profile, runtime = build_base_tool_runtime()
        registered_names = {t.canonical_name for t in registry.list()}
        assert registered_names == EXPECTED_BUILTIN_TOOLS

    def test_profile_is_base(self):
        """Returned profile must be base profile."""
        registry, profile, runtime = build_base_tool_runtime()
        assert profile.profile_id == "base"

    def test_custom_profile_id(self):
        """Must accept custom profile_id."""
        registry, profile, runtime = build_base_tool_runtime(profile_id="custom")
        assert profile.profile_id == "custom"

    def test_repeated_calls_return_independent_instances(self):
        """Each call must return independent triple."""
        r1, p1, rt1 = build_base_tool_runtime()
        r2, p2, rt2 = build_base_tool_runtime()
        assert r1 is not r2
        assert p1 is not p2
        assert rt1 is not rt2


class TestRuntimeSmokeTest:
    """Smoke tests for runtime execution through bootstrap."""

    def test_finish_tool_executes_successfully(self):
        """finish tool must execute through bootstrapped runtime."""
        registry, profile, runtime = build_base_tool_runtime()
        call = ToolCall(
            id="test_finish",
            name="finish",
            arguments={"answer": "Task completed", "summary": "All done"},
        )
        result = runtime.execute(call, profile)
        assert result.ok
        assert "Task completed" in result.content
        assert result.metadata.get("is_finish") is True

    def test_finish_tool_minimal_args(self):
        """finish tool with no args must work."""
        registry, profile, runtime = build_base_tool_runtime()
        call = ToolCall(
            id="test_finish_minimal",
            name="finish",
            arguments={},
        )
        result = runtime.execute(call, profile)
        assert result.ok
        assert "finished" in result.content.lower()

    def test_unknown_tool_returns_error(self):
        """Unknown tool must return error result."""
        registry, profile, runtime = build_base_tool_runtime()
        call = ToolCall(
            id="test_unknown",
            name="nonexistent_tool",
            arguments={},
        )
        result = runtime.execute(call, profile)
        assert result.is_error
        assert "not found" in result.content.lower()

    def test_list_files_requires_context(self):
        """list_files must reject execution without ToolContext."""
        registry, profile, runtime = build_base_tool_runtime()
        call = ToolCall(
            id="test_list_files",
            name="list_files",
            arguments={"path": "."},
        )
        result = runtime.execute(call, profile)
        assert result.is_error
        assert result.metadata.get("error_type") == "missing_context"
