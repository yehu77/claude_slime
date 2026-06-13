"""Tests for batch rollout dataset builder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.rl.dataset_builder import (
    DatasetBuildResult,
    RolloutDatasetBuilder,
    TrajectoryLoadError,
    build_rollout_dataset,
    discover_run_dirs,
)
from pycodeagent.rl.dataset_manifest import (
    DatasetManifest,
    FilterConfig,
    build_reward_summary,
    build_status_counts,
    build_verifier_counts,
)
from pycodeagent.trajectory.schema import (
    Message,
    Role,
    RunStatus,
    ToolCall,
    ToolResult,
    Trajectory,
    VerifyResult,
)
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "dataset_builder"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


# ─── Trajectory helpers ───


def make_trajectory(
    *,
    task_id: str = "task_001",
    tool_profile_id: str = "base",
    reward: float = 1.0,
    status: RunStatus = RunStatus.COMPLETED,
    verifier: VerifyResult | None = None,
) -> Trajectory:
    """Create a minimal trajectory for testing."""
    if verifier is None:
        verifier = VerifyResult(passed=True, score=1.0)
    return Trajectory(
        task_id=task_id,
        repo="examples/buggy_calc",
        tool_profile_id=tool_profile_id,
        messages=[
            Message(role=Role.SYSTEM, content="You are a coding agent."),
            Message(role=Role.USER, content="Fix the failing tests."),
            Message(role=Role.ASSISTANT, content="I'll fix it."),
        ],
        reward=reward,
        status=status,
        verifier=verifier,
    )


def _write_trajectory(run_dir: Path, trajectory: Trajectory) -> Path:
    """Write a trajectory.json into a run directory."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "trajectory.json"
    path.write_text(trajectory.model_dump_json(), encoding="utf-8")
    return path


def _make_experiment_dir(
    base: Path,
    *,
    trajectories: list[Trajectory],
) -> Path:
    """Create a fake experiment directory structure.

    Structure:
    base/
      runs/
        seed_0/
          base/
            task_001__profile_base/
              trajectory.json
            ...
    """
    exp_dir = base / "experiment"
    for i, traj in enumerate(trajectories):
        run_dir = (
            exp_dir
            / "runs"
            / "seed_0"
            / "base"
            / f"{traj.task_id}__{traj.tool_profile_id}"
        )
        _write_trajectory(run_dir, traj)
    return exp_dir


def _make_batch_dir(
    base: Path,
    *,
    trajectories: list[Trajectory],
) -> Path:
    """Create a batch directory matching real BatchRunner output structure.

    Real BatchRunner structure:
    base/
      summary.json
      runs.jsonl
      task_001__profile_base/
        trajectory.json
      ...
    """
    batch_dir = base / "batch"
    batch_dir.mkdir(parents=True, exist_ok=True)
    for traj in trajectories:
        # Run dirs directly under batch_dir (real BatchRunner layout)
        run_dir = batch_dir / f"{traj.task_id}__{traj.tool_profile_id}"
        _write_trajectory(run_dir, traj)
    return batch_dir


def _make_batch_dir_legacy(
    base: Path,
    *,
    trajectories: list[Trajectory],
) -> Path:
    """Create a batch directory with legacy runs/ subdir structure.

    Legacy structure:
    base/
      runs/
        task_001__profile_base/
          trajectory.json
        ...
    """
    batch_dir = base / "batch_legacy"
    for traj in trajectories:
        run_dir = batch_dir / "runs" / f"{traj.task_id}__{traj.tool_profile_id}"
        _write_trajectory(run_dir, traj)
    return batch_dir


# ─── RolloutDatasetBuilder tests ───


