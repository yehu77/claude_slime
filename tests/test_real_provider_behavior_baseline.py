from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import BaseLLMClient, FakeLLMClient, GenerateRequest, GenerateResponse
from pycodeagent.env.task import CodingTask
from pycodeagent.eval.real_provider_behavior_baseline import (
    load_realistic_runtime_tasks,
    run_behavior_baseline,
)
from pycodeagent.testing import cleanup_test_path, make_request_test_dir


def _get_test_root(request: pytest.FixtureRequest) -> Path:
    return make_request_test_dir("real_provider_behavior_baseline", request)


@pytest.fixture
def test_root(request: pytest.FixtureRequest):
    root = _get_test_root(request)
    yield root
    cleanup_test_path(root)


def _make_repo(root: Path, name: str, files: dict[str, str]) -> Path:
    repo = root / name
    repo.mkdir(parents=True, exist_ok=True)
    for rel_path, content in files.items():
        target = repo / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return repo


def test_default_realistic_task_loader_preserves_v1_contracts() -> None:
    tasks = load_realistic_runtime_tasks()

    assert [task.task_id for task in tasks] == [
        "realistic_revise_add_one_001",
        "realistic_patch_calculator_001",
        "realistic_subdir_formatter_001",
    ]
    assert all(task.repo_path.is_absolute() for task in tasks)
    assert all(task.metadata_contract() is not None for task in tasks)
    assert all(task.metadata_contract().schema_version == 1 for task in tasks)
    assert all(task.requires_runtime_validation_evidence() for task in tasks)


class _ErrorClient(BaseLLMClient):
    def generate(self, request: GenerateRequest) -> GenerateResponse:
        raise RuntimeError("provider disconnected")


