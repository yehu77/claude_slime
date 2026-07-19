"""Mainline contract tests for deterministic RunCampaign orchestration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from pycodeagent.agent.llm_client import FakeLLMClient, GenerateResponse
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask
from pycodeagent.eval.run_campaign import (
    CAMPAIGN_ARTIFACT_INDEX_NAME,
    CAMPAIGN_FAILURE_SUMMARY_NAME,
    CAMPAIGN_MANIFEST_NAME,
    PROFILE_CAMPAIGN_GROUP_MANIFEST_NAME,
    CampaignProvider,
    RunCampaign,
    RunCampaignError,
    RunMatrix,
    campaign_spec_fingerprint,
    execute_run_campaign,
    execute_profile_run_campaigns,
    expand_run_campaign,
)
from pycodeagent.rl.dataset_builder import discover_run_dirs


pytestmark = pytest.mark.mainline


def _task(tmp_path: Path, task_id: str = "campaign_task") -> CodingTask:
    repo = tmp_path / f"{task_id}_repo"
    repo.mkdir()
    (repo / "value.py").write_text("VALUE = 42\n", encoding="utf-8")
    return CodingTask(
        task_id=task_id,
        repo_path=repo,
        prompt="Report that the workspace is valid.",
        test_command=[
            sys.executable,
            "-c",
            "from pathlib import Path; assert Path('value.py').is_file()",
        ],
        max_turns=2,
    )


def _client(case) -> FakeLLMClient:
    return FakeLLMClient(
        [
            GenerateResponse.from_native_tool_calling(
                assistant_text="The workspace is valid.",
                finish_reason="stop",
                response_id=f"response_{case.run_id}",
            )
        ],
        provenance={
            "provider_kind": "fake",
            "provider_id": case.provider.provider_id,
        },
    )


def _campaign(
    *,
    task_ids: list[str] | tuple[str, ...] = ("campaign_task",),
    families: list[str] | tuple[str, ...] = ("native_claude",),
    profile_modes: list[str] | tuple[str, ...] = ("base",),
    profile_seeds: list[int] | tuple[int, ...] = (0,),
    providers: list[dict] | tuple[dict, ...] = (
        {"provider_id": "fake-a", "metadata": {"client_mode": "fake"}},
    ),
    repeat_count: int = 1,
) -> RunCampaign:
    return RunCampaign(
        campaign_id="campaign_contract_test",
        matrix=RunMatrix(
            task_ids=task_ids,
            families=families,
            profile_modes=profile_modes,
            profile_seeds=profile_seeds,
            providers=providers,
            repeat_count=repeat_count,
        ),
        retention_owner="campaign-test-owner",
    )


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_equivalent_matrix_inputs_expand_to_identical_order_and_run_ids() -> None:
    first = _campaign(
        task_ids=["task-b", "task-a"],
        families=["native_codex", "native_claude"],
        profile_modes=["tool_reorder", "base"],
        profile_seeds=[7, 0],
        providers=[
            {"provider_id": "provider-z"},
            {"provider_id": "provider-a"},
        ],
        repeat_count=2,
    )
    second = _campaign(
        task_ids=["task-a", "task-b"],
        families=["native_claude", "native_codex"],
        profile_modes=["base", "tool_reorder"],
        profile_seeds=[0, 7],
        providers=[
            {"provider_id": "provider-a"},
            {"provider_id": "provider-z"},
        ],
        repeat_count=2,
    )

    first_plan = expand_run_campaign(first)
    second_plan = expand_run_campaign(second)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert campaign_spec_fingerprint(first) == campaign_spec_fingerprint(second)
    assert [case.model_dump(mode="json") for case in first_plan] == [
        case.model_dump(mode="json") for case in second_plan
    ]
    assert len(first_plan) == first.matrix.run_count == 64
    assert len({case.run_id for case in first_plan}) == 64
    assert [case.ordinal for case in first_plan] == list(range(64))


def test_matrix_rejects_duplicate_dimensions_and_secret_provider_metadata() -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        RunMatrix(
            task_ids=["task", "task"],
            families=["native_claude"],
            profile_modes=["base"],
            providers=[{"provider_id": "fake"}],
        )
    with pytest.raises(ValidationError, match="non-secret"):
        CampaignProvider(
            provider_id="unsafe",
            metadata={"transport": {"authorization": "Bearer secret"}},
        )
    with pytest.raises(ValidationError, match="finite JSON-compatible"):
        CampaignProvider(
            provider_id="non-finite",
            metadata={"temperature": float("nan")},
        )


def test_fake_client_matrix_preserves_identity_artifacts_and_is_idempotent(
    tmp_path: Path,
) -> None:
    task = _task(tmp_path)
    campaign = _campaign(
        families=["native_codex", "native_claude"],
        providers=[
            {"provider_id": "fake-b", "metadata": {"region": "test-b"}},
            {"provider_id": "fake-a", "metadata": {"region": "test-a"}},
        ],
    )
    output_root = tmp_path / "campaign"
    calls: list[str] = []

    def client_factory(case):
        calls.append(case.run_id)
        return _client(case)

    result = execute_run_campaign(
        campaign,
        [task],
        client_factory,
        output_root,
    )

    assert result.contract_ok is True
    assert result.planned_run_count == 4
    assert result.terminal_run_count == 4
    assert result.executed_run_count == 4
    assert result.recovered_run_count == 0
    assert result.skipped_run_count == 0
    assert len(calls) == 4

    index = _load(output_root / CAMPAIGN_ARTIFACT_INDEX_NAME)
    assert len(index["entries"]) == 4
    for entry in index["entries"]:
        assert entry["disposition"] == "terminal"
        assert entry["attempt_count"] == 1
        record = entry["record"]
        assert record["outcome"] == "trajectory_recorded"
        assert record["trajectory_status"] == "completed"
        assert record["reward"] == 1.0
        assert record["verifier"]["passed"] is True
        case = record["case"]
        attempt_root = output_root / record["attempt_path"]
        trajectory = _load(output_root / record["artifact_paths"]["trajectory"])
        profile = _load(output_root / record["artifact_paths"]["tool_profile"])
        trace_manifest = _load(
            output_root / record["artifact_paths"]["runtime_trace_manifest"]
        )
        assert trajectory["task_id"] == case["task_id"]
        assert trajectory["tool_profile_id"] == record["tool_profile_id"]
        assert profile["profile_id"] == record["tool_profile_id"]
        assert profile["metadata"]["family"] == (
            "claude" if case["family"] == "native_claude" else "codex"
        )
        assert trace_manifest["run_id"] == attempt_root.name
        assert trace_manifest["run_id"].startswith(case["run_id"])
        assert trace_manifest["retention"]["owner"] == "campaign-test-owner"

    stable_paths = [
        output_root / CAMPAIGN_ARTIFACT_INDEX_NAME,
        output_root / CAMPAIGN_FAILURE_SUMMARY_NAME,
        output_root / CAMPAIGN_MANIFEST_NAME,
    ]
    before = {path.name: path.read_bytes() for path in stable_paths}

    def forbidden_factory(_case):
        raise AssertionError("completed logical runs must not be executed again")

    resumed = execute_run_campaign(
        campaign,
        [task],
        forbidden_factory,
        output_root,
    )

    assert resumed.executed_run_count == 0
    assert resumed.recovered_run_count == 0
    assert resumed.skipped_run_count == 4
    assert {path.name: path.read_bytes() for path in stable_paths} == before


def test_completed_attempt_is_recovered_after_interruption_without_reexecution(
    tmp_path: Path,
) -> None:
    task = _task(tmp_path)
    campaign = _campaign()
    output_root = tmp_path / "campaign"
    execution_count = 0

    def interrupt_after_artifacts(task, client, attempt_root, case, campaign):
        nonlocal execution_count
        execution_count += 1
        run_coding_task(
            task,
            client,
            attempt_root,
            profile_mode=case.profile_mode,
            profile_seed=case.profile_seed,
            tool_stack_kind=case.family,
            retention_class=campaign.retention_class,
            retention_owner=campaign.retention_owner,
        )
        raise KeyboardInterrupt("simulated crash after artifact finalization")

    with pytest.raises(KeyboardInterrupt, match="simulated crash"):
        execute_run_campaign(
            campaign,
            [task],
            _client,
            output_root,
            run_executor=interrupt_after_artifacts,
        )

    def forbidden_factory(_case):
        raise AssertionError("a complete attempt must be recovered")

    resumed = execute_run_campaign(
        campaign,
        [task],
        forbidden_factory,
        output_root,
    )

    assert execution_count == 1
    assert resumed.executed_run_count == 0
    assert resumed.recovered_run_count == 1
    assert resumed.skipped_run_count == 0
    index = _load(output_root / CAMPAIGN_ARTIFACT_INDEX_NAME)
    assert index["entries"][0]["attempt_count"] == 1
    assert index["entries"][0]["record"]["outcome"] == "trajectory_recorded"


def test_partial_attempt_is_preserved_and_resume_uses_a_new_attempt(
    tmp_path: Path,
) -> None:
    task = _task(tmp_path)
    campaign = _campaign()
    output_root = tmp_path / "campaign"

    def partial_interrupt(_task, _client, attempt_root, _case, _campaign):
        (attempt_root / "runtime_trace.jsonl").write_text(
            "partial-trace\n",
            encoding="utf-8",
        )
        raise KeyboardInterrupt("simulated partial attempt")

    with pytest.raises(KeyboardInterrupt, match="partial attempt"):
        execute_run_campaign(
            campaign,
            [task],
            _client,
            output_root,
            run_executor=partial_interrupt,
        )

    first_attempt = next((output_root / "runs").glob("*/attempts/*"))
    partial_trace = first_attempt / "runtime_trace.jsonl"
    before = partial_trace.read_bytes()

    resumed = execute_run_campaign(campaign, [task], _client, output_root)

    assert resumed.executed_run_count == 1
    assert resumed.recovered_run_count == 0
    assert partial_trace.read_bytes() == before
    attempts = sorted(first_attempt.parent.glob("*"))
    assert len(attempts) == 2
    assert attempts[0] != attempts[1]
    index = _load(output_root / CAMPAIGN_ARTIFACT_INDEX_NAME)
    assert index["entries"][0]["attempt_count"] == 2
    assert index["entries"][0]["record"]["attempt_number"] == 2


def test_executor_failure_is_terminal_summarized_and_does_not_stop_matrix(
    tmp_path: Path,
) -> None:
    task = _task(tmp_path)
    campaign = _campaign(
        providers=[
            {"provider_id": "a-broken"},
            {"provider_id": "b-working"},
        ]
    )
    output_root = tmp_path / "campaign"

    def client_factory(case):
        if case.provider.provider_id == "a-broken":
            raise RuntimeError("provider unavailable")
        return _client(case)

    result = execute_run_campaign(
        campaign,
        [task],
        client_factory,
        output_root,
    )

    assert result.planned_run_count == 2
    assert result.terminal_run_count == 2
    assert result.executor_error_count == 1
    assert result.contract_ok is False
    failure_summary = _load(output_root / CAMPAIGN_FAILURE_SUMMARY_NAME)
    assert failure_summary["failed_run_count"] == 1
    assert failure_summary["failure_kind_counts"] == {"executor_error": 1}
    manifest = _load(output_root / CAMPAIGN_MANIFEST_NAME)
    assert manifest["pending_run_count"] == 0
    assert manifest["outcome_counts"] == {
        "executor_error": 1,
        "trajectory_recorded": 1,
    }


def test_output_root_rejects_spec_drift_and_missing_tasks(tmp_path: Path) -> None:
    task = _task(tmp_path)
    campaign = _campaign()
    output_root = tmp_path / "campaign"
    execute_run_campaign(campaign, [task], _client, output_root)

    changed = _campaign(repeat_count=2)
    with pytest.raises(RunCampaignError, match="different spec or plan"):
        execute_run_campaign(changed, [task], _client, output_root)

    missing = _campaign(task_ids=["missing-task"])
    with pytest.raises(RunCampaignError, match="missing CodingTask"):
        execute_run_campaign(missing, [task], _client, tmp_path / "missing")


def test_resume_rejects_a_terminal_record_that_escapes_the_campaign_root(
    tmp_path: Path,
) -> None:
    task = _task(tmp_path)
    campaign = _campaign()
    output_root = tmp_path / "campaign"
    execute_run_campaign(campaign, [task], _client, output_root)

    record_path = next((output_root / "runs").glob("*/campaign_run_record.json"))
    record = _load(record_path)
    record["attempt_path"] = "../outside"
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RunCampaignError, match="escapes output root"):
        execute_run_campaign(campaign, [task], _client, output_root)


def test_profile_campaign_group_preserves_mode_seed_pairs_and_resumes(
    tmp_path: Path,
) -> None:
    task = _task(tmp_path)
    output_root = tmp_path / "profile_campaigns"
    calls: list[tuple[str, str, int]] = []

    def client_factory(task, mode, repeat_index):
        calls.append((task.task_id, mode, repeat_index))
        return FakeLLMClient(
            [
                GenerateResponse.from_native_tool_calling(
                    assistant_text="The workspace is valid.",
                    finish_reason="stop",
                    response_id=f"{task.task_id}_{mode}_{repeat_index}",
                )
            ],
            provenance={"provider_kind": "fake"},
        )

    result = execute_profile_run_campaigns(
        campaign_id="profile_pairing_test",
        tasks=[task],
        client_factory=client_factory,
        output_root=output_root,
        profile_seed_by_mode={"tool_reorder": 7, "base": 0},
        repeat_count=2,
        tool_stack_kind="native_claude",
        provider={"provider_kind": "fake"},
    )

    assert result.campaign_count == 2
    assert result.planned_run_count == 4
    assert result.terminal_run_count == 4
    assert result.contract_ok is True
    assert calls == [
        ("campaign_task", "base", 0),
        ("campaign_task", "base", 1),
        ("campaign_task", "tool_reorder", 0),
        ("campaign_task", "tool_reorder", 1),
    ]
    manifest_path = output_root / PROFILE_CAMPAIGN_GROUP_MANIFEST_NAME
    manifest = _load(manifest_path)
    assert [
        (entry["profile_mode"], entry["profile_seed"])
        for entry in manifest["campaigns"]
    ] == [("base", 0), ("tool_reorder", 7)]

    indexed_cases: list[dict] = []
    for campaign_entry in manifest["campaigns"]:
        artifact_index = _load(
            output_root / campaign_entry["artifact_index"]
        )
        for entry in artifact_index["entries"]:
            record = entry["record"]
            assert record["trajectory_status"] == "completed"
            assert record["reward"] == 1.0
            assert (
                output_root / campaign_entry["campaign_root"]
                / record["artifact_paths"]["trajectory"]
            ).is_file()
            indexed_cases.append(record["case"])
    assert {
        (case["profile_mode"], case["profile_seed"])
        for case in indexed_cases
    } == {("base", 0), ("tool_reorder", 7)}
    assert len(discover_run_dirs(output_root, source_type="batch")) == 4

    before = manifest_path.read_bytes()

    def forbidden_factory(_task, _mode, _repeat_index):
        raise AssertionError("terminal campaign cases must be skipped")

    resumed = execute_profile_run_campaigns(
        campaign_id="profile_pairing_test",
        tasks=[task],
        client_factory=forbidden_factory,
        output_root=output_root,
        profile_seed_by_mode={"base": 0, "tool_reorder": 7},
        repeat_count=2,
        tool_stack_kind="native_claude",
        provider={"provider_kind": "fake"},
    )

    assert resumed.executed_run_count == 0
    assert resumed.skipped_run_count == 4
    assert manifest_path.read_bytes() == before


def test_active_campaign_modules_have_no_private_task_repeat_orchestration() -> None:
    modules = {
        "real_provider_behavior_baseline.py": 0,
        "real_provider_credibility_bundle.py": 0,
        "toolview_mutation_data_generation.py": 1,
    }
    eval_root = Path(__file__).resolve().parents[1] / "pycodeagent/eval"
    for filename, expected_direct_runtime_calls in modules.items():
        source = (eval_root / filename).read_text(encoding="utf-8")
        assert "execute_profile_run_campaigns(" in source
        assert "_materialize_source_runs" not in source
        assert "_materialize_credibility_source_runs" not in source
        assert "shutil.rmtree" not in source
        assert source.count("run_coding_task(") == expected_direct_runtime_calls


def test_profile_campaign_group_rejects_a_mixed_legacy_run_root(
    tmp_path: Path,
) -> None:
    task = _task(tmp_path)
    legacy_run = tmp_path / "runs" / "legacy-direct-run"
    legacy_run.mkdir(parents=True)
    (legacy_run / "trajectory.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(RunCampaignError, match="legacy direct runs"):
        execute_profile_run_campaigns(
            campaign_id="mixed_layout_test",
            tasks=[task],
            client_factory=lambda *_args: _client,
            output_root=tmp_path / "runs",
            profile_seed_by_mode={"base": 0},
            repeat_count=1,
            tool_stack_kind="native_claude",
        )
