"""Tool profile sampler.

Produces deterministic profile variants for mutation experiments.
Config-backed: reads variant candidates from mutation config YAML.

Supported modes:
- base: identity mapping (exposed_name == canonical_name), derived from builtin canonical tools
- name_only: only tool names are mutated (selects non-index-0 names)
- description_only: only descriptions are mutated (selects non-index-0 descriptions)
- schema_only: only input schemas are restructured (selects non-index-0 schemas)
- name_description_schema: all three mutated

The seed determines which candidate index is selected when multiple candidates exist.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from pycodeagent.tools.profile_factory import build_base_tool_profile
from pycodeagent.tools.spec import ToolAdapter, ToolProfile, ToolView

from pycodeagent.mutations.profile_loader import load_tool_profile
from pycodeagent.mutations.name_mutator import NameMutator
from pycodeagent.mutations.description_mutator import DescriptionMutator
from pycodeagent.mutations.schema_mutator import SchemaCandidate, SchemaMutator


_DEFAULT_MUTATION_CONFIG = Path(__file__).parent.parent.parent / "configs" / "tools" / "mutation_v1.yaml"


def _load_mutation_config(config_path: Path) -> dict[str, Any]:
    """Load mutation config from YAML file."""
    if not config_path.exists():
        raise FileNotFoundError(f"Mutation config not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Mutation config must be a mapping, got {type(data).__name__}")

    return data


class ToolProfileSampler:
    """Sampler for deterministic tool profile variants.

    Config-backed: reads variant candidates from a mutation config YAML file.
    The seed determines which candidate is selected for each tool.

    Example:
        sampler = ToolProfileSampler(seed=42)
        profile = sampler.sample(mode="schema_only")
    """

    def __init__(
        self,
        seed: int = 0,
        *,
        mutation_config_path: str | Path | None = None,
        base_config_path: str | Path | None = None,
    ) -> None:
        """Initialize the sampler with a seed and optional config paths.

        Args:
            seed: Random seed for deterministic profile generation.
            mutation_config_path: Path to mutation config YAML (default: mutation_v1.yaml).
            base_config_path: Legacy compatibility argument. The sampler now
                derives its base profile directly from builtin canonical tools.
        """
        self.seed = seed
        self.mutation_config_path = Path(mutation_config_path) if mutation_config_path else _DEFAULT_MUTATION_CONFIG
        self.base_config_path = Path(base_config_path) if base_config_path else None

        # Lazy load configs
        self._mutation_config: dict[str, Any] | None = None
        self._base_profile: ToolProfile | None = None

        # Mutator instances
        self._name_mutator = NameMutator()
        self._description_mutator = DescriptionMutator()
        self._schema_mutator = SchemaMutator()

    def _get_mutation_config(self) -> dict[str, Any]:
        """Get mutation config, loading if necessary."""
        if self._mutation_config is None:
            self._mutation_config = _load_mutation_config(self.mutation_config_path)
        return self._mutation_config

    def _get_base_profile(self) -> ToolProfile:
        """Get base profile, loading if necessary."""
        if self._base_profile is None:
            self._base_profile = build_base_tool_profile()
        return self._base_profile

    def _normalize_string_candidates(
        self,
        base_value: str,
        candidates: Any,
    ) -> Any:
        """Prepend the canonical base value and drop duplicate base entries."""
        if not isinstance(candidates, list):
            return candidates

        normalized = [base_value]
        normalized.extend(candidate for candidate in candidates if candidate != base_value)
        return normalized

    def _is_base_schema_candidate(
        self,
        base_schema: dict[str, Any],
        candidate: Any,
    ) -> bool:
        """Return True when the candidate exactly matches the canonical base schema."""
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

    def _normalize_schema_candidates(
        self,
        base_view: ToolView,
        candidates: Any,
    ) -> Any:
        """Prepend the canonical base schema and drop duplicate base entries."""
        if not isinstance(candidates, list):
            return candidates

        normalized: list[dict[str, Any] | SchemaCandidate] = [
            {"input_schema": base_view.input_schema, "adapter": {}}
        ]
        normalized.extend(
            candidate
            for candidate in candidates
            if not self._is_base_schema_candidate(base_view.input_schema, candidate)
        )
        return normalized

    def _select_tool_variant(
        self,
        base_view: ToolView,
        mode: str,
        config: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any], ToolAdapter]:
        """Select name, description, schema, adapter for a tool.

        Delegates to NameMutator, DescriptionMutator, and SchemaMutator.

        Args:
            base_view: The base ToolView from the loaded base profile.
            mode: Sampling mode.
            config: Mutation config dict.

        Returns:
            (exposed_name, description, input_schema, adapter) tuple.
        """
        canonical_name = base_view.canonical_name
        tool_variants = config.get("tool_variants", {})
        variants = tool_variants.get(canonical_name, {})

        name_candidates = variants.get("name_candidates", [base_view.exposed_name])
        desc_candidates = variants.get("description_candidates", [base_view.description])
        schema_candidates = variants.get(
            "schema_candidates",
            [{"input_schema": base_view.input_schema, "adapter": {}}],
        )

        # Determine which dimensions to mutate
        mutate_name = mode != "base" and mode in ("name_only", "name_description_schema")
        mutate_description = mode != "base" and mode in ("description_only", "name_description_schema")
        mutate_schema = mode != "base" and mode in ("schema_only", "name_description_schema")

        # Builtin canonical tool definitions are the only base truth. Mutation
        # configs contribute delta candidates only; legacy duplicate-base
        # entries are ignored during normalization.
        effective_name_candidates = self._normalize_string_candidates(
            base_view.exposed_name,
            name_candidates,
        )
        effective_desc_candidates = self._normalize_string_candidates(
            base_view.description,
            desc_candidates,
        )
        effective_schema_candidates = self._normalize_schema_candidates(
            base_view,
            schema_candidates,
        )

        if mutate_name:
            exposed_name = self._name_mutator.mutate(
                canonical_name,
                candidates=effective_name_candidates,
                seed=self.seed,
                mutate=True,
            )
        else:
            exposed_name = base_view.exposed_name

        if mutate_description:
            description = self._description_mutator.mutate(
                base_description=base_view.description,
                candidates=effective_desc_candidates,
                seed=self.seed,
                mutate=True,
                tool_name=canonical_name,
            )
        else:
            description = base_view.description

        if mutate_schema:
            input_schema, adapter = self._schema_mutator.mutate(
                base_schema=base_view.input_schema,
                candidates=effective_schema_candidates,
                seed=self.seed,
                mutate=True,
                tool_name=canonical_name,
            )
        else:
            input_schema = base_view.input_schema
            adapter = ToolAdapter()

        return exposed_name, description, input_schema, adapter

    def sample(self, mode: str) -> ToolProfile:
        """Sample a profile for the given mode.

        Args:
            mode: One of 'base', 'name_only', 'description_only',
                  'schema_only', 'name_description_schema'.

        Returns:
            A ToolProfile with the requested mutations applied.

        Raises:
            ValueError: If mode is not recognized.
        """
        valid_modes = {
            "base",
            "name_only",
            "description_only",
            "schema_only",
            "name_description_schema",
        }
        if mode not in valid_modes:
            raise ValueError(f"Invalid mode '{mode}'. Must be one of: {sorted(valid_modes)}")

        config = self._get_mutation_config()
        base = self._get_base_profile()

        # Generate profile_id
        h = hashlib.sha256(f"{mode}:{self.seed}".encode()).hexdigest()[:8]
        profile_id_prefix = config.get("profile_id_prefix", "mutation")
        profile_id = f"{profile_id_prefix}_{mode}_{h}"

        tools: list[ToolView] = []
        adapters: dict[str, ToolAdapter] = {}

        for base_view in base.tools:
            exposed_name, description, input_schema, adapter = self._select_tool_variant(
                base_view, mode, config
            )

            # Determine version
            is_mutated = (
                exposed_name != base_view.canonical_name
                or description != base_view.description
                or input_schema != base_view.input_schema
            )
            version = "mutated" if is_mutated else "default"

            view = ToolView(
                canonical_name=base_view.canonical_name,
                exposed_name=exposed_name,
                description=description,
                input_schema=input_schema,
                version=version,
            )
            tools.append(view)
            adapters[exposed_name] = adapter

        return ToolProfile(
            profile_id=profile_id,
            tools=tools,
            adapters=adapters,
        )

    def sample_all_modes(self) -> dict[str, ToolProfile]:
        """Sample profiles for all supported modes.

        Returns:
            A dict mapping mode name to ToolProfile.
        """
        return {
            "base": self.sample("base"),
            "name_only": self.sample("name_only"),
            "description_only": self.sample("description_only"),
            "schema_only": self.sample("schema_only"),
            "name_description_schema": self.sample("name_description_schema"),
        }


def build_sampled_tool_profile(
    mode: str,
    seed: int = 0,
    config_path: str | Path | None = None,
) -> ToolProfile:
    """Convenience function to build a sampled profile.

    If config_path is provided and points to a standard profile config,
    loads from it directly. Otherwise, builds using the sampler.

    Args:
        mode: Sampling mode or profile_id when loading from config.
        seed: Random seed for deterministic sampling.
        config_path: Optional path to a config file.

    Returns:
        A ToolProfile.
    """
    if config_path is not None:
        config_path = Path(config_path)
        # Check if it's a mutation config or a standard profile config
        try:
            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict) and "tool_variants" in data:
                # It's a mutation config, use sampler
                sampler = ToolProfileSampler(seed=seed, mutation_config_path=config_path)
                return sampler.sample(mode)
            else:
                # It's a standard profile config, load directly
                return load_tool_profile(config_path)
        except FileNotFoundError:
            raise

    sampler = ToolProfileSampler(seed=seed)
    return sampler.sample(mode)
