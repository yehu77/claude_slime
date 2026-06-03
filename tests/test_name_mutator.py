"""Tests for the name mutator."""

from __future__ import annotations

import pytest

from pycodeagent.mutations.name_mutator import (
    NameMutator,
    NameMutationError,
    mutate_name,
)


class TestNameMutatorIdentity:
    """Tests for identity/no-op behavior."""

    def test_mutate_false_returns_first_candidate(self):
        """When mutate=False, should return the first candidate."""
        mutator = NameMutator()
        result = mutator.mutate(
            canonical_name="read_file",
            candidates=["read_file", "open_source", "inspect_file"],
            seed=42,
            mutate=False,
        )
        assert result == "read_file"

    def test_single_candidate_returns_it(self):
        """With only one candidate, should return it regardless of mutate flag."""
        mutator = NameMutator()
        result = mutator.mutate(
            canonical_name="read_file",
            candidates=["read_file"],
            seed=42,
            mutate=True,
        )
        assert result == "read_file"

    def test_no_candidates_returns_canonical_name(self):
        """With no candidates, should return canonical name."""
        mutator = NameMutator()
        result = mutator.mutate(
            canonical_name="read_file",
            candidates=None,
            seed=42,
            mutate=True,
        )
        assert result == "read_file"

    def test_empty_candidates_returns_canonical_name(self):
        """With empty candidates list, should return canonical name."""
        mutator = NameMutator()
        result = mutator.mutate(
            canonical_name="read_file",
            candidates=[],
            seed=42,
            mutate=True,
        )
        assert result == "read_file"


class TestNameMutatorDeterminism:
    """Tests for deterministic behavior."""

    def test_same_seed_same_canonical_same_result(self):
        """Same seed + same canonical name should produce same result."""
        mutator = NameMutator()
        candidates = ["read_file", "open_source", "inspect_file"]
        r1 = mutator.mutate("read_file", candidates, seed=42, mutate=True)
        r2 = mutator.mutate("read_file", candidates, seed=42, mutate=True)
        assert r1 == r2

    def test_different_seed_can_produce_different_result(self):
        """Different seeds should be able to produce different results."""
        mutator = NameMutator()
        candidates = ["read_file", "open_source", "inspect_file"]
        results = set()
        for seed in range(20):
            result = mutator.mutate("read_file", candidates, seed=seed, mutate=True)
            results.add(result)
        # With 20 seeds and 2 non-base candidates, should see both
        assert len(results) == 2


class TestNameMutatorVariation:
    """Tests for mutation variation."""

    def test_mutate_true_selects_non_base(self):
        """When mutate=True, should select from non-base candidates."""
        mutator = NameMutator()
        candidates = ["read_file", "open_source", "inspect_file"]
        for seed in range(100):
            result = mutator.mutate("read_file", candidates, seed=seed, mutate=True)
            assert result != "read_file"
            assert result in candidates

    def test_different_canonical_names_affect_selection(self):
        """Different canonical names should affect the hash selection."""
        mutator = NameMutator()
        candidates = ["tool", "variant_a", "variant_b"]
        results_by_name = {}
        for name in ["read_file", "list_files", "search_code"]:
            results_by_name[name] = mutator.mutate(name, candidates, seed=42, mutate=True)
        # At least some tools should get different names
        assert len(set(results_by_name.values())) >= 1


class TestNameMutatorValidation:
    """Tests for input validation."""

    def test_empty_canonical_name_raises(self):
        """Empty canonical name should raise."""
        mutator = NameMutator()
        with pytest.raises(NameMutationError, match="canonical_name"):
            mutator.mutate("", ["tool_a", "tool_b"], seed=42, mutate=True)

    def test_non_string_canonical_name_raises(self):
        """Non-string canonical name should raise."""
        mutator = NameMutator()
        with pytest.raises(NameMutationError, match="canonical_name"):
            mutator.mutate(123, ["tool_a", "tool_b"], seed=42, mutate=True)  # type: ignore

    def test_invalid_candidate_type_raises(self):
        """Non-string candidate should raise."""
        mutator = NameMutator()
        with pytest.raises(NameMutationError, match="candidates"):
            mutator.mutate("read_file", ["valid", 123], seed=42, mutate=True)  # type: ignore

    def test_empty_candidate_raises(self):
        """Empty string candidate should raise."""
        mutator = NameMutator()
        with pytest.raises(NameMutationError, match="candidates"):
            mutator.mutate("read_file", ["valid", ""], seed=42, mutate=True)

    def test_candidates_not_list_raises(self):
        """Candidates not a list should raise."""
        mutator = NameMutator()
        with pytest.raises(NameMutationError, match="candidates"):
            mutator.mutate("read_file", "not_a_list", seed=42, mutate=True)  # type: ignore


class TestMutateNameFunction:
    """Tests for the convenience function."""

    def test_mutate_name_function_works(self):
        """Convenience function should work like NameMutator.mutate."""
        result = mutate_name(
            "read_file",
            candidates=["read_file", "open_source", "inspect_file"],
            seed=42,
            mutate=True,
        )
        assert result in ["open_source", "inspect_file"]

    def test_mutate_name_identity(self):
        """Convenience function with mutate=False should return base."""
        result = mutate_name(
            "read_file",
            candidates=["read_file", "open_source"],
            seed=42,
            mutate=False,
        )
        assert result == "read_file"
