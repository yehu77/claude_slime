"""Build and verify the single phase-one multi-agent mock golden bundle.

The checked-in snapshot deliberately lives under ``examples/`` because it is
also the documented phase-one contract.  Tests consume that exact directory;
there is no second fixture copy to keep in sync.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Sequence

from pycodeagent.adapters.mock_adapter import MockAdapter, MockTraceNormalizer
from pycodeagent.env.task import CodingTask
from pycodeagent.harness import AgentHarness
from pycodeagent.rl.schema_following import SchemaFollowingSample
from pycodeagent.tools.spec import ToolProfile
from pycodeagent.traces import (
    RawAgentTrace,
    SchemaFollowingTraceRenderer,
    read_canonical_trace,
    read_normalization_report,
    read_raw_trace,
    read_tool_catalog,
    write_canonical_trace,
    write_normalization_report,
    write_raw_trace,
    write_tool_catalog,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN_DIR = _PROJECT_ROOT / "examples" / "multi_agent_mock_run"

GOLDEN_ID = "phase1_multi_agent_mock_native_claude_v1"
GOLDEN_RUN_ID = "phase1_multi_agent_mock"
GOLDEN_TASK_ID = "phase1_multi_agent_mock_task"
GOLDEN_PROFILE_ID = "mock_base"
WORKSPACE_PLACEHOLDER = "<workspace_dir>"
MANIFEST_FILENAME = "golden_manifest.json"
ARTIFACT_FILENAMES = (
    "README.md",
    "raw_trace.jsonl",
    "raw_trace_summary.json",
    "tool_catalog.json",
    "canonical_trace.json",
    "normalization_report.json",
    "schema_following_sample.json",
)


class MultiAgentMockGoldenError(ValueError):
    """Raised when the checked-in phase-one golden is incomplete or drifts."""


def build_multi_agent_mock_golden(output_dir: str | Path) -> dict[str, Any]:
    """Regenerate the deterministic native-Claude phase-one mock bundle."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pycodeagent_multi_agent_mock_") as tmp:
        work_root = Path(tmp)
        source_repo = work_root / "source_repo"
        source_repo.mkdir()
        (source_repo / "README.md").write_text(
            "# Phase-one mock source\n",
            encoding="utf-8",
        )
        task = _build_task(source_repo)
        result = AgentHarness(
            adapter=MockAdapter(),
            normalizer=MockTraceNormalizer(),
        ).run_task(
            task,
            output_dir=work_root / "runs",
            run_id=GOLDEN_RUN_ID,
        )

        if result.tool_catalog is None:
            raise MultiAgentMockGoldenError("MockAdapter did not emit a tool catalog")
        profile_payload = result.tool_catalog.metadata.get("tool_profile")
        if not isinstance(profile_payload, dict):
            raise MultiAgentMockGoldenError("Mock tool catalog is missing tool_profile")
        source_profile = ToolProfile.model_validate(profile_payload)
        sanitized_trace = RawAgentTrace(
            summary=result.raw_trace.summary.model_copy(
                update={"workspace_dir": WORKSPACE_PLACEHOLDER}
            ),
            events=result.raw_trace.events,
        )
        samples = SchemaFollowingTraceRenderer().render_from_trace(
            result.normalization.canonical_trace,
            raw_trace=sanitized_trace,
            target_profiles=[source_profile],
        )
        if len(samples) != len(result.normalization.canonical_trace.actions):
            raise MultiAgentMockGoldenError(
                "Schema renderer did not produce one sample per canonical action"
            )
        if not samples:
            raise MultiAgentMockGoldenError("Mock golden produced no schema-following sample")

        _write_readme(target / "README.md")
        write_raw_trace(
            sanitized_trace,
            target / "raw_trace.jsonl",
            target / "raw_trace_summary.json",
        )
        write_tool_catalog(result.tool_catalog, target / "tool_catalog.json")
        write_canonical_trace(
            result.normalization.canonical_trace,
            target / "canonical_trace.json",
        )
        write_normalization_report(
            result.normalization.report,
            target / "normalization_report.json",
        )
        _write_json(
            target / "schema_following_sample.json",
            samples[0].model_dump(mode="json"),
        )

    manifest = _build_manifest(target)
    _write_json(target / MANIFEST_FILENAME, manifest, sort_keys=True)
    return manifest


