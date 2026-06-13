"""Deterministic local-runtime helpers for observed ToolView tests."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from pycodeagent.agent.llm_client import FakeLLMClient, GenerateResponse, ToolCallCandidate
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.eval.layout import experiment_dir_name, mode_dir_name
from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.tools.bootstrap import build_base_tool_profile, build_builtin_registry
from pycodeagent.tools.spec import ToolProfile
from pycodeagent.trajectory.schema import Trajectory


FIXED_WORKSPACE_ID = "abc123def456"


class _FixedUuid:
    hex = "abc123def4567890abc123def4567890"


@dataclass(frozen=True)
class RuntimeObservedBatchSource:
    """Deterministic batch-style source artifacts for observed dataset tests."""

    batch_root: Path
    batch_run_dir: Path
    output_dir: Path
    workspace_dir: Path
    profile: ToolProfile
    trajectory: Trajectory
    read_call: object
    finish_call: object


@dataclass(frozen=True)
class RuntimeObservedStudySource:
    """Deterministic study-style source artifacts for observed bundle tests."""

    study_root: Path
    run_dirs: list[Path]
    batch_sources: list[RuntimeObservedBatchSource]


def make_runtime_observed_batch_source(
    tmp: Path,
    *,
    task_id: str = "observed_task",
    task_prompt: str = "Inspect main.py and finish.",
    finish_answer: str = "Done",
    profile_mode: str | None = None,
    profile_seed: int = 0,
) -> RuntimeObservedBatchSource:
    """Create a deterministic local runtime run copied into batch layout."""
    repo = tmp / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (repo / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n",
        encoding="utf-8",
    )

    registry = build_builtin_registry()
    profile = (
        ToolProfileSampler(seed=profile_seed).sample(profile_mode)
        if profile_mode is not None
        else build_base_tool_profile()
    )
    read_call = profile.project_canonical_call(
        "read_file",
        {"path": "main.py"},
        call_id="c1",
        canonical_tool=registry.get("read_file"),
    )
    finish_call = profile.project_canonical_call(
        "finish",
        {"answer": finish_answer},
        call_id="c2",
        canonical_tool=registry.get("finish"),
    )

    responses = [
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
            response_id="resp_native_1",
        ),
        GenerateResponse.from_native_tool_calling(
            assistant_text="Done.",
            tool_calls=[
                ToolCallCandidate(
                    call_id=str(finish_call.call_id),
                    name=str(finish_call.name),
                    arguments_raw=json.dumps(finish_call.arguments, ensure_ascii=False),
                    arguments_obj=dict(finish_call.arguments),
                    source="native",
                )
            ],
            finish_reason="tool_calls",
            response_id="resp_native_2",
        ),
    ]

    output_dir = tmp / "output"
    task = CodingTask(
        task_id=task_id,
        repo_path=repo,
        prompt=task_prompt,
        test_command="pytest -q -p no:cacheprovider",
        max_turns=5,
    )
    client = FakeLLMClient(responses=responses)

    time_values = iter(range(1700000000000, 1700000000500))
    with patch(
        "pycodeagent.runtime_trace.writer._unix_time_ms",
        side_effect=lambda: next(time_values),
    ), patch(
        "pycodeagent.env.coding_env.uuid.uuid4",
        return_value=_FixedUuid(),
    ):
        trajectory = run_coding_task(
            task,
            client,
            output_dir,
            profile_mode=profile_mode,
            profile_seed=profile_seed,
        )

    workspace_dir = output_dir / "w" / FIXED_WORKSPACE_ID
    batch_root = tmp / "batch"
    batch_run_dir = batch_root / f"{task_id}__{profile.profile_id}"
    if batch_run_dir.exists():
        shutil.rmtree(batch_run_dir)
    batch_run_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(output_dir, batch_run_dir)

    return RuntimeObservedBatchSource(
        batch_root=batch_root,
        batch_run_dir=batch_run_dir,
        output_dir=output_dir,
        workspace_dir=workspace_dir,
        profile=profile,
        trajectory=trajectory,
        read_call=read_call,
        finish_call=finish_call,
    )


def make_runtime_observed_study_source(
    tmp: Path,
    *,
    study_id: str = "observed_study",
    entries: list[dict[str, object]] | None = None,
) -> RuntimeObservedStudySource:
    """Create a deterministic study-style source tree with multiple runs."""
    if entries is None:
        entries = [
            {"task_id": "task_base_seed0", "profile_mode": "base", "profile_seed": 0},
            {
                "task_id": "task_nds_seed0",
                "profile_mode": "name_description_schema",
                "profile_seed": 0,
            },
            {
                "task_id": "task_arg_seed1",
                "profile_mode": "argument_rename",
                "profile_seed": 1,
            },
            {
                "task_id": "task_order_seed1",
                "profile_mode": "tool_reorder",
                "profile_seed": 1,
            },
        ]

    study_root = tmp / "study"
    experiments_root = study_root / "experiments"
    run_dirs: list[Path] = []
    batch_sources: list[RuntimeObservedBatchSource] = []

    for index, entry in enumerate(entries):
        task_id = str(entry["task_id"])
        profile_mode = str(entry["profile_mode"])
        profile_seed = int(entry.get("profile_seed", 0))
        finish_answer = str(entry.get("finish_answer", "Done"))
        task_prompt = str(entry.get("task_prompt", "Inspect main.py and finish."))
        batch_source = make_runtime_observed_batch_source(
            tmp / "study_batch_sources" / f"{index:02d}_{task_id}",
            task_id=task_id,
            task_prompt=task_prompt,
            finish_answer=finish_answer,
            profile_mode=(None if profile_mode == "base" else profile_mode),
            profile_seed=profile_seed,
        )
        batch_sources.append(batch_source)
        profile = batch_source.profile

        experiment_id = f"{study_id}__{profile_mode}"
        experiment_dir = experiments_root / experiment_dir_name(experiment_id, profile_mode)
        run_dir = (
            experiment_dir
            / "runs"
            / f"seed_{profile_seed}"
            / mode_dir_name(profile_mode)
            / f"{task_id}__{profile.profile_id}"
        )
        if run_dir.exists():
            shutil.rmtree(run_dir)
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(batch_source.output_dir, run_dir)

        if batch_source.trajectory.status.value != "completed":
            raise AssertionError(
                f"Deterministic runtime_observed study source run did not complete: {task_id}"
            )
        if not (run_dir / "runtime_trace.jsonl").exists():
            raise AssertionError(
                f"Deterministic runtime_observed study source is missing runtime trace: {task_id}"
            )
        run_dirs.append(run_dir)

    return RuntimeObservedStudySource(
        study_root=study_root,
        run_dirs=run_dirs,
        batch_sources=batch_sources,
    )
