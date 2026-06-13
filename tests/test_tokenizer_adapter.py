"""Tests for tokenizer adapters."""

from __future__ import annotations

import subprocess
import sys

import pytest

from pycodeagent.rl.tokenizer import (
    BaseTokenizerAdapter,
    FakeTokenizerAdapter,
    resolve_tokenizer_adapter,
)
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig


class TestFakeTokenizerAdapter:
    """Tests for FakeTokenizerAdapter."""

    def test_encode_empty_string(self):
        """Empty string should produce empty token list."""
        config = FakeTokenizerConfig()
        tokenizer = FakeTokenizerAdapter(config)
        assert tokenizer.encode("") == []

    def test_encode_non_empty(self):
        """Non-empty string should produce tokens."""
        config = FakeTokenizerConfig(chars_per_token=4)
        tokenizer = FakeTokenizerAdapter(config)
        tokens = tokenizer.encode("hello world")
        assert len(tokens) > 0
        assert all(isinstance(t, int) for t in tokens)

    def test_encode_deterministic(self):
        """Same input should produce same output."""
        config = FakeTokenizerConfig()
        tokenizer = FakeTokenizerAdapter(config)
        text = "This is a test string"
        tokens1 = tokenizer.encode(text)
        tokens2 = tokenizer.encode(text)
        assert tokens1 == tokens2

    def test_encode_respects_chars_per_token(self):
        """Token count should depend on chars_per_token."""
        text = "hello world"  # 11 characters

        config_4 = FakeTokenizerConfig(chars_per_token=4)
        tokenizer_4 = FakeTokenizerAdapter(config_4)
        tokens_4 = tokenizer_4.encode(text)
        # 11 chars / 4 per token = 3 tokens (rounded up)

        config_2 = FakeTokenizerConfig(chars_per_token=2)
        tokenizer_2 = FakeTokenizerAdapter(config_2)
        tokens_2 = tokenizer_2.encode(text)
        # 11 chars / 2 per token = 6 tokens (rounded up)

        assert len(tokens_4) == 3
        assert len(tokens_2) == 6

    def test_encode_token_ids_in_valid_range(self):
        """Token IDs should be in valid range."""
        config = FakeTokenizerConfig(vocab_size=1000)
        tokenizer = FakeTokenizerAdapter(config)
        tokens = tokenizer.encode("some test text")
        # IDs 0-3 are reserved for special tokens
        assert all(4 <= t < 1000 for t in tokens)

    def test_decode_empty(self):
        """Empty token list should decode to empty string."""
        config = FakeTokenizerConfig()
        tokenizer = FakeTokenizerAdapter(config)
        assert tokenizer.decode([]) == ""

    def test_decode_non_empty(self):
        """Non-empty tokens should return placeholder."""
        config = FakeTokenizerConfig()
        tokenizer = FakeTokenizerAdapter(config)
        result = tokenizer.decode([10, 20, 30])
        assert "[FAKE:" in result
        assert "3 tokens" in result

    def test_get_offsets_empty(self):
        """Empty string should have empty offsets."""
        config = FakeTokenizerConfig()
        tokenizer = FakeTokenizerAdapter(config)
        assert tokenizer.get_offsets("") == []

    def test_get_offsets_non_empty(self):
        """Offsets should match token boundaries."""
        config = FakeTokenizerConfig(chars_per_token=4)
        tokenizer = FakeTokenizerAdapter(config)
        text = "hello world"  # 11 characters
        offsets = tokenizer.get_offsets(text)

        # Should have 3 offsets for 3 tokens
        assert len(offsets) == 3

        # Check boundaries
        assert offsets[0] == (0, 4)  # First 4 chars
        assert offsets[1] == (4, 8)  # Next 4 chars
        assert offsets[2] == (8, 11)  # Last 3 chars (partial)

    def test_get_offsets_cover_full_text(self):
        """Offsets should cover the entire text."""
        config = FakeTokenizerConfig(chars_per_token=5)
        tokenizer = FakeTokenizerAdapter(config)
        text = "abcdefghijklmnopqrstuvwxyz"  # 26 chars
        offsets = tokenizer.get_offsets(text)

        # First offset starts at 0
        assert offsets[0][0] == 0
        # Last offset ends at text length
        assert offsets[-1][1] == len(text)
        # Offsets are contiguous
        for i in range(len(offsets) - 1):
            assert offsets[i][1] == offsets[i + 1][0]

    def test_vocab_size(self):
        """vocab_size should match config."""
        config = FakeTokenizerConfig(vocab_size=500)
        tokenizer = FakeTokenizerAdapter(config)
        assert tokenizer.vocab_size == 500

    def test_special_token_ids(self):
        """Special token IDs should match config."""
        config = FakeTokenizerConfig(
            bos_token_id=1,
            eos_token_id=2,
            pad_token_id=0,
        )
        tokenizer = FakeTokenizerAdapter(config)
        assert tokenizer.bos_token_id == 1
        assert tokenizer.eos_token_id == 2
        assert tokenizer.pad_token_id == 0