def verify_multi_agent_mock_golden(output_dir: str | Path) -> dict[str, Any]:
    """Verify manifest hashes plus cross-artifact phase-one contracts."""
    target = Path(output_dir)
    if not target.is_dir():
        raise MultiAgentMockGoldenError(f"Golden directory is missing: {target}")

    expected_names = set(ARTIFACT_FILENAMES) | {MANIFEST_FILENAME}
    actual_names = {entry.name for entry in target.iterdir()}
    if actual_names != expected_names:
        raise MultiAgentMockGoldenError(
            "Golden file set drift: "
            f"expected {sorted(expected_names)!r}, got {sorted(actual_names)!r}"
        )

    manifest = _read_json(target / MANIFEST_FILENAME)
    if manifest.get("schema_version") != 1:
        raise MultiAgentMockGoldenError("Golden manifest has unsupported schema_version")
    if manifest.get("golden_id") != GOLDEN_ID:
        raise MultiAgentMockGoldenError("Golden manifest has unexpected golden_id")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(ARTIFACT_FILENAMES):
        raise MultiAgentMockGoldenError("Golden manifest artifact set drift")
    for name in ARTIFACT_FILENAMES:
        record = artifacts[name]
        if not isinstance(record, dict):
            raise MultiAgentMockGoldenError(f"Golden manifest record is invalid: {name}")
        path = target / name
        actual_size = path.stat().st_size
        actual_digest = _sha256(path)
        if record.get("bytes") != actual_size:
            raise MultiAgentMockGoldenError(f"Golden byte-size drift: {name}")
        if record.get("sha256") != actual_digest:
            raise MultiAgentMockGoldenError(f"Golden sha256 drift: {name}")

    raw_trace = read_raw_trace(
        target / "raw_trace.jsonl",
        target / "raw_trace_summary.json",
    )
    catalog = read_tool_catalog(target / "tool_catalog.json")
    canonical_trace = read_canonical_trace(target / "canonical_trace.json")
    report = read_normalization_report(target / "normalization_report.json")
    sample = SchemaFollowingSample.model_validate(
        _read_json(target / "schema_following_sample.json")
    )
    _verify_cross_artifact_contract(
        manifest=manifest,
        raw_trace=raw_trace,
        catalog=catalog,
        canonical_trace=canonical_trace,
        report=report,
        sample=sample,
    )
    return manifest


def check_multi_agent_mock_golden(output_dir: str | Path = DEFAULT_GOLDEN_DIR) -> dict[str, Any]:
    """Verify the snapshot and compare it byte-for-byte with a fresh rebuild."""
    target = Path(output_dir)
    manifest = verify_multi_agent_mock_golden(target)
    with tempfile.TemporaryDirectory(prefix="pycodeagent_multi_agent_check_") as tmp:
        regenerated = Path(tmp) / "golden"
        build_multi_agent_mock_golden(regenerated)
        verify_multi_agent_mock_golden(regenerated)
        for name in (*ARTIFACT_FILENAMES, MANIFEST_FILENAME):
            if (target / name).read_bytes() != (regenerated / name).read_bytes():
                raise MultiAgentMockGoldenError(
                    f"Golden regeneration drift: {name}; run the documented --write command"
                )
    return manifest


def _build_task(source_repo: Path) -> CodingTask:
    return CodingTask(
        task_id=GOLDEN_TASK_ID,
        repo_path=source_repo,
        prompt="Inspect the repo and run tests.",
        test_command="pytest -q",
        metadata={
            "mock_plan": [
                {
                    "tool": "Read",
                    "arguments": {"file_path": "README.md"},
                    "assistant_text": "I will inspect the repository README first.",
                    "result": {"ok": True, "content": "README contents"},
                },
                {
                    "tool": "Bash",
                    "arguments": {"command": "pytest -q"},
                    "assistant_text": "I will run tests to validate the current state.",
                    "result": {"ok": True, "content": "pytest passed"},
                },
            ]
        },
    )


def _build_manifest(target: Path) -> dict[str, Any]:
    raw_trace = read_raw_trace(
        target / "raw_trace.jsonl",
        target / "raw_trace_summary.json",
    )
    catalog = read_tool_catalog(target / "tool_catalog.json")
    canonical_trace = read_canonical_trace(target / "canonical_trace.json")
    profile_payload = catalog.metadata.get("tool_profile")
    if not isinstance(profile_payload, dict):
        raise MultiAgentMockGoldenError("Generated catalog is missing tool_profile")
    profile = ToolProfile.model_validate(profile_payload)
    sample = SchemaFollowingSample.model_validate(
        _read_json(target / "schema_following_sample.json")
    )
    return {
        "schema_version": 1,
        "golden_id": GOLDEN_ID,
        "generator": {
            "module": "pycodeagent.testing.multi_agent_mock_golden",
            "update_command": (
                "python -B -m pycodeagent.testing.multi_agent_mock_golden --write"
            ),
            "check_command": (
                "python -B -m pycodeagent.testing.multi_agent_mock_golden --check"
            ),
        },
        "artifacts": {
            name: {"bytes": (target / name).stat().st_size, "sha256": _sha256(target / name)}
            for name in ARTIFACT_FILENAMES
        },
        "contract": {
            "agent_name": raw_trace.agent_name,
            "agent_version": raw_trace.agent_version,
            "task_id": raw_trace.task_id,
            "tool_catalog_id": raw_trace.tool_catalog_id,
            "tool_profile_id": profile.profile_id,
            "family": profile.metadata.get("family"),
            "native_profile_kind": profile.metadata.get("native_profile_kind"),
            "status": raw_trace.status.value,
            "raw_event_count": len(raw_trace.events),
            "canonical_action_count": len(canonical_trace.actions),
            "canonical_capabilities": [
                action.capability for action in canonical_trace.actions
            ],
            "sample_action_id": sample.metadata.get("action_id"),
            "sample_target_tool_name": sample.target_tool_call.name,
        },
    }


