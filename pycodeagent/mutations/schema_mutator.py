"""Tool schema mutator.

Provides deterministic selection of alternative input schemas and adapters.
Used by the profile sampler to generate mutated tool profiles.
"""

from __future__ import annotations

import hashlib
from typing import Any

from pycodeagent.tools.spec import ToolAdapter


class SchemaMutationError(ValueError):
    """Raised when schema mutation fails due to invalid input."""


class SchemaCandidate:
    """A schema candidate with its associated adapter.

    Attributes:
        input_schema: The JSON schema for tool arguments.
        adapter: The ToolAdapter that maps exposed args to canonical args.
    """

    def __init__(
        self,
        input_schema: dict[str, Any],
        adapter: ToolAdapter | dict[str, Any] | None = None,
    ) -> None:
        """Initialize a schema candidate.

        Args:
            input_schema: The JSON schema for tool arguments.
            adapter: Either a ToolAdapter, a dict with adapter config, or None.
        """
        self.input_schema = input_schema
        if adapter is None:
            self.adapter = ToolAdapter()
        elif isinstance(adapter, ToolAdapter):
            self.adapter = adapter
        elif isinstance(adapter, dict):
            self.adapter = ToolAdapter(
                exposed_to_canonical=adapter.get("exposed_to_canonical", {}),
                defaults=adapter.get("defaults", {}),
            )
        else:
            raise SchemaMutationError(
                f"adapter must be ToolAdapter, dict, or None, got {type(adapter).__name__}"
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SchemaCandidate":
        """Create a SchemaCandidate from a dict.

        Expected format:
            {
                "input_schema": {...},
                "adapter": {
                    "exposed_to_canonical": {...},
                    "defaults": {...}
                }
            }
        """
        if not isinstance(data, dict):
            raise SchemaMutationError(
                f"Schema candidate must be a dict, got {type(data).__name__}"
            )

        input_schema = data.get("input_schema")
        if input_schema is None:
            raise SchemaMutationError(
                "Schema candidate must have 'input_schema' key"
            )
        if not isinstance(input_schema, dict):
            raise SchemaMutationError(
                f"input_schema must be a dict, got {type(input_schema).__name__}"
            )

        return cls(input_schema=input_schema, adapter=data.get("adapter"))


class SchemaMutator:
    """Mutator for tool input schemas.

    Selects from a list of schema candidates deterministically using a seed.
    Each candidate includes both the input schema and the adapter needed to
    map exposed arguments back to canonical arguments.

    Example:
        mutator = SchemaMutator()
        schema, adapter = mutator.mutate(
            base_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            candidates=[
                SchemaCandidate(input_schema={...}, adapter={}),
                SchemaCandidate(input_schema={...}, adapter={"exposed_to_canonical": {...}}),
            ],
            seed=42,
            mutate=True,
        )
    """

    def mutate(
        self,
        base_schema: dict[str, Any],
        candidates: list[SchemaCandidate | dict[str, Any]] | None = None,
        seed: int = 0,
        *,
        mutate: bool = True,
        tool_name: str = "unknown",
    ) -> tuple[dict[str, Any], ToolAdapter]:
        """Select a schema and adapter from candidates.

        Args:
            base_schema: The base/default input schema.
            candidates: List of SchemaCandidate objects or dicts.
                       Index 0 is the base schema.
            seed: Random seed for deterministic selection.
            mutate: If True, select from non-base candidates (indices 1+).
                   If False, return the base schema (index 0 or base_schema).
            tool_name: Canonical tool name (used for error messages and hashing).

        Returns:
            A tuple of (input_schema, ToolAdapter).

        Raises:
            SchemaMutationError: If candidates are invalid.
        """
        # Validate base_schema
        if not isinstance(base_schema, dict):
            raise SchemaMutationError(
                f"base_schema must be a dict, got {base_schema!r}"
            )

        # Default to base schema as only candidate
        if candidates is None or len(candidates) == 0:
            candidates = [SchemaCandidate(input_schema=base_schema, adapter=None)]

        # Normalize and validate candidates
        normalized = self._normalize_candidates(candidates, tool_name)

        if not mutate:
            # Return base (index 0)
            return normalized[0].input_schema, normalized[0].adapter

        # For mutation mode, select from non-base indices [1, N)
        num_candidates = len(normalized)
        if num_candidates <= 1:
            # Only one candidate, return it (no mutation possible)
            return normalized[0].input_schema, normalized[0].adapter

        # Select from range [1, num_candidates)
        idx = self._select_mutated_index(seed, tool_name, num_candidates)
        return normalized[idx].input_schema, normalized[idx].adapter

    def _normalize_candidates(
        self,
        candidates: list[SchemaCandidate | dict[str, Any]],
        tool_name: str,
    ) -> list[SchemaCandidate]:
        """Normalize candidate list to SchemaCandidate objects."""
        if not isinstance(candidates, list):
            raise SchemaMutationError(
                f"candidates must be a list, got {type(candidates).__name__}"
            )

        normalized: list[SchemaCandidate] = []
        for i, candidate in enumerate(candidates):
            if isinstance(candidate, SchemaCandidate):
                normalized.append(candidate)
            elif isinstance(candidate, dict):
                try:
                    normalized.append(SchemaCandidate.from_dict(candidate))
                except SchemaMutationError as e:
                    raise SchemaMutationError(
                        f"candidates[{i}] is invalid for tool {tool_name!r}: {e}"
                    ) from e
            else:
                raise SchemaMutationError(
                    f"candidates[{i}] must be SchemaCandidate or dict, "
                    f"got {type(candidate).__name__} (tool_name={tool_name!r})"
                )

        return normalized

    def _select_mutated_index(
        self, seed: int, tool_name: str, num_candidates: int
    ) -> int:
        """Select a non-base (non-zero) candidate index.

        Returns an index in [1, num_candidates), deterministically based on seed.
        """
        non_base_count = num_candidates - 1
        h = hashlib.sha256(f"{seed}:{tool_name}:schema:mut".encode())
        offset = int.from_bytes(h.digest()[:4], "big") % non_base_count
        return 1 + offset


def mutate_schema(
    base_schema: dict[str, Any],
    candidates: list[SchemaCandidate | dict[str, Any]] | None = None,
    seed: int = 0,
    *,
    mutate: bool = True,
    tool_name: str = "unknown",
) -> tuple[dict[str, Any], ToolAdapter]:
    """Convenience function for schema mutation.

    Args:
        base_schema: The base input schema.
        candidates: List of SchemaCandidate objects or dicts.
        seed: Random seed for deterministic selection.
        mutate: If True, select from non-base candidates.
        tool_name: Canonical tool name for error messages and hashing.

    Returns:
        A tuple of (input_schema, ToolAdapter).
    """
    return SchemaMutator().mutate(
        base_schema, candidates, seed, mutate=mutate, tool_name=tool_name
    )
