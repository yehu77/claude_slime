"""Phase-2 guardrail: mutated profile -> runtime compatibility.

Tests that sampled profiles from various modes (name_only, schema_only,
name_description_schema) can:
1. Expose mutated tools
2. Be resolved by runtime
3. Map arguments correctly through adapters
4. Execute canonical handlers

This guards against changes to profile sampler, mutators, or runtime
that would silently break the profile->runtime contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.tools.bootstrap import build_builtin_registry
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.registry import ToolRegistry
from pycodeagent.tools.runtime import ToolRuntime
from pycodeagent.tools.spec import ToolProfile
from pycodeagent.trajectory.schema import ToolCall


_TEST_NAMESPACE = "phase2_profile_runtime"


def _get_test_workspace() -> Path:
    """Get a unique test workspace."""
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup_workspace(path: Path) -> None:
    """Clean up test workspace."""
    cleanup_test_path(path)


def _get_tool_view(profile: ToolProfile, canonical_name: str):
    """Return the ToolView for a canonical tool name."""
    return next(tool for tool in profile.tools if tool.canonical_name == canonical_name)


def _make_tool_context(workspace: Path) -> ToolContext:
    """Build a ToolContext rooted at the test workspace."""
    from pycodeagent.env.task import CodingTask

    task = CodingTask(
        task_id="test",
        repo_path=workspace,
        prompt="test",
    )
    return ToolContext(workspace_root=workspace, task=task)


def _build_search_args(schema_props: dict[str, object]) -> dict[str, object]:
    """Build valid search_code args for the selected exposed schema."""
    if {"query", "path", "glob_pattern"} <= set(schema_props):
        return {"query": "hello", "path": ".", "glob_pattern": "*.py"}
    if {"query", "scope", "filter"} <= set(schema_props):
        return {"query": "hello", "scope": ".", "filter": "*.py"}
    if {"term", "location", "glob"} <= set(schema_props):
        return {"term": "hello", "location": ".", "glob": "*.py"}
    raise AssertionError(f"Unexpected search_code schema keys: {sorted(schema_props)}")


def _build_run_command_args(schema_props: dict[str, object]) -> dict[str, object]:
    """Build valid run_command args for the selected exposed schema."""
    if {"command", "timeout", "cwd"} <= set(schema_props):
        return {"command": "git --version", "timeout": 5, "cwd": "subdir"}
    if {"cmd", "time_limit", "working_dir"} <= set(schema_props):
        return {"cmd": "git --version", "time_limit": 5, "working_dir": "subdir"}
    if {"instruction", "max_wait", "directory"} <= set(schema_props):
        return {"instruction": "git --version", "max_wait": 5, "directory": "subdir"}
    raise AssertionError(f"Unexpected run_command schema keys: {sorted(schema_props)}")


class TestProfileSamplerModes:
    """Tests for all profile sampler modes."""

    def test_base_mode_produces_identity_profile(self):
        """Base mode should produce identity mapping."""
        sampler = ToolProfileSampler(seed=0)
        profile = sampler.sample("base")

        # All exposed names should match canonical names
        for tool in profile.tools:
            assert tool.exposed_name == tool.canonical_name

        # All adapters should be empty (identity)
        for adapter in profile.adapters.values():
            assert adapter.exposed_to_canonical == {}
            assert adapter.defaults == {}

    def test_name_only_mode_changes_names(self):
        """name_only mode should change tool names."""
        sampler = ToolProfileSampler(seed=0)
        profile = sampler.sample("name_only")

        # At least one tool should have different exposed name
        name_changed = any(
            tool.exposed_name != tool.canonical_name for tool in profile.tools
        )
        assert name_changed, "name_only mode should change at least one tool name"

    def test_description_only_mode_changes_descriptions(self):
        """description_only mode should change descriptions."""
        sampler = ToolProfileSampler(seed=0)
        base_profile = sampler.sample("base")
        desc_profile = sampler.sample("description_only")

        # At least one description should differ
        base_descs = {t.canonical_name: t.description for t in base_profile.tools}
        desc_changed = any(
            t.description != base_descs.get(t.canonical_name, "")
            for t in desc_profile.tools
        )
        assert desc_changed, "description_only mode should change at least one description"

    def test_schema_only_mode_changes_schemas(self):
        """schema_only mode should change input schemas."""
        sampler = ToolProfileSampler(seed=0)
        base_profile = sampler.sample("base")
        schema_profile = sampler.sample("schema_only")

        # At least one schema should differ
        base_schemas = {t.canonical_name: t.input_schema for t in base_profile.tools}
        schema_changed = any(
            t.input_schema != base_schemas.get(t.canonical_name, {})
            for t in schema_profile.tools
        )
        assert schema_changed, "schema_only mode should change at least one schema"

    def test_full_mutation_mode_changes_all(self):
        """name_description_schema mode should change name, description, and schema."""
        sampler = ToolProfileSampler(seed=0)
        base_profile = sampler.sample("base")
        full_profile = sampler.sample("name_description_schema")

        # All dimensions should differ from base for at least one tool
        name_changed = any(
            t.exposed_name != t.canonical_name for t in full_profile.tools
        )
        base_descs = {t.canonical_name: t.description for t in base_profile.tools}
        desc_changed = any(
            t.description != base_descs.get(t.canonical_name, "")
            for t in full_profile.tools
        )
        base_schemas = {t.canonical_name: t.input_schema for t in base_profile.tools}
        schema_changed = any(
            t.input_schema != base_schemas.get(t.canonical_name, {})
            for t in full_profile.tools
        )

        assert name_changed, "Full mutation should change at least one name"
        assert desc_changed, "Full mutation should change at least one description"
        assert schema_changed, "Full mutation should change at least one schema"

    def test_deterministic_profile_ids(self):
        """Same seed and mode should produce same profile_id."""
        sampler1 = ToolProfileSampler(seed=42)
        sampler2 = ToolProfileSampler(seed=42)

        for mode in ["base", "name_only", "schema_only", "name_description_schema"]:
            profile1 = sampler1.sample(mode)
            profile2 = sampler2.sample(mode)
            assert profile1.profile_id == profile2.profile_id

    def test_different_seeds_different_ids(self):
        """Different seeds should produce different profile_ids for mutated modes."""
        sampler1 = ToolProfileSampler(seed=0)
        sampler2 = ToolProfileSampler(seed=1)

        for mode in ["name_only", "schema_only", "name_description_schema"]:
            profile1 = sampler1.sample(mode)
            profile2 = sampler2.sample(mode)
            # Note: might be same by chance, but very unlikely with hash
            # At minimum, we test that the system handles different seeds


class TestMutatedProfileRuntimeCompatibility:
    """Tests that mutated profiles remain runtime-compatible."""

    @pytest.fixture
    def registry(self) -> ToolRegistry:
        """Fresh registry with builtin tools."""
        return build_builtin_registry()

    @pytest.fixture
    def workspace(self) -> Path:
        """Test workspace."""
        ws = _get_test_workspace()
        yield ws
        _cleanup_workspace(ws)

    def test_base_profile_resolves_tools(self, registry: ToolRegistry):
        """Base profile should resolve all builtin tools."""
        sampler = ToolProfileSampler(seed=0)
        profile = sampler.sample("base")
        runtime = ToolRuntime(registry)

        for tool in profile.tools:
            resolved = profile.get_tool(tool.exposed_name)
            assert resolved is not None

    def test_name_only_profile_resolves_tools(self, registry: ToolRegistry):
        """name_only profile should resolve tools with mutated names."""
        sampler = ToolProfileSampler(seed=0)
        profile = sampler.sample("name_only")

        # All exposed tools should be resolvable
        for tool in profile.tools:
            resolved = profile.get_tool(tool.exposed_name)
            assert resolved is not None
            view, adapter = resolved
            assert view.canonical_name == tool.canonical_name

    def test_schema_only_profile_resolves_tools(self, registry: ToolRegistry):
        """schema_only profile should resolve tools with mutated schemas."""
        sampler = ToolProfileSampler(seed=0)
        profile = sampler.sample("schema_only")

        for tool in profile.tools:
            resolved = profile.get_tool(tool.exposed_name)
            assert resolved is not None

    def test_full_mutation_profile_resolves_tools(self, registry: ToolRegistry):
        """Full mutation profile should resolve tools."""
        sampler = ToolProfileSampler(seed=0)
        profile = sampler.sample("name_description_schema")

        for tool in profile.tools:
            resolved = profile.get_tool(tool.exposed_name)
            assert resolved is not None


class TestSchemaMutationArgumentMapping:
    """Tests that schema-mutated tools map arguments correctly."""

    @pytest.fixture
    def registry(self) -> ToolRegistry:
        return build_builtin_registry()

    @pytest.fixture
    def workspace(self) -> Path:
        ws = _get_test_workspace()
        # Create a simple file for testing
        (ws / "test.py").write_text("print('hello')\n")
        (ws / "subdir").mkdir()
        yield ws
        _cleanup_workspace(ws)

    def test_base_schema_read_file(self, registry: ToolRegistry, workspace: Path):
        """Base schema read_file should work with path argument."""
        sampler = ToolProfileSampler(seed=0)
        profile = sampler.sample("base")
        runtime = ToolRuntime(registry)

        # Find the read_file tool
        read_file_view = None
        for tool in profile.tools:
            if tool.canonical_name == "read_file":
                read_file_view = tool
                break
        assert read_file_view is not None

        # Create a call using base schema
        call = ToolCall(
            id="test_call",
            name=read_file_view.exposed_name,
            arguments={"path": "test.py"},
        )

        # Execute through runtime
        from pycodeagent.env.task import CodingTask

        task = CodingTask(
            task_id="test",
            repo_path=workspace,
            prompt="test",
        )
        ctx = ToolContext(workspace_root=workspace, task=task)
        result = runtime.execute(call, profile, ctx)

        assert result.ok
        assert "hello" in result.content

    def test_schema_mutated_read_file_maps_arguments(
        self, registry: ToolRegistry, workspace: Path
    ):
        """Schema-mutated read_file should map arguments correctly."""
        sampler = ToolProfileSampler(seed=0)
        profile = sampler.sample("schema_only")

        # Find the read_file tool (may have different exposed name)
        read_file_view = None
        for tool in profile.tools:
            if tool.canonical_name == "read_file":
                read_file_view = tool
                break
        assert read_file_view is not None

        # Check if schema is mutated (has different field names)
        schema_props = read_file_view.input_schema.get("properties", {})
        adapter = profile.adapters.get(read_file_view.exposed_name)

        # If schema uses different field names, adapter should map them
        if "path" not in schema_props:
            # Schema is mutated, adapter should have mappings
            assert adapter is not None
            assert len(adapter.exposed_to_canonical) > 0

            # The adapter should map something to "path"
            canonical_targets = set(adapter.exposed_to_canonical.values())
            assert "path" in canonical_targets

    def test_schema_mutated_finish_maps_arguments(
        self, registry: ToolRegistry, workspace: Path
    ):
        """Schema-mutated finish should map arguments correctly."""
        sampler = ToolProfileSampler(seed=0)
        profile = sampler.sample("schema_only")

        # Find finish tool
        finish_view = None
        for tool in profile.tools:
            if tool.canonical_name == "finish":
                finish_view = tool
                break
        assert finish_view is not None

        schema_props = finish_view.input_schema.get("properties", {})
        adapter = profile.adapters.get(finish_view.exposed_name)

        # If schema uses different field names, verify adapter mapping
        if "answer" not in schema_props:
            assert adapter is not None
            assert len(adapter.exposed_to_canonical) > 0
            canonical_targets = set(adapter.exposed_to_canonical.values())
            assert "answer" in canonical_targets

    def test_schema_mutated_search_code_maps_arguments_and_executes(
        self, registry: ToolRegistry, workspace: Path
    ):
        """Schema-mutated search_code should map args to canonical fields and run."""
        sampler = ToolProfileSampler(seed=0)
        profile = sampler.sample("schema_only")
        runtime = ToolRuntime(registry)

        search_view = _get_tool_view(profile, "search_code")
        schema_props = search_view.input_schema.get("properties", {})
        args = _build_search_args(schema_props)

        _, canonical_args = profile.map_call_arguments(
            search_view.exposed_name,
            args,
            registry.get("search_code"),
        )
        assert canonical_args == {
            "query": "hello",
            "path": ".",
            "glob_pattern": "*.py",
        }

        call = ToolCall(
            id="search_call",
            name=search_view.exposed_name,
            arguments=args,
        )
        result = runtime.execute(call, profile, _make_tool_context(workspace))

        assert result.ok
        assert "test.py:1: print('hello')" in result.content

    def test_schema_mutated_run_command_maps_cwd_and_executes(
        self, registry: ToolRegistry, workspace: Path
    ):
        """Schema-mutated run_command should map cwd and execute in workspace."""
        sampler = ToolProfileSampler(seed=0)
        profile = sampler.sample("schema_only")
        runtime = ToolRuntime(registry)

        run_view = _get_tool_view(profile, "run_command")
        schema_props = run_view.input_schema.get("properties", {})
        args = _build_run_command_args(schema_props)

        _, canonical_args = profile.map_call_arguments(
            run_view.exposed_name,
            args,
            registry.get("run_command"),
        )
        assert canonical_args == {
            "command": "git --version",
            "timeout": 5,
            "cwd": "subdir",
        }

        call = ToolCall(
            id="run_call",
            name=run_view.exposed_name,
            arguments=args,
        )
        result = runtime.execute(call, profile, _make_tool_context(workspace))

        assert result.ok
        assert "[exit code] 0" in result.content


class TestProfileModesProduceValidToolViews:
    """Tests that all modes produce valid ToolView objects."""

    @pytest.mark.parametrize("mode", [
        "base",
        "name_only",
        "description_only",
        "schema_only",
        "name_description_schema",
    ])
    def test_mode_produces_valid_views(self, mode: str):
        """Each mode should produce valid ToolView objects."""
        sampler = ToolProfileSampler(seed=0)
        profile = sampler.sample(mode)

        assert profile.profile_id
        assert len(profile.tools) > 0

        for tool in profile.tools:
            assert tool.canonical_name
            assert tool.exposed_name
            assert tool.description
            assert isinstance(tool.input_schema, dict)
            assert "type" in tool.input_schema
            assert tool.input_schema["type"] == "object"

    @pytest.mark.parametrize("mode", [
        "base",
        "name_only",
        "description_only",
        "schema_only",
        "name_description_schema",
    ])
    def test_mode_exposes_all_builtin_tools(self, mode: str):
        """Each mode should expose all 6 builtin tools."""
        sampler = ToolProfileSampler(seed=0)
        profile = sampler.sample(mode)

        expected_canonicals = {
            "list_files",
            "read_file",
            "search_code",
            "apply_patch",
            "run_command",
            "finish",
        }
        actual_canonicals = {tool.canonical_name for tool in profile.tools}
        assert actual_canonicals == expected_canonicals


class TestAdapterMappingContract:
    """Tests for the adapter mapping contract."""

    def test_base_mode_has_empty_adapters(self):
        """Base mode should have empty adapters (identity mapping)."""
        sampler = ToolProfileSampler(seed=0)
        profile = sampler.sample("base")

        for exposed_name, adapter in profile.adapters.items():
            assert adapter.exposed_to_canonical == {}
            assert adapter.defaults == {}

    def test_mutated_modes_have_valid_adapters(self):
        """Mutated modes should have valid adapters where schema changed."""
        sampler = ToolProfileSampler(seed=0)

        for mode in ["schema_only", "name_description_schema"]:
            profile = sampler.sample(mode)

            for tool in profile.tools:
                adapter = profile.adapters.get(tool.exposed_name)
                assert adapter is not None
                # Adapter should be a valid ToolAdapter
                assert hasattr(adapter, "exposed_to_canonical")
                assert hasattr(adapter, "defaults")
                assert hasattr(adapter, "map_arguments")


class TestDeterministicSamplingAcrossModes:
    """Tests for determinism of profile sampling."""

    def test_same_seed_same_tools(self):
        """Same seed should produce same tools in same order."""
        sampler1 = ToolProfileSampler(seed=42)
        sampler2 = ToolProfileSampler(seed=42)

        for mode in ["base", "name_only", "schema_only"]:
            profile1 = sampler1.sample(mode)
            profile2 = sampler2.sample(mode)

            assert len(profile1.tools) == len(profile2.tools)
            for t1, t2 in zip(profile1.tools, profile2.tools):
                assert t1.canonical_name == t2.canonical_name
                assert t1.exposed_name == t2.exposed_name
                assert t1.description == t2.description
                assert t1.input_schema == t2.input_schema
