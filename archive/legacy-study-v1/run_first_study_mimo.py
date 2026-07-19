from __future__ import annotations

from pathlib import Path
from typing import Any

from pycodeagent.agent import MimoNativeToolClient, ModelConfig
from pycodeagent.dev import (
    build_openai_compatible_model_config,
    load_mimo_local_config,
    resolve_local_config_path,
)
from pycodeagent.eval import run_study_from_config


_LOCAL_CONFIG_FILENAME = "mimo_v25pro.local.json"
_REPO_LOCAL_CONFIG_PATH = Path("configs/local/mimo_v25pro.local.json")
_LOCAL_CONFIG_EXAMPLE_PATH = Path("configs/local/mimo_v25pro.local.example.json")
_API_KEY_ENV = "MIMO_API_KEY"
_MODEL_NAME = "mimo-v2.5-pro"


def _load_local_config(path: Path | None = None) -> dict[str, Any]:
    resolved_path = path or resolve_local_config_path(
        _LOCAL_CONFIG_FILENAME,
        repo_fallback=_REPO_LOCAL_CONFIG_PATH,
    )
    return load_mimo_local_config(
        resolved_path,
        example_path=_LOCAL_CONFIG_EXAMPLE_PATH,
        default_api_key_env=_API_KEY_ENV,
    )


def build_model_config(local_config: dict[str, Any]) -> ModelConfig:
    return build_openai_compatible_model_config(
        local_config,
        model_name=_MODEL_NAME,
    )


def main() -> None:
    local_config = _load_local_config()
    model_config = build_model_config(local_config)

    study_config_path = str(
        local_config.get(
            "study_config_path",
            "configs/studies/first_mutation_sensitivity.json",
        )
    )
    output_dir = local_config.get(
        "output_dir",
        "runs/studies/first_mutation_sensitivity_mimo_v25pro",
    )

    result = run_study_from_config(
        study_config_path,
        client_factory=lambda: MimoNativeToolClient(model_config),
        output_dir=output_dir,
    )

    print(f"study_id={result.config.study_id}")
    print(f"output_dir={result.output_dir}")
    print(f"task_count={result.task_count}")
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
