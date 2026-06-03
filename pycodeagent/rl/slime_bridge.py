"""Bridge prepared pycodeagent rollouts into slime-compatible train samples.

This module keeps the conversion logic independent of the slime runtime so it
can be validated with fast unit tests. The slime-side wrapper only needs to
turn the returned records into ``slime.utils.types.Sample`` objects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.rl.mask_alignment import (
    align_character_mask_to_tokens,
    validate_character_mask_length,
    validate_token_alignment_lengths,
)
from pycodeagent.rl.slime_rollout import SlimeRolloutRecord
from pycodeagent.rl.tensorize import TokenizedExample
from pycodeagent.rl.tokenizer import BaseTokenizerAdapter
from pycodeagent.rl.tokenizer_config import TokenizerConfig

TOKENIZED_JSONL_FILENAMES = ("smoke_tokenized.jsonl", "tokenized.jsonl")


class PreparedRolloutBundle(BaseModel):
    """Resolved prepared-rollout bundle metadata."""

    source_path: str
    rollouts_path: str
    tokenizer_config_path: str | None = None
    rollouts: list[SlimeRolloutRecord] = Field(default_factory=list)


class SlimeTrainSample(BaseModel):
    """Tokenizer-aligned sample ready to be wrapped as a slime Sample."""

    task_id: str
    tool_profile_id: str
    tokens: list[int]
    response_length: int
    loss_mask: list[int]
    reward: float
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    train_metadata: dict[str, Any] = Field(default_factory=dict)


def load_prepared_rollout_bundle(path: str | Path) -> PreparedRolloutBundle:
    """Load prepared rollouts from a dataset directory or rollouts JSONL path."""
    path = Path(path)
    if path.is_dir():
        rollouts_path = path / "rollouts.jsonl"
        tokenizer_config_path = path / "tokenizer_config.yaml"
    elif path.is_file():
        rollouts_path = path
        tokenizer_config_path = path.parent / "tokenizer_config.yaml"
    else:
        raise FileNotFoundError(f"Prepared rollout path does not exist: {path}")

    if not rollouts_path.exists():
        raise FileNotFoundError(f"Missing rollouts.jsonl: {rollouts_path}")

    rollouts = _load_rollouts_jsonl(rollouts_path)
    return PreparedRolloutBundle(
        source_path=str(path),
        rollouts_path=str(rollouts_path),
        tokenizer_config_path=(
            str(tokenizer_config_path) if tokenizer_config_path.exists() else None
        ),
        rollouts=rollouts,
    )


def load_bundle_tokenizer_config(path: str | Path) -> TokenizerConfig | None:
    """Load tokenizer config adjacent to a prepared rollout bundle when present."""
    bundle = load_prepared_rollout_bundle(path)
    if bundle.tokenizer_config_path is None:
        return None
    return TokenizerConfig.load(bundle.tokenizer_config_path)


def map_run_status_to_slime_status(status: str) -> str:
    """Map pycodeagent run statuses onto slime's Sample.Status values."""
    if status == "completed":
        return "completed"
    if status in {"failed", "error", "timeout"}:
        return "failed"
    return "pending"


def rollout_to_slime_train_sample(
    rollout: SlimeRolloutRecord,
    tokenizer: BaseTokenizerAdapter,
    *,
    max_length: int | None = None,
) -> SlimeTrainSample:
    """Convert one rollout record into a slime-compatible token/loss-mask sample."""
    validate_character_mask_length(rollout.text, rollout.character_mask)

    token_ids = tokenizer.encode(rollout.text)
    offsets = tokenizer.get_offsets(rollout.text)
    token_train_mask = align_character_mask_to_tokens(rollout.character_mask, offsets)

    validate_token_alignment_lengths(token_ids, token_train_mask)

    if max_length is not None and len(token_ids) > max_length:
        token_ids = token_ids[:max_length]
        token_train_mask = token_train_mask[:max_length]

    if not token_ids:
        raise ValueError(f"Rollout {rollout.task_id} produced no tokens")

    try:
        first_trainable_index = next(
            i for i, trainable in enumerate(token_train_mask) if trainable == 1
        )
    except StopIteration as exc:
        raise ValueError(
            f"Rollout {rollout.task_id} has no trainable tokens after tokenization"
        ) from exc

    response_length = len(token_ids) - first_trainable_index
    loss_mask = token_train_mask[first_trainable_index:]
    if response_length <= 0 or not loss_mask:
        raise ValueError(
            f"Rollout {rollout.task_id} produced invalid response window: "
            f"{response_length=}"
        )

    trainable_token_count = sum(token_train_mask)
    metadata = dict(rollout.metadata)
    metadata.update(
        {
            "task_id": rollout.task_id,
            "tool_profile_id": rollout.tool_profile_id,
            "verifier_passed": rollout.verifier_passed,
            "verifier_score": rollout.verifier_score,
            "raw_reward": rollout.reward,
            "trainable_char_count": rollout.trainable_char_count,
            "total_char_count": rollout.total_char_count,
            "trainable_token_count": trainable_token_count,
            "total_token_count": len(token_ids),
            "prompt_token_count": first_trainable_index,
        }
    )
    train_metadata = {
        "task_id": rollout.task_id,
        "tool_profile_id": rollout.tool_profile_id,
        "reward": rollout.reward,
        "status": rollout.status,
        "verifier_passed": rollout.verifier_passed,
        "verifier_score": rollout.verifier_score,
        "trainable_token_count": trainable_token_count,
    }

    return SlimeTrainSample(
        task_id=rollout.task_id,
        tool_profile_id=rollout.tool_profile_id,
        tokens=token_ids,
        response_length=response_length,
        loss_mask=loss_mask,
        reward=rollout.reward,
        status=map_run_status_to_slime_status(rollout.status),
        metadata=metadata,
        train_metadata=train_metadata,
    )


