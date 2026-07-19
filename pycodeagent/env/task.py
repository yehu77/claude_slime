"""Coding task definition.

A CodingTask describes a unit of work for the agent: which repo to work on,
what to do, how to verify success, and what constraints to enforce.
"""

from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath
from pathlib import PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TaskCapability = Literal[
    "workspace_read",
    "workspace_write",
    "command_execution",
    "validation",
    "failure_recovery",
]

_RUNTIME_SELECTION_METADATA_KEYS = frozenset(
    {
        "adapter",
        "adapter_name",
        "family",
        "native_profile_kind",
        "profile",
        "profile_mode",
        "profile_seed",
        "provider",
        "provider_family",
        "tool_profile_id",
        "tool_stack_kind",
    }
)
_LEGACY_TOOL_HINT_KEYS = frozenset({"expected_pattern", "primary_tools"})


class TaskMetadataContractV1(BaseModel):
    """Versioned, family-neutral behavioral metadata for one coding task."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    required_capabilities: list[TaskCapability] = Field(min_length=1)
    behavioral_requirements: list[str] = Field(default_factory=list)
    require_runtime_validation_evidence: bool = False

    @field_validator("required_capabilities")
    @classmethod
    def _validate_unique_capabilities(
        cls,
        value: list[TaskCapability],
    ) -> list[TaskCapability]:
        if len(value) != len(set(value)):
            raise ValueError("required_capabilities must not contain duplicates")
        return value

    @field_validator("behavioral_requirements")
    @classmethod
    def _validate_behavioral_requirements(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("behavioral_requirements must contain non-empty strings")
        if len(normalized) != len(set(normalized)):
            raise ValueError("behavioral_requirements must not contain duplicates")
        return normalized


class CodingTask(BaseModel):
    """A single coding task for the agent to solve."""

    task_id: str
    repo_path: Path
    prompt: str
    test_command: str | list[str] = "pytest -q"
    max_turns: int = 12
    allowed_files: list[str] = Field(default_factory=list)
    forbidden_files: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_family_neutral_metadata(self) -> CodingTask:
        runtime_keys = sorted(_RUNTIME_SELECTION_METADATA_KEYS & self.metadata.keys())
        if runtime_keys:
            raise ValueError(
                "task metadata cannot select runtime family/profile/adapter/provider; "
                f"pass runtime selection at invocation time instead: {runtime_keys!r}"
            )

        contract_payload = self.metadata.get("task_contract")
        if contract_payload is None:
            return self
        if not isinstance(contract_payload, dict):
            raise ValueError("metadata.task_contract must be an object")

        legacy_keys = sorted(_LEGACY_TOOL_HINT_KEYS & self.metadata.keys())
        if legacy_keys:
            raise ValueError(
                "versioned task_contract cannot be combined with legacy tool-name "
                f"metadata: {legacy_keys!r}"
            )
        TaskMetadataContractV1.model_validate(contract_payload)
        return self

    def metadata_contract(self) -> TaskMetadataContractV1 | None:
        """Return validated v1 metadata, or ``None`` for a legacy-v0 task."""
        payload = self.metadata.get("task_contract")
        if payload is None:
            return None
        return TaskMetadataContractV1.model_validate(payload)

    def requires_runtime_validation_evidence(self) -> bool:
        """Whether runtime completion should be gated on successful validation."""
        contract = self.metadata_contract()
        if contract is not None:
            return contract.require_runtime_validation_evidence
        return bool(self.metadata.get("require_runtime_validation_evidence", False))

    def normalize_repo_relative_path(self, file_path: str) -> str:
        """Normalize a path into a repo-relative POSIX path.

        The runtime should only operate on workspace-relative paths. This
        rejects absolute paths and directory traversal before pattern matching.
        """
        raw_text = str(file_path or "")
        normalized_text = raw_text.replace("\\", "/")
        posix_path = PurePosixPath(normalized_text)
        windows_path = PureWindowsPath(raw_text)

        if posix_path.is_absolute() or windows_path.is_absolute():
            raise ValueError(f"Absolute paths are not allowed: {file_path}")
        if any(part == ".." for part in posix_path.parts):
            raise ValueError(f"Path escapes workspace: {file_path}")

        normalized = str(posix_path)
        if normalized in {"", "."}:
            return "."
        return normalized

    def is_file_allowed(self, file_path: str) -> bool:
        """Check whether a file path is within the allowed set and not forbidden."""
        import fnmatch

        try:
            normalized_path = self.normalize_repo_relative_path(file_path)
        except ValueError:
            return False

        for pattern in self.forbidden_files:
            if fnmatch.fnmatch(normalized_path, pattern):
                return False

        if not self.allowed_files:
            return True

        return any(
            fnmatch.fnmatch(normalized_path, pattern)
            for pattern in self.allowed_files
        )

    @classmethod
    def from_jsonl(cls, path: Path) -> list[CodingTask]:
        """Load tasks from a JSONL file."""
        tasks = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    tasks.append(cls.model_validate_json(line))
        return tasks
