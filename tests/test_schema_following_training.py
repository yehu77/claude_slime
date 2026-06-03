"""Tests for schema-following serialization and training preparation primitives."""

from __future__ import annotations

from pycodeagent.rl.schema_following import (
    CanonicalToolIntent,
    ExposedToolCallTarget,
    SchemaFollowingMessage,
    SchemaFollowingSample,
)
from pycodeagent.rl.schema_following_training import (
    build_schema_following_prepared_sample,
)
from pycodeagent.rl.serializer import serialize_schema_following_sample
from pycodeagent.rl.tensorize import tensorize_schema_following_sample
from pycodeagent.rl.tokenizer import FakeTokenizerAdapter
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig


def make_schema_sample() -> SchemaFollowingSample:
    target = ExposedToolCallTarget(
        call_id="call_1",
        name="inspect_file",
        arguments={"path": "src/app.py"},
    )
    return SchemaFollowingSample(
        sample_id="sf__sample__001",
        sample_type="schema_following",
        source_type="synthetic",
        split="train",
        task_id="task_001",
        tool_profile_id="schema_only",
        mutation_category="schema_flat_to_nested",
        messages=[
            SchemaFollowingMessage(role="system", content="You are a coding agent."),
            SchemaFollowingMessage(role="user", content="Inspect src/app.py."),
            SchemaFollowingMessage(role="assistant", content="I will inspect that file."),
            SchemaFollowingMessage(
                role="tool",
                content="src/app.py exists",
                metadata={"tool_name": "list_files"},
            ),
        ],
        canonical_intent=CanonicalToolIntent(
            tool="read_file",
            arguments={"path": "src/app.py"},
        ),
        target_tool_call=target,
        target_text=target.render_text(),
        loss_mask_policy="assistant_tool_call_only",
        metadata={"profile_mode": "schema_only"},
    )


class TestSerializeSchemaFollowingSample:
    def test_target_call_is_the_only_trainable_segment(self) -> None:
        sample = make_schema_sample()

        serialized = serialize_schema_following_sample(sample)

        assert serialized.sample_id == sample.sample_id
        assert serialized.text == "".join(segment.text for segment in serialized.segments)
        assert [segment.kind for segment in serialized.segments] == [
            "system",
            "user",
            "assistant",
            "tool",
            "assistant_tool_call",
        ]
        assert [segment.trainable for segment in serialized.segments] == [
            False,
            False,
            False,
            False,
            True,
        ]
        assert serialized.segments[-1].text == sample.target_text

    def test_serialized_metadata_preserves_canonical_and_target_calls(self) -> None:
        sample = make_schema_sample()

        serialized = serialize_schema_following_sample(sample)

        assert serialized.metadata["canonical_intent"] == {
            "tool": "read_file",
            "arguments": {"path": "src/app.py"},
        }
        assert serialized.metadata["target_tool_call"] == {
            "id": "call_1",
            "name": "inspect_file",
            "arguments": {"path": "src/app.py"},
        }


class TestSchemaFollowingPreparedSample:
    def test_prepared_sample_masks_only_tool_call_text(self) -> None:
        sample = make_schema_sample()

        prepared = build_schema_following_prepared_sample(sample)

        assert prepared.trainable_char_count == len(sample.target_text)
        assert sum(prepared.character_mask) == prepared.trainable_char_count
        assert prepared.segments[-1]["kind"] == "assistant_tool_call"
        assert prepared.segments[-1]["trainable"] is True
        assert [segment["trainable"] for segment in prepared.segments[:-1]] == [
            False,
            False,
            False,
            False,
        ]

    def test_tensorize_preserves_schema_following_metadata(self) -> None:
        sample = make_schema_sample()
        prepared = build_schema_following_prepared_sample(sample)

        example = tensorize_schema_following_sample(
            prepared,
            FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=4)),
            TokenizerConfig(tokenizer_name="fake", max_length=128),
        )

        assert example.trainable_token_count > 0
        assert example.metadata["sample_id"] == sample.sample_id
        assert example.metadata["split"] == "train"
        assert example.metadata["mutation_category"] == "schema_flat_to_nested"
        assert example.metadata["loss_mask_policy"] == "assistant_tool_call_only"
        assert example.metadata["canonical_intent"] == {
            "tool": "read_file",
            "arguments": {"path": "src/app.py"},
        }
