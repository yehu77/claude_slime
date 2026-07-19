from __future__ import annotations

from pathlib import Path

from pycodeagent.agent import resolve_runtime_provider_config
from pycodeagent.dev import resolve_local_config_path
from pycodeagent.eval import run_study_from_provider_config


_LOCAL_CONFIG_FILENAME = "real_provider_runtime.local.json"
_REPO_LOCAL_CONFIG_PATH = Path("configs/local/real_provider_runtime.local.json")
_LOCAL_CONFIG_EXAMPLE_PATH = Path("configs/local/real_provider_runtime.local.example.json")
_DEFAULT_STUDY_CONFIG_PATH = "configs/studies/first_mutation_sensitivity.json"
_DEFAULT_OUTPUT_DIR = "runs/studies/first_mutation_sensitivity_real_provider"


def _resolve_provider_config_path(path: Path | None = None) -> Path:
    return path or resolve_local_config_path(
        _LOCAL_CONFIG_FILENAME,
        repo_fallback=_REPO_LOCAL_CONFIG_PATH,
    )


def main() -> None:
    provider_config_path = _resolve_provider_config_path()
    resolve_runtime_provider_config(
        provider_config_path,
        example_path=_LOCAL_CONFIG_EXAMPLE_PATH,
    )
    result = run_study_from_provider_config(
        _DEFAULT_STUDY_CONFIG_PATH,
        provider_config_path,
        output_dir=_DEFAULT_OUTPUT_DIR,
    )

    print(f"study_id={result.config.study_id}")
    print(f"output_dir={result.output_dir}")
    print(f"task_count={result.task_count}")
    print(f"provider_config={provider_config_path}")
    print(f"provider_config_example={_LOCAL_CONFIG_EXAMPLE_PATH}")
    print("mode_comparisons=")
    for comp in result.mode_comparisons:
        print(
            f"  {comp.mode}: pass_at_1={comp.pass_at_1:.3f}, "
            f"delta_pass_at_1={comp.delta_pass_at_1:.3f}, "
            f"avg_reward={comp.avg_reward:.3f}, "
            f"delta_avg_reward={comp.delta_avg_reward:.3f}"
        )


if __name__ == "__main__":
    main()
