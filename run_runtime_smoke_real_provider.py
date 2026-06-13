from __future__ import annotations

from pathlib import Path

from pycodeagent.agent import build_llm_client, resolve_runtime_provider_config
from pycodeagent.dev import resolve_local_config_path
from pycodeagent.env.coding_env import run_coding_task
from pycodeagent.env.task import CodingTask


_LOCAL_CONFIG_FILENAME = "real_provider_runtime.local.json"
_REPO_LOCAL_CONFIG_PATH = Path("configs/local/real_provider_runtime.local.json")
_LOCAL_CONFIG_EXAMPLE_PATH = Path("configs/local/real_provider_runtime.local.example.json")
_DEFAULT_OUTPUT_DIR = Path("runs/real_provider_smoke")


def _load_provider_config(path: Path | None = None):
    resolved_path = path or resolve_local_config_path(
        _LOCAL_CONFIG_FILENAME,
        repo_fallback=_REPO_LOCAL_CONFIG_PATH,
    )
    return resolve_runtime_provider_config(
        resolved_path,
        example_path=_LOCAL_CONFIG_EXAMPLE_PATH,
    )


def _build_smoke_task() -> CodingTask:
    return CodingTask(
        task_id="real_provider_smoke_read_then_finish",
        repo_path=Path("examples/runtime_rewrite_greeter"),
        prompt=(
            "Read greeter.py and then finish with a short answer. "
            "Do not modify files in this smoke run."
        ),
        test_command=["python", "-c", "print('real provider smoke ok')"],
        max_turns=4,
        metadata={"category": "real_provider_smoke"},
    )


def main() -> None:
    provider_config = _load_provider_config()
    client = build_llm_client(provider_config)
    task = _build_smoke_task()
    output_dir = _DEFAULT_OUTPUT_DIR / f"{provider_config.client_mode}__{provider_config.model}"

    trajectory = run_coding_task(task, client, output_dir)

    print(f"task_id={trajectory.task_id}")
    print(f"status={trajectory.status.value}")
    print(f"output_dir={output_dir}")
    print(f"tool_profile_id={trajectory.tool_profile_id}")
    print(f"provider={trajectory.metadata.get('provider', {})}")


if __name__ == "__main__":
    main()
