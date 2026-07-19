from __future__ import annotations

import json
import shutil
from pathlib import Path

from pycodeagent.agent import build_llm_client, resolve_runtime_provider_config
from pycodeagent.dev import resolve_local_config_path
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask


_LOCAL_CONFIG_FILENAME = "real_provider_runtime.local.json"
_REPO_LOCAL_CONFIG_PATH = Path("configs/local/real_provider_runtime.local.json")
_LOCAL_CONFIG_EXAMPLE_PATH = Path("configs/local/real_provider_runtime.local.example.json")
_DEFAULT_OUTPUT_DIR = Path("runs/p3b_real_provider_compaction_acceptance")


def _load_provider_config(path: Path | None = None):
    resolved_path = path or resolve_local_config_path(
        _LOCAL_CONFIG_FILENAME,
        repo_fallback=_REPO_LOCAL_CONFIG_PATH,
    )
    return resolve_runtime_provider_config(
        resolved_path,
        example_path=_LOCAL_CONFIG_EXAMPLE_PATH,
    )


def _build_acceptance_task() -> CodingTask:
    return CodingTask(
        task_id="p3b_real_provider_compaction_acceptance",
        repo_path=Path("examples/runtime_rewrite_greeter"),
        prompt=(
            "First read greeter.py. Then read test_greeter.py. "
            "Only after inspecting both files, finish with a brief summary. "
            "Do not modify files and do not run tests."
        ),
        max_turns=6,
        metadata={"category": "p3b_real_provider_acceptance"},
    )


def _load_trace_events(output_dir: Path) -> list[dict]:
    trace_path = output_dir / "runtime_trace.jsonl"
    if not trace_path.exists():
        return []
    return [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _trace_summary(events: list[dict]) -> dict:
    kinds = [event.get("event_kind") for event in events]
    requested = [event for event in events if event.get("event_kind") == "context_compaction_requested"]
    completed = [event for event in events if event.get("event_kind") == "context_compaction_completed"]
    failed = [event for event in events if event.get("event_kind") == "context_compaction_failed"]
    applied = [event for event in events if event.get("event_kind") == "context_compaction_applied"]
    return {
        "event_kinds": kinds,
        "compaction_requested_count": len(requested),
        "compaction_completed_count": len(completed),
        "compaction_failed_count": len(failed),
        "compaction_applied_count": len(applied),
        "last_requested": requested[-1]["data"] if requested else None,
        "last_completed": completed[-1]["data"] if completed else None,
        "last_failed": failed[-1]["data"] if failed else None,
        "last_applied": applied[-1]["data"] if applied else None,
    }


def main() -> None:
    provider_config = _load_provider_config()
    client = build_llm_client(provider_config)
    task = _build_acceptance_task()
    output_dir = _DEFAULT_OUTPUT_DIR / f"{provider_config.client_mode}__{provider_config.model}"
    if output_dir.exists():
        shutil.rmtree(output_dir)

    trajectory = run_coding_task(
        task,
        client,
        output_dir,
        context_policy_mode="model_backed_compaction",
        context_max_messages=5,
    )
    events = _load_trace_events(output_dir)
    trace_summary = _trace_summary(events)

    print(f"task_id={trajectory.task_id}")
    print(f"status={trajectory.status.value}")
    print(f"output_dir={output_dir}")
    print(f"tool_profile_id={trajectory.tool_profile_id}")
    print(f"provider={trajectory.metadata.get('provider', {})}")
    print(f"history_lineage_ok={trajectory.metadata.get('history_lineage_report_ok')}")
    print(f"compaction_requested_count={trace_summary['compaction_requested_count']}")
    print(f"compaction_completed_count={trace_summary['compaction_completed_count']}")
    print(f"compaction_failed_count={trace_summary['compaction_failed_count']}")
    print(f"compaction_applied_count={trace_summary['compaction_applied_count']}")
    print(
        "last_compaction_completed="
        f"{json.dumps(trace_summary['last_completed'], ensure_ascii=False)}"
    )
    print(
        "last_compaction_applied="
        f"{json.dumps(trace_summary['last_applied'], ensure_ascii=False)}"
    )


if __name__ == "__main__":
    main()
