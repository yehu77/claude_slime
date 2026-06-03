"""Structured configuration for tokenizer instantiation.

All important tokenizer knobs live here with explicit defaults.
Deterministic and serializable for reproducibility.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


# Default ignore index for non-trainable tokens (PyTorch convention)
IGNORE_INDEX: int = -100


class TokenizerConfig(BaseModel):
    """Configuration for a tokenizer.

    Attributes:
        tokenizer_name: Name or path for the tokenizer (e.g., "gpt2", "Qwen/Qwen2-0.5B")
        max_length: Maximum sequence length for truncation
        truncation: Whether to truncate sequences exceeding max_length
        padding: Padding strategy ("longest", "max_length", "do_not_pad")
        bos_token_id: Optional explicit BOS token ID override
        eos_token_id: Optional explicit EOS token ID override
        pad_token_id: Optional explicit PAD token ID override
        add_special_tokens: Whether to add special tokens (BOS, EOS) during encoding
        metadata: Arbitrary metadata for logging/tracking
    """

    tokenizer_name: str
    max_length: int = 2048
    truncation: bool = True
    padding: str = "do_not_pad"
    bos_token_id: int | None = None
    eos_token_id: int | None = None
    pad_token_id: int | None = None
    add_special_tokens: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    def save(self, path: Path | str) -> None:
        """Save config to a YAML file.

        Args:
            path: Path to save the config
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False, sort_keys=False)

    @classmethod
    def load(cls, path: Path | str) -> TokenizerConfig:
        """Load config from a YAML file.

        Args:
            path: Path to load the config from

        Returns:
            TokenizerConfig instance
        """
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    def model_dump_yaml(self) -> str:
        """Serialize config to YAML string.

        Returns:
            YAML string representation
        """
        return yaml.dump(self.model_dump(), default_flow_style=False, sort_keys=False)


class FakeTokenizerConfig(BaseModel):
    """Configuration for the fake tokenizer used in tests.

    Provides deterministic tokenization without requiring model downloads.

    Attributes:
        vocab_size: Size of the vocabulary
        bos_token_id: BOS token ID
        eos_token_id: EOS token ID
        pad_token_id: PAD token ID
        unk_token_id: UNK token ID
        chars_per_token: Simulated characters per token (for offset calculation)
    """

    vocab_size: int = 1000
    bos_token_id: int = 1
    eos_token_id: int = 2
    pad_token_id: int = 0
    unk_token_id: int = 3
    chars_per_token: int = 4
