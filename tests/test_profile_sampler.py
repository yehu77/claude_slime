"""Tests for tool profile sampling."""

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


_CONFIGS_DIR = Path(__file__).parent.parent / "configs" / "tools"
_MUTATION_V1_CONFIG = _CONFIGS_DIR / "mutation_v1.yaml"
_SUPPORTED_MODES = {
    "base",
    "name_only",
    "description_only",
    "argument_rename",
    "schema_flat_to_nested",
    "tool_reorder",
    "schema_only",
    "name_description_schema",
}


def _expected_tool_count() -> int:
    return len(build_base_tool_profile().tools)


def _make_sampler_test_dir() -> Path:
    return make_unique_test_dir("profile_sampler", prefix="sampler")


def _cleanup_sampler_test_dir(test_dir: Path) -> None:
    cleanup_test_path(test_dir)


def _get_tool(profile: ToolProfile, canonical_name: str):
    return next(tool for tool in profile.tools if tool.canonical_name == canonical_name)


class TestSamplerDeterminism:
    def test_same_seed_same_mode_same_profile_id(self):
        p1 = ToolProfileSampler(seed=42).sample("schema_flat_to_nested")
        p2 = ToolProfileSampler(seed=42).sample("schema_flat_to_nested")
        assert p1.profile_id == p2.profile_id

    def test_same_seed_same_mode_same_tools(self):
        p1 = ToolProfileSampler(seed=42).sample("tool_reorder")
        p2 = ToolProfileSampler(seed=42).sample("tool_reorder")
        assert [tool.canonical_name for tool in p1.tools] == [
            tool.canonical_name for tool in p2.tools
        ]
        assert [tool.exposed_name for tool in p1.tools] == [
            tool.exposed_name for tool in p2.tools
        ]
        assert p1.metadata == p2.metadata

    def test_different_seed_different_profile_id(self):
        p1 = ToolProfileSampler(seed=1).sample("argument_rename")
        p2 = ToolProfileSampler(seed=2).sample("argument_rename")
        assert p1.profile_id != p2.profile_id


