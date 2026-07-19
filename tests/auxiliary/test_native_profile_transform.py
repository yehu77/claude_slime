"""Tests for native-aware surface-level ToolProfile transformations."""

from __future__ import annotations

from pathlib import Path

import pytest

from pycodeagent.mutations import load_tool_profile_from_dict
from pycodeagent.auxiliary.claude_api.tool_catalog_snapshot import (
    build_catalog_from_claude_request_tools,
)
from pycodeagent.auxiliary.claude_api.trace_loader import read_claude_api_session
from pycodeagent.tools.contracts import ToolContractKind
from pycodeagent.tools.profile_factory import (
    build_native_claude_profile,
    build_native_codex_profile,
)
from pycodeagent.tools.spec import ToolAdapter, ToolProfile, ToolView
from pycodeagent.traces import (
    build_native_transformed_profile,
    catalog_to_base_tool_profile,
    generate_description_candidates,
    generate_name_candidates,
)


_REAL_SESSION_PATH = Path(
    "runs/claude_gateway_traces/84f8f6fa-4cb3-480d-8e8a-a80fc035bdcc.jsonl"
)


def _real_session_path() -> Path:
    if not _REAL_SESSION_PATH.exists():
        pytest.skip(f"Missing real Claude session fixture: {_REAL_SESSION_PATH}")
    return _REAL_SESSION_PATH


def _make_base_profile() -> ToolProfile:
    return ToolProfile(
        profile_id="native::catalog_1",
        tools=[
            ToolView(
                canonical_name="Read",
                exposed_name="Read",
                description="Read a file from disk.",
                input_schema={
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
                metadata={
                    "native_name": "Read",
                    "source_catalog_id": "catalog_1",
                    "canonical_mapping_status": "native_identity_not_canonicalized",
                },
            ),
            ToolView(
                canonical_name="Edit",
                exposed_name="Edit",
                description="Edit a file with exact replacements.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "old_string": {"type": "string"},
                        "new_string": {"type": "string"},
                    },
                    "required": ["file_path", "old_string", "new_string"],
                },
                metadata={
                    "native_name": "Edit",
                    "source_catalog_id": "catalog_1",
                    "canonical_mapping_status": "native_identity_not_canonicalized",
                },
            ),
        ],
        adapters={
            "Read": ToolAdapter(),
            "Edit": ToolAdapter(),
        },
        metadata={
            "source_catalog_id": "catalog_1",
            "source_agent_name": "claude_code",
            "source_agent_version": "api_trace_v1",
            "native_schema_snapshot": True,
            "tool_order_preserved": True,
            "canonical_mapping_status": "native_identity_not_canonicalized",
        },
    )


def _profile_to_loader_dict(profile: ToolProfile) -> dict:
    return {
        "profile_id": profile.profile_id,
        "tools": [
            {
                "canonical": tool.canonical_name,
                "exposed_name": tool.exposed_name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "kind": (
                    tool.contract_kind.value
                    if tool.contract_kind != ToolContractKind.FUNCTION
                    else None
                ),
                "input_format": tool.input_format,
                "version": tool.version,
                "adapter": {
                    "exposed_to_canonical": profile.adapters[tool.exposed_name].exposed_to_canonical,
                    "defaults": profile.adapters[tool.exposed_name].defaults,
                },
            }
            for tool in profile.tools
        ],
    }


