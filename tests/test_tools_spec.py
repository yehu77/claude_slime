"""Tests for tool spec: ToolAdapter and validate_json_schema.

Locks the contract for:
- Identity mapping
- Field renaming
- Nested path mapping
- Defaults injection
- Schema validation
"""

from __future__ import annotations

import pytest

from pycodeagent.tools.spec import (
    ToolAdapter,
    ToolArgumentError,
    validate_json_schema,
)


class TestToolAdapterIdentity:
    """Tests for identity mapping (no exposed_to_canonical)."""

    def test_empty_adapter_passes_through(self):
        """Empty adapter should pass arguments unchanged."""
        adapter = ToolAdapter()
        result = adapter.map_arguments({"path": "foo.py", "line": 10})
        assert result == {"path": "foo.py", "line": 10}

    def test_empty_adapter_with_nested_args(self):
        """Empty adapter should preserve nested structure."""
        adapter = ToolAdapter()
        result = adapter.map_arguments({
            "path": "test.py",
            "range": {"start": 1, "end": 50},
        })
        assert result["path"] == "test.py"
        assert result["range"]["start"] == 1
        assert result["range"]["end"] == 50


class TestToolAdapterFieldMapping:
    """Tests for exposed_to_canonical field mapping."""

    def test_simple_field_rename(self):
        """Simple field renaming."""
        adapter = ToolAdapter(exposed_to_canonical={"target": "path"})
        result = adapter.map_arguments({"target": "foo.py"})
        assert result == {"path": "foo.py"}

    def test_multiple_field_renames(self):
        """Multiple field renames."""
        adapter = ToolAdapter(exposed_to_canonical={
            "target": "path",
            "begin": "start_line",
            "end": "end_line",
        })
        result = adapter.map_arguments({
            "target": "test.py",
            "begin": 1,
            "end": 50,
        })
        assert result == {
            "path": "test.py",
            "start_line": 1,
            "end_line": 50,
        }


class TestToolAdapterNestedMapping:
    """Tests for nested path mapping."""

    def test_nested_to_flat(self):
        """Map nested exposed args to flat canonical args."""
        adapter = ToolAdapter(exposed_to_canonical={
            "target": "path",
            "line_range.begin": "start_line",
            "line_range.end": "end_line",
        })
        result = adapter.map_arguments({
            "target": "src/main.py",
            "line_range": {"begin": 10, "end": 30},
        })
        assert result == {
            "path": "src/main.py",
            "start_line": 10,
            "end_line": 30,
        }

    def test_flat_to_nested(self):
        """Map flat exposed args to nested canonical args."""
        adapter = ToolAdapter(exposed_to_canonical={
            "file": "location.path",
            "line": "location.line",
        })
        result = adapter.map_arguments({"file": "test.py", "line": 42})
        assert result == {"location": {"path": "test.py", "line": 42}}


class TestToolAdapterDefaults:
    """Tests for defaults injection."""

    def test_defaults_added_for_missing(self):
        """Defaults should be added when field is missing."""
        adapter = ToolAdapter(defaults={"start_line": 1, "end_line": 100})
        result = adapter.map_arguments({"path": "foo.py"})
        assert result["path"] == "foo.py"
        assert result["start_line"] == 1
        assert result["end_line"] == 100

    def test_defaults_not_override_explicit(self):
        """Defaults should NOT override explicit values."""
        adapter = ToolAdapter(defaults={"start_line": 1})
        result = adapter.map_arguments({"path": "foo.py", "start_line": 50})
        assert result["start_line"] == 50

    def test_defaults_with_mapping(self):
        """Defaults work with field mapping."""
        adapter = ToolAdapter(
            exposed_to_canonical={"target": "path"},
            defaults={"start_line": 1},
        )
        result = adapter.map_arguments({"target": "test.py"})
        assert result == {"path": "test.py", "start_line": 1}


class TestToolAdapterMissingFields:
    """Tests for handling missing/unmapped fields."""

    def test_unmapped_field_raises(self):
        """Unmapped field should raise ToolArgumentError."""
        adapter = ToolAdapter(exposed_to_canonical={"path": "path"})
        with pytest.raises(ToolArgumentError, match="missing mappings"):
            adapter.map_arguments({"path": "ok.py", "extra": "unmapped"})

    def test_optional_missing_in_input_ok(self):
        """Missing optional field in input is OK if not required."""
        adapter = ToolAdapter(exposed_to_canonical={"path": "path"})
        result = adapter.map_arguments({"path": "foo.py"})
        assert result == {"path": "foo.py"}


