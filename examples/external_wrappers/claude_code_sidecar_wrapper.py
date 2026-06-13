"""Example Claude Code wrapper that writes scaffold sidecar artifacts.

This is a smoke-test wrapper, not a real vendor binary.
It demonstrates the expected sidecar handoff protocol.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    prompt = argv[-1] if argv else ""

    workspace_dir = Path(os.environ["PYCODEAGENT_WORKSPACE_DIR"])
    raw_trace_path = Path(os.environ["PYCODEAGENT_RAW_TRACE_PATH"])
    raw_trace_summary_path = Path(os.environ["PYCODEAGENT_RAW_TRACE_SUMMARY_PATH"])

    target = workspace_dir / "README.md"
    if not target.exists():
        py_files = sorted(workspace_dir.glob("*.py"))
        target = py_files[0] if py_files else (workspace_dir / "WRAPPER_TOUCH.txt")

    original = target.read_text(encoding="utf-8") if target.exists() else ""
    target.write_text(original + "\n# Wrapper touched this file.\n", encoding="utf-8")

    raw_trace_path.write_text(
        json.dumps(
            {
                "event_id": "event_001",
                "seq": 1,
                "event_kind": "assistant_text",
                "source": "agent",
                "visibility": "model",
                "evidence_level": "observed",
                "raw_payload": {},
                "parsed_payload": {"text": "I will inspect the repository and prepare a fix."},
                "parent_event_id": None,
                "artifact_refs": [],
                "error": None,
                "metadata": {"wrapper": "claude_code_sidecar_wrapper"},
            }
        )
        + "\n"
        + json.dumps(
            {
                "event_id": "event_002",
                "seq": 2,
                "event_kind": "run_end",
                "source": "adapter",
                "visibility": "internal",
                "evidence_level": "observed",
                "raw_payload": {},
                "parsed_payload": {"status": "completed", "wrapper_prompt": prompt},
                "parent_event_id": None,
                "artifact_refs": [],
                "error": None,
                "metadata": {"wrapper": "claude_code_sidecar_wrapper"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    raw_trace_summary_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "trace_id": "claude_code_wrapper_trace",
                "agent_name": "claude_code",
                "agent_version": "raw_trace_v1",
                "task_id": os.environ["PYCODEAGENT_TASK_ID"],
                "workspace_dir": str(workspace_dir),
                "tool_catalog_id": None,
                "status": "completed",
                "final_diff": "",
                "verifier_result": {
                    "passed": True,
                    "score": 1.0,
                    "stdout": "",
                    "stderr": ""
                },
                "metadata": {
                    "capture_mode": "sidecar",
                    "wrapper": "claude_code_sidecar_wrapper"
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("claude_code sidecar wrapper completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