class TestRolloutDatasetBuilderExperiment:
    """Tests for build_from_experiment."""

    def test_basic_build(self):
        """Should build dataset from experiment directory."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="task_001", reward=1.0),
                make_trajectory(task_id="task_002", reward=0.5, tool_profile_id="schema_v1"),
            ]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder(dataset_id="test_ds")
            result = builder.build_from_experiment(exp_dir, output_dir)

            assert isinstance(result, DatasetBuildResult)
            assert result.sample_count == 2
            assert result.rollout_count == 2
            assert result.output_dir == output_dir
            assert result.manifest.dataset_id == "test_ds"
            assert result.manifest.source_type == "experiment"
            assert result.manifest.source_path == str(exp_dir)
        finally:
            _cleanup(tmp)

    def test_manifest_written(self):
        """Should write dataset_manifest.json."""
        tmp = _get_test_dir()
        try:
            trajectories = [make_trajectory()]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            builder.build_from_experiment(exp_dir, output_dir)

            manifest_path = output_dir / "dataset_manifest.json"
            assert manifest_path.exists()

            loaded = DatasetManifest.load(manifest_path)
            assert loaded.sample_count == 1
            assert loaded.rollout_count == 1
            raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert "created_at" not in raw_manifest
        finally:
            _cleanup(tmp)

    def test_rollouts_jsonl_written(self):
        """Should write rollouts.jsonl with correct count."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="task_001"),
                make_trajectory(task_id="task_002"),
            ]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            builder.build_from_experiment(exp_dir, output_dir)

            rollouts_path = output_dir / "rollouts.jsonl"
            assert rollouts_path.exists()
            lines = rollouts_path.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 2
            for line in lines:
                data = json.loads(line)
                assert "task_id" in data
        finally:
            _cleanup(tmp)

    def test_samples_jsonl_written(self):
        """Should write samples.jsonl with correct count."""
        tmp = _get_test_dir()
        try:
            trajectories = [make_trajectory()]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            builder.build_from_experiment(exp_dir, output_dir)

            samples_path = output_dir / "samples.jsonl"
            assert samples_path.exists()
            lines = samples_path.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 1
        finally:
            _cleanup(tmp)

    def test_manifest_statistics(self):
        """Should compute correct reward/status/verifier statistics."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="t1", reward=1.0, status=RunStatus.COMPLETED, verifier=VerifyResult(passed=True, score=1.0)),
                make_trajectory(task_id="t2", reward=0.0, status=RunStatus.FAILED, verifier=VerifyResult(passed=False, score=0.0)),
                make_trajectory(task_id="t3", reward=0.5, status=RunStatus.COMPLETED, verifier=VerifyResult(passed=True, score=0.5)),
            ]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_experiment(exp_dir, output_dir)

            m = result.manifest
            assert m.sample_count == 3
            assert m.reward_summary.min == 0.0
            assert m.reward_summary.max == 1.0
            assert m.reward_summary.mean == pytest.approx(0.5)
            assert m.status_counts.completed == 2
            assert m.status_counts.failed == 1
            assert m.verifier_counts.passed == 2
            assert m.verifier_counts.failed == 1
            assert sorted(m.task_ids) == ["t1", "t2", "t3"]
        finally:
            _cleanup(tmp)

    def test_deterministic_ordering(self):
        """Runs should be processed in sorted order for determinism."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="task_002"),
                make_trajectory(task_id="task_001"),
            ]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_experiment(exp_dir, output_dir)

            assert result.manifest.task_ids == ["task_001", "task_002"]
        finally:
            _cleanup(tmp)

    def test_empty_experiment(self):
        """Should handle experiment with no runs gracefully."""
        tmp = _get_test_dir()
        try:
            exp_dir = tmp / "empty_exp"
            exp_dir.mkdir(parents=True, exist_ok=True)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_experiment(exp_dir, output_dir)

            assert result.sample_count == 0
            assert result.rollout_count == 0
            assert result.manifest.reward_summary.count == 0
        finally:
            _cleanup(tmp)


