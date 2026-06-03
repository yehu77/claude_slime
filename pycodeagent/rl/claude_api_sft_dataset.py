"""Batch export for Claude API trace -> conservative SFT datasets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.rl.claude_api_sft import build_claude_api_sft_sample
from pycodeagent.rl.claude_api_sft_dataset_io import write_claude_api_sft_jsonl
from pycodeagent.traces.claude_api_trace_extract import extract_claude_session
from pycodeagent.traces.claude_api_trace_loader import read_claude_api_session


class ClaudeApiSFTFailedFile(BaseModel):
    """One session file that failed during batch export."""

    path: str
    stage: str
    error: str


class ClaudeApiSFTDatasetBuildResult(BaseModel):
    """Summary of one batch Claude API SFT dataset export."""

    output_dir: str
    source_dir: str
    session_count: int
    request_count: int
    sample_count: int
    extractor_skipped_request_count: int
    converter_skipped_sample_count: int
    error_request_count: int
    incomplete_request_count: int
    no_trainable_target_count: int
    failed_files: list[ClaudeApiSFTFailedFile] = Field(default_factory=list)
    dataset_manifest_path: str
    split_metrics_path: str
    present_splits: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def discover_claude_gateway_session_files(source_dir: str | Path) -> list[Path]:
    """Return deterministic Claude gateway session JSONL files under one source dir."""
    source_dir = Path(source_dir)
    return sorted(
        path
        for path in source_dir.glob("*.jsonl")
        if path.is_file()
    )


def _relative_trace_path(path: Path, source_dir: Path) -> str:
    try:
        return path.relative_to(source_dir).as_posix()
    except ValueError:
        return str(path)


def _count_target_block_types(samples: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in samples:
        for block in sample.target_blocks:
            counts[block.block_type] = counts.get(block.block_type, 0) + 1
    return counts


def build_claude_api_sft_dataset(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    strict: bool = True,
    include_incomplete: bool = False,
    continue_on_error: bool = False,
) -> ClaudeApiSFTDatasetBuildResult:
    """Export a batch Claude API trace directory as conservative SFT dataset."""
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    session_files = discover_claude_gateway_session_files(source_dir)
    samples = []
    failed_files: list[ClaudeApiSFTFailedFile] = []
    notes: list[str] = []

    session_count = 0
    request_count = 0
    extractor_skipped_request_count = 0
    converter_skipped_sample_count = 0
    error_request_count = 0
    incomplete_request_count = 0
    no_trainable_target_count = 0
    model_counts: dict[str, int] = {}
    stop_reason_counts: dict[str, int] = {}

    for session_file in session_files:
        relative_trace_path = _relative_trace_path(session_file, source_dir)
        try:
            session = read_claude_api_session(
                session_file,
                strict=strict,
            )
        except Exception as exc:
            if not continue_on_error:
                raise
            failed_files.append(
                ClaudeApiSFTFailedFile(
                    path=relative_trace_path,
                    stage="load",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        try:
            extracted = extract_claude_session(
                session,
                include_incomplete=include_incomplete,
            )
            extracted.metadata["source_trace_path"] = str(session_file)
        except Exception as exc:
            if not continue_on_error:
                raise
            failed_files.append(
                ClaudeApiSFTFailedFile(
                    path=relative_trace_path,
                    stage="extract",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        session_count += 1
        request_count += extracted.metadata.get("message_request_count", len(extracted.samples))
        extractor_skipped_request_count += len(extracted.skipped_request_ids)
        error_request_count += int(extracted.metadata.get("error_request_count", 0))
        incomplete_request_count += int(extracted.metadata.get("incomplete_request_count", 0))

        for extracted_sample in extracted.samples:
            try:
                sample = build_claude_api_sft_sample(
                    extracted_sample,
                    source_trace_path=relative_trace_path,
                )
            except Exception as exc:
                if not continue_on_error:
                    raise
                converter_skipped_sample_count += 1
                failed_files.append(
                    ClaudeApiSFTFailedFile(
                        path=relative_trace_path,
                        stage="convert",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            if sample is None:
                converter_skipped_sample_count += 1
                if extracted_sample.error is not None:
                    continue
                no_trainable_target_count += 1
                continue

            samples.append(sample)
            model = sample.metadata.get("model")
            if isinstance(model, str) and model:
                model_counts[model] = model_counts.get(model, 0) + 1
            stop_reason = sample.metadata.get("stop_reason")
            if isinstance(stop_reason, str) and stop_reason:
                stop_reason_counts[stop_reason] = stop_reason_counts.get(stop_reason, 0) + 1

    train_path = output_dir / "train.jsonl"
    write_claude_api_sft_jsonl(samples, train_path)

    split_counts = {"train": len(samples)}
    present_splits = ["train"]
    target_block_type_counts = _count_target_block_types(samples)

    manifest = {
        "dataset_type": "claude_api_sft",
        "version": 1,
        "source_dir": str(source_dir),
        "sample_count": len(samples),
        "session_count": session_count,
        "request_count": request_count,
        "extractor_skipped_request_count": extractor_skipped_request_count,
        "converter_skipped_sample_count": converter_skipped_sample_count,
        "error_request_count": error_request_count,
        "incomplete_request_count": incomplete_request_count,
        "no_trainable_target_count": no_trainable_target_count,
        "failed_files": [item.model_dump(mode="json") for item in failed_files],
        "loss_mask_policy": "assistant_selected_blocks_only",
        "present_splits": present_splits,
        "canonical_sample_input": "train.jsonl",
        "notes": notes,
    }
    split_metrics = {
        "version": 1,
        "split_counts": split_counts,
        "session_count": session_count,
        "request_count": request_count,
        "extractor_skipped_request_count": extractor_skipped_request_count,
        "converter_skipped_sample_count": converter_skipped_sample_count,
        "error_request_count": error_request_count,
        "incomplete_request_count": incomplete_request_count,
        "no_trainable_target_count": no_trainable_target_count,
        "model_counts": model_counts,
        "stop_reason_counts": stop_reason_counts,
        "target_block_type_counts": target_block_type_counts,
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

    return ClaudeApiSFTDatasetBuildResult(
        output_dir=str(output_dir),
        source_dir=str(source_dir),
        session_count=session_count,
        request_count=request_count,
        sample_count=len(samples),
        extractor_skipped_request_count=extractor_skipped_request_count,
        converter_skipped_sample_count=converter_skipped_sample_count,
        error_request_count=error_request_count,
        incomplete_request_count=incomplete_request_count,
        no_trainable_target_count=no_trainable_target_count,
        failed_files=failed_files,
        dataset_manifest_path=str(dataset_manifest_path),
        split_metrics_path=str(split_metrics_path),
        present_splits=present_splits,
        notes=notes,
    )
