"""End-to-end tests for the phase-one mock scaffold."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycodeagent.adapters import MockAdapter, MockToolCatalogProvider, MockTraceNormalizer
from pycodeagent.env.task import CodingTask
from pycodeagent.harness import AgentHarness
from pycodeagent.rl.schema_following_dataset import write_schema_following_jsonl
from pycodeagent.rl.training_prep import prepare_schema_following_training_input
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir
from pycodeagent.tools.profile_factory import build_base_tool_profile
from pycodeagent.traces import SchemaFollowingTraceRenderer


_TEST_NAMESPACE = "mock_scaffold"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


def _make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "README.md").write_text("# Repo\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    return repo


def _make_task(repo: Path, *, prompt: str = "Inspect the repo and run tests.") -> CodingTask:
    return CodingTask(
        task_id="task_001",
        repo_path=repo,
        prompt=prompt,
        test_command="pytest -q",
        metadata={},
    )


def _write_schema_following_dataset(dataset_dir: Path, samples) -> None:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    write_schema_following_jsonl(samples, dataset_dir / "train.jsonl")
    (dataset_dir / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "dataset_type": "schema_following_synthetic",
                "version": 1,
                "sample_count": len(samples),
                "loss_mask_policy": "assistant_tool_call_only",
                "present_splits": ["train"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (dataset_dir / "split_metrics.json").write_text(
        json.dumps({"version": 1, "split_counts": {"train": len(samples)}}, indent=2),
        encoding="utf-8",
    )


class _CountingCatalogProvider:
    def __init__(self) -> None:
        self.calls = 0
        self._delegate = MockToolCatalogProvider()

    def agent_id(self) -> str:
        return self._delegate.agent_id()

    def get_tool_catalog(self, **kwargs):
        self.calls += 1
        return self._delegate.get_tool_catalog(**kwargs)


class _EscapePathAdapter:
    def agent_id(self) -> str:
        return "bad_agent"

    def agent_version(self) -> str:
        return "v1"

    def run_task(self, task: CodingTask, context) -> object:
        from pycodeagent.traces import RawAgentRunResult

        outside = context.run_dir.parent.parent / "outside.jsonl"
        return RawAgentRunResult(
            run_id=context.run_id,
            task_id=task.task_id,
            agent_id=self.agent_id(),
            agent_version=self.agent_version(),
            raw_trace_path=str(outside),
            raw_trace_summary_path=str(outside.with_name("outside_summary.json")),
            stdout_path=str(context.stdout_path),
            stderr_path=str(context.stderr_path),
            final_diff_path=str(context.run_dir / "final.diff"),
            verifier_result_path=str(context.run_dir / "verifier.json"),
            workspace_before_hash="before",
            workspace_after_hash="after",
        )


class TestMockScaffold:
    def test_mock_normalizer_ignores_harness_verifier_command(self) -> None:
        tmp = _get_test_dir()
        try:
            repo = _make_repo(tmp)
            task = _make_task(repo)
            harness = AgentHarness(
                adapter=MockAdapter(),
                normalizer=MockTraceNormalizer(),
                tool_catalog_provider=MockToolCatalogProvider(),
            )

            result = harness.run_task(task, output_dir=tmp / "runs", run_id="run_001")

            capabilities = [action.capability for action in result.normalization.canonical_trace.actions]
            assert capabilities == ["READ_FILE", "RUN_COMMAND", "FINISH"]
            assert len([cap for cap in capabilities if cap == "RUN_COMMAND"]) == 1
            assert any(
                event.parsed_payload.get("command_role") == "harness_verifier"
                for event in result.raw_trace.events
                if event.event_kind == "command_exec"
            )
        finally:
            _cleanup(tmp)

    def test_renderer_blocks_future_leakage(self) -> None:
        tmp = _get_test_dir()
        try:
            repo = _make_repo(tmp)
            task = _make_task(repo)
            harness = AgentHarness(
                adapter=MockAdapter(),
                normalizer=MockTraceNormalizer(),
                tool_catalog_provider=MockToolCatalogProvider(),
            )
            result = harness.run_task(task, output_dir=tmp / "runs", run_id="run_001")
            renderer = SchemaFollowingTraceRenderer()
            samples = renderer.render_from_trace(
                result.normalization.canonical_trace,
                raw_trace=result.raw_trace,
                target_profiles=[build_base_tool_profile(profile_id="base_test")],
            )

            read_sample = samples[0]
            run_sample = samples[1]
            read_context = "\n".join(message.content for message in read_sample.messages)
            run_context = "\n".join(message.content for message in run_sample.messages)

            assert "README contents" not in read_context
            assert "pytest passed" not in run_context
            assert result.normalization.canonical_trace.final_diff not in run_context
            assert "Task finished." not in run_context
        finally:
            _cleanup(tmp)

    def test_harness_prefers_adapter_catalog_over_provider(self) -> None:
        tmp = _get_test_dir()
        try:
            repo = _make_repo(tmp)
            task = _make_task(repo)
            provider = _CountingCatalogProvider()
            harness = AgentHarness(
                adapter=MockAdapter(emit_tool_catalog=True),
                normalizer=MockTraceNormalizer(),
                tool_catalog_provider=provider,
            )

            result = harness.run_task(task, output_dir=tmp / "runs", run_id="run_001")

            assert provider.calls == 0
            assert result.tool_catalog is not None
            assert result.bundle_paths.tool_catalog_path.exists()
        finally:
            _cleanup(tmp)

    def test_harness_uses_provider_when_adapter_omits_catalog(self) -> None:
        tmp = _get_test_dir()
        try:
            repo = _make_repo(tmp)
            task = _make_task(repo)
            provider = _CountingCatalogProvider()
            harness = AgentHarness(
                adapter=MockAdapter(emit_tool_catalog=False),
                normalizer=MockTraceNormalizer(),
                tool_catalog_provider=provider,
            )

            result = harness.run_task(task, output_dir=tmp / "runs", run_id="run_001")

            assert provider.calls == 1
            assert result.tool_catalog is not None
            assert result.bundle_paths.tool_catalog_path.exists()
        finally:
            _cleanup(tmp)

    def test_harness_rejects_artifact_paths_outside_run_bundle(self) -> None:
        tmp = _get_test_dir()
        try:
            repo = _make_repo(tmp)
            task = _make_task(repo)
            harness = AgentHarness(
                adapter=_EscapePathAdapter(),
                normalizer=MockTraceNormalizer(),
            )

            with pytest.raises(ValueError, match="escapes run bundle"):
                harness.run_task(task, output_dir=tmp / "runs", run_id="run_001")
        finally:
            _cleanup(tmp)

    def test_mock_scaffold_can_feed_schema_following_training_prep(self) -> None:
        tmp = _get_test_dir()
        try:
            repo = _make_repo(tmp)
            task = _make_task(repo)
            harness = AgentHarness(
                adapter=MockAdapter(),
                normalizer=MockTraceNormalizer(),
                tool_catalog_provider=MockToolCatalogProvider(),
            )
            result = harness.run_task(task, output_dir=tmp / "runs", run_id="run_001")
            renderer = SchemaFollowingTraceRenderer()
            samples = renderer.render_from_trace(
                result.normalization.canonical_trace,
                raw_trace=result.raw_trace,
                target_profiles=[build_base_tool_profile(profile_id="base_test")],
            )

            dataset_dir = tmp / "schema_dataset"
            output_dir = tmp / "prepared"
            _write_schema_following_dataset(dataset_dir, samples)
            recommendation = prepare_schema_following_training_input(
                dataset_dir,
                output_dir,
                split="train",
                fake_tokenizer_config=FakeTokenizerConfig(),
                max_length=128,
                batch_size=8,
                learning_rate=1e-4,
                run_id="mock_schema_train",
            )

            assert recommendation.contract_ok is True
            assert recommendation.prepared_sample_count == len(samples)
            assert (output_dir / "contract_report.json").exists()
            assert (output_dir / "tokenized.jsonl").exists()
        finally:
            _cleanup(tmp)