class TestRolloutDatasetBuilderBatch:
    """Tests for build_from_batch with real BatchRunner layout."""

    def test_real_batch_layout(self):
        """Should build dataset from real BatchRunner output (runs directly under batch_dir)."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="task_001"),
                make_trajectory(task_id="task_002"),
            ]
            batch_dir = _make_batch_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder(dataset_id="batch_ds")
            result = builder.build_from_batch(batch_dir, output_dir)

            assert result.sample_count == 2
            assert result.manifest.source_type == "batch"
            assert result.manifest.source_path == str(batch_dir)
        finally:
            _cleanup(tmp)

    def test_legacy_batch_layout(self):
        """Should also support legacy runs/ subdirectory layout."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="task_001"),
                make_trajectory(task_id="task_002"),
            ]
            batch_dir = _make_batch_dir_legacy(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder(dataset_id="legacy_ds")
            result = builder.build_from_batch(batch_dir, output_dir)

            assert result.sample_count == 2
            assert result.manifest.source_type == "batch"
        finally:
            _cleanup(tmp)

    def test_real_layout_preferred_over_legacy(self):
        """When both layouts exist, real layout (direct runs) should be preferred."""
        tmp = _get_test_dir()
        try:
            batch_dir = tmp / "mixed_batch"
            batch_dir.mkdir(parents=True, exist_ok=True)

            # Real layout run
            traj_real = make_trajectory(task_id="real_task")
            _write_trajectory(batch_dir / "real_task__base", traj_real)

            # Legacy layout run (should be ignored when real layout exists)
            traj_legacy = make_trajectory(task_id="legacy_task")
            _write_trajectory(batch_dir / "runs" / "legacy_task__base", traj_legacy)

            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_batch(batch_dir, output_dir)

            # Should only find the real layout run
            assert result.sample_count == 1
            assert result.manifest.task_ids == ["real_task"]
        finally:
            _cleanup(tmp)

    def test_empty_batch(self):
        """Should handle empty batch directory."""
        tmp = _get_test_dir()
        try:
            batch_dir = tmp / "empty_batch"
            batch_dir.mkdir(parents=True, exist_ok=True)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_batch(batch_dir, output_dir)

            assert result.sample_count == 0
        finally:
            _cleanup(tmp)

    def test_batch_with_metadata_files(self):
        """Should ignore summary.json and runs.jsonl at batch root."""
        tmp = _get_test_dir()
        try:
            batch_dir = tmp / "batch_with_meta"
            batch_dir.mkdir(parents=True, exist_ok=True)

            # Write metadata files (should be ignored)
            (batch_dir / "summary.json").write_text("{}", encoding="utf-8")
            (batch_dir / "runs.jsonl").write_text("\n", encoding="utf-8")

            # Write a run
            traj = make_trajectory(task_id="task_001")
            _write_trajectory(batch_dir / "task_001__base", traj)

            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_batch(batch_dir, output_dir)

            assert result.sample_count == 1
        finally:
            _cleanup(tmp)


class TestRolloutDatasetBuilderRunDirs:
    """Tests for build_from_run_dirs."""

    def test_explicit_run_dirs(self):
        """Should build dataset from explicit list of run directories."""
        tmp = _get_test_dir()
        try:
            traj1 = make_trajectory(task_id="t1")
            traj2 = make_trajectory(task_id="t2")

            run_dir1 = tmp / "run1"
            run_dir2 = tmp / "run2"
            _write_trajectory(run_dir1, traj1)
            _write_trajectory(run_dir2, traj2)

            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_run_dirs(
                [run_dir1, run_dir2],
                output_dir,
                source_type="runs",
                source_path="manual",
            )

            assert result.sample_count == 2
            assert result.manifest.source_type == "runs"
            assert result.manifest.source_path == "manual"
        finally:
            _cleanup(tmp)


class TestDiscoverRunDirs:
    """Tests for the public run-directory discovery helper."""

    def test_discovers_experiment_runs(self):
        tmp = _get_test_dir()
        try:
            exp_dir = _make_experiment_dir(
                tmp,
                trajectories=[
                    make_trajectory(task_id="task_001"),
                    make_trajectory(task_id="task_002"),
                ],
            )
            run_dirs = discover_run_dirs(exp_dir, source_type="experiment")
            assert len(run_dirs) == 2
            assert all((run_dir / "trajectory.json").exists() for run_dir in run_dirs)
        finally:
            _cleanup(tmp)

    def test_discovers_batch_runs(self):
        tmp = _get_test_dir()
        try:
            batch_dir = _make_batch_dir(
                tmp,
                trajectories=[
                    make_trajectory(task_id="task_001"),
                    make_trajectory(task_id="task_002"),
                ],
            )
            run_dirs = discover_run_dirs(batch_dir, source_type="batch")
            assert len(run_dirs) == 2
            assert all((run_dir / "trajectory.json").exists() for run_dir in run_dirs)
        finally:
            _cleanup(tmp)

    def test_discovers_study_runs(self):
        tmp = _get_test_dir()
        try:
            study_dir = tmp / "study"
            experiments_dir = study_dir / "experiments"
            _write_trajectory(
                experiments_dir / "exp_a" / "runs" / "seed_0" / "base" / "task_a__base",
                make_trajectory(task_id="task_a"),
            )
            _write_trajectory(
                experiments_dir / "exp_b" / "runs" / "seed_0" / "base" / "task_b__base",
                make_trajectory(task_id="task_b"),
            )

            run_dirs = discover_run_dirs(study_dir, source_type="study")
            assert len(run_dirs) == 2
            assert all((run_dir / "trajectory.json").exists() for run_dir in run_dirs)
        finally:
            _cleanup(tmp)

    def test_invalid_source_type_raises(self):
        with pytest.raises(ValueError, match="Unknown source_type"):
            discover_run_dirs("dummy", source_type="unknown")

    def test_missing_trajectory_skipped(self):
        """Run dirs without trajectory.json should be skipped."""
        tmp = _get_test_dir()
        try:
            traj1 = make_trajectory(task_id="t1")
            run_dir1 = tmp / "run1"
            _write_trajectory(run_dir1, traj1)

            run_dir2 = tmp / "run2"
            run_dir2.mkdir(parents=True, exist_ok=True)
            # No trajectory.json in run_dir2

            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_run_dirs(
                [run_dir1, run_dir2],
                output_dir,
            )

            assert result.sample_count == 1
        finally:
            _cleanup(tmp)

    def test_invalid_trajectory_raises(self):
        """Invalid JSON in trajectory.json should fail fast."""
        tmp = _get_test_dir()
        try:
            traj1 = make_trajectory(task_id="t1")
            run_dir1 = tmp / "run1"
            _write_trajectory(run_dir1, traj1)

            run_dir2 = tmp / "run2"
            run_dir2.mkdir(parents=True, exist_ok=True)
            (run_dir2 / "trajectory.json").write_text("NOT VALID JSON{{{{", encoding="utf-8")

            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            with pytest.raises(TrajectoryLoadError, match="Invalid JSON"):
                builder.build_from_run_dirs(
                    [run_dir1, run_dir2],
                    output_dir,
                )
        finally:
            _cleanup(tmp)


class TestFiltering:
    """Tests for filter configuration behavior."""

    def test_include_failed_false(self):
        """include_failed=False should exclude non-completed runs."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="t1", status=RunStatus.COMPLETED),
                make_trajectory(task_id="t2", status=RunStatus.FAILED),
                make_trajectory(task_id="t3", status=RunStatus.TIMEOUT),
            ]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_experiment(
                exp_dir, output_dir,
                filter_config=FilterConfig(include_failed=False),
            )

            assert result.sample_count == 1
            assert result.manifest.task_ids == ["t1"]
        finally:
            _cleanup(tmp)

    def test_allowed_statuses(self):
        """allowed_statuses should only include listed statuses."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="t1", status=RunStatus.COMPLETED),
                make_trajectory(task_id="t2", status=RunStatus.FAILED),
                make_trajectory(task_id="t3", status=RunStatus.ERROR),
            ]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_experiment(
                exp_dir, output_dir,
                filter_config=FilterConfig(allowed_statuses=["completed", "error"]),
            )

            assert result.sample_count == 2
            assert sorted(result.manifest.task_ids) == ["t1", "t3"]
        finally:
            _cleanup(tmp)

    def test_verifier_passed_true(self):
        """verifier_passed=True should only include verified runs."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="t1", verifier=VerifyResult(passed=True, score=1.0)),
                make_trajectory(task_id="t2", verifier=VerifyResult(passed=False, score=0.0)),
            ]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_experiment(
                exp_dir, output_dir,
                filter_config=FilterConfig(verifier_passed=True),
            )

            assert result.sample_count == 1
            assert result.manifest.task_ids == ["t1"]
        finally:
            _cleanup(tmp)

    def test_verifier_passed_false(self):
        """verifier_passed=False should only include non-verified runs."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="t1", verifier=VerifyResult(passed=True, score=1.0)),
                make_trajectory(task_id="t2", verifier=VerifyResult(passed=False, score=0.0)),
            ]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_experiment(
                exp_dir, output_dir,
                filter_config=FilterConfig(verifier_passed=False),
            )

            assert result.sample_count == 1
            assert result.manifest.task_ids == ["t2"]
        finally:
            _cleanup(tmp)

    def test_min_reward(self):
        """min_reward should filter out low-reward runs."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="t1", reward=1.0),
                make_trajectory(task_id="t2", reward=0.3),
                make_trajectory(task_id="t3", reward=0.0),
            ]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_experiment(
                exp_dir, output_dir,
                filter_config=FilterConfig(min_reward=0.5),
            )

            assert result.sample_count == 1
            assert result.manifest.task_ids == ["t1"]
        finally:
            _cleanup(tmp)

    def test_task_ids_filter(self):
        """task_ids filter should only include listed tasks."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="task_001"),
                make_trajectory(task_id="task_002"),
                make_trajectory(task_id="task_003"),
            ]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_experiment(
                exp_dir, output_dir,
                filter_config=FilterConfig(task_ids=["task_001", "task_003"]),
            )

            assert result.sample_count == 2
            assert sorted(result.manifest.task_ids) == ["task_001", "task_003"]
        finally:
            _cleanup(tmp)

    def test_profile_ids_filter(self):
        """profile_ids filter should only include listed profiles."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="t1", tool_profile_id="base"),
                make_trajectory(task_id="t2", tool_profile_id="schema_v1"),
            ]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_experiment(
                exp_dir, output_dir,
                filter_config=FilterConfig(profile_ids=["base"]),
            )

            assert result.sample_count == 1
            assert result.manifest.profile_ids == ["base"]
        finally:
            _cleanup(tmp)

    def test_combined_filters(self):
        """Multiple filters should be ANDed together."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="t1", reward=1.0, status=RunStatus.COMPLETED),
                make_trajectory(task_id="t2", reward=0.3, status=RunStatus.COMPLETED),
                make_trajectory(task_id="t3", reward=1.0, status=RunStatus.FAILED),
            ]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_experiment(
                exp_dir, output_dir,
                filter_config=FilterConfig(min_reward=0.5, include_failed=False),
            )

            assert result.sample_count == 1
            assert result.manifest.task_ids == ["t1"]
        finally:
            _cleanup(tmp)

    def test_no_verifier_treated_as_not_passed(self):
        """Trajectories with no verifier should be treated as not passed."""
        tmp = _get_test_dir()
        try:
            traj_with = make_trajectory(task_id="t1", verifier=VerifyResult(passed=True, score=1.0))
            traj_without = make_trajectory(task_id="t2", verifier=None)
            # Override verifier to None
            traj_without.verifier = None

            trajectories = [traj_with, traj_without]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_experiment(
                exp_dir, output_dir,
                filter_config=FilterConfig(verifier_passed=True),
            )

            assert result.sample_count == 1
            assert result.manifest.task_ids == ["t1"]
        finally:
            _cleanup(tmp)

    def test_filter_config_in_manifest(self):
        """Filter config should be recorded in manifest."""
        tmp = _get_test_dir()
        try:
            trajectories = [make_trajectory()]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            fc = FilterConfig(min_reward=0.1, include_failed=False, task_ids=["task_001"])
            builder = RolloutDatasetBuilder()
            result = builder.build_from_experiment(
                exp_dir, output_dir,
                filter_config=fc,
            )

            assert result.manifest.filter_config.min_reward == 0.1
            assert result.manifest.filter_config.include_failed is False
            assert result.manifest.filter_config.task_ids == ["task_001"]
        finally:
            _cleanup(tmp)


