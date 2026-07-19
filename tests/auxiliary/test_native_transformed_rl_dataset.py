"""Tests for native-transformed RL prompt dataset infrastructure."""

from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.auxiliary.claude_api.sft import (
    ClaudeApiSFTMessage,
    ClaudeApiSFTSample,
    ClaudeApiSFTTargetBlock,
    ClaudeApiSFTToolCallTarget,
)
from pycodeagent.auxiliary.claude_api.sft_dataset_io import write_claude_api_sft_jsonl
from pycodeagent.auxiliary.native_transformed.rl_dataset import (
    build_native_transformed_rl_prompt_sample,
    export_native_transformed_rl_dataset,
    read_native_transformed_rl_jsonl,
    render_native_transformed_rl_prompt_text,
    write_native_transformed_rl_jsonl,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "native_transformed_rl_dataset"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _make_sample(
    sample_id: str = "sample_1",
    *,
    mode: str = "name_only",
    tool_name: str = "InspectFile",
    arguments: dict | None = None,
    with_tool_use: bool = True,
) -> ClaudeApiSFTSample:
    target_blocks: list[ClaudeApiSFTTargetBlock]
    if with_tool_use:
        target_blocks = [
            ClaudeApiSFTTargetBlock(
                block_type="tool_use",
                tool_call=ClaudeApiSFTToolCallTarget(
                    call_id=f"call_{sample_id}",
                    name=tool_name,
                    arguments=arguments or {"file_path": "README.md"},
                ),
                metadata={"index": 0},
            )
        ]
    else:
        target_blocks = [
            ClaudeApiSFTTargetBlock(block_type="text", text="Done.", metadata={"index": 0})
        ]

    return ClaudeApiSFTSample(
        sample_id=sample_id,
        sample_type="claude_api_sft",
        source_type="claude_api_trace",
        task_id=f"task_{sample_id}",
        tool_profile_id=f"profile_{mode}",
        messages=[
            ClaudeApiSFTMessage(role="system", content="You are a coding agent."),
            ClaudeApiSFTMessage(role="user", content="Inspect README.md."),
        ],
        tool_specs=[
            {
                "name": tool_name,
                "description": "Read a file.",
                "input_schema": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            }
        ],
        target_blocks=target_blocks,
        loss_mask_policy="assistant_selected_blocks_only",
        metadata={
            "transformation_mode": mode,
            "source_catalog_id": "catalog",
            "base_profile_id": "base",
            "target_profile_id": f"profile_{mode}",
            "source_trace_path": "trace.jsonl",
        },
    )


class TestNativeTransformedRLDataset:
    def test_build_prompt_sample_keeps_reference_out_of_prompt(self) -> None:
        source = _make_sample(arguments={"file_path": "SECRET_TARGET.md"})

        sample = build_native_transformed_rl_prompt_sample(source)

        assert sample is not None
        assert sample.sample_type == "native_transformed_rl_prompt"
        assert sample.source_type == "native_transformed_claude_api_sft"
        assert sample.messages == source.messages
        assert sample.tool_specs == source.tool_specs
        assert sample.reward_reference.expected_tool_calls[0].name == "InspectFile"
        assert sample.reward_reference.expected_tool_calls[0].arguments == {
            "file_path": "SECRET_TARGET.md"
        }
        prompt_text = render_native_transformed_rl_prompt_text(sample)
        assert "<|tool|>" not in prompt_text
        assert "SECRET_TARGET.md" not in prompt_text
        assert "InspectFile" in prompt_text  # Tool specs remain visible.

    def test_text_only_target_is_not_exported_as_rl_prompt(self) -> None:
        assert build_native_transformed_rl_prompt_sample(
            _make_sample(with_tool_use=False)
        ) is None

    def test_jsonl_roundtrip_preserves_prompt_sample(self) -> None:
        tmp = _get_test_dir()
        try:
            sample = build_native_transformed_rl_prompt_sample(_make_sample())
            assert sample is not None
            path = tmp / "rl_prompts.jsonl"

            write_native_transformed_rl_jsonl([sample], path)
            loaded = read_native_transformed_rl_jsonl(path)

            assert len(loaded) == 1
            assert loaded[0].model_dump(mode="json") == sample.model_dump(mode="json")
        finally:
            _cleanup(tmp)

    def test_export_writes_prompts_manifest_and_metrics(self) -> None:
        tmp = _get_test_dir()
        try:
            source_dir = tmp / "sft"
            output_dir = tmp / "rl"
            write_claude_api_sft_jsonl(
                [
                    _make_sample("keep_base", mode="base", tool_name="Read"),
                    _make_sample("keep_name", mode="name_only", tool_name="InspectFile"),
                    _make_sample("drop_text", with_tool_use=False),
                ],
                source_dir / "train.jsonl",
            )

            result = export_native_transformed_rl_dataset(source_dir, output_dir)

            assert result.input_sample_count == 3
            assert result.sample_count == 2
            assert result.skipped_no_tool_use_count == 1
            assert result.mode_counts == {"base": 1, "name_only": 1}
            assert result.tool_name_counts == {"Read": 1, "InspectFile": 1}
            prompts = read_native_transformed_rl_jsonl(result.prompt_data_path)
            assert [sample.sample_id for sample in prompts] == ["keep_base", "keep_name"]

            manifest = json.loads((output_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
            metrics = json.loads((output_dir / "split_metrics.json").read_text(encoding="utf-8"))
            assert manifest["dataset_type"] == "native_transformed_rl_prompt"
            assert manifest["primary_sample_input"] == "train/rl_prompts.jsonl"
            assert metrics["split_counts"] == {"train": 2}
            assert metrics["skipped_no_tool_use_count"] == 1
        finally:
            _cleanup(tmp)
