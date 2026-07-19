"""Validation for auxiliary transformed native SFT datasets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from pycodeagent.auxiliary.claude_api.sft import ClaudeApiSFTSample


class NativeTransformedSFTValidationIssue(BaseModel):
    """One validation issue for one transformed native SFT sample."""

    line_no: int
    sample_id: str | None = None
    reason: str
    context: dict[str, Any] = Field(default_factory=dict)


class NativeTransformedSFTValidationReport(BaseModel):
    """Validation report for a transformed native SFT dataset directory."""

    dataset_dir: str
    train_path: str
    sample_count: int
    valid_sample_count: int
    invalid_sample_count: int
    mode_counts: dict[str, int] = Field(default_factory=dict)
    invalid_reasons: dict[str, int] = Field(default_factory=dict)
    issues: list[NativeTransformedSFTValidationIssue] = Field(default_factory=list)
    validation_report_path: str = ""

    @property
    def ok(self) -> bool:
        return not self.issues


def _increment(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _add_issue(
    issues: list[NativeTransformedSFTValidationIssue],
    invalid_reasons: dict[str, int],
    *,
    line_no: int,
    sample_id: str | None,
    reason: str,
    context: dict[str, Any] | None = None,
) -> None:
    _increment(invalid_reasons, reason)
    issues.append(
        NativeTransformedSFTValidationIssue(
            line_no=line_no,
            sample_id=sample_id,
            reason=reason,
            context=context or {},
        )
    )


def _required_source_keys() -> tuple[str, ...]:
    return (
        "source_trace_path",
        "source_request_id",
        "source_catalog_id",
        "base_profile_id",
        "target_profile_id",
    )


def _validate_raw_sample_shape(
    data: dict[str, Any],
    *,
    line_no: int,
    issues: list[NativeTransformedSFTValidationIssue],
    invalid_reasons: dict[str, int],
) -> None:
    sample_id = data.get("sample_id") if isinstance(data.get("sample_id"), str) else None
    metadata = data.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    tool_specs = data.get("tool_specs")
    target_blocks = data.get("target_blocks")

    transformation_mode = metadata.get("transformation_mode")
    if not isinstance(transformation_mode, str) or not transformation_mode:
        _add_issue(
            issues,
            invalid_reasons,
            line_no=line_no,
            sample_id=sample_id,
            reason="missing_transformation_mode",
        )

    if not isinstance(tool_specs, list) or len(tool_specs) == 0:
        _add_issue(
            issues,
            invalid_reasons,
            line_no=line_no,
            sample_id=sample_id,
            reason="empty_visible_tool_specs",
        )
        visible_names: set[str] = set()
    else:
        visible_names = {
            spec.get("name")
            for spec in tool_specs
            if isinstance(spec, dict) and isinstance(spec.get("name"), str) and spec.get("name")
        }
        if not visible_names:
            _add_issue(
                issues,
                invalid_reasons,
                line_no=line_no,
                sample_id=sample_id,
                reason="empty_visible_tool_specs",
            )

    missing_source_keys = [
        key for key in _required_source_keys() if not isinstance(metadata.get(key), str) or not metadata.get(key)
    ]
    if missing_source_keys:
        _add_issue(
            issues,
            invalid_reasons,
            line_no=line_no,
            sample_id=sample_id,
            reason="missing_source_metadata",
            context={"missing_keys": missing_source_keys},
        )

    remap_report = metadata.get("tool_use_remap_report")
    if not isinstance(remap_report, dict):
        _add_issue(
            issues,
            invalid_reasons,
            line_no=line_no,
            sample_id=sample_id,
            reason="missing_remap_report",
        )
    else:
        unmapped_tool_uses = remap_report.get("unmapped_tool_uses", 0)
        dropped_tool_uses = remap_report.get("dropped_tool_uses", 0)
        if unmapped_tool_uses != 0:
            _add_issue(
                issues,
                invalid_reasons,
                line_no=line_no,
                sample_id=sample_id,
                reason="remap_report_has_unmapped_tool_uses",
                context={"unmapped_tool_uses": unmapped_tool_uses},
            )
        if dropped_tool_uses != 0:
            _add_issue(
                issues,
                invalid_reasons,
                line_no=line_no,
                sample_id=sample_id,
                reason="remap_report_has_dropped_tool_uses",
                context={"dropped_tool_uses": dropped_tool_uses},
            )

    if not isinstance(target_blocks, list):
        return

    for index, block in enumerate(target_blocks):
        if not isinstance(block, dict):
            continue
        block_type = block.get("block_type")
        if block_type in {"thinking", "tool_result"}:
            _add_issue(
                issues,
                invalid_reasons,
                line_no=line_no,
                sample_id=sample_id,
                reason="forbidden_target_block_type",
                context={"index": index, "block_type": block_type},
            )
            continue
        if block_type != "tool_use":
            continue
        tool_call = block.get("tool_call")
        tool_name = tool_call.get("name") if isinstance(tool_call, dict) else None
        if not isinstance(tool_name, str) or not tool_name or tool_name not in visible_names:
            _add_issue(
                issues,
                invalid_reasons,
                line_no=line_no,
                sample_id=sample_id,
                reason="tool_call_name_not_in_visible_specs",
                context={"index": index, "tool_name": tool_name},
            )


def validate_native_transformed_sft_dataset(
    dataset_dir: str | Path,
) -> NativeTransformedSFTValidationReport:
    """Validate one transformed native SFT dataset directory and write a report."""
    dataset_dir = Path(dataset_dir)
    train_path = dataset_dir / "train.jsonl"
    if not train_path.exists():
        raise FileNotFoundError(f"Missing transformed dataset file: {train_path}")

    issues: list[NativeTransformedSFTValidationIssue] = []
    invalid_reasons: dict[str, int] = {}
    mode_counts: dict[str, int] = {}
    sample_count = 0
    valid_sample_count = 0

    manifest_path = dataset_dir / "dataset_manifest.json"
    if not manifest_path.exists():
        _add_issue(
            issues,
            invalid_reasons,
            line_no=0,
            sample_id=None,
            reason="missing_dataset_manifest",
        )
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            _add_issue(
                issues,
                invalid_reasons,
                line_no=0,
                sample_id=None,
                reason="invalid_dataset_manifest_json",
                context={"error": str(exc)},
            )
        else:
            if manifest.get("dataset_type") != "native_transformed_claude_api_sft":
                _add_issue(
                    issues,
                    invalid_reasons,
                    line_no=0,
                    sample_id=None,
                    reason="invalid_dataset_type",
                    context={"dataset_type": manifest.get("dataset_type")},
                )
            if manifest.get("primary_sample_input") != "train.jsonl":
                _add_issue(
                    issues,
                    invalid_reasons,
                    line_no=0,
                    sample_id=None,
                    reason="invalid_primary_sample_input",
                    context={"primary_sample_input": manifest.get("primary_sample_input")},
                )
            if manifest.get("present_splits") != ["train"]:
                _add_issue(
                    issues,
                    invalid_reasons,
                    line_no=0,
                    sample_id=None,
                    reason="invalid_present_splits",
                    context={"present_splits": manifest.get("present_splits")},
                )

    split_metrics_path = dataset_dir / "split_metrics.json"
    if not split_metrics_path.exists():
        _add_issue(
            issues,
            invalid_reasons,
            line_no=0,
            sample_id=None,
            reason="missing_split_metrics",
        )

    with open(train_path, encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            sample_count += 1
            line_start_issue_count = len(issues)
            sample_id: str | None = None
            data: dict[str, Any] | None = None

            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                _add_issue(
                    issues,
                    invalid_reasons,
                    line_no=line_no,
                    sample_id=None,
                    reason="invalid_json",
                    context={"error": str(exc)},
                )
                continue

            if not isinstance(parsed, dict):
                _add_issue(
                    issues,
                    invalid_reasons,
                    line_no=line_no,
                    sample_id=None,
                    reason="invalid_sample_shape",
                    context={"type": type(parsed).__name__},
                )
                continue

            data = parsed
            if isinstance(data.get("sample_id"), str):
                sample_id = data["sample_id"]

            metadata = data.get("metadata")
            if isinstance(metadata, dict):
                transformation_mode = metadata.get("transformation_mode")
                if isinstance(transformation_mode, str) and transformation_mode:
                    _increment(mode_counts, transformation_mode)

            _validate_raw_sample_shape(
                data,
                line_no=line_no,
                issues=issues,
                invalid_reasons=invalid_reasons,
            )

            try:
                ClaudeApiSFTSample.model_validate(data)
            except ValidationError as exc:
                _add_issue(
                    issues,
                    invalid_reasons,
                    line_no=line_no,
                    sample_id=sample_id,
                    reason="parse_error",
                    context={"error": str(exc)},
                )

            if len(issues) == line_start_issue_count:
                valid_sample_count += 1

    report = NativeTransformedSFTValidationReport(
        dataset_dir=str(dataset_dir),
        train_path=str(train_path),
        sample_count=sample_count,
        valid_sample_count=valid_sample_count,
        invalid_sample_count=sample_count - valid_sample_count,
        mode_counts=mode_counts,
        invalid_reasons=invalid_reasons,
        issues=issues,
    )
    report_path = dataset_dir / "validation_report.json"
    report.validation_report_path = str(report_path)
    report_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return report