class TestBatchFiltering:
    """Tests for filter configuration on batch inputs (regression protection)."""

    def test_batch_filter_include_failed_false(self):
        """include_failed=False should work on batch layout."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="t1", status=RunStatus.COMPLETED),
                make_trajectory(task_id="t2", status=RunStatus.FAILED),
            ]
            batch_dir = _make_batch_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_batch(
                batch_dir, output_dir,
                filter_config=FilterConfig(include_failed=False),
            )

            assert result.sample_count == 1
            assert result.manifest.task_ids == ["t1"]
        finally:
            _cleanup(tmp)

    def test_batch_filter_min_reward(self):
        """min_reward filter should work on batch layout."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="t1", reward=1.0),
                make_trajectory(task_id="t2", reward=0.3),
            ]
            batch_dir = _make_batch_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_batch(
                batch_dir, output_dir,
                filter_config=FilterConfig(min_reward=0.5),
            )

            assert result.sample_count == 1
            assert result.manifest.task_ids == ["t1"]
        finally:
            _cleanup(tmp)

    def test_batch_filter_verifier_passed(self):
        """verifier_passed filter should work on batch layout."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="t1", verifier=VerifyResult(passed=True, score=1.0)),
                make_trajectory(task_id="t2", verifier=VerifyResult(passed=False, score=0.0)),
            ]
            batch_dir = _make_batch_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_batch(
                batch_dir, output_dir,
                filter_config=FilterConfig(verifier_passed=True),
            )

            assert result.sample_count == 1
            assert result.manifest.task_ids == ["t1"]
        finally:
            _cleanup(tmp)

    def test_batch_filter_task_ids(self):
        """task_ids filter should work on batch layout."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="task_001"),
                make_trajectory(task_id="task_002"),
            ]
            batch_dir = _make_batch_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            builder = RolloutDatasetBuilder()
            result = builder.build_from_batch(
                batch_dir, output_dir,
                filter_config=FilterConfig(task_ids=["task_001"]),
            )

            assert result.sample_count == 1
            assert result.manifest.task_ids == ["task_001"]
        finally:
            _cleanup(tmp)


