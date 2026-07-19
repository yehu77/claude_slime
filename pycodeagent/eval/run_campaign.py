"""Versioned, deterministic orchestration for runtime run matrices."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from pycodeagent.agent.llm_client import BaseLLMClient
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.runtime_trace import DEFAULT_RETENTION_CLASS
from pycodeagent.runtime_trace.retention import DEFAULT_RETENTION_OWNER
from pycodeagent.tools.bootstrap import ToolStackKind
from pycodeagent.trajectory.schema import Trajectory


RUN_CAMPAIGN_SCHEMA = "pycodeagent-run-campaign/v1"
RUN_CASE_SCHEMA = "pycodeagent-run-campaign-case/v1"
RUN_RECORD_SCHEMA = "pycodeagent-run-campaign-record/v1"
CAMPAIGN_SPEC_ARTIFACT_SCHEMA = "pycodeagent-run-campaign-spec-artifact/v1"
CAMPAIGN_ARTIFACT_INDEX_SCHEMA = "pycodeagent-run-campaign-artifact-index/v1"
CAMPAIGN_FAILURE_SUMMARY_SCHEMA = "pycodeagent-run-campaign-failure-summary/v1"
CAMPAIGN_MANIFEST_SCHEMA = "pycodeagent-run-campaign-manifest/v1"

CAMPAIGN_SPEC_NAME = "campaign_spec.json"
CAMPAIGN_ARTIFACT_INDEX_NAME = "campaign_artifact_index.json"
CAMPAIGN_FAILURE_SUMMARY_NAME = "campaign_failure_summary.json"
CAMPAIGN_MANIFEST_NAME = "campaign_manifest.json"
RUN_RECORD_NAME = "campaign_run_record.json"
ATTEMPT_RECORD_NAME = "campaign_attempt.json"
PROFILE_CAMPAIGN_GROUP_SPEC_NAME = "profile_campaign_group_spec.json"
PROFILE_CAMPAIGN_GROUP_MANIFEST_NAME = "profile_campaign_group_manifest.json"
PROFILE_CAMPAIGN_GROUP_SPEC_SCHEMA = "pycodeagent-profile-campaign-group-spec/v1"
PROFILE_CAMPAIGN_GROUP_MANIFEST_SCHEMA = (
    "pycodeagent-profile-campaign-group-manifest/v1"
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SECRET_METADATA_KEYS = {
    "api_key",
    "authorization",
    "password",
    "secret",
    "token",
}


class RunCampaignError(ValueError):
    """Raised when a campaign contract or installed artifact state is invalid."""


class CampaignProvider(BaseModel):
    """One non-secret provider dimension in a run matrix."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider_id")
    @classmethod
    def _validate_provider_id(cls, value: str) -> str:
        return _validate_id(value, "provider_id")

    @field_validator("metadata")
    @classmethod
    def _validate_provider_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        secret_path = _find_secret_key(value)
        if secret_path is not None:
            raise ValueError(
                "provider metadata must be non-secret; forbidden key at "
                f"{secret_path}"
            )
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "provider metadata must be finite JSON-compatible data"
            ) from exc
        return dict(value)


