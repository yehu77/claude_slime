"""Deterministic split/profile planning for synthetic schema-following data."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.tools.spec import ToolProfile

SchemaFollowingSplitName = Literal[
    "train",
    "eval_seen",
    "eval_unseen_name",
    "eval_unseen_description",
    "eval_unseen_schema",
    "eval_nested",
    "eval_distractor",
]
SyntheticProfileSplitRole = Literal[
    "train_seen",
    "eval_unseen_name",
    "eval_unseen_description",
    "eval_unseen_schema",
]

SCHEMA_FOLLOWING_SPLIT_ORDER: list[SchemaFollowingSplitName] = [
    "train",
    "eval_seen",
    "eval_unseen_name",
    "eval_unseen_description",
    "eval_unseen_schema",
    "eval_nested",
    "eval_distractor",
]


class SyntheticProfileSpec(BaseModel):
    """Specification for one synthetic profile used during generation."""

    category: str
    mode: str
    seed: int
    split_role: SyntheticProfileSplitRole
    notes: list[str] = Field(default_factory=list)


def _profile_signature(profile: ToolProfile) -> str:
    """Return a stable signature for one sampled profile."""
    payload = []
    for tool in profile.tools:
        adapter = profile.adapters.get(tool.exposed_name)
        payload.append(
            {
                "canonical_name": tool.canonical_name,
                "exposed_name": tool.exposed_name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "adapter": (
                    adapter.model_dump(mode="json")
                    if adapter is not None
                    else {"exposed_to_canonical": {}, "defaults": {}}
                ),
            }
        )
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _collect_unique_mode_seeds(
    *,
    mode: str,
    start_seed: int,
    count: int,
    family: str,
) -> list[int]:
    """Collect deterministic seeds that yield distinct sampled profiles."""
    seen: set[str] = set()
    seeds: list[int] = []
    seed = start_seed

    while len(seeds) < count:
        profile = ToolProfileSampler(seed=seed, family=family).sample(mode)
        signature = _profile_signature(profile)
        if signature not in seen:
            seen.add(signature)
            seeds.append(seed)
        seed += 1
        if seed - start_seed > 512:
            raise ValueError(
                f"Unable to find {count} unique sampled profiles for mode {mode!r}"
            )

    return seeds


def build_default_synthetic_profile_specs(
    *,
    seed: int = 42,
    family: str,
) -> list[SyntheticProfileSpec]:
    """Build the default synthetic profile plan for Phase 3.

    This intentionally supports only the subset of categories implemented in
    Phase 3. Later phases can extend this plan without changing the split names.
    """
    name_train_seed, name_unseen_seed = _collect_unique_mode_seeds(
        mode="name_only",
        start_seed=seed + 10,
        count=2,
        family=family,
    )
    desc_train_seed, desc_unseen_seed = _collect_unique_mode_seeds(
        mode="description_only",
        start_seed=seed + 20,
        count=2,
        family=family,
    )
    schema_train_seed, schema_unseen_seed = _collect_unique_mode_seeds(
        mode="schema_only",
        start_seed=seed + 30,
        count=2,
        family=family,
    )
    mixed_train_seed = _collect_unique_mode_seeds(
        mode="name_description_schema",
        start_seed=seed + 40,
        count=1,
        family=family,
    )[0]

    return [
        SyntheticProfileSpec(
            category="base",
            mode="base",
            seed=seed,
            split_role="train_seen",
        ),
        SyntheticProfileSpec(
            category="rename_light",
            mode="name_only",
            seed=name_train_seed,
            split_role="train_seen",
        ),
        SyntheticProfileSpec(
            category="rename_light",
            mode="name_only",
            seed=name_unseen_seed,
            split_role="eval_unseen_name",
        ),
        SyntheticProfileSpec(
            category="description_paraphrase",
            mode="description_only",
            seed=desc_train_seed,
            split_role="train_seen",
        ),
        SyntheticProfileSpec(
            category="description_paraphrase",
            mode="description_only",
            seed=desc_unseen_seed,
            split_role="eval_unseen_description",
        ),
        SyntheticProfileSpec(
            category="schema_flat_to_nested",
            mode="schema_only",
            seed=schema_train_seed,
            split_role="train_seen",
        ),
        SyntheticProfileSpec(
            category="schema_flat_to_nested",
            mode="schema_only",
            seed=schema_unseen_seed,
            split_role="eval_unseen_schema",
        ),
        SyntheticProfileSpec(
            category="mixed_hard",
            mode="name_description_schema",
            seed=mixed_train_seed,
            split_role="train_seen",
        ),
    ]


def _stable_bucket(text: str, modulo: int) -> int:
    """Return a deterministic bucket index."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % modulo


def assign_synthetic_split(
    spec: SyntheticProfileSpec,
    *,
    split_key: str,
    requires_nested_args: bool,
) -> SchemaFollowingSplitName:
    """Assign a deterministic schema-following split for one sample."""
    if spec.split_role == "train_seen":
        return "eval_seen" if _stable_bucket(split_key, 5) == 0 else "train"
    if spec.split_role == "eval_unseen_name":
        return "eval_unseen_name"
    if spec.split_role == "eval_unseen_description":
        return "eval_unseen_description"
    if spec.split_role == "eval_unseen_schema":
        return "eval_nested" if requires_nested_args else "eval_unseen_schema"
    raise ValueError(f"Unsupported synthetic split role: {spec.split_role}")
