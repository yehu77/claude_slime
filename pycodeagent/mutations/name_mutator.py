"""Tool name mutator.

Provides deterministic selection of alternative exposed names for tools.
Used by the profile sampler to generate mutated tool profiles.
"""

from __future__ import annotations

import hashlib
from typing import Any


class NameMutationError(ValueError):
    """Raised when name mutation fails due to invalid input."""


class NameMutator:
    """Mutator for tool exposed names.

    Selects from a list of candidate names deterministically using a seed.
    The first candidate (index 0) is treated as the base/identity name.

    Example:
        mutator = NameMutator()
        name = mutator.mutate(
            canonical_name="read_file",
            candidates=["read_file", "open_source", "inspect_file"],
            seed=42,
            mutate=True,
        )
    """

    def mutate(
        self,
        canonical_name: str,
        candidates: list[str] | None = None,
        seed: int = 0,
        *,
        mutate: bool = True,
    ) -> str:
        """Select an exposed name from candidates.

        Args:
            canonical_name: The canonical tool name (used as fallback and for hashing).
            candidates: List of candidate exposed names. Index 0 is the base name.
            seed: Random seed for deterministic selection.
            mutate: If True, select from non-base candidates (indices 1+).
                   If False, return the base name (index 0 or canonical_name).

        Returns:
            The selected exposed name.

        Raises:
            NameMutationError: If candidates are invalid.
        """
        # Validate canonical_name
        if not canonical_name or not isinstance(canonical_name, str):
            raise NameMutationError(
                f"canonical_name must be a non-empty string, got {canonical_name!r}"
            )

        # Default to identity (canonical name as only candidate)
        if candidates is None or len(candidates) == 0:
            candidates = [canonical_name]

        # Validate candidates
        self._validate_candidates(candidates, canonical_name)

        if not mutate:
            # Return base (index 0)
            return candidates[0]

        # For mutation mode, select from non-base indices [1, N)
        num_candidates = len(candidates)
        if num_candidates <= 1:
            # Only one candidate, return it (no mutation possible)
            return candidates[0]

        # Select from range [1, num_candidates)
        idx = self._select_mutated_index(seed, canonical_name, num_candidates)
        return candidates[idx]

    def _validate_candidates(
        self, candidates: list[Any], canonical_name: str
    ) -> None:
        """Validate candidate list."""
        if not isinstance(candidates, list):
            raise NameMutationError(
                f"candidates must be a list, got {type(candidates).__name__}"
            )

        for i, candidate in enumerate(candidates):
            if not isinstance(candidate, str) or not candidate:
                raise NameMutationError(
                    f"candidates[{i}] must be a non-empty string, got {candidate!r} "
                    f"(canonical_name={canonical_name!r})"
                )

    def _select_mutated_index(
        self, seed: int, canonical_name: str, num_candidates: int
    ) -> int:
        """Select a non-base (non-zero) candidate index.

        Returns an index in [1, num_candidates), deterministically based on seed.
        """
        # Number of non-base candidates
        non_base_count = num_candidates - 1
        h = hashlib.sha256(f"{seed}:{canonical_name}:name:mut".encode())
        offset = int.from_bytes(h.digest()[:4], "big") % non_base_count
        return 1 + offset


def mutate_name(
    canonical_name: str,
    candidates: list[str] | None = None,
    seed: int = 0,
    *,
    mutate: bool = True,
) -> str:
    """Convenience function for name mutation.

    Args:
        canonical_name: The canonical tool name.
        candidates: List of candidate exposed names.
        seed: Random seed for deterministic selection.
        mutate: If True, select from non-base candidates.

    Returns:
        The selected exposed name.
    """
    return NameMutator().mutate(canonical_name, candidates, seed, mutate=mutate)
