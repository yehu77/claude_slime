"""Application-service boundary for the formal pycodeagent CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict

from pycodeagent.agent.provider_runtime import (
    RuntimeProviderConfig,
    build_llm_client,
    resolve_runtime_provider_config,
)
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.eval.native_family_acceptance import run_native_family_acceptance
from pycodeagent.eval.real_provider_behavior_baseline import (
    load_realistic_runtime_tasks,
    run_real_provider_behavior_baseline,
)
from pycodeagent.eval.real_provider_credibility_bundle import (
    DEFAULT_CREDIBILITY_PROFILE_MODES,
    DEFAULT_CREDIBILITY_PROFILE_SEED_BY_MODE,
    run_real_provider_credibility_bundle,
)
from pycodeagent.eval.toolview_mutation_data_generation import (
    DEFAULT_MUTATION_DATA_PROFILE_MODES,
    DEFAULT_MUTATION_DATA_PROFILE_SEED_BY_MODE,
    run_real_provider_toolview_mutation_data_generation,
)
from pycodeagent.rl.contract import verify_slime_contract
from pycodeagent.rl.dataset_manifest import FilterConfig
from pycodeagent.rl.schema_following_from_runtime import (
    generate_schema_following_from_runtime_runs,
)
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig, TokenizerConfig
from pycodeagent.rl.training_prep import prepare_slime_training_input
from pycodeagent.tools.bootstrap import ToolStackKind


CLI_MANIFEST_SCHEMA = "pycodeagent-cli-manifest/v1"
CLI_MANIFEST_NAME = "pycodeagent_cli_manifest.json"
FamilyScope = Literal["native_claude", "native_codex", "multi_native"]
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROVIDER_EXAMPLE = (
    _PROJECT_ROOT / "configs/local/real_provider_runtime.local.example.json"
)


class ApplicationServiceResult(BaseModel):
    """Machine-readable result returned by every formal CLI service."""

    model_config = ConfigDict(extra="forbid")

    result_schema: Literal["pycodeagent-cli-service-result/v1"] = (
        "pycodeagent-cli-service-result/v1"
    )
    version: Literal[1] = 1
    command: str
    ok: bool
    status: Literal["succeeded", "contract_failed"]
    output_root: str
    manifest_path: str
    task_ids: list[str]
    profile_modes: list[str]
    profile_seed_by_mode: dict[str, int]
    family: FamilyScope | None = None
    result_type: str
    application_manifest_path: str | None = None
    result: dict[str, Any]


def run_service(options: Mapping[str, Any]) -> ApplicationServiceResult:
    """Run one selected task through the provider-backed local runtime."""

    tasks = _load_tasks(options["tasks"])
    task_id = str(options["task_id"])
    matching = [task for task in tasks if task.task_id == task_id]
    if len(matching) != 1:
        raise ValueError(f"Expected exactly one task_id={task_id!r}")
    task = matching[0]
    family = _family(options)
    profile_mode = str(options["profile_mode"])
    profile_seed = int(options["profile_seed"])
    output_root = Path(options["output_root"]).resolve()
    provider = _provider(options.get("provider_config"))
    trajectory = run_coding_task(
        task,
        build_llm_client(provider),
        output_root,
        profile_mode=profile_mode,
        profile_seed=profile_seed,
        tool_stack_kind=family,
    )
    result = {
        "task_id": trajectory.task_id,
        "status": trajectory.status.value,
        "reward": trajectory.reward,
        "verifier": (
            trajectory.verifier.model_dump(mode="json")
            if trajectory.verifier is not None
            else None
        ),
        "tool_profile_id": trajectory.tool_profile_id,
        "trajectory_path": str(output_root / "trajectory.json"),
        "provider": provider.runtime_provenance(),
    }
    return _finalize(
        command="run",
        ok=trajectory.status.value == "completed",
        output_root=output_root,
        task_ids=[task.task_id],
        profile_modes=[profile_mode],
        profile_seed_by_mode={profile_mode: profile_seed},
        family=family,
        result_type="trajectory",
        application_manifest_path=output_root / "trajectory.json",
        result=result,
    )


def campaign_service(options: Mapping[str, Any]) -> ApplicationServiceResult:
    """Run one active provider campaign through its application service."""

    kind = str(options["kind"])
    family = _family(options)
    tasks_path = Path(options["tasks"])
    output_root = Path(options["output_root"]).resolve()
    repeat_count = int(options["repeat_count"])
    provider = _provider(options.get("provider_config"))
    task_ids = sorted(task.task_id for task in _load_tasks(tasks_path))
    modes = [str(mode) for mode in options["profile_modes"]]
    seeds = {
        str(mode): int(seed)
        for mode, seed in dict(options["profile_seed_by_mode"]).items()
    }

    if kind == "behavior":
        if len(modes) != 1:
            raise ValueError("behavior campaign requires exactly one profile mode")
        result = run_real_provider_behavior_baseline(
            provider,
            output_root,
            tasks_path=tasks_path,
            repeat_count=repeat_count,
            profile_mode=modes[0],
            tool_stack_kind=family,
        )
        ok = result.campaign_contract_ok
        application_manifest = result.campaign_group_manifest_path
    elif kind == "credibility":
        result = run_real_provider_credibility_bundle(
            provider,
            output_root,
            tasks_path=tasks_path,
            profile_modes=modes,
            profile_seed_by_mode=seeds,
            repeat_count=repeat_count,
            tool_stack_kind=family,
            **_tokenizer_kwargs(options),
        )
        ok = result.contract_ok
        application_manifest = result.credibility_manifest_path
    elif kind == "toolview":
        prepare_training_input = bool(options["prepare_training_input"])
        result = run_real_provider_toolview_mutation_data_generation(
            provider,
            output_root,
            tasks_path=tasks_path,
            profile_modes=modes,
            profile_seed_by_mode=seeds,
            repeat_count=repeat_count,
            tool_stack_kind=family,
            prepare_training_input=prepare_training_input,
            **(_tokenizer_kwargs(options) if prepare_training_input else {}),
        )
        ok = result.contract_ok
        application_manifest = result.generation_manifest_path
    else:
        raise ValueError(f"Unknown campaign kind: {kind!r}")

    return _finalize(
        command="campaign",
        ok=bool(ok),
        output_root=output_root,
        task_ids=task_ids,
        profile_modes=modes,
        profile_seed_by_mode=seeds,
        family=family,
        result_type=type(result).__name__,
        application_manifest_path=Path(application_manifest),
        result=result.model_dump(mode="json"),
    )


def export_service(options: Mapping[str, Any]) -> ApplicationServiceResult:
    """Export observed ToolView samples from runtime run artifacts."""

    output_root = Path(options["output_dir"]).resolve()
    result = generate_schema_following_from_runtime_runs(
        Path(options["source_dir"]),
        output_root,
        source_type=str(options["source_type"]),
        filter_config=FilterConfig(
            include_failed=bool(options["include_failed"]),
        ),
        split_seed=int(options["seed"]),
    )
    return _finalize(
        command="export",
        ok=result.sample_count > 0,
        output_root=output_root,
        task_ids=[],
        profile_modes=[],
        profile_seed_by_mode={},
        family=None,
        result_type=type(result).__name__,
        application_manifest_path=Path(result.dataset_manifest_path),
        result=result.model_dump(mode="json"),
    )


def prep_service(options: Mapping[str, Any]) -> ApplicationServiceResult:
    """Build the canonical slime-compatible training-prep bundle."""

    output_root = Path(options["output_dir"]).resolve()
    recommendation = prepare_slime_training_input(
        Path(options["source_dir"]),
        output_root,
        source_type=str(options["source_type"]),
        include_failed=bool(options["include_failed"]),
        verifier_passed=_optional_bool(options["verifier_passed"]),
        max_length=int(options["max_length"]),
        batch_size=int(options["batch_size"]),
        learning_rate=float(options["learning_rate"]),
        max_steps=int(options["max_steps"]),
        seed=int(options["seed"]),
        run_id=str(options["run_id"]),
        **_tokenizer_kwargs(options),
    )
    return _finalize(
        command="prep",
        ok=recommendation.contract_ok,
        output_root=output_root,
        task_ids=[],
        profile_modes=[],
        profile_seed_by_mode={},
        family=None,
        result_type=type(recommendation).__name__,
        application_manifest_path=Path(recommendation.bundle_manifest_path),
        result=recommendation.model_dump(mode="json"),
    )


def verify_service(options: Mapping[str, Any]) -> ApplicationServiceResult:
    """Verify the slime contract through the read-only verifier service."""

    output_root = Path(options["output_dir"]).resolve()
    result = verify_slime_contract(
        Path(options["source_dir"]),
        output_root,
        source_type=str(options["source_type"]),
        filter_config=FilterConfig(
            include_failed=bool(options["include_failed"]),
        ),
        pack_max_length=int(options["max_length"]),
        write_report=True,
        **_tokenizer_kwargs(options),
    )
    report_path = output_root / "contract_report.json"
    return _finalize(
        command="verify",
        ok=result.ok,
        output_root=output_root,
        task_ids=[],
        profile_modes=[],
        profile_seed_by_mode={},
        family=None,
        result_type=type(result).__name__,
        application_manifest_path=report_path if report_path.is_file() else None,
        result=result.model_dump(mode="json"),
    )


def acceptance_service(options: Mapping[str, Any]) -> ApplicationServiceResult:
    """Run the native-family acceptance service."""

    local_only = bool(options["local_only"])
    base_root = Path(options["output_root"]).resolve()
    provider: RuntimeProviderConfig | None = None
    if local_only:
        output_root = base_root / "local_only"
    else:
        provider = _provider(options.get("provider_config"))
        output_root = base_root / f"{provider.client_mode}__{provider.model}"
    report = run_native_family_acceptance(
        output_root,
        provider_config=provider,
        include_real_provider=not local_only,
    )
    report_path = Path(report.output_root) / "native_family_acceptance_report.json"
    result = {
        "stabilized": report.stabilized,
        "provider": report.provider,
        "entrypoint_check_count": len(report.entrypoint_checks),
        "regression_command_count": len(report.regression_commands),
        "real_provider_task_count": len(report.real_provider_tasks),
        "native_codex_task_count": len(report.native_codex_tasks),
        "generation_smoke_count": len(report.generation_smokes),
        "report_path": str(report_path),
    }
    return _finalize(
        command="acceptance",
        ok=report.stabilized,
        output_root=Path(report.output_root),
        task_ids=sorted(
            {
                task.task_id
                for task in [
                    *report.real_provider_tasks,
                    *report.native_codex_tasks,
                ]
            }
        ),
        profile_modes=list(DEFAULT_MUTATION_DATA_PROFILE_MODES),
        profile_seed_by_mode=dict(DEFAULT_MUTATION_DATA_PROFILE_SEED_BY_MODE),
        family="multi_native",
        result_type=type(report).__name__,
        application_manifest_path=report_path,
        result=result,
    )


def campaign_defaults(kind: str) -> tuple[list[str], dict[str, int], int]:
    """Return stable active-campaign defaults for CLI normalization."""

    if kind == "behavior":
        return ["base"], {"base": 0}, 3
    if kind == "credibility":
        return (
            list(DEFAULT_CREDIBILITY_PROFILE_MODES),
            dict(DEFAULT_CREDIBILITY_PROFILE_SEED_BY_MODE),
            3,
        )
    if kind == "toolview":
        return (
            list(DEFAULT_MUTATION_DATA_PROFILE_MODES),
            dict(DEFAULT_MUTATION_DATA_PROFILE_SEED_BY_MODE),
            1,
        )
    raise ValueError(f"Unknown campaign kind: {kind!r}")


def _provider(path: str | Path | None) -> RuntimeProviderConfig:
    return resolve_runtime_provider_config(
        Path(path) if path is not None else None,
        example_path=_PROVIDER_EXAMPLE,
    )


def _load_tasks(path: str | Path) -> list[CodingTask]:
    tasks = CodingTask.from_jsonl(Path(path))
    resolved: list[CodingTask] = []
    for task in tasks:
        repo_path = task.repo_path
        if not repo_path.is_absolute():
            repo_path = (_PROJECT_ROOT / repo_path).resolve()
        resolved.append(task.model_copy(update={"repo_path": repo_path}))
    return resolved


def _family(options: Mapping[str, Any]) -> ToolStackKind:
    family = str(options["family"])
    if family not in {"native_claude", "native_codex"}:
        raise ValueError(f"Unknown native family: {family!r}")
    return family  # type: ignore[return-value]


def _tokenizer_kwargs(options: Mapping[str, Any]) -> dict[str, Any]:
    max_length = int(options.get("max_length", 2048))
    tokenizer_name = options.get("tokenizer_name")
    fake_tokenizer = bool(options.get("fake_tokenizer"))
    if tokenizer_name and fake_tokenizer:
        raise ValueError("Choose tokenizer_name or fake_tokenizer, not both")
    if tokenizer_name:
        return {
            "tokenizer_config": TokenizerConfig(
                tokenizer_name=str(tokenizer_name),
                max_length=max_length,
            ),
            "fake_tokenizer_config": None,
        }
    if fake_tokenizer:
        return {
            "tokenizer_config": TokenizerConfig(
                tokenizer_name="fake",
                max_length=max_length,
            ),
            "fake_tokenizer_config": FakeTokenizerConfig(
                vocab_size=int(options.get("fake_vocab_size", 1000)),
                chars_per_token=int(options.get("fake_chars_per_token", 4)),
            ),
        }
    raise ValueError("Explicit tokenizer_name or fake_tokenizer=true is required")


def _optional_bool(value: Any) -> bool | None:
    if value == "any" or value is None:
        return None
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    raise ValueError(f"Invalid optional boolean value: {value!r}")


def _finalize(
    *,
    command: str,
    ok: bool,
    output_root: Path,
    task_ids: list[str],
    profile_modes: list[str],
    profile_seed_by_mode: dict[str, int],
    family: FamilyScope | None,
    result_type: str,
    application_manifest_path: Path | None,
    result: dict[str, Any],
) -> ApplicationServiceResult:
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / CLI_MANIFEST_NAME
    payload = {
        "schema": CLI_MANIFEST_SCHEMA,
        "version": 1,
        "command": command,
        "status": "succeeded" if ok else "contract_failed",
        "task_ids": sorted(task_ids),
        "profile": {
            "modes": list(profile_modes),
            "seed_by_mode": {
                mode: profile_seed_by_mode[mode]
                for mode in sorted(profile_seed_by_mode)
            },
        },
        "family": family,
        "result_type": result_type,
        "application_manifest_path": (
            str(application_manifest_path)
            if application_manifest_path is not None
            else None
        ),
        "result": result,
    }
    _write_json_atomic(manifest_path, payload)
    return ApplicationServiceResult(
        command=command,
        ok=ok,
        status="succeeded" if ok else "contract_failed",
        output_root=str(output_root),
        manifest_path=str(manifest_path),
        task_ids=sorted(task_ids),
        profile_modes=list(profile_modes),
        profile_seed_by_mode=dict(profile_seed_by_mode),
        family=family,
        result_type=result_type,
        application_manifest_path=(
            str(application_manifest_path)
            if application_manifest_path is not None
            else None
        ),
        result=result,
    )


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
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
