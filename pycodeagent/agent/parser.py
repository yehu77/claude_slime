"""Text-mode output parser.

Parses assistant responses that contain:
- Optional <assistant>...</assistant> text
- Zero or more tool calls in canonical `` blocks
- Compatibility tool calls in <tool_call>...</tool_call> blocks

Canonical example:

<assistant>
I will inspect the repository first.
</assistant>
<|tool|>
{"id":"call_1","name":"list_files","arguments":{"path":"."}}
<|end|>

Compatibility example observed from some models:

<tool_call>
{"name":"read_file","arguments":{"path":"foo.py"}}
</tool_call>
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

from pycodeagent.trajectory.schema import ToolCall


class ParseResult(BaseModel):
    """Result of parsing an assistant text response.

    Always returns a structured result — never raises on parse failure.
    Parse errors are recorded for trajectory logging and stopping decisions.
    """

    ok: bool
    assistant_content: str = ""
    tool_calls: list[ToolCall] = []
    parse_errors: list[str] = []

    @property
    def has_tool_calls(self) -> bool:
        """Check if any tool calls were successfully parsed."""
        return len(self.tool_calls) > 0

    @property
    def has_parse_errors(self) -> bool:
        """Check if any parse errors occurred."""
        return len(self.parse_errors) > 0


# Regex patterns for parsing
_ASSISTANT_PATTERN = re.compile(
    r"<assistant>(.*?)</assistant>",
    re.DOTALL,
)
_TOOL_PATTERN = re.compile(
    r"<\|tool\|>(.*?)<\|end\|>",
    re.DOTALL,
)
_COMPAT_TOOL_PATTERN = re.compile(
    r"<tool_call>(.*?)</tool_call>",
    re.DOTALL,
)
_COMPAT_TOOL_NAME_PATTERN = re.compile(r"<tool_name>(.*?)</tool_name>", re.DOTALL)
_COMPAT_ARGUMENTS_PATTERN = re.compile(r"<arguments>(.*?)</arguments>", re.DOTALL)
_TOOL_RESULT_PATTERN = re.compile(
    r"<tool_result>.*?</tool_result>",
    re.DOTALL,
)


def parse_assistant_response(text: str) -> ParseResult:
    """Parse a text-mode assistant response.

    Extracts:
    1. Content from <assistant>...</assistant> tags (if present)
    2. Tool calls from `` blocks containing JSON

    Args:
        text: Raw text output from the LLM.

    Returns:
        ParseResult with assistant content, tool calls, and any errors.
    """
    assistant_content = ""
    tool_calls: list[ToolCall] = []
    parse_errors: list[str] = []

    # Check for malformed tags (unclosed tags)
    _check_malformed_tags(text, parse_errors)

    # Extract assistant text content
    assistant_match = _ASSISTANT_PATTERN.search(text)
    if assistant_match:
        assistant_content = assistant_match.group(1).strip()
    else:
        has_any_tool_blocks = bool(_TOOL_PATTERN.search(text) or _COMPAT_TOOL_PATTERN.search(text))
        if not has_any_tool_blocks:
            # If no <assistant> tags, treat entire text as assistant content
            assistant_content = text.strip()
        else:
            # Compatibility path: strip tool/tool_result blocks and keep any
            # remaining free-form assistant text outside them.
            stripped = _TOOL_PATTERN.sub("", text)
            stripped = _COMPAT_TOOL_PATTERN.sub("", stripped)
            stripped = _TOOL_RESULT_PATTERN.sub("", stripped)
            assistant_content = stripped.strip()

    # Extract and parse canonical tool calls
    for match in _TOOL_PATTERN.finditer(text):
        tool_json = match.group(1).strip()
        if not tool_json:
            parse_errors.append("Empty tool call block")
            continue

        try:
            tool_data = json.loads(tool_json)
        except json.JSONDecodeError as e:
            parse_errors.append(f"Invalid JSON in tool call: {e}")
            continue

        # Validate required fields
        if not isinstance(tool_data, dict):
            parse_errors.append(f"Tool call must be a JSON object, got {type(tool_data).__name__}")
            continue

        tool_id = tool_data.get("id")
        tool_name = tool_data.get("name")
        tool_args = tool_data.get("arguments")

        if tool_id is None:
            parse_errors.append("Tool call missing required field 'id'")
            continue
        if tool_name is None:
            parse_errors.append("Tool call missing required field 'name'")
            continue
        if tool_args is None:
            parse_errors.append("Tool call missing required field 'arguments'")
            continue

        if not isinstance(tool_args, dict):
            parse_errors.append(f"Tool call 'arguments' must be an object, got {type(tool_args).__name__}")
            continue

        tool_calls.append(
            ToolCall(
                id=str(tool_id),
                name=str(tool_name),
                arguments=tool_args,
            )
        )

    # Extract and parse compatibility tool calls. Some models emit
    # <tool_call>...</tool_call> blocks without explicit ids and also invent
    # <tool_result> text inline. We accept the tool-call block and synthesize
    # a stable per-response id when needed; <tool_result> blocks are ignored.
    compat_index = 0
    for match in _COMPAT_TOOL_PATTERN.finditer(text):
        tool_block = match.group(1).strip()
        if not tool_block:
            parse_errors.append("Empty compatibility tool call block")
            continue

        try:
            tool_data = _extract_compat_tool_data(tool_block)
        except json.JSONDecodeError as e:
            parse_errors.append(f"Invalid JSON in compatibility tool call: {e}")
            continue

        if not isinstance(tool_data, dict):
            parse_errors.append(
                f"Compatibility tool call must be a JSON object, got {type(tool_data).__name__}"
            )
            continue

        tool_name = tool_data.get("name")
        tool_args = tool_data.get("arguments")

        if tool_name is None:
            parse_errors.append("Compatibility tool call missing required field 'name'")
            continue
        if tool_args is None:
            parse_errors.append("Compatibility tool call missing required field 'arguments'")
            continue
        if not isinstance(tool_args, dict):
            parse_errors.append(
                f"Compatibility tool call 'arguments' must be an object, got {type(tool_args).__name__}"
            )
            continue

        tool_id = tool_data.get("id")
        if tool_id is None:
            compat_index += 1
            tool_id = f"compat_call_{compat_index}"

        tool_calls.append(
            ToolCall(
                id=str(tool_id),
                name=str(tool_name),
                arguments=tool_args,
            )
        )

    ok = len(parse_errors) == 0
    return ParseResult(
        ok=ok,
        assistant_content=assistant_content,
        tool_calls=tool_calls,
        parse_errors=parse_errors,
    )


def _check_malformed_tags(text: str, parse_errors: list[str]) -> None:
    """Check for unclosed/malformed tags and add errors.

    Checks for:
    - <assistant> without </assistant>
    - <|tool|> without <|end|>

    Args:
        text: The text to check.
        parse_errors: List to append error messages to.
    """
    # Check for unclosed <assistant> tag
    assistant_start = text.find("<assistant>")
    if assistant_start != -1:
        assistant_end = text.find("</assistant>")
        if assistant_end == -1:
            parse_errors.append("Unclosed <assistant> tag: missing </assistant>")

    # Check for unclosed <|tool|> block
    tool_start = text.find("<|tool|>")
    if tool_start != -1:
        # Find all <|tool|> and <|end|> occurrences
        tool_starts = []
        tool_ends = []
        pos = 0
        while True:
            idx = text.find("<|tool|>", pos)
            if idx == -1:
                break
            tool_starts.append(idx)
            pos = idx + 1

        pos = 0
        while True:
            idx = text.find("<|end|>", pos)
            if idx == -1:
                break
            tool_ends.append(idx)
            pos = idx + 1

        # If there are more <|tool|> than <|end|>, we have unclosed blocks
        if len(tool_starts) > len(tool_ends):
            parse_errors.append(
                f"Unclosed tool block: {len(tool_starts)} <|tool|> tags but only {len(tool_ends)} <|end|> tags"
            )

    # Check for unclosed <tool_call> compatibility block
    compat_start = text.find("<tool_call>")
    if compat_start != -1:
        compat_starts = []
        compat_ends = []
        pos = 0
        while True:
            idx = text.find("<tool_call>", pos)
            if idx == -1:
                break
            compat_starts.append(idx)
            pos = idx + 1

        pos = 0
        while True:
            idx = text.find("</tool_call>", pos)
            if idx == -1:
                break
            compat_ends.append(idx)
            pos = idx + 1

        if len(compat_starts) > len(compat_ends):
            parse_errors.append(
                f"Unclosed compatibility tool block: {len(compat_starts)} <tool_call> tags but only {len(compat_ends)} </tool_call> tags"
            )


def _extract_first_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object embedded anywhere in a text block."""
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        candidate = text[idx:]
        try:
            value, _ = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise json.JSONDecodeError("No JSON object found", text, 0)


def _extract_compat_tool_data(text: str) -> dict[str, Any]:
    """Extract compatibility tool-call payload from several observed formats."""
    tool_name_match = _COMPAT_TOOL_NAME_PATTERN.search(text)
    arguments_match = _COMPAT_ARGUMENTS_PATTERN.search(text)
    if tool_name_match and arguments_match:
        arguments = _extract_first_json_object(arguments_match.group(1).strip())
        return {
            "name": tool_name_match.group(1).strip(),
            "arguments": arguments,
        }

    return _extract_first_json_object(text)


def format_tool_call_for_display(call: ToolCall) -> str:
    """Format a tool call for display in logs or debugging.

    Args:
        call: The tool call to format.

    Returns:
        A human-readable string representation.
    """
    args_str = ", ".join(f"{k}={v!r}" for k, v in call.arguments.items())
    return f"{call.name}({args_str})"
