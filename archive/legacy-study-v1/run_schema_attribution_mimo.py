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
_DEFAULT_STUDY_CONFIG_PATH = "configs/studies/schema_failure_attribution_v1.json"
_DEFAULT_OUTPUT_DIR = "runs/studies/schema_failure_attribution_v1_mimo_v25pro"
_MODEL_NAME = "mimo-v2.5-pro"


def _load_local_config(path: Path | None = None) -> dict[str, Any]:
    resolved_path = path or resolve_local_config_path(
        _LOCAL_CONFIG_FILENAME,
        repo_fallback=_REPO_LOCAL_CONFIG_PATH,
    )
    return load_mimo_local_config(
        resolved_path,
        example_path=_LOCAL_CONFIG_EXAMPLE_PATH,
        default_api_key_env="MIMO_API_KEY",
    )


def build_model_config(local_config: dict[str, Any]) -> ModelConfig:
    return build_openai_compatible_model_config(
        local_config,
        model_name=_MODEL_NAME,
    )


def main() -> None:
    local_config = _load_local_config()
    model_config = build_model_config(local_config)

    result = run_study_from_config(
        str(local_config.get("schema_study_config_path", _DEFAULT_STUDY_CONFIG_PATH)),
        client_factory=lambda: MimoNativeToolClient(model_config),
        output_dir=local_config.get("schema_output_dir", _DEFAULT_OUTPUT_DIR),
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
            f"delta_avg_reward={comp.delta_avg_reward:.3f}, "
            f"entered_execution_rate={comp.entered_execution_rate:.3f}, "
            f"clean_run_pass_at_1={comp.clean_run_pass_at_1:.3f}, "
            f"verifier_failed_rate={comp.verifier_failed_rate:.3f}"
        )


if __name__ == "__main__":
    main()