class TestBuildRolloutDatasetConvenience:
    """Tests for the convenience function build_rollout_dataset."""

    def test_experiment_type(self):
        """Should dispatch to build_from_experiment."""
        tmp = _get_test_dir()
        try:
            trajectories = [make_trajectory()]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            result = build_rollout_dataset(
                exp_dir, output_dir,
                source_type="experiment",
                dataset_id="conv_ds",
            )

            assert result.manifest.source_type == "experiment"
            assert result.manifest.dataset_id == "conv_ds"
        finally:
            _cleanup(tmp)

    def test_batch_type(self):
        """Should dispatch to build_from_batch."""
        tmp = _get_test_dir()
        try:
            trajectories = [make_trajectory()]
            batch_dir = _make_batch_dir(tmp, trajectories=trajectories)
            output_dir = tmp / "output"

            result = build_rollout_dataset(
                batch_dir, output_dir,
                source_type="batch",
            )

            assert result.manifest.source_type == "batch"
        finally:
            _cleanup(tmp)

    def test_unknown_type_raises(self):
        """Unknown source_type should raise ValueError."""
        tmp = _get_test_dir()
        try:
            with pytest.raises(ValueError, match="Unknown source_type"):
                build_rollout_dataset(
                    tmp, tmp / "output",
                    source_type="unknown",
                )
        finally:
            _cleanup(tmp)


