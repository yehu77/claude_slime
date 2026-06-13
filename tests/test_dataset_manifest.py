"""Tests for dataset manifest model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.rl.dataset_manifest import (
    DatasetManifest,
    FilterConfig,
    RewardSummary,
    StatusCounts,
    VerifierCounts,
    build_reward_summary,
    build_status_counts,
    build_verifier_counts,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "dataset_manifest"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


# ─── RewardSummary tests ───


class TestRewardSummary:
    """Tests for RewardSummary and build_reward_summary."""

    def test_build_reward_summary_basic(self):
        """Should compute correct min/max/mean/total."""
        summary = build_reward_summary([1.0, 0.5, 0.0])
        assert summary.min == 0.0
        assert summary.max == 1.0
        assert summary.mean == pytest.approx(0.5)
        assert summary.total == pytest.approx(1.5)
        assert summary.count == 3

    def test_build_reward_summary_empty(self):
        """Empty list should return zero summary."""
        summary = build_reward_summary([])
        assert summary.min == 0.0
        assert summary.max == 0.0
        assert summary.mean == 0.0
        assert summary.total == 0.0
        assert summary.count == 0

    def test_build_reward_summary_single(self):
        """Single value should have min == max == mean."""
        summary = build_reward_summary([0.75])
        assert summary.min == 0.75
        assert summary.max == 0.75
        assert summary.mean == 0.75
        assert summary.count == 1


# ─── StatusCounts tests ───


class TestStatusCounts:
    """Tests for StatusCounts and build_status_counts."""

    def test_build_status_counts_basic(self):
        """Should count each status correctly."""
        counts = build_status_counts(["completed", "completed", "failed", "error", "timeout"])
        assert counts.completed == 2
        assert counts.failed == 1
        assert counts.error == 1
        assert counts.timeout == 1

    def test_build_status_counts_empty(self):
        """Empty list should have zero counts."""
        counts = build_status_counts([])
        assert counts.completed == 0
        assert counts.failed == 0
        assert counts.error == 0
        assert counts.timeout == 0

    def test_build_status_counts_unknown_ignored(self):
        """Unknown statuses should be ignored."""
        counts = build_status_counts(["completed", "unknown_status"])
        assert counts.completed == 1


# ─── VerifierCounts tests ───


class TestVerifierCounts:
    """Tests for VerifierCounts and build_verifier_counts."""

    def test_build_verifier_counts_basic(self):
        """Should count passed and failed correctly."""
        counts = build_verifier_counts([True, True, False])
        assert counts.passed == 2
        assert counts.failed == 1

    def test_build_verifier_counts_empty(self):
        """Empty list should have zero counts."""
        counts = build_verifier_counts([])
        assert counts.passed == 0
        assert counts.failed == 0


# ─── FilterConfig tests ───


class TestFilterConfig:
    """Tests for FilterConfig."""

    def test_default_filter_config(self):
        """Default filter config should include all runs."""
        config = FilterConfig()
        assert config.include_failed is True
        assert config.allowed_statuses is None
        assert config.verifier_passed is None
        assert config.min_reward is None
        assert config.task_ids is None
        assert config.profile_ids is None

    def test_filter_config_to_dict(self):
        """FilterConfig should serialize to dict."""
        config = FilterConfig(min_reward=0.5, include_failed=False)
        d = config.to_dict()
        assert d["min_reward"] == 0.5
        assert d["include_failed"] is False


# ─── DatasetManifest tests ───


class TestDatasetManifest:
    """Tests for DatasetManifest creation, save/load, and serialization."""

    def _make_manifest(self, **overrides) -> DatasetManifest:
        defaults = dict(
            dataset_id="test_ds",
            source_type="experiment",
            source_path="/tmp/exp",
            sample_count=10,
            rollout_count=10,
            reward_summary=build_reward_summary([1.0, 0.5, 0.0]),
        )
        defaults.update(overrides)
        return DatasetManifest(**defaults)

    def test_manifest_creation(self):
        """Should create manifest with required fields."""
        manifest = self._make_manifest()
        assert manifest.dataset_id == "test_ds"
        assert manifest.source_type == "experiment"
        assert manifest.sample_count == 10
        assert manifest.rollout_count == 10
        assert manifest.reward_summary.count == 3

    def test_manifest_created_at_defaults_to_none(self):
        """Manifest should not inject a nondeterministic created_at by default."""
        manifest = self._make_manifest()
        assert manifest.created_at is None

    def test_manifest_default_counts(self):
        """Default status and verifier counts should be zeros."""
        manifest = self._make_manifest()
        assert manifest.status_counts.completed == 0
        assert manifest.verifier_counts.passed == 0

    def test_manifest_with_counts(self):
        """Should accept status and verifier counts."""
        manifest = self._make_manifest(
            status_counts=build_status_counts(["completed", "completed", "failed"]),
            verifier_counts=build_verifier_counts([True, False]),
        )
        assert manifest.status_counts.completed == 2
        assert manifest.status_counts.failed == 1
        assert manifest.verifier_counts.passed == 1
        assert manifest.verifier_counts.failed == 1

    def test_save_and_load_roundtrip(self):
        """Save/load should preserve all fields."""
        output_dir = _get_test_dir()
        try:
            manifest = self._make_manifest(
                task_ids=["task_001", "task_002"],
                profile_ids=["base_0", "schema_only_0"],
                status_counts=build_status_counts(["completed", "completed"]),
                verifier_counts=build_verifier_counts([True, False]),
                filter_config=FilterConfig(min_reward=0.1, include_failed=False),
            )
            path = output_dir / "dataset_manifest.json"
            manifest.save(path)

            loaded = DatasetManifest.load(path)
            assert loaded.dataset_id == manifest.dataset_id
            assert loaded.source_type == manifest.source_type
            assert loaded.sample_count == manifest.sample_count
            assert loaded.rollout_count == manifest.rollout_count
            assert loaded.task_ids == manifest.task_ids
            assert loaded.profile_ids == manifest.profile_ids
            assert loaded.reward_summary.min == manifest.reward_summary.min
            assert loaded.reward_summary.max == manifest.reward_summary.max
            assert loaded.reward_summary.mean == pytest.approx(manifest.reward_summary.mean)
            assert loaded.status_counts.completed == manifest.status_counts.completed
            assert loaded.verifier_counts.passed == manifest.verifier_counts.passed
            assert loaded.filter_config.min_reward == manifest.filter_config.min_reward
            assert loaded.filter_config.include_failed == manifest.filter_config.include_failed
            assert loaded.created_at is None
        finally:
            _cleanup(output_dir)

    def test_deterministic_serialization(self):
        """Same manifest should produce same JSON on repeated saves."""
        output_dir = _get_test_dir()
        try:
            manifest = self._make_manifest(
                task_ids=["task_001"],
                profile_ids=["base_0"],
                filter_config=FilterConfig(min_reward=0.5),
                created_at="2025-01-01T00:00:00+00:00",
            )
            path = output_dir / "manifest.json"

            manifest.save(path)
            content1 = path.read_text()

            manifest.save(path)
            content2 = path.read_text()

            assert content1 == content2
        finally:
            _cleanup(output_dir)

    def test_to_dict(self):
        """to_dict should produce JSON-serializable dict."""
        manifest = self._make_manifest()
        d = manifest.to_dict()
        assert isinstance(d, dict)
        assert "dataset_id" in d
        assert "reward_summary" in d
        assert "created_at" not in d
        # Should be JSON-serializable
        json.dumps(d)

    def test_manifest_json_readable(self):
        """Saved manifest should be human-readable JSON."""
        output_dir = _get_test_dir()
        try:
            manifest = self._make_manifest(
                task_ids=["task_001"],
                filter_config=FilterConfig(min_reward=0.1),
            )
            path = output_dir / "manifest.json"
            manifest.save(path)

            data = json.loads(path.read_text())
            assert data["dataset_id"] == "test_ds"
            assert data["filter_config"]["min_reward"] == 0.1
            assert "created_at" not in data
        finally:
            _cleanup(output_dir)
