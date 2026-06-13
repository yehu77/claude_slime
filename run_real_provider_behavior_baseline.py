from __future__ import annotations

from pathlib import Path

from pycodeagent.agent import resolve_runtime_provider_config
from pycodeagent.dev import resolve_local_config_path
from pycodeagent.eval import run_real_provider_behavior_baseline


_LOCAL_CONFIG_FILENAME = "real_provider_runtime.local.json"
_REPO_LOCAL_CONFIG_PATH = Path("configs/local/real_provider_runtime.local.json")
_LOCAL_CONFIG_EXAMPLE_PATH = Path("configs/local/real_provider_runtime.local.example.json")
_DEFAULT_TASKS_PATH = Path("datasets/tasks/realistic_runtime_tasks.jsonl")
_DEFAULT_OUTPUT_ROOT = Path("runs/real_provider_behavior_baseline")
_DEFAULT_REPEAT_COUNT = 3


def _resolve_provider_config_path(path: Path | None = None) -> Path | None:
    if path is not None:
        return path
    resolved = resolve_local_config_path(
        _LOCAL_CONFIG_FILENAME,
        repo_fallback=_REPO_LOCAL_CONFIG_PATH,
    )
    return resolved if resolved.exists() else None


def main() -> None:
    provider_config_path = _resolve_provider_config_path()
    provider_config = resolve_runtime_provider_config(
        provider_config_path,
        example_path=_LOCAL_CONFIG_EXAMPLE_PATH,
    )
    output_root = _DEFAULT_OUTPUT_ROOT / f"{provider_config.client_mode}__{provider_config.model}"
    result = run_real_provider_behavior_baseline(
        provider_config,
        output_root,
        tasks_path=_DEFAULT_TASKS_PATH,
        repeat_count=_DEFAULT_REPEAT_COUNT,
        profile_mode="base",
    )

    print(f"output_root={result.output_root}")
    print(f"runs_root={result.runs_root}")
    print(f"task_count={result.task_count}")
    print(f"run_count={result.run_count}")
    print(f"repeat_count={result.repeat_count}")
    print(f"passed={result.summary.pass_count}/{result.summary.run_count}")
    print(f"provider={result.provider}")
    print(f"runtime_behavior_audit={result.runtime_behavior_audit_path}")
    print(f"behavior_baseline_summary={result.behavior_baseline_summary_path}")
    print(f"failure_buckets={result.failure_buckets_path}")


if __name__ == "__main__":
    main()