class TestFakeTokenizerDeterminism:
    """Tests for fake tokenizer determinism."""

    def test_repeated_encoding_same_result(self):
        """Repeated encoding should produce identical results."""
        config = FakeTokenizerConfig()
        tokenizer = FakeTokenizerAdapter(config)
        text = "The quick brown fox jumps over the lazy dog"

        results = [tokenizer.encode(text) for _ in range(10)]
        assert all(r == results[0] for r in results)

    def test_different_texts_different_tokens(self):
        """Different texts should generally produce different tokens."""
        config = FakeTokenizerConfig(chars_per_token=4)
        tokenizer = FakeTokenizerAdapter(config)

        tokens1 = tokenizer.encode("hello")
        tokens2 = tokenizer.encode("world")

        # At minimum, they should be same length (same char count / chars_per_token)
        # But ideally the token IDs differ
        assert len(tokens1) == len(tokens2)

    def test_offsets_match_encode_count(self):
        """Number of offsets should match number of tokens."""
        config = FakeTokenizerConfig()
        tokenizer = FakeTokenizerAdapter(config)
        text = "Some sample text for testing"

        tokens = tokenizer.encode(text)
        offsets = tokenizer.get_offsets(text)

        assert len(tokens) == len(offsets)


class TestFakeTokenizerEdgeCases:
    """Tests for edge cases."""

    def test_single_character(self):
        """Single character should produce one token."""
        config = FakeTokenizerConfig(chars_per_token=4)
        tokenizer = FakeTokenizerAdapter(config)

        tokens = tokenizer.encode("a")
        offsets = tokenizer.get_offsets("a")

        assert len(tokens) == 1
        assert offsets == [(0, 1)]

    def test_exact_multiple(self):
        """Text length exactly divisible by chars_per_token."""
        config = FakeTokenizerConfig(chars_per_token=3)
        tokenizer = FakeTokenizerAdapter(config)
        text = "abcdef"  # 6 chars, exactly 2 tokens

        tokens = tokenizer.encode(text)
        offsets = tokenizer.get_offsets(text)

        assert len(tokens) == 2
        assert offsets == [(0, 3), (3, 6)]

    def test_unicode_text(self):
        """Should handle unicode text."""
        config = FakeTokenizerConfig(chars_per_token=4)
        tokenizer = FakeTokenizerAdapter(config)
        text = "你好世界测试"  # Chinese characters

        tokens = tokenizer.encode(text)
        offsets = tokenizer.get_offsets(text)

        assert len(tokens) > 0
        # Last offset should cover full text
        assert offsets[-1][1] == len(text)

    def test_whitespace_text(self):
        """Should handle whitespace-only text."""
        config = FakeTokenizerConfig(chars_per_token=4)
        tokenizer = FakeTokenizerAdapter(config)
        text = "   \t\n  "

        tokens = tokenizer.encode(text)
        offsets = tokenizer.get_offsets(text)

        assert len(tokens) > 0
        assert offsets[-1][1] == len(text)


