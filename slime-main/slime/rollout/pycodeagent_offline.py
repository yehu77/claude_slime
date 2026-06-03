"""Offline slime bridge for pycodeagent-prepared training bundles.

Use this when training from ``prepare_slime_training_data.py`` outputs instead
of generating fresh rollouts online.
"""

from __future__ import annotations

import copy
import logging
import os
import random
from functools import lru_cache
from pathlib import Path

import torch

from slime.utils.types import Sample

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_pycodeagent_dependencies():
    """Resolve pycodeagent bridge imports only when the offline bridge is used."""
    try:
        from pycodeagent.rl.slime_bridge import (
            build_slime_train_samples,
            build_tokenized_slime_train_samples,
            is_tokenized_training_path,
        )
        from pycodeagent.rl.tokenizer import HFTokenizerAdapter
        from pycodeagent.rl.tokenizer_config import TokenizerConfig
    except ModuleNotFoundError as exc:
        missing_module = exc.name or ""
        if missing_module.split(".")[0] == "pycodeagent" or "No module named 'pycodeagent'" in str(exc):
            raise ModuleNotFoundError(
                "slime.rollout.pycodeagent_offline requires the pycodeagent package "
                "to be importable. Add the repository root to PYTHONPATH or install "
                "pycodeagent before running offline slime training."
            ) from exc
        raise

    return (
        build_slime_train_samples,
        build_tokenized_slime_train_samples,
        is_tokenized_training_path,
        HFTokenizerAdapter,
        TokenizerConfig,
    )


class PyCodeAgentPreparedDataSource:
    """Read a prepared pycodeagent bundle and serve fixed slime Samples."""

    def __init__(self, args):
        self.args = args
        if self.args.n_samples_per_prompt != 1:
            raise ValueError(
                "PyCodeAgentPreparedDataSource only supports n_samples_per_prompt=1"
            )

        bundle_path = getattr(args, "prompt_data", None)
        if bundle_path is None:
            raise ValueError(
                "PyCodeAgentPreparedDataSource expects --prompt-data to point "
                "to a prepared dataset directory, rollouts.jsonl file, or "
                "tokenized JSONL file"
            )

        (
            build_slime_train_samples,
            build_tokenized_slime_train_samples,
            is_tokenized_training_path,
            HFTokenizerAdapter,
            _,
        ) = _load_pycodeagent_dependencies()
        if is_tokenized_training_path(bundle_path):
            converted_samples = build_tokenized_slime_train_samples(bundle_path)
        else:
            max_length = _resolve_max_length(bundle_path, args)
            tokenizer = HFTokenizerAdapter(args.hf_checkpoint)
            converted_samples = build_slime_train_samples(
                bundle_path,
                tokenizer,
                max_length=max_length,
            )
        if not converted_samples:
            raise ValueError(f"No prepared samples found at {bundle_path}")

        self.templates = [
            Sample(
                prompt="",
                response="",
                tokens=converted.tokens,
                response_length=converted.response_length,
                reward=converted.reward,
                loss_mask=converted.loss_mask,
                status=Sample.Status(converted.status),
                metadata=converted.metadata,
                train_metadata=converted.train_metadata,
            )
            for converted in converted_samples
        ]

        self.epoch_id = 0
        self.sample_group_index = 0
        self.sample_index = 0
        self.sample_offset = 0
        if self.args.rollout_shuffle:
            random.Random(self.args.rollout_seed).shuffle(self.templates)

    def get_samples(self, num_samples: int) -> list[list[Sample]]:
        if num_samples <= 0:
            return []

        selected = self._take_templates(num_samples)
        result: list[list[Sample]] = []
        for template in selected:
            sample = copy.deepcopy(template)
            sample.group_index = self.sample_group_index
            sample.index = self.sample_index
            self.sample_group_index += 1
            self.sample_index += 1
            result.append([sample])
        return result

    def add_samples(self, samples: list[list[Sample]]):
        raise RuntimeError(
            "PyCodeAgentPreparedDataSource is read-only and does not accept new samples"
        )

    def save(self, rollout_id):
        if getattr(self.args, "save", None) is None:
            return
        state_dict = {
            "sample_offset": self.sample_offset,
            "epoch_id": self.epoch_id,
            "sample_group_index": self.sample_group_index,
            "sample_index": self.sample_index,
        }
        path = os.path.join(self.args.save, f"rollout/global_dataset_state_dict_{rollout_id}.pt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save(state_dict, path)

    def load(self, rollout_id=None):
        if getattr(self.args, "load", None) is None:
            return
        path = os.path.join(self.args.load, f"rollout/global_dataset_state_dict_{rollout_id}.pt")
        if not os.path.exists(path):
            logger.info("Offline pycodeagent data source checkpoint does not exist: %s", path)
            return
        state_dict = torch.load(path)
        self.sample_offset = state_dict.get("sample_offset", 0)
        self.epoch_id = state_dict.get("epoch_id", 0)
        self.sample_group_index = state_dict.get("sample_group_index", 0)
        self.sample_index = state_dict.get("sample_index", 0)
        if self.args.rollout_shuffle:
            rng = random.Random(self.args.rollout_seed + self.epoch_id)
            rng.shuffle(self.templates)

    def __len__(self) -> int:
        return len(self.templates)

    def _take_templates(self, num_samples: int) -> list[Sample]:
        selected: list[Sample] = []
        while len(selected) < num_samples:
            if self.sample_offset >= len(self.templates):
                self.epoch_id += 1
                self.sample_offset = 0
                if self.args.rollout_shuffle:
                    rng = random.Random(self.args.rollout_seed + self.epoch_id)
                    rng.shuffle(self.templates)

            remaining = num_samples - len(selected)
            end = min(self.sample_offset + remaining, len(self.templates))
            selected.extend(self.templates[self.sample_offset:end])
            self.sample_offset = end
        return selected


def generate_rollout(args, rollout_id, data_source, evaluation=False):
    """Return fixed offline samples from the prepared pycodeagent bundle."""
    assert not evaluation, "Offline pycodeagent rollout does not support evaluation"
    return data_source.get_samples(args.rollout_batch_size)


def generate_eval_rollout(args, rollout_id, data_source, evaluation=False):
    """Evaluation path is intentionally not implemented for the offline bridge."""
    raise NotImplementedError(
        "Offline pycodeagent bridge does not implement eval rollouts. "
        "Disable eval or provide a separate eval_function_path."
    )


def _resolve_max_length(bundle_path: str, args) -> int | None:
    *_, TokenizerConfig = _load_pycodeagent_dependencies()
    path = Path(bundle_path)
    config_path = path / "tokenizer_config.yaml" if path.is_dir() else path.parent / "tokenizer_config.yaml"
    if config_path.exists():
        return TokenizerConfig.load(config_path).max_length
    return getattr(args, "rollout_max_context_len", None)