class RunMatrix(BaseModel):
    """Deterministic task × family × ToolView × seed × provider matrix."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_ids: tuple[str, ...] = Field(min_length=1)
    families: tuple[ToolStackKind, ...] = Field(min_length=1)
    profile_modes: tuple[str, ...] = Field(min_length=1)
    profile_seeds: tuple[int, ...] = (0,)
    providers: tuple[CampaignProvider, ...] = Field(min_length=1)
    repeat_count: int = Field(default=1, ge=1, le=1000)

    @field_validator("task_ids", "profile_modes", mode="before")
    @classmethod
    def _normalize_string_dimensions(
        cls,
        value: Sequence[str],
    ) -> tuple[str, ...]:
        normalized = tuple(str(item).strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("matrix string dimensions cannot contain empty values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("matrix dimensions cannot contain duplicates")
        return tuple(sorted(normalized))

    @field_validator("families", mode="before")
    @classmethod
    def _normalize_families(
        cls,
        value: Sequence[str],
    ) -> tuple[str, ...]:
        normalized = tuple(str(item) for item in value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("families cannot contain duplicates")
        return tuple(sorted(normalized))

    @field_validator("profile_seeds", mode="before")
    @classmethod
    def _normalize_profile_seeds(
        cls,
        value: Sequence[int],
    ) -> tuple[int, ...]:
        normalized = tuple(int(item) for item in value)
        if not normalized:
            raise ValueError("profile_seeds cannot be empty")
        if any(item < 0 for item in normalized):
            raise ValueError("profile_seeds must be non-negative")
        if len(normalized) != len(set(normalized)):
            raise ValueError("profile_seeds cannot contain duplicates")
        return tuple(sorted(normalized))

    @field_validator("providers", mode="before")
    @classmethod
    def _normalize_providers(
        cls,
        value: Sequence[CampaignProvider | Mapping[str, Any]],
    ) -> tuple[CampaignProvider, ...]:
        normalized = tuple(CampaignProvider.model_validate(item) for item in value)
        provider_ids = [item.provider_id for item in normalized]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("providers cannot contain duplicate provider_id values")
        return tuple(sorted(normalized, key=lambda item: item.provider_id))

    @model_validator(mode="after")
    def _validate_ids(self) -> "RunMatrix":
        for task_id in self.task_ids:
            _validate_id(task_id, "task_id")
        for mode in self.profile_modes:
            _validate_id(mode, "profile_mode")
        return self

    @property
    def run_count(self) -> int:
        return (
            len(self.task_ids)
            * len(self.families)
            * len(self.profile_modes)
            * len(self.profile_seeds)
            * len(self.providers)
            * self.repeat_count
        )


class RunCampaign(BaseModel):
    """Versioned campaign specification installed at one output root."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    campaign_id: str
    matrix: RunMatrix
    retention_class: str = DEFAULT_RETENTION_CLASS
    retention_owner: str = DEFAULT_RETENTION_OWNER

    @field_validator("campaign_id")
    @classmethod
    def _validate_campaign_id(cls, value: str) -> str:
        return _validate_id(value, "campaign_id")

    @field_validator("retention_class", "retention_owner")
    @classmethod
    def _validate_retention_fields(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("retention fields must be non-empty")
        return normalized


class CampaignRunCase(BaseModel):
    """One deterministic logical run expanded from a campaign."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    ordinal: int = Field(ge=0)
    run_id: str
    campaign_id: str
    task_id: str
    family: ToolStackKind
    profile_mode: str
    profile_seed: int
    provider: CampaignProvider
    repeat_index: int


class CampaignRunRecord(BaseModel):
    """Terminal record for one logical run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    spec_fingerprint: str
    case: CampaignRunCase
    outcome: Literal["trajectory_recorded", "executor_error"]
    attempt_number: int = Field(ge=1)
    attempt_path: str
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    trajectory_status: str | None = None
    tool_profile_id: str | None = None
    reward: float | None = None
    verifier: dict[str, Any] | None = None
    failure_kind: str | None = None
    failure_detail: str | None = None


class RunCampaignResult(BaseModel):
    """Invocation result plus stable campaign artifact locations."""

    output_root: str
    spec_fingerprint: str
    plan_fingerprint: str
    planned_run_count: int
    terminal_run_count: int
    pending_run_count: int
    executed_run_count: int
    recovered_run_count: int
    skipped_run_count: int
    executor_error_count: int
    failed_trajectory_count: int
    contract_ok: bool
    campaign_spec_path: str
    artifact_index_path: str
    failure_summary_path: str
    manifest_path: str


class ProfileCampaignGroupResult(BaseModel):
    """Aggregate result for paired ToolView mode/seed RunCampaign values."""

    output_root: str
    spec_fingerprint: str
    campaign_count: int
    planned_run_count: int
    terminal_run_count: int
    pending_run_count: int
    executed_run_count: int
    recovered_run_count: int
    skipped_run_count: int
    executor_error_count: int
    failed_trajectory_count: int
    contract_ok: bool
    spec_path: str
    manifest_path: str
    campaign_manifest_paths: list[str]


CampaignClientFactory = Callable[[CampaignRunCase], BaseLLMClient]
CampaignRunExecutor = Callable[
    [CodingTask, BaseLLMClient, Path, CampaignRunCase, RunCampaign],
    Trajectory,
]
ProfileCampaignClientFactory = Callable[
    [CodingTask, str, int],
    BaseLLMClient,
]


def campaign_spec_fingerprint(campaign: RunCampaign) -> str:
    """Return the canonical SHA-256 identity of one campaign spec."""

    return _sha256_json(campaign.model_dump(mode="json"))


def expand_run_campaign(campaign: RunCampaign) -> list[CampaignRunCase]:
    """Expand a normalized campaign into deterministic logical runs."""

    identity_payloads: list[dict[str, Any]] = []
    for task_id in campaign.matrix.task_ids:
        for family in campaign.matrix.families:
            for profile_mode in campaign.matrix.profile_modes:
                for profile_seed in campaign.matrix.profile_seeds:
                    for provider in campaign.matrix.providers:
                        for repeat_index in range(campaign.matrix.repeat_count):
                            identity_payloads.append(
                                {
                                    "campaign_id": campaign.campaign_id,
                                    "task_id": task_id,
                                    "family": family,
                                    "profile_mode": profile_mode,
                                    "profile_seed": profile_seed,
                                    "provider": provider.model_dump(mode="json"),
                                    "repeat_index": repeat_index,
                                }
                            )

    cases: list[CampaignRunCase] = []
    for ordinal, identity in enumerate(identity_payloads):
        run_id = f"run_{_sha256_json(identity)[:20]}"
        cases.append(
            CampaignRunCase(
                ordinal=ordinal,
                run_id=run_id,
                **identity,
            )
        )
    if len({case.run_id for case in cases}) != len(cases):
        raise RunCampaignError("Campaign run identity collision")
    return cases


def execute_run_campaign(
    campaign: RunCampaign,
    tasks: Sequence[CodingTask],
    client_factory: CampaignClientFactory,
    output_root: str | Path,
    *,
    run_executor: CampaignRunExecutor | None = None,
) -> RunCampaignResult:
    """Execute or resume a campaign without overwriting prior attempts."""

    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    runs_root = root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)

    task_by_id = _validate_tasks(campaign, tasks)
    spec_fingerprint = campaign_spec_fingerprint(campaign)
    plan = expand_run_campaign(campaign)
    plan_fingerprint = _sha256_json(
        [case.model_dump(mode="json") for case in plan]
    )
    _install_or_validate_spec(root, campaign, spec_fingerprint, plan_fingerprint)

    executor = run_executor or _default_run_executor
    records: dict[str, CampaignRunRecord] = {}
    executed_count = 0
    recovered_count = 0
    skipped_count = 0
    interruption: BaseException | None = None

    for case in plan:
        logical_run_root = runs_root / case.run_id
        logical_run_root.mkdir(parents=True, exist_ok=True)
        record_path = logical_run_root / RUN_RECORD_NAME

        if record_path.exists():
            records[case.run_id] = _load_and_validate_record(
                root,
                record_path,
                case,
                spec_fingerprint,
            )
            skipped_count += 1
            continue

        recovered = _recover_completed_attempt(
            root,
            logical_run_root,
            case,
            spec_fingerprint,
        )
        if recovered is not None:
            _write_json_atomic(record_path, recovered.model_dump(mode="json"))
            records[case.run_id] = recovered
            recovered_count += 1
            continue

        attempt_number = _next_attempt_number(logical_run_root)
        attempt_root = (
            logical_run_root
            / "attempts"
            / f"{case.run_id}__attempt_{attempt_number:04d}"
        )
        attempt_root.mkdir(parents=True, exist_ok=False)
        attempt_record_path = attempt_root / ATTEMPT_RECORD_NAME
        _write_attempt_record(
            attempt_record_path,
            case,
            spec_fingerprint,
            attempt_number,
            outcome="running",
        )
        executed_count += 1

        try:
            client = client_factory(case)
            trajectory = executor(
                task_by_id[case.task_id],
                client,
                attempt_root,
                case,
                campaign,
            )
            record = _trajectory_record(
                root,
                case,
                spec_fingerprint,
                attempt_number,
                attempt_root,
                trajectory,
            )
            _write_attempt_record(
                attempt_record_path,
                case,
                spec_fingerprint,
                attempt_number,
                outcome="trajectory_recorded",
            )
            _write_json_atomic(record_path, record.model_dump(mode="json"))
            records[case.run_id] = record
        except (KeyboardInterrupt, SystemExit) as exc:
            _write_attempt_record(
                attempt_record_path,
                case,
                spec_fingerprint,
                attempt_number,
                outcome="interrupted",
                failure_detail=f"{type(exc).__name__}: {exc}",
            )
            interruption = exc
            break
        except Exception as exc:
            record = _executor_error_record(
                root,
                case,
                spec_fingerprint,
                attempt_number,
                attempt_root,
                exc,
            )
            _write_attempt_record(
                attempt_record_path,
                case,
                spec_fingerprint,
                attempt_number,
                outcome="executor_error",
                failure_detail=record.failure_detail,
            )
            _write_json_atomic(record_path, record.model_dump(mode="json"))
            records[case.run_id] = record

    result = _write_campaign_artifacts(
        root,
        campaign,
        plan,
        records,
        spec_fingerprint=spec_fingerprint,
        plan_fingerprint=plan_fingerprint,
        executed_count=executed_count,
        recovered_count=recovered_count,
        skipped_count=skipped_count,
    )
    if interruption is not None:
        raise interruption
    return result


