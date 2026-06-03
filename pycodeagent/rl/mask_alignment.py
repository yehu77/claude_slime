"""Shared helpers for aligning character-level masks to token offsets."""

from __future__ import annotations


def validate_character_mask_length(text: str, character_mask: list[int]) -> None:
    """Validate that a character mask matches the serialized text length."""
    if len(character_mask) != len(text):
        raise ValueError(
            "Character mask length does not match text length: "
            f"{len(character_mask)} != {len(text)}"
        )


def align_character_mask_to_tokens(
    character_mask: list[int],
    offsets: list[tuple[int, int]],
) -> list[int]:
    """Mark a token trainable when any covered character is trainable."""
    token_mask: list[int] = []

    for start, end in offsets:
        is_trainable = any(
            character_mask[i] for i in range(start, end) if i < len(character_mask)
        )
        token_mask.append(1 if is_trainable else 0)

    return token_mask


def validate_token_alignment_lengths(
    input_ids: list[int],
    token_train_mask: list[int],
) -> None:
    """Validate that token ids and train masks have the same length."""
    if len(input_ids) != len(token_train_mask):
        raise ValueError(
            "Token count mismatch: "
            f"input_ids={len(input_ids)}, token_train_mask={len(token_train_mask)}"
        )
