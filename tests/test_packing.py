"""Tests for sequence packing."""

from __future__ import annotations

import pytest

from pycodeagent.rl.packing import PackedBatch, PackedSequence, pack_examples, unpack_sequence
from pycodeagent.rl.tensorize import TokenizedExample
from pycodeagent.rl.tokenizer_config import IGNORE_INDEX


def make_example(
    length: int,
    trainable: bool = True,
    metadata: dict | None = None,
) -> TokenizedExample:
    """Create a TokenizedExample with the specified length.

    Args:
        length: Number of tokens
        trainable: Whether all tokens are trainable
        metadata: Optional metadata

    Returns:
        TokenizedExample
    """
    input_ids = list(range(100, 100 + length))
    attention_mask = [1] * length
    train_mask = [1 if trainable else 0] * length
    labels = input_ids if trainable else [IGNORE_INDEX] * length

    return TokenizedExample(
        input_ids=input_ids,
        attention_mask=attention_mask,
        labels=labels,
        token_train_mask=train_mask,
        metadata=metadata or {"task_id": f"task_{length}"},
    )


class TestPackExamples:
    """Tests for pack_examples."""

    def test_empty_input(self):
        """Empty list should produce empty batch."""
        batch = pack_examples([], max_length=100)
        assert batch.num_sequences == 0
        assert batch.total_examples == 0

    def test_single_example_fits(self):
        """Single example that fits should be in one sequence."""
        example = make_example(10)
        batch = pack_examples([example], max_length=100)

        assert batch.num_sequences == 1
        assert batch.total_examples == 1
        assert batch.sequences[0].length == 10

    def test_multiple_examples_fit(self):
        """Multiple examples that fit together should be packed."""
        examples = [make_example(30), make_example(30), make_example(30)]
        batch = pack_examples(examples, max_length=100)

        assert batch.num_sequences == 1
        assert batch.total_examples == 3
        assert batch.sequences[0].length == 90

    def test_examples_exceed_max_length(self):
        """Examples that don't fit should start a new sequence."""
        examples = [make_example(60), make_example(60)]
        batch = pack_examples(examples, max_length=100)

        assert batch.num_sequences == 2
        assert batch.total_examples == 2

    def test_exact_fit(self):
        """Examples that exactly fill max_length."""
        examples = [make_example(50), make_example(50)]
        batch = pack_examples(examples, max_length=100)

        assert batch.num_sequences == 1
        assert batch.sequences[0].length == 100

    def test_oversized_example(self):
        """Example exceeding max_length should be in its own truncated sequence."""
        example = make_example(200)
        batch = pack_examples([example], max_length=100)

        assert batch.num_sequences == 1
        assert batch.sequences[0].length == 100
        assert batch.sequences[0].metadata.get("truncated") is True
        assert batch.stats["num_oversized"] == 1

    def test_mixed_sizes(self):
        """Mix of different sized examples."""
        examples = [
            make_example(20),  # Fits with next
            make_example(30),  # Fits with previous
            make_example(80),  # New sequence
            make_example(10),  # Could fit with previous? No, 80+10=90 ≤ 100, yes
        ]
        batch = pack_examples(examples, max_length=100)

        # First two (50) pack together
        # Third (80) + fourth (10) = 90, pack together
        assert batch.num_sequences == 2

    def test_max_length_respected(self):
        """No packed sequence should exceed max_length."""
        examples = [make_example(40), make_example(40), make_example(40)]
        batch = pack_examples(examples, max_length=100)

        for seq in batch.sequences:
            assert seq.length <= 100


class TestPackedSequenceFields:
    """Tests for PackedSequence field correctness."""

    def test_input_ids_preserved(self):
        """Input IDs should be preserved correctly."""
        ex1 = make_example(5, metadata={"task_id": "a"})
        ex2 = make_example(3, metadata={"task_id": "b"})

        batch = pack_examples([ex1, ex2], max_length=100)
        seq = batch.sequences[0]

        # First 5 tokens should match ex1
        assert seq.input_ids[:5] == ex1.input_ids
        # Next 3 tokens should match ex2
        assert seq.input_ids[5:8] == ex2.input_ids

    def test_labels_preserved(self):
        """Labels should be preserved correctly."""
        ex1 = make_example(5, trainable=True)
        ex2 = make_example(3, trainable=False)

        batch = pack_examples([ex1, ex2], max_length=100)
        seq = batch.sequences[0]

        # First 5 labels should be trainable
        assert seq.labels[:5] == ex1.labels
        # Next 3 labels should be IGNORE_INDEX
        assert seq.labels[5:8] == ex2.labels

    def test_attention_mask_preserved(self):
        """Attention masks should be all 1s for real tokens."""
        ex1 = make_example(5)
        ex2 = make_example(3)

        batch = pack_examples([ex1, ex2], max_length=100)
        seq = batch.sequences[0]

        assert all(m == 1 for m in seq.attention_mask)

    def test_source_indices(self):
        """Source indices should correctly map tokens to examples."""
        ex1 = make_example(5)
        ex2 = make_example(3)

        batch = pack_examples([ex1, ex2], max_length=100)
        seq = batch.sequences[0]

        # First 5 tokens from source 0, next 3 from source 1
        assert seq.source_indices[:5] == [0, 0, 0, 0, 0]
        assert seq.source_indices[5:8] == [1, 1, 1]

    def test_source_spans(self):
        """Source spans should correctly record positions."""
        ex1 = make_example(5, metadata={"task_id": "task_1"})
        ex2 = make_example(3, metadata={"task_id": "task_2"})

        batch = pack_examples([ex1, ex2], max_length=100)
        seq = batch.sequences[0]

        assert len(seq.source_spans) == 2
        assert seq.source_spans[0]["start"] == 0
        assert seq.source_spans[0]["length"] == 5
        assert seq.source_spans[0]["metadata"]["task_id"] == "task_1"
        assert seq.source_spans[1]["start"] == 5
        assert seq.source_spans[1]["length"] == 3
        assert seq.source_spans[1]["metadata"]["task_id"] == "task_2"


