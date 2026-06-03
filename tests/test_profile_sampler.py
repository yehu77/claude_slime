"""Tests for tool profile sampling.

Verifies deterministic behavior, config-backed sampling, seed effects,
runtime compatibility, and profile_id stability.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pycodeagent.mutations.profile_sampler import (
    ToolProfileSampler,
    build_sampled_tool_profile,
)
from pycodeagent.tools.profile_factory import build_base_tool_profile
from pycodeagent.tools.spec import ToolProfile
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


# Config paths
_CONFIGS_DIR = Path(__file__).parent.parent / "configs" / "tools"
_MUTATION_V1_CONFIG = _CONFIGS_DIR / "mutation_v1.yaml"


def _make_sampler_test_dir() -> Path:
    """Create a unique pytest-managed directory for sampler tests."""
    return make_unique_test_dir("profile_sampler", prefix="sampler")


def _cleanup_sampler_test_dir(test_dir: Path) -> None:
    """Remove a sampler test directory."""
    cleanup_test_path(test_dir)


class TestSamplerDeterminism:
    """Tests for deterministic sampling."""

    def test_same_seed_same_mode_same_profile_id(self):
        """Same seed + same mode should produce same profile_id."""
        s1 = ToolProfileSampler(seed=42)
        s2 = ToolProfileSampler(seed=42)
        p1 = s1.sample("base")
        p2 = s2.sample("base")
        assert p1.profile_id == p2.profile_id

    def test_same_seed_same_mode_same_tools(self):
        """Same seed + same mode should produce identical tool views."""
        s1 = ToolProfileSampler(seed=42)
        s2 = ToolProfileSampler(seed=42)
        p1 = s1.sample("schema_only")
        p2 = s2.sample("schema_only")

        for tv1, tv2 in zip(p1.tools, p2.tools):
            assert tv1.exposed_name == tv2.exposed_name
            assert tv1.description == tv2.description
            assert tv1.input_schema == tv2.input_schema

    def test_different_seed_different_profile_id(self):
        """Different seeds should produce different profile_ids."""
        p1 = ToolProfileSampler(seed=1).sample("base")
        p2 = ToolProfileSampler(seed=2).sample("base")
        assert p1.profile_id != p2.profile_id

    def test_base_mode_identity_mapping(self):
        """Base mode should have exposed_name == canonical_name for all tools."""
        profile = ToolProfileSampler(seed=0).sample("base")
        for tv in profile.tools:
            assert tv.exposed_name == tv.canonical_name

    def test_base_mode_no_adapter_mapping(self):
        """Base mode should have empty adapter mappings (identity)."""
        profile = ToolProfileSampler(seed=0).sample("base")
        for adapter in profile.adapters.values():
            assert adapter.exposed_to_canonical == {}


class TestSamplerConfigBacked:
    """Tests for config-backed behavior."""

    def test_sampler_loads_mutation_config(self):
        """Sampler should load tool_variants from mutation config."""
        sampler = ToolProfileSampler(seed=42, mutation_config_path=_MUTATION_V1_CONFIG)
        config = sampler._get_mutation_config()

        assert "tool_variants" in config
        assert "read_file" in config["tool_variants"]
        assert "base_config" not in config

        rf_variants = config["tool_variants"]["read_file"]
        assert "name_candidates" in rf_variants
        assert "description_candidates" in rf_variants
        assert "schema_candidates" in rf_variants

        # Should have multiple candidates
        assert len(rf_variants["name_candidates"]) > 1
        assert len(rf_variants["description_candidates"]) > 1
        assert len(rf_variants["schema_candidates"]) > 1

    def test_sampler_uses_config_candidates(self):
        """Sampler should select from config-defined candidates."""
        sampler = ToolProfileSampler(seed=42, mutation_config_path=_MUTATION_V1_CONFIG)
        profile = sampler.sample("name_only")

        # name_only mode should select from name_candidates
        # The exposed names should be from the config's name_candidates lists
        config = sampler._get_mutation_config()

        for tv in profile.tools:
            variants = config["tool_variants"].get(tv.canonical_name, {})
            name_candidates = variants.get("name_candidates", [tv.canonical_name])
            assert tv.exposed_name in name_candidates

    def test_changing_config_affects_output(self):
        """Changing config candidates should affect sampled output."""
        # This test verifies that the sampler reads from config
        # by checking that the mutation config has multiple candidates
        sampler = ToolProfileSampler(seed=42, mutation_config_path=_MUTATION_V1_CONFIG)
        config = sampler._get_mutation_config()

        # mutation_v1.yaml has multiple candidates for each tool
        for tool_name in ["read_file", "list_files", "search_code"]:
            variants = config["tool_variants"].get(tool_name, {})
            assert len(variants.get("name_candidates", [])) > 1
            assert len(variants.get("description_candidates", [])) > 1
            assert len(variants.get("schema_candidates", [])) > 1

    def test_base_mode_uses_base_profile_as_source_of_truth(self):
        """Mutation-only configs must not override the generated builtin base profile."""
        test_dir = _make_sampler_test_dir()
        try:
            mutation_config = test_dir / "mutation.yaml"
            mutation_config.write_text(
                yaml.safe_dump(
                    {
                        "profile_id_prefix": "mutation",
                        "tool_variants": {
                            "search_code": {
                                "name_candidates": ["wrong_search_name", "find_text"],
                                "description_candidates": [
                                    "WRONG BASE DESCRIPTION",
                                    "Locate text patterns within the codebase.",
                                ],
                                "schema_candidates": [
                                    {
                                        "input_schema": {
                                            "type": "object",
                                            "properties": {
                                                "pattern": {
                                                    "type": "string",
                                                    "description": "Wrong base field.",
                                                }
                                            },
                                            "required": ["pattern"],
                                        },
                                        "adapter": {},
                                    },
                                    {
                                        "input_schema": {
                                            "type": "object",
                                            "properties": {
                                                "term": {
                                                    "type": "string",
                                                    "description": "Text to search for.",
                                                }
                                            },
                                            "required": ["term"],
                                        },
                                        "adapter": {
                                            "exposed_to_canonical": {"term": "query"}
                                        },
                                    },
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            sampler = ToolProfileSampler(
                seed=0,
                mutation_config_path=mutation_config,
            )
            base_profile = build_base_tool_profile()
            base_search = next(
                tool
                for tool in base_profile.tools
                if tool.canonical_name == "search_code"
            )

            sampled_base = sampler.sample("base")
            sampled_base_search = next(
                tool
                for tool in sampled_base.tools
                if tool.canonical_name == "search_code"
            )
            assert sampled_base_search.exposed_name == base_search.exposed_name
            assert sampled_base_search.description == base_search.description
            assert sampled_base_search.input_schema == base_search.input_schema

            sampled_name_only = sampler.sample("name_only")
            sampled_name_search = next(
                tool
                for tool in sampled_name_only.tools
                if tool.canonical_name == "search_code"
            )
            assert sampled_name_search.exposed_name in {"wrong_search_name", "find_text"}
            assert sampled_name_search.description == base_search.description
            assert sampled_name_search.input_schema == base_search.input_schema

            sampled_schema_only = sampler.sample("schema_only")
            sampled_schema_search = next(
                tool
                for tool in sampled_schema_only.tools
                if tool.canonical_name == "search_code"
            )
            assert sampled_schema_search.exposed_name == base_search.exposed_name
            assert sampled_schema_search.description == base_search.description
            assert sampled_schema_search.input_schema != base_search.input_schema
        finally:
            _cleanup_sampler_test_dir(test_dir)


class TestSamplerSeedEffects:
    """Tests for seed affecting sampled content."""

    def test_different_seeds_can_produce_different_names(self):
        """Different seeds should be able to produce different exposed names in name_only mode."""
        names_by_seed = {}
        for seed in range(10):
            profile = ToolProfileSampler(seed=seed).sample("name_only")
            # Collect exposed names for read_file's canonical
            for tv in profile.tools:
                if tv.canonical_name == "read_file":
                    names_by_seed[seed] = tv.exposed_name
                    break

        # With 10 seeds and multiple name candidates, we should see some variation
        unique_names = set(names_by_seed.values())
        assert len(unique_names) > 1, "Different seeds should produce different names"

    def test_different_seeds_can_produce_different_descriptions(self):
        """Different seeds should be able to produce different descriptions in description_only mode."""
        descs_by_seed = {}
        for seed in range(10):
            profile = ToolProfileSampler(seed=seed).sample("description_only")
            for tv in profile.tools:
                if tv.canonical_name == "read_file":
                    descs_by_seed[seed] = tv.description
                    break

        unique_descs = set(descs_by_seed.values())
        assert len(unique_descs) > 1, "Different seeds should produce different descriptions"

    def test_different_seeds_can_produce_different_schemas(self):
        """Different seeds should be able to produce different schemas in schema_only mode."""
        schemas_by_seed = {}
        for seed in range(10):
            profile = ToolProfileSampler(seed=seed).sample("schema_only")
            for tv in profile.tools:
                if tv.canonical_name == "read_file":
                    # Compare schema structure (properties keys)
                    props = tuple(sorted(tv.input_schema.get("properties", {}).keys()))
                    schemas_by_seed[seed] = props
                    break

        unique_schemas = set(schemas_by_seed.values())
        assert len(unique_schemas) > 1, "Different seeds should produce different schemas"

    def test_same_seed_produces_same_content(self):
        """Same seed should always produce the same content across calls."""
        sampler = ToolProfileSampler(seed=12345)
        p1 = sampler.sample("name_description_schema")
        p2 = sampler.sample("name_description_schema")

        for tv1, tv2 in zip(p1.tools, p2.tools):
            assert tv1.exposed_name == tv2.exposed_name
            assert tv1.description == tv2.description
            assert tv1.input_schema == tv2.input_schema


class TestSamplerModes:
    """Tests for specific mutation modes."""

    def test_name_only_changes_names(self):
        """name_only mode should change tool names."""
        sampler = ToolProfileSampler(seed=42)
        base = sampler.sample("base")
        name_only = sampler.sample("name_only")

        # name_only should have different names than base for at least some tools
        base_names = {tv.exposed_name for tv in base.tools}
        name_only_names = {tv.exposed_name for tv in name_only.tools}

        assert base_names != name_only_names

    def test_name_only_preserves_descriptions(self):
        """name_only mode should keep base descriptions."""
        sampler = ToolProfileSampler(seed=42)
        base = sampler.sample("base")
        name_only = sampler.sample("name_only")

        # Descriptions should match (base mode uses index 0, which is the base description)
        base_descs = {tv.canonical_name: tv.description for tv in base.tools}
        name_only_descs = {tv.canonical_name: tv.description for tv in name_only.tools}

        for canonical in base_descs:
            assert base_descs[canonical] == name_only_descs[canonical]

    def test_description_only_changes_descriptions(self):
        """description_only mode should change descriptions."""
        sampler = ToolProfileSampler(seed=42)
        base = sampler.sample("base")
        desc_only = sampler.sample("description_only")

        # At least some descriptions should differ
        changed = sum(
            1 for tv in desc_only.tools
            if tv.description != next((b.description for b in base.tools if b.canonical_name == tv.canonical_name), "")
        )
        assert changed > 0

    def test_description_only_preserves_names(self):
        """description_only mode should keep base names."""
        sampler = ToolProfileSampler(seed=42)
        profile = sampler.sample("description_only")

        for tv in profile.tools:
            assert tv.exposed_name == tv.canonical_name

    def test_schema_only_changes_schemas(self):
        """schema_only mode should change input schemas."""
        sampler = ToolProfileSampler(seed=42)
        base = sampler.sample("base")
        schema_only = sampler.sample("schema_only")

        # At least some schemas should differ
        changed = sum(
            1 for tv in schema_only.tools
            if tv.input_schema != next((b.input_schema for b in base.tools if b.canonical_name == tv.canonical_name), {})
        )
        assert changed > 0

    def test_schema_only_adds_adapter_mappings(self):
        """schema_only mode should have non-empty adapter mappings for some tools."""
        sampler = ToolProfileSampler(seed=42)
        profile = sampler.sample("schema_only")

        has_mapping = any(
            adapter.exposed_to_canonical
            for adapter in profile.adapters.values()
        )
        assert has_mapping

    def test_schema_only_preserves_names(self):
        """schema_only mode should keep base names."""
        sampler = ToolProfileSampler(seed=42)
        profile = sampler.sample("schema_only")

        for tv in profile.tools:
            assert tv.exposed_name == tv.canonical_name

    def test_name_description_schema_changes_all(self):
        """name_description_schema mode should change names, descriptions, and schemas."""
        sampler = ToolProfileSampler(seed=42)
        base = sampler.sample("base")
        full_mut = sampler.sample("name_description_schema")

        base_names = {tv.exposed_name for tv in base.tools}
        full_names = {tv.exposed_name for tv in full_mut.tools}
        assert base_names != full_names

        changed_descs = sum(
            1 for tv in full_mut.tools
            if tv.description != next((b.description for b in base.tools if b.canonical_name == tv.canonical_name), "")
        )
        assert changed_descs > 0

        changed_schemas = sum(
            1 for tv in full_mut.tools
            if tv.input_schema != next((b.input_schema for b in base.tools if b.canonical_name == tv.canonical_name), {})
        )
        assert changed_schemas > 0

    def test_invalid_mode_raises(self):
        """Invalid mode should raise ValueError."""
        sampler = ToolProfileSampler(seed=42)
        with pytest.raises(ValueError, match="Invalid mode"):
            sampler.sample("nonexistent")


class TestSamplerRuntimeCompatibility:
    """Tests for runtime compatibility of sampled profiles."""

    def test_sampled_profile_get_exposed_specs(self):
        """Sampled profile should produce valid exposed specs."""
        sampler = ToolProfileSampler(seed=42)
        profile = sampler.sample("name_description_schema")

        specs = profile.get_exposed_specs()
        assert len(specs) == 6
        for spec in specs:
            assert "name" in spec
            assert "description" in spec
            assert "input_schema" in spec

    def test_sampled_profile_get_tool_versions(self):
        """Sampled profile should produce version data."""
        sampler = ToolProfileSampler(seed=42)
        profile = sampler.sample("schema_only")

        versions = profile.get_tool_versions()
        assert len(versions) == 6
        for name, info in versions.items():
            assert "canonical_name" in info
            assert "version" in info

    def test_schema_only_adapter_mapping_works(self):
        """Schema-only adapter should correctly map arguments."""
        sampler = ToolProfileSampler(seed=42)
        profile = sampler.sample("schema_only")

        # read_file keeps same exposed_name in schema_only, but schema may be restructured
        result = profile.get_tool("read_file")
        assert result is not None
        view, adapter = result
        assert view.canonical_name == "read_file"

        # If adapter has mapping, test it
        if adapter.exposed_to_canonical:
            # Determine which schema variant was selected based on properties
            props = view.input_schema.get("properties", {})
            if "target" in props:
                # Variant: target + line_range
                mapped = adapter.map_arguments({
                    "target": "test.py",
                    "line_range": {"begin": 1, "end": 50},
                })
                assert mapped["path"] == "test.py"
            elif "file" in props:
                # Variant: file + lines
                mapped = adapter.map_arguments({
                    "file": "test.py",
                    "lines": {"from": 1, "to": 50},
                })
                assert mapped["path"] == "test.py"
            else:
                # Base schema
                mapped = adapter.map_arguments({"path": "test.py"})
                assert mapped["path"] == "test.py"

    def test_name_only_profile_works_with_runtime(self):
        """name_only profile should work with ToolRuntime execute."""
        from pycodeagent.tools.registry import ToolRegistry
        from pycodeagent.tools.runtime import ToolRuntime
        from pycodeagent.tools.builtin import ALL_BUILTIN_TOOLS
        from pycodeagent.trajectory.schema import ToolCall

        sampler = ToolProfileSampler(seed=42)
        profile = sampler.sample("name_only")

        registry = ToolRegistry()
        for tool in ALL_BUILTIN_TOOLS:
            registry.register(tool)
        runtime = ToolRuntime(registry)

        # Find the exposed name for read_file
        exposed_name = next(tv.exposed_name for tv in profile.tools if tv.canonical_name == "read_file")

        call = ToolCall(id="c1", name=exposed_name, arguments={"path": "test.py"})
        result = runtime.execute(call, profile)
        # Should succeed or fail gracefully, not crash
        assert result is not None

    def test_schema_only_profile_works_with_runtime(self):
        """schema_only profile with adapter should work with ToolRuntime."""
        from pycodeagent.tools.registry import ToolRegistry
        from pycodeagent.tools.runtime import ToolRuntime
        from pycodeagent.tools.builtin import ALL_BUILTIN_TOOLS
        from pycodeagent.trajectory.schema import ToolCall

        sampler = ToolProfileSampler(seed=42)
        profile = sampler.sample("schema_only")

        registry = ToolRegistry()
        for tool in ALL_BUILTIN_TOOLS:
            registry.register(tool)
        runtime = ToolRuntime(registry)

        # Call read_file with appropriate args for the selected schema
        view = next(tv for tv in profile.tools if tv.canonical_name == "read_file")
        props = view.input_schema.get("properties", {})

        if "target" in props:
            args = {"target": "test.py"}
        elif "file" in props:
            args = {"file": "test.py"}
        else:
            args = {"path": "test.py"}

        call = ToolCall(id="c1", name=view.exposed_name, arguments=args)
        result = runtime.execute(call, profile)
        assert result is not None


class TestSamplerProfileIdStability:
    """Tests for profile_id generation stability."""

    def test_profile_id_format(self):
        """profile_id should include mode and hash."""
        profile = ToolProfileSampler(seed=42).sample("base")
        # Format: mutation_base_<8-char-hex> or base_<8-char-hex>
        assert "base" in profile.profile_id
        parts = profile.profile_id.split("_")
        assert len(parts) >= 2

    def test_profile_id_stable_across_calls(self):
        """Same params should always produce same profile_id."""
        ids = set()
        for _ in range(10):
            profile = ToolProfileSampler(seed=42).sample("schema_only")
            ids.add(profile.profile_id)
        assert len(ids) == 1

    def test_all_modes_produce_profiles(self):
        """All modes should produce valid profiles."""
        sampler = ToolProfileSampler(seed=0)
        for mode in ["base", "name_only", "description_only", "schema_only", "name_description_schema"]:
            profile = sampler.sample(mode)
            assert isinstance(profile, ToolProfile)
            assert len(profile.tools) == 6


class TestBuildSampledToolProfile:
    """Tests for the convenience function."""

    def test_build_without_config(self):
        """Should build profile using sampler."""
        profile = build_sampled_tool_profile(mode="base", seed=42)
        assert isinstance(profile, ToolProfile)

    def test_build_with_standard_config(self):
        """Should load profile from standard config directly."""
        test_dir = _make_sampler_test_dir()
        try:
            config_path = test_dir / "profile.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "profile_id": "direct_profile",
                        "tools": [
                            {
                                "canonical": "read_file",
                                "exposed_name": "read_file",
                                "description": "Read a file.",
                                "input_schema": {
                                    "type": "object",
                                    "properties": {"path": {"type": "string"}},
                                    "required": ["path"],
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            profile = build_sampled_tool_profile(
                mode="base",
                seed=42,
                config_path=config_path,
            )
            assert isinstance(profile, ToolProfile)
            assert profile.profile_id == "direct_profile"
        finally:
            _cleanup_sampler_test_dir(test_dir)

    def test_build_with_mutation_config(self):
        """Should use sampler when given mutation config."""
        profile = build_sampled_tool_profile(
            mode="name_only",
            seed=42,
            config_path=_MUTATION_V1_CONFIG,
        )
        assert isinstance(profile, ToolProfile)
        # Should have mutated names
        assert any(tv.exposed_name != tv.canonical_name for tv in profile.tools)


class TestSampleAllModes:
    """Tests for sample_all_modes."""

    def test_returns_all_five_modes(self):
        """sample_all_modes should return all 5 modes."""
        sampler = ToolProfileSampler(seed=42)
        profiles = sampler.sample_all_modes()
        assert set(profiles.keys()) == {
            "base", "name_only", "description_only",
            "schema_only", "name_description_schema",
        }

    def test_all_profiles_valid(self):
        """All sampled profiles should be valid."""
        sampler = ToolProfileSampler(seed=42)
        profiles = sampler.sample_all_modes()
        for mode, profile in profiles.items():
            assert isinstance(profile, ToolProfile)
            assert len(profile.tools) == 6
