from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient, GenerateResponse, ToolCallCandidate
from pycodeagent.env.task import CodingTask
from pycodeagent.eval.real_provider_behavior_baseline import run_behavior_baseline
from pycodeagent.eval.real_provider_credibility_bundle import (
    DEFAULT_CREDIBILITY_PROFILE_MODES,
    DEFAULT_CREDIBILITY_PROFILE_SEED_BY_MODE,
    build_real_provider_credibility_bundle_from_runs,
    run_provider_credibility_bundle,
)
from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.rl.dataset_manifest import FilterConfig
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig
from pycodeagent.testing import cleanup_test_path, make_request_test_dir


def _get_test_root(request: pytest.FixtureRequest) -> Path:
    return make_request_test_dir("real_provider_credibility_bundle", request)


def _bundle_output_root(test_root: Path) -> Path:
    project_root = Path(__file__).resolve().parents[1]
    return project_root / "tmpcred" / test_root.name[:24]


@pytest.fixture
def test_root(request: pytest.FixtureRequest):
    root = _get_test_root(request)
    yield root
    cleanup_test_path(_bundle_output_root(root))
    cleanup_test_path(root)


def _make_repo(root: Path, name: str, files: dict[str, str]) -> Path:
    repo = root / name
    repo.mkdir(parents=True, exist_ok=True)
    for rel_path, content in files.items():
        target = repo / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return repo


def _provider_provenance() -> dict[str, object]:
    return {
        "provider_kind": "test_openai_compatible",
        "client_mode": "mimo_native_tools",
        "model": "fake-model",
        "base_url": "https://example.invalid/v1",
        "api_key_env": "PYCODEAGENT_API_KEY",
        "timeout_seconds": 30.0,
        "max_retries": 2,
        "temperature": None,
        "max_output_tokens": None,
    }


def _make_tasks(test_root: Path) -> tuple[list[CodingTask], Path]:
    repo_a = _make_repo(
        test_root,
        "a",
        {
            "main.py": "print('hello from a')\n",
            "test_ok.py": "def test_ok():\n    assert True\n",
        },
    )
    repo_b = _make_repo(
        test_root,
        "b",
        {
            "main.py": "print('hello from b')\n",
            "test_ok.py": "def test_ok():\n    assert True\n",
        },
    )
    tasks = [
        CodingTask(
            task_id="ta",
            repo_path=repo_a,
            prompt="Read main.py and finish.",
            test_command=[sys.executable, "-c", "print('ok')"],
            max_turns=4,
        ),
        CodingTask(
            task_id="tb",
            repo_path=repo_b,
            prompt="Read main.py and finish.",
            test_command=[sys.executable, "-c", "print('ok')"],
            max_turns=4,
        ),
    ]
    tasks_path = test_root / "tasks.jsonl"
    tasks_path.write_text(
        "".join(task.model_dump_json() + "\n" for task in tasks),
        encoding="utf-8",
    )
    return tasks, tasks_path


def _client_factory(task: CodingTask, mode: str, repeat_index: int) -> FakeLLMClient:
    profile = ToolProfileSampler(seed=DEFAULT_CREDIBILITY_PROFILE_SEED_BY_MODE[mode]).sample(mode)
    read_call = profile.project_canonical_call("read_file", {"path": "main.py"}, call_id="c1")
    finish_call = profile.project_canonical_call(
        "finish",
        {"answer": f"{task.task_id}:{mode}:{repeat_index}"},
        call_id="c2",
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
                response_id=f"{task.task_id}_{mode}_{repeat_index}_resp_2",
            ),
        ],
        provenance=_provider_provenance(),
    )


def _run_happy_bundle(test_root: Path):
    tasks, tasks_path = _make_tasks(test_root)
    output_root = _bundle_output_root(test_root)
    cleanup_test_path(output_root)
    result = run_provider_credibility_bundle(
        tasks,
        _client_factory,
        output_root,
        tasks_path=tasks_path,
        provider=_provider_provenance(),
        fake_tokenizer_config=FakeTokenizerConfig(),
    )
    return result, tasks_path