class TestRealProviderBehaviorBaseline:
    @pytest.mark.slow
    @pytest.mark.integration
    def test_behavior_baseline_writes_summary_and_failure_buckets(self, test_root: Path) -> None:
        success_repo = _make_repo(
            test_root,
            "success_repo",
            {
                "calculator.py": "def add(a, b):\n    return a - b\n",
                "test_calculator.py": "from calculator import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
            },
        )
        stalled_repo = _make_repo(
            test_root,
            "stalled_repo",
            {
                "main.py": "def broken():\n    return 1\n",
                "test_fail.py": "def test_fail():\n    assert False\n",
            },
        )
        malformed_repo = _make_repo(
            test_root,
            "malformed_repo",
            {
                "main.py": "print('hello')\n",
                "test_ok.py": "def test_ok():\n    assert True\n",
            },
        )
        llm_error_repo = _make_repo(
            test_root,
            "llm_error_repo",
            {
                "main.py": "print('hello')\n",
                "test_ok.py": "def test_ok():\n    assert True\n",
            },
        )

        tasks = [
            CodingTask(
                task_id="success_revise",
                repo_path=success_repo,
                prompt="Run pytest, fix calculator.py, rerun pytest, then finish.",
                test_command="pytest -q -p no:cacheprovider",
                max_turns=6,
                allowed_files=["calculator.py"],
                metadata={"require_runtime_validation_evidence": True},
            ),
            CodingTask(
                task_id="stalled_after_failure",
                repo_path=stalled_repo,
                prompt="Run pytest and finish only after validation passes.",
                test_command="pytest -q -p no:cacheprovider",
                max_turns=3,
                metadata={"require_runtime_validation_evidence": True},
            ),
            CodingTask(
                task_id="schema_malformed",
                repo_path=malformed_repo,
                prompt="Read main.py and finish.",
                test_command="pytest -q -p no:cacheprovider",
                max_turns=3,
            ),
            CodingTask(
                task_id="llm_error",
                repo_path=llm_error_repo,
                prompt="Read main.py and finish.",
                test_command="pytest -q -p no:cacheprovider",
                max_turns=2,
            ),
        ]

        responses = {
            "success_revise": [
                """<|tool|>
{"id":"c1","name":"python_run","arguments":{"target":"pytest","run_as_module":true,"args":["-q","-p","no:cacheprovider","test_calculator.py"]}}
<|end|>""",
                """<|tool|>
{"id":"c2","name":"finish","arguments":{"answer":"done"}}
<|end|>""",
                """<|tool|>
{"id":"c3","name":"write_file","arguments":{"path":"calculator.py","content":"def add(a, b):\\n    return a + b\\n"}}
<|end|>""",
                """<|tool|>
{"id":"c4","name":"python_run","arguments":{"target":"pytest","run_as_module":true,"args":["-q","-p","no:cacheprovider","test_calculator.py"]}}
<|end|>""",
                """<|tool|>
{"id":"c5","name":"finish","arguments":{"answer":"fixed"}}
<|end|>""",
            ],
            "stalled_after_failure": [
                """<|tool|>
{"id":"c1","name":"python_run","arguments":{"target":"pytest","run_as_module":true,"args":["-q","-p","no:cacheprovider","test_fail.py"]}}
<|end|>""",
                """<|tool|>
{"id":"c2","name":"finish","arguments":{"answer":"done"}}
<|end|>""",
            ],
            "schema_malformed": [
                """<|tool|>
{"id":"c1","name":"read_file","arguments":
<|end|>"""
            ],
        }

        def client_factory(task: CodingTask, repeat_index: int):
            if task.task_id == "llm_error":
                return _ErrorClient()
            return FakeLLMClient(responses[task.task_id])

        result = run_behavior_baseline(
            tasks,
            client_factory,
            test_root / "baseline",
            repeat_count=1,
            profile_mode="base",
            tasks_path=test_root / "tasks.jsonl",
            provider={"provider_kind": "test", "client_mode": "fake"},
            tool_stack_kind="native_claude",
        )

        assert result.audit.run_count == 4
        assert result.audit.runs_with_validation_failure == 2
        assert result.audit.runs_with_revision_after_failure == 1
        assert result.audit.runs_with_premature_finish == 2
        assert result.audit.runs_with_finish_without_progress == 2
        assert result.audit.runs_with_finish_after_recent_failure == 2
        assert result.audit.runs_with_no_progress_after_validation_failure == 1
        assert result.audit.runs_with_schema_malformed == 1
        assert result.audit.runs_with_parse_error == 1
        assert result.audit.runs_with_llm_error == 1
        assert result.audit.runs_with_no_tool_progress == 2
        assert result.audit.runs_with_empty_turn_no_tool_no_content == 0
        assert result.audit.runs_with_unrecovered_validation_failure == 1
        assert result.audit.runs_with_tool_execution_failure_unrecovered == 0

        summary = json.loads(Path(result.behavior_baseline_summary_path).read_text(encoding="utf-8"))
        assert summary["task_count"] == 4
        assert summary["run_count"] == 4
        assert summary["provider"]["client_mode"] == "fake"
        assert summary["tool_stack_kind"] == "native_claude"
        assert summary["runs_with_finish_without_progress"] == 2
        assert summary["runs_with_finish_after_recent_failure"] == 2
        assert summary["per_task"]["success_revise"]["runs_with_revision_after_failure"] == 1
        assert summary["per_task"]["stalled_after_failure"]["runs_with_unrecovered_validation_failure"] == 1
        assert (
            summary["promotion_gates"]["revision_revalidation_finish_pattern_present"]["passed"]
            is True
        )
        assert (
            summary["promotion_gates"]["premature_finish_not_dominant_after_protocol_first"]["passed"]
            is True
        )
        assert (
            summary["promotion_gates"]["parse_malformed_not_dominant_failure_mode"]["passed"]
            is True
        )

        buckets = json.loads(Path(result.failure_buckets_path).read_text(encoding="utf-8"))
        assert buckets["buckets"]["premature_finish"]["run_count"] == 2
        assert buckets["buckets"]["finish_without_progress"]["run_count"] == 2
        assert buckets["buckets"]["finish_after_recent_failure"]["run_count"] == 2
        assert buckets["buckets"]["schema_malformed"]["run_count"] == 1
        assert buckets["buckets"]["llm_error"]["run_count"] == 1
        assert buckets["buckets"]["no_progress_after_validation_failure"]["run_count"] == 1
