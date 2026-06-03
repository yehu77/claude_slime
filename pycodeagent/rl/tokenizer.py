"""Tokenizer adapter layer for tokenization.

Provides a narrow, stable internal contract for tokenization that:
- Wraps real tokenizer interfaces when available
- Is testable without external downloads in unit tests
- Is deterministic (same input -> same output)

Two main adapters:
- BaseTokenizerAdapter: Abstract interface
- FakeTokenizerAdapter: Deterministic fake for tests
- HFTokenizerAdapter: Real HuggingFace tokenizer (optional, requires transformers)
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig


class BaseTokenizerAdapter(ABC):
    """Abstract base class for tokenizer adapters.

    Defines the minimal contract needed for tensorization.
    All implementations must be deterministic.
    """

    @abstractmethod
    def encode(self, text: str) -> list[int]:
        """Encode text to a list of token IDs.

        Args:
            text: The text to encode

        Returns:
            List of token IDs
        """
        ...

    @abstractmethod
    def decode(self, token_ids: list[int]) -> str:
        """Decode token IDs back to text.

        Args:
            token_ids: List of token IDs

        Returns:
            Decoded text string
        """
        ...

    @abstractmethod
    def get_offsets(self, text: str) -> list[tuple[int, int]]:
        """Get character offsets for each token.

        Returns the (start, end) character position for each token.
        Essential for aligning character-level masks to token-level masks.

        Args:
            text: The text to tokenize

        Returns:
            List of (start, end) tuples, one per token
        """
        ...

    @property
    @abstractmethod
    def vocab_size(self) -> int:
        """Size of the vocabulary."""
        ...

    @property
    @abstractmethod
    def bos_token_id(self) -> int | None:
        """BOS token ID, or None if not defined."""
        ...

    @property
    @abstractmethod
    def eos_token_id(self) -> int | None:
        """EOS token ID, or None if not defined."""
        ...

    @property
    @abstractmethod
    def pad_token_id(self) -> int | None:
        """PAD token ID, or None if not defined."""
        ...


class FakeTokenizerAdapter(BaseTokenizerAdapter):
    """Deterministic fake tokenizer for testing.

    Does not require any model downloads or network access.
    Uses a simple hash-based encoding that is:
    - Deterministic (same text -> same tokens)
    - Reproducible across runs
    - Supports offset calculation

    Tokenization strategy:
    - Split text into chunks of `chars_per_token` characters
    - Hash each chunk to a token ID in range [4, vocab_size)
    - Reserve IDs 0-3 for special tokens (PAD, BOS, EOS, UNK)

    This is NOT a real tokenizer - it's only for testing.
    """

    def __init__(self, config: FakeTokenizerConfig | None = None) -> None:
        """Initialize the fake tokenizer.

        Args:
            config: Configuration for the fake tokenizer
        """
        self._config = config or FakeTokenizerConfig()

    def encode(self, text: str) -> list[int]:
        """Encode text using simple chunking and hashing.

        Uses SHA-256 for cross-process deterministic hashing.

        Args:
            text: The text to encode

        Returns:
            List of token IDs
        """
        if not text:
            return []

        token_ids: list[int] = []
        chars_per_token = self._config.chars_per_token
        vocab_size = self._config.vocab_size

        # Reserve 4 special token IDs (0-3)
        usable_vocab = vocab_size - 4

        # Split text into chunks
        for i in range(0, len(text), chars_per_token):
            chunk = text[i : i + chars_per_token]
            # Deterministic SHA-256 based token ID (cross-process stable)
            hash_bytes = hashlib.sha256(chunk.encode("utf-8")).digest()
            hash_int = int.from_bytes(hash_bytes[:8], byteorder="big")
            token_id = (hash_int % usable_vocab) + 4
            token_ids.append(token_id)

        return token_ids

    def decode(self, token_ids: list[int]) -> str:
        """Decode token IDs back to text.

        Since this is a fake tokenizer, decode cannot recover the original text.
        Instead, it returns a placeholder representation.

        Args:
            token_ids: List of token IDs

        Returns:
            Placeholder string representation
        """
        if not token_ids:
            return ""
        # Return placeholder since we can't recover original text
        return f"[FAKE:{len(token_ids)} tokens]"

    def get_offsets(self, text: str) -> list[tuple[int, int]]:
        """Get character offsets for each token.

        Args:
            text: The text to tokenize

        Returns:
            List of (start, end) tuples, one per token
        """
        if not text:
            return []

        offsets: list[tuple[int, int]] = []
        chars_per_token = self._config.chars_per_token

        for i in range(0, len(text), chars_per_token):
            start = i
            end = min(i + chars_per_token, len(text))
            offsets.append((start, end))

        return offsets

    @property
    def vocab_size(self) -> int:
        """Size of the vocabulary."""
        return self._config.vocab_size

    @property
    def bos_token_id(self) -> int | None:
        """BOS token ID."""
        return self._config.bos_token_id

    @property
    def eos_token_id(self) -> int | None:
        """EOS token ID."""
        return self._config.eos_token_id

    @property
    def pad_token_id(self) -> int | None:
        """PAD token ID."""
        return self._config.pad_token_id


class HFTokenizerAdapter(BaseTokenizerAdapter):
    """HuggingFace tokenizer adapter for real tokenization.

    Requires the `transformers` library to be installed.
    This adapter wraps a real HuggingFace tokenizer and provides
    the BaseTokenizerAdapter interface.

    Note: This is provided for convenience but is optional.
    Tests should use FakeTokenizerAdapter instead.
    """

    def __init__(self, tokenizer_name: str) -> None:
        """Initialize with a HuggingFace tokenizer name.

        Args:
            tokenizer_name: Name or path of the tokenizer

        Raises:
            ImportError: If transformers is not installed
        """
        try:
            from transformers import AutoTokenizer
        except ImportError as e:
            raise ImportError(
                "transformers is required for HFTokenizerAdapter. "
                "Install with: pip install transformers"
            ) from e

        self._tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)

    def encode(self, text: str) -> list[int]:
        """Encode text using the HuggingFace tokenizer.

        Args:
            text: The text to encode

        Returns:
            List of token IDs
        """
        return self._tokenizer.encode(text, add_special_tokens=False)

    def decode(self, token_ids: list[int]) -> str:
        """Decode token IDs back to text.

        Args:
            token_ids: List of token IDs

        Returns:
            Decoded text string
        """
        return self._tokenizer.decode(token_ids, skip_special_tokens=True)

    def get_offsets(self, text: str) -> list[tuple[int, int]]:
        """Get character offsets for each token.

        Uses the HuggingFace tokenizer's `return_offsets_mapping` feature.

        Args:
            text: The text to tokenize

        Returns:
            List of (start, end) tuples, one per token
        """
        encoding = self._tokenizer(
            text, return_offsets_mapping=True, add_special_tokens=False
        )
        return list(encoding["offset_mapping"])

    @property
    def vocab_size(self) -> int:
        """Size of the vocabulary."""
        return self._tokenizer.vocab_size

    @property
    def bos_token_id(self) -> int | None:
        """BOS token ID."""
        return self._tokenizer.bos_token_id

    @property
    def eos_token_id(self) -> int | None:
        """EOS token ID."""
        return self._tokenizer.eos_token_id

    @property
    def pad_token_id(self) -> int | None:
        """PAD token ID."""
        return self._tokenizer.pad_token_id


def get_tokenizer(config: TokenizerConfig) -> BaseTokenizerAdapter:
    """Get a tokenizer adapter from config.

    Supports both explicit fake-tokenizer configs and real HuggingFace
    tokenizers. Tests should still prefer constructing FakeTokenizerAdapter
    directly when they need tight control over fake-tokenizer settings.

    Args:
        config: Tokenizer configuration

    Returns:
        Tokenizer adapter instance

    Raises:
        ImportError: If transformers is not installed for HF tokenizers
    """
    if config.tokenizer_name == "fake":
        return FakeTokenizerAdapter()
    return HFTokenizerAdapter(config.tokenizer_name)


def resolve_tokenizer_adapter(
    *,
    tokenizer: BaseTokenizerAdapter | None = None,
    tokenizer_config: TokenizerConfig | None = None,
    fake_tokenizer_config: FakeTokenizerConfig | None = None,
    default_max_length: int = 2048,
) -> tuple[BaseTokenizerAdapter, TokenizerConfig]:
    """Resolve an explicit tokenizer path for tensorization/verification.

    This helper intentionally does not silently fall back to a fake tokenizer.
    Callers must provide one of:
    - `tokenizer`
    - `tokenizer_config`
    - `fake_tokenizer_config`
    """
    if tokenizer_config is not None and fake_tokenizer_config is not None:
        if tokenizer_config.tokenizer_name != "fake":
            raise ValueError(
                "fake_tokenizer_config can only be used with tokenizer_name='fake'."
            )

    if tokenizer is None:
        if tokenizer_config is not None:
            if tokenizer_config.tokenizer_name == "fake":
                tokenizer = FakeTokenizerAdapter(fake_tokenizer_config)
            else:
                tokenizer = get_tokenizer(tokenizer_config)
        elif fake_tokenizer_config is not None:
            tokenizer = FakeTokenizerAdapter(fake_tokenizer_config)
        else:
            raise ValueError(
                "Explicit tokenizer selection is required. Provide tokenizer, "
                "tokenizer_config, or fake_tokenizer_config."
            )

    if tokenizer_config is None:
        tokenizer_name = (
            "fake"
            if isinstance(tokenizer, FakeTokenizerAdapter)
            else tokenizer.__class__.__name__
        )
        tokenizer_config = TokenizerConfig(
            tokenizer_name=tokenizer_name,
            max_length=default_max_length,
            truncation=True,
        )

    expects_fake = tokenizer_config.tokenizer_name == "fake"
    is_fake = isinstance(tokenizer, FakeTokenizerAdapter)
    if expects_fake != is_fake:
        raise ValueError(
            "tokenizer and tokenizer_config disagree on fake vs real tokenizer path."
        )
    if fake_tokenizer_config is not None and not expects_fake:
        raise ValueError(
            "fake_tokenizer_config is only valid for the explicit fake tokenizer path."
        )

    return tokenizer, tokenizer_config
