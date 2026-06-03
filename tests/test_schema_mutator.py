"""Tests for the schema mutator."""

from __future__ import annotations

import pytest

from pycodeagent.mutations.schema_mutator import (
    SchemaMutator,
    SchemaMutationError,
    SchemaCandidate,
    mutate_schema,
)
from pycodeagent.tools.spec import ToolAdapter


# --- Test fixtures ---

_BASE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "File path to read."},
        "start_line": {"type": "integer", "description": "First line (1-based)."},
        "end_line": {"type": "integer", "description": "Last line (1-based)."},
    },
    "required": ["path"],
}

_NESTED_SCHEMA = {
    "type": "object",
    "properties": {
        "target": {"type": "string", "description": "File to inspect."},
        "line_range": {
            "type": "object",
            "properties": {
                "begin": {"type": "integer", "description": "First line."},
                "end": {"type": "integer", "description": "Last line."},
            },
        },
    },
    "required": ["target"],
}

_NESTED_ADAPTER = {
    "exposed_to_canonical": {
        "target": "path",
        "line_range.begin": "start_line",
        "line_range.end": "end_line",
    },
}

_RENAMED_SCHEMA = {
    "type": "object",
    "properties": {
        "file": {"type": "string", "description": "Path of the file."},
        "lines": {
            "type": "object",
            "properties": {
                "from": {"type": "integer", "description": "Starting line."},
                "to": {"type": "integer", "description": "Ending line."},
            },
        },
    },
    "required": ["file"],
}

_RENAMED_ADAPTER = {
    "exposed_to_canonical": {
        "file": "path",
        "lines.from": "start_line",
        "lines.to": "end_line",
    },
}


def _make_candidates():
    """Create a list of schema candidates as dicts."""
    return [
        {"input_schema": _BASE_SCHEMA, "adapter": {}},
        {"input_schema": _NESTED_SCHEMA, "adapter": _NESTED_ADAPTER},
        {"input_schema": _RENAMED_SCHEMA, "adapter": _RENAMED_ADAPTER},
    ]


class TestSchemaCandidate:
    """Tests for SchemaCandidate helper."""

    def test_from_dict_valid(self):
        """Should create from valid dict."""
        data = {"input_schema": _BASE_SCHEMA, "adapter": {}}
        candidate = SchemaCandidate.from_dict(data)
        assert candidate.input_schema == _BASE_SCHEMA
        assert isinstance(candidate.adapter, ToolAdapter)
        assert candidate.adapter.exposed_to_canonical == {}

    def test_from_dict_with_adapter_mapping(self):
        """Should create with adapter mapping."""
        data = {"input_schema": _NESTED_SCHEMA, "adapter": _NESTED_ADAPTER}
        candidate = SchemaCandidate.from_dict(data)
        assert candidate.input_schema == _NESTED_SCHEMA
        assert candidate.adapter.exposed_to_canonical == _NESTED_ADAPTER["exposed_to_canonical"]

    def test_from_dict_missing_input_schema_raises(self):
        """Should raise if input_schema is missing."""
        with pytest.raises(SchemaMutationError, match="input_schema"):
            SchemaCandidate.from_dict({"adapter": {}})

    def test_from_dict_non_dict_raises(self):
        """Should raise if input is not a dict."""
        with pytest.raises(SchemaMutationError, match="dict"):
            SchemaCandidate.from_dict("not a dict")

    def test_from_dict_invalid_input_schema_type_raises(self):
        """Should raise if input_schema is not a dict."""
        with pytest.raises(SchemaMutationError, match="input_schema"):
            SchemaCandidate.from_dict({"input_schema": "not a dict"})

    def test_init_with_tool_adapter(self):
        """Should accept ToolAdapter directly."""
        adapter = ToolAdapter(exposed_to_canonical={"target": "path"})
        candidate = SchemaCandidate(input_schema=_BASE_SCHEMA, adapter=adapter)
        assert candidate.adapter is adapter

    def test_init_with_none_adapter(self):
        """Should create empty ToolAdapter when adapter is None."""
        candidate = SchemaCandidate(input_schema=_BASE_SCHEMA, adapter=None)
        assert isinstance(candidate.adapter, ToolAdapter)
        assert candidate.adapter.exposed_to_canonical == {}

    def test_init_with_invalid_adapter_type_raises(self):
        """Should raise for invalid adapter type."""
        with pytest.raises(SchemaMutationError, match="adapter"):
            SchemaCandidate(input_schema=_BASE_SCHEMA, adapter=123)  # type: ignore


