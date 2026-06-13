"""Built-in canonical tools for the coding agent runtime."""

from pycodeagent.tools.builtin.bash import run_command_tool
from pycodeagent.tools.builtin.file_ops import (
    create_file_tool,
    list_files_tool,
    read_file_tool,
    write_file_tool,
)
from pycodeagent.tools.builtin.finish import finish_tool
from pycodeagent.tools.builtin.patch import apply_patch_tool
from pycodeagent.tools.builtin.python_run import python_run_tool
from pycodeagent.tools.builtin.search import search_code_tool

ALL_BUILTIN_TOOLS = [
    list_files_tool,
    read_file_tool,
    write_file_tool,
    create_file_tool,
    search_code_tool,
    apply_patch_tool,
    run_command_tool,
    python_run_tool,
    finish_tool,
]

__all__ = [
    "ALL_BUILTIN_TOOLS",
    "list_files_tool",
    "read_file_tool",
    "write_file_tool",
    "create_file_tool",
    "search_code_tool",
    "apply_patch_tool",
    "run_command_tool",
    "python_run_tool",
    "finish_tool",
]
