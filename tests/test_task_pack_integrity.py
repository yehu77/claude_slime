"""Repository-level integrity gate for checked-in active coding task packs.

Runtime-created task files, archived legacy studies, and caller-supplied
external datasets are outside this static repository policy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import pytest
from pydantic import ValidationError

from pycodeagent.env.task import CodingTask


pytestmark = pytest.mark.mainline

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_TASK_PACK_GLOB = "datasets/tasks/*.jsonl"
_REALISTIC_TASK_PACK = _PROJECT_ROOT / "datasets/tasks/realistic_runtime_tasks.jsonl"
_REALISTIC_TASK_MIGRATION_GOLDEN = {
    "realistic_revise_add_one_001": {
        "repo_path": "examples/runtime_realistic_revise_add_one",
        "test_command": "pytest -q -p no:cacheprovider",
        "allowed_files": ["generated.py"],
        "required_capabilities": [
            "workspace_write",
            "command_execution",
            "validation",
            "failure_recovery",
        ],
        "behavioral_requirements": [
            "Create generated.py before validation.",
            "Observe an initial validation failure before revising generated.py.",
            "Defer completion while validation failure remains unresolved.",
            "Revalidate after revision and complete only after validation succeeds.",
        ],
    },
    "realistic_patch_calculator_001": {
        "repo_path": "examples/runtime_realistic_patch_calculator",
        "test_command": "pytest -q -p no:cacheprovider",
        "allowed_files": ["calculator.py"],
        "required_capabilities": [
            "workspace_read",
            "workspace_write",
            "command_execution",
            "validation",
            "failure_recovery",
        ],
        "behavioral_requirements": [
            "Inspect calculator.py before modifying it.",
            "Observe a failing validation before rewriting calculator.py.",
            "Revalidate after the rewrite and complete only after validation succeeds.",
        ],
    },
    "realistic_subdir_formatter_001": {
        "repo_path": "examples/runtime_realistic_subdir_formatter",
        "test_command": "python app/check_formatter.py",
        "allowed_files": ["app/formatter.py", "app/check_formatter.py"],
        "required_capabilities": [
            "workspace_read",
            "workspace_write",
            "command_execution",
            "validation",
            "failure_recovery",
        ],
        "behavioral_requirements": [
            "Inspect app/formatter.py before modifying it.",
            "Run the formatter validation from the app working directory before and after the change.",
            "Observe the initial validation failure before fixing the formatter.",
            "Complete only after validation succeeds from the app working directory.",
        ],
    },
}


class _TaskPackIntegrityError(AssertionError):
    """Raised when checked-in task assets violate repository policy."""


@dataclass(frozen=True)
class _TaskPackInventory:
    task_pack_paths: tuple[str, ...]
    task_ids: tuple[str, ...]
    workspace_paths: tuple[str, ...]

    @property
    def task_pack_count(self) -> int:
        return len(self.task_pack_paths)

    @property
    def task_count(self) -> int:
        return len(self.task_ids)


def _format_validation_error(error: ValidationError) -> str:
    first = error.errors()[0]
    location = ".".join(str(part) for part in first.get("loc", ())) or "record"
    return f"{location}: {first.get('msg', 'invalid value')}"


def _resolve_repo_reference(
    project_root: Path,
    raw_path: object,
    *,
    location: str,
    field_name: str,
    issues: list[str],
) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        issues.append(
            f"{location}: invalid_{field_name}: expected a non-empty string"
        )
        return None

    normalized = raw_path.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(raw_path)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or ".." in posix_path.parts
    ):
        issues.append(
            f"{location}: invalid_{field_name}: must be repo-relative without '..': "
            f"{raw_path!r}"
        )
        return None

    resolved = (project_root / Path(*posix_path.parts)).resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError:
        issues.append(
            f"{location}: invalid_{field_name}: escapes repository: {raw_path!r}"
        )
        return None
    return resolved


def _validate_repository_task_assets(project_root: Path) -> _TaskPackInventory:
    project_root = project_root.resolve()
    issues: list[str] = []
    pack_paths = tuple(sorted(project_root.glob(_TASK_PACK_GLOB)))

    if not pack_paths:
        issues.append(
            f"{_TASK_PACK_GLOB}: no active task packs were discovered"
        )

    first_task_location: dict[str, str] = {}
    task_ids: list[str] = []
    workspace_paths: list[str] = []

    for pack_path in pack_paths:
        relative_pack = pack_path.relative_to(project_root).as_posix()
        nonempty_record_count = 0
        try:
            lines = pack_path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            issues.append(f"{relative_pack}: unreadable_task_pack: {error}")
            continue

        for line_number, raw_line in enumerate(lines, start=1):
            if not raw_line.strip():
                continue
            nonempty_record_count += 1
            location = f"{relative_pack}:{line_number}"
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as error:
                issues.append(
                    f"{location}: invalid_json: {error.msg} at column {error.colno}"
                )
                continue
            if not isinstance(payload, dict):
                issues.append(
                    f"{location}: invalid_task_record: expected a JSON object"
                )
                continue

            try:
                task = CodingTask.model_validate(payload)
            except ValidationError as error:
                issues.append(
                    f"{location}: invalid_task_record: "
                    f"{_format_validation_error(error)}"
                )
                continue

            task_location = f"{location} ({task.task_id})"
            normalized_task_id = task.task_id.strip()
            if not normalized_task_id or normalized_task_id != task.task_id:
                issues.append(
                    f"{task_location}: invalid_task_id: must be non-empty and trimmed"
                )
            else:
                previous_location = first_task_location.get(task.task_id)
                if previous_location is not None:
                    issues.append(
                        f"{task_location}: duplicate_task_id: {task.task_id!r}; "
                        f"first declared at {previous_location}"
                    )
                else:
                    first_task_location[task.task_id] = task_location
                task_ids.append(task.task_id)

            workspace = _resolve_repo_reference(
                project_root,
                payload.get("repo_path"),
                location=task_location,
                field_name="workspace_path",
                issues=issues,
            )
            if workspace is None:
                continue
            if not workspace.exists():
                issues.append(
                    f"{task_location}: missing_workspace: "
                    f"{payload.get('repo_path')!r}"
                )
            elif not workspace.is_dir():
                issues.append(
                    f"{task_location}: workspace_not_directory: "
                    f"{payload.get('repo_path')!r}"
                )
            else:
                workspace_paths.append(
                    workspace.relative_to(project_root).as_posix()
                )

        if nonempty_record_count == 0:
            issues.append(f"{relative_pack}: empty_task_pack")

    if issues:
        rendered = "\n".join(f"- {issue}" for issue in issues)
        raise _TaskPackIntegrityError(
            f"Repository task-pack integrity validation failed:\n{rendered}"
        )

    return _TaskPackInventory(
        task_pack_paths=tuple(
            path.relative_to(project_root).as_posix() for path in pack_paths
        ),
        task_ids=tuple(task_ids),
        workspace_paths=tuple(workspace_paths),
    )


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def _task_record(
    task_id: str,
    *,
    repo_path: str = "examples/workspace",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "repo_path": repo_path,
        "prompt": "Make the requested change.",
        "metadata": metadata or {},
    }


def _make_valid_temp_repository(tmp_path: Path) -> Path:
    project_root = tmp_path / "repo"
    (project_root / "examples" / "workspace").mkdir(parents=True)
    _write_jsonl(
        project_root / "datasets" / "tasks" / "tasks.jsonl",
        [_task_record("task_001")],
    )
    return project_root


def test_checked_in_task_packs_are_integral() -> None:
    inventory = _validate_repository_task_assets(_PROJECT_ROOT)

    discovered_packs = tuple(
        path.relative_to(_PROJECT_ROOT).as_posix()
        for path in sorted(_PROJECT_ROOT.glob(_TASK_PACK_GLOB))
    )
    assert inventory.task_pack_paths == discovered_packs
    assert inventory.task_pack_count > 0
    assert inventory.task_count > 0
    assert len(inventory.task_ids) == len(set(inventory.task_ids))
    assert len(inventory.workspace_paths) == inventory.task_count


def test_realistic_task_pack_matches_family_neutral_v1_migration_golden() -> None:
    tasks = CodingTask.from_jsonl(_REALISTIC_TASK_PACK)
    by_id = {task.task_id: task for task in tasks}

    assert set(by_id) == set(_REALISTIC_TASK_MIGRATION_GOLDEN)
    for task_id, expected in _REALISTIC_TASK_MIGRATION_GOLDEN.items():
        task = by_id[task_id]
        contract = task.metadata_contract()

        assert contract is not None
        assert contract.schema_version == 1
        assert task.repo_path.as_posix() == expected["repo_path"]
        assert task.test_command == expected["test_command"]
        assert task.allowed_files == expected["allowed_files"]
        assert task.forbidden_files == []
        assert task.max_turns == 20
        assert contract.required_capabilities == expected["required_capabilities"]
        assert contract.behavioral_requirements == expected["behavioral_requirements"]
        assert contract.require_runtime_validation_evidence is True
        assert task.requires_runtime_validation_evidence() is True
        assert "primary_tools" not in task.metadata
        assert "expected_pattern" not in task.metadata
        assert "require_runtime_validation_evidence" not in task.metadata

        restored = CodingTask.model_validate_json(task.model_dump_json())
        assert restored.model_dump(mode="json") == task.model_dump(mode="json")


def test_realistic_task_metadata_contains_no_runtime_family_or_tool_name_hints() -> None:
    forbidden_hints = {
        "Bash",
        "Edit",
        "Glob",
        "Grep",
        "Read",
        "Write",
        "apply_patch",
        "create_file",
        "exec_command",
        "finish",
        "native_claude",
        "native_codex",
        "python_run",
        "read_file",
        "write_file",
        "write_stdin",
    }

    for task in CodingTask.from_jsonl(_REALISTIC_TASK_PACK):
        serialized_metadata = json.dumps(task.metadata, sort_keys=True)
        for hint in forbidden_hints:
            assert hint not in serialized_metadata, (task.task_id, hint)


def test_new_top_level_task_pack_is_discovered_automatically(tmp_path: Path) -> None:
    project_root = _make_valid_temp_repository(tmp_path)
    (project_root / "examples" / "second").mkdir()
    _write_jsonl(
        project_root / "datasets" / "tasks" / "new_pack.jsonl",
        [_task_record("task_002", repo_path="examples/second")],
    )

    inventory = _validate_repository_task_assets(project_root)

    assert inventory.task_pack_paths == (
        "datasets/tasks/new_pack.jsonl",
        "datasets/tasks/tasks.jsonl",
    )
    assert inventory.task_ids == ("task_002", "task_001")


@pytest.mark.parametrize(
    ("repo_path", "error_code"),
    [
        ("examples/missing", "missing_workspace"),
        ("../outside", "invalid_workspace_path"),
        ("/absolute/workspace", "invalid_workspace_path"),
    ],
)
def test_invalid_workspace_reference_fails_loudly(
    tmp_path: Path,
    repo_path: str,
    error_code: str,
) -> None:
    project_root = tmp_path / "repo"
    _write_jsonl(
        project_root / "datasets" / "tasks" / "tasks.jsonl",
        [_task_record("task_001", repo_path=repo_path)],
    )

    with pytest.raises(_TaskPackIntegrityError, match=error_code):
        _validate_repository_task_assets(project_root)


def test_workspace_reference_to_file_is_rejected(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    workspace_file = project_root / "examples" / "not_a_directory"
    workspace_file.parent.mkdir(parents=True)
    workspace_file.write_text("not a workspace", encoding="utf-8")
    _write_jsonl(
        project_root / "datasets" / "tasks" / "tasks.jsonl",
        [_task_record("task_001", repo_path="examples/not_a_directory")],
    )

    with pytest.raises(
        _TaskPackIntegrityError,
        match="workspace_not_directory",
    ):
        _validate_repository_task_assets(project_root)


def test_duplicate_task_id_across_packs_fails_loudly(tmp_path: Path) -> None:
    project_root = _make_valid_temp_repository(tmp_path)
    _write_jsonl(
        project_root / "datasets" / "tasks" / "second.jsonl",
        [_task_record("task_001")],
    )

    with pytest.raises(_TaskPackIntegrityError) as error:
        _validate_repository_task_assets(project_root)

    message = str(error.value)
    assert "duplicate_task_id" in message
    assert "datasets/tasks/second.jsonl:1" in message
    assert "datasets/tasks/tasks.jsonl:1" in message


def test_malformed_task_record_reports_pack_and_line(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    pack_path = project_root / "datasets" / "tasks" / "tasks.jsonl"
    pack_path.parent.mkdir(parents=True)
    pack_path.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(_TaskPackIntegrityError) as error:
        _validate_repository_task_assets(project_root)

    message = str(error.value)
    assert "datasets/tasks/tasks.jsonl:1" in message
    assert "invalid_json" in message


def _v1_task_metadata(**contract_updates: Any) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema_version": 1,
        "required_capabilities": ["workspace_read", "validation"],
        "behavioral_requirements": ["Inspect the workspace before validating."],
        "require_runtime_validation_evidence": True,
    }
    contract.update(contract_updates)
    return {"category": "contract_test", "task_contract": contract}


def test_family_neutral_task_metadata_v1_round_trips() -> None:
    task = CodingTask(
        task_id="task_contract_v1",
        repo_path="examples/workspace",
        prompt="Inspect the workspace and validate it.",
        metadata=_v1_task_metadata(),
    )

    restored = CodingTask.model_validate_json(task.model_dump_json())

    assert restored.task_id == task.task_id
    assert restored.metadata_contract() is not None
    assert restored.metadata_contract().schema_version == 1
    assert restored.metadata_contract().required_capabilities == [
        "workspace_read",
        "validation",
    ]
    assert restored.requires_runtime_validation_evidence() is True


@pytest.mark.parametrize(
    ("contract_updates", "error_pattern"),
    [
        ({"schema_version": 2}, "Input should be 1"),
        ({"schema_version": None}, "Input should be 1"),
        ({"unknown_field": True}, "Extra inputs are not permitted"),
        ({"required_capabilities": ["unknown"]}, "Input should be"),
        ({"required_capabilities": []}, "at least 1 item"),
        (
            {"required_capabilities": ["validation", "validation"]},
            "must not contain duplicates",
        ),
        (
            {"behavioral_requirements": [" "]},
            "must contain non-empty strings",
        ),
    ],
)
def test_family_neutral_task_metadata_rejects_invalid_v1_contracts(
    contract_updates: dict[str, Any],
    error_pattern: str,
) -> None:
    with pytest.raises(ValidationError, match=error_pattern):
        CodingTask(
            task_id="invalid_contract",
            repo_path="examples/workspace",
            prompt="Validate the workspace.",
            metadata=_v1_task_metadata(**contract_updates),
        )


def test_family_neutral_task_metadata_requires_explicit_schema_version() -> None:
    metadata = _v1_task_metadata()
    del metadata["task_contract"]["schema_version"]

    with pytest.raises(ValidationError, match="Field required"):
        CodingTask(
            task_id="missing_version",
            repo_path="examples/workspace",
            prompt="Validate the workspace.",
            metadata=metadata,
        )


@pytest.mark.parametrize(
    "selector",
    [
        "adapter",
        "family",
        "native_profile_kind",
        "profile_mode",
        "provider_family",
        "tool_profile_id",
        "tool_stack_kind",
    ],
)
def test_task_metadata_cannot_select_runtime_family_or_profile(selector: str) -> None:
    with pytest.raises(ValidationError, match="pass runtime selection at invocation"):
        CodingTask(
            task_id="runtime_selector_in_task",
            repo_path="examples/workspace",
            prompt="Validate the workspace.",
            metadata={selector: "native_claude"},
        )


def test_versioned_contract_rejects_legacy_tool_name_hints() -> None:
    metadata = _v1_task_metadata()
    metadata["primary_tools"] = ["read_file", "finish"]

    with pytest.raises(ValidationError, match="legacy tool-name metadata"):
        CodingTask(
            task_id="mixed_metadata_generations",
            repo_path="examples/workspace",
            prompt="Validate the workspace.",
            metadata=metadata,
        )


def test_legacy_v0_metadata_remains_loadable_until_pack_migration() -> None:
    task = CodingTask(
        task_id="legacy_v0",
        repo_path="examples/workspace",
        prompt="Validate the workspace.",
        metadata={
            "primary_tools": ["read_file", "finish"],
            "require_runtime_validation_evidence": True,
        },
    )

    assert task.metadata_contract() is None
    assert task.requires_runtime_validation_evidence() is True
