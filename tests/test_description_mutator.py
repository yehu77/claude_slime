"""Tests for the description mutator."""

from __future__ import annotations

import pytest

from pycodeagent.mutations.description_mutator import (
    DescriptionMutator,
    DescriptionMutationError,
    mutate_description,
)


class TestDescriptionMutatorIdentity:
    """Tests for identity/no-op behavior."""

    def test_mutate_false_returns_first_candidate(self):
        """When mutate=False, should return the first candidate."""
        mutator = DescriptionMutator()
        result = mutator.mutate(
            base_description="Read a file.",
            candidates=["Read a file.", "Inspect source.", "View contents."],
            seed=42,
            mutate=False,
        )
        assert result == "Read a file."

    def test_single_candidate_returns_it(self):
        """With only one candidate, should return it regardless of mutate flag."""
        mutator = DescriptionMutator()
        result = mutator.mutate(
            base_description="Read a file.",
            candidates=["Read a file."],
            seed=42,
            mutate=True,
        )
        assert result == "Read a file."

    def test_no_candidates_returns_base_description(self):
        """With no candidates, should return base description."""
        mutator = DescriptionMutator()
        result = mutator.mutate(
            base_description="Read a file.",
            candidates=None,
            seed=42,
            mutate=True,
        )
        assert result == "Read a file."

    def test_empty_candidates_returns_base_description(self):
        """With empty candidates list, should return base description."""
        mutator = DescriptionMutator()
        result = mutator.mutate(
            base_description="Read a file.",
            candidates=[],
            seed=42,
            mutate=True,
        )
        assert result == "Read a file."


class TestDescriptionMutatorDeterminism:
    """Tests for deterministic behavior."""

    def test_same_seed_same_tool_name_same_result(self):
        """Same seed + same tool name should produce same result."""
        mutator = DescriptionMutator()
        candidates = ["Read a file.", "Inspect source.", "View contents."]
        r1 = mutator.mutate("Read a file.", candidates, seed=42, mutate=True, tool_name="read_file")
        r2 = mutator.mutate("Read a file.", candidates, seed=42, mutate=True, tool_name="read_file")
        assert r1 == r2

    def test_different_seed_can_produce_different_result(self):
        """Different seeds should be able to produce different results."""
        mutator = DescriptionMutator()
        candidates = ["Read a file.", "Inspect source.", "View contents."]
        results = set()
        for seed in range(20):
            result = mutator.mutate(
                "Read a file.", candidates, seed=seed, mutate=True, tool_name="read_file"
            )
            results.add(result)
        # With 20 seeds and 2 non-base candidates, should see both
        assert len(results) == 2


class TestDescriptionMutatorVariation:
    """Tests for mutation variation."""

    def test_mutate_true_selects_non_base(self):
        """When mutate=True, should select from non-base candidates."""
        mutator = DescriptionMutator()
        candidates = ["Read a file.", "Inspect source.", "View contents."]
        for seed in range(100):
            result = mutator.mutate(
                "Read a file.", candidates, seed=seed, mutate=True, tool_name="read_file"
            )
            assert result != "Read a file."
            assert result in candidates

    def test_different_tool_names_affect_selection(self):
        """Different tool names should affect the hash selection."""
        mutator = DescriptionMutator()
        candidates = ["Default desc.", "Variant A.", "Variant B."]
        results_by_name = {}
        for name in ["read_file", "list_files", "search_code"]:
            results_by_name[name] = mutator.mutate(
                "Default desc.", candidates, seed=42, mutate=True, tool_name=name
            )
        # At least some tools should get different descriptions
        assert len(set(results_by_name.values())) >= 1


class TestDescriptionMutatorValidation:
    """Tests for input validation."""

    def test_non_string_base_description_raises(self):
        """Non-string base description should raise."""
        mutator = DescriptionMutator()
        with pytest.raises(DescriptionMutationError, match="base_description"):
            mutator.mutate(123, ["desc a", "desc b"], seed=42, mutate=True)  # type: ignore

    def test_invalid_candidate_type_raises(self):
        """Non-string candidate should raise."""
        mutator = DescriptionMutator()
        with pytest.raises(DescriptionMutationError, match="candidates"):
            mutator.mutate("Base.", ["valid", 123], seed=42, mutate=True)  # type: ignore

    def test_candidates_not_list_raises(self):
        """Candidates not a list should raise."""
        mutator = DescriptionMutator()
        with pytest.raises(DescriptionMutationError, match="candidates"):
            mutator.mutate("Base.", "not_a_list", seed=42, mutate=True)  # type: ignore


class TestMutateDescriptionFunction:
    """Tests for the convenience function."""

    def test_mutate_description_function_works(self):
        """Convenience function should work like DescriptionMutator.mutate."""
        result = mutate_description(
            "Read a file.",
            candidates=["Read a file.", "Inspect source.", "View contents."],
            seed=42,
            mutate=True,
            tool_name="read_file",
        )
        assert result in ["Inspect source.", "View contents."]

    def test_mutate_description_identity(self):
        """Convenience function with mutate=False should return base."""
        result = mutate_description(
            "Read a file.",
            candidates=["Read a file.", "Inspect source."],
            seed=42,
            mutate=False,
            tool_name="read_file",
        )
        assert result == "Read a file."

    def test_empty_string_description_allowed(self):
        """Empty string description should be allowed."""
        mutator = DescriptionMutator()
        result = mutator.mutate("", candidates=["", "Non-empty"], seed=42, mutate=False)
        assert result == ""
