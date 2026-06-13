"""Tests for canonical-to-exposed projection through ToolAdapter and ToolProfile."""

from __future__ import annotations

import pytest

from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.tools.bootstrap import build_base_tool_profile, build_builtin_registry
from pycodeagent.tools.spec import ToolAdapter, ToolArgumentError, validate_json_schema


def _canonical_examples() -> dict[str, dict]:
    return {
        "list_files": {"path": ".", "recursive": True},
        "read_file": {
            "path": "src/calculator.py",
            "start_line": 1,
            "end_line": 80,
        },
        "search_code": {
            "query": "def add",
            "path": "src",
            "glob_pattern": "*.py",
        },
        "apply_patch": {
            "diff": "--- a/src/calculator.py\n+++ b/src/calculator.py\n@@ -1 +1 @@\n-old\n+new\n",
        },
        "run_command": {
            "command": "git status",
            "timeout": 5,
            "cwd": ".",
        },
        "finish": {
            "answer": "Updated calculator.py and tests pass.",
        },
    }


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

    def test_ambiguous_reverse_mapping_raises(self):
        adapter = ToolAdapter(
            exposed_to_canonical={
                "target": "path",
                "file": "path",
            }
        )
        with pytest.raises(ToolArgumentError, match="ambiguous reverse mappings"):
            adapter.to_exposed_args({"path": "ok.py"})

    def test_validates_exposed_schema_after_projection(self):
        adapter = ToolAdapter(exposed_to_canonical={"target": "path"})
        exposed_schema = {
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
        }
        result = adapter.to_exposed_args(
            {"path": "ok.py"},
            exposed_schema=exposed_schema,
        )
        assert result == {"target": "ok.py"}


class TestToolProfileProjectionRoundtrip:
    @pytest.fixture
    def registry(self):
        return build_builtin_registry()

    @pytest.mark.parametrize(
        ("profile_factory", "label"),
        [
            (lambda: build_base_tool_profile(), "base"),
            (lambda: ToolProfileSampler(seed=0).sample("schema_only"), "schema_only"),
            (
                lambda: ToolProfileSampler(seed=0).sample("name_description_schema"),
                "name_description_schema",
            ),
        ],
    )
    def test_builtin_tools_roundtrip_under_profile(self, registry, profile_factory, label):
        profile = profile_factory()
        examples = _canonical_examples()

        for tool in profile.tools:
            canonical_tool = registry.get(tool.canonical_name)
            canonical_args = examples[tool.canonical_name]

            projected = profile.project_canonical_call(
                tool.canonical_name,
                canonical_args,
                call_id="call_1",
                canonical_tool=canonical_tool,
            )

            assert projected.call_id == "call_1"
            assert projected.name == tool.exposed_name
            validate_json_schema(
                projected.arguments,
                tool.input_schema,
                schema_name=f"{label}_exposed",
            )

            _, roundtrip_args = profile.map_call_arguments(
                projected.name,
                projected.arguments,
                canonical_tool=canonical_tool,
            )
            assert roundtrip_args == canonical_args

    def test_project_canonical_call_unknown_tool_raises(self):
        profile = build_base_tool_profile()
        with pytest.raises(ToolArgumentError, match="Unknown canonical tool"):
            profile.project_canonical_call("not_a_tool", {"path": "x"})
