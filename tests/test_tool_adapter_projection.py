"""Tests for native-family canonical-to-exposed projection."""

from __future__ import annotations

import pytest

from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.tools.families import (
    build_claude_canonical_registry,
    build_codex_canonical_registry,
)
from pycodeagent.tools.spec import ToolAdapter, ToolArgumentError, validate_json_schema


class TestToolAdapterToExposedArgs:
    def test_identity_adapter_passes_through(self):
        adapter = ToolAdapter()
        result = adapter.to_exposed_args({"path": "foo.py", "line": 10})
        assert result == {"path": "foo.py", "line": 10}

    def test_nested_reverse_projection(self):
        adapter = ToolAdapter(
            exposed_to_canonical={
                "target": "path",
                "line_range.begin": "start_line",
                "line_range.end": "end_line",
            }
        )
        result = adapter.to_exposed_args(
            {
                "path": "src/main.py",
                "start_line": 10,
                "end_line": 30,
            }
        )
        assert result == {
            "target": "src/main.py",
            "line_range": {"begin": 10, "end": 30},
        }

    def test_missing_reverse_mapping_raises(self):
        adapter = ToolAdapter(exposed_to_canonical={"target": "path"})
        with pytest.raises(ToolArgumentError, match="missing reverse mappings"):
            adapter.to_exposed_args({"path": "ok.py", "start_line": 1})


def test_claude_profile_roundtrip_under_schema_mutation():
    registry = build_claude_canonical_registry()
    profile = ToolProfileSampler(seed=0, family="claude").sample("schema_only")
    canonical_args = {"file_path": "/workspace/src/main.py", "offset": 1, "limit": 20}
    canonical_tool = registry.get("Read")

    projected = profile.project_canonical_call(
        "Read",
        canonical_args,
        call_id="call_1",
        canonical_tool=canonical_tool,
    )

    validate_json_schema(
        projected.arguments,
        next(tool for tool in profile.tools if tool.canonical_name == "Read").input_schema,
        schema_name="claude_exposed",
    )
    _, roundtrip_args = profile.map_call_arguments(
        projected.name,
        projected.arguments,
        canonical_tool=canonical_tool,
    )
    assert roundtrip_args == canonical_args


def test_codex_freeform_apply_patch_projection_roundtrip():
    registry = build_codex_canonical_registry()
    profile = ToolProfileSampler(seed=0, family="codex").sample("base")
    canonical_tool = registry.get("apply_patch")
    patch = (
        "*** Begin Patch\n"
        "*** Update File: src/demo.py\n"
        "@@\n"
        "-print('old')\n"
        "+print('new')\n"
        "*** End Patch\n"
    )

    projected = profile.project_canonical_payload(
        "apply_patch",
        canonical_input_text=patch,
        call_id="call_1",
        canonical_tool=canonical_tool,
    )

    assert projected.input_text == patch
    _, roundtrip_payload = profile.map_call_payload(
        projected.name,
        input_text=projected.input_text,
        canonical_tool=canonical_tool,
    )
    assert roundtrip_payload == patch


def test_project_canonical_call_unknown_tool_raises():
    profile = ToolProfileSampler(seed=0, family="claude").sample("base")

    with pytest.raises(ToolArgumentError, match="Unknown canonical tool"):
        profile.project_canonical_call("not_a_tool", {"path": "x"})
