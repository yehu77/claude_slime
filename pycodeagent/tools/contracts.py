"""Shared internal tool-contract helpers.

Step C0 keeps legacy function-tool compatibility while adding the minimum
contract machinery needed for freeform tools.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ToolContractKind(str, Enum):
    """Internal tool definition kinds supported by the local runtime."""

    FUNCTION = "function"
    FREEFORM = "freeform"


class ToolPayloadKind(str, Enum):
    """Internal tool-call payload kinds supported by the local runtime."""

    ARGUMENTS_OBJECT = "arguments_object"
    INPUT_TEXT = "input_text"


class ExposedToolSpec(BaseModel):
    """Validated exposed tool spec used by request-side contract checks."""

    name: str
    description: str = ""
    kind: ToolContractKind = ToolContractKind.FUNCTION
    input_schema: dict[str, Any] | None = None
    input_format: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_contract(self) -> "ExposedToolSpec":
        if self.kind == ToolContractKind.FUNCTION:
            if self.input_schema is None:
                self.input_schema = {}
            if not isinstance(self.input_schema, dict):
                raise ValueError("function tool spec input_schema must be a mapping")
            if self.input_format is not None and not isinstance(self.input_format, dict):
                raise ValueError("function tool spec input_format must be a mapping when present")
            return self

        if self.input_format is not None and not isinstance(self.input_format, dict):
            raise ValueError("freeform tool spec input_format must be a mapping when present")
        if self.input_schema is not None and not isinstance(self.input_schema, dict):
            raise ValueError("freeform tool spec input_schema must be a mapping when present")
        return self

    def to_wire_dict(self) -> dict[str, Any]:
        """Return the normalized wire representation.

        Function specs intentionally preserve the legacy shape:

        - no explicit ``kind`` key by default
        - ``input_schema`` remains the main contract field

        Freeform specs add the explicit discriminant and raw input format.
        """
        data: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
        }
        if self.kind == ToolContractKind.FREEFORM:
            data["kind"] = self.kind.value
            if self.input_format is not None:
                data["input_format"] = dict(self.input_format)
            if self.input_schema:
                data["input_schema"] = dict(self.input_schema)
        else:
            data["input_schema"] = dict(self.input_schema or {})
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data

    def __getitem__(self, key: str) -> Any:
        return self.to_wire_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_wire_dict().get(key, default)

    def keys(self):
        return self.to_wire_dict().keys()

    def items(self):
        return self.to_wire_dict().items()

    def __iter__(self):
        return iter(self.to_wire_dict())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ExposedToolSpec):
            return self.to_wire_dict() == other.to_wire_dict()
        if isinstance(other, dict):
            return self.to_wire_dict() == other
        return super().__eq__(other)

    def model_dump(self, *args, **kwargs) -> dict[str, Any]:  # type: ignore[override]
        return self.to_wire_dict()


def coerce_tool_contract_kind(raw_kind: Any) -> ToolContractKind:
    """Coerce a raw contract-kind value into the enum."""
    if isinstance(raw_kind, ToolContractKind):
        return raw_kind
    if raw_kind is None:
        return ToolContractKind.FUNCTION
    return ToolContractKind(str(raw_kind))


def normalize_exposed_tool_spec(spec: dict[str, Any] | ExposedToolSpec) -> dict[str, Any]:
    """Validate and normalize one exposed tool spec."""
    if isinstance(spec, ExposedToolSpec):
        return spec.to_wire_dict()
    return ExposedToolSpec.model_validate(spec).to_wire_dict()


def tool_spec_kind(spec: dict[str, Any]) -> ToolContractKind:
    """Return the effective kind for an exposed tool spec dict."""
    return coerce_tool_contract_kind(spec.get("kind"))


def tool_spec_input_schema(spec: dict[str, Any]) -> dict[str, Any] | None:
    """Return the object input schema when the spec is function-shaped."""
    if tool_spec_kind(spec) != ToolContractKind.FUNCTION:
        return None
    input_schema = spec.get("input_schema", {})
    return input_schema if isinstance(input_schema, dict) else None


def tool_spec_input_format(spec: dict[str, Any]) -> dict[str, Any] | None:
    """Return the raw input format when the spec is freeform."""
    if tool_spec_kind(spec) != ToolContractKind.FREEFORM:
        return None
    input_format = spec.get("input_format")
    return input_format if isinstance(input_format, dict) else None
