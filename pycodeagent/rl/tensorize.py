"""Tensorization: convert training samples / rollout records into tokenized examples.

Converts the existing character/span-level training data into token-level
tensors suitable for downstream training pipelines.

Mask alignment policy:
- A token is trainable if **any** of its covered characters are trainable.
- Non-trainable tokens get label = IGNORE_INDEX (-100).
- Trainable tokens get label = token_id.

This "any-character" policy ensures that tokens at segment boundaries
(where a token may span trainable and non-trainable characters) are
treated as trainable, avoiding accidental masking of partial signals.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.rl.mask_alignment import (
    align_character_mask_to_tokens,
    validate_character_mask_length,
    validate_token_alignment_lengths,
)
from pycodeagent.rl.schema_following_training import SchemaFollowingPreparedSample
from pycodeagent.rl.tokenizer import BaseTokenizerAdapter
from pycodeagent.rl.tokenizer_config import IGNORE_INDEX, TokenizerConfig


class TokenizedExample(BaseModel):
    """A single tokenized training example.

    Attributes:
        input_ids: Token IDs
        attention_mask: 1 for real tokens, 0 for padding
        labels: Token IDs for trainable positions, IGNORE_INDEX for non-trainable
        token_train_mask: Per-token trainability (1=trainable, 0=not)
        metadata: Preserved metadata from the source sample/rollout
    """

    input_ids: list[int]
    attention_mask: list[int]
    labels: list[int]
    token_train_mask: list[int]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def length(self) -> int:
        """Number of tokens in this example."""
        return len(self.input_ids)

    @property
    def trainable_token_count(self) -> int:
        """Number of trainable tokens."""
        return sum(self.token_train_mask)


def _build_labels(
    input_ids: list[int],
    token_train_mask: list[int],
) -> list[int]:
    """Build labels from input_ids and token-level train mask.

    Trainable tokens keep their token_id as label.
    Non-trainable tokens get IGNORE_INDEX (-100).

    Args:
        input_ids: Token IDs
        token_train_mask: Per-token trainability mask

    Returns:
        Labels list
    """
    return [
        tid if mask == 1 else IGNORE_INDEX
        for tid, mask in zip(input_ids, token_train_mask)
    ]


def tensorize_sample(
    sample: Any,
    tokenizer: BaseTokenizerAdapter,
    config: TokenizerConfig,
) -> TokenizedExample:
    """Convert a TrainingSample into a tokenized example.

    Args:
        sample: TrainingSample with text, character_mask, and metadata
        tokenizer: Tokenizer adapter
        config: Tokenizer configuration

    Returns:
        TokenizedExample with aligned labels and masks
    """
    text = sample.text
    character_mask = sample.character_mask

    # Tokenize
    input_ids = tokenizer.encode(text)
    offsets = tokenizer.get_offsets(text)

    # Align character mask to tokens
    token_train_mask = align_character_mask_to_tokens(character_mask, offsets)

    # Ensure lengths match
    validate_token_alignment_lengths(input_ids, token_train_mask)

    # Apply truncation
    if config.truncation and len(input_ids) > config.max_length:
        input_ids = input_ids[: config.max_length]
        token_train_mask = token_train_mask[: config.max_length]

    # Build labels
    labels = _build_labels(input_ids, token_train_mask)

    # Build attention mask (all 1s for real tokens)
    attention_mask = [1] * len(input_ids)

    # Preserve metadata
    metadata = {
        "task_id": sample.task_id,
        "tool_profile_id": sample.tool_profile_id,
        "reward": sample.reward,
        "status": sample.status,
        "verifier_passed": sample.verifier_passed,
        "verifier_score": sample.verifier_score,
        "trainable_char_count": sample.trainable_char_count,
    }

    return TokenizedExample(
        input_ids=input_ids,
        attention_mask=attention_mask,
        labels=labels,
        token_train_mask=token_train_mask,
        metadata=metadata,
    )


def tensorize_rollout(
    rollout: Any,
    tokenizer: BaseTokenizerAdapter,
    config: TokenizerConfig,
) -> TokenizedExample:
    """Convert a SlimeRolloutRecord into a tokenized example.

    Args:
        rollout: SlimeRolloutRecord with text, character_mask, and metadata
        tokenizer: Tokenizer adapter
        config: Tokenizer configuration

    Returns:
        TokenizedExample with aligned labels and masks
    """
    text = rollout.text
    character_mask = rollout.character_mask

    # Tokenize
    input_ids = tokenizer.encode(text)
    offsets = tokenizer.get_offsets(text)

    # Align character mask to tokens
    token_train_mask = align_character_mask_to_tokens(character_mask, offsets)

    # Ensure lengths match
    validate_token_alignment_lengths(input_ids, token_train_mask)

    # Apply truncation
    if config.truncation and len(input_ids) > config.max_length:
        input_ids = input_ids[: config.max_length]
        token_train_mask = token_train_mask[: config.max_length]

    # Build labels
    labels = _build_labels(input_ids, token_train_mask)

    # Build attention mask
    attention_mask = [1] * len(input_ids)

    # Preserve metadata
    metadata = {
        "task_id": rollout.task_id,
        "tool_profile_id": rollout.tool_profile_id,
        "reward": rollout.reward,
        "status": rollout.status,
        "verifier_passed": rollout.verifier_passed,
        "verifier_score": rollout.verifier_score,
        "trainable_char_count": rollout.trainable_char_count,
    }

    return TokenizedExample(
        input_ids=input_ids,
        attention_mask=attention_mask,
        labels=labels,
        token_train_mask=token_train_mask,
        metadata=metadata,
    )


def tensorize_schema_following_sample(
    sample: SchemaFollowingPreparedSample,
    tokenizer: BaseTokenizerAdapter,
    config: TokenizerConfig,
) -> TokenizedExample:
    """Convert a prepared schema-following sample into a tokenized example."""
    metadata = dict(sample.metadata)
    metadata.update(
        {
            "sample_id": sample.sample_id,
            "sample_type": sample.sample_type,
            "source_type": sample.source_type,
            "split": sample.split,
            "task_id": sample.task_id,
            "tool_profile_id": sample.tool_profile_id,
            "mutation_category": sample.mutation_category,
            "trainable_char_count": sample.trainable_char_count,
            "loss_mask_policy": sample.loss_mask_policy,
        }
    )
    return tensorize_text(
        sample.text,
        sample.character_mask,
        tokenizer,
        config,
        metadata=metadata,
    )


def tensorize_text(
    text: str,
    character_mask: list[int],
    tokenizer: BaseTokenizerAdapter,
    config: TokenizerConfig,
    *,
    metadata: dict[str, Any] | None = None,
) -> TokenizedExample:
    """Convert raw text and character mask into a tokenized example.

    Lower-level API for cases where you have text and a mask
    but not a full sample/rollout object.

    Args:
        text: The text to tokenize
        character_mask: Character-level trainability mask
        tokenizer: Tokenizer adapter
        config: Tokenizer configuration
        metadata: Optional metadata to preserve

    Returns:
        TokenizedExample with aligned labels and masks
    """
    validate_character_mask_length(text, character_mask)

    # Tokenize
    input_ids = tokenizer.encode(text)
    offsets = tokenizer.get_offsets(text)

    # Align character mask to tokens
    token_train_mask = align_character_mask_to_tokens(character_mask, offsets)

    # Ensure lengths match
    validate_token_alignment_lengths(input_ids, token_train_mask)

    # Apply truncation
    if config.truncation and len(input_ids) > config.max_length:
        input_ids = input_ids[: config.max_length]
        token_train_mask = token_train_mask[: config.max_length]

    # Build labels
    labels = _build_labels(input_ids, token_train_mask)

    # Build attention mask
    attention_mask = [1] * len(input_ids)

    return TokenizedExample(
        input_ids=input_ids,
        attention_mask=attention_mask,
        labels=labels,
        token_train_mask=token_train_mask,
        metadata=metadata or {},
    )