class TestAutoDatasetId:
    """Tests for deterministic dataset IDs."""

    def test_unresolved_before_build_when_not_provided(self):
        """Dataset ID should be resolved from build inputs, not at init time."""
        builder = RolloutDatasetBuilder()
        assert builder.dataset_id is None

    def test_custom_id(self):
        """Should use provided dataset_id."""
        builder = RolloutDatasetBuilder(dataset_id="my_custom_id")
        assert builder.dataset_id == "my_custom_id"

    def test_same_source_and_filters_produce_same_id(self):
        """Default IDs should be stable for identical inputs."""
        tmp = _get_test_dir()
        try:
            trajectories = [make_trajectory(task_id="task_001")]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)

            builder1 = RolloutDatasetBuilder()
            result1 = builder1.build_from_experiment(exp_dir, tmp / "output_1")

            builder2 = RolloutDatasetBuilder()
            result2 = builder2.build_from_experiment(exp_dir, tmp / "output_2")

            assert result1.manifest.dataset_id == result2.manifest.dataset_id
            assert result1.manifest.dataset_id.startswith("ds_")
            assert len(result1.manifest.dataset_id) == 15  # "ds_" + 12 hex chars
        finally:
            _cleanup(tmp)

    def test_filter_change_changes_default_id(self):
        """Filter config must participate in the derived dataset ID."""
        tmp = _get_test_dir()
        try:
            trajectories = [
                make_trajectory(task_id="task_001", reward=1.0),
                make_trajectory(task_id="task_002", reward=0.0),
            ]
            exp_dir = _make_experiment_dir(tmp, trajectories=trajectories)

            builder1 = RolloutDatasetBuilder()
            result1 = builder1.build_from_experiment(
                exp_dir,
                tmp / "output_1",
                filter_config=FilterConfig(),
            )

            builder2 = RolloutDatasetBuilder()
            result2 = builder2.build_from_experiment(
                exp_dir,
                tmp / "output_2",
                filter_config=FilterConfig(min_reward=0.5),
            )

            assert result1.manifest.dataset_id != result2.manifest.dataset_id
        finally:
            _cleanup(tmp)
