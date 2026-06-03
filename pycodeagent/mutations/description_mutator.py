"""Tool description mutator.

Provides deterministic selection of alternative descriptions for tools.
Used by the profile sampler to generate mutated tool profiles.
"""

from __future__ import annotations

import hashlib
from typing import Any


class DescriptionMutationError(ValueError):
    """Raised when description mutation fails due to invalid input."""


class DescriptionMutator:
    """Mutator for tool descriptions.

    Selects from a list of candidate descriptions deterministically using a seed.
    The first candidate (index 0) is treated as the base/identity description.

    Example:
        mutator = DescriptionMutator()
        desc = mutator.mutate(
            base_description="Read a file from the workspace.",
            candidates=[
                "Read a file from the workspace.",
                "Inspect source code by filename.",
                "View the contents of a source file.",
            ],
            seed=42,
            mutate=True,
        )
    """

    def mutate(
        self,
        base_description: str,
        candidates: list[str] | None = None,
        seed: int = 0,
        *,
        mutate: bool = True,
        tool_name: str = "unknown",
    ) -> str:
        """Select a description from candidates.

        Args:
            base_description: The base/default description.
            candidates: List of candidate descriptions. Index 0 is the base.
            seed: Random seed for deterministic selection.
            mutate: If True, select from non-base candidates (indices 1+).
                   If False, return the base description (index 0 or base_description).
            tool_name: Canonical tool name (used for error messages and hashing).

        Returns:
            The selected description.

        Raises:
            DescriptionMutationError: If candidates are invalid.
        """
        # Validate base_description
        if not isinstance(base_description, str):
            raise DescriptionMutationError(
                f"base_description must be a string, got {base_description!r}"
            )

        # Default to base description as only candidate
        if candidates is None or len(candidates) == 0:
            candidates = [base_description]

        # Validate candidates
        self._validate_candidates(candidates, tool_name)

        if not mutate:
            # Return base (index 0)
            return candidates[0]

        # For mutation mode, select from non-base indices [1, N)
        num_candidates = len(candidates)
        if num_candidates <= 1:
            # Only one candidate, return it (no mutation possible)
            return candidates[0]

        # Select from range [1, num_candidates)
        idx = self._select_mutated_index(seed, tool_name, num_candidates)
        return candidates[idx]

    def _validate_candidates(
        self, candidates: list[Any], tool_name: str
    ) -> None:
        """Validate candidate list."""
        if not isinstance(candidates, list):
            raise DescriptionMutationError(
                f"candidates must be a list, got {type(candidates).__name__}"
            )

        for i, candidate in enumerate(candidates):
            if not isinstance(candidate, str):
                raise DescriptionMutationError(
                    f"candidates[{i}] must be a string, got {candidate!r} "
                    f"(tool_name={tool_name!r})"
                )

    def _select_mutated_index(
        self, seed: int, tool_name: str, num_candidates: int
    ) -> int:
        """Select a non-base (non-zero) candidate index.

        Returns an index in [1, num_candidates), deterministically based on seed.
        """
        non_base_count = num_candidates - 1
        h = hashlib.sha256(f"{seed}:{tool_name}:desc:mut".encode())
        offset = int.from_bytes(h.digest()[:4], "big") % non_base_count
        return 1 + offset


def mutate_description(
    base_description: str,
    candidates: list[str] | None = None,
    seed: int = 0,
    *,
    mutate: bool = True,
    tool_name: str = "unknown",
) -> str:
    """Convenience function for description mutation.

    Args:
        base_description: The base description.
        candidates: List of candidate descriptions.
        seed: Random seed for deterministic selection.
        mutate: If True, select from non-base candidates.
        tool_name: Canonical tool name for error messages and hashing.

    Returns:
        The selected description.
    """
    return DescriptionMutator().mutate(
        base_description, candidates, seed, mutate=mutate, tool_name=tool_name
    )
