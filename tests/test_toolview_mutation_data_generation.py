from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient, GenerateResponse, ToolCallCandidate
from pycodeagent.env.task import CodingTask
from pycodeagent.eval.toolview_mutation_data_generation import (
    DEFAULT_MUTATION_DATA_PROFILE_MODES,
    DEFAULT_MUTATION_DATA_PROFILE_SEED_BY_MODE,
    run_toolview_mutation_data_generation,
)
from pycodeagent.mutations.profile_sampler import ToolProfileSampler
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig
from pycodeagent.testing import cleanup_test_path, make_request_test_dir


def _get_test_root(request: pytest.FixtureRequest) -> Path:
    return make_request_test_dir("toolview_mutation_data_generation", request)


def _bundle_output_root(test_root: Path) -> Path:
    project_root = Path(__file__).resolve().parents[1]
    return project_root / "tmpmutationdata" / test_root.name[:24]


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
    repo = _make_repo(
        test_root,
        "repo",
        {
            "main.py": "print('hello')\n",
            "test_ok.py": "def test_ok():\n    assert True\n",
        },
    )
    tasks = [
        CodingTask(
            task_id="task_a",
            repo_path=repo,
            prompt="Read main.py and finish.",
            test_command=["python", "-c", "print('ok')"],
            max_turns=4,
        )
    ]
    tasks_path = test_root / "tasks.jsonl"
    tasks_path.write_text(
        "".join(task.model_dump_json() + "\n" for task in tasks),
        encoding="utf-8",
    )
    return tasks, tasks_path


def _client_factory(task: CodingTask, mode: str, repeat_index: int) -> FakeLLMClient:
    profile = ToolProfileSampler(seed=DEFAULT_MUTATION_DATA_PROFILE_SEED_BY_MODE[mode]).sample(mode)
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


def _read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class TestToolViewMutationDataGeneration:
    def test_happy_path_writes_raw_dataset_and_training_prep(self, test_root: Path) -> None:
        tasks, tasks_path = _make_tasks(test_root)
        output_root = _bundle_output_root(test_root)
        cleanup_test_path(output_root)

        result = run_toolview_mutation_data_generation(
            tasks,
            _client_factory,
            output_root,
            tasks_path=tasks_path,
            provider=_provider_provenance(),
            fake_tokenizer_config=FakeTokenizerConfig(),
        )

        assert result.profile_modes == list(DEFAULT_MUTATION_DATA_PROFILE_MODES)
        assert result.profile_seed_by_mode == DEFAULT_MUTATION_DATA_PROFILE_SEED_BY_MODE
        assert result.repeat_count == 1
        assert result.discovered_run_count == 4
        assert result.included_run_count == 4
        assert result.skipped_run_count == 0
        assert result.observed_sample_count == 8
        assert result.training_prep_enabled is True
        assert result.training_prep_contract_ok is True
        assert result.contract_ok is True

        assert Path(result.raw_dataset_manifest_path).exists()
        assert Path(result.raw_source_manifest_path).exists()
        assert Path(result.training_prep_path).exists()
        assert Path(result.acceptance_report_path).exists()
        assert Path(result.generation_summary_path).exists()
        assert Path(result.generation_manifest_path).exists()

        summary = _read_json(result.generation_summary_path)
        assert summary["profile_modes"] == list(DEFAULT_MUTATION_DATA_PROFILE_MODES)
        assert summary["observed_sample_count"] == 8
        assert summary["completed_run_count_by_mode"] == {
            "argument_rename": 1,
            "base": 1,
            "schema_flat_to_nested": 1,
            "tool_reorder": 1,
        }
        assert summary["sample_count_by_mode"] == {
            "argument_rename": 2,
            "base": 2,
            "schema_flat_to_nested": 2,
            "tool_reorder": 2,
        }
        assert summary["training_prep_enabled"] is True
        assert summary["training_prep_contract_ok"] is True
        assert summary["contract_ok"] is True

        acceptance = _read_json(result.acceptance_report_path)
        assert acceptance["configured_modes"] == list(DEFAULT_MUTATION_DATA_PROFILE_MODES)
        assert acceptance["contract_ok"] is True
        assert all(payload["passed"] is True for payload in acceptance["gates"].values())

    def test_can_generate_raw_dataset_without_training_prep(self, test_root: Path) -> None:
        tasks, tasks_path = _make_tasks(test_root)
        output_root = _bundle_output_root(test_root) / "raw_only"
        cleanup_test_path(output_root)

        result = run_toolview_mutation_data_generation(
            tasks,
            _client_factory,
            output_root,
            tasks_path=tasks_path,
            provider=_provider_provenance(),
            prepare_training_input=False,
        )

        assert result.observed_sample_count == 8
        assert result.training_prep_enabled is False
        assert result.training_prep_contract_ok is None
        assert result.training_prep_path is None
        assert result.prepared_dataset_dir is None
        assert result.contract_ok is True

        summary = _read_json(result.generation_summary_path)
        assert summary["training_prep_enabled"] is False
        assert summary["training_prep_contract_ok"] is None
        acceptance = _read_json(result.acceptance_report_path)
        assert acceptance["gates"]["training_prep_ok"]["passed"] is True