class TestNativeProfileTransform:
    def test_name_candidates_are_deterministic_and_surface_preserving(self) -> None:
        tool = _make_base_profile().tools[0]

        candidates_1 = generate_name_candidates(tool)
        candidates_2 = generate_name_candidates(tool)

        assert candidates_1 == candidates_2
        assert candidates_1[0] == "Read"
        assert "read" in candidates_1
        assert "read_tool" in candidates_1
        assert "use_read" in candidates_1

    def test_description_candidates_are_deterministic(self) -> None:
        tool = _make_base_profile().tools[0]

        candidates_1 = generate_description_candidates(tool)
        candidates_2 = generate_description_candidates(tool)

        assert candidates_1 == candidates_2
        assert candidates_1[0] == "Read a file from disk."
        assert any(candidate.startswith("Use this tool to ") for candidate in candidates_1[1:])

    def test_base_mode_preserves_surface_and_schema(self) -> None:
        base_profile = _make_base_profile()

        transformed = build_native_transformed_profile(base_profile, mode="base", seed=7)

        assert [tool.exposed_name for tool in transformed.tools] == ["Read", "Edit"]
        assert [tool.description for tool in transformed.tools] == [
            "Read a file from disk.",
            "Edit a file with exact replacements.",
        ]
        assert transformed.tools[0].input_schema == base_profile.tools[0].input_schema
        assert transformed.adapters["Read"].exposed_to_canonical == {}
        assert transformed.metadata["transformation_mode"] == "base"
        assert transformed.metadata["tool_order_preserved"] is True

    def test_name_only_changes_only_names(self) -> None:
        base_profile = _make_base_profile()

        transformed = build_native_transformed_profile(base_profile, mode="name_only", seed=7)

        assert [tool.exposed_name for tool in transformed.tools] != ["Read", "Edit"]
        assert [tool.description for tool in transformed.tools] == [
            "Read a file from disk.",
            "Edit a file with exact replacements.",
        ]
        assert transformed.tools[0].input_schema == base_profile.tools[0].input_schema
        assert transformed.adapters[transformed.tools[0].exposed_name].exposed_to_canonical == {}
        assert transformed.tools[0].metadata["transformation_mode"] == "name_only"

    def test_description_only_changes_only_descriptions(self) -> None:
        base_profile = _make_base_profile()

        transformed = build_native_transformed_profile(
            base_profile,
            mode="description_only",
            seed=7,
        )

        assert [tool.exposed_name for tool in transformed.tools] == ["Read", "Edit"]
        assert [tool.description for tool in transformed.tools] != [
            "Read a file from disk.",
            "Edit a file with exact replacements.",
        ]
        assert transformed.tools[0].input_schema == base_profile.tools[0].input_schema
        assert transformed.tools[0].metadata["transformation_mode"] == "description_only"

    def test_name_description_changes_both_surface_fields(self) -> None:
        base_profile = _make_base_profile()

        transformed = build_native_transformed_profile(
            base_profile,
            mode="name_description",
            seed=7,
        )

        assert [tool.exposed_name for tool in transformed.tools] != ["Read", "Edit"]
        assert [tool.description for tool in transformed.tools] != [
            "Read a file from disk.",
            "Edit a file with exact replacements.",
        ]
        assert transformed.tools[0].input_schema == base_profile.tools[0].input_schema
        assert transformed.metadata["transformation_mode"] == "name_description"

    def test_name_transformation_resolves_collisions_deterministically(self) -> None:
        profile = ToolProfile(
            profile_id="native::collision",
            tools=[
                ToolView(
                    canonical_name="Read",
                    exposed_name="Read",
                    description="Read a file.",
                    input_schema={"type": "object", "properties": {}},
                    metadata={
                        "native_name": "Read",
                        "canonical_mapping_status": "native_identity_not_canonicalized",
                    },
                ),
                ToolView(
                    canonical_name="read",
                    exposed_name="read",
                    description="Another read tool.",
                    input_schema={"type": "object", "properties": {}},
                    metadata={
                        "native_name": "read",
                        "canonical_mapping_status": "native_identity_not_canonicalized",
                    },
                ),
            ],
            adapters={"Read": ToolAdapter(), "read": ToolAdapter()},
            metadata={
                "source_catalog_id": "collision_catalog",
                "source_agent_name": "claude_code",
                "source_agent_version": "api_trace_v1",
            },
        )

        transformed = build_native_transformed_profile(profile, mode="name_only", seed=1)
        names = [tool.exposed_name for tool in transformed.tools]
        assert len(names) == len(set(names))

    def test_real_claude_fixture_can_transform_and_preserve_order(self) -> None:
        session = read_claude_api_session(_real_session_path())
        request = session.message_requests[0]
        catalog = build_catalog_from_claude_request_tools(
            request,
            source_trace_path=_real_session_path(),
        )
        assert catalog is not None
        base_profile = catalog_to_base_tool_profile(catalog)

        transformed = build_native_transformed_profile(
            base_profile,
            mode="name_description",
            seed=13,
        )

        assert len(transformed.tools) == len(base_profile.tools)
        assert [tool.metadata["native_name"] for tool in transformed.tools] == [
            tool.metadata["native_name"] for tool in base_profile.tools
        ]
        assert transformed.metadata["source_catalog_id"] == catalog.catalog_id
        assert transformed.metadata["tool_order_preserved"] is True
        assert all(
            tool.metadata["canonical_mapping_status"] == "native_identity_not_canonicalized"
            for tool in transformed.tools
        )

    def test_transformed_profile_is_accepted_by_profile_loader_and_specs(self) -> None:
        transformed = build_native_transformed_profile(
            _make_base_profile(),
            mode="name_description",
            seed=5,
        )

        loaded = load_tool_profile_from_dict(_profile_to_loader_dict(transformed))
        specs = transformed.get_exposed_specs()

        assert loaded.profile_id == transformed.profile_id
        assert len(specs) == 2
        assert specs[0]["name"] == transformed.tools[0].exposed_name
        assert specs[0]["input_schema"] == transformed.tools[0].input_schema

    def test_step_d_native_claude_profile_can_flow_through_transform_path(self) -> None:
        base_profile = build_native_claude_profile()

        transformed = build_native_transformed_profile(
            base_profile,
            mode="description_only",
            seed=3,
        )

        assert transformed.metadata["family"] == "claude"
        assert transformed.metadata["native_profile_kind"] == "native_claude"
        assert transformed.metadata["mutation_source_family"] == "claude"
        assert transformed.metadata["canonical_mapping_status"] == "native_identity_not_canonicalized"
        assert [tool.canonical_name for tool in transformed.tools] == [
            "Bash",
            "Read",
            "Edit",
            "Write",
            "Grep",
            "Glob",
        ]
        assert all(tool.contract_kind == ToolContractKind.FUNCTION for tool in transformed.tools)

    @pytest.mark.parametrize(
        ("mode", "seed"),
        [
            ("base", 0),
            ("name_only", 11),
            ("description_only", 13),
            ("name_description", 17),
        ],
    )
    def test_step_d_native_codex_profile_preserves_freeform_apply_patch_through_transform(
        self,
        mode: str,
        seed: int,
    ) -> None:
        base_profile = build_native_codex_profile()

        transformed = build_native_transformed_profile(
            base_profile,
            mode=mode,
            seed=seed,
        )
        apply_patch_tool = next(
            tool for tool in transformed.tools if tool.canonical_name == "apply_patch"
        )
        specs = {spec["name"]: spec for spec in transformed.get_exposed_specs()}
        apply_patch_spec = specs[apply_patch_tool.exposed_name]
        loaded = load_tool_profile_from_dict(_profile_to_loader_dict(transformed))
        loaded_apply_patch = next(
            tool for tool in loaded.tools if tool.canonical_name == "apply_patch"
        )

        assert transformed.metadata["family"] == "codex"
        assert transformed.metadata["native_profile_kind"] == "native_codex"
        assert transformed.metadata["mutation_source_family"] == "codex"
        assert apply_patch_tool.contract_kind == ToolContractKind.FREEFORM
        assert apply_patch_tool.input_format == base_profile.tools[-1].input_format
        assert apply_patch_tool.metadata["family"] == "codex"
        assert apply_patch_tool.metadata["native_profile_kind"] == "native_codex"
        assert apply_patch_tool.metadata["mutation_source_family"] == "codex"
        assert apply_patch_tool.metadata["canonical_mapping_status"] == "native_identity_not_canonicalized"
        assert apply_patch_spec["kind"] == "freeform"
        assert apply_patch_spec["input_format"]["syntax"] == "lark"
        assert "input_schema" not in apply_patch_spec
        assert loaded_apply_patch.contract_kind == ToolContractKind.FREEFORM
        assert loaded_apply_patch.input_format == apply_patch_tool.input_format