class TestSamplerConfigBacked:
    def test_sampler_loads_schema_variants(self):
        sampler = ToolProfileSampler(seed=42, mutation_config_path=_MUTATION_V1_CONFIG)
        config = sampler._get_mutation_config()

        assert "tool_variants" in config
        rf_variants = config["tool_variants"]["read_file"]
        assert "schema_variants" in rf_variants
        assert len(rf_variants["schema_variants"]) >= 3
        assert all("variant_id" in variant for variant in rf_variants["schema_variants"])
        assert {
            variant["category"] for variant in rf_variants["schema_variants"]
        } == {"argument_rename", "schema_flat_to_nested"}

    def test_base_mode_uses_builtin_base_profile_as_source_of_truth(self):
        test_dir = _make_sampler_test_dir()
        try:
            mutation_config = test_dir / "mutation.yaml"
            mutation_config.write_text(
                yaml.safe_dump(
                    {
                        "profile_id_prefix": "mutation",
                        "tool_variants": {
                            "search_code": {
                                "name_candidates": ["wrong_search_name"],
                                "description_candidates": ["WRONG BASE DESCRIPTION"],
                                "schema_variants": [
                                    {
                                        "category": "argument_rename",
                                        "input_schema": {
                                            "type": "object",
                                            "properties": {
                                                "pattern": {"type": "string"}
                                            },
                                            "required": ["pattern"],
                                        },
                                        "adapter": {
                                            "exposed_to_canonical": {"pattern": "query"}
                                        },
                                    }
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            sampler = ToolProfileSampler(seed=0, mutation_config_path=mutation_config)
            base_profile = build_base_tool_profile()
            base_search = _get_tool(base_profile, "search_code")
            sampled_base = sampler.sample("base")
            sampled_search = _get_tool(sampled_base, "search_code")

            assert sampled_search.exposed_name == base_search.exposed_name
            assert sampled_search.description == base_search.description
            assert sampled_search.input_schema == base_search.input_schema
        finally:
            _cleanup_sampler_test_dir(test_dir)

    def test_legacy_schema_candidates_still_load_and_classify(self):
        test_dir = _make_sampler_test_dir()
        try:
            legacy_config = test_dir / "legacy_mutation.yaml"
            legacy_config.write_text(
                yaml.safe_dump(
                    {
                        "profile_id_prefix": "mutation",
                        "tool_variants": {
                            "read_file": {
                                "schema_candidates": [
                                    {
                                        "input_schema": {
                                            "type": "object",
                                            "properties": {
                                                "target": {"type": "string"},
                                                "line_range": {
                                                    "type": "object",
                                                    "properties": {
                                                        "begin": {"type": "integer"},
                                                        "end": {"type": "integer"},
                                                    },
                                                },
                                            },
                                            "required": ["target"],
                                        },
                                        "adapter": {
                                            "exposed_to_canonical": {
                                                "target": "path",
                                                "line_range.begin": "start_line",
                                                "line_range.end": "end_line",
                                            }
                                        },
                                    },
                                    {
                                        "input_schema": {
                                            "type": "object",
                                            "properties": {
                                                "file_path": {"type": "string"},
                                                "start": {"type": "integer"},
                                                "stop": {"type": "integer"},
                                            },
                                            "required": ["file_path"],
                                        },
                                        "adapter": {
                                            "exposed_to_canonical": {
                                                "file_path": "path",
                                                "start": "start_line",
                                                "stop": "end_line",
                                            }
                                        },
                                    },
                                ]
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            sampler = ToolProfileSampler(seed=0, mutation_config_path=legacy_config)
            nested_profile = sampler.sample("schema_flat_to_nested")
            rename_profile = sampler.sample("argument_rename")

            assert _get_tool(nested_profile, "read_file").metadata["schema_variant_category"] == "schema_flat_to_nested"
            assert _get_tool(rename_profile, "read_file").metadata["schema_variant_category"] == "argument_rename"
        finally:
            _cleanup_sampler_test_dir(test_dir)


class TestSamplerModes:
    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Invalid mode"):
            ToolProfileSampler(seed=42).sample("nonexistent")

    @pytest.mark.parametrize("mode", sorted(_SUPPORTED_MODES))
    def test_all_modes_produce_profiles(self, mode: str):
        profile = ToolProfileSampler(seed=0).sample(mode)
        assert isinstance(profile, ToolProfile)
        assert len(profile.tools) == _expected_tool_count()
        assert profile.metadata["mode"] == mode

    def test_argument_rename_only_uses_argument_rename_schema_category(self):
        profile = ToolProfileSampler(seed=0).sample("argument_rename")
        categories = {
            tool.metadata["schema_variant_category"]
            for tool in profile.tools
            if tool.metadata["schema_mutated"]
        }
        assert categories == {"argument_rename"}
        assert all(not tool.metadata["name_mutated"] for tool in profile.tools)
        assert all(not tool.metadata["description_mutated"] for tool in profile.tools)

    def test_schema_flat_to_nested_only_uses_nested_schema_category(self):
        profile = ToolProfileSampler(seed=0).sample("schema_flat_to_nested")
        categories = {
            tool.metadata["schema_variant_category"]
            for tool in profile.tools
            if tool.metadata["schema_mutated"]
        }
        assert categories == {"schema_flat_to_nested"}
        assert all(not tool.metadata["name_mutated"] for tool in profile.tools)
        assert all(not tool.metadata["description_mutated"] for tool in profile.tools)

    def test_tool_reorder_preserves_tool_definitions_but_changes_order(self):
        sampler = ToolProfileSampler(seed=0)
        base_profile = sampler.sample("base")
        reorder_profile = sampler.sample("tool_reorder")

        base_order = [tool.canonical_name for tool in base_profile.tools]
        reordered = [tool.canonical_name for tool in reorder_profile.tools]

        assert set(base_order) == set(reordered)
        assert reordered != base_order
        assert reordered[-1] == "finish"

        for tool in reorder_profile.tools:
            base_tool = _get_tool(base_profile, tool.canonical_name)
            assert tool.exposed_name == base_tool.exposed_name
            assert tool.description == base_tool.description
            assert tool.input_schema == base_tool.input_schema
            assert tool.metadata["tool_order_index_exposed"] != tool.metadata["tool_order_index_base"] or reordered != base_order
            assert tool.metadata["tool_reordered"] == (
                tool.metadata["tool_order_index_exposed"] != tool.metadata["tool_order_index_base"]
            )

        assert reorder_profile.metadata["tool_order_seed"] == 0
        assert reorder_profile.metadata["mutation_axes"] == ["tool_reorder"]
        assert reorder_profile.metadata["reorder_anchor_policy"] == "finish_last"

    def test_schema_only_sets_compat_mode(self):
        profile = ToolProfileSampler(seed=0).sample("schema_only")
        assert profile.metadata["compat_mode"] == "schema_only"
        assert profile.metadata["mutation_axes"] == ["schema"]

    def test_name_description_schema_sets_compat_mode(self):
        profile = ToolProfileSampler(seed=0).sample("name_description_schema")
        assert profile.metadata["compat_mode"] == "name_description_schema"
        assert profile.metadata["mutation_axes"] == ["name", "description", "schema"]


class TestSamplerMetadata:
    def test_tool_metadata_contains_order_and_mutation_flags(self):
        profile = ToolProfileSampler(seed=0).sample("name_description_schema")

        for exposed_index, tool in enumerate(profile.tools):
            assert tool.metadata["tool_order_index_exposed"] == exposed_index
            assert isinstance(tool.metadata["tool_order_index_base"], int)
            assert "name_variant_id" in tool.metadata
            assert "description_variant_id" in tool.metadata
            assert "schema_variant_id" in tool.metadata
            assert "schema_variant_category" in tool.metadata
            assert "name_mutated" in tool.metadata
            assert "description_mutated" in tool.metadata
            assert "schema_mutated" in tool.metadata
            assert "tool_reordered" in tool.metadata

    def test_profile_metadata_contains_schema_variant_categories(self):
        profile = ToolProfileSampler(seed=0).sample("schema_flat_to_nested")
        assert set(profile.metadata["schema_variant_categories"]) == {
            tool.canonical_name for tool in profile.tools
        }
        assert set(profile.metadata["selected_variant_ids"]) == {
            tool.canonical_name for tool in profile.tools
        }
        assert profile.metadata["mutation_manifest_version"] == 1
        assert profile.metadata["reorder_anchor_policy"] == "finish_last"


class TestSamplerRuntimeCompatibility:
    def test_argument_rename_profile_maps_read_file_arguments(self):
        profile = ToolProfileSampler(seed=0).sample("argument_rename")
        view = _get_tool(profile, "read_file")

        if view.metadata["schema_variant_category"] != "argument_rename":
            pytest.skip("read_file did not receive an argument_rename variant")

        _, canonical_args = profile.map_call_arguments(
            view.exposed_name,
            {"file_path": "test.py", "start": 1, "stop": 5},
        )
        assert canonical_args == {"path": "test.py", "start_line": 1, "end_line": 5}

    def test_schema_flat_to_nested_profile_maps_read_file_arguments(self):
        profile = ToolProfileSampler(seed=0).sample("schema_flat_to_nested")
        view = _get_tool(profile, "read_file")

        if view.metadata["schema_variant_category"] != "schema_flat_to_nested":
            pytest.skip("read_file did not receive a nested variant")

        props = set(view.input_schema.get("properties", {}))
        if "target" in props:
            exposed_args = {"target": "test.py", "line_range": {"begin": 1, "end": 5}}
        else:
            exposed_args = {"file": "test.py", "lines": {"from": 1, "to": 5}}

        _, canonical_args = profile.map_call_arguments(
            view.exposed_name,
            exposed_args,
        )
        assert canonical_args == {"path": "test.py", "start_line": 1, "end_line": 5}

    def test_argument_rename_profile_maps_write_file_arguments(self):
        profile = ToolProfileSampler(seed=0).sample("argument_rename")
        view = _get_tool(profile, "write_file")

        _, canonical_args = profile.map_call_arguments(
            view.exposed_name,
            {"file": "test.py", "text": "print('ok')\n"},
        )
        assert canonical_args == {"path": "test.py", "content": "print('ok')\n"}

    def test_schema_flat_to_nested_profile_maps_python_run_arguments(self):
        profile = ToolProfileSampler(seed=0).sample("schema_flat_to_nested")
        view = _get_tool(profile, "python_run")

        _, canonical_args = profile.map_call_arguments(
            view.exposed_name,
            {
                "execution": {
                    "target": "pytest",
                    "run_as_module": True,
                },
                "options": {
                    "args": ["-q"],
                    "timeout": 30,
                    "cwd": ".",
                },
            },
        )
        assert canonical_args == {
            "target": "pytest",
            "run_as_module": True,
            "args": ["-q"],
            "timeout": 30,
            "cwd": ".",
        }

    def test_sampled_profile_get_exposed_specs(self):
        profile = ToolProfileSampler(seed=42).sample("name_description_schema")
        specs = profile.get_exposed_specs()
        assert len(specs) == _expected_tool_count()
        for spec in specs:
            assert {"name", "description", "input_schema"} <= set(spec)


class TestBuildSampledToolProfile:
    def test_build_without_config(self):
        profile = build_sampled_tool_profile(mode="base", seed=42)
        assert isinstance(profile, ToolProfile)

    def test_build_with_standard_config(self):
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
            assert profile.profile_id == "direct_profile"
        finally:
            _cleanup_sampler_test_dir(test_dir)

    def test_build_with_mutation_config(self):
        profile = build_sampled_tool_profile(
            mode="argument_rename",
            seed=42,
            config_path=_MUTATION_V1_CONFIG,
        )
        assert isinstance(profile, ToolProfile)


class TestSampleAllModes:
    def test_returns_all_supported_modes(self):
        profiles = ToolProfileSampler(seed=42).sample_all_modes()
        assert set(profiles) == _SUPPORTED_MODES

    def test_all_profiles_valid(self):
        profiles = ToolProfileSampler(seed=42).sample_all_modes()
        for profile in profiles.values():
            assert isinstance(profile, ToolProfile)
            assert len(profile.tools) == _expected_tool_count()
