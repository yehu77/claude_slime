"""Native-transformed pycodeagent RL datasource and reward glue for slime."""

from __future__ import annotations

import copy
import logging
import os
import random
from functools import lru_cache
from pathlib import Path
from typing import Any

import torch

from slime.utils.types import Sample

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_pycodeagent_dependencies():
    """Resolve pycodeagent imports only when the RL bridge is used."""
    try:
        from pycodeagent.auxiliary.native_transformed.reward import (
            evaluate_native_transformed_rl_completion,
        )
        from pycodeagent.auxiliary.native_transformed.rl_dataset import (
            NativeTransformedRLPromptSample,
            read_native_transformed_rl_jsonl,
            render_native_transformed_rl_prompt_text,
        )
    except ModuleNotFoundError as exc:
        missing_module = exc.name or ""
        if missing_module.split(".")[0] == "pycodeagent" or "No module named 'pycodeagent'" in str(exc):
            raise ModuleNotFoundError(
                "slime.rollout.pycodeagent_native_rl requires the pycodeagent package "
                "to be importable. Add the repository root to PYTHONPATH or install "
                "pycodeagent before running native RL training."
            ) from exc
        raise

    return (
        NativeTransformedRLPromptSample,
        evaluate_native_transformed_rl_completion,
        read_native_transformed_rl_jsonl,
        render_native_transformed_rl_prompt_text,
    )


class PyCodeAgentNativeRLDataSource:
    """Read native-transformed RL prompt samples and serve slime prompt Samples."""

    def __init__(self, args):
        self.args = args
        if self.args.n_samples_per_prompt < 1:
            raise ValueError(
                "PyCodeAgentNativeRLDataSource requires n_samples_per_prompt>=1"
            )

        prompt_data = getattr(args, "prompt_data", None)
        if prompt_data is None:
            raise ValueError(
                "PyCodeAgentNativeRLDataSource expects --prompt-data to point "
                "to rl_prompts.jsonl or a native-transformed RL dataset directory"
            )

        _, _, read_native_transformed_rl_jsonl, render_prompt = _load_pycodeagent_dependencies()
        prompt_path = _resolve_rl_prompt_path(prompt_data)
        rl_samples = read_native_transformed_rl_jsonl(prompt_path)
        if not rl_samples:
            raise ValueError(f"No native-transformed RL prompt samples found at {prompt_path}")

        self.templates = [
            Sample(
                prompt=render_prompt(rl_sample),
                response="",
                reward=None,
                metadata=_sample_metadata(rl_sample),
                status=Sample.Status.PENDING,
            )
            for rl_sample in rl_samples
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
            group: list[Sample] = []
            for _ in range(self.args.n_samples_per_prompt):
                sample = copy.deepcopy(template)
                sample.group_index = self.sample_group_index
                sample.index = self.sample_index
                self.sample_index += 1
                group.append(sample)
            self.sample_group_index += 1
            result.append(group)
        return result

    def add_samples(self, samples: list[list[Sample]]):
        raise RuntimeError(
            "PyCodeAgentNativeRLDataSource is read-only and does not accept new samples"
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
            logger.info("Native RL data source checkpoint does not exist: %s", path)
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


async def reward_func(args, sample_or_samples, **kwargs):
    """Custom slime RM path for native-transformed RL samples."""
    del args, kwargs
    if isinstance(sample_or_samples, list):
        return [_score_sample(sample) for sample in sample_or_samples]
    return _score_sample(sample_or_samples)


def sample_to_native_rl_reward_case(sample: Sample):
    """Return the structured pycodeagent reward case for one generated sample."""
    NativeTransformedRLPromptSample, evaluate_completion, _, _ = _load_pycodeagent_dependencies()
    metadata = sample.metadata if isinstance(sample.metadata, dict) else {}
    payload = metadata.get("native_transformed_rl_sample")
    if not isinstance(payload, dict):
        raise ValueError(
            "Native RL sample metadata is missing native_transformed_rl_sample"
        )
    rl_sample = NativeTransformedRLPromptSample.model_validate(payload)
    return evaluate_completion(rl_sample, sample.response or "")


def _score_sample(sample: Sample) -> float:
    case = sample_to_native_rl_reward_case(sample)
    sample.metadata = dict(sample.metadata or {})
    sample.metadata["native_transformed_reward"] = _reward_case_summary(case)
    return case.reward


def _resolve_rl_prompt_path(path: str | Path) -> Path:
    path = Path(path)
    if path.is_file():
        return path
    if not path.is_dir():
        raise FileNotFoundError(f"Native RL prompt path does not exist: {path}")
    for relative in ("train/rl_prompts.jsonl", "rl_prompts.jsonl"):
        candidate = path / relative
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Missing rl_prompts.jsonl in {path}; expected train/rl_prompts.jsonl "
        "or rl_prompts.jsonl"
    )


def _sample_metadata(rl_sample) -> dict[str, Any]:
    metadata = dict(rl_sample.metadata)
    metadata.update(
        {
            "sample_id": rl_sample.sample_id,
            "task_id": rl_sample.task_id,
            "tool_profile_id": rl_sample.tool_profile_id,
            "source_type": rl_sample.source_type,
            "reward_reference": rl_sample.reward_reference.model_dump(mode="json"),
            "native_transformed_rl_sample": rl_sample.model_dump(mode="json"),
        }
    )
    return metadata


def _reward_case_summary(case) -> dict[str, Any]:
    return {
        "reward": case.reward,
        "parse_ok": case.parse_ok,
        "tool_name_ok": case.tool_name_ok,
        "arguments_exact_match": case.arguments_exact_match,
        "schema_status": case.schema_status,
        "error_code": case.error_code,
        "reward_breakdown": dict(case.reward_breakdown),
        "predicted_tool_name": case.predicted_tool_name,
        "expected_tool_name": case.expected_tool_name,
    }