def _verify_cross_artifact_contract(
    *,
    manifest: dict[str, Any],
    raw_trace: RawAgentTrace,
    catalog,
    canonical_trace,
    report,
    sample: SchemaFollowingSample,
) -> None:
    contract = manifest.get("contract")
    if not isinstance(contract, dict):
        raise MultiAgentMockGoldenError("Golden manifest contract is invalid")

    expected_values = {
        "agent_name": raw_trace.agent_name,
        "agent_version": raw_trace.agent_version,
        "task_id": raw_trace.task_id,
        "tool_catalog_id": raw_trace.tool_catalog_id,
        "status": raw_trace.status.value,
        "raw_event_count": len(raw_trace.events),
        "canonical_action_count": len(canonical_trace.actions),
        "canonical_capabilities": [
            action.capability for action in canonical_trace.actions
        ],
    }
    for field, actual in expected_values.items():
        if contract.get(field) != actual:
            raise MultiAgentMockGoldenError(f"Golden contract drift: {field}")

    if raw_trace.workspace_dir != WORKSPACE_PLACEHOLDER:
        raise MultiAgentMockGoldenError("Golden raw trace workspace path is not sanitized")
    if raw_trace.tool_catalog_id != catalog.catalog_id:
        raise MultiAgentMockGoldenError("Raw trace tool_catalog_id does not match catalog")
    if (catalog.agent_name, catalog.agent_version) != (
        raw_trace.agent_name,
        raw_trace.agent_version,
    ):
        raise MultiAgentMockGoldenError("Catalog agent identity does not match raw trace")

    profile_payload = catalog.metadata.get("tool_profile")
    if not isinstance(profile_payload, dict):
        raise MultiAgentMockGoldenError("Catalog is missing native tool_profile metadata")
    profile = ToolProfile.model_validate(profile_payload)
    if profile.profile_id != contract.get("tool_profile_id"):
        raise MultiAgentMockGoldenError("Golden contract drift: tool_profile_id")
    if profile.metadata.get("family") != "claude":
        raise MultiAgentMockGoldenError("Golden profile is not native Claude family")
    if profile.metadata.get("native_profile_kind") != "native_claude":
        raise MultiAgentMockGoldenError("Golden profile is not strict native Claude")
    if contract.get("family") != "claude":
        raise MultiAgentMockGoldenError("Golden contract drift: family")
    if contract.get("native_profile_kind") != "native_claude":
        raise MultiAgentMockGoldenError("Golden contract drift: native_profile_kind")

    catalog_names = {tool.raw_tool_name for tool in catalog.tools}
    raw_events_by_id = {event.event_id: event for event in raw_trace.events}
    raw_tool_calls = [event for event in raw_trace.events if event.event_kind == "tool_call"]
    if not raw_tool_calls:
        raise MultiAgentMockGoldenError("Golden raw trace contains no tool_call events")
    for event in raw_tool_calls:
        tool_name = event.parsed_payload.get("tool_name")
        if tool_name not in catalog_names:
            raise MultiAgentMockGoldenError(
                f"Raw tool call is absent from native catalog: {tool_name!r}"
            )

    if canonical_trace.trace_id != raw_trace.trace_id:
        raise MultiAgentMockGoldenError("Canonical trace_id does not match raw trace")
    if (canonical_trace.task_id, canonical_trace.agent_name, canonical_trace.agent_version) != (
        raw_trace.task_id,
        raw_trace.agent_name,
        raw_trace.agent_version,
    ):
        raise MultiAgentMockGoldenError("Canonical trace identity does not match raw trace")
    if len(canonical_trace.actions) != len(raw_tool_calls):
        raise MultiAgentMockGoldenError(
            "Canonical action count must equal the number of raw tool calls"
        )
    for action in canonical_trace.actions:
        if not action.raw_event_refs:
            raise MultiAgentMockGoldenError(f"Canonical action has no raw refs: {action.action_id}")
        if any(event_id not in raw_events_by_id for event_id in action.raw_event_refs):
            raise MultiAgentMockGoldenError(
                f"Canonical action has unknown raw ref: {action.action_id}"
            )

    if report.trace_id != raw_trace.trace_id or report.catalog_id != catalog.catalog_id:
        raise MultiAgentMockGoldenError("Normalization report does not match raw trace/catalog")
    if len(report.mapped_events) != len(set(report.mapped_events)):
        raise MultiAgentMockGoldenError("Normalization report contains duplicate mapped events")
    if any(event_id not in raw_events_by_id for event_id in report.mapped_events):
        raise MultiAgentMockGoldenError("Normalization report has unknown mapped event")

    action_by_id = {action.action_id: action for action in canonical_trace.actions}
    sample_action_id = sample.metadata.get("action_id")
    if not isinstance(sample_action_id, str) or sample_action_id not in action_by_id:
        raise MultiAgentMockGoldenError("Schema-following sample has an unknown action_id")
    if contract.get("sample_action_id") != sample_action_id:
        raise MultiAgentMockGoldenError("Golden contract drift: sample_action_id")
    if contract.get("sample_target_tool_name") != sample.target_tool_call.name:
        raise MultiAgentMockGoldenError("Golden contract drift: sample_target_tool_name")
    if sample.task_id != raw_trace.task_id:
        raise MultiAgentMockGoldenError("Schema-following sample task_id does not match raw trace")
    if sample.tool_profile_id != profile.profile_id:
        raise MultiAgentMockGoldenError("Schema-following sample profile does not match catalog")
    if sample.metadata.get("trace_id") != raw_trace.trace_id:
        raise MultiAgentMockGoldenError("Schema-following sample trace_id does not match raw trace")
    action = action_by_id[sample_action_id]
    if sample.canonical_intent.tool.casefold() != action.capability.casefold():
        raise MultiAgentMockGoldenError("Schema-following sample intent does not match action")
    if sample.canonical_intent.arguments != action.canonical_args:
        raise MultiAgentMockGoldenError("Schema-following sample arguments do not match action")
    target_catalog_entry = next(
        (tool for tool in catalog.tools if tool.raw_tool_name == sample.target_tool_call.name),
        None,
    )
    if target_catalog_entry is None:
        raise MultiAgentMockGoldenError("Schema-following target is absent from native catalog")
    if (
        target_catalog_entry.canonical_name is not None
        and target_catalog_entry.canonical_name.casefold()
        != sample.canonical_intent.tool.casefold()
    ):
        raise MultiAgentMockGoldenError(
            "Schema-following target does not resolve to its canonical intent"
        )


