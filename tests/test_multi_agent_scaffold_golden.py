"""Golden snapshot tests for the phase-one multi-agent mock scaffold."""

from __future__ import annotations

import json
from pathlib import Path

from pycodeagent.adapters.mock_adapter import (
    MockTraceNormalizer,
    build_mock_tool_catalog,
    generate_synthetic_raw_trace,
)
from pycodeagent.env.task import CodingTask
from pycodeagent.tools.profile_factory import build_base_tool_profile
from pycodeagent.traces import SchemaFollowingTraceRenderer


_FIXTURE_DIR = Path("tests/fixtures/multi_agent_mock_bundle")
_EXAMPLE_DIR = Path("examples/multi_agent_mock_run")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _build_expected_snapshot() -> tuple[dict, list[dict], dict, dict, dict]:
    repo = Path("examples/buggy_counter")
    task = CodingTask(
        task_id="task_001",
        repo_path=repo,
        prompt="Inspect the repo and run tests.",
        test_command="pytest -q",
    )
    profile = build_base_tool_profile(profile_id="mock_base")
    catalog = build_mock_tool_catalog(
        task_id=task.task_id,
        agent_name="mock_agent",
        agent_version="v1",
        profile=profile,
    )
    raw_trace = generate_synthetic_raw_trace(
        task=task,
        agent_name="mock_agent",
        agent_version="v1",
        workspace_dir=Path("<workspace_dir>"),
        tool_catalog_id=catalog.catalog_id,
        profile=profile,
    )
    normalization = MockTraceNormalizer().normalize(raw_trace, tool_catalog=catalog)
    renderer = SchemaFollowingTraceRenderer()
    sample = renderer.render_from_trace(
        normalization.canonical_trace,
        raw_trace=raw_trace,
        target_profiles=[build_base_tool_profile(profile_id="base")],
    )[0]
    return (
        raw_trace.summary.model_dump(mode="json"),
        [event.model_dump(mode="json") for event in raw_trace.events],
        normalization.canonical_trace.model_dump(mode="json"),
        normalization.report.model_dump(mode="json"),
        sample.model_dump(mode="json"),
    )


class TestMultiAgentScaffoldGolden:
    def test_fixture_bundle_matches_generated_snapshot(self) -> None:
        (
            expected_summary,
            expected_events,
            expected_canonical,
            expected_report,
            expected_sample,
        ) = _build_expected_snapshot()

        assert _load_json(_FIXTURE_DIR / "raw_trace_summary.json") == expected_summary
        assert _load_jsonl(_FIXTURE_DIR / "raw_trace.jsonl") == expected_events
        assert _load_json(_FIXTURE_DIR / "canonical_trace.json") == expected_canonical
        assert _load_json(_FIXTURE_DIR / "normalization_report.json") == expected_report
        assert _load_json(_FIXTURE_DIR / "schema_following_sample.json") == expected_sample

    def test_example_bundle_matches_fixture_bundle(self) -> None:
        for name in (
            "raw_trace_summary.json",
            "raw_trace.jsonl",
            "canonical_trace.json",
            "normalization_report.json",
            "schema_following_sample.json",
        ):
            assert (_EXAMPLE_DIR / name).read_text(encoding="utf-8") == (
                _FIXTURE_DIR / name
            ).read_text(encoding="utf-8")
