"""Native-aware surface-level ToolProfile transformations."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from pycodeagent.mutations.description_mutator import DescriptionMutator
from pycodeagent.mutations.name_mutator import NameMutator
from pycodeagent.tools.spec import ToolAdapter, ToolProfile, ToolView

NativeTransformationMode = Literal[
    "base",
    "name_only",
    "description_only",
    "name_description",
]

_NATIVE_IDENTITY_STATUS = "native_identity_not_canonicalized"
_SUPPORTED_MODES: set[str] = {
    "base",
    "name_only",
    "description_only",
    "name_description",
}


def build_native_transformed_profiles(
    base_profile: ToolProfile,
    *,
    modes: list[NativeTransformationMode],
    seed: int = 0,
) -> dict[str, ToolProfile]:
    """Build multiple transformed profiles from one base native profile."""
    return {
        mode: build_native_transformed_profile(base_profile, mode=mode, seed=seed)
        for mode in modes
    }


def build_native_transformed_profile(
    base_profile: ToolProfile,
    *,
    mode: NativeTransformationMode,
    seed: int = 0,
) -> ToolProfile:
    """Build one transformed ToolProfile from a base native profile."""
    if mode not in _SUPPORTED_MODES:
        raise ValueError(f"Invalid native transformation mode: {mode!r}")

    mutate_name = mode in {"name_only", "name_description"}
    mutate_description = mode in {"description_only", "name_description"}
    name_mutator = NameMutator()
    description_mutator = DescriptionMutator()

    tools: list[ToolView] = []
    adapters: dict[str, ToolAdapter] = {}
    used_names: set[str] = set()

    for index, base_view in enumerate(base_profile.tools):
        name_candidates = generate_name_candidates(base_view)
        description_candidates = generate_description_candidates(base_view)

        if mutate_name:
            exposed_name = _select_unique_transformed_name(
                base_view=base_view,
                candidates=name_candidates,
                used_names=used_names,
                seed=seed,
                mutator=name_mutator,
            )
        else:
            exposed_name = base_view.exposed_name
            if exposed_name in used_names:
                raise ValueError(f"Base native profile already has duplicate exposed name: {exposed_name!r}")

        if mutate_description:
            description = description_mutator.mutate(
                base_description=base_view.description,
                candidates=description_candidates,
                seed=seed,
                mutate=True,
                tool_name=base_view.metadata.get("native_name", base_view.exposed_name),
            )
        else:
            description = base_view.description

        tool_metadata = dict(base_view.metadata)
        tool_metadata.update(
            {
                "source_profile_id": base_profile.profile_id,
                "transformation_mode": mode,
                "transformation_seed": seed,
                "transformed_tool_index": index,
                "canonical_mapping_status": _NATIVE_IDENTITY_STATUS,
                "native_name": tool_metadata.get("native_name", base_view.exposed_name),
            }
        )

        transformed_view = ToolView(
            canonical_name=base_view.canonical_name,
            exposed_name=exposed_name,
            description=description,
            input_schema=base_view.input_schema,
            version="native_transformed" if mode != "base" else base_view.version,
            metadata=tool_metadata,
        )
        tools.append(transformed_view)
        adapters[exposed_name] = _clone_adapter(base_profile.adapters[base_view.exposed_name])
        used_names.add(exposed_name)

    profile_metadata = dict(base_profile.metadata)
    profile_metadata.update(
        {
            "source_profile_id": base_profile.profile_id,
            "transformation_mode": mode,
            "transformation_seed": seed,
            "tool_order_preserved": True,
            "native_schema_snapshot": True,
            "canonical_mapping_status": _NATIVE_IDENTITY_STATUS,
        }
    )
    return ToolProfile(
        profile_id=f"{base_profile.profile_id}::{mode}::{seed}",
        tools=tools,
        adapters=adapters,
        metadata=profile_metadata,
    )


def generate_name_candidates(tool_view: ToolView) -> list[str]:
    """Generate deterministic, semantics-preserving surface name candidates."""
    base = tool_view.exposed_name
    tokens = _tokenize_name(tool_view.metadata.get("native_name", base))
    if not tokens:
        return [base]

    snake = "_".join(tokens)
    camel = tokens[0] + "".join(token.title() for token in tokens[1:])
    pascal = "".join(token.title() for token in tokens)
    candidates = [
        base,
        snake,
        camel,
        pascal,
        f"{snake}_tool",
        f"use_{snake}",
    ]
    return _dedupe_strings(candidates)


def generate_description_candidates(tool_view: ToolView) -> list[str]:
    """Generate deterministic, semantics-preserving description candidates."""
    base = tool_view.description
    if base == "":
        return [base]

    normalized = re.sub(r"\s+", " ", base).strip()
    if normalized == "":
        return [""]

    bare = normalized.rstrip(".")
    lower_sentence = bare[:1].lower() + bare[1:] if bare else bare
    candidates = [
        base,
        normalized,
        f"Use this tool to {lower_sentence}.",
        f"Tool for {lower_sentence}.",
    ]
    return _dedupe_strings(candidates)


def _select_unique_transformed_name(
    *,
    base_view: ToolView,
    candidates: list[str],
    used_names: set[str],
    seed: int,
    mutator: NameMutator,
) -> str:
    if len(candidates) <= 1:
        if candidates[0] in used_names:
            raise ValueError(f"Unable to produce unique transformed name for {base_view.exposed_name!r}")
        return candidates[0]

    native_key = str(base_view.metadata.get("native_name", base_view.exposed_name))
    first_choice = mutator.mutate(
        native_key,
        candidates=candidates,
        seed=seed,
        mutate=True,
    )
    ordered_choices = [first_choice]
    ordered_choices.extend(
        candidate for candidate in candidates[1:] if candidate != first_choice
    )
    if candidates[0] not in ordered_choices:
        ordered_choices.append(candidates[0])

    for candidate in ordered_choices:
        if candidate not in used_names:
            return candidate

    for suffix_index in range(2, 10):
        candidate = f"{candidates[0]}_{suffix_index}"
        if candidate not in used_names:
            return candidate

    raise ValueError(f"Unable to produce unique transformed name for {base_view.exposed_name!r}")


def _clone_adapter(adapter: ToolAdapter) -> ToolAdapter:
    return ToolAdapter(
        exposed_to_canonical=dict(adapter.exposed_to_canonical),
        defaults=dict(adapter.defaults),
    )


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _tokenize_name(name: str) -> list[str]:
    cleaned = re.sub(r"[^0-9A-Za-z]+", " ", name)
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", cleaned)
    tokens = [token.lower() for token in expanded.split() if token]
    return tokens