def execute_profile_run_campaigns(
    *,
    campaign_id: str,
    tasks: Sequence[CodingTask],
    client_factory: ProfileCampaignClientFactory,
    output_root: str | Path,
    profile_seed_by_mode: Mapping[str, int],
    repeat_count: int,
    tool_stack_kind: ToolStackKind,
    provider: Mapping[str, Any] | None = None,
    retention_class: str = DEFAULT_RETENTION_CLASS,
    retention_owner: str = DEFAULT_RETENTION_OWNER,
    run_executor: CampaignRunExecutor | None = None,
) -> ProfileCampaignGroupResult:
    """Execute paired ToolView mode/seed values through standard campaigns.

    One RunCampaign is installed per ToolView mode so a mapping such as
    ``{"base": 0, "tool_reorder": 7}`` remains paired instead of expanding
    into the mode × seed cross-product of one RunMatrix.
    """

    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    normalized_campaign_id = _validate_id(campaign_id, "campaign_id")
    if repeat_count < 1 or repeat_count > 1000:
        raise RunCampaignError("repeat_count must be between 1 and 1000")
    if tool_stack_kind not in {"native_claude", "native_codex"}:
        raise RunCampaignError(
            f"Unknown tool_stack_kind: {tool_stack_kind!r}"
        )
    if not retention_class.strip() or not retention_owner.strip():
        raise RunCampaignError("retention fields must be non-empty")
    legacy_direct_runs = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "trajectory.json").is_file()
    )
    if legacy_direct_runs:
        raise RunCampaignError(
            "Profile campaign group cannot share an output root with legacy "
            "direct runs; preserve them and select a new output root: "
            + ", ".join(legacy_direct_runs)
        )
    task_by_id = _validate_task_sequence(tasks)
    normalized_profiles = _normalize_profile_seed_mapping(profile_seed_by_mode)
    normalized_provider = CampaignProvider(
        provider_id="configured-provider",
        metadata={"provenance": dict(provider or {})},
    )
    group_spec = {
        "schema": PROFILE_CAMPAIGN_GROUP_SPEC_SCHEMA,
        "campaign_id": normalized_campaign_id,
        "task_ids": sorted(task_by_id),
        "tool_stack_kind": tool_stack_kind,
        "profile_seed_by_mode": normalized_profiles,
        "provider": normalized_provider.model_dump(mode="json"),
        "repeat_count": repeat_count,
        "retention_class": retention_class,
        "retention_owner": retention_owner,
    }
    spec_fingerprint = _sha256_json(group_spec)
    bound_spec = {
        **group_spec,
        "spec_fingerprint": spec_fingerprint,
    }
    group_spec_path = root / PROFILE_CAMPAIGN_GROUP_SPEC_NAME
    if group_spec_path.exists():
        if _read_json(group_spec_path) != bound_spec:
            raise RunCampaignError(
                "Profile campaign group output root is bound to a different spec"
            )
    else:
        _write_json_atomic(group_spec_path, bound_spec)

    campaign_entries: list[dict[str, Any]] = []
    campaign_results: list[RunCampaignResult] = []
    for mode, profile_seed in normalized_profiles.items():
        profile_identity = {
            "profile_mode": mode,
            "profile_seed": profile_seed,
        }
        profile_digest = _sha256_json(profile_identity)[:12]
        campaign_root = root / f"profile_{profile_digest}"
        campaign = RunCampaign(
            campaign_id=f"{normalized_campaign_id}__{profile_digest}",
            matrix=RunMatrix(
                task_ids=tuple(task_by_id),
                families=(tool_stack_kind,),
                profile_modes=(mode,),
                profile_seeds=(profile_seed,),
                providers=(normalized_provider,),
                repeat_count=repeat_count,
            ),
            retention_class=retention_class,
            retention_owner=retention_owner,
        )

        def case_client_factory(
            case: CampaignRunCase,
            *,
            expected_mode: str = mode,
        ) -> BaseLLMClient:
            if case.profile_mode != expected_mode:
                raise RunCampaignError("Profile campaign case mode drift")
            return client_factory(
                task_by_id[case.task_id],
                case.profile_mode,
                case.repeat_index,
            )

        result = execute_run_campaign(
            campaign,
            list(task_by_id.values()),
            case_client_factory,
            campaign_root,
            run_executor=run_executor,
        )
        campaign_results.append(result)
        campaign_entries.append(
            {
                "profile_mode": mode,
                "profile_seed": profile_seed,
                "campaign_root": _relative(root, campaign_root),
                "campaign_spec": _relative(
                    root,
                    Path(result.campaign_spec_path),
                ),
                "campaign_manifest": _relative(
                    root,
                    Path(result.manifest_path),
                ),
                "artifact_index": _relative(
                    root,
                    Path(result.artifact_index_path),
                ),
                "failure_summary": _relative(
                    root,
                    Path(result.failure_summary_path),
                ),
                "planned_run_count": result.planned_run_count,
                "terminal_run_count": result.terminal_run_count,
                "pending_run_count": result.pending_run_count,
                "contract_ok": result.contract_ok,
            }
        )

    manifest = {
        "schema": PROFILE_CAMPAIGN_GROUP_MANIFEST_SCHEMA,
        "spec_fingerprint": spec_fingerprint,
        "campaign_count": len(campaign_results),
        "planned_run_count": sum(
            result.planned_run_count for result in campaign_results
        ),
        "terminal_run_count": sum(
            result.terminal_run_count for result in campaign_results
        ),
        "pending_run_count": sum(
            result.pending_run_count for result in campaign_results
        ),
        "contract_ok": all(result.contract_ok for result in campaign_results),
        "campaigns": campaign_entries,
    }
    group_manifest_path = root / PROFILE_CAMPAIGN_GROUP_MANIFEST_NAME
    _write_json_atomic(group_manifest_path, manifest)
    return ProfileCampaignGroupResult(
        output_root=str(root),
        spec_fingerprint=spec_fingerprint,
        campaign_count=len(campaign_results),
        planned_run_count=sum(
            result.planned_run_count for result in campaign_results
        ),
        terminal_run_count=sum(
            result.terminal_run_count for result in campaign_results
        ),
        pending_run_count=sum(
            result.pending_run_count for result in campaign_results
        ),
        executed_run_count=sum(
            result.executed_run_count for result in campaign_results
        ),
        recovered_run_count=sum(
            result.recovered_run_count for result in campaign_results
        ),
        skipped_run_count=sum(
            result.skipped_run_count for result in campaign_results
        ),
        executor_error_count=sum(
            result.executor_error_count for result in campaign_results
        ),
        failed_trajectory_count=sum(
            result.failed_trajectory_count for result in campaign_results
        ),
        contract_ok=all(result.contract_ok for result in campaign_results),
        spec_path=str(group_spec_path),
        manifest_path=str(group_manifest_path),
        campaign_manifest_paths=[
            result.manifest_path for result in campaign_results
        ],
    )