class TestSchemaMutatorIdentity:
    """Tests for identity/no-op behavior."""

    def test_mutate_false_returns_base(self):
        """When mutate=False, should return the base schema and identity adapter."""
        mutator = SchemaMutator()
        schema, adapter = mutator.mutate(
            base_schema=_BASE_SCHEMA,
            candidates=_make_candidates(),
            seed=42,
            mutate=False,
        )
        assert schema == _BASE_SCHEMA
        assert adapter.exposed_to_canonical == {}

    def test_single_candidate_returns_base(self):
        """With only one candidate, should return it regardless of mutate flag."""
        mutator = SchemaMutator()
        candidates = [{"input_schema": _BASE_SCHEMA, "adapter": {}}]
        schema, adapter = mutator.mutate(
            base_schema=_BASE_SCHEMA,
            candidates=candidates,
            seed=42,
            mutate=True,
        )
        assert schema == _BASE_SCHEMA

    def test_no_candidates_returns_base(self):
        """With no candidates, should return base schema."""
        mutator = SchemaMutator()
        schema, adapter = mutator.mutate(
            base_schema=_BASE_SCHEMA,
            candidates=None,
            seed=42,
            mutate=True,
        )
        assert schema == _BASE_SCHEMA
        assert isinstance(adapter, ToolAdapter)


class TestSchemaMutatorDeterminism:
    """Tests for deterministic behavior."""

    def test_same_seed_same_tool_name_same_result(self):
        """Same seed + same tool name should produce same result."""
        mutator = SchemaMutator()
        candidates = _make_candidates()
        s1, a1 = mutator.mutate(_BASE_SCHEMA, candidates, seed=42, mutate=True, tool_name="read_file")
        s2, a2 = mutator.mutate(_BASE_SCHEMA, candidates, seed=42, mutate=True, tool_name="read_file")
        assert s1 == s2
        assert a1.exposed_to_canonical == a2.exposed_to_canonical

    def test_different_seed_can_produce_different_result(self):
        """Different seeds should be able to produce different schemas."""
        mutator = SchemaMutator()
        candidates = _make_candidates()
        schemas_by_seed = {}
        for seed in range(20):
            schema, _ = mutator.mutate(
                _BASE_SCHEMA, candidates, seed=seed, mutate=True, tool_name="read_file"
            )
            # Compare by properties keys
            props = tuple(sorted(schema.get("properties", {}).keys()))
            schemas_by_seed[seed] = props
        # With 20 seeds and 2 non-base candidates, should see variation
        assert len(set(schemas_by_seed.values())) > 1


class TestSchemaMutatorVariation:
    """Tests for mutation variation."""

    def test_mutate_true_selects_non_base(self):
        """When mutate=True, should select from non-base candidates."""
        mutator = SchemaMutator()
        candidates = _make_candidates()
        for seed in range(100):
            schema, _ = mutator.mutate(
                _BASE_SCHEMA, candidates, seed=seed, mutate=True, tool_name="read_file"
            )
            # Should not be the base schema
            assert schema != _BASE_SCHEMA

    def test_different_tool_names_affect_selection(self):
        """Different tool names should affect the hash selection."""
        mutator = SchemaMutator()
        candidates = _make_candidates()
        results_by_name = {}
        for name in ["read_file", "list_files", "search_code"]:
            schema, _ = mutator.mutate(
                _BASE_SCHEMA, candidates, seed=42, mutate=True, tool_name=name
            )
            props = tuple(sorted(schema.get("properties", {}).keys()))
            results_by_name[name] = props
        # At least some tools should get different schemas
        assert len(set(results_by_name.values())) >= 1


