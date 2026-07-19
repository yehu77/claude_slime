"""Auxiliary eval for native-transformed Claude API SFT tool-name following."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from pycodeagent.auxiliary.claude_api.sft import ClaudeApiSFTSample
from pycodeagent.rl.schema_following_eval import parse_tool_call_block
from pycodeagent.auxiliary.claude_api.serializer import serialize_claude_api_sft_sample


class NativeTransformedPredictor(Protocol):
    """Protocol for predictors that complete a native-transformed SFT prompt."""

    def predict(self, sample: ClaudeApiSFTSample, prompt_text: str) -> str:
        """Return generated text for one evaluation sample."""
        ...


class NativeTransformedToolNameEvalCase(BaseModel):
    """Detailed outcome for one native-transformed tool-name probe."""

    sample_id: str
    task_id: str
    tool_profile_id: str
    transformation_mode: str | None = None
    prompt_text: str
    predicted_text: str
    expected_tool_name: str
    predicted_tool_name: str | None = None
    expected_arguments: dict[str, Any]
    predicted_arguments: dict[str, Any] | None = None
    parse_ok: bool
    tool_name_ok: bool
    arguments_exact_match: bool
    error_code: str | None = None
    error_message: str | None = None


class NativeTransformedToolNameEvalReport(BaseModel):
    """Aggregate report for native-transformed tool-name probes."""

    model_label: str
    dataset_dir: str
    sample_count: int
    parse_rate: float
    tool_name_accuracy: float
    argument_exact_match_rate: float
    failed_cases: list[NativeTransformedToolNameEvalCase] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NativeTransformedToolNameComparisonReport(BaseModel):
    """Before/after comparison for the native-transformed smoke eval."""

    dataset_dir: str
    baseline_label: str
    trained_label: str
    baseline_report_path: str
    trained_report_path: str
    sample_count: int
    parse_rate_delta: float
    tool_name_accuracy_delta: float
    argument_exact_match_rate_delta: float
    improved: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_native_transformed_prompt_text(sample: ClaudeApiSFTSample) -> str:
    """Return serialized non-trainable context for one native-transformed sample."""
    serialized = serialize_claude_api_sft_sample(sample)
    return "".join(segment.text for segment in serialized.segments if not segment.trainable)


def evaluate_native_transformed_tool_name_predictor(
    samples: list[ClaudeApiSFTSample],
    *,
    predictor: NativeTransformedPredictor,
    model_label: str,
    dataset_dir: str | Path,
    failed_case_limit: int | None = 100,
    metadata: dict[str, Any] | None = None,
) -> NativeTransformedToolNameEvalReport:
    """Evaluate whether a predictor emits the expected transformed tool name."""
    cases: list[NativeTransformedToolNameEvalCase] = []
    failed_cases: list[NativeTransformedToolNameEvalCase] = []

    for sample in samples:
        prompt_text = build_native_transformed_prompt_text(sample)
        predicted_text = predictor.predict(sample, prompt_text)
        case = evaluate_native_transformed_tool_name_sample(
            sample,
            prompt_text=prompt_text,
            predicted_text=predicted_text,
        )
        cases.append(case)
        if case.error_code is not None:
            if failed_case_limit is None or len(failed_cases) < failed_case_limit:
                failed_cases.append(case)

    total = len(cases)
    parse_rate = (sum(1 for case in cases if case.parse_ok) / total) if total else 0.0
    tool_name_accuracy = (
        sum(1 for case in cases if case.tool_name_ok) / total
    ) if total else 0.0
    argument_exact_match_rate = (
        sum(1 for case in cases if case.arguments_exact_match) / total
    ) if total else 0.0
    return NativeTransformedToolNameEvalReport(
        model_label=model_label,
        dataset_dir=str(dataset_dir),
        sample_count=total,
        parse_rate=parse_rate,
        tool_name_accuracy=tool_name_accuracy,
        argument_exact_match_rate=argument_exact_match_rate,
        failed_cases=failed_cases,
        metadata=metadata or {},
    )


def evaluate_native_transformed_tool_name_sample(
    sample: ClaudeApiSFTSample,
    *,
    prompt_text: str,
    predicted_text: str,
) -> NativeTransformedToolNameEvalCase:
    """Evaluate one generated completion against the first target tool-use block."""
    expected_name, expected_arguments = _first_tool_use_target(sample)
    transformation_mode = sample.metadata.get("transformation_mode")
    mode = transformation_mode if isinstance(transformation_mode, str) else None

    try:
        payload = parse_tool_call_block(predicted_text)
    except ValueError as exc:
        return NativeTransformedToolNameEvalCase(
            sample_id=sample.sample_id,
            task_id=sample.task_id,
            tool_profile_id=sample.tool_profile_id,
            transformation_mode=mode,
            prompt_text=prompt_text,
            predicted_text=predicted_text,
            expected_tool_name=expected_name,
            expected_arguments=expected_arguments,
            parse_ok=False,
            tool_name_ok=False,
            arguments_exact_match=False,
            error_code=_normalize_parse_error(str(exc)),
            error_message=str(exc),
        )

    predicted_name = payload["name"]
    predicted_arguments = payload.get("arguments")
    tool_name_ok = predicted_name == expected_name
    arguments_exact_match = predicted_arguments == expected_arguments
    error_code = None
    error_message = None
    if not tool_name_ok:
        error_code = "tool_name_mismatch"
        error_message = f"Predicted {predicted_name!r}, expected {expected_name!r}"
    elif not arguments_exact_match:
        error_code = "arguments_mismatch"
        error_message = "Predicted arguments do not exactly match expected arguments"

    return NativeTransformedToolNameEvalCase(
        sample_id=sample.sample_id,
        task_id=sample.task_id,
        tool_profile_id=sample.tool_profile_id,
        transformation_mode=mode,
        prompt_text=prompt_text,
        predicted_text=predicted_text,
        expected_tool_name=expected_name,
        predicted_tool_name=predicted_name,
        expected_arguments=expected_arguments,
        predicted_arguments=predicted_arguments,
        parse_ok=True,
        tool_name_ok=tool_name_ok,
        arguments_exact_match=arguments_exact_match,
        error_code=error_code,
        error_message=error_message,
    )


def compare_native_transformed_tool_name_reports(
    baseline: NativeTransformedToolNameEvalReport,
    trained: NativeTransformedToolNameEvalReport,
    *,
    baseline_report_path: str,
    trained_report_path: str,
    metadata: dict[str, Any] | None = None,
) -> NativeTransformedToolNameComparisonReport:
    """Compare base and trained native-transformed tool-name reports."""
    tool_delta = trained.tool_name_accuracy - baseline.tool_name_accuracy
    return NativeTransformedToolNameComparisonReport(
        dataset_dir=baseline.dataset_dir,
        baseline_label=baseline.model_label,
        trained_label=trained.model_label,
        baseline_report_path=baseline_report_path,
        trained_report_path=trained_report_path,
        sample_count=trained.sample_count,
        parse_rate_delta=trained.parse_rate - baseline.parse_rate,
        tool_name_accuracy_delta=tool_delta,
        argument_exact_match_rate_delta=(
            trained.argument_exact_match_rate - baseline.argument_exact_match_rate
        ),
        improved=tool_delta > 0.0,
        metadata=metadata or {},
    )


def write_native_transformed_eval_report_json(
    path: str | Path,
    report: NativeTransformedToolNameEvalReport,
) -> None:
    """Write a native-transformed eval report to JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def write_native_transformed_comparison_report_json(
    path: str | Path,
    report: NativeTransformedToolNameComparisonReport,
) -> None:
    """Write a native-transformed before/after comparison report to JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _first_tool_use_target(sample: ClaudeApiSFTSample) -> tuple[str, dict[str, Any]]:
    for block in sample.target_blocks:
        if block.block_type == "tool_use" and block.tool_call is not None:
            return block.tool_call.name, dict(block.tool_call.arguments)
    raise ValueError(f"Sample has no tool_use target block: {sample.sample_id}")


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