def _default_run_executor(
    task: CodingTask,
    client: BaseLLMClient,
    attempt_root: Path,
    case: CampaignRunCase,
    campaign: RunCampaign,
) -> Trajectory:
    return run_coding_task(
        task,
        client,
        attempt_root,
        profile_mode=case.profile_mode,
        profile_seed=case.profile_seed,
        tool_stack_kind=case.family,
        retention_class=campaign.retention_class,
        retention_owner=campaign.retention_owner,
    )


def _validate_tasks(
    campaign: RunCampaign,
    tasks: Sequence[CodingTask],
) -> dict[str, CodingTask]:
    task_by_id: dict[str, CodingTask] = {}
    for task in tasks:
        if task.task_id in task_by_id:
            raise RunCampaignError(f"Duplicate CodingTask: {task.task_id}")
        task_by_id[task.task_id] = task
    missing = sorted(set(campaign.matrix.task_ids) - set(task_by_id))
    if missing:
        raise RunCampaignError(
            "Campaign references missing CodingTask values: "
            + ", ".join(missing)
        )
    return task_by_id


def _validate_task_sequence(
    tasks: Sequence[CodingTask],
) -> dict[str, CodingTask]:
    task_by_id: dict[str, CodingTask] = {}
    for task in tasks:
        if task.task_id in task_by_id:
            raise RunCampaignError(f"Duplicate CodingTask: {task.task_id}")
        task_by_id[task.task_id] = task
    if not task_by_id:
        raise RunCampaignError("Profile campaign group requires at least one task")
    return {
        task_id: task_by_id[task_id]
        for task_id in sorted(task_by_id)
    }


