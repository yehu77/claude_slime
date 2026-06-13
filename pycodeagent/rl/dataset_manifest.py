"""Dataset manifest for rollout/training datasets.

Provides a structured summary of a generated dataset, allowing downstream
training code to inspect dataset contents without scanning all records.

The manifest captures:
- Source information (experiment/batch path)
- Sample counts and breakdowns
- Reward statistics
- Filter configuration used during build
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class RewardSummary(BaseModel):
    """Summary statistics for rewards in the dataset."""

    min: float
    max: float
    mean: float
    total: float
    count: int


class StatusCounts(BaseModel):
    """Counts by run status."""

    completed: int = 0
    failed: int = 0
    timeout: int = 0
    error: int = 0


class VerifierCounts(BaseModel):
    """Counts by verifier outcome."""

    passed: int = 0
    failed: int = 0


class FilterConfig(BaseModel):
    """Configuration for dataset filtering/inclusion rules.

    Attributes:
        allowed_statuses: List of allowed run statuses (None = all)
        verifier_passed: None = all, True = only passed, False = only failed
        min_reward: Minimum reward threshold (None = no threshold)
        include_failed: Whether to include non-completed runs
        task_ids: Optional list of task IDs to include (None = all)
        profile_ids: Optional list of profile IDs to include (None = all)
    """

    allowed_statuses: list[str] | None = None
    verifier_passed: bool | None = None
    min_reward: float | None = None
    include_failed: bool = True
    task_ids: list[str] | None = None
    profile_ids: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return self.model_dump()


class DatasetManifest(BaseModel):
    """Manifest for a generated rollout/training dataset.

    This is the stable metadata file that summarizes a dataset build.
    It allows downstream training code to:
    - Know sample counts without scanning files
    - Filter datasets by task/profile/reward
    - Understand what source data was used
    - Reproduce the filter configuration

    Attributes:
        dataset_id: Unique identifier for this dataset
        source_type: Type of source ("experiment" or "batch")
        source_path: Path to the source directory
        sample_count: Total number of samples in the dataset
        rollout_count: Total number of rollouts (same as sample_count typically)
        task_ids: List of unique task IDs in the dataset
        profile_ids: List of unique tool profile IDs in the dataset
        reward_summary: Reward statistics
        status_counts: Counts by run status
        verifier_counts: Counts by verifier outcome
        filter_config: Filter configuration used during build
        created_at: Optional timestamp when manifest was created
        output_dir: Path where dataset was written
    """

    dataset_id: str
    source_type: str
    source_path: str
    sample_count: int
    rollout_count: int
    task_ids: list[str] = Field(default_factory=list)
    profile_ids: list[str] = Field(default_factory=list)
    reward_summary: RewardSummary
    status_counts: StatusCounts = Field(default_factory=StatusCounts)
    verifier_counts: VerifierCounts = Field(default_factory=VerifierCounts)
    filter_config: FilterConfig = Field(default_factory=FilterConfig)
    created_at: str | None = None
    output_dir: str = ""

    def save(self, path: str | Path) -> None:
        """Save manifest to JSON file.

        Args:
            path: Output file path
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(mode="json", exclude_none=True), f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> DatasetManifest:
        """Load manifest from JSON file.

        Args:
            path: Input file path

        Returns:
            Loaded DatasetManifest
        """
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return self.model_dump(mode="json", exclude_none=True)


def build_reward_summary(rewards: list[float]) -> RewardSummary:
    """Build reward summary from a list of rewards.

    Args:
        rewards: List of reward values

    Returns:
        RewardSummary with statistics
    """
    if not rewards:
        return RewardSummary(min=0.0, max=0.0, mean=0.0, total=0.0, count=0)

    return RewardSummary(
        min=min(rewards),
        max=max(rewards),
        mean=sum(rewards) / len(rewards),
        total=sum(rewards),
        count=len(rewards),
    )


def build_status_counts(statuses: list[str]) -> StatusCounts:
    """Build status counts from a list of statuses.

    Args:
        statuses: List of status strings

    Returns:
        StatusCounts with counts per status
    """
    counts = StatusCounts()
    for status in statuses:
        if status == "completed":
            counts.completed += 1
        elif status == "failed":
            counts.failed += 1
        elif status == "timeout":
            counts.timeout += 1
        elif status == "error":
            counts.error += 1
    return counts


def build_verifier_counts(passed_flags: list[bool]) -> VerifierCounts:
    """Build verifier counts from a list of passed flags.

    Args:
        passed_flags: List of verifier passed booleans

    Returns:
        VerifierCounts with passed/failed counts
    """
    counts = VerifierCounts()
    for passed in passed_flags:
        if passed:
            counts.passed += 1
        else:
            counts.failed += 1
    return counts
