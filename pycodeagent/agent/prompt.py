"""Prompt construction for text-mode agent execution."""

from __future__ import annotations

from typing import Any


SYSTEM_PROMPT = """You are a coding agent working inside a repository workspace.

The available tools are listed in the user message inside a <tools> block.
Use only the exact tool names and argument shapes shown there.

Tool-use output contract:
1. If you want to call a tool, emit one or more blocks in exactly this format:
<|tool|>
{"id":"call_1","name":"tool_name","arguments":{"key":"value"}}
<|end|>
2. Do not output <tool_result> blocks. Tool results are produced only by the environment.
3. Do not pretend a tool already ran. If you need file contents, patches, or command output, call the tool and wait.
4. If you include normal assistant text, put it inside <assistant>...</assistant>.
"""


def build_system_message() -> dict[str, Any]:
    """Build the system message for the conversation."""
    return {"role": "system", "content": SYSTEM_PROMPT}


def build_user_task_message(task_prompt: str) -> dict[str, Any]:
    """Build the user message containing the task description.

    Args:
        task_prompt: The task description from CodingTask.prompt.

    Returns:
        A message dict with role='user' and the task content.
    """
    return {"role": "user", "content": task_prompt}


def build_tool_specs_section(tool_specs: list[dict[str, Any]]) -> str:
    """Build a text representation of available tools.

    This is appended to the prompt in text mode so the model knows what
    tools are available and their schemas.

    Args:
        tool_specs: Output from ToolProfile.get_exposed_specs().

    Returns:
        A formatted string describing available tools.
    """
    lines = ["<tools>"]
    for spec in tool_specs:
        name = spec.get("name", "unknown")
        desc = spec.get("description", "")
        schema = spec.get("input_schema", {})
        lines.append(f"  {name}: {desc}")
        if schema.get("properties"):
            props = schema["properties"]
            required = set(schema.get("required", []))
            for prop_name, prop_spec in props.items():
                prop_type = prop_spec.get("type", "any")
                prop_desc = prop_spec.get("description", "")
                req_marker = " (required)" if prop_name in required else ""
                lines.append(f"    - {prop_name}: {prop_type}{req_marker} - {prop_desc}")
    lines.append("</tools>")
    return "\n".join(lines)


def build_initial_messages(
    task_prompt: str,
    tool_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the initial message list for a new task.

    Args:
        task_prompt: The task description.
        tool_specs: Available tool definitions.

    Returns:
        A list of message dicts: [system, user_with_tools]
    """
    tool_section = build_tool_specs_section(tool_specs)
    user_content = (
        f"{task_prompt}\n\n"
        "Use only the exact tool names and argument shapes listed below.\n\n"
        f"{tool_section}"
    )
    return [
        build_system_message(),
        {"role": "user", "content": user_content},
    ]


def format_history_for_prompt(messages: list[dict[str, Any]]) -> str:
    """Format conversation history for inclusion in a prompt.

    This is used when the LLM doesn't natively support message history,
    requiring us to flatten it into the prompt.

    Args:
        messages: List of message dicts from the conversation.

    Returns:
        A formatted string representation of the history.
    """
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if role == "system":
            parts.append(f"<system>\n{content}\n</system>")
        elif role == "user":
            parts.append(f"<user>\n{content}\n</user>")
        elif role == "assistant":
            parts.append(f"<assistant>\n{content}\n</assistant>")
        elif role == "tool":
            tool_name = msg.get("tool_name", "tool")
            parts.append(f"<tool name=\"{tool_name}\">\n{content}\n</tool>")
    return "\n".join(parts)