def _normalize_profile_seed_mapping(
    profile_seed_by_mode: Mapping[str, int],
) -> dict[str, int]:
    if not profile_seed_by_mode:
        raise RunCampaignError(
            "Profile campaign group requires at least one ToolView mode"
        )
    normalized: dict[str, int] = {}
    for raw_mode, raw_seed in profile_seed_by_mode.items():
        mode = _validate_id(str(raw_mode), "profile_mode")
        if mode in normalized:
            raise RunCampaignError(f"Duplicate ToolView mode: {mode}")
        seed = int(raw_seed)
        if seed < 0:
            raise RunCampaignError("profile seeds must be non-negative")
        normalized[mode] = seed
    return {
        mode: normalized[mode]
        for mode in sorted(normalized)
    }


def _install_or_validate_spec(
    root: Path,
    campaign: RunCampaign,
    spec_fingerprint: str,
    plan_fingerprint: str,
) -> None:
    path = root / CAMPAIGN_SPEC_NAME
    payload = {
        "schema": CAMPAIGN_SPEC_ARTIFACT_SCHEMA,
        "spec_fingerprint": spec_fingerprint,
        "plan_fingerprint": plan_fingerprint,
        "campaign": campaign.model_dump(mode="json"),
    }
    if path.exists():
        existing = _read_json(path)
        if existing != payload:
            raise RunCampaignError(
                "Campaign output root is bound to a different spec or plan"
            )
        return
    _write_json_atomic(path, payload)


