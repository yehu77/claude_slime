"""Auxiliary batch export for transformed SFT datasets from Claude API traces."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from pycodeagent.auxiliary.claude_api.sft_dataset import discover_claude_gateway_session_files
from pycodeagent.auxiliary.claude_api.sft_dataset_io import write_claude_api_sft_jsonl
from pycodeagent.auxiliary.claude_api.tool_catalog_snapshot import (
    build_catalog_from_claude_request_tools,
)
from pycodeagent.auxiliary.native_transformed.sft import build_transformed_native_sft_sample
from pycodeagent.tools.spec import ToolProfile
from pycodeagent.auxiliary.claude_api.trace_extract import extract_claude_request_sample
from pycodeagent.auxiliary.claude_api.trace_loader import read_claude_api_session
from pycodeagent.traces.native_profile_transform import (
    NativeTransformationMode,
    build_native_transformed_profile,
)
from pycodeagent.traces.tool_catalog_snapshot import catalog_to_base_tool_profile


_DEFAULT_MODES: tuple[NativeTransformationMode, ...] = (
    "base",
    "name_only",
    "description_only",
    "name_description",
)


class NativeTransformedSFTFailedFile(BaseModel):
    """One session file that failed during transformed dataset export."""

    path: str
    stage: str
    error: str


class NativeTransformedSFTDatasetBuildResult(BaseModel):
    """Summary of one transformed native SFT dataset export."""

    output_dir: str
    source_dir: str
    session_count: int
    request_count: int
    tool_use_request_count: int
    skipped_request_count: int
    sample_count: int
    mode_counts: dict[str, int] = Field(default_factory=dict)
    mapped_tool_use_count: int = 0
    unmapped_tool_use_count: int = 0
    dropped_tool_use_count: int = 0
    remap_status_counts: dict[str, int] = Field(default_factory=dict)
    failed_files: list[NativeTransformedSFTFailedFile] = Field(default_factory=list)
    dataset_manifest_path: str
    split_metrics_path: str
    present_splits: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _relative_trace_path(path: Path, source_dir: Path) -> str:
    try:
        return path.relative_to(source_dir).as_posix()
    except ValueError:
        return str(path)


def _increment(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _count_target_block_types(samples: list[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in samples:
        for block in sample.target_blocks:
            _increment(counts, block.block_type)
    return counts


def build_native_transformed_sft_dataset(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    modes: tuple[NativeTransformationMode, ...] = _DEFAULT_MODES,
    strict: bool = True,
    continue_on_error: bool = False,
) -> NativeTransformedSFTDatasetBuildResult:
    """Export transformed native SFT samples from Claude tool-use traces."""
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    session_files = discover_claude_gateway_session_files(source_dir)
    samples = []
    failed_files: list[NativeTransformedSFTFailedFile] = []
    notes = [
        "skipped_request_count counts requests skipped before transformed sample emission "
        "(for example no tools, no tool_use, or incomplete extraction)."
    ]

    session_count = 0
    request_count = 0
    tool_use_request_count = 0
    skipped_request_count = 0
    mode_counts: dict[str, int] = {mode: 0 for mode in modes}
    model_counts: dict[str, int] = {}
    stop_reason_counts: dict[str, int] = {}
    remap_status_counts: dict[str, int] = {}
    mapped_tool_use_count = 0
    unmapped_tool_use_count = 0
    dropped_tool_use_count = 0

    for session_file in session_files:
        relative_trace_path = _relative_trace_path(session_file, source_dir)
        try:
            session = read_claude_api_session(session_file, strict=strict)
        except Exception as exc:
            if not continue_on_error:
                raise
            failed_files.append(
                NativeTransformedSFTFailedFile(
                    path=relative_trace_path,
                    stage="load",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        try:
            for request in session.message_requests:
                request_count += 1
                extracted = extract_claude_request_sample(
                    request,
                    include_incomplete=False,
                )
                if extracted is None:
                    skipped_request_count += 1
                    continue

                extracted.metadata["source_trace_path"] = relative_trace_path

                tool_specs = request.request_body.get("tools")
                if not isinstance(tool_specs, list) or len(tool_specs) == 0:
                    skipped_request_count += 1
                    continue

                if not any(block.block_type == "tool_use" for block in extracted.response_blocks):
                    skipped_request_count += 1
                    continue

                catalog = build_catalog_from_claude_request_tools(
                    request,
                    source_trace_path=relative_trace_path,
                )
                if catalog is None:
                    skipped_request_count += 1
                    continue

                base_profile = catalog_to_base_tool_profile(catalog)
                tool_use_request_count += 1

                for mode in modes:
                    target_profile = build_native_transformed_profile(
                        base_profile,
                        mode=mode,
                        seed=0,
                    )
                    result = build_transformed_native_sft_sample(
                        extracted,
                        source_catalog=catalog,
                        base_profile=base_profile,
                        target_profile=target_profile,
                        session=session,
                    )
                    unmapped_tool_use_count += result.remap_report.unmapped_tool_uses
                    dropped_tool_use_count += result.remap_report.dropped_tool_uses
                    for entry in result.remap_report.entries:
                        _increment(remap_status_counts, entry.status)
                        if entry.status == "mapped":
                            mapped_tool_use_count += 1

                    if result.sample is None:
                        continue

                    samples.append(result.sample)
                    mode_counts[mode] = mode_counts.get(mode, 0) + 1
                    model = result.sample.metadata.get("model")
                    if isinstance(model, str) and model:
                        _increment(model_counts, model)
                    stop_reason = result.sample.metadata.get("stop_reason")
                    if isinstance(stop_reason, str) and stop_reason:
                        _increment(stop_reason_counts, stop_reason)
        except Exception as exc:
            if not continue_on_error:
                raise
            failed_files.append(
                NativeTransformedSFTFailedFile(
                    path=relative_trace_path,
                    stage="transform",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        session_count += 1

    train_path = output_dir / "train.jsonl"
    write_claude_api_sft_jsonl(samples, train_path)

    present_splits = ["train"]
    manifest = {
        "dataset_type": "native_transformed_claude_api_sft",
        "version": 1,
        "source_dir": str(source_dir),
        "sample_count": len(samples),
        "session_count": session_count,
        "request_count": request_count,
        "tool_use_request_count": tool_use_request_count,
        "skipped_request_count": skipped_request_count,
        "mode_counts": mode_counts,
        "failed_files": [item.model_dump(mode="json") for item in failed_files],
        "present_splits": present_splits,
        "primary_sample_input": "train.jsonl",
        "notes": notes,
    }
    split_metrics = {
        "version": 1,
        "split_counts": {"train": len(samples)},
        "mode_counts": mode_counts,
        "model_counts": model_counts,
        "stop_reason_counts": stop_reason_counts,
        "target_block_type_counts": _count_target_block_types(samples),
        "remap_status_counts": remap_status_counts,
        "mapped_tool_use_count": mapped_tool_use_count,
        "unmapped_tool_use_count": unmapped_tool_use_count,
        "dropped_tool_use_count": dropped_tool_use_count,
    }

    dataset_manifest_path = output_dir / "dataset_manifest.json"
    split_metrics_path = output_dir / "split_metrics.json"
    dataset_manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    split_metrics_path.write_text(
        json.dumps(split_metrics, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )

    return NativeTransformedSFTDatasetBuildResult(
        output_dir=str(output_dir),
        source_dir=str(source_dir),
        session_count=session_count,
        request_count=request_count,
        tool_use_request_count=tool_use_request_count,
        skipped_request_count=skipped_request_count,
        sample_count=len(samples),
        mode_counts=mode_counts,
        mapped_tool_use_count=mapped_tool_use_count,
        unmapped_tool_use_count=unmapped_tool_use_count,
        dropped_tool_use_count=dropped_tool_use_count,
        remap_status_counts=remap_status_counts,
        failed_files=failed_files,
        dataset_manifest_path=str(dataset_manifest_path),
        split_metrics_path=str(split_metrics_path),
        present_splits=present_splits,
        notes=notes,
    )