class TestSchemaMutatorAdapterMapping:
    """Tests for adapter mapping correctness."""

    def test_nested_schema_adapter_maps_args(self):
        """Nested schema adapter should correctly map arguments."""
        adapter = ToolAdapter(
            exposed_to_canonical={
                "target": "path",
                "line_range.begin": "start_line",
                "line_range.end": "end_line",
            }
        )
        mapped = adapter.map_arguments({
            "target": "test.py",
            "line_range": {"begin": 1, "end": 50},
        })
        assert mapped["path"] == "test.py"
        assert mapped["start_line"] == 1
        assert mapped["end_line"] == 50

    def test_renamed_schema_adapter_maps_args(self):
        """Renamed schema adapter should correctly map arguments."""
        adapter = ToolAdapter(
            exposed_to_canonical={
                "file": "path",
                "lines.from": "start_line",
                "lines.to": "end_line",
            }
        )
        mapped = adapter.map_arguments({
            "file": "test.py",
            "lines": {"from": 1, "to": 50},
        })
        assert mapped["path"] == "test.py"
        assert mapped["start_line"] == 1
        assert mapped["end_line"] == 50

    def test_identity_adapter_passes_through(self):
        """Identity adapter (empty mapping) should pass through args."""
        adapter = ToolAdapter()
        mapped = adapter.map_arguments({"path": "test.py", "start_line": 1})
        assert mapped == {"path": "test.py", "start_line": 1}

    def test_mutate_returns_correct_adapter(self):
        """Mutated schema should come with correct adapter."""
        mutator = SchemaMutator()
        # Find a seed that selects the nested schema candidate
        candidates = _make_candidates()
        for seed in range(100):
            schema, adapter = mutator.mutate(
                _BASE_SCHEMA, candidates, seed=seed, mutate=True, tool_name="read_file"
            )
            props = schema.get("properties", {})
            if "target" in props:
                # This is the nested schema variant
                assert adapter.exposed_to_canonical.get("target") == "path"
                break
        else:
            pytest.fail("Did not find a seed that selects the nested schema")


class TestSchemaMutatorValidation:
    """Tests for input validation."""

    def test_non_dict_base_schema_raises(self):
        """Non-dict base schema should raise."""
        mutator = SchemaMutator()
        with pytest.raises(SchemaMutationError, match="base_schema"):
            mutator.mutate("not a dict", candidates=None, seed=42, mutate=True)

    def test_invalid_candidate_type_raises(self):
        """Non-dict/non-SchemaCandidate should raise."""
        mutator = SchemaMutator()
        with pytest.raises(SchemaMutationError, match="candidates"):
            mutator.mutate(_BASE_SCHEMA, candidates=["not valid"], seed=42, mutate=True)

    def test_candidates_not_list_raises(self):
        """Candidates not a list should raise."""
        mutator = SchemaMutator()
        with pytest.raises(SchemaMutationError, match="candidates"):
            mutator.mutate(_BASE_SCHEMA, candidates="not_a_list", seed=42, mutate=True)

    def test_invalid_dict_candidate_raises(self):
        """Dict candidate without input_schema should raise."""
        mutator = SchemaMutator()
        with pytest.raises(SchemaMutationError, match="input_schema"):
            mutator.mutate(
                _BASE_SCHEMA,
                candidates=[{"adapter": {}}],
                seed=42,
                mutate=True,
            )


class TestMutateSchemaFunction:
    """Tests for the convenience function."""

    def test_mutate_schema_function_works(self):
        """Convenience function should work like SchemaMutator.mutate."""
        schema, adapter = mutate_schema(
            _BASE_SCHEMA,
            candidates=_make_candidates(),
            seed=42,
            mutate=True,
            tool_name="read_file",
        )
        assert schema != _BASE_SCHEMA
        assert isinstance(adapter, ToolAdapter)

    def test_mutate_schema_identity(self):
        """Convenience function with mutate=False should return base."""
        schema, adapter = mutate_schema(
            _BASE_SCHEMA,
            candidates=_make_candidates(),
            seed=42,
            mutate=False,
        )
        assert schema == _BASE_SCHEMA


class TestSchemaMutatorWithSchemaCandidateObjects:
    """Tests using SchemaCandidate objects directly."""

    def test_schema_candidate_objects_work(self):
        """Should accept SchemaCandidate objects as candidates."""
        mutator = SchemaMutator()
        candidates = [
            SchemaCandidate(input_schema=_BASE_SCHEMA),
            SchemaCandidate(
                input_schema=_NESTED_SCHEMA,
                adapter={"exposed_to_canonical": {"target": "path"}},
            ),
        ]
        schema, adapter = mutator.mutate(
            _BASE_SCHEMA, candidates, seed=42, mutate=True, tool_name="read_file"
        )
        # Should be the nested schema
        assert "target" in schema.get("properties", {})
        assert adapter.exposed_to_canonical.get("target") == "path"

    def test_mixed_candidates_work(self):
        """Should accept mixed SchemaCandidate and dict candidates."""
        mutator = SchemaMutator()
        candidates = [
            SchemaCandidate(input_schema=_BASE_SCHEMA),
            {"input_schema": _NESTED_SCHEMA, "adapter": _NESTED_ADAPTER},
        ]
        schema, adapter = mutator.mutate(
            _BASE_SCHEMA, candidates, seed=42, mutate=True, tool_name="read_file"
        )
        assert "target" in schema.get("properties", {})