def _trajectory_record(
    root: Path,
    case: CampaignRunCase,
    spec_fingerprint: str,
    attempt_number: int,
    attempt_root: Path,
    trajectory: Trajectory,
) -> CampaignRunRecord:
    if trajectory.task_id != case.task_id:
        raise RunCampaignError(
            f"Executor returned task_id={trajectory.task_id!r} "
            f"for campaign task {case.task_id!r}"
        )
    artifact_paths = _validate_complete_attempt(root, attempt_root, trajectory)
    status = trajectory.status.value
    failure_kind = None
    if status != "completed":
        failure_kind = str(
            trajectory.metadata.get("failure_reason")
            or trajectory.metadata.get("stop_reason")
            or status
        )
    verifier = (
        trajectory.verifier.model_dump(mode="json")
        if trajectory.verifier is not None
        else None
    )
    return CampaignRunRecord(
        spec_fingerprint=spec_fingerprint,
        case=case,
        outcome="trajectory_recorded",
        attempt_number=attempt_number,
        attempt_path=_relative(root, attempt_root),
        artifact_paths=artifact_paths,
        trajectory_status=status,
        tool_profile_id=trajectory.tool_profile_id,
        reward=trajectory.reward,
        verifier=verifier,
        failure_kind=failure_kind,
    )


def _executor_error_record(
    root: Path,
    case: CampaignRunCase,
    spec_fingerprint: str,
    attempt_number: int,
    attempt_root: Path,
    error: Exception,
) -> CampaignRunRecord:
    return CampaignRunRecord(
        spec_fingerprint=spec_fingerprint,
        case=case,
        outcome="executor_error",
        attempt_number=attempt_number,
        attempt_path=_relative(root, attempt_root),
        failure_kind="executor_error",
        failure_detail=f"{type(error).__name__}: {error}",
    )


def _recover_completed_attempt(
    root: Path,
    logical_run_root: Path,
    case: CampaignRunCase,
    spec_fingerprint: str,
) -> CampaignRunRecord | None:
    attempts_root = logical_run_root / "attempts"
    for attempt_root in reversed(sorted(attempts_root.glob("*"))):
        trajectory_path = attempt_root / "trajectory.json"
        if not trajectory_path.is_file():
            continue
        try:
            trajectory = Trajectory.model_validate_json(
                trajectory_path.read_text(encoding="utf-8")
            )
            attempt_number = _attempt_number(attempt_root)
            return _trajectory_record(
                root,
                case,
                spec_fingerprint,
                attempt_number,
                attempt_root,
                trajectory,
            )
        except (OSError, ValueError, RunCampaignError):
            continue
    return None


