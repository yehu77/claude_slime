from __future__ import annotations

from pathlib import Path

from pycodeagent.agent import resolve_runtime_provider_config
from pycodeagent.dev import resolve_local_config_path
from pycodeagent.eval import run_real_provider_credibility_bundle
from pycodeagent.eval.real_provider_credibility_bundle import (
    DEFAULT_CREDIBILITY_PROFILE_MODES,
    DEFAULT_CREDIBILITY_PROFILE_SEED_BY_MODE,
    DEFAULT_CREDIBILITY_REPEAT_COUNT,
)
from pycodeagent.rl.tokenizer_config import FakeTokenizerConfig


_LOCAL_CONFIG_FILENAME = "real_provider_runtime.local.json"
_REPO_LOCAL_CONFIG_PATH = Path("configs/local/real_provider_runtime.local.json")
_LOCAL_CONFIG_EXAMPLE_PATH = Path("configs/local/real_provider_runtime.local.example.json")
_DEFAULT_TASKS_PATH = Path("datasets/tasks/realistic_runtime_tasks.jsonl")
_DEFAULT_OUTPUT_ROOT = Path("runs/real_provider_credibility_bundle")


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
    result = run_real_provider_credibility_bundle(
        provider_config,
        output_root,
        tasks_path=_DEFAULT_TASKS_PATH,
        profile_modes=list(DEFAULT_CREDIBILITY_PROFILE_MODES),
        profile_seed_by_mode=dict(DEFAULT_CREDIBILITY_PROFILE_SEED_BY_MODE),
        repeat_count=DEFAULT_CREDIBILITY_REPEAT_COUNT,
        fake_tokenizer_config=FakeTokenizerConfig(),
    )

    print(f"output_root={result.output_root}")
    print(f"source_runs_root={result.source_runs_root}")
    print(f"tasks_path={result.tasks_path}")
    print(f"profile_modes={result.profile_modes}")
    print(f"profile_seed_by_mode={result.profile_seed_by_mode}")
    print(f"repeat_count={result.repeat_count}")
    print(f"provider={result.provider}")
    print(f"contract_ok={result.contract_ok}")
    print(f"runtime_behavior_audit={result.runtime_behavior_audit_path}")
    print(f"behavior_baseline_summary={result.behavior_baseline_summary_path}")
    print(f"failure_buckets={result.failure_buckets_path}")
    print(f"runtime_observed_bundle={result.runtime_observed_bundle_path}")
    print(f"runtime_execution_reconciliation={result.runtime_execution_reconciliation_path}")
    print(f"credibility_summary={result.credibility_summary_path}")
    print(f"credibility_manifest={result.credibility_manifest_path}")
    print(f"credibility_gates={result.credibility_gates_path}")


if __name__ == "__main__":
    main()