class TestUnpackSequence:
    """Tests for unpack_sequence."""

    def test_roundtrip(self):
        """Packing then unpacking should recover original examples."""
        examples = [
            make_example(5, trainable=True, metadata={"task_id": "a"}),
            make_example(3, trainable=False, metadata={"task_id": "b"}),
        ]

        batch = pack_examples(examples, max_length=100)
        seq = batch.sequences[0]
        unpacked = unpack_sequence(seq)

        assert len(unpacked) == 2
        assert unpacked[0].input_ids == examples[0].input_ids
        assert unpacked[0].labels == examples[0].labels
        assert unpacked[1].input_ids == examples[1].input_ids
        assert unpacked[1].labels == examples[1].labels

    def test_metadata_preserved(self):
        """Metadata should survive pack/unpack roundtrip."""
        examples = [
            make_example(5, metadata={"task_id": "x", "reward": 1.0}),
        ]

        batch = pack_examples(examples, max_length=100)
        unpacked = unpack_sequence(batch.sequences[0])

        assert unpacked[0].metadata["task_id"] == "x"
        assert unpacked[0].metadata["reward"] == 1.0


class TestPackedBatchStats:
    """Tests for packing statistics."""

    def test_stats_populated(self):
        """Stats should be populated."""
        examples = [make_example(10), make_example(20)]
        batch = pack_examples(examples, max_length=100)

        assert "num_packed" in batch.stats
        assert "total_tokens" in batch.stats
        assert "utilization" in batch.stats

    def test_utilization(self):
        """Utilization should be tokens / (sequences * max_length)."""
        examples = [make_example(50)]
        batch = pack_examples(examples, max_length=100)

        # 50 tokens in 1 sequence of max_length 100 = 0.5 utilization
        assert batch.stats["utilization"] == 0.5

    def test_full_utilization(self):
        """Full utilization when sequences are exactly max_length."""
        examples = [make_example(50), make_example(50)]
        batch = pack_examples(examples, max_length=100)

        assert batch.stats["utilization"] == 1.0


class TestEdgeCases:
    """Edge case tests for packing."""

    def test_single_token_examples(self):
        """Single-token examples should pack correctly."""
        examples = [make_example(1) for _ in range(10)]
        batch = pack_examples(examples, max_length=100)

        # All 10 should fit in one sequence
        assert batch.num_sequences == 1
        assert batch.sequences[0].length == 10

    def test_max_length_1(self):
        """max_length=1 with single-token examples."""
        examples = [make_example(1) for _ in range(3)]
        batch = pack_examples(examples, max_length=1)

        # Each example in its own sequence
        assert batch.num_sequences == 3

    def test_all_oversized(self):
        """All examples exceed max_length."""
        examples = [make_example(200), make_example(300)]
        batch = pack_examples(examples, max_length=100)

        # Each truncated to max_length in its own sequence
        assert batch.num_sequences == 2
        assert batch.stats["num_oversized"] == 2

    def test_packed_sequence_num_sources(self):
        """num_sources should count source examples."""
        examples = [make_example(10), make_example(10), make_example(10)]
        batch = pack_examples(examples, max_length=100)

        assert batch.sequences[0].num_sources == 3


class TestIntegration:
    """Integration smoke test: build sample -> tokenize -> pack."""

    def test_end_to_end(self):
        """Full pipeline from sample to packed batch."""
        from pycodeagent.rl.tensorize import tensorize_text
        from pycodeagent.rl.tokenizer import FakeTokenizerAdapter
        from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig

        # Create multiple samples with masks matching text length
        text1 = "system prompt user task assistant response"
        text2 = "system prompt user task assistant tool_call"

        # Last 10 chars are trainable
        samples_data = [
            (text1, [0] * (len(text1) - 10) + [1] * 10),
            (text2, [0] * (len(text2) - 10) + [1] * 10),
        ]

        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=4))
        config = TokenizerConfig(tokenizer_name="fake", max_length=100)

        # Tensorize each sample
        examples = []
        for text, mask in samples_data:
            example = tensorize_text(text, mask, tokenizer, config, metadata={"idx": len(examples)})
            examples.append(example)

        # Pack
        batch = pack_examples(examples, max_length=100)

        # Verify consistency
        assert batch.total_examples == 2
        for seq in batch.sequences:
            assert len(seq.input_ids) == len(seq.labels)
            assert len(seq.input_ids) == len(seq.attention_mask)
            assert len(seq.input_ids) == len(seq.token_train_mask)
            assert len(seq.input_ids) == len(seq.source_indices)
            assert seq.length <= 100

    def test_end_to_end_with_truncation(self):
        """Pipeline with truncation."""
        from pycodeagent.rl.tensorize import tensorize_text
        from pycodeagent.rl.tokenizer import FakeTokenizerAdapter
        from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig

        text = "a" * 200  # 200 chars
        mask = [1] * 200

        tokenizer = FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=4))
        config = TokenizerConfig(tokenizer_name="fake", max_length=20)

        example = tensorize_text(text, mask, tokenizer, config)
        # 200/4=50 tokens, truncated to 20
        assert len(example.input_ids) == 20

        batch = pack_examples([example], max_length=30)
        assert batch.num_sequences == 1
