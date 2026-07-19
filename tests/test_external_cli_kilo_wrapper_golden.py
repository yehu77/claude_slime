"""Golden snapshot test for the Kilo wrapper smoke bundle."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pycodeagent.testing import cleanup_test_path, make_unique_test_dir

from run_external_agent_smoke import run_external_agent_smoke


_FIXTURE_DIR = Path("tests/fixtures/external_cli_kilo_wrapper_bundle")
_TEST_NAMESPACE = "external_cli_kilo_wrapper_golden"
_RUN_ID = "kilo_wrapper_smoke_001"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _normalize_string(
    value: str,
    *,
    repo_root: Path,
    run_dir: Path,
    workspace_dir: Path,
) -> str:
    normalized = value.replace("\r\n", "\n").replace("\\", "/")
    replacements = [
        (str(workspace_dir.resolve()), "<workspace_dir>"),
        (str(run_dir.resolve()), "<run_dir>"),
        (str(repo_root.resolve()), "<repo_root>"),
    ]
    for source, target in replacements:
        normalized = normalized.replace(source, target)
        normalized = normalized.replace(source.replace("\\", "/"), target)
    normalized = re.sub(
        r"\n=+ warnings summary =+\n.*?\n-- Docs: https://docs\.pytest\.org/en/stable/how-to/capture-warnings\.html\n",
        "\n",
        normalized,
        flags=re.DOTALL,
    )
    normalized = re.sub(
        r"=+ FAILURES =+",
        "================================== FAILURES ===================================",
        normalized,
    )
    normalized = re.sub(
        r"=+ short test summary info =+",
        "=========================== short test summary info ===========================",
        normalized,
    )
    normalized = re.sub(
        r"_+\s+(test_[^\n]+?)\s+_+",
        r"__ \1 __",
        normalized,
    )
    normalized = re.sub(
        r"(?:<repo_root>/[^:\n]*/)?([^/\n:]+\.py:\d+)",
        r"\1",
        normalized,
    )
    normalized = re.sub(r", \d+ warnings", "", normalized)
    normalized = re.sub(r"in \d+\.\d+s", "in <duration>", normalized)
    return normalized


def _normalize_value(
    value,
    *,
    repo_root: Path,
    run_dir: Path,
    workspace_dir: Path,
):
    if isinstance(value, str):
        return _normalize_string(
            value,
            repo_root=repo_root,
            run_dir=run_dir,
            workspace_dir=workspace_dir,
        )
    if isinstance(value, list):
        return [
            _normalize_value(
                item,
                repo_root=repo_root,
                run_dir=run_dir,
                workspace_dir=workspace_dir,
            )
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: _normalize_value(
                item,
                repo_root=repo_root,
                run_dir=run_dir,
                workspace_dir=workspace_dir,
            )
            for key, item in value.items()
        }
    return value


class TestExternalCliKiloWrapperGolden:
    def test_wrapper_smoke_bundle_matches_fixture(self) -> None:
        tmp = make_unique_test_dir(_TEST_NAMESPACE)
        try:
            repo_root = Path.cwd().resolve()
            result = run_external_agent_smoke(
                agent="kilo_code",
                repo_path=repo_root / "examples" / "buggy_counter",
                output_dir=tmp / "runs",
                prompt="Inspect the repo and run tests.",
                test_command="python -m pytest -q",
                command_prefix=[
                    "python",
                    str(
                        repo_root
                        / "examples"
                        / "external_wrappers"
                        / "kilo_code_sidecar_wrapper.py"
                    ),
                ],
                run_id=_RUN_ID,
            )
            run_dir = Path(str(result["bundle_dir"]))
            workspace_dir = run_dir / "workspace"
            summary = _load_json(run_dir / "raw_trace_summary.json")
            verifier = _load_json(run_dir / "verifier.json")
            canonical = _load_json(run_dir / "canonical_trace.json")
            final_diff = (run_dir / "final.diff").read_text(encoding="utf-8")

            assert result["tool_catalog_path"] is None
            assert not (run_dir / "tool_catalog.json").exists()

            assert _normalize_value(
                summary,
                repo_root=repo_root,
                run_dir=run_dir,
                workspace_dir=workspace_dir,
            ) == _normalize_value(
                _load_json(_FIXTURE_DIR / "raw_trace_summary.json"),
                repo_root=repo_root,
                run_dir=run_dir,
                workspace_dir=workspace_dir,
            )
            assert result["status"] == "completed"
            assert summary["metadata"]["execution_status"] == "completed"
            assert summary["status"] == summary["metadata"]["final_status"] == "failed"
            assert summary["final_diff"] == final_diff
            assert summary["verifier_result"] == verifier
            assert summary["metadata"]["reward"] == verifier["score"] == 0.0
            assert canonical["status"] == summary["status"]
            assert canonical["final_diff"] == final_diff
            assert canonical["verifier_result"] == verifier

            assert _normalize_value(
                _load_jsonl(run_dir / "raw_trace.jsonl"),
                repo_root=repo_root,
                run_dir=run_dir,
                workspace_dir=workspace_dir,
            ) == _normalize_value(
                _load_jsonl(_FIXTURE_DIR / "raw_trace.jsonl"),
                repo_root=repo_root,
                run_dir=run_dir,
                workspace_dir=workspace_dir,
            )

            assert _normalize_string(
                (run_dir / "final.diff").read_text(encoding="utf-8"),
                repo_root=repo_root,
                run_dir=run_dir,
                workspace_dir=workspace_dir,
            ) == _normalize_string(
                (_FIXTURE_DIR / "final.diff").read_text(encoding="utf-8"),
                repo_root=repo_root,
                run_dir=run_dir,
                workspace_dir=workspace_dir,
            )

            assert _normalize_value(
                verifier,
                repo_root=repo_root,
                run_dir=run_dir,
                workspace_dir=workspace_dir,
            ) == _normalize_value(
                _load_json(_FIXTURE_DIR / "verifier.json"),
                repo_root=repo_root,
                run_dir=run_dir,
                workspace_dir=workspace_dir,
            )

            assert _normalize_value(
                _load_json(run_dir / "adapter_metadata.json"),
                repo_root=repo_root,
                run_dir=run_dir,
                workspace_dir=workspace_dir,
            ) == _normalize_value(
                _load_json(_FIXTURE_DIR / "adapter_metadata.json"),
                repo_root=repo_root,
                run_dir=run_dir,
                workspace_dir=workspace_dir,
            )
        finally:
            cleanup_test_path(tmp)
