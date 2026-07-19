"""Tests for native-family profile sampling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.mutations.profile_sampler import (
    ToolProfileSampler,
    build_sampled_tool_profile,
)
from pycodeagent.mutations.profile_loader import (
    MUTATION_CONFIG_SCHEMA_VERSION,
    load_mutation_config,
)
from pycodeagent.tools.contracts import ToolContractKind
from pycodeagent.tools.profile_factory import (
    build_native_claude_profile,
    build_native_codex_profile,
)


_NATIVE_MUTATION_CONFIG = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "tools"
    / "native_family_mutation_v1.yaml"
)


def test_sampler_requires_family_or_explicit_base_profile():
    with pytest.raises(ValueError, match="requires either base_profile"):
        ToolProfileSampler(seed=0).sample("base")


def test_claude_sampler_is_deterministic_for_same_seed():
    p1 = ToolProfileSampler(seed=42, family="claude").sample("schema_flat_to_nested")
    p2 = ToolProfileSampler(seed=42, family="claude").sample("schema_flat_to_nested")

    assert p1.model_dump(mode="json") == p2.model_dump(mode="json")


def test_codex_sampler_is_deterministic_for_same_seed():
    p1 = ToolProfileSampler(seed=42, family="codex").sample("name_only")
    p2 = ToolProfileSampler(seed=42, family="codex").sample("name_only")

    assert p1.model_dump(mode="json") == p2.model_dump(mode="json")


def test_native_base_profiles_preserve_family_metadata():
    claude = build_native_claude_profile()
    codex = build_native_codex_profile()

    assert claude.metadata["family"] == "claude"
    assert codex.metadata["family"] == "codex"
    assert claude.metadata["reorder_anchor_policy"] == "preserve_source_order"
    assert codex.metadata["reorder_anchor_policy"] == "preserve_source_order"


def test_build_sampled_tool_profile_requires_family_when_base_profile_missing():
    with pytest.raises(ValueError, match="requires either base_profile"):
        build_sampled_tool_profile(mode="base", seed=0)


def test_build_sampled_tool_profile_from_claude_family():
    profile = build_sampled_tool_profile(
        mode="name_description_schema",
        seed=0,
        family="claude",
    )

    assert profile.metadata["family"] == "claude"
    assert profile.metadata["mutation_config_version"] == 1
    assert profile.metadata["mutation_source_family"] == "claude"
    assert profile.metadata["reorder_anchor_policy"] == "preserve_source_order"


def test_build_sampled_tool_profile_from_codex_family_preserves_freeform_apply_patch():
    profile = build_sampled_tool_profile(
        mode="base",
        seed=0,
        family="codex",
    )
    apply_patch = next(tool for tool in profile.tools if tool.canonical_name == "apply_patch")

    assert apply_patch.contract_kind == ToolContractKind.FREEFORM
    assert apply_patch.input_format is not None
    assert apply_patch.input_format["syntax"] == "lark"


def test_sampler_uses_native_family_mutation_config_by_default():
    profile = ToolProfileSampler(seed=0, family="claude").sample("argument_rename")

    assert profile.profile_id.startswith("native_claude_mutation_claude_argument_rename_")


def test_explicit_base_profile_can_drive_sampling_without_family():
    base_profile = build_native_codex_profile(profile_id="codex_base")
    profile = ToolProfileSampler(seed=7, base_profile=base_profile).sample("name_only")

    assert profile.metadata["family"] == "codex"
    assert profile.metadata["source_profile_id"] == "codex_base"


def test_sample_all_modes_returns_supported_native_profiles():
    profiles = ToolProfileSampler(seed=42, family="claude").sample_all_modes()

    assert set(profiles) == {
        "base",
        "name_only",
        "description_only",
        "argument_rename",
        "schema_flat_to_nested",
        "tool_reorder",
        "schema_only",
        "name_description_schema",
    }
    assert all(profile.metadata["family"] == "claude" for profile in profiles.values())


def test_custom_native_config_path_is_supported():
    profile = ToolProfileSampler(
        seed=0,
        family="claude",
        mutation_config_path=_NATIVE_MUTATION_CONFIG,
    ).sample("argument_rename")

    assert profile.metadata["family"] == "claude"


def test_mutation_config_loader_is_versioned_and_accepts_yaml_and_json(
    tmp_path: Path,
):
    yaml_config = load_mutation_config(_NATIVE_MUTATION_CONFIG)
    assert yaml_config["mutation_config_version"] == MUTATION_CONFIG_SCHEMA_VERSION

    json_path = tmp_path / "mutation.json"
    json_path.write_text(json.dumps(yaml_config), encoding="utf-8")
    assert load_mutation_config(json_path) == yaml_config


@pytest.mark.parametrize("version", [None, 0, 2, "1"])
def test_mutation_config_loader_rejects_missing_or_unknown_version(
    tmp_path: Path,
    version: object,
):
    payload = {
        "profile_id_prefix": "test_mutation",
        "tool_variants": {},
    }
    if version is not None:
        payload["mutation_config_version"] = version
    path = tmp_path / "mutation.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="mutation_config_version=1"):
        load_mutation_config(path)


def test_mutation_config_loader_uses_one_mapping_error_for_yaml_and_json(
    tmp_path: Path,
):
    for name, content in (("bad.yaml", "- item\n"), ("bad.json", "[1, 2]")):
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match="Mutation config must be a mapping"):
            load_mutation_config(path)


def test_mutation_config_loader_has_one_missing_file_error(tmp_path: Path):
    missing = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError, match=r"Mutation config file not found:"):
        load_mutation_config(missing)
