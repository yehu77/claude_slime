"""Reward evaluators for native-transformed RL prompt samples."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from pycodeagent.rl.native_transformed_rl_dataset import (
    NativeTransformedExpectedToolCall,
    NativeTransformedRLPromptSample,
)
from pycodeagent.rl.schema_following_eval import parse_tool_call_block


SchemaStatus = Literal["valid", "invalid", "not_applicable"]


class NativeTransformedRLRewardCase(BaseModel):
    """Detailed reward outcome for one generated completion."""

    sample_id: str
    task_id: str
    tool_profile_id: str
    predicted_text: str
    expected_tool_name: str
    expected_arguments: dict[str, Any]
    predicted_tool_name: str | None = None
    predicted_arguments: dict[str, Any] | None = None
    reward: float
    parse_ok: bool
    tool_name_ok: bool
    arguments_exact_match: bool
    schema_status: SchemaStatus
    reward_breakdown: dict[str, float] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def evaluate_native_transformed_rl_completion(
    sample: NativeTransformedRLPromptSample,
    predicted_text: str,
) -> NativeTransformedRLRewardCase:
    """Evaluate one generated completion against the first expected tool call."""
    expected = sample.reward_reference.expected_tool_calls[0]
    try:
        payload = parse_tool_call_block(predicted_text)
    except ValueError as exc:
        return _failed_parse_case(sample, expected, predicted_text, exc)

    predicted_name = payload["name"]
    predicted_arguments = payload.get("arguments")
    tool_name_ok = predicted_name == expected.name
    arguments_exact_match = predicted_arguments == expected.arguments
    schema_status, schema_error = _validate_against_tool_spec(
        sample.tool_specs,
        predicted_name,
        predicted_arguments,
    )

    raw_breakdown = {
        "parse": 0.1,
        "tool_name": 0.4 if tool_name_ok else 0.0,
        "arguments_exact": 0.4 if arguments_exact_match else 0.0,
    }
    denominator = 0.9
    if schema_status != "not_applicable":
        raw_breakdown["schema"] = 0.1 if schema_status == "valid" else 0.0
        denominator = 1.0

    reward = min(1.0, sum(raw_breakdown.values()) / denominator)
    error_code, error_message = _resolve_error(
        tool_name_ok=tool_name_ok,
        arguments_exact_match=arguments_exact_match,
        schema_status=schema_status,
        schema_error=schema_error,
    )
    return NativeTransformedRLRewardCase(
        sample_id=sample.sample_id,
        task_id=sample.task_id,
        tool_profile_id=sample.tool_profile_id,
        predicted_text=predicted_text,
        expected_tool_name=expected.name,
        expected_arguments=expected.arguments,
        predicted_tool_name=predicted_name,
        predicted_arguments=predicted_arguments,
        reward=reward,
        parse_ok=True,
        tool_name_ok=tool_name_ok,
        arguments_exact_match=arguments_exact_match,
        schema_status=schema_status,
        reward_breakdown=raw_breakdown,
        error_code=error_code,
        error_message=error_message,
        metadata={
            "reference_type": sample.reward_reference.reference_type,
            "expected_tool_call_count": len(sample.reward_reference.expected_tool_calls),
        },
    )


def _failed_parse_case(
    sample: NativeTransformedRLPromptSample,
    expected: NativeTransformedExpectedToolCall,
    predicted_text: str,
    exc: ValueError,
) -> NativeTransformedRLRewardCase:
    return NativeTransformedRLRewardCase(
        sample_id=sample.sample_id,
        task_id=sample.task_id,
        tool_profile_id=sample.tool_profile_id,
        predicted_text=predicted_text,
        expected_tool_name=expected.name,
        expected_arguments=expected.arguments,
        reward=0.0,
        parse_ok=False,
        tool_name_ok=False,
        arguments_exact_match=False,
        schema_status="not_applicable",
        reward_breakdown={
            "parse": 0.0,
            "tool_name": 0.0,
            "arguments_exact": 0.0,
        },
        error_code=_normalize_parse_error(str(exc)),
        error_message=str(exc),
    )


def _validate_against_tool_spec(
    tool_specs: list[dict[str, Any]],
    tool_name: str,
    arguments: dict[str, Any] | None,
) -> tuple[SchemaStatus, str | None]:
    if arguments is None:
        return "not_applicable", None
    spec = next(
        (tool_spec for tool_spec in tool_specs if tool_spec.get("name") == tool_name),
        None,
    )
    if spec is None:
        return "not_applicable", None
    schema = spec.get("input_schema")
    if not isinstance(schema, dict):
        return "not_applicable", None
    if schema.get("type") not in {None, "object"}:
        return "not_applicable", None

    required = schema.get("required", [])
    if not isinstance(required, list):
        return "invalid", "required must be a list"
    for key in required:
        if not isinstance(key, str):
            return "invalid", "required entries must be strings"
        if key not in arguments:
            return "invalid", f"missing required argument: {key}"

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return "not_applicable", None
    for key, value in arguments.items():
        property_schema = properties.get(key)
        if not isinstance(property_schema, dict):
            continue
        expected_type = property_schema.get("type")
        if isinstance(expected_type, str) and not _matches_json_type(value, expected_type):
            return "invalid", f"argument {key!r} is not {expected_type}"
    return "valid", None


def _matches_json_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "null":
        return value is None
    return True


def _resolve_error(
    *,
    tool_name_ok: bool,
    arguments_exact_match: bool,
    schema_status: SchemaStatus,
    schema_error: str | None,
) -> tuple[str | None, str | None]:
    if not tool_name_ok:
        return "tool_name_mismatch", "Predicted tool name does not match expected tool name"
    if schema_status == "invalid":
        return "schema_invalid", schema_error or "Predicted arguments do not match tool schema"
    if not arguments_exact_match:
        return "arguments_mismatch", "Predicted arguments do not exactly match expected arguments"
    return None, None


def _normalize_parse_error(error: str) -> str:
    if error == "missing_tool_call_block":
        return "missing_tool_call_block"
    if error == "missing_end_marker":
        return "missing_end_marker"
    if error.startswith("invalid_json:"):
        return "invalid_json"
    if error.startswith("invalid_payload"):
        return error
    return "parse_error"
