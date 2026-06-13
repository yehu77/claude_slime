"""Shared command parsing helpers for verifier and controlled tool execution."""

from __future__ import annotations

import os
import shlex
from collections.abc import Sequence

_SHELL_CONTROL_TOKENS = {
    "&",
    "&&",
    ";",
    "|",
    "||",
    "<",
    "<<",
    ">",
    ">>",
    "1>",
    "1>>",
    "2>",
    "2>>",
}


def parse_command_argv(
    command: str | Sequence[str],
    *,
    field_name: str,
) -> list[str]:
    """Normalize a command into argv without invoking a shell.

    String commands are parsed with shell-like quoting but must not contain
    shell control operators. For complex commands, callers should pass an
    explicit argv list instead of relying on shell syntax.
    """
    if isinstance(command, str):
        stripped = command.strip()
        if not stripped:
            raise ValueError(f"{field_name} must not be empty")

        try:
            argv = shlex.split(stripped, posix=os.name != "nt")
        except ValueError as exc:
            raise ValueError(f"Invalid {field_name}: {exc}") from exc

        _validate_string_command_tokens(argv, field_name=field_name)
        return argv

    if not isinstance(command, Sequence) or isinstance(command, (bytes, bytearray)):
        raise ValueError(
            f"{field_name} must be a string or sequence of strings, got {type(command).__name__}"
        )

    argv = list(command)
    if not argv:
        raise ValueError(f"{field_name} must not be empty")

    for index, token in enumerate(argv):
        if not isinstance(token, str) or not token:
            raise ValueError(
                f"{field_name}[{index}] must be a non-empty string, got {token!r}"
            )

    return argv


def _validate_string_command_tokens(argv: list[str], *, field_name: str) -> None:
    """Reject shell control syntax in string-form commands."""
    for token in argv:
        if token in _SHELL_CONTROL_TOKENS:
            raise ValueError(
                f"{field_name} uses unsupported shell syntax: {token!r}. "
                "Pass an argv list for complex commands."
            )
        if token.startswith("$("):
            raise ValueError(
                f"{field_name} uses unsupported command substitution: {token!r}"
            )
        if "`" in token:
            raise ValueError(
                f"{field_name} uses unsupported shell syntax: backticks are not allowed"
            )
