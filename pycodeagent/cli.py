"""Formal, machine-readable command-line interface for pycodeagent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from pycodeagent.application import cli_services


CLI_CONFIG_SCHEMA = "pycodeagent-cli-config/v1"
CLI_RESULT_SCHEMA = "pycodeagent-cli-result/v1"
CLI_ERROR_SCHEMA = "pycodeagent-cli-error/v1"
CLI_VERSION = 1

EXIT_OK = 0
EXIT_CONTRACT_FAILED = 1
EXIT_USAGE = 2
EXIT_INPUT = 3
EXIT_APPLICATION = 4
EXIT_INTERRUPTED = 130

_DEFAULT_TASKS = "datasets/tasks/realistic_runtime_tasks.jsonl"


class CliUsageError(ValueError):
    """Raised for parse, config, or option-contract errors."""


class _MachineArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliUsageError(message)


_DEFAULTS: dict[str, dict[str, Any]] = {
    "run": {
        "tasks": _DEFAULT_TASKS,
        "family": "native_claude",
        "profile_mode": "base",
        "profile_seed": 0,
    },
    "campaign": {
        "tasks": _DEFAULT_TASKS,
        "family": "native_claude",
        "prepare_training_input": True,
        "max_length": 2048,
        "fake_tokenizer": False,
        "fake_vocab_size": 1000,
        "fake_chars_per_token": 4,
    },
    "export": {
        "source_type": "batch",
        "include_failed": False,
        "seed": 42,
    },
    "prep": {
        "source_type": "batch",
        "include_failed": False,
        "verifier_passed": "any",
        "max_length": 2048,
        "batch_size": 8,
        "learning_rate": 1e-4,
        "max_steps": 1000,
        "seed": 42,
        "run_id": "slime_contract_train",
        "fake_tokenizer": False,
        "fake_vocab_size": 1000,
        "fake_chars_per_token": 4,
    },
    "verify": {
        "source_type": "batch",
        "include_failed": False,
        "max_length": 2048,
        "fake_tokenizer": False,
        "fake_vocab_size": 1000,
        "fake_chars_per_token": 4,
    },
    "acceptance": {
        "local_only": False,
        "output_root": "runs/native_family_acceptance",
    },
}

_REQUIRED: dict[str, set[str]] = {
    "run": {"task_id", "output_root"},
    "campaign": {"kind", "output_root"},
    "export": {"source_dir", "output_dir"},
    "prep": {"source_dir", "output_dir"},
    "verify": {"source_dir", "output_dir"},
    "acceptance": set(),
}

_EXTRA_ALLOWED: dict[str, set[str]] = {
    "run": {"provider_config"},
    "campaign": {
        "provider_config",
        "tokenizer_name",
        "profile_modes",
        "profile_seed_by_mode",
        "repeat_count",
    },
    "export": set(),
    "prep": {"tokenizer_name"},
    "verify": {"tokenizer_name"},
    "acceptance": {"provider_config"},
}

_SERVICES = {
    "run": cli_services.run_service,
    "campaign": cli_services.campaign_service,
    "export": cli_services.export_service,
    "prep": cli_services.prep_service,
    "verify": cli_services.verify_service,
    "acceptance": cli_services.acceptance_service,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = _MachineArgumentParser(
        prog="python -m pycodeagent",
        description=(
            "Run stable pycodeagent application services with versioned JSON output."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=argparse.SUPPRESS,
        help=(
            "Versioned command config JSON. Place before the subcommand; "
            "explicit CLI options override config arguments."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Run one task through the local runtime.")
    _add_path_option(run, "--tasks")
    run.add_argument("--task-id", default=argparse.SUPPRESS)
    _add_path_option(run, "--output-root")
    _add_path_option(run, "--provider-config")
    _add_family(run)
    run.add_argument("--profile-mode", default=argparse.SUPPRESS)
    run.add_argument("--profile-seed", type=int, default=argparse.SUPPRESS)

    campaign = commands.add_parser(
        "campaign",
        help="Run an active behavior, credibility, or ToolView campaign.",
    )
    campaign.add_argument(
        "--kind",
        choices=["behavior", "credibility", "toolview"],
        default=argparse.SUPPRESS,
    )
    _add_path_option(campaign, "--tasks")
    _add_path_option(campaign, "--output-root")
    _add_path_option(campaign, "--provider-config")
    _add_family(campaign)
    campaign.add_argument(
        "--profile-modes",
        type=_comma_list,
        default=argparse.SUPPRESS,
        metavar="MODE[,MODE...]",
    )
    campaign.add_argument(
        "--profile-seeds",
        dest="profile_seed_by_mode",
        type=_json_object,
        default=argparse.SUPPRESS,
        metavar='\'{"base":0}\'',
    )
    campaign.add_argument("--repeat-count", type=int, default=argparse.SUPPRESS)
    campaign.add_argument(
        "--prepare-training-input",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
    )
    _add_tokenizer_options(campaign)

    export = commands.add_parser(
        "export",
        help="Export runtime-observed ToolView samples.",
    )
    _add_path_option(export, "--source-dir")
    _add_path_option(export, "--output-dir")
    _add_source_type(export)
    export.add_argument(
        "--include-failed",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
    )
    export.add_argument("--seed", type=int, default=argparse.SUPPRESS)

    prep = commands.add_parser(
        "prep",
        help="Build the canonical slime-compatible training bundle.",
    )
    _add_path_option(prep, "--source-dir")
    _add_path_option(prep, "--output-dir")
    _add_source_type(prep)
    prep.add_argument(
        "--include-failed",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
    )
    prep.add_argument(
        "--verifier-passed",
        choices=["true", "false", "any"],
        default=argparse.SUPPRESS,
    )
    _add_training_options(prep)
    _add_tokenizer_options(prep)

    verify = commands.add_parser(
        "verify",
        help="Verify source runs against the slime contract.",
    )
    _add_path_option(verify, "--source-dir")
    _add_path_option(verify, "--output-dir")
    _add_source_type(verify)
    verify.add_argument(
        "--include-failed",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
    )
    verify.add_argument("--max-length", type=int, default=argparse.SUPPRESS)
    _add_tokenizer_options(verify)

    acceptance = commands.add_parser(
        "acceptance",
        help="Run native-family acceptance and regression.",
    )
    acceptance.add_argument(
        "--local-only",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
    )
    _add_path_option(acceptance, "--provider-config")
    _add_path_option(acceptance, "--output-root")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse, merge, dispatch, and emit one machine-readable result."""

    command: str | None = None
    try:
        namespace = _build_parser().parse_args(argv)
        explicit = vars(namespace)
        command = str(explicit.pop("command"))
        config_path = explicit.pop("config", None)
        options = _merge_options(
            command,
            explicit,
            _load_config(config_path, command) if config_path else {},
        )
        result = _SERVICES[command](options)
        exit_code = EXIT_OK if result.ok else EXIT_CONTRACT_FAILED
        _emit(
            {
                "schema": CLI_RESULT_SCHEMA,
                "version": CLI_VERSION,
                "command": command,
                "ok": result.ok,
                "exit_code": exit_code,
                "manifest_path": result.manifest_path,
                "result": result.model_dump(mode="json"),
            },
            stream=sys.stdout,
        )
        return exit_code
    except CliUsageError as exc:
        return _emit_error(command, EXIT_USAGE, "usage_error", exc)
    except (FileNotFoundError, json.JSONDecodeError, ValidationError) as exc:
        return _emit_error(command, EXIT_INPUT, "input_error", exc)
    except KeyboardInterrupt as exc:
        return _emit_error(command, EXIT_INTERRUPTED, "interrupted", exc)
    except Exception as exc:
        return _emit_error(command, EXIT_APPLICATION, "application_error", exc)