def _pick_included_base_trace(source_runs_root: str | Path) -> Path:
    candidates = sorted(Path(source_runs_root).rglob("runtime_trace.jsonl"))
    for candidate in candidates:
        if "__base__" in str(candidate.parent):
            return candidate
    raise FileNotFoundError("No included base runtime trace found for credibility bundle test")


def _read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


class TestRealProviderCredibilityBundle:
    def test_happy_path_writes_credibility_bundle(self, test_root: Path) -> None:
        result, _tasks_path = _run_happy_bundle(test_root)

        assert result.profile_modes == list(DEFAULT_CREDIBILITY_PROFILE_MODES)
        assert result.profile_seed_by_mode == DEFAULT_CREDIBILITY_PROFILE_SEED_BY_MODE
        assert result.repeat_count == 3
        assert result.total_source_run_count == 24
        assert result.completed_source_run_count == 24
        assert result.included_observed_run_count == 24
        assert result.observed_sample_count == 48
        assert result.trace_backed_sample_count == 48
        assert result.trace_backed_sample_rate == 1.0
        assert result.critical_reconciliation_error_count == 0
        assert result.contract_ok is True

        assert Path(result.runtime_behavior_audit_path).exists()
        assert Path(result.behavior_baseline_summary_path).exists()
        assert Path(result.failure_buckets_path).exists()
        assert Path(result.runtime_observed_bundle_path).exists()
        assert Path(result.runtime_execution_reconciliation_path).exists()
        assert Path(result.credibility_summary_path).exists()
        assert Path(result.credibility_manifest_path).exists()
        assert Path(result.credibility_gates_path).exists()

        summary = _read_json(result.credibility_summary_path)
        assert summary["profile_modes"] == list(DEFAULT_CREDIBILITY_PROFILE_MODES)
        assert summary["sample_count_by_mode"] == {
            "base": 12,
            "argument_rename": 12,
            "schema_flat_to_nested": 12,
            "tool_reorder": 12,
        }
        assert summary["sample_count_by_execution_kind"] == {
            "file_read": 24,
            "finish_signal": 24,
        }
        assert summary["sample_count_by_policy_decision"] == {"allow": 48}

        gates = _read_json(result.credibility_gates_path)
        assert gates["contract_ok"] is True
        assert all(payload["passed"] is True for payload in gates["gates"].values())

    def test_missing_runtime_trace_fails_trace_coverage_gate_only(self, test_root: Path) -> None:
        result, tasks_path = _run_happy_bundle(test_root)
        trace_path = _pick_included_base_trace(result.source_runs_root)
        trace_path.unlink()

        rebuilt = build_real_provider_credibility_bundle_from_runs(
            result.source_runs_root,
            test_root / "rebuilt_missing_trace",
            tasks_path=tasks_path,
            provider=_provider_provenance(),
            fake_tokenizer_config=FakeTokenizerConfig(),
        )

        gates = _read_json(rebuilt.credibility_gates_path)
        assert gates["contract_ok"] is False
        assert gates["gates"]["runtime_trace_coverage_ok"]["passed"] is False
        assert gates["gates"]["reconciliation_critical_ok"]["passed"] is True
        assert gates["gates"]["training_prep_contract_ok"]["passed"] is True

    def test_reconciliation_critical_failure_propagates_to_bundle(self, test_root: Path) -> None:
        result, tasks_path = _run_happy_bundle(test_root)
        trace_path = _pick_included_base_trace(result.source_runs_root)
        rows = _read_jsonl(trace_path)
        filtered = [
            row
            for row in rows
            if not (
                row.get("event_kind") == "tool_execution_completed"
                and row.get("tool_call_id") == "c1"
            )
        ]
        _write_jsonl(trace_path, filtered)

        rebuilt = build_real_provider_credibility_bundle_from_runs(
            result.source_runs_root,
            test_root / "rebuilt_reconciliation_failure",
            tasks_path=tasks_path,
            provider=_provider_provenance(),
            fake_tokenizer_config=FakeTokenizerConfig(),
        )

        gates = _read_json(rebuilt.credibility_gates_path)
        assert gates["contract_ok"] is False
        assert gates["gates"]["reconciliation_critical_ok"]["passed"] is False
        assert gates["gates"]["training_prep_contract_ok"]["passed"] is False

    def test_no_mutated_mode_samples_gate_can_fail_without_losing_mode_coverage(
        self,
        test_root: Path,
    ) -> None:
        result, tasks_path = _run_happy_bundle(test_root)
        base_profile_id = ToolProfileSampler(seed=0).sample("base").profile_id

        rebuilt = build_real_provider_credibility_bundle_from_runs(
            result.source_runs_root,
            test_root / "rebuilt_base_only_observed",
            tasks_path=tasks_path,
            provider=_provider_provenance(),
            observed_filter_config=FilterConfig(profile_ids=[base_profile_id]),
            fake_tokenizer_config=FakeTokenizerConfig(),
        )

        gates = _read_json(rebuilt.credibility_gates_path)
        assert gates["contract_ok"] is False
        assert gates["gates"]["mode_coverage_ok"]["passed"] is True
        assert gates["gates"]["mutated_mode_samples_present"]["passed"] is False
        assert gates["gates"]["training_prep_contract_ok"]["passed"] is True

    def test_nested_runtime_observed_contract_gate_can_fail_independently(
        self,
        test_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        result, tasks_path = _run_happy_bundle(test_root)

        from pycodeagent.eval import real_provider_credibility_bundle as module
        from pycodeagent.eval.runtime_observed_postrun import RuntimeObservedStudyBundleResult

        nested_payload = _read_json(result.runtime_observed_bundle_path)
        nested_result = RuntimeObservedStudyBundleResult.model_validate(nested_payload)

        def _fake_prepare(*args, **kwargs):
            return nested_result.model_copy(update={"contract_ok": False})

        monkeypatch.setattr(module, "prepare_study_runtime_observed_bundle", _fake_prepare)

        rebuilt = build_real_provider_credibility_bundle_from_runs(
            result.source_runs_root,
            test_root / "rebuilt_nested_contract_false",
            tasks_path=tasks_path,
            provider=_provider_provenance(),
            fake_tokenizer_config=FakeTokenizerConfig(),
        )

        gates = _read_json(rebuilt.credibility_gates_path)
        assert gates["contract_ok"] is False
        assert gates["gates"]["reconciliation_critical_ok"]["passed"] is True
        assert gates["gates"]["training_prep_contract_ok"]["passed"] is False

    def test_baseline_and_bundle_entrypaths_remain_separate(self, test_root: Path) -> None:
        tasks, tasks_path = _make_tasks(test_root)
        baseline = run_behavior_baseline(
            tasks,
            lambda task, repeat_index: _client_factory(task, "base", repeat_index),
            test_root / "baseline_only",
            repeat_count=1,
            profile_mode="base",
            tasks_path=tasks_path,
            provider=_provider_provenance(),
        )
        bundle = run_provider_credibility_bundle(
            tasks,
            _client_factory,
            test_root / "bundle_entrypath",
            tasks_path=tasks_path,
            provider=_provider_provenance(),
            fake_tokenizer_config=FakeTokenizerConfig(),
        )

        assert Path(baseline.runtime_behavior_audit_path).exists()
        assert Path(baseline.behavior_baseline_summary_path).exists()
        assert Path(baseline.failure_buckets_path).exists()
        assert not (Path(baseline.output_root) / "runtime_observed_bundle").exists()

        assert Path(bundle.runtime_behavior_audit_path).exists()
        assert Path(bundle.behavior_baseline_summary_path).exists()
        assert Path(bundle.failure_buckets_path).exists()
        assert Path(bundle.runtime_observed_bundle_path).exists()