def tokenized_example_to_slime_train_sample(
    example: TokenizedExample,
) -> SlimeTrainSample:
    """Convert an already-tokenized training example into a slime sample payload."""
    validate_token_alignment_lengths(example.input_ids, example.token_train_mask)
    _validate_optional_tokenized_lengths(example)

    if not example.input_ids:
        raise ValueError("Tokenized example produced no tokens")

    try:
        first_trainable_index = next(
            i for i, trainable in enumerate(example.token_train_mask) if trainable == 1
        )
    except StopIteration as exc:
        sample_label = (
            example.metadata.get("sample_id")
            or example.metadata.get("task_id")
            or "<unknown>"
        )
        raise ValueError(
            f"Tokenized example {sample_label} has no trainable tokens"
        ) from exc

    response_length = len(example.input_ids) - first_trainable_index
    loss_mask = example.token_train_mask[first_trainable_index:]
    if response_length <= 0 or not loss_mask:
        raise ValueError(
            "Tokenized example produced invalid response window: "
            f"{response_length=}"
        )

    metadata = dict(example.metadata)
    task_id = str(metadata.get("task_id") or metadata.get("sample_id") or "")
    tool_profile_id = str(
        metadata.get("tool_profile_id") or metadata.get("target_profile_id") or ""
    )
    trainable_token_count = sum(example.token_train_mask)
    metadata.update(
        {
            "task_id": task_id,
            "tool_profile_id": tool_profile_id,
            "trainable_token_count": trainable_token_count,
            "total_token_count": len(example.input_ids),
            "prompt_token_count": first_trainable_index,
        }
    )
    train_metadata = {
        "task_id": task_id,
        "tool_profile_id": tool_profile_id,
        "reward": 0.0,
        "status": "completed",
        "trainable_token_count": trainable_token_count,
    }
    for key in ("sample_id", "source_type"):
        if key in metadata:
            train_metadata[key] = metadata[key]

    return SlimeTrainSample(
        task_id=task_id,
        tool_profile_id=tool_profile_id,
        tokens=list(example.input_ids),
        response_length=response_length,
        loss_mask=loss_mask,
        reward=0.0,
        status="completed",
        metadata=metadata,
        train_metadata=train_metadata,
    )


def build_slime_train_samples(
    path: str | Path,
    tokenizer: BaseTokenizerAdapter,
    *,
    max_length: int | None = None,
) -> list[SlimeTrainSample]:
    """Load a prepared rollout bundle and convert every rollout."""
    bundle = load_prepared_rollout_bundle(path)
    return [
        rollout_to_slime_train_sample(rollout, tokenizer, max_length=max_length)
        for rollout in bundle.rollouts
    ]


def build_tokenized_slime_train_samples(path: str | Path) -> list[SlimeTrainSample]:
    """Load tokenized JSONL input and convert each record to a slime train sample."""
    tokenized_path = resolve_tokenized_jsonl_path(path)
    examples = _load_tokenized_examples_jsonl(tokenized_path)
    return [tokenized_example_to_slime_train_sample(example) for example in examples]


def is_tokenized_training_path(path: str | Path) -> bool:
    """Return whether a path should be consumed as tokenized JSONL input."""
    path = Path(path)
    if path.is_dir():
        if (path / "rollouts.jsonl").exists():
            return False
        return any((path / name).exists() for name in TOKENIZED_JSONL_FILENAMES)
    if not path.is_file():
        return False
    if path.name in TOKENIZED_JSONL_FILENAMES:
        return True
    return _jsonl_looks_tokenized(path)


def resolve_tokenized_jsonl_path(path: str | Path) -> Path:
    """Resolve a tokenized JSONL file from a direct file or prepared directory."""
    path = Path(path)
    if path.is_file():
        if path.name in TOKENIZED_JSONL_FILENAMES or _jsonl_looks_tokenized(path):
            return path
        raise ValueError(f"Path is not a tokenized JSONL file: {path}")
    if not path.is_dir():
        raise FileNotFoundError(f"Tokenized training path does not exist: {path}")

    for filename in TOKENIZED_JSONL_FILENAMES:
        tokenized_path = path / filename
        if tokenized_path.exists():
            return tokenized_path
    raise FileNotFoundError(
        f"Missing tokenized JSONL in {path}; expected one of "
        f"{', '.join(TOKENIZED_JSONL_FILENAMES)}"
    )


def _load_rollouts_jsonl(path: Path) -> list[SlimeRolloutRecord]:
    rollouts: list[SlimeRolloutRecord] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rollouts.append(SlimeRolloutRecord.model_validate(json.loads(line)))
    return rollouts


def _load_tokenized_examples_jsonl(path: Path) -> list[TokenizedExample]:
    examples: list[TokenizedExample] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            examples.append(TokenizedExample.model_validate(json.loads(line)))
    return examples


def _jsonl_looks_tokenized(path: Path) -> bool:
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                return False
            return isinstance(data, dict) and {
                "input_ids",
                "token_train_mask",
            }.issubset(data)
    return False


def _validate_optional_tokenized_lengths(example: TokenizedExample) -> None:
    expected_length = len(example.input_ids)
    if len(example.attention_mask) != expected_length:
        raise ValueError(
            "Tokenized example attention_mask length does not match input_ids: "
            f"{len(example.attention_mask)} != {expected_length}"
        )
    if len(example.labels) != expected_length:
        raise ValueError(
            "Tokenized example labels length does not match input_ids: "
            f"{len(example.labels)} != {expected_length}"
        )