def _write_readme(path: Path) -> None:
    path.write_text(
        "# Phase-one multi-agent mock golden\n\n"
        "This directory is the single tracked golden for the phase-one synthetic "
        "multi-agent scaffold. It is generated from a fixed `MockAdapter` scenario "
        "using the strict native Claude ToolView (`mock_base`).\n\n"
        "Do not edit these artifacts by hand. Update them with:\n\n"
        "```bash\n"
        "python -B -m pycodeagent.testing.multi_agent_mock_golden --write\n"
        "```\n\n"
        "Verify both manifest integrity and deterministic regeneration with:\n\n"
        "```bash\n"
        "python -B -m pycodeagent.testing.multi_agent_mock_golden --check\n"
        "```\n\n"
        "The bundle preserves RawAgentTrace, the emitted native tool catalog, agent "
        "identity, canonical normalization, and one representative schema-following "
        "sample. Tests consume this directory directly; no duplicated fixture is kept.\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MultiAgentMockGoldenError(f"Invalid JSON artifact: {path.name}") from exc
    if not isinstance(payload, dict):
        raise MultiAgentMockGoldenError(f"JSON artifact must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any], *, sort_keys: bool = False) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=sort_keys) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or verify the phase-one multi-agent mock golden bundle."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write",
        action="store_true",
        help="regenerate the target golden bundle",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="verify the target bundle and compare it with a fresh rebuild (default)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_GOLDEN_DIR,
        help="golden directory to write or verify",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.write:
        build_multi_agent_mock_golden(args.output_dir)
        verify_multi_agent_mock_golden(args.output_dir)
        print(f"Wrote multi-agent mock golden: {args.output_dir}")
        return 0
    check_multi_agent_mock_golden(args.output_dir)
    print(f"Verified multi-agent mock golden: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
