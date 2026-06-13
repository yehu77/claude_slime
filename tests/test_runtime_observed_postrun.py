"""Tests for study-scale runtime-observed post-run bundle generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import FakeLLMClient, GenerateResponse, ToolCallCandidate
from pycodeagent.eval.experiment_config import ExperimentConfig
from pycodeagent.eval.experiment_runner import ExperimentRunner
from pycodeagent.eval.runtime_observed_postrun import (
    prepare_study_runtime_observed_bundle,
)
from pycodeagent.eval.study_config import StudyConfig
from pycodeagent.eval.study_runner import MutationStudyRunner
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig
from pycodeagent.testing import (
    cleanup_test_path,
    make_runtime_observed_study_source,
    make_unique_test_dir,
)
from pycodeagent.trajectory.schema import Trajectory


pytestmark = [pytest.mark.slow, pytest.mark.integration]


_TEST_NAMESPACE = "runtime_observed_postrun"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _make_source_repo(test_root: Path, name: str, files: dict[str, str]) -> Path:
    repo = test_root / "source" / name
    repo.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return repo


def _make_tasks_jsonl(test_root: Path, tasks: list[dict]) -> Path:
    tasks_path = test_root / "tasks.jsonl"
    with open(tasks_path, "w", encoding="utf-8") as f:
        for task in tasks:
            f.write(json.dumps(task) + "\n")
    return tasks_path


def _make_read_then_finish_factory():
    def factory():
        return FakeLLMClient(
            responses=[
                GenerateResponse.from_native_tool_calling(
                    assistant_text="I will inspect main.py first.",
                    tool_calls=[
                        ToolCallCandidate(
                            call_id="c1",
                            name="read_file",
                            arguments_raw='{"path":"main.py"}',
                            arguments_obj={"path": "main.py"},
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
                            call_id="c2",
                            name="finish",
                            arguments_raw='{"answer":"Done"}',
                            arguments_obj={"answer": "Done"},
                            source="native",
                        )
                    ],
                    finish_reason="tool_calls",
                    response_id="resp_native_2",
                ),
            ]
        )

    return factory


class TestRuntimeObservedPostrunBundle:
    def test_runtime_observed_study_source_is_stable_multi_profile_input(self) -> None:
        tmp = _get_test_dir()
        try:
            source = make_runtime_observed_study_source(tmp)
            assert len(source.run_dirs) == 4
            assert len(source.batch_sources) == 4

            statuses: list[str] = []
            profile_ids: list[str] = []
            for run_dir in source.run_dirs:
                trajectory = Trajectory.model_validate(
                    json.loads((run_dir / "trajectory.json").read_text(encoding="utf-8"))
                )
                statuses.append(trajectory.status.value)
                profile_ids.append(trajectory.tool_profile_id)
                assert (run_dir / "runtime_trace.jsonl").exists()

            assert statuses == ["completed", "completed", "completed", "completed"]
            assert len(set(profile_ids)) == 4
        finally:
            _cleanup(tmp)

    def test_prepare_study_runtime_observed_bundle_writes_summary_and_manifest(self) -> None:
        tmp = _get_test_dir()
        try:
            source = make_runtime_observed_study_source(tmp)
            output_dir = tmp / "bundle"

            result = prepare_study_runtime_observed_bundle(
                source.study_root,
                output_dir,
                source_type="study",
                fake_tokenizer_config=FakeTokenizerConfig(),
                max_length=2048,
                run_id="runtime_observed_study_bundle_test",
            )

            assert result.contract_ok is True
            assert result.discovered_run_count == 4
            assert result.included_run_count == 4
            assert result.skipped_run_count == 0
            assert result.observed_sample_count == 8
            assert result.tokenized_example_count == 8
            assert result.profile_modes == [
                "argument_rename",
                "base",
                "name_description_schema",
                "tool_reorder",
            ]
            assert result.seeds == [0, 1]
            assert result.task_count == 4
            assert result.run_count_by_mode == {
                "argument_rename": 1,
                "base": 1,
                "name_description_schema": 1,
                "tool_reorder": 1,
            }
            assert result.sample_count_by_mode == {
                "argument_rename": 2,
                "base": 2,
                "name_description_schema": 2,
                "tool_reorder": 2,
            }
            assert result.trainable_sample_count_by_mode == {
                "argument_rename": 2,
                "base": 2,
                "name_description_schema": 2,
                "tool_reorder": 2,
            }
            assert result.sample_count_by_seed == {"0": 4, "1": 4}
            assert result.sample_count_by_canonical_tool == {
                "finish": 4,
                "read_file": 4,
            }
            assert result.sample_count_by_mode_and_canonical_tool == {
                "argument_rename": {"finish": 1, "read_file": 1},
                "base": {"finish": 1, "read_file": 1},
                "name_description_schema": {"finish": 1, "read_file": 1},
                "tool_reorder": {"finish": 1, "read_file": 1},
            }
            assert result.sample_count_by_mode_and_schema_variant_category == {
                "argument_rename": {"argument_rename": 2},
                "name_description_schema": {
                    "argument_rename": 1,
                    "schema_flat_to_nested": 1,
                },
            }
            assert result.sample_count_by_tool_reordered == {"false": 8}
            assert result.runtime_trace_present_count == 4
            assert result.runtime_trace_coverage_rate == 1.0
            assert result.trace_backed_sample_count == 8
            assert result.trace_backed_sample_rate == 1.0
            assert result.completed_run_count == 4
            assert result.verifier_passed_run_count == 4
            assert result.reconciliation_ok_count == 8
            assert result.reconciliation_error_count == 0
            assert result.critical_reconciliation_error_count == 0
            assert result.sample_count_by_execution_kind == {
                "file_read": 4,
                "finish_signal": 4,
            }
            assert result.sample_count_by_policy_decision == {"allow": 8}
            assert result.deny_count_by_policy_reason_code == {}
            assert result.sample_count_by_content_delta_kind == {}
            assert result.validation_turn_count == 0
            assert result.revalidation_turn_count == 0
            assert result.revision_turn_count == 0
            assert result.finish_deferred_count == 0
            assert result.compaction_turn_count == 0
            assert result.runs_with_validation_failure == 0
            assert result.runs_with_revision_after_failure == 0
            assert result.runs_with_finish_deferred == 0
            assert result.runs_with_compaction == 0

            assert (output_dir / "raw_dataset" / "train.jsonl").exists()
            assert (output_dir / "prepared" / "tokenized.jsonl").exists()
            assert (output_dir / "study_observed_manifest.json").exists()
            assert (output_dir / "study_observed_summary.json").exists()
            assert (output_dir / "runtime_observed_bundle.json").exists()
            assert (output_dir / "runtime_behavior_audit.json").exists()
            assert (output_dir / "runtime_execution_reconciliation.json").exists()

            summary = json.loads(
                (output_dir / "study_observed_summary.json").read_text(encoding="utf-8")
            )
            assert summary["sample_count_by_canonical_tool"] == {
                "finish": 4,
                "read_file": 4,
            }
            assert summary["trainable_sample_count_by_mode"] == {
                "argument_rename": 2,
                "base": 2,
                "name_description_schema": 2,
                "tool_reorder": 2,
            }
            assert summary["sample_count_by_mode_and_canonical_tool"] == {
                "argument_rename": {"finish": 1, "read_file": 1},
                "base": {"finish": 1, "read_file": 1},
                "name_description_schema": {"finish": 1, "read_file": 1},
                "tool_reorder": {"finish": 1, "read_file": 1},
            }
            assert summary["sample_count_by_mode_and_schema_variant_category"] == {
                "argument_rename": {"argument_rename": 2},
                "name_description_schema": {
                    "argument_rename": 1,
                    "schema_flat_to_nested": 1,
                },
            }
            assert summary["sample_count_by_tool_reordered"] == {"false": 8}
            assert summary["trace_backed_sample_count"] == 8
            assert summary["trace_backed_sample_rate"] == 1.0
            assert summary["reconciliation_ok_count"] == 8
            assert summary["reconciliation_error_count"] == 0
            assert summary["critical_reconciliation_error_count"] == 0
            assert summary["validation_turn_count"] == 0
            assert summary["runs_with_compaction"] == 0

            manifest = json.loads(
                (output_dir / "study_observed_manifest.json").read_text(encoding="utf-8")
            )
            assert manifest["bundle_type"] == "runtime_observed_study_bundle"
            assert manifest["source_type"] == "study"
            assert manifest["observed_sample_count"] == 8
            assert "runtime_behavior_audit_path" in manifest["paths"]
            assert "runtime_execution_reconciliation_path" in manifest["paths"]
        finally:
            _cleanup(tmp)

    def test_experiment_runner_build_runtime_observed_bundle_explicit_entry(self) -> None:
        tmp = _get_test_dir()
        try:
            source = _make_source_repo(
                tmp,
                "experiment_source",
                {
                    "main.py": "print('hello')\n",
                    "test_ok.py": "def test_ok():\n    assert True\n",
                },
            )
            tasks_path = _make_tasks_jsonl(
                tmp,
                [
                    {
                        "task_id": "task_001",
                        "repo_path": str(source),
                        "prompt": "Read main.py and finish.",
                        "test_command": "pytest -q -p no:cacheprovider",
                        "max_turns": 4,
                    }
                ],
            )
            config = ExperimentConfig(
                experiment_id="observed_bundle_experiment",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(tmp / "experiments"),
            )

            runner = ExperimentRunner(_make_read_then_finish_factory())
            result = runner.run(config)
            bundle = runner.build_runtime_observed_bundle(
                result,
                fake_tokenizer_config=FakeTokenizerConfig(),
                max_length=2048,
                run_id="runtime_observed_experiment_bundle_test",
            )

            assert bundle.source_type == "experiment"
            assert bundle.discovered_run_count == 1
            assert bundle.observed_sample_count == 2
            assert Path(bundle.study_observed_manifest_path).exists()
            assert Path(bundle.study_observed_summary_path).exists()
            assert Path(bundle.runtime_behavior_audit_path).exists()
            assert Path(bundle.runtime_execution_reconciliation_path).exists()
            assert Path(bundle.bundle_root).name == "runtime_observed_bundle"
        finally:
            _cleanup(tmp)

    def test_study_runner_build_runtime_observed_bundle_explicit_entry(self) -> None:
        tmp = _get_test_dir()
        try:
            source = _make_source_repo(
                tmp,
                "study_source",
                {
                    "main.py": "print('hello')\n",
                    "test_ok.py": "def test_ok():\n    assert True\n",
                },
            )
            tasks_path = _make_tasks_jsonl(
                tmp,
                [
                    {
                        "task_id": "task_001",
                        "repo_path": str(source),
                        "prompt": "Read main.py and finish.",
                        "test_command": "pytest -q -p no:cacheprovider",
                        "max_turns": 4,
                    }
                ],
            )
            config = StudyConfig(
                study_id="observed_bundle_study",
                tasks_path=str(tasks_path),
                profile_modes=["base"],
                seeds=[0],
                output_root=str(tmp / "studies"),
            )

            runner = MutationStudyRunner(_make_read_then_finish_factory())
            result = runner.run(config)
            bundle = runner.build_runtime_observed_bundle(
                result,
                fake_tokenizer_config=FakeTokenizerConfig(),
                max_length=2048,
                run_id="runtime_observed_study_bundle_explicit_test",
            )

            assert bundle.source_type == "study"
            assert bundle.discovered_run_count == 1
            assert bundle.observed_sample_count == 2
            assert Path(bundle.study_observed_manifest_path).exists()
            assert Path(bundle.study_observed_summary_path).exists()
            assert Path(bundle.runtime_behavior_audit_path).exists()
            assert Path(bundle.runtime_execution_reconciliation_path).exists()
            assert Path(bundle.bundle_root).name == "runtime_observed_bundle"
        finally:
            _cleanup(tmp)
