from __future__ import annotations

from pathlib import Path

from pycodeagent.agent import resolve_runtime_provider_config
from pycodeagent.dev import resolve_local_config_path
from pycodeagent.eval.toolview_mutation_data_generation import (
    DEFAULT_MUTATION_DATA_PROFILE_MODES,
    DEFAULT_MUTATION_DATA_PROFILE_SEED_BY_MODE,
    DEFAULT_MUTATION_DATA_REPEAT_COUNT,
    run_real_provider_toolview_mutation_data_generation,
)
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig


_LOCAL_CONFIG_FILENAME = "real_provider_runtime.local.json"
_REPO_LOCAL_CONFIG_PATH = Path("configs/local/real_provider_runtime.local.json")
_LOCAL_CONFIG_EXAMPLE_PATH = Path("configs/local/real_provider_runtime.local.example.json")
_DEFAULT_TASKS_PATH = Path("datasets/tasks/realistic_runtime_tasks.jsonl")
_DEFAULT_OUTPUT_ROOT = Path("runs/toolview_mutation_data_generation")


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
    result = run_real_provider_toolview_mutation_data_generation(
        provider_config,
        output_root,
        tasks_path=_DEFAULT_TASKS_PATH,
        profile_modes=list(DEFAULT_MUTATION_DATA_PROFILE_MODES),
        profile_seed_by_mode=dict(DEFAULT_MUTATION_DATA_PROFILE_SEED_BY_MODE),
        repeat_count=DEFAULT_MUTATION_DATA_REPEAT_COUNT,
        prepare_training_input=True,
        fake_tokenizer_config=FakeTokenizerConfig(),
    )

    print(f"output_root={result.output_root}")
    print(f"source_runs_root={result.source_runs_root}")
    print(f"raw_dataset_dir={result.raw_dataset_dir}")
    print(f"prepared_dataset_dir={result.prepared_dataset_dir}")
    print(f"tasks_path={result.tasks_path}")
    print(f"profile_modes={result.profile_modes}")
    print(f"profile_seed_by_mode={result.profile_seed_by_mode}")
    print(f"repeat_count={result.repeat_count}")
    print(f"provider={result.provider}")
    print(f"observed_sample_count={result.observed_sample_count}")
    print(f"training_prep_enabled={result.training_prep_enabled}")
    print(f"training_prep_contract_ok={result.training_prep_contract_ok}")
    print(f"contract_ok={result.contract_ok}")
    print(f"raw_dataset_manifest={result.raw_dataset_manifest_path}")
    print(f"raw_source_manifest={result.raw_source_manifest_path}")
    print(f"training_prep={result.training_prep_path}")
    print(f"acceptance_report={result.acceptance_report_path}")
    print(f"generation_summary={result.generation_summary_path}")
    print(f"generation_manifest={result.generation_manifest_path}")


if __name__ == "__main__":
    main()