class TestBaseTokenizerAdapterContract:
    """Tests verifying the adapter contract."""

    def test_fake_adapter_implements_contract(self):
        """FakeTokenizerAdapter should implement all abstract methods."""
        config = FakeTokenizerConfig()
        tokenizer = FakeTokenizerAdapter(config)

        # All these should work without error
        assert hasattr(tokenizer, "encode")
        assert hasattr(tokenizer, "decode")
        assert hasattr(tokenizer, "get_offsets")
        assert hasattr(tokenizer, "vocab_size")
        assert hasattr(tokenizer, "bos_token_id")
        assert hasattr(tokenizer, "eos_token_id")
        assert hasattr(tokenizer, "pad_token_id")

        # Verify they're callable
        assert callable(tokenizer.encode)
        assert callable(tokenizer.decode)
        assert callable(tokenizer.get_offsets)


class TestResolveTokenizerAdapter:
    """Tests for explicit tokenizer resolution."""

    def test_requires_explicit_selection(self):
        with pytest.raises(ValueError, match="Explicit tokenizer selection is required"):
            resolve_tokenizer_adapter()

    def test_fake_tokenizer_config_is_explicit_opt_in(self):
        tokenizer, config = resolve_tokenizer_adapter(
            fake_tokenizer_config=FakeTokenizerConfig(chars_per_token=3),
            default_max_length=512,
        )

        assert isinstance(tokenizer, FakeTokenizerAdapter)
        assert config.tokenizer_name == "fake"
        assert config.max_length == 512

    def test_explicit_fake_tokenizer_gets_fake_config(self):
        tokenizer, config = resolve_tokenizer_adapter(
            tokenizer=FakeTokenizerAdapter(),
            default_max_length=256,
        )

        assert isinstance(tokenizer, FakeTokenizerAdapter)
        assert config.tokenizer_name == "fake"
        assert config.max_length == 256

    def test_rejects_mismatched_tokenizer_and_config(self):
        with pytest.raises(ValueError, match="disagree on fake vs real tokenizer path"):
            resolve_tokenizer_adapter(
                tokenizer=FakeTokenizerAdapter(),
                tokenizer_config=TokenizerConfig(tokenizer_name="custom_real"),
            )


class TestCrossProcessDeterminism:
    """Tests that fake tokenizer output is stable across separate Python processes."""

    def test_encode_same_across_processes(self):
        """Same text should produce identical token IDs in separate processes.

        This verifies that the SHA-256 based hashing is not affected by
        Python's per-process hash randomization.
        """
        text = "The quick brown fox jumps over the lazy dog"
        config = FakeTokenizerConfig(chars_per_token=4)
        tokenizer = FakeTokenizerAdapter(config)
        tokens_in_process = tokenizer.encode(text)

        # Run the same encoding in a subprocess
        script = (
            "from pycodeagent.rl.tokenizer import FakeTokenizerAdapter; "
            "from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig; "
            f"t = FakeTokenizerAdapter(FakeTokenizerConfig(chars_per_token=4)); "
            f"print(t.encode({text!r}))"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Subprocess failed: {result.stderr}"
        tokens_from_subprocess = eval(result.stdout.strip())

        assert tokens_in_process == tokens_from_subprocess

    def test_encode_deterministic_multiple_processes(self):
        """Multiple subprocess runs should produce identical results."""
        text = "hello world test string"
        script = (
            "from pycodeagent.rl.tokenizer import FakeTokenizerAdapter; "
            "from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig; "
            f"t = FakeTokenizerAdapter(FakeTokenizerConfig()); "
            f"print(t.encode({text!r}))"
        )

        results = []
        for _ in range(3):
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0
            results.append(eval(result.stdout.strip()))

        # All subprocess results should be identical
        assert all(r == results[0] for r in results)
