"""Run artifact recorder.

Responsible for persisting run artifacts to disk:
- trajectory.json
- tool_profile.json
- verifier.json
- final.patch

The recorder is decoupled from specific LLM APIs and focuses on
serializing the structured objects defined in trajectory/schema.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.tools.spec import ToolProfile
from pycodeagent.trajectory.schema import Trajectory, VerifyResult


class RunRecorder:
    """Persist run artifacts to a directory."""

    def __init__(self, run_dir: Path) -> None:
        """Initialize recorder with a run directory.

        Args:
            run_dir: Directory to write artifacts to. Will be created if needed.
        """
        self.run_dir = Path(run_dir)

    def ensure_dir(self) -> None:
        """Create the run directory if it doesn't exist."""
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def write_trajectory(self, trajectory: Trajectory) -> Path:
        """Write trajectory.json.

        Args:
            trajectory: The trajectory to serialize.

        Returns:
            Path to the written file.
        """
        self.ensure_dir()
        path = self.run_dir / "trajectory.json"
        path.write_text(
            json.dumps(trajectory.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def write_tool_profile(self, profile: ToolProfile) -> Path:
        """Write tool_profile.json.

        Args:
            profile: The tool profile to serialize.

        Returns:
            Path to the written file.
        """
        self.ensure_dir()
        path = self.run_dir / "tool_profile.json"
        path.write_text(
            json.dumps(profile.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def write_verifier_result(self, result: VerifyResult) -> Path:
        """Write verifier.json.

        Args:
            result: The verifier result to serialize.

        Returns:
            Path to the written file.
        """
        self.ensure_dir()
        path = self.run_dir / "verifier.json"
        path.write_text(
            json.dumps(result.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def write_final_patch(self, patch_text: str) -> Path:
        """Write final.patch.

        Args:
            patch_text: The unified diff text.

        Returns:
            Path to the written file.
        """
        self.ensure_dir()
        path = self.run_dir / "final.patch"
        path.write_text(patch_text, encoding="utf-8")
        return path

    def write_all(
        self,
        trajectory: Trajectory,
        profile: ToolProfile,
        verifier_result: VerifyResult,
        patch_text: str,
    ) -> dict[str, Path]:
        """Write all artifacts at once.

        Args:
            trajectory: The trajectory to serialize.
            profile: The tool profile to serialize.
            verifier_result: The verifier result to serialize.
            patch_text: The unified diff text.

        Returns:
            Dict mapping artifact names to their paths.
        """
        return {
            "trajectory": self.write_trajectory(trajectory),
            "tool_profile": self.write_tool_profile(profile),
            "verifier": self.write_verifier_result(verifier_result),
            "patch": self.write_final_patch(patch_text),
        }
