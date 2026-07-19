"""Auxiliary RL prompt dataset contract for native-transformed samples."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from pycodeagent.auxiliary.claude_api.sft import (
    ClaudeApiSFTMessage,
    ClaudeApiSFTSample,
)
from pycodeagent.auxiliary.claude_api.sft_dataset_io import read_claude_api_sft_jsonl
from pycodeagent.auxiliary.claude_api.serializer import serialize_claude_api_sft_sample


class NativeTransformedExpectedToolCall(BaseModel):
    """One expected assistant tool call retained as reward reference."""

    call_id: str
    name: str
    arguments: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class NativeTransformedRewardReference(BaseModel):
    """Reference data used by RL reward evaluators, never by model prompts."""

    reference_type: Literal["tool_call_exact"] = "tool_call_exact"
    expected_tool_calls: list[NativeTransformedExpectedToolCall] = Field(min_length=1)
    target_block_count: int
    target_text_block_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class NativeTransformedRLPromptSample(BaseModel):
    """Prompt-only RL sample derived from a native-transformed SFT sample."""

    sample_id: str
    sample_type: Literal["native_transformed_rl_prompt"] = "native_transformed_rl_prompt"
    source_type: Literal["native_transformed_claude_api_sft"] = (
        "native_transformed_claude_api_sft"
    )
    task_id: str
    tool_profile_id: str
    messages: list[ClaudeApiSFTMessage] = Field(min_length=1)
    tool_specs: list[dict[str, Any]] = Field(default_factory=list)
    reward_reference: NativeTransformedRewardReference
    metadata: dict[str, Any] = Field(default_factory=dict)


class NativeTransformedRLDatasetBuildResult(BaseModel):
    """Summary of one native-transformed RL prompt dataset export."""

    output_dir: str
    source_path: str
    input_sample_count: int
    sample_count: int
    skipped_no_tool_use_count: int
    dataset_manifest_path: str
    split_metrics_path: str
    prompt_data_path: str
    mode_counts: dict[str, int] = Field(default_factory=dict)
    tool_name_counts: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


def build_native_transformed_rl_prompt_sample(
    sample: ClaudeApiSFTSample,
) -> NativeTransformedRLPromptSample | None:
    """Derive one prompt-only RL sample from a canonical SFT sample."""
    expected_tool_calls = [
        NativeTransformedExpectedToolCall(
            call_id=block.tool_call.call_id,
            name=block.tool_call.name,
            arguments=dict(block.tool_call.arguments),
            metadata=dict(block.metadata),
        )
        for block in sample.target_blocks
        if block.block_type == "tool_use" and block.tool_call is not None
    ]
    if not expected_tool_calls:
        return None

    text_block_count = sum(1 for block in sample.target_blocks if block.block_type == "text")
    metadata = _build_prompt_metadata(sample)
    return NativeTransformedRLPromptSample(
        sample_id=sample.sample_id,
        task_id=sample.task_id,
        tool_profile_id=sample.tool_profile_id,
        messages=[
            ClaudeApiSFTMessage.model_validate(message.model_dump(mode="json"))
            for message in sample.messages
        ],
        tool_specs=[dict(tool_spec) for tool_spec in sample.tool_specs],
        reward_reference=NativeTransformedRewardReference(
            expected_tool_calls=expected_tool_calls,
            target_block_count=len(sample.target_blocks),
            target_text_block_count=text_block_count,
            metadata={
                "source_sample_type": sample.sample_type,
                "source_loss_mask_policy": sample.loss_mask_policy,
            },
        ),
        metadata=metadata,
    )


def render_native_transformed_rl_prompt_text(
    sample: NativeTransformedRLPromptSample,
) -> str:
    """Render the non-trainable prompt text for one RL prompt sample."""
    placeholder = ClaudeApiSFTSample(
        sample_id=sample.sample_id,
        sample_type="claude_api_sft",
        source_type="claude_api_trace",
        task_id=sample.task_id,
        tool_profile_id=sample.tool_profile_id,
        messages=sample.messages,
        tool_specs=sample.tool_specs,
        target_blocks=[
            {
                "block_type": "tool_use",
                "tool_call": {
                    "call_id": expected.call_id,
                    "name": expected.name,
                    "arguments": expected.arguments,
                },
            }
            for expected in sample.reward_reference.expected_tool_calls
        ],
        loss_mask_policy="assistant_selected_blocks_only",
        metadata=dict(sample.metadata),
    )
    serialized = serialize_claude_api_sft_sample(placeholder)
    return "".join(segment.text for segment in serialized.segments if not segment.trainable)


def write_native_transformed_rl_jsonl(
    samples: list[NativeTransformedRLPromptSample],
    path: str | Path,
) -> None:
    """Write RL prompt samples to deterministic JSONL."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(
                json.dumps(
                    sample.model_dump(mode="json"),
                    sort_keys=True,
                    ensure_ascii=False,
                )
            )
            handle.write("\n")


