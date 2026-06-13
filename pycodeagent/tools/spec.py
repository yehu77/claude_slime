"""Core tool system types.

Decouples canonical tool backends from the tool definitions exposed to the LLM,
enabling controlled tool schema mutation experiments.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field


class ToolArgumentError(ValueError):
    """Raised when exposed or canonical tool arguments fail validation."""


# --- Canonical backend ---


class CanonicalTool(BaseModel):
    """A real tool implementation with a stable canonical interface."""

    canonical_name: str
    description: str = ""
    canonical_schema: dict[str, Any]
    handler: Callable[..., Any]
    version: str = "default"

    model_config = ConfigDict(arbitrary_types_allowed=True)


# --- Exposed view ---


class ToolView(BaseModel):
    """The tool definition exposed to the LLM.

    Multiple ToolViews can point to the same canonical backend with different
    names, descriptions, and input schemas.
    """

    canonical_name: str
    exposed_name: str
    description: str
    input_schema: dict[str, Any]
    version: str = "default"
    metadata: dict[str, Any] = Field(default_factory=dict)


# --- Argument mapping ---


class ToolAdapter(BaseModel):
    """Maps exposed arguments to canonical arguments.

    Keys use dot-notation for nested properties (e.g. "line_range.begin").
    Values are the corresponding canonical argument names.
    """

    exposed_to_canonical: dict[str, str] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)

    def map_arguments(
        self,
        exposed_args: dict[str, Any],
        *,
        exposed_schema: dict[str, Any] | None = None,
        canonical_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Transform exposed arguments into canonical arguments.

        Validation is intentionally done both before and after mapping so the
        runtime can distinguish:
        - invalid exposed tool usage
        - invalid adapter output
        """
        if exposed_schema is not None:
            validate_json_schema(exposed_args, exposed_schema, schema_name="exposed")

        canonical: dict[str, Any] = {}

        if not self.exposed_to_canonical:
            canonical = _copy_nested(exposed_args)
        else:
            unmapped_leaf_paths = sorted(
                path
                for path in _iter_leaf_paths(exposed_args)
                if path not in self.exposed_to_canonical
            )
            if unmapped_leaf_paths:
                raise ToolArgumentError(
                    "Adapter is missing mappings for exposed fields: "
                    + ", ".join(unmapped_leaf_paths)
                )

            for exposed_key, canonical_key in self.exposed_to_canonical.items():
                value = _get_nested(exposed_args, exposed_key)
                if value is not None:
                    _set_nested(canonical, canonical_key, value)

        for key, value in self.defaults.items():
            if _get_nested(canonical, key) is None:
                _set_nested(canonical, key, value)

        if canonical_schema is not None:
            validate_json_schema(
                canonical,
                canonical_schema,
                schema_name="canonical",
            )

        return canonical

    def to_exposed_args(
        self,
        canonical_args: dict[str, Any],
        *,
        exposed_schema: dict[str, Any] | None = None,
        canonical_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Project canonical arguments into the currently exposed schema.

        Validation mirrors ``map_arguments()``:
        - optional canonical validation before projection
        - optional exposed validation after projection
        """
        if canonical_schema is not None:
            validate_json_schema(
                canonical_args,
                canonical_schema,
                schema_name="canonical",
            )

        if not self.exposed_to_canonical:
            exposed = _copy_nested(canonical_args)
        else:
            canonical_to_exposed = _invert_mapping(self.exposed_to_canonical)
            unmapped_leaf_paths = sorted(
                path
                for path in _iter_leaf_paths(canonical_args)
                if path not in canonical_to_exposed
            )
            if unmapped_leaf_paths:
                raise ToolArgumentError(
                    "Adapter is missing reverse mappings for canonical fields: "
                    + ", ".join(unmapped_leaf_paths)
                )

            exposed: dict[str, Any] = {}
            for canonical_key, exposed_key in canonical_to_exposed.items():
                value = _get_nested(canonical_args, canonical_key)
                if value is not None:
                    _set_nested(exposed, exposed_key, _copy_nested(value))

        if exposed_schema is not None:
            validate_json_schema(exposed, exposed_schema, schema_name="exposed")

        return exposed


# --- Profile ---


class ToolProfile(BaseModel):
    """A set of tool views with their adapters, forming a complete tool
    configuration that the LLM sees during a run."""

    profile_id: str
    tools: list[ToolView]
    adapters: dict[str, ToolAdapter] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def get_exposed_specs(self) -> list[dict[str, Any]]:
        """Return tool specs in the format expected by LLM tool-use APIs."""
        return [
            {
                "name": tv.exposed_name,
                "description": tv.description,
                "input_schema": tv.input_schema,
            }
            for tv in self.tools
        ]

    def get_tool(self, exposed_name: str) -> tuple[ToolView, ToolAdapter] | None:
        """Look up a tool view and its adapter by exposed name."""
        for tv in self.tools:
            if tv.exposed_name == exposed_name:
                adapter = self.adapters.get(tv.exposed_name, ToolAdapter())
                return tv, adapter
        return None

    def get_tool_versions(self) -> dict[str, dict[str, str]]:
        """Return a compact view of exposed tool versions for trajectory logs."""
        return {
            tv.exposed_name: {
                "canonical_name": tv.canonical_name,
                "version": tv.version,
            }
            for tv in self.tools
        }

    def map_call_arguments(
        self,
        exposed_name: str,
        exposed_args: dict[str, Any],
        canonical_tool: CanonicalTool | None = None,
    ) -> tuple[ToolView, dict[str, Any]]:
        """Resolve an exposed tool call into canonical arguments."""
        resolved = self.get_tool(exposed_name)
        if resolved is None:
            raise ToolArgumentError(f"Unknown tool: {exposed_name}")

        view, adapter = resolved
        canonical_args = adapter.map_arguments(
            exposed_args,
            exposed_schema=view.input_schema,
            canonical_schema=(
                canonical_tool.canonical_schema if canonical_tool is not None else None
            ),
        )
        return view, canonical_args

    def project_canonical_call(
        self,
        canonical_name: str,
        canonical_args: dict[str, Any],
        *,
        call_id: str = "call_1",
        canonical_tool: CanonicalTool | None = None,
    ):
        """Project a canonical intent into the exposed ToolView for this profile."""
        matches = [tool for tool in self.tools if tool.canonical_name == canonical_name]
        if not matches:
            raise ToolArgumentError(f"Unknown canonical tool: {canonical_name}")
        if len(matches) > 1:
            raise ToolArgumentError(
                f"Ambiguous canonical tool projection for {canonical_name!r}: "
                f"{len(matches)} ToolViews found"
            )

        view = matches[0]
        adapter = self.adapters.get(view.exposed_name, ToolAdapter())
        exposed_args = adapter.to_exposed_args(
            canonical_args,
            exposed_schema=view.input_schema,
            canonical_schema=(
                canonical_tool.canonical_schema if canonical_tool is not None else None
            ),
        )

        from pycodeagent.rl.schema_following import ExposedToolCallTarget

        return ExposedToolCallTarget(
            call_id=call_id,
            name=view.exposed_name,
            arguments=exposed_args,
        )


# --- Helpers ---


def _get_nested(obj: dict[str, Any], dotted_key: str) -> Any:
    """Get a value from a nested dict using dot-notation."""
    keys = dotted_key.split(".")
    current = obj
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _set_nested(obj: dict[str, Any], dotted_key: str, value: Any) -> None:
    """Set a value in a nested dict using dot-notation."""
    keys = dotted_key.split(".")
    current = obj
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


def _copy_nested(value: Any) -> Any:
    """Create a plain-Python deep copy for dict/list tool arguments."""
    if isinstance(value, dict):
        return {key: _copy_nested(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_copy_nested(child) for child in value]
    return value


def _invert_mapping(mapping: dict[str, str]) -> dict[str, str]:
    """Invert an exposed->canonical mapping, failing on ambiguous targets."""
    inverse: dict[str, str] = {}
    for exposed_key, canonical_key in mapping.items():
        existing = inverse.get(canonical_key)
        if existing is not None and existing != exposed_key:
            raise ToolArgumentError(
                "Adapter has ambiguous reverse mappings for canonical field "
                f"{canonical_key!r}: {existing!r}, {exposed_key!r}"
            )
        inverse[canonical_key] = exposed_key
    return inverse


def _iter_leaf_paths(value: Any, prefix: str = "") -> list[str]:
    """Return dotted paths for all leaf values in a nested argument object."""
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else key
            paths.extend(_iter_leaf_paths(child, child_prefix))
        return paths

    if isinstance(value, list):
        return [prefix] if prefix else []

    return [prefix] if prefix else []


def validate_json_schema(
    value: Any,
    schema: dict[str, Any],
    *,
    schema_name: str,
) -> None:
    """Validate a limited JSON Schema subset used by tool specs.

    The project mainly needs object/property/required/enum/nested structure
    validation. This intentionally covers the common subset used in tool
    mutation experiments without depending on an external validator.
    """
    _validate_against_schema(value, schema, path="$", schema_name=schema_name)


def _validate_against_schema(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str,
    schema_name: str,
) -> None:
    schema_type = schema.get("type")

    if schema_type is None:
        return

    if isinstance(schema_type, list):
        last_error: ToolArgumentError | None = None
        for candidate_type in schema_type:
            try:
                _validate_against_schema(
                    value,
                    {**schema, "type": candidate_type},
                    path=path,
                    schema_name=schema_name,
                )
                return
            except ToolArgumentError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        return

    if schema_type == "object":
        if not isinstance(value, dict):
            raise ToolArgumentError(
                f"{schema_name} schema violation at {path}: expected object"
            )

        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise ToolArgumentError(
                    f"{schema_name} schema violation at {path}: missing required field '{key}'"
                )

        properties = schema.get("properties", {})
        additional_properties = schema.get("additionalProperties", True)

        for key, child_value in value.items():
            if key in properties:
                _validate_against_schema(
                    child_value,
                    properties[key],
                    path=f"{path}.{key}",
                    schema_name=schema_name,
                )
            elif additional_properties is False:
                raise ToolArgumentError(
                    f"{schema_name} schema violation at {path}: unexpected field '{key}'"
                )
        return

    if schema_type == "array":
        if not isinstance(value, list):
            raise ToolArgumentError(
                f"{schema_name} schema violation at {path}: expected array"
            )

        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                _validate_against_schema(
                    item,
                    item_schema,
                    path=f"{path}[{index}]",
                    schema_name=schema_name,
                )
        return

    if schema_type == "string" and not isinstance(value, str):
        raise ToolArgumentError(
            f"{schema_name} schema violation at {path}: expected string"
        )

    if schema_type == "integer" and not (
        isinstance(value, int) and not isinstance(value, bool)
    ):
        raise ToolArgumentError(
            f"{schema_name} schema violation at {path}: expected integer"
        )

    if schema_type == "number" and not (
        isinstance(value, (int, float)) and not isinstance(value, bool)
    ):
        raise ToolArgumentError(
            f"{schema_name} schema violation at {path}: expected number"
        )

    if schema_type == "boolean" and not isinstance(value, bool):
        raise ToolArgumentError(
            f"{schema_name} schema violation at {path}: expected boolean"
        )

    if schema_type == "null" and value is not None:
        raise ToolArgumentError(
            f"{schema_name} schema violation at {path}: expected null"
        )

    enum_values = schema.get("enum")
    if enum_values is not None and value not in enum_values:
        raise ToolArgumentError(
            f"{schema_name} schema violation at {path}: expected one of {enum_values!r}"
        )