def _merge_options(
    command: str,
    explicit: Mapping[str, Any],
    configured: Mapping[str, Any],
) -> dict[str, Any]:
    if command not in _DEFAULTS:
        raise CliUsageError(f"Unknown command: {command}")
    allowed = (
        set(_DEFAULTS[command])
        | _REQUIRED[command]
        | _EXTRA_ALLOWED[command]
    )
    unknown = sorted(set(configured) - allowed)
    if unknown:
        raise CliUsageError(
            "Unknown config arguments for "
            f"{command}: {', '.join(unknown)}"
        )
    options = {
        **_DEFAULTS[command],
        **dict(configured),
        **dict(explicit),
    }
    missing = sorted(
        key
        for key in _REQUIRED[command]
        if options.get(key) in {None, ""}
    )
    if missing:
        raise CliUsageError(
            f"Missing required arguments for {command}: {', '.join(missing)}"
        )
    _validate_option_types(command, options)
    _validate_enums(command, options)
    if command == "campaign":
        _normalize_campaign_options(options)
    if command in {"prep", "verify"} or (
        command == "campaign"
        and (
            options["kind"] == "credibility"
            or (
                options["kind"] == "toolview"
                and bool(options["prepare_training_input"])
            )
        )
    ):
        _validate_tokenizer_choice(options)
    return options


