"""Tool profile sampler.

Produces deterministic profile variants for mutation experiments.
Config-backed: reads variant candidates from mutation config YAML.

Supported modes:
- base: identity mapping (exposed_name == canonical_name), derived from builtin canonical tools
- name_only: only tool names are mutated
- description_only: only descriptions are mutated
- argument_rename: only flat argument-name mutations are applied
- schema_flat_to_nested: only flat-to-nested schema mutations are applied
- tool_reorder: only exposed tool order is changed
- schema_only: compatibility mode that samples from all schema mutations
- name_description_schema: compatibility mode that mutates name, description, and schema
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pycodeagent.mutations.description_mutator import DescriptionMutator
from pycodeagent.mutations.name_mutator import NameMutator
from pycodeagent.mutations.profile_loader import load_tool_profile
from pycodeagent.mutations.schema_mutator import (
    SCHEMA_VARIANT_CATEGORIES,
    SchemaCandidate,
    SchemaMutator,
)
from pycodeagent.tools.profile_factory import build_base_tool_profile
from pycodeagent.tools.spec import ToolAdapter, ToolProfile, ToolView


_DEFAULT_MUTATION_CONFIG = Path(__file__).parent.parent.parent / "configs" / "tools" / "mutation_v1.yaml"
_MUTATION_MANIFEST_VERSION = 1
_REORDER_ANCHOR_POLICY = "finish_last"
_SUPPORTED_MODES = (
    "base",
    "name_only",
    "description_only",
    "argument_rename",
    "schema_flat_to_nested",
    "tool_reorder",
    "schema_only",
    "name_description_schema",
)


@dataclass(frozen=True)
class _StringCandidate:
    variant_id: str
    value: str


def _stable_variant_id(*parts: object) -> str:
    payload = "\0".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    return digest


def _load_mutation_config(config_path: Path) -> dict[str, Any]:
    """Load mutation config from YAML file."""
    if not config_path.exists():
        raise FileNotFoundError(f"Mutation config not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Mutation config must be a mapping, got {type(data).__name__}")

    return data


def _stable_hash_int(*parts: object) -> int:
    payload = "\0".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _mode_spec(mode: str) -> dict[str, Any]:
    if mode == "base":
        return {
            "mutate_name": False,
            "mutate_description": False,
            "mutate_schema": False,
            "schema_category": None,
            "reorder_tools": False,
            "mutation_axes": [],
            "compat_mode": None,
        }
    if mode == "name_only":
        return {
            "mutate_name": True,
            "mutate_description": False,
            "mutate_schema": False,
            "schema_category": None,
            "reorder_tools": False,
            "mutation_axes": ["name"],
            "compat_mode": None,
        }
    if mode == "description_only":
        return {
            "mutate_name": False,
            "mutate_description": True,
            "mutate_schema": False,
            "schema_category": None,
            "reorder_tools": False,
            "mutation_axes": ["description"],
            "compat_mode": None,
        }
    if mode == "argument_rename":
        return {
            "mutate_name": False,
            "mutate_description": False,
            "mutate_schema": True,
            "schema_category": "argument_rename",
            "reorder_tools": False,
            "mutation_axes": ["argument_rename"],
            "compat_mode": None,
        }
    if mode == "schema_flat_to_nested":
        return {
            "mutate_name": False,
            "mutate_description": False,
            "mutate_schema": True,
            "schema_category": "schema_flat_to_nested",
            "reorder_tools": False,
            "mutation_axes": ["schema_flat_to_nested"],
            "compat_mode": None,
        }
    if mode == "tool_reorder":
        return {
            "mutate_name": False,
            "mutate_description": False,
            "mutate_schema": False,
            "schema_category": None,
            "reorder_tools": True,
            "mutation_axes": ["tool_reorder"],
            "compat_mode": None,
        }
    if mode == "schema_only":
        return {
            "mutate_name": False,
            "mutate_description": False,
            "mutate_schema": True,
            "schema_category": None,
            "reorder_tools": False,
            "mutation_axes": ["schema"],
            "compat_mode": "schema_only",
        }
    if mode == "name_description_schema":
        return {
            "mutate_name": True,
            "mutate_description": True,
            "mutate_schema": True,
            "schema_category": None,
            "reorder_tools": False,
            "mutation_axes": ["name", "description", "schema"],
            "compat_mode": "name_description_schema",
        }
    raise ValueError(f"Invalid mode '{mode}'. Must be one of: {sorted(_SUPPORTED_MODES)}")


class ToolProfileSampler:
    """Sampler for deterministic tool profile variants."""

    def __init__(
        self,
        seed: int = 0,
        *,
        mutation_config_path: str | Path | None = None,
        base_config_path: str | Path | None = None,
    ) -> None:
        self.seed = seed
        self.mutation_config_path = Path(mutation_config_path) if mutation_config_path else _DEFAULT_MUTATION_CONFIG
        self.base_config_path = Path(base_config_path) if base_config_path else None
        self._mutation_config: dict[str, Any] | None = None
        self._base_profile: ToolProfile | None = None
        self._name_mutator = NameMutator()
        self._description_mutator = DescriptionMutator()
        self._schema_mutator = SchemaMutator()

    def _get_mutation_config(self) -> dict[str, Any]:
        if self._mutation_config is None:
            self._mutation_config = _load_mutation_config(self.mutation_config_path)
        return self._mutation_config

    def _get_base_profile(self) -> ToolProfile:
        if self._base_profile is None:
            self._base_profile = build_base_tool_profile()
        return self._base_profile

    def _normalize_string_candidates(
        self,
        base_value: str,
        candidates: Any,
        *,
        tool_name: str,
        field_name: str,
    ) -> list[_StringCandidate]:
        base_variant_id = f"{tool_name}_{field_name}_base"
        if not isinstance(candidates, list):
            return [_StringCandidate(variant_id=base_variant_id, value=base_value)]

        normalized = [_StringCandidate(variant_id=base_variant_id, value=base_value)]
        seen_values = {base_value}
        for index, candidate in enumerate(candidates):
            if isinstance(candidate, str):
                candidate_value = candidate
                candidate_variant_id = (
                    f"{tool_name}_{field_name}_{_stable_variant_id(field_name, candidate_value)}"
                )
            elif isinstance(candidate, dict):
                raw_value = candidate.get("value")
                if not isinstance(raw_value, str):
                    continue
                candidate_value = raw_value
                raw_variant_id = candidate.get("id")
                candidate_variant_id = (
                    str(raw_variant_id)
                    if raw_variant_id is not None
                    else f"{tool_name}_{field_name}_{_stable_variant_id(field_name, index, candidate_value)}"
                )
            else:
                continue

            if candidate_value in seen_values:
                continue
            normalized.append(
                _StringCandidate(
                    variant_id=candidate_variant_id,
                    value=candidate_value,
                )
            )
            seen_values.add(candidate_value)
        return normalized

    def _is_base_schema_candidate(
        self,
        base_schema: dict[str, Any],
        candidate: Any,
    ) -> bool:
        if isinstance(candidate, SchemaCandidate):
            return (
                candidate.input_schema == base_schema
                and candidate.adapter.exposed_to_canonical == {}
                and candidate.adapter.defaults == {}
            )

        if not isinstance(candidate, dict):
            return False

        if candidate.get("input_schema") != base_schema:
            return False

        adapter = candidate.get("adapter", {})
        if adapter is None:
            return True
        if not isinstance(adapter, dict):
            return False

        return (
            adapter.get("exposed_to_canonical", {}) == {}
            and adapter.get("defaults", {}) == {}
        )

    def _classify_legacy_schema_candidate(self, candidate: Any) -> str | None:
        adapter: ToolAdapter | dict[str, Any] | None = None
        if isinstance(candidate, SchemaCandidate):
            if candidate.category is not None:
                return candidate.category
            adapter = candidate.adapter
        elif isinstance(candidate, dict):
            adapter = candidate.get("adapter")
            category = candidate.get("category")
            if category is not None:
                if category not in SCHEMA_VARIANT_CATEGORIES:
                    raise ValueError(
                        "Invalid schema variant category "
                        f"{category!r}; expected one of {sorted(SCHEMA_VARIANT_CATEGORIES)}"
                    )
                return str(category)

        mapping: dict[str, str] = {}
        if isinstance(adapter, ToolAdapter):
            mapping = adapter.exposed_to_canonical
        elif isinstance(adapter, dict):
            raw_mapping = adapter.get("exposed_to_canonical", {})
            if isinstance(raw_mapping, dict):
                mapping = {
                    str(key): str(value)
                    for key, value in raw_mapping.items()
                }

        has_dotted_paths = any(
            "." in key or "." in value
            for key, value in mapping.items()
        )
        return "schema_flat_to_nested" if has_dotted_paths else "argument_rename"

    def _normalize_schema_candidates(
        self,
        base_view: ToolView,
        variants: dict[str, Any],
    ) -> list[SchemaCandidate]:
        raw_variants = variants.get("schema_variants")
        if raw_variants is None:
            raw_variants = variants.get("schema_candidates", [])
        if not isinstance(raw_variants, list):
            return [
                SchemaCandidate(
                    input_schema=base_view.input_schema,
                    adapter={},
                    category=None,
                    variant_id=f"{base_view.canonical_name}_schema_base",
                )
            ]

        normalized: list[SchemaCandidate] = [
            SchemaCandidate(
                input_schema=base_view.input_schema,
                adapter={},
                category=None,
                variant_id=f"{base_view.canonical_name}_schema_base",
            )
        ]
        for raw_variant in raw_variants:
            if self._is_base_schema_candidate(base_view.input_schema, raw_variant):
                continue

            if isinstance(raw_variant, SchemaCandidate):
                category = raw_variant.category or self._classify_legacy_schema_candidate(raw_variant)
                normalized.append(
                    SchemaCandidate(
                        input_schema=raw_variant.input_schema,
                        adapter=raw_variant.adapter,
                        category=category,
                        variant_id=(
                            raw_variant.variant_id
                            or f"{base_view.canonical_name}_schema_{_stable_variant_id(category, raw_variant.input_schema, raw_variant.adapter.exposed_to_canonical, raw_variant.adapter.defaults)}"
                        ),
                    )
                )
                continue

            if not isinstance(raw_variant, dict):
                continue

            category = raw_variant.get("category")
            if category is None:
                category = self._classify_legacy_schema_candidate(raw_variant)
            elif category not in SCHEMA_VARIANT_CATEGORIES:
                raise ValueError(
                    "Invalid schema variant category "
                    f"{category!r}; expected one of {sorted(SCHEMA_VARIANT_CATEGORIES)}"
                )

            normalized.append(
                SchemaCandidate.from_dict(
                    {
                        **raw_variant,
                        "category": category,
                        "variant_id": raw_variant.get("variant_id")
                        or f"{base_view.canonical_name}_schema_{_stable_variant_id(category, json.dumps(raw_variant.get('input_schema', {}), sort_keys=True), json.dumps(raw_variant.get('adapter', {}), sort_keys=True))}",
                    }
                )
            )
        return normalized

    def _filter_schema_candidates(
        self,
        candidates: list[SchemaCandidate],
        *,
        schema_category: str | None,
    ) -> list[SchemaCandidate]:
        if schema_category is None:
            return candidates

        filtered = [candidates[0]]
        filtered.extend(
            candidate
            for candidate in candidates[1:]
            if candidate.category == schema_category
        )
        return filtered

    def _select_tool_variant(
        self,
        base_view: ToolView,
        mode: str,
        config: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any], ToolAdapter, dict[str, Any]]:
        canonical_name = base_view.canonical_name
        tool_variants = config.get("tool_variants", {})
        variants = tool_variants.get(canonical_name, {})
        spec = _mode_spec(mode)

        name_candidates = self._normalize_string_candidates(
            base_view.exposed_name,
            variants.get("name_candidates", [base_view.exposed_name]),
            tool_name=canonical_name,
            field_name="name",
        )
        desc_candidates = self._normalize_string_candidates(
            base_view.description,
            variants.get("description_candidates", [base_view.description]),
            tool_name=canonical_name,
            field_name="description",
        )
        schema_candidates = self._normalize_schema_candidates(base_view, variants)
        schema_candidates = self._filter_schema_candidates(
            schema_candidates,
            schema_category=spec["schema_category"],
        )

        if spec["mutate_name"]:
            exposed_name = self._name_mutator.mutate(
                canonical_name,
                candidates=[candidate.value for candidate in name_candidates],
                seed=self.seed,
                mutate=True,
            )
        else:
            exposed_name = base_view.exposed_name
        selected_name_candidate = next(
            (
                candidate
                for candidate in name_candidates
                if candidate.value == exposed_name
            ),
            name_candidates[0],
        )

        if spec["mutate_description"]:
            description = self._description_mutator.mutate(
                base_description=base_view.description,
                candidates=[candidate.value for candidate in desc_candidates],
                seed=self.seed,
                mutate=True,
                tool_name=canonical_name,
            )
        else:
            description = base_view.description
        selected_description_candidate = next(
            (
                candidate
                for candidate in desc_candidates
                if candidate.value == description
            ),
            desc_candidates[0],
        )

        if spec["mutate_schema"]:
            input_schema, adapter = self._schema_mutator.mutate(
                base_schema=base_view.input_schema,
                candidates=schema_candidates,
                seed=self.seed,
                mutate=True,
                tool_name=canonical_name,
            )
        else:
            input_schema = base_view.input_schema
            adapter = ToolAdapter()

        selected_schema_candidate = schema_candidates[0]
        for candidate in schema_candidates:
            if (
                candidate.input_schema == input_schema
                and candidate.adapter.exposed_to_canonical == adapter.exposed_to_canonical
                and candidate.adapter.defaults == adapter.defaults
            ):
                selected_schema_candidate = candidate
                break

        state = {
            "name_variant_id": selected_name_candidate.variant_id,
            "description_variant_id": selected_description_candidate.variant_id,
            "schema_variant_id": selected_schema_candidate.variant_id,
            "schema_variant_category": selected_schema_candidate.category,
            "name_mutated": exposed_name != base_view.exposed_name,
            "description_mutated": description != base_view.description,
            "schema_mutated": input_schema != base_view.input_schema,
        }
        return exposed_name, description, input_schema, adapter, state

    def _reorder_tools(self, tools: list[ToolView]) -> list[ToolView]:
        anchored_finish = [
            tool for tool in tools if tool.canonical_name == "finish"
        ]
        reorderable = [
            tool for tool in tools if tool.canonical_name != "finish"
        ]
        base_order = [tool.canonical_name for tool in reorderable]
        reordered = sorted(
            reorderable,
            key=lambda tool: (
                _stable_hash_int("tool_reorder", self.seed, tool.canonical_name),
                tool.canonical_name,
            ),
        )
        if [tool.canonical_name for tool in reordered] == base_order and len(reordered) > 1:
            offset = 1 + (_stable_hash_int("tool_reorder_offset", self.seed) % (len(reordered) - 1))
            reordered = reordered[offset:] + reordered[:offset]
        return reordered + anchored_finish

    def sample(self, mode: str) -> ToolProfile:
        if mode not in _SUPPORTED_MODES:
            raise ValueError(f"Invalid mode '{mode}'. Must be one of: {sorted(_SUPPORTED_MODES)}")

        config = self._get_mutation_config()
        base = self._get_base_profile()
        spec = _mode_spec(mode)

        h = hashlib.sha256(f"{mode}:{self.seed}".encode()).hexdigest()[:8]
        profile_id_prefix = config.get("profile_id_prefix", "mutation")
        profile_id = f"{profile_id_prefix}_{mode}_{h}"

        tools: list[ToolView] = []
        adapters: dict[str, ToolAdapter] = {}
        schema_variant_categories: dict[str, str | None] = {}
        selected_variant_ids: dict[str, dict[str, str | None]] = {}

        for base_index, base_view in enumerate(base.tools):
            exposed_name, description, input_schema, adapter, state = self._select_tool_variant(
                base_view,
                mode,
                config,
            )
            is_mutated = (
                state["name_mutated"]
                or state["description_mutated"]
                or state["schema_mutated"]
            )
            version = "mutated" if is_mutated else "default"
            view = ToolView(
                canonical_name=base_view.canonical_name,
                exposed_name=exposed_name,
                description=description,
                input_schema=input_schema,
                version=version,
                metadata={
                    "name_variant_id": state["name_variant_id"],
                    "description_variant_id": state["description_variant_id"],
                    "schema_variant_id": state["schema_variant_id"],
                    "schema_variant_category": state["schema_variant_category"],
                    "name_mutated": state["name_mutated"],
                    "description_mutated": state["description_mutated"],
                    "schema_mutated": state["schema_mutated"],
                    "tool_order_index_base": base_index,
                    "tool_order_index_exposed": base_index,
                    "tool_reordered": False,
                },
            )
            tools.append(view)
            adapters[exposed_name] = adapter
            schema_variant_categories[base_view.canonical_name] = state["schema_variant_category"]
            selected_variant_ids[base_view.canonical_name] = {
                "name_variant_id": state["name_variant_id"],
                "description_variant_id": state["description_variant_id"],
                "schema_variant_id": state["schema_variant_id"],
            }

        if spec["reorder_tools"]:
            tools = self._reorder_tools(tools)

        for exposed_index, tool in enumerate(tools):
            tool.metadata["tool_order_index_exposed"] = exposed_index
            tool.metadata["tool_reordered"] = (
                exposed_index != tool.metadata["tool_order_index_base"]
            )

        return ToolProfile(
            profile_id=profile_id,
            tools=tools,
            adapters=adapters,
            metadata={
                "mutation_manifest_version": _MUTATION_MANIFEST_VERSION,
                "mode": mode,
                "seed": self.seed,
                "mutation_axes": list(spec["mutation_axes"]),
                "compat_mode": spec["compat_mode"],
                "reorder_anchor_policy": _REORDER_ANCHOR_POLICY,
                "tool_order_seed": self.seed if spec["reorder_tools"] else None,
                "schema_variant_categories": schema_variant_categories,
                "selected_variant_ids": selected_variant_ids,
            },
        )

    def sample_all_modes(self) -> dict[str, ToolProfile]:
        return {
            mode: self.sample(mode)
            for mode in _SUPPORTED_MODES
        }


def build_sampled_tool_profile(
    mode: str,
    seed: int = 0,
    config_path: str | Path | None = None,
) -> ToolProfile:
    """Convenience function to build a sampled profile."""
    if config_path is not None:
        config_path = Path(config_path)
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict) and "tool_variants" in data:
            sampler = ToolProfileSampler(seed=seed, mutation_config_path=config_path)
            return sampler.sample(mode)
        return load_tool_profile(config_path)

    sampler = ToolProfileSampler(seed=seed)
    return sampler.sample(mode)