class TestValidateJsonSchema:
    """Tests for validate_json_schema."""

    def test_valid_object_schema_passes(self):
        """Valid object should pass schema validation."""
        schema = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
        validate_json_schema({"path": "test.py"}, schema, schema_name="test")

    def test_missing_required_field_raises(self):
        """Missing required field should raise."""
        schema = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
        with pytest.raises(ToolArgumentError, match="missing required field"):
            validate_json_schema({}, schema, schema_name="test")

    def test_wrong_type_raises(self):
        """Wrong type should raise."""
        schema = {"type": "string"}
        with pytest.raises(ToolArgumentError, match="expected string"):
            validate_json_schema(123, schema, schema_name="test")

    def test_integer_type_passes(self):
        """Integer validation."""
        schema = {"type": "integer"}
        validate_json_schema(42, schema, schema_name="test")

    def test_integer_type_rejects_float(self):
        """Integer should reject float."""
        schema = {"type": "integer"}
        with pytest.raises(ToolArgumentError, match="expected integer"):
            validate_json_schema(3.14, schema, schema_name="test")

    def test_boolean_type_passes(self):
        """Boolean validation."""
        schema = {"type": "boolean"}
        validate_json_schema(True, schema, schema_name="test")
        validate_json_schema(False, schema, schema_name="test")

    def test_array_type_passes(self):
        """Array validation."""
        schema = {
            "type": "array",
            "items": {"type": "string"},
        }
        validate_json_schema(["a", "b"], schema, schema_name="test")

    def test_array_type_rejects_non_list(self):
        """Array should reject non-list."""
        schema = {"type": "array"}
        with pytest.raises(ToolArgumentError, match="expected array"):
            validate_json_schema("not a list", schema, schema_name="test")

    def test_enum_passes(self):
        """Enum validation passes for valid value."""
        schema = {"enum": ["read", "write", "execute"]}
        validate_json_schema("read", schema, schema_name="test")

    def test_enum_rejects_invalid(self):
        """Enum rejects invalid value (requires type field to trigger validation)."""
        schema = {"type": "string", "enum": ["read", "write"]}
        with pytest.raises(ToolArgumentError, match="expected one of"):
            validate_json_schema("delete", schema, schema_name="test")

    def test_enum_without_type_not_validated(self):
        """Enum without type field does not trigger validation (current behavior)."""
        schema = {"enum": ["read", "write"]}
        # Current implementation skips validation when schema_type is None
        validate_json_schema("delete", schema, schema_name="test")

    def test_nested_object_schema(self):
        """Nested object validation."""
        schema = {
            "type": "object",
            "properties": {
                "range": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "integer"},
                        "end": {"type": "integer"},
                    },
                    "required": ["start", "end"],
                },
            },
            "required": ["range"],
        }
        validate_json_schema({"range": {"start": 1, "end": 10}}, schema, schema_name="test")

    def test_additional_properties_false_rejects_extra(self):
        """additionalProperties: false rejects extra fields."""
        schema = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "additionalProperties": False,
        }
        with pytest.raises(ToolArgumentError, match="unexpected field"):
            validate_json_schema({"path": "ok", "extra": "bad"}, schema, schema_name="test")

    def test_type_union_passes_any(self):
        """Union type [string, null] should accept either."""
        schema = {"type": ["string", "null"]}
        validate_json_schema("hello", schema, schema_name="test")
        validate_json_schema(None, schema, schema_name="test")

    def test_type_union_rejects_other(self):
        """Union type should reject non-matching."""
        schema = {"type": ["string", "null"]}
        with pytest.raises(ToolArgumentError):
            validate_json_schema(123, schema, schema_name="test")


class TestToolAdapterSchemaValidation:
    """Tests for adapter with schema validation."""

    def test_adapter_validates_exposed_schema(self):
        """Adapter should validate against exposed_schema."""
        adapter = ToolAdapter()
        exposed_schema = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
        # Valid
        adapter.map_arguments({"path": "test.py"}, exposed_schema=exposed_schema)
        # Invalid - missing required
        with pytest.raises(ToolArgumentError, match="missing required field"):
            adapter.map_arguments({}, exposed_schema=exposed_schema)

    def test_adapter_validates_canonical_schema(self):
        """Adapter should validate result against canonical_schema."""
        adapter = ToolAdapter()
        canonical_schema = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
        # Result passes canonical schema
        adapter.map_arguments({"path": "ok.py"}, canonical_schema=canonical_schema)
        # Result fails canonical schema
        with pytest.raises(ToolArgumentError, match="missing required field"):
            adapter.map_arguments({}, canonical_schema=canonical_schema)