def _validate_option_types(command: str, options: Mapping[str, Any]) -> None:
    integer_fields = {
        "profile_seed",
        "repeat_count",
        "seed",
        "max_length",
        "batch_size",
        "max_steps",
        "fake_vocab_size",
        "fake_chars_per_token",
    }
    boolean_fields = {
        "local_only",
        "include_failed",
        "prepare_training_input",
        "fake_tokenizer",
    }
    for field in sorted(integer_fields & set(options)):
        if type(options[field]) is not int:
            raise CliUsageError(f"{field} must be an integer")
    for field in sorted(boolean_fields & set(options)):
        if type(options[field]) is not bool:
            raise CliUsageError(f"{field} must be a boolean")
    if "learning_rate" in options and (
        isinstance(options["learning_rate"], bool)
        or not isinstance(options["learning_rate"], (int, float))
    ):
        raise CliUsageError("learning_rate must be a number")
    if command == "campaign" and "profile_modes" in options:
        if (
            not isinstance(options["profile_modes"], list)
            or not all(
                isinstance(mode, str) and mode
                for mode in options["profile_modes"]
            )
        ):
            raise CliUsageError("profile_modes must be a non-empty string array")
    if "profile_seed_by_mode" in options and not isinstance(
        options["profile_seed_by_mode"],
        Mapping,
    ):
        raise CliUsageError("profile_seed_by_mode must be an object")
    if "profile_seed_by_mode" in options and not all(
        isinstance(mode, str) and mode and type(seed) is int
        for mode, seed in options["profile_seed_by_mode"].items()
    ):
        raise CliUsageError(
            "profile_seed_by_mode must map non-empty strings to integers"
        )


