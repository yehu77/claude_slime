"""Structured report writing for mutation sensitivity studies.

Writes machine-readable study outputs to a directory:
- study_config.json: The study configuration
- study_summary.json: Overall study summary
- mode_comparison.json: Per-mode comparison vs baseline
- seed_comparison.json: Per-seed metrics across all modes
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pycodeagent.eval.study_config import StudyConfig
from pycodeagent.eval.study_runner import StudyResult


class StudyReport:
    """Structured study report writer.

    Writes study outputs to a directory in machine-readable JSON format.
    """

    def __init__(self, output_dir: Path | str) -> None:
        """Initialize the report writer.

        Args:
            output_dir: Directory to write reports.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_config(self, config: StudyConfig) -> None:
        """Write the study configuration.

        Args:
            config: Study configuration.
        """
        path = self.output_dir / "study_config.json"
        config.save(path)

    def write_summary(self, result: StudyResult) -> None:
        """Write the study summary.

        Args:
            result: Study result.
        """
        summary = {
            "study_id": result.config.study_id,
            "tasks_path": result.config.tasks_path,
            "task_count": result.task_count,
            "profile_modes": result.config.profile_modes,
            "baseline_mode": result.config.baseline_mode,
            "seeds": result.config.seeds,
            "baseline_metrics": result.baseline_metrics,
            "per_mode_deltas": {
                comp.mode: {
                    "delta_pass_at_1": comp.delta_pass_at_1,
                    "delta_avg_reward": comp.delta_avg_reward,
                    "delta_parse_error_rate": comp.delta_parse_error_rate,
                    "delta_schema_error_rate": comp.delta_schema_error_rate,
                    "delta_patch_apply_success_rate": comp.delta_patch_apply_success_rate,
                    "delta_entered_execution_rate": comp.delta_entered_execution_rate,
                    "delta_clean_run_pass_at_1": comp.delta_clean_run_pass_at_1,
                    "delta_verifier_failed_rate": comp.delta_verifier_failed_rate,
                }
                for comp in result.mode_comparisons
                if comp.mode != result.config.baseline_mode
            },
            "experiment_output_dirs": {
                mode: exp_result.output_dir
                for mode, exp_result in result.experiment_results.items()
            },
        }

        path = self.output_dir / "study_summary.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, sort_keys=False)

    def write_mode_comparison(self, result: StudyResult) -> None:
        """Write per-mode comparison table.

        Args:
            result: Study result.
        """
        comparisons = []
        for comp in result.mode_comparisons:
            comparisons.append(asdict(comp))

        path = self.output_dir / "mode_comparison.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(comparisons, f, indent=2, sort_keys=False)

    def write_seed_comparison(self, result: StudyResult) -> None:
        """Write per-seed comparison table.

        Args:
            result: Study result.
        """
        comparisons = []
        for comp in result.seed_comparisons:
            comparisons.append(asdict(comp))

        path = self.output_dir / "seed_comparison.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(comparisons, f, indent=2, sort_keys=False)

    def write_seed_variability(self, result: StudyResult) -> None:
        """Write seed variability summaries.

        Args:
            result: Study result.
        """
        variability = []
        for sv in result.seed_variability:
            variability.append(asdict(sv))

        path = self.output_dir / "seed_variability.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(variability, f, indent=2, sort_keys=False)

    def write_all(self, result: StudyResult) -> None:
        """Write all study report files.

        Args:
            result: Study result.
        """
        self.write_config(result.config)
        self.write_summary(result)
        self.write_mode_comparison(result)
        self.write_seed_comparison(result)
        self.write_seed_variability(result)

    def load_config(self) -> StudyConfig:
        """Load the study configuration.

        Returns:
            StudyConfig instance.
        """
        path = self.output_dir / "study_config.json"
        return StudyConfig.load(path)

    def load_summary(self) -> dict[str, Any]:
        """Load the study summary.

        Returns:
            Summary dict.
        """
        path = self.output_dir / "study_summary.json"
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def load_mode_comparison(self) -> list[dict[str, Any]]:
        """Load the mode comparison table.

        Returns:
            List of mode comparison dicts.
        """
        path = self.output_dir / "mode_comparison.json"
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def load_seed_comparison(self) -> list[dict[str, Any]]:
        """Load the seed comparison table.

        Returns:
            List of seed comparison dicts.
        """
        path = self.output_dir / "seed_comparison.json"
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def load_seed_variability(self) -> list[dict[str, Any]]:
        """Load the seed variability summaries.

        Returns:
            List of seed variability dicts.
        """
        path = self.output_dir / "seed_variability.json"
        with open(path, encoding="utf-8") as f:
            return json.load(f)


def write_study_report(result: StudyResult) -> StudyReport:
    """Write a complete study report.

    Convenience function that writes all report files.

    Args:
        result: Study result.

    Returns:
        StudyReport instance.
    """
    report = StudyReport(result.output_dir)
    report.write_all(result)
    return report
