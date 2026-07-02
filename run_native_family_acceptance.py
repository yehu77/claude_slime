from __future__ import annotations

import argparse
from pathlib import Path

from pycodeagent.agent import resolve_runtime_provider_config
from pycodeagent.dev import resolve_local_config_path
from pycodeagent.eval.native_family_acceptance import run_native_family_acceptance


_LOCAL_CONFIG_FILENAME = "real_provider_runtime.local.json"
_REPO_LOCAL_CONFIG_PATH = Path("configs/local/real_provider_runtime.local.json")
_LOCAL_CONFIG_EXAMPLE_PATH = Path("configs/local/real_provider_runtime.local.example.json")
_DEFAULT_OUTPUT_ROOT = Path("runs/native_family_acceptance")


def _resolve_provider_config(path: Path | None = None):
    if path is not None:
        return resolve_runtime_provider_config(
            path,
            example_path=_LOCAL_CONFIG_EXAMPLE_PATH,
        )
    resolved_path = resolve_local_config_path(
        _LOCAL_CONFIG_FILENAME,
        repo_fallback=_REPO_LOCAL_CONFIG_PATH,
    )
    return resolve_runtime_provider_config(
        resolved_path,
        example_path=_LOCAL_CONFIG_EXAMPLE_PATH,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the native-family acceptance and regression pack.",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Skip the real-provider Claude mini acceptance and run local-only acceptance.",
    )
    parser.add_argument(
        "--provider-config",
        type=Path,
        default=None,
        help="Optional explicit provider config JSON path for the real-provider run.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=_DEFAULT_OUTPUT_ROOT,
        help="Base output directory for acceptance artifacts.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    provider_config = None
    if not args.local_only:
        provider_config = _resolve_provider_config(args.provider_config)
        output_root = args.output_root / (
            f"{provider_config.client_mode}__{provider_config.model}"
        )
    else:
        output_root = args.output_root / "local_only"

    report = run_native_family_acceptance(
        output_root,
        provider_config=provider_config,
        include_real_provider=not args.local_only,
    )

    print(f"output_root={report.output_root}")
    print(f"stabilized={report.stabilized}")
    print(f"provider={report.provider}")
    print(f"regression_commands={len(report.regression_commands)}")
    print(f"real_provider_tasks={len(report.real_provider_tasks)}")
    print(f"native_codex_tasks={len(report.native_codex_tasks)}")
    print(f"generation_smokes={len(report.generation_smokes)}")
    print(
        "report_path="
        f"{Path(report.output_root) / 'native_family_acceptance_report.json'}"
    )


if __name__ == "__main__":
    main()