def _load_config(path: str | Path, command: str) -> dict[str, Any]:
    config_path = Path(path)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CliUsageError(f"Invalid CLI config JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise CliUsageError("CLI config must be a JSON object")
    if payload.get("schema") != CLI_CONFIG_SCHEMA:
        raise CliUsageError(
            f"CLI config schema must be {CLI_CONFIG_SCHEMA!r}"
        )
    if payload.get("command") != command:
        raise CliUsageError(
            "CLI config command does not match the selected subcommand"
        )
    arguments = payload.get("arguments")
    if not isinstance(arguments, dict):
        raise CliUsageError("CLI config arguments must be an object")
    return dict(arguments)


def _normalize_campaign_options(options: dict[str, Any]) -> None:
    modes, seeds, repeat_count = cli_services.campaign_defaults(
        str(options["kind"])
    )
    if "profile_modes" not in options:
        options["profile_modes"] = modes
    else:
        options["profile_modes"] = [
            str(mode) for mode in options["profile_modes"]
        ]
    if not options["profile_modes"]:
        raise CliUsageError("campaign profile_modes cannot be empty")
    configured_seeds = options.get("profile_seed_by_mode")
    if configured_seeds is None:
        configured_seeds = seeds
    if not isinstance(configured_seeds, Mapping):
        raise CliUsageError("profile_seed_by_mode must be an object")
    normalized_seeds = {
        str(mode): int(configured_seeds.get(mode, seeds.get(mode, 0)))
        for mode in options["profile_modes"]
    }
    extras = sorted(set(configured_seeds) - set(options["profile_modes"]))
    if extras:
        raise CliUsageError(
            "profile seeds reference unselected modes: " + ", ".join(extras)
        )
    if any(seed < 0 for seed in normalized_seeds.values()):
        raise CliUsageError("profile seeds must be non-negative")
    options["profile_seed_by_mode"] = normalized_seeds
    options.setdefault("repeat_count", repeat_count)
    if int(options["repeat_count"]) < 1:
        raise CliUsageError("repeat_count must be positive")


def _validate_enums(command: str, options: Mapping[str, Any]) -> None:
    if "source_type" in options and options["source_type"] not in {
        "study",
        "experiment",
        "batch",
    }:
        raise CliUsageError(f"Invalid source_type: {options['source_type']!r}")
    if "family" in options and options["family"] not in {
        "native_claude",
        "native_codex",
    }:
        raise CliUsageError(f"Invalid family: {options['family']!r}")
    if command == "campaign" and options.get("kind") not in {
        "behavior",
        "credibility",
        "toolview",
    }:
        raise CliUsageError(f"Invalid campaign kind: {options.get('kind')!r}")
    if options.get("verifier_passed", "any") not in {
        "true",
        "false",
        "any",
    }:
        raise CliUsageError("verifier_passed must be true, false, or any")


def _validate_tokenizer_choice(options: Mapping[str, Any]) -> None:
    tokenizer_name = options.get("tokenizer_name")
    fake_tokenizer = bool(options.get("fake_tokenizer"))
    if bool(tokenizer_name) == fake_tokenizer:
        raise CliUsageError(
            "Choose exactly one of --tokenizer-name or --fake-tokenizer"
        )


def _add_path_option(parser: argparse.ArgumentParser, name: str) -> None:
    parser.add_argument(name, type=Path, default=argparse.SUPPRESS)


def _add_family(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--family",
        choices=["native_claude", "native_codex"],
        default=argparse.SUPPRESS,
    )


def _add_source_type(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source-type",
        choices=["study", "experiment", "batch"],
        default=argparse.SUPPRESS,
    )


def _add_training_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-length", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--batch-size", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--learning-rate", type=float, default=argparse.SUPPRESS)
    parser.add_argument("--max-steps", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--seed", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--run-id", default=argparse.SUPPRESS)


def _add_tokenizer_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tokenizer-name", default=argparse.SUPPRESS)
    parser.add_argument(
        "--fake-tokenizer",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--fake-vocab-size",
        type=int,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--fake-chars-per-token",
        type=int,
        default=argparse.SUPPRESS,
    )


def _comma_list(value: str) -> list[str]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("expected at least one mode")
    return values


def _json_object(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError("expected a JSON object")
    return payload


def _emit_error(
    command: str | None,
    exit_code: int,
    kind: str,
    error: BaseException,
) -> int:
    _emit(
        {
            "schema": CLI_ERROR_SCHEMA,
            "version": CLI_VERSION,
            "command": command,
            "ok": False,
            "exit_code": exit_code,
            "error": {
                "kind": kind,
                "type": type(error).__name__,
                "message": str(error),
            },
        },
        stream=sys.stderr,
    )
    return exit_code


def _emit(payload: Mapping[str, Any], *, stream: Any) -> None:
    stream.write(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
