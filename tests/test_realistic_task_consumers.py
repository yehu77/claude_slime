"""Mainline contracts for explicit native-family realistic-task consumers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from pycodeagent.agent.llm_client import (
    FakeLLMClient,
    GenerateResponse,
    ToolCallCandidate,
)
from pycodeagent.env.task import CodingTask
from pycodeagent.eval.real_provider_behavior_baseline import run_behavior_baseline
from pycodeagent.eval.real_provider_credibility_bundle import (
    run_provider_credibility_bundle,
)
from pycodeagent.rl.dataset_builder import discover_run_dirs
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig


pytestmark = pytest.mark.mainline


def _native_claude_read_client() -> FakeLLMClient:
    return FakeLLMClient(
        [
            GenerateResponse.from_native_tool_calling(
                assistant_text="Inspecting the workspace.",
                tool_calls=[
                    ToolCallCandidate(
                        call_id="read_1",
                        name="Read",
                        arguments_obj={"file_path": "main.py"},
                        source="native",
                    )
                ],
                finish_reason="tool_calls",
            ),
            GenerateResponse.from_native_tool_calling(
                assistant_text="Done.",
                finish_reason="stop",
            ),
        ]
    )


def _task(tmp_path: Path, task_id: str) -> CodingTask:
    repo = tmp_path / task_id
    repo.mkdir()
    (repo / "main.py").write_text("print('ok')\n", encoding="utf-8")
    return CodingTask(
        task_id=task_id,
        repo_path=repo,
        prompt="Inspect main.py and complete after validation succeeds.",
        test_command=[sys.executable, "-c", "print('verified')"],
        max_turns=3,
        metadata={
            "task_contract": {
                "schema_version": 1,
                "required_capabilities": ["workspace_read", "validation"],
                "require_runtime_validation_evidence": True,
            }
        },
    )


def test_behavior_baseline_records_explicit_tool_stack_kind(tmp_path: Path) -> None:
    task = _task(tmp_path, "behavior_consumer")
    result = run_behavior_baseline(
        [task],
        lambda _task, _repeat: _native_claude_read_client(),
        tmp_path / "behavior",
        repeat_count=1,
        profile_mode="base",
        provider={"provider_kind": "fake"},
        tool_stack_kind="native_claude",
    )

    summary = json.loads(
        Path(result.behavior_baseline_summary_path).read_text(encoding="utf-8")
    )
    run_dir = discover_run_dirs(result.runs_root, source_type="batch")[0]
    profile = json.loads((run_dir / "tool_profile.json").read_text(encoding="utf-8"))

    assert result.tool_stack_kind == "native_claude"
    assert summary["tool_stack_kind"] == "native_claude"
    assert profile["metadata"]["family"] == "claude"
    assert profile["metadata"]["native_profile_kind"] == "native_claude"


def test_credibility_bundle_records_explicit_tool_stack_kind(tmp_path: Path) -> None:
    task = _task(tmp_path, "credibility_consumer")
    result = run_provider_credibility_bundle(
        [task],
        lambda _task, _mode, _repeat: _native_claude_read_client(),
        tmp_path / "credibility",
        provider={
            "provider_kind": "fake",
            "client_mode": "fake_native",
            "model": "fake-model",
            "base_url": "local",
            "api_key_env": "TEST_KEY",
        },
        profile_modes=["base"],
        profile_seed_by_mode={"base": 0},
        repeat_count=1,
        tool_stack_kind="native_claude",
        fake_tokenizer_config=FakeTokenizerConfig(),
    )

    manifest = json.loads(
        Path(result.credibility_manifest_path).read_text(encoding="utf-8")
    )
    summary = json.loads(
        Path(result.credibility_summary_path).read_text(encoding="utf-8")
    )
    run_dir = discover_run_dirs(
        result.source_runs_root,
        source_type="batch",
    )[0]
    profile = json.loads((run_dir / "tool_profile.json").read_text(encoding="utf-8"))

    assert result.tool_stack_kind == "native_claude"
    assert manifest["tool_stack_kind"] == "native_claude"
    assert summary["tool_stack_kind"] == "native_claude"
    assert profile["metadata"]["family"] == "claude"