def _load_and_validate_record(
    root: Path,
    path: Path,
    case: CampaignRunCase,
    spec_fingerprint: str,
) -> CampaignRunRecord:
    try:
        record = CampaignRunRecord.model_validate(_read_json(path))
    except Exception as exc:
        raise RunCampaignError(f"Invalid campaign run record: {path}") from exc
    if (
        record.spec_fingerprint != spec_fingerprint
        or record.case.model_dump(mode="json") != case.model_dump(mode="json")
    ):
        raise RunCampaignError(
            f"Campaign run record identity mismatch: {case.run_id}"
        )
    attempt_root = _resolve_artifact_path(root, record.attempt_path)
    attempt_record = _read_json(attempt_root / ATTEMPT_RECORD_NAME)
    if (
        attempt_record.get("spec_fingerprint") != spec_fingerprint
        or attempt_record.get("case") != case.model_dump(mode="json")
        or attempt_record.get("attempt_number") != record.attempt_number
    ):
        raise RunCampaignError(
            f"Campaign attempt record identity mismatch: {case.run_id}"
        )
    if record.outcome == "trajectory_recorded":
        trajectory_path = _resolve_artifact_path(
            root,
            record.artifact_paths.get("trajectory", ""),
        )
        try:
            trajectory = Trajectory.model_validate_json(
                trajectory_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise RunCampaignError(
                f"Recorded campaign trajectory is missing or invalid: {case.run_id}"
            ) from exc
        expected = _validate_complete_attempt(root, attempt_root, trajectory)
        if expected != record.artifact_paths:
            raise RunCampaignError(
                f"Campaign run artifact index drift: {case.run_id}"
            )
    return record


def _validate_complete_attempt(
    root: Path,
    attempt_root: Path,
    trajectory: Trajectory,
) -> dict[str, str]:
    required = {
        "trajectory": attempt_root / "trajectory.json",
        "tool_profile": attempt_root / "tool_profile.json",
        "runtime_trace": attempt_root / "runtime_trace.jsonl",
        "runtime_trace_manifest": attempt_root / "runtime_trace_manifest.json",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise RunCampaignError(
            "Campaign executor did not produce complete run artifacts: "
            + ", ".join(sorted(missing))
        )
    saved_trajectory = Trajectory.model_validate_json(
        required["trajectory"].read_text(encoding="utf-8")
    )
    if saved_trajectory.model_dump(mode="json") != trajectory.model_dump(mode="json"):
        raise RunCampaignError("Returned trajectory differs from trajectory.json")
    profile = _read_json(required["tool_profile"])
    trace_manifest = _read_json(required["runtime_trace_manifest"])
    if profile.get("profile_id") != trajectory.tool_profile_id:
        raise RunCampaignError("tool_profile.json identity drift")
    if (
        trace_manifest.get("task_id") != trajectory.task_id
        or trace_manifest.get("tool_profile_id") != trajectory.tool_profile_id
        or trace_manifest.get("ended_at_unix_ms") is None
    ):
        raise RunCampaignError("runtime trace manifest is incomplete or mismatched")
    optional = {
        "verifier": attempt_root / "verifier.json",
        "patch": attempt_root / "patch.diff",
        "run_retention_manifest": attempt_root / "run_retention_manifest.json",
    }
    artifacts = {
        name: _relative(root, path)
        for name, path in required.items()
    }
    artifacts.update(
        {
            name: _relative(root, path)
            for name, path in optional.items()
            if path.is_file()
        }
    )
    return {name: artifacts[name] for name in sorted(artifacts)}


def _write_campaign_artifacts(
    root: Path,
    campaign: RunCampaign,
    plan: Sequence[CampaignRunCase],
    records: Mapping[str, CampaignRunRecord],
    *,
    spec_fingerprint: str,
    plan_fingerprint: str,
    executed_count: int,
    recovered_count: int,
    skipped_count: int,
) -> RunCampaignResult:
    index_entries: list[dict[str, Any]] = []
    for case in plan:
        logical_root = root / "runs" / case.run_id
        record = records.get(case.run_id)
        index_entries.append(
            {
                "case": case.model_dump(mode="json"),
                "disposition": "terminal" if record is not None else "pending",
                "attempt_count": sum(
                    path.is_dir()
                    for path in (logical_root / "attempts").glob("*")
                ),
                "record": (
                    record.model_dump(mode="json") if record is not None else None
                ),
            }
        )
    artifact_index = {
        "schema": CAMPAIGN_ARTIFACT_INDEX_SCHEMA,
        "spec_fingerprint": spec_fingerprint,
        "plan_fingerprint": plan_fingerprint,
        "entries": index_entries,
    }
    _write_json_atomic(root / CAMPAIGN_ARTIFACT_INDEX_NAME, artifact_index)

    outcome_counts = Counter(record.outcome for record in records.values())
    trajectory_status_counts = Counter(
        record.trajectory_status
        for record in records.values()
        if record.trajectory_status is not None
    )
    failure_run_ids = sorted(
        record.case.run_id
        for record in records.values()
        if record.outcome == "executor_error"
        or (
            record.trajectory_status is not None
            and record.trajectory_status != "completed"
        )
    )
    failure_kind_counts = Counter(
        record.failure_kind or "unknown"
        for record in records.values()
        if record.case.run_id in failure_run_ids
    )
    failure_summary = {
        "schema": CAMPAIGN_FAILURE_SUMMARY_SCHEMA,
        "spec_fingerprint": spec_fingerprint,
        "failed_run_count": len(failure_run_ids),
        "failure_kind_counts": _sorted_counter(failure_kind_counts),
        "failed_run_ids": failure_run_ids,
    }
    _write_json_atomic(root / CAMPAIGN_FAILURE_SUMMARY_NAME, failure_summary)

    pending_count = len(plan) - len(records)
    executor_error_count = outcome_counts.get("executor_error", 0)
    failed_trajectory_count = sum(
        count
        for status, count in trajectory_status_counts.items()
        if status != "completed"
    )
    contract_ok = pending_count == 0 and executor_error_count == 0
    manifest = {
        "schema": CAMPAIGN_MANIFEST_SCHEMA,
        "campaign_id": campaign.campaign_id,
        "spec_fingerprint": spec_fingerprint,
        "plan_fingerprint": plan_fingerprint,
        "planned_run_count": len(plan),
        "terminal_run_count": len(records),
        "pending_run_count": pending_count,
        "contract_ok": contract_ok,
        "outcome_counts": _sorted_counter(outcome_counts),
        "trajectory_status_counts": _sorted_counter(trajectory_status_counts),
        "dimensions": {
            "task_ids": list(campaign.matrix.task_ids),
            "families": list(campaign.matrix.families),
            "profile_modes": list(campaign.matrix.profile_modes),
            "profile_seeds": list(campaign.matrix.profile_seeds),
            "provider_ids": [
                provider.provider_id for provider in campaign.matrix.providers
            ],
            "repeat_count": campaign.matrix.repeat_count,
        },
        "paths": {
            "campaign_spec": CAMPAIGN_SPEC_NAME,
            "artifact_index": CAMPAIGN_ARTIFACT_INDEX_NAME,
            "failure_summary": CAMPAIGN_FAILURE_SUMMARY_NAME,
            "runs_root": "runs",
        },
    }
    _write_json_atomic(root / CAMPAIGN_MANIFEST_NAME, manifest)

    return RunCampaignResult(
        output_root=str(root),
        spec_fingerprint=spec_fingerprint,
        plan_fingerprint=plan_fingerprint,
        planned_run_count=len(plan),
        terminal_run_count=len(records),
        pending_run_count=pending_count,
        executed_run_count=executed_count,
        recovered_run_count=recovered_count,
        skipped_run_count=skipped_count,
        executor_error_count=executor_error_count,
        failed_trajectory_count=failed_trajectory_count,
        contract_ok=contract_ok,
        campaign_spec_path=str(root / CAMPAIGN_SPEC_NAME),
        artifact_index_path=str(root / CAMPAIGN_ARTIFACT_INDEX_NAME),
        failure_summary_path=str(root / CAMPAIGN_FAILURE_SUMMARY_NAME),
        manifest_path=str(root / CAMPAIGN_MANIFEST_NAME),
    )


def _write_attempt_record(
    path: Path,
    case: CampaignRunCase,
    spec_fingerprint: str,
    attempt_number: int,
    *,
    outcome: str,
    failure_detail: str | None = None,
) -> None:
    _write_json_atomic(
        path,
        {
            "schema": "pycodeagent-run-campaign-attempt/v1",
            "spec_fingerprint": spec_fingerprint,
            "case": case.model_dump(mode="json"),
            "attempt_number": attempt_number,
            "outcome": outcome,
            "failure_detail": failure_detail,
        },
    )


def _next_attempt_number(logical_run_root: Path) -> int:
    attempts = [
        _attempt_number(path)
        for path in (logical_run_root / "attempts").glob("*")
        if path.is_dir()
    ]
    return max(attempts, default=0) + 1


def _attempt_number(path: Path) -> int:
    match = re.search(r"__attempt_(\d+)$", path.name)
    if match is None:
        raise RunCampaignError(f"Invalid campaign attempt directory: {path}")
    return int(match.group(1))


def _validate_id(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise ValueError(
            f"{field_name} must match {_SAFE_ID.pattern!r}: {value!r}"
        )
    return normalized


def _find_secret_key(value: Any, prefix: str = "metadata") -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}"
            if key_text.lower() in _SECRET_METADATA_KEYS:
                return path
            nested = _find_secret_key(item, path)
            if nested is not None:
                return nested
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            nested = _find_secret_key(item, f"{prefix}[{index}]")
            if nested is not None:
                return nested
    return None


def _sha256_json(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _sorted_counter(counter: Counter[Any]) -> dict[str, int]:
    return {
        str(key): counter[key]
        for key in sorted(counter, key=lambda item: str(item))
    }


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise RunCampaignError(
            f"Campaign artifact escapes output root: {path}"
        ) from exc


def _resolve_artifact_path(root: Path, relative_path: str) -> Path:
    candidate = root / relative_path
    try:
        candidate.resolve().relative_to(root)
    except ValueError as exc:
        raise RunCampaignError(
            f"Campaign artifact escapes output root: {relative_path}"
        ) from exc
    if not candidate.is_file() and not candidate.is_dir():
        raise RunCampaignError(f"Campaign artifact is missing: {relative_path}")
    return candidate


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunCampaignError(f"Invalid JSON artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise RunCampaignError(f"JSON artifact must be an object: {path}")
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
