"""Acceptance runner for the native-family tool-runtime path."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pycodeagent.agent import (
    FakeLLMClient,
    build_llm_client,
    resolve_runtime_provider_config,
)
from pycodeagent.agent.llm_client import GenerateResponse, ToolCallCandidate
from pycodeagent.agent.provider_runtime import RuntimeProviderConfig
from pycodeagent.dev import resolve_local_config_path
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.eval.toolview_mutation_data_generation import (
    DEFAULT_MUTATION_DATA_PROFILE_MODES,
    DEFAULT_MUTATION_DATA_PROFILE_SEED_BY_MODE,
    run_toolview_mutation_data_generation,
)
from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig
from pycodeagent.tools import (
    build_native_claude_profile,
    build_native_claude_runtime,
    build_native_codex_profile,
    build_native_codex_runtime,
)
from pycodeagent.tools.context import ToolContext
from pycodeagent.trajectory.schema import ToolCall


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_CONFIG_FILENAME = "real_provider_runtime.local.json"
_REPO_LOCAL_CONFIG_PATH = _PROJECT_ROOT / "configs" / "local" / _LOCAL_CONFIG_FILENAME
_LOCAL_CONFIG_EXAMPLE_PATH = (
    _PROJECT_ROOT / "configs" / "local" / "real_provider_runtime.local.example.json"
)
_DEFAULT_NATIVE_FAMILY_MUTATION_CONFIG = (
    _PROJECT_ROOT / "configs" / "tools" / "native_family_mutation_v1.yaml"
)
_REGRESSION_DETERMINISTIC = [
    "tests/test_process_exec.py",
    "tests/test_shell_runtimes.py",
    "tests/test_patch_runtime.py",
    "tests/test_step_c0_tool_contracts.py",
    "tests/test_strict_family_tools.py",
    "tests/test_tools_bootstrap.py",
    "tests/test_tool_stack_selection.py",
    "tests/test_native_profile_transform.py",
    "tests/test_profile_sampler.py",
    "tests/test_schema_following_sample.py",
]
_REGRESSION_RUNTIME_OBSERVED = [
    "tests/test_schema_following_from_runtime.py",
    "tests/test_schema_following_from_runtime_golden.py",
    "tests/test_runtime_observed_postrun.py",
    "tests/test_runtime_observed_postrun_golden.py",
    "tests/test_runtime_observed_training_prep_golden.py",
    "tests/test_toolview_mutation_data_generation.py",
    "tests/test_runtime_execution_reconciliation.py",
]
_CLAUDE_NATIVE_TOOLS = ["Bash", "Read", "Edit", "Write", "Grep", "Glob"]
_CODEX_NATIVE_TOOLS = ["exec_command", "write_stdin", "apply_patch"]


class CommandResult(BaseModel):
    name: str
    command: list[str]
    exit_code: int
    duration_seconds: float
    passed: bool
    stdout_path: str
    stderr_path: str


class EntrypointCheckResult(BaseModel):
    name: str
    passed: bool
    profile_id: str | None = None
    tool_names: list[str] = Field(default_factory=list)
    detail: str = ""


class TaskAcceptanceResult(BaseModel):
    task_id: str
    family: str
    passed: bool
    output_dir: str
    repo_path: str
    status: str
    verifier_passed: bool | None = None
    reward: float | None = None
    tool_profile_id: str | None = None
    tool_names: list[str] = Field(default_factory=list)
    canonical_names: list[str] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)
    required_tools_all: list[str] = Field(default_factory=list)
    required_tools_any: list[str] = Field(default_factory=list)
    workspace_changed: bool | None = None
    notes: list[str] = Field(default_factory=list)


class DirectFlowResult(BaseModel):
    name: str
    family: str
    passed: bool
    workspace_root: str
    detail: str
    tool_results: dict[str, dict[str, Any]] = Field(default_factory=dict)


class GenerationSmokeResult(BaseModel):
    family: str
    passed: bool
    output_root: str
    raw_dataset_manifest_path: str
    acceptance_report_path: str
    contract_ok: bool
    observed_sample_count: int
    sample_count_by_family: dict[str, int] = Field(default_factory=dict)
    sample_count_by_contract_kind: dict[str, int] = Field(default_factory=dict)


class NativeFamilyAcceptanceReport(BaseModel):
    version: int = 1
    generated_at: str
    output_root: str
    provider: dict[str, Any] = Field(default_factory=dict)
    entrypoint_checks: list[EntrypointCheckResult] = Field(default_factory=list)
    regression_commands: list[CommandResult] = Field(default_factory=list)
    real_provider_tasks: list[TaskAcceptanceResult] = Field(default_factory=list)
    native_codex_tasks: list[TaskAcceptanceResult] = Field(default_factory=list)
    native_codex_direct_flow: DirectFlowResult | None = None
    generation_smokes: list[GenerationSmokeResult] = Field(default_factory=list)
    codex_real_provider_transport_limited: bool = True
    codex_real_provider_transport_note: str = (
        "Strict Codex real-provider acceptance remains blocked because the "
        "current OpenAI-compatible native tool transport is function-only, "
        "while strict apply_patch is freeform."
    )
    stabilized: bool = False


def run_native_family_acceptance(
    output_root: str | Path,
    *,
    provider_config: RuntimeProviderConfig | str | Path | None = None,
    include_real_provider: bool = True,
) -> NativeFamilyAcceptanceReport:
    """Run the native-family acceptance pack and write a JSON report."""
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    pytest_python = _resolve_pytest_python()
    test_python = pytest_python
    provider: dict[str, Any] = {}
    resolved_provider: RuntimeProviderConfig | None = None
    if include_real_provider:
        resolved_provider = _resolve_default_provider_config(provider_config)
        provider = resolved_provider.runtime_provenance()

    entrypoint_checks = _run_entrypoint_checks()
    regression_commands = [
        _run_pytest_suite(
            "deterministic_regression",
            _REGRESSION_DETERMINISTIC,
            output_root / "regression",
            pytest_python,
        ),
        _run_pytest_suite(
            "runtime_observed_regression",
            _REGRESSION_RUNTIME_OBSERVED,
            output_root / "regression",
            pytest_python,
        ),
    ]

    real_provider_tasks: list[TaskAcceptanceResult] = []
    if include_real_provider and resolved_provider is not None:
        real_provider_tasks = _run_native_claude_real_provider_pack(
            resolved_provider,
            output_root / "native_claude_real_provider",
            test_python,
        )

    native_codex_tasks = _run_native_codex_repo_task_pack(
        output_root / "native_codex_local",
        test_python,
    )
    native_codex_direct_flow = _run_native_codex_direct_flow(
        output_root / "native_codex_direct_flow"
    )
    generation_smokes = _run_generation_smokes(
        output_root / "generation_smokes",
        test_python,
    )

    report = NativeFamilyAcceptanceReport(
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        output_root=str(output_root),
        provider=provider,
        entrypoint_checks=entrypoint_checks,
        regression_commands=regression_commands,
        real_provider_tasks=real_provider_tasks,
        native_codex_tasks=native_codex_tasks,
        native_codex_direct_flow=native_codex_direct_flow,
        generation_smokes=generation_smokes,
    )
    report.stabilized = _report_is_stabilized(report, include_real_provider=include_real_provider)

    report_path = output_root / "native_family_acceptance_report.json"
    _write_json(report_path, report.model_dump(mode="json"))
    return report


def _resolve_default_provider_config(
    provider_config: RuntimeProviderConfig | str | Path | None,
) -> RuntimeProviderConfig:
    if isinstance(provider_config, RuntimeProviderConfig):
        return provider_config
    if provider_config is not None:
        return resolve_runtime_provider_config(provider_config, example_path=_LOCAL_CONFIG_EXAMPLE_PATH)
    resolved_path = resolve_local_config_path(
        _LOCAL_CONFIG_FILENAME,
        repo_fallback=_REPO_LOCAL_CONFIG_PATH,
    )
    return resolve_runtime_provider_config(
        resolved_path,
        example_path=_LOCAL_CONFIG_EXAMPLE_PATH,
    )


def _resolve_pytest_python() -> Path:
    candidates = [
        _PROJECT_ROOT / ".venv-regression" / "bin" / "python",
        _PROJECT_ROOT / ".venv" / "bin" / "python",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        probe = subprocess.run(
            [str(candidate), "-m", "pytest", "--version"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            return candidate
    raise RuntimeError("Could not find a Python interpreter with pytest available")


def _run_pytest_suite(
    name: str,
    test_paths: list[str],
    logs_root: Path,
    python_executable: Path,
) -> CommandResult:
    logs_root.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_root / f"{name}.stdout.log"
    stderr_path = logs_root / f"{name}.stderr.log"
    command = [str(python_executable), "-m", "pytest", "-q", *test_paths]
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    duration_seconds = round(time.perf_counter() - started, 3)
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    return CommandResult(
        name=name,
        command=command,
        exit_code=completed.returncode,
        duration_seconds=duration_seconds,
        passed=completed.returncode == 0,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
    )


def _run_entrypoint_checks() -> list[EntrypointCheckResult]:
    results: list[EntrypointCheckResult] = []

    claude_registry, claude_profile, _ = build_native_claude_runtime()
    claude_profile_only = build_native_claude_profile()
    claude_tools = [tool.canonical_name for tool in claude_profile.tools]
    claude_registry_tools = [tool.canonical_name for tool in claude_registry.list()]
    results.append(
        EntrypointCheckResult(
            name="build_native_claude_runtime",
            passed=claude_tools == _CLAUDE_NATIVE_TOOLS
            and claude_registry_tools == _CLAUDE_NATIVE_TOOLS,
            profile_id=claude_profile.profile_id,
            tool_names=claude_tools,
            detail="Strict Claude runtime stack should expose the native Claude tool set.",
        )
    )
    results.append(
        EntrypointCheckResult(
            name="build_native_claude_profile",
            passed=[tool.canonical_name for tool in claude_profile_only.tools] == _CLAUDE_NATIVE_TOOLS,
            profile_id=claude_profile_only.profile_id,
            tool_names=[tool.canonical_name for tool in claude_profile_only.tools],
            detail="Strict Claude profile should preserve source-aligned native names.",
        )
    )

    codex_registry, codex_profile, _ = build_native_codex_runtime()
    codex_profile_only = build_native_codex_profile()
    codex_tools = [tool.canonical_name for tool in codex_profile.tools]
    codex_registry_tools = [tool.canonical_name for tool in codex_registry.list()]
    results.append(
        EntrypointCheckResult(
            name="build_native_codex_runtime",
            passed=codex_tools == _CODEX_NATIVE_TOOLS
            and codex_registry_tools == _CODEX_NATIVE_TOOLS,
            profile_id=codex_profile.profile_id,
            tool_names=codex_tools,
            detail="Strict Codex runtime stack should expose exec_command, write_stdin, and apply_patch.",
        )
    )
    results.append(
        EntrypointCheckResult(
            name="build_native_codex_profile",
            passed=[tool.canonical_name for tool in codex_profile_only.tools] == _CODEX_NATIVE_TOOLS,
            profile_id=codex_profile_only.profile_id,
            tool_names=[tool.canonical_name for tool in codex_profile_only.tools],
            detail="Strict Codex profile should preserve freeform apply_patch.",
        )
    )
    return results


def _run_native_claude_real_provider_pack(
    provider_config: RuntimeProviderConfig,
    output_root: Path,
    test_python: Path,
) -> list[TaskAcceptanceResult]:
    formatter_validation_command = f"{test_python} -m pytest -q test_formatter.py"
    labels_validation_command = f"{test_python} -m pytest -q test_labels.py"
    tasks = [
        _TaskSpec(
            task_id="native_claude_read_only_smoke",
            source_repo=_PROJECT_ROOT / "examples" / "runtime_rewrite_greeter",
            prompt=(
                "Use the Read tool to inspect greeter.py. Do not modify any files, "
                "and do not use Bash for this task. Then give a one-sentence answer "
                "describing what render_greeting currently returns."
            ),
            test_command=[str(test_python), "-c", "print('native claude smoke ok')"],
            max_turns=4,
            required_tools_all=["Read"],
            forbid_workspace_changes=True,
        ),
        _TaskSpec(
            task_id="native_claude_fix_formatter",
            source_repo=_PROJECT_ROOT / "examples" / "buggy_formatter",
            prompt=(
                "Use Read first, then Edit or Write as needed, to fix the broken "
                "greet(name) behavior in formatter.py. Keep the change minimal. "
                f"For validation, use Bash with `{formatter_validation_command}` "
                "from the current directory. Do not install packages and do not "
                "use `cd /workspace`. "
                "As soon as you have one successful validation result, stop "
                "immediately without any extra inspection."
            ),
            test_command=[str(test_python), "-m", "pytest", "-q"],
            max_turns=10,
            required_tools_all=["Read"],
            required_tools_any=["Edit", "Write"],
        ),
        _TaskSpec(
            task_id="native_claude_fix_labels_with_search",
            source_repo=_PROJECT_ROOT / "examples" / "feature_labels",
            prompt=(
                "First use Grep with the prefix-related pattern to locate the "
                "prefix test, then use Glob to confirm the relevant files and find "
                "the matching implementation. Make the minimal code change so the "
                "tests pass. Use the Claude-native file tools for the edit. "
                f"For validation, use Bash with `{labels_validation_command}` "
                "from the current directory. Do not install packages and do not "
                "use `cd /workspace`. "
                "As soon as you have one successful validation result, stop "
                "immediately without any extra inspection."
            ),
            test_command=[str(test_python), "-m", "pytest", "-q"],
            max_turns=12,
            required_tools_all=["Glob", "Grep"],
            required_tools_any=["Edit", "Write"],
        ),
    ]
    return [
        _run_real_provider_task(
            task_spec,
            provider_config,
            output_root / task_spec.task_id,
        )
        for task_spec in tasks
    ]


def _run_real_provider_task(
    task_spec: "_TaskSpec",
    provider_config: RuntimeProviderConfig,
    task_root: Path,
) -> TaskAcceptanceResult:
    workspace_root = (task_root / "workspace").resolve()
    run_dir = (task_root / "run").resolve()
    _copy_repo(task_spec.source_repo, workspace_root)
    task = CodingTask(
        task_id=task_spec.task_id,
        repo_path=workspace_root,
        prompt=task_spec.prompt,
        test_command=task_spec.test_command,
        max_turns=task_spec.max_turns,
        metadata={"category": "native_family_acceptance", "family": "claude"},
    )
    trajectory = run_coding_task(
        task,
        build_llm_client(provider_config),
        run_dir,
        tool_stack_kind="native_claude",
    )
    tool_names = [call.name for call in trajectory.tool_calls]
    canonical_names = [str(call.canonical_name or "") for call in trajectory.tool_calls]
    verifier_passed = trajectory.verifier.passed if trajectory.verifier is not None else None
    notes: list[str] = []
    missing_required_all = [
        tool for tool in task_spec.required_tools_all if tool not in tool_names
    ]
    if missing_required_all:
        notes.append(
            "Missing required native tool usage: "
            + ", ".join(missing_required_all)
        )
    missing_required_any = bool(task_spec.required_tools_any) and not any(
        tool in tool_names for tool in task_spec.required_tools_any
    )
    if missing_required_any:
        notes.append(
            "Expected at least one of these native tools: "
            + ", ".join(task_spec.required_tools_any)
        )
    workspace_changed = _repo_tree_changed(task_spec.source_repo, workspace_root)
    if task_spec.forbid_workspace_changes and workspace_changed:
        notes.append("Workspace changed during a read-only acceptance task.")
    passed = (
        trajectory.status.value == "completed"
        and verifier_passed is True
        and not missing_required_all
        and not missing_required_any
        and (
            not task_spec.forbid_workspace_changes
            or workspace_changed is False
        )
    )
    return TaskAcceptanceResult(
        task_id=task_spec.task_id,
        family="claude",
        passed=passed,
        output_dir=str(run_dir),
        repo_path=str(workspace_root),
        status=trajectory.status.value,
        verifier_passed=verifier_passed,
        reward=trajectory.reward,
        tool_profile_id=trajectory.tool_profile_id,
        tool_names=tool_names,
        canonical_names=canonical_names,
        expected_tools=sorted(
            {
                *task_spec.required_tools_all,
                *task_spec.required_tools_any,
            }
        ),
        required_tools_all=list(task_spec.required_tools_all),
        required_tools_any=list(task_spec.required_tools_any),
        workspace_changed=workspace_changed,
        notes=notes,
    )


def _run_native_codex_repo_task_pack(
    output_root: Path,
    test_python: Path,
) -> list[TaskAcceptanceResult]:
    task_specs = [
        _TaskSpec(
            task_id="native_codex_exec_command_smoke",
            source_repo=_PROJECT_ROOT / "examples" / "runtime_rewrite_greeter",
            prompt="Run one exec_command to print the current working directory and then stop.",
            test_command=[str(test_python), "-c", "print('native codex exec smoke ok')"],
            max_turns=3,
            required_tools_all=["exec_command"],
            forbid_workspace_changes=True,
        ),
        _TaskSpec(
            task_id="native_codex_write_stdin_smoke",
            source_repo=_PROJECT_ROOT / "examples" / "runtime_rewrite_greeter",
            prompt="Start an interactive command with exec_command, continue it with write_stdin, then stop.",
            test_command=[str(test_python), "-c", "print('native codex stdin smoke ok')"],
            max_turns=4,
            required_tools_all=["exec_command", "write_stdin"],
            forbid_workspace_changes=True,
        ),
        _TaskSpec(
            task_id="native_codex_repo_patch",
            source_repo=_PROJECT_ROOT / "examples" / "runtime_realistic_patch_calculator",
            prompt="Fix the add() bug using apply_patch and stop when the tests pass.",
            test_command=[str(test_python), "-m", "pytest", "-q"],
            max_turns=4,
            required_tools_all=["apply_patch"],
        ),
    ]
    return [
        _run_native_codex_repo_task(
            task_spec,
            output_root / task_spec.task_id,
        )
        for task_spec in task_specs
    ]


def _run_native_codex_repo_task(
    task_spec: "_TaskSpec",
    task_root: Path,
) -> TaskAcceptanceResult:
    workspace_root = (task_root / "workspace").resolve()
    run_dir = (task_root / "run").resolve()
    _copy_repo(task_spec.source_repo, workspace_root)
    task = CodingTask(
        task_id=task_spec.task_id,
        repo_path=workspace_root,
        prompt=task_spec.prompt,
        test_command=task_spec.test_command,
        max_turns=task_spec.max_turns,
        metadata={"category": "native_family_acceptance", "family": "codex"},
    )
    client = _native_codex_acceptance_client(task_spec.task_id)
    trajectory = run_coding_task(
        task,
        client,
        run_dir,
        tool_stack_kind="native_codex",
    )
    tool_names = [call.name for call in trajectory.tool_calls]
    canonical_names = [str(call.canonical_name or "") for call in trajectory.tool_calls]
    verifier_passed = trajectory.verifier.passed if trajectory.verifier is not None else None
    missing_required_all = [
        tool for tool in task_spec.required_tools_all if tool not in tool_names
    ]
    workspace_changed = _repo_tree_changed(task_spec.source_repo, workspace_root)
    notes: list[str] = []
    if missing_required_all:
        notes.append(
            "Missing required native tool usage: "
            + ", ".join(missing_required_all)
        )
    if task_spec.forbid_workspace_changes and workspace_changed:
        notes.append("Workspace changed during a read-only acceptance task.")
    passed = (
        trajectory.status.value == "completed"
        and verifier_passed is True
        and not missing_required_all
        and (
            not task_spec.forbid_workspace_changes
            or workspace_changed is False
        )
    )
    return TaskAcceptanceResult(
        task_id=task_spec.task_id,
        family="codex",
        passed=passed,
        output_dir=str(run_dir),
        repo_path=str(workspace_root),
        status=trajectory.status.value,
        verifier_passed=verifier_passed,
        reward=trajectory.reward,
        tool_profile_id=trajectory.tool_profile_id,
        tool_names=tool_names,
        canonical_names=canonical_names,
        expected_tools=list(task_spec.required_tools_all),
        required_tools_all=list(task_spec.required_tools_all),
        required_tools_any=[],
        workspace_changed=workspace_changed,
        notes=notes,
    )


def _run_native_codex_direct_flow(output_root: Path) -> DirectFlowResult:
    output_root = output_root.resolve()
    workspace_root = (output_root / "workspace").resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    target = workspace_root / "calc.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    registry, profile, runtime = build_native_codex_runtime()
    ctx = ToolContext(workspace_root=workspace_root, artifact_root=output_root / "artifacts")

    exec_result = runtime.execute(
        ToolCall(
            id="exec_1",
            name="exec_command",
            arguments={
                "cmd": "IFS= read -r line; printf '%s' \"$line\"",
                "tty": True,
                "yield_time_ms": 50,
            },
        ),
        profile,
        ctx=ctx,
    )
    session_id = exec_result.metadata.get("session_id")
    stdin_result = runtime.execute(
        ToolCall(
            id="stdin_1",
            name="write_stdin",
            arguments={
                "session_id": session_id,
                "chars": "hello\n",
                "yield_time_ms": 500,
            },
        ),
        profile,
        ctx=ctx,
    )
    patch_result = runtime.execute(
        ToolCall(
            id="patch_1",
            name="apply_patch",
            input_text=(
                "*** Begin Patch\n"
                "*** Update File: calc.py\n"
                "@@\n"
                "-def add(a, b):\n"
                "-    return a - b\n"
                "+def add(a, b):\n"
                "+    return a + b\n"
                "*** End Patch\n"
            ),
        ),
        profile,
        ctx=ctx,
    )
    passed = (
        exec_result.ok
        and session_id is not None
        and stdin_result.ok
        and patch_result.ok
        and target.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"
    )
    flow_result = DirectFlowResult(
        name="native_codex_direct_flow",
        family="codex",
        passed=passed,
        workspace_root=str(workspace_root),
        detail="Strict Codex direct flow should cover exec_command, write_stdin, and freeform apply_patch.",
        tool_results={
            "exec_command": {
                "ok": exec_result.ok,
                "metadata": dict(exec_result.metadata),
                "content": exec_result.content,
            },
            "write_stdin": {
                "ok": stdin_result.ok,
                "metadata": dict(stdin_result.metadata),
                "content": stdin_result.content,
            },
            "apply_patch": {
                "ok": patch_result.ok,
                "metadata": dict(patch_result.metadata),
                "content": patch_result.content,
            },
        },
    )
    _write_json(output_root / "native_codex_direct_flow.json", flow_result.model_dump(mode="json"))
    return flow_result


def _run_generation_smokes(output_root: Path, test_python: Path) -> list[GenerationSmokeResult]:
    tasks, tasks_path = _make_generation_tasks(output_root, test_python)
    provider = {
        "provider_kind": "fake_acceptance",
        "client_mode": "native_tools",
        "model": "fake-model",
    }
    claude_result = run_toolview_mutation_data_generation(
        tasks,
        _native_claude_client_factory,
        output_root / "native_claude",
        tasks_path=tasks_path,
        provider=provider,
        tool_stack_kind="native_claude",
        fake_tokenizer_config=FakeTokenizerConfig(),
    )
    codex_result = run_toolview_mutation_data_generation(
        tasks,
        _native_codex_client_factory,
        output_root / "native_codex",
        tasks_path=tasks_path,
        provider=provider,
        tool_stack_kind="native_codex",
        fake_tokenizer_config=FakeTokenizerConfig(),
    )
    return [
        _to_generation_smoke_result("claude", claude_result),
        _to_generation_smoke_result("codex", codex_result),
    ]


def _make_generation_tasks(
    output_root: Path,
    test_python: Path,
) -> tuple[list[CodingTask], Path]:
    repo = output_root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (repo / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    tasks = [
        CodingTask(
            task_id="native_family_generation_smoke",
            repo_path=repo,
            prompt="Inspect main.py and stop.",
            test_command=[str(test_python), "-c", "print('ok')"],
            max_turns=4,
        )
    ]
    tasks_path = output_root / "tasks.jsonl"
    tasks_path.write_text(
        "".join(task.model_dump_json() + "\n" for task in tasks),
        encoding="utf-8",
    )
    return tasks, tasks_path


def _native_claude_client_factory(
    task: CodingTask,
    mode: str,
    repeat_index: int,
) -> FakeLLMClient:
    profile = ToolProfileSampler(
        seed=DEFAULT_MUTATION_DATA_PROFILE_SEED_BY_MODE[mode],
        mutation_config_path=_DEFAULT_NATIVE_FAMILY_MUTATION_CONFIG,
        base_profile=build_native_claude_profile(),
    ).sample(mode)
    read_call = profile.project_canonical_payload(
        "Read",
        canonical_args={"file_path": "main.py"},
        call_id="c1",
    )
    return FakeLLMClient(
        responses=[
            GenerateResponse.from_native_tool_calling(
                assistant_text="I will inspect main.py first.",
                tool_calls=[
                    ToolCallCandidate(
                        call_id=str(read_call.call_id),
                        name=str(read_call.name),
                        arguments_raw=json.dumps(read_call.arguments, ensure_ascii=False),
                        arguments_obj=dict(read_call.arguments),
                        source="native",
                    )
                ],
                finish_reason="tool_calls",
                response_id=f"{task.task_id}_{mode}_{repeat_index}_resp_1",
            ),
            GenerateResponse.from_native_tool_calling(
                assistant_text="Done.",
                finish_reason="stop",
                response_id=f"{task.task_id}_{mode}_{repeat_index}_resp_2",
            ),
        ],
        provenance={"provider_kind": "fake", "family": "claude"},
    )


def _native_codex_client_factory(
    task: CodingTask,
    mode: str,
    repeat_index: int,
) -> FakeLLMClient:
    profile = ToolProfileSampler(
        seed=DEFAULT_MUTATION_DATA_PROFILE_SEED_BY_MODE[mode],
        mutation_config_path=_DEFAULT_NATIVE_FAMILY_MUTATION_CONFIG,
        base_profile=build_native_codex_profile(),
    ).sample(mode)
    patch_call = profile.project_canonical_payload(
        "apply_patch",
        canonical_input_text=(
            "*** Begin Patch\n"
            "*** Update File: main.py\n"
            "@@\n"
            "-print('hello')\n"
            "+print('hola')\n"
            "*** End Patch\n"
        ),
        call_id="c1",
    )
    return FakeLLMClient(
        responses=[
            GenerateResponse.from_native_tool_calling(
                assistant_text="Applying the patch.",
                tool_calls=[
                    ToolCallCandidate(
                        call_id=str(patch_call.call_id),
                        name=str(patch_call.name),
                        input_text=patch_call.input_text,
                        source="native",
                    )
                ],
                finish_reason="tool_calls",
                response_id=f"{task.task_id}_{mode}_{repeat_index}_resp_1",
            ),
            GenerateResponse.from_native_tool_calling(
                assistant_text="Done.",
                finish_reason="stop",
                response_id=f"{task.task_id}_{mode}_{repeat_index}_resp_2",
            ),
        ],
        provenance={"provider_kind": "fake", "family": "codex"},
    )


def _native_codex_acceptance_client(task_id: str) -> FakeLLMClient:
    if task_id == "native_codex_exec_command_smoke":
        responses = [
            GenerateResponse.from_native_tool_calling(
                assistant_text="Running exec_command.",
                tool_calls=[
                    ToolCallCandidate(
                        call_id="c1",
                        name="exec_command",
                        arguments_raw=json.dumps(
                            {"cmd": "pwd"},
                            ensure_ascii=False,
                        ),
                        arguments_obj={"cmd": "pwd"},
                        source="native",
                    )
                ],
                finish_reason="tool_calls",
                response_id="native_codex_exec_command_smoke_1",
            ),
            GenerateResponse.from_native_tool_calling(
                assistant_text="Done.",
                finish_reason="stop",
                response_id="native_codex_exec_command_smoke_2",
            ),
        ]
    elif task_id == "native_codex_write_stdin_smoke":
        responses = [
            GenerateResponse.from_native_tool_calling(
                assistant_text="Starting the interactive command.",
                tool_calls=[
                    ToolCallCandidate(
                        call_id="c1",
                        name="exec_command",
                        arguments_raw=json.dumps(
                            {
                                "cmd": "IFS= read -r line; printf '%s' \"$line\"",
                                "tty": True,
                                "yield_time_ms": 50,
                            },
                            ensure_ascii=False,
                        ),
                        arguments_obj={
                            "cmd": "IFS= read -r line; printf '%s' \"$line\"",
                            "tty": True,
                            "yield_time_ms": 50,
                        },
                        source="native",
                    )
                ],
                finish_reason="tool_calls",
                response_id="native_codex_write_stdin_smoke_1",
            ),
            GenerateResponse.from_native_tool_calling(
                assistant_text="Continuing via write_stdin.",
                tool_calls=[
                    ToolCallCandidate(
                        call_id="c2",
                        name="write_stdin",
                        arguments_raw=json.dumps(
                            {
                                "session_id": 1,
                                "chars": "hello\n",
                                "yield_time_ms": 500,
                            },
                            ensure_ascii=False,
                        ),
                        arguments_obj={
                            "session_id": 1,
                            "chars": "hello\n",
                            "yield_time_ms": 500,
                        },
                        source="native",
                    )
                ],
                finish_reason="tool_calls",
                response_id="native_codex_write_stdin_smoke_2",
            ),
            GenerateResponse.from_native_tool_calling(
                assistant_text="Done.",
                finish_reason="stop",
                response_id="native_codex_write_stdin_smoke_3",
            ),
        ]
    elif task_id == "native_codex_repo_patch":
        responses = [
            GenerateResponse.from_native_tool_calling(
                assistant_text="Applying the patch.",
                tool_calls=[
                    ToolCallCandidate(
                        call_id="c1",
                        name="apply_patch",
                        input_text=(
                            "*** Begin Patch\n"
                            "*** Update File: calculator.py\n"
                            "@@\n"
                            "-def add(a, b):\n"
                            "-    return a - b\n"
                            "+def add(a, b):\n"
                            "+    return a + b\n"
                            "*** End Patch\n"
                        ),
                        source="native",
                    )
                ],
                finish_reason="tool_calls",
                response_id="native_codex_repo_patch_1",
            ),
            GenerateResponse.from_native_tool_calling(
                assistant_text="Done.",
                finish_reason="stop",
                response_id="native_codex_repo_patch_2",
            ),
        ]
    else:
        raise ValueError(f"Unknown native Codex acceptance task: {task_id!r}")

    return FakeLLMClient(
        responses=responses,
        provenance={"provider_kind": "fake", "family": "codex"},
    )


def _to_generation_smoke_result(
    family: str,
    result: Any,
) -> GenerationSmokeResult:
    manifest = json.loads(Path(result.raw_dataset_manifest_path).read_text(encoding="utf-8"))
    return GenerationSmokeResult(
        family=family,
        passed=bool(result.contract_ok),
        output_root=str(Path(result.raw_dataset_manifest_path).parents[1]),
        raw_dataset_manifest_path=str(result.raw_dataset_manifest_path),
        acceptance_report_path=str(result.acceptance_report_path),
        contract_ok=bool(result.contract_ok),
        observed_sample_count=int(result.observed_sample_count),
        sample_count_by_family=dict(manifest.get("sample_count_by_family", {})),
        sample_count_by_contract_kind=dict(manifest.get("sample_count_by_contract_kind", {})),
    )


def _report_is_stabilized(
    report: NativeFamilyAcceptanceReport,
    *,
    include_real_provider: bool,
) -> bool:
    if not all(check.passed for check in report.entrypoint_checks):
        return False
    if not all(command.passed for command in report.regression_commands):
        return False
    if include_real_provider and not report.real_provider_tasks:
        return False
    if include_real_provider and not all(task.passed for task in report.real_provider_tasks):
        return False
    if not report.native_codex_tasks or not all(task.passed for task in report.native_codex_tasks):
        return False
    if report.native_codex_direct_flow is None or not report.native_codex_direct_flow.passed:
        return False
    if not report.generation_smokes or not all(smoke.passed for smoke in report.generation_smokes):
        return False
    return True


def _copy_repo(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _repo_tree_changed(source: Path, workspace: Path) -> bool:
    source_files = sorted(path for path in source.rglob("*") if path.is_file())
    workspace_files = sorted(path for path in workspace.rglob("*") if path.is_file())
    if [path.relative_to(source) for path in source_files] != [
        path.relative_to(workspace) for path in workspace_files
    ]:
        return True
    for source_file in source_files:
        rel = source_file.relative_to(source)
        workspace_file = workspace / rel
        if source_file.read_bytes() != workspace_file.read_bytes():
            return True
    return False


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class _TaskSpec(BaseModel):
    task_id: str
    source_repo: Path
    prompt: str
    test_command: list[str]
    max_turns: int
    required_tools_all: list[str] = Field(default_factory=list)
    required_tools_any: list[str] = Field(default_factory=list)
    forbid_workspace_changes: bool = False
