"""Tests for tool profile config loading.

Verifies that YAML configs load correctly and produce valid ToolProfile objects.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pycodeagent.mutations.profile_loader import (
    load_tool_profile,
    load_tool_profile_from_dict,
)
from pycodeagent.tools.builtin import ALL_BUILTIN_TOOLS
from pycodeagent.tools.profile_factory import build_base_tool_profile
from pycodeagent.tools.spec import ToolProfile
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


# --- Test directory helpers ---


def _make_test_dir() -> Path:
    """Create a unique pytest-managed test directory."""
    return make_unique_test_dir("profile_loader", prefix="loader")


def _cleanup(test_dir: Path) -> None:
    """Remove the test directory."""
    cleanup_test_path(test_dir)


# --- Config paths ---

_CONFIGS_DIR = Path(__file__).parent.parent / "configs" / "tools"
_BASE_CONFIG = _CONFIGS_DIR / "base.yaml"
_MUTATION_V1_CONFIG = _CONFIGS_DIR / "mutation_v1.yaml"


class TestLoadToolProfile:
    """Tests for load_tool_profile from YAML files."""

    def test_legacy_base_config_loads_successfully(self):
        """Legacy base config snapshot should still load without errors."""
        profile = load_tool_profile(_BASE_CONFIG)
        assert isinstance(profile, ToolProfile)
        assert profile.profile_id == "base"

    def test_mutation_v1_config_has_expected_structure(self):
        """Mutation v1 config should have tool_variants structure."""
        import yaml
        with open(_MUTATION_V1_CONFIG, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "tool_variants" in data
        assert "profile_id_prefix" in data
        assert data["profile_id_prefix"] == "mutation"
        assert "base_config" not in data

    def test_generated_base_profile_has_expected_tools(self):
        """Generated base profile should have all builtin tools."""
        profile = build_base_tool_profile()
        tool_names = {tv.exposed_name for tv in profile.tools}
        expected = {"list_files", "read_file", "search_code", "apply_patch", "run_command", "finish"}
        assert tool_names == expected

    def test_generated_base_profile_matches_builtin_contracts(self):
        """Generated base profile must be derived from builtin canonical tools."""
        profile = build_base_tool_profile()
        profile_tools = {tool.canonical_name: tool for tool in profile.tools}
        builtin_tools = {tool.canonical_name: tool for tool in ALL_BUILTIN_TOOLS}

        assert set(profile_tools) == set(builtin_tools)

        for canonical_name, builtin_tool in builtin_tools.items():
            loaded_view = profile_tools[canonical_name]

            assert loaded_view.exposed_name == builtin_tool.canonical_name
            assert loaded_view.description == builtin_tool.description
            assert loaded_view.input_schema == builtin_tool.canonical_schema

    def test_legacy_base_config_matches_generated_base_profile(self):
        """Legacy base config snapshot must match the generated base profile."""
        loaded = load_tool_profile(_BASE_CONFIG)
        generated = build_base_tool_profile()

        loaded_tools = {tool.canonical_name: tool for tool in loaded.tools}
        generated_tools = {tool.canonical_name: tool for tool in generated.tools}

        assert loaded.profile_id == generated.profile_id
        assert set(loaded_tools) == set(generated_tools)

        for canonical_name, generated_view in generated_tools.items():
            loaded_view = loaded_tools[canonical_name]
            assert loaded_view.exposed_name == generated_view.exposed_name
            assert loaded_view.description == generated_view.description
            assert loaded_view.input_schema == generated_view.input_schema

    def test_exposed_specs_are_well_formed(self):
        """get_exposed_specs should produce valid tool specs."""
        profile = build_base_tool_profile()
        specs = profile.get_exposed_specs()

        assert len(specs) == 6
        for spec in specs:
            assert "name" in spec
            assert "description" in spec
            assert "input_schema" in spec
            assert isinstance(spec["name"], str)
            assert isinstance(spec["description"], str)
            assert isinstance(spec["input_schema"], dict)

    def test_file_not_found_raises(self):
        """Loading a non-existent config should raise FileNotFoundError."""
        test_dir = _make_test_dir()
        try:
            nonexistent = test_dir / "nonexistent.yaml"
            with pytest.raises(FileNotFoundError):
                load_tool_profile(nonexistent)
        finally:
            _cleanup(test_dir)

    def test_invalid_yaml_raises(self):
        """Loading invalid YAML should raise."""
        test_dir = _make_test_dir()
        try:
            bad_yaml = test_dir / "bad.yaml"
            bad_yaml.write_text("this is not: valid: yaml: [", encoding="utf-8")
            with pytest.raises(Exception):  # yaml.scanner.ScannerError or similar
                load_tool_profile(bad_yaml)
        finally:
            _cleanup(test_dir)

    def test_missing_profile_id_raises(self):
        """Config without profile_id should raise ValueError."""
        test_dir = _make_test_dir()
        try:
            config_file = test_dir / "no_id.yaml"
            config_file.write_text("tools: []", encoding="utf-8")
            with pytest.raises(ValueError, match="profile_id"):
                load_tool_profile(config_file)
        finally:
            _cleanup(test_dir)

    def test_missing_tools_raises(self):
        """Config without tools list should raise ValueError."""
        test_dir = _make_test_dir()
        try:
            config_file = test_dir / "no_tools.yaml"
            config_file.write_text("profile_id: test", encoding="utf-8")
            with pytest.raises(ValueError, match="tools"):
                load_tool_profile(config_file)
        finally:
            _cleanup(test_dir)


class TestLoadToolProfileFromDict:
    """Tests for load_tool_profile_from_dict - no temp file dependency."""

    def test_minimal_valid_config(self):
        """Minimal valid config should load without temp file."""
        data = {
            "profile_id": "test",
            "tools": [
                {
                    "canonical": "read_file",
                    "exposed_name": "read_file",
                    "description": "Read a file.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                }
            ],
        }
        profile = load_tool_profile_from_dict(data)
        assert profile.profile_id == "test"
        assert len(profile.tools) == 1
        assert profile.tools[0].exposed_name == "read_file"

    def test_adapter_mapping_loaded(self):
        """Adapter mapping should be loaded correctly."""
        data = {
            "profile_id": "test",
            "tools": [
                {
                    "canonical": "read_file",
                    "exposed_name": "open_source",
                    "description": "Inspect source.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                    "adapter": {
                        "exposed_to_canonical": {"target": "path"},
                        "defaults": {"start_line": 1},
                    },
                }
            ],
        }
        profile = load_tool_profile_from_dict(data)
        adapter = profile.adapters.get("open_source")
        assert adapter is not None
        assert adapter.exposed_to_canonical == {"target": "path"}
        assert adapter.defaults == {"start_line": 1}

    def test_invalid_dict_type_raises(self):
        """Non-dict input should raise ValueError."""
        with pytest.raises(ValueError, match="mapping"):
            load_tool_profile_from_dict("not a dict")

    def test_missing_profile_id_raises(self):
        """Dict without profile_id should raise ValueError."""
        with pytest.raises(ValueError, match="profile_id"):
            load_tool_profile_from_dict({"tools": []})

    def test_missing_tools_raises(self):
        """Dict without tools should raise ValueError."""
        with pytest.raises(ValueError, match="tools"):
            load_tool_profile_from_dict({"profile_id": "test"})

    def test_invalid_tool_entry_raises(self):
        """Invalid tool entry should raise ValueError."""
        with pytest.raises(ValueError, match="tools"):
            load_tool_profile_from_dict({
                "profile_id": "test",
                "tools": ["not a dict"],
            })

    def test_missing_canonical_raises(self):
        """Tool without canonical name should raise ValueError."""
        with pytest.raises(ValueError, match="canonical"):
            load_tool_profile_from_dict({
                "profile_id": "test",
                "tools": [{
                    "exposed_name": "test",
                    "input_schema": {},
                }],
            })

    def test_missing_exposed_name_raises(self):
        """Tool without exposed_name should raise ValueError."""
        with pytest.raises(ValueError, match="exposed_name"):
            load_tool_profile_from_dict({
                "profile_id": "test",
                "tools": [{
                    "canonical": "test",
                    "input_schema": {},
                }],
            })


class TestProfileCompatibility:
    """Tests for profile compatibility with runtime."""

    def test_get_tool_returns_view_and_adapter(self):
        """get_tool should return (ToolView, ToolAdapter) tuple."""
        profile = build_base_tool_profile()
        result = profile.get_tool("read_file")
        assert result is not None
        view, adapter = result
        assert view.exposed_name == "read_file"
        assert view.canonical_name == "read_file"

    def test_get_tool_versions_returns_stable_data(self):
        """get_tool_versions should return stable version info."""
        profile = build_base_tool_profile()
        versions = profile.get_tool_versions()
        assert "read_file" in versions
        assert versions["read_file"]["canonical_name"] == "read_file"
        assert versions["read_file"]["version"] == "default"
