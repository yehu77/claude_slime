"""Tests for tensorization."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from pycodeagent.rl.tensorize import TokenizedExample, tensorize_sample, tensorize_text
from pycodeagent.rl.tokenizer import FakeTokenizerAdapter
from pycodeagent.rl.tokenizer_config import IGNORE_INDEX, FakeTokenizerConfig, TokenizerConfig


@dataclass
class MockTrainingSample:
    """Mock TrainingSample for testing."""

    text: str
    character_mask: list[int]
    task_id: str
    tool_profile_id: str
    reward: float
    status: str
    verifier_passed: bool
    verifier_score: float
    trainable_char_count: int


def make_sample(
    text: str,
    trainable_ranges: list[tuple[int, int]] | None = None,
) -> MockTrainingSample:
    """Create a mock sample with specified trainable ranges.

    Args:
        text: The text
        trainable_ranges: List of (start, end) ranges that are trainable.
                         If None, all characters are trainable.

    Returns:
        MockTrainingSample
    """
    if trainable_ranges is None:
        character_mask = [1] * len(text)
    else:
        character_mask = [0] * len(text)
        for start, end in trainable_ranges:
            for i in range(start, end):
                character_mask[i] = 1

    trainable_count = sum(character_mask)

    return MockTrainingSample(
        text=text,
        character_mask=character_mask,
        task_id="test_task",
        tool_profile_id="test_profile",
        reward=1.0,
        status="completed",
        verifier_passed=True,
        verifier_score=1.0,
        trainable_char_count=trainable_count,
    )


class TestTokenizedExample:
    """Tests for TokenizedExample."""

    def test_length_property(self):
        """length property should return input_ids length."""
        example = TokenizedExample(
            input_ids=[1, 2, 3, 4, 5],
            attention_mask=[1, 1, 1, 1, 1],
            labels=[1, 2, -100, 4, 5],
            token_train_mask=[1, 1, 0, 1, 1],
            metadata={},
        )
        assert example.length == 5

    def test_trainable_token_count(self):
        """trainable_token_count should sum token_train_mask."""
        example = TokenizedExample(
            input_ids=[1, 2, 3, 4, 5],
            attention_mask=[1, 1, 1, 1, 1],
            labels=[1, 2, -100, 4, 5],
            token_train_mask=[1, 1, 0, 1, 1],
            metadata={},
        )
        assert example.trainable_token_count == 4


class TestTensorizeText:
    """Tests for tensorize_text."""

    def test_all_trainable(self):
        """All-trainable text should have all-trainable tokens."""
        text = "hello world"
        character_mask = [1] * len(text)

        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=4))
        config = TokenizerConfig(tokenizer_name="fake", max_length=100)

        example = tensorize_text(text, character_mask, tokenizer, config)

        # All tokens should be trainable
        assert all(m == 1 for m in example.token_train_mask)
        # All labels should equal input_ids
        assert example.labels == example.input_ids
        # Attention mask should be all 1s
        assert all(m == 1 for m in example.attention_mask)

    def test_none_trainable(self):
        """None-trainable text should have all-ignored labels."""
        text = "hello world"
        character_mask = [0] * len(text)

        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=4))
        config = TokenizerConfig(tokenizer_name="fake", max_length=100)

        example = tensorize_text(text, character_mask, tokenizer, config)

        # All tokens should be non-trainable
        assert all(m == 0 for m in example.token_train_mask)
        # All labels should be IGNORE_INDEX
        assert all(l == IGNORE_INDEX for l in example.labels)

    def test_partial_trainable_boundary_token(self):
        """Token covering both trainable and non-trainable chars should be trainable.

        This tests the "any-character" policy.
        """
        # Create text where trainable chars are in the middle
        text = "AAAABBBBCCCC"  # 12 chars total
        # Make only middle 4 chars trainable (positions 4-7)
        character_mask = [0, 0, 0, 0, 1, 1, 1, 1, 0, 0, 0, 0]

        # Use 4 chars per token, so we have 3 tokens:
        # Token 0: chars 0-3 (not trainable)
        # Token 1: chars 4-7 (trainable)
        # Token 2: chars 8-11 (not trainable)
        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=4))
        config = TokenizerConfig(tokenizer_name="fake", max_length=100)

        example = tensorize_text(text, character_mask, tokenizer, config)

        assert len(example.input_ids) == 3
        assert example.token_train_mask == [0, 1, 0]
        assert example.labels[0] == IGNORE_INDEX
        assert example.labels[1] == example.input_ids[1]
        assert example.labels[2] == IGNORE_INDEX

    def test_boundary_token_any_policy(self):
        """Test that a token spanning trainable/non-trainable is marked trainable."""
        # Create a boundary case where a token spans both
        text = "AAAAABBBBB"  # 10 chars
        # First 5 trainable, last 5 not
        character_mask = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]

        # 4 chars per token:
        # Token 0: chars 0-3 (all trainable -> trainable)
        # Token 1: chars 4-7 (mixed) -> trainable (any policy)
        # Token 2: chars 8-9 (not trainable) -> not trainable
        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=4))
        config = TokenizerConfig(tokenizer_name="fake", max_length=100)

        example = tensorize_text(text, character_mask, tokenizer, config)

        assert example.token_train_mask == [1, 1, 0]

    def test_truncation(self):
        """Truncation should respect max_length."""
        text = "a" * 100  # 100 chars
        character_mask = [1] * 100

        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=4))
        # 100 chars / 4 = 25 tokens
        config = TokenizerConfig(tokenizer_name="fake", max_length=10, truncation=True)

        example = tensorize_text(text, character_mask, tokenizer, config)

        assert len(example.input_ids) == 10
        assert len(example.labels) == 10
        assert len(example.attention_mask) == 10

    def test_no_truncation(self):
        """No truncation should preserve all tokens."""
        text = "a" * 100
        character_mask = [1] * 100

        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=4))
        config = TokenizerConfig(tokenizer_name="fake", max_length=10, truncation=False)

        example = tensorize_text(text, character_mask, tokenizer, config)

        # Should have 25 tokens (100 chars / 4)
        assert len(example.input_ids) == 25

    def test_empty_text(self):
        """Empty text should produce empty example."""
        text = ""
        character_mask = []

        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig())
        config = TokenizerConfig(tokenizer_name="fake", max_length=100)

        example = tensorize_text(text, character_mask, tokenizer, config)

        assert example.input_ids == []
        assert example.labels == []
        assert example.attention_mask == []

    def test_metadata_preserved(self):
        """Metadata should be preserved."""
        text = "hello"
        character_mask = [1] * len(text)

        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig())
        config = TokenizerConfig(tokenizer_name="fake", max_length=100)
        metadata = {"task_id": "test_001", "custom": "value"}

        example = tensorize_text(text, character_mask, tokenizer, config, metadata=metadata)

        assert example.metadata == metadata

    def test_deterministic(self):
        """Same input should produce same output."""
        text = "The quick brown fox"
        character_mask = [1] * len(text)

        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig())
        config = TokenizerConfig(tokenizer_name="fake", max_length=100)

        example1 = tensorize_text(text, character_mask, tokenizer, config)
        example2 = tensorize_text(text, character_mask, tokenizer, config)

        assert example1.input_ids == example2.input_ids
        assert example1.labels == example2.labels


class TestTensorizeSample:
    """Tests for tensorize_sample."""

    def test_minimal_sample(self):
        """Should tensorize a minimal sample."""
        sample = make_sample("hello world")

        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=4))
        config = TokenizerConfig(tokenizer_name="fake", max_length=100)

        example = tensorize_sample(sample, tokenizer, config)

        assert len(example.input_ids) > 0
        assert example.length == len(example.input_ids)
        assert example.metadata["task_id"] == "test_task"

    def test_partial_trainable_sample(self):
        """Should handle partially trainable sample."""
        text = "system prompt user task assistant response"
        # Only "assistant response" is trainable (last 19 chars)
        trainable_start = len(text) - 19
        sample = make_sample(
            text,
            trainable_ranges=[(trainable_start, len(text))],
        )

        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=4))
        config = TokenizerConfig(tokenizer_name="fake", max_length=100)

        example = tensorize_sample(sample, tokenizer, config)

        # Last few tokens should be trainable, earlier ones not
        assert any(m == 1 for m in example.token_train_mask)
        assert any(m == 0 for m in example.token_train_mask)

    def test_metadata_preserved(self):
        """Sample metadata should be preserved in example."""
        sample = make_sample("test text")
        sample.task_id = "my_task_001"
        sample.tool_profile_id = "profile_v2"
        sample.reward = 0.75

        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig())
        config = TokenizerConfig(tokenizer_name="fake", max_length=100)

        example = tensorize_sample(sample, tokenizer, config)

        assert example.metadata["task_id"] == "my_task_001"
        assert example.metadata["tool_profile_id"] == "profile_v2"
        assert example.metadata["reward"] == 0.75


class TestMaskAlignment:
    """Tests for mask alignment semantics."""

    def test_mask_length_matches_text(self):
        """Character mask length must match text length."""
        text = "hello"
        character_mask = [1, 1, 1]  # Wrong length

        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig())
        config = TokenizerConfig(tokenizer_name="fake", max_length=100)

        with pytest.raises(ValueError, match="Character mask length"):
            tensorize_text(text, character_mask, tokenizer, config)

    def test_token_mask_length_matches_input_ids(self):
        """Token mask length should match input_ids length."""
        text = "hello world"
        character_mask = [1] * len(text)

        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=3))
        config = TokenizerConfig(tokenizer_name="fake", max_length=100)

        example = tensorize_text(text, character_mask, tokenizer, config)

        assert len(example.token_train_mask) == len(example.input_ids)
        assert len(example.labels) == len(example.input_ids)
        assert len(example.attention_mask) == len(example.input_ids)

    def test_labels_use_ignore_index(self):
        """Non-trainable tokens should use IGNORE_INDEX for labels."""
        text = "AAAAABBBBB"
        character_mask = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]

        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=5))
        config = TokenizerConfig(tokenizer_name="fake", max_length=100)

        example = tensorize_text(text, character_mask, tokenizer, config)

        # First token trainable, second not
        assert example.labels[0] == example.input_ids[0]
        assert example.labels[1] == IGNORE_INDEX