def read_native_transformed_rl_jsonl(
    path: str | Path,
) -> list[NativeTransformedRLPromptSample]:
    """Read and validate native-transformed RL prompt samples from JSONL."""
    path = Path(path)
    samples: list[NativeTransformedRLPromptSample] = []
    with open(path, encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_no} of {path}: {exc}") from exc
            try:
                samples.append(NativeTransformedRLPromptSample.model_validate(payload))
            except Exception as exc:
                raise ValueError(
                    f"Invalid native-transformed RL sample on line {line_no} of {path}: {exc}"
                ) from exc
    return samples


def export_native_transformed_rl_dataset(
    source_path: str | Path,
    output_dir: str | Path,
) -> NativeTransformedRLDatasetBuildResult:
    """Export RL prompt samples from a native-transformed SFT dataset file or dir."""
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    input_path = source_path / "train.jsonl" if source_path.is_dir() else source_path
    sft_samples = read_claude_api_sft_jsonl(input_path)

    rl_samples: list[NativeTransformedRLPromptSample] = []
    skipped_no_tool_use_count = 0
    mode_counts: dict[str, int] = {}
    tool_name_counts: dict[str, int] = {}

    for sft_sample in sft_samples:
        rl_sample = build_native_transformed_rl_prompt_sample(sft_sample)
        if rl_sample is None:
            skipped_no_tool_use_count += 1
            continue
        rl_samples.append(rl_sample)
        mode = rl_sample.metadata.get("transformation_mode")
        if isinstance(mode, str) and mode:
            _increment(mode_counts, mode)
        for expected in rl_sample.reward_reference.expected_tool_calls:
            _increment(tool_name_counts, expected.name)

    prompt_data_path = output_dir / "train" / "rl_prompts.jsonl"
    write_native_transformed_rl_jsonl(rl_samples, prompt_data_path)

    notes = [
        "RL prompts contain only context messages and tool specs; target blocks are retained only in reward_reference.",
        "First version exports only samples with at least one tool_use target.",
    ]
    manifest = {
        "dataset_type": "native_transformed_rl_prompt",
        "version": 1,
        "source_path": str(source_path),
        "input_path": str(input_path),
        "sample_count": len(rl_samples),
        "input_sample_count": len(sft_samples),
        "primary_sample_input": "train/rl_prompts.jsonl",
        "present_splits": ["train"],
        "notes": notes,
    }
    split_metrics = {
        "version": 1,
        "split_counts": {"train": len(rl_samples)},
        "input_sample_count": len(sft_samples),
        "skipped_no_tool_use_count": skipped_no_tool_use_count,
        "mode_counts": mode_counts,
        "tool_name_counts": tool_name_counts,
    }
    dataset_manifest_path = output_dir / "dataset_manifest.json"
    split_metrics_path = output_dir / "split_metrics.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    split_metrics_path.write_text(
        json.dumps(split_metrics, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )

    return NativeTransformedRLDatasetBuildResult(
        output_dir=str(output_dir),
        source_path=str(source_path),
        input_sample_count=len(sft_samples),
        sample_count=len(rl_samples),
        skipped_no_tool_use_count=skipped_no_tool_use_count,
        dataset_manifest_path=str(dataset_manifest_path),
        split_metrics_path=str(split_metrics_path),
        prompt_data_path=str(prompt_data_path),
        mode_counts=mode_counts,
        tool_name_counts=tool_name_counts,
        notes=notes,
    )


def _build_prompt_metadata(sample: ClaudeApiSFTSample) -> dict[str, Any]:
    metadata = dict(sample.metadata)
    metadata.update(
        {
            "source_sample_id": sample.sample_id,
            "source_sample_type": sample.sample_type,
            "source_type": "native_transformed_claude_api_sft",
            "task_id": sample.task_id,
            "tool_profile_id": sample.tool_profile_id,
        }
    )
    return metadata


def _increment(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1
