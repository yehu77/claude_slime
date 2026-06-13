"""Tests for ToolRuntime.execute.

Locks the contract for:
- Successful handler execution
- Handler with ctx parameter
- Handler without ctx parameter
- Handler exception → structured error result
- Unknown tool → error result
- Profile/adapter mapping → canonical handler execution
"""

from __future__ import annotations

import pytest

from pycodeagent.tools.builtin.file_ops import write_file_tool
from pycodeagent.tools.builtin.python_run import python_run_tool
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.registry import ToolRegistry
from pycodeagent.tools.runtime import ToolRuntime
from pycodeagent.tools.spec import (
    CanonicalTool,
    ToolAdapter,
    ToolProfile,
    ToolView,
)
from pycodeagent.trajectory.schema import ToolCall
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


# --- Test handlers ---


def _handler_read_file(path: str, **kwargs) -> str:
    """Simple handler without ctx."""
    return f"content of {path}"


def _handler_with_ctx(path: str, *, ctx=None, **kwargs) -> str:
    """Handler that accepts ctx."""
    return f"ctx={ctx is not None}, path={path}"


def _handler_failing(path: str, **kwargs):
    """Handler that always raises."""
    raise RuntimeError("Something went wrong")


def _handler_returns_tool_result(**kwargs):
    """Handler that returns a ToolResult directly."""
    from pycodeagent.trajectory.schema import ToolResult
    return ToolResult(ok=True, content="direct result", metadata={"custom": True})


# --- Fixtures ---


def _make_registry_with_read_file() -> ToolRegistry:
    """Create a registry with a read_file canonical tool."""
    registry = ToolRegistry()
    registry.register(CanonicalTool(
        canonical_name="read_file",
        canonical_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        handler=_handler_read_file,
    ))
    return registry


def _make_base_profile() -> ToolProfile:
    """Create a base profile where exposed_name == canonical_name."""
    return ToolProfile(
        profile_id="base",
        tools=[
            ToolView(
                canonical_name="read_file",
                exposed_name="read_file",
                description="Read a file.",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
        ],
        adapters={},
    )


def _make_remapped_profile() -> ToolProfile:
    """Create a profile where read_file is exposed as open_source with renamed args."""
    return ToolProfile(
        profile_id="remapped",
        tools=[
            ToolView(
                canonical_name="read_file",
                exposed_name="open_source",
                description="Inspect source code.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "target": {"type": "string"},
                    },
                    "required": ["target"],
                },
            ),
        ],
        adapters={
            "open_source": ToolAdapter(
                exposed_to_canonical={"target": "path"},
            ),
        },
    )


# --- Tests ---


class TestToolRuntimeSuccess:
    """Tests for successful handler execution."""

    def test_simple_handler_returns_string(self):
        """Handler returning string should become ToolResult(ok=True, content=...)."""
        runtime = ToolRuntime(_make_registry_with_read_file())
        profile = _make_base_profile()
        call = ToolCall(id="c1", name="read_file", arguments={"path": "main.py"})

        result = runtime.execute(call, profile)

        assert result.ok
        assert not result.is_error
        assert result.content == "content of main.py"

    def test_handler_returning_tool_result(self):
        """Handler returning ToolResult should be passed through."""
        registry = ToolRegistry()
        registry.register(CanonicalTool(
            canonical_name="custom",
            canonical_schema={"type": "object", "properties": {}, "required": []},
            handler=_handler_returns_tool_result,
        ))
        profile = ToolProfile(
            profile_id="test",
            tools=[ToolView(
                canonical_name="custom",
                exposed_name="custom",
                description="Custom tool.",
                input_schema={"type": "object", "properties": {}, "required": []},
            )],
        )
        runtime = ToolRuntime(registry)
        call = ToolCall(id="c1", name="custom", arguments={})

        result = runtime.execute(call, profile)

        assert result.ok
        assert result.content == "direct result"
        assert result.metadata.get("custom") is True


class TestToolRuntimeWithCtx:
    """Tests for handlers that accept ctx."""

    def test_handler_receives_ctx(self):
        """Handler with ctx parameter should receive context."""
        registry = ToolRegistry()
        registry.register(CanonicalTool(
            canonical_name="read_file",
            canonical_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=_handler_with_ctx,
        ))
        profile = _make_base_profile()
        runtime = ToolRuntime(registry)
        call = ToolCall(id="c1", name="read_file", arguments={"path": "test.py"})

        # Without ctx
        result = runtime.execute(call, profile, ctx=None)
        assert result.ok
        assert "ctx=False" in result.content

    def test_handler_receives_ctx_when_provided(self):
        """Handler with ctx should get the context object."""
        from pycodeagent.tools.context import ToolContext
        from pycodeagent.env.task import CodingTask
        from pathlib import Path

        registry = ToolRegistry()
        registry.register(CanonicalTool(
            canonical_name="read_file",
            canonical_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=_handler_with_ctx,
        ))
        profile = _make_base_profile()
        runtime = ToolRuntime(registry)
        call = ToolCall(id="c1", name="read_file", arguments={"path": "test.py"})

        task = CodingTask(task_id="t", repo_path=Path("/tmp/test"), prompt="test")
        ctx = ToolContext(workspace_root=Path("/tmp/test"), task=task)

        result = runtime.execute(call, profile, ctx=ctx)
        assert result.ok
        assert "ctx=True" in result.content

    def test_handler_without_ctx_ignores_context(self):
        """Handler without ctx should not receive context."""
        from pycodeagent.tools.context import ToolContext
        from pycodeagent.env.task import CodingTask
        from pathlib import Path

        runtime = ToolRuntime(_make_registry_with_read_file())
        profile = _make_base_profile()
        call = ToolCall(id="c1", name="read_file", arguments={"path": "test.py"})

        task = CodingTask(task_id="t", repo_path=Path("/tmp/test"), prompt="test")
        ctx = ToolContext(workspace_root=Path("/tmp/test"), task=task)

        # Should not error even though ctx is provided
        result = runtime.execute(call, profile, ctx=ctx)
        assert result.ok
        assert result.content == "content of test.py"


class TestToolRuntimeErrors:
    """Tests for error paths."""

    def test_unknown_tool_returns_error(self):
        """Tool not in profile should return error result."""
        runtime = ToolRuntime(_make_registry_with_read_file())
        profile = _make_base_profile()
        call = ToolCall(id="c1", name="nonexistent", arguments={})

        result = runtime.execute(call, profile)

        assert not result.ok
        assert result.is_error
        assert "not found" in result.content
        assert result.metadata.get("error_type") == "unknown_tool"
        assert result.metadata.get("stage") == "resolve_exposed_call"

    def test_handler_exception_returns_error(self):
        """Handler raising exception should return structured error."""
        registry = ToolRegistry()
        registry.register(CanonicalTool(
            canonical_name="failing",
            canonical_schema={"type": "object", "properties": {}, "required": []},
            handler=_handler_failing,
        ))
        profile = ToolProfile(
            profile_id="test",
            tools=[ToolView(
                canonical_name="failing",
                exposed_name="failing",
                description="Always fails.",
                input_schema={"type": "object", "properties": {}, "required": []},
            )],
        )
        runtime = ToolRuntime(registry)
        call = ToolCall(id="c1", name="failing", arguments={"path": "x"})

        result = runtime.execute(call, profile)

        assert not result.ok
        assert result.is_error
        assert "Something went wrong" in result.content
        assert "Traceback" not in result.content
        assert result.metadata.get("error_type") == "handler_exception"
        assert result.metadata.get("stage") == "invoke_handler"
        assert result.metadata.get("exception_type") == "RuntimeError"

    def test_missing_required_arg_returns_error(self):
        """Missing required argument should return argument mapping error."""
        runtime = ToolRuntime(_make_registry_with_read_file())
        profile = _make_base_profile()
        # Call without required 'path' argument
        call = ToolCall(id="c1", name="read_file", arguments={})

        result = runtime.execute(call, profile)

        assert not result.ok
        assert result.is_error
        assert result.metadata.get("error_type") in {
            "schema_validation",
            "argument_mapping",
        }
        if result.metadata.get("error_type") == "schema_validation":
            assert result.metadata.get("stage") == "validate_exposed_arguments"
        else:
            assert result.metadata.get("stage") == "map_arguments"

    def test_canonical_not_in_registry_returns_error(self):
        """Tool in profile but not in registry should return error."""
        runtime = ToolRuntime(ToolRegistry())  # Empty registry
        profile = _make_base_profile()
        call = ToolCall(id="c1", name="read_file", arguments={"path": "test.py"})

        result = runtime.execute(call, profile)

        assert not result.ok
        assert result.is_error
        assert result.metadata.get("error_type") == "canonical_tool_lookup"
        assert result.metadata.get("stage") == "resolve_canonical_tool"


class TestToolRuntimeProfileMapping:
    """Tests for profile/adapter mapping to canonical handler."""

    def test_remapped_exposed_name_executes_canonical(self):
        """Exposed name should map through adapter to canonical handler."""
        runtime = ToolRuntime(_make_registry_with_read_file())
        profile = _make_remapped_profile()
        # Call with exposed name "open_source" and remapped arg "target"
        call = ToolCall(id="c1", name="open_source", arguments={"target": "main.py"})

        result = runtime.execute(call, profile)

        assert result.ok
        assert result.content == "content of main.py"

    def test_canonical_name_backfilled_on_call(self):
        """execute should back-fill call.canonical_name from the ToolView."""
        runtime = ToolRuntime(_make_registry_with_read_file())
        profile = _make_remapped_profile()
        call = ToolCall(id="c1", name="open_source", arguments={"target": "test.py"})

        assert call.canonical_name is None  # Before execution
        runtime.execute(call, profile)
        assert call.canonical_name == "read_file"  # After execution

    def test_wrong_args_for_remapped_tool(self):
        """Wrong args for remapped tool should return argument error."""
        runtime = ToolRuntime(_make_registry_with_read_file())
        profile = _make_remapped_profile()
        # Using original "path" arg name instead of remapped "target"
        call = ToolCall(id="c1", name="open_source", arguments={"path": "test.py"})

        result = runtime.execute(call, profile)

        assert not result.ok
        assert result.is_error


class TestToolRuntimeInspection:
    """Tests for pre-execution inspection boundaries."""

    def test_inspect_call_exposes_canonical_name_and_args(self):
        runtime = ToolRuntime(_make_registry_with_read_file())
        profile = _make_remapped_profile()
        call = ToolCall(id="c1", name="open_source", arguments={"target": "main.py"})

        inspection = runtime.inspect_call(call, profile)

        assert inspection.schema_valid is True
        assert inspection.mapping_valid is True
        assert inspection.canonical_tool is not None
        assert inspection.canonical_tool.canonical_name == "read_file"
        assert inspection.canonical_args == {"path": "main.py"}
        assert call.canonical_name == "read_file"

    def test_inspect_call_reports_mapping_failure(self):
        runtime = ToolRuntime(_make_registry_with_read_file())
        profile = _make_remapped_profile()
        call = ToolCall(id="c1", name="open_source", arguments={"path": "wrong.py"})

        inspection = runtime.inspect_call(call, profile)

        assert inspection.schema_valid is False or inspection.mapping_valid is False
        assert inspection.mapping_valid is False
        assert inspection.error_result is not None
        assert inspection.error_type in {"schema_validation", "argument_mapping"}
        if inspection.error_type == "schema_validation":
            assert inspection.error_result.metadata.get("stage") == "validate_exposed_arguments"
        else:
            assert inspection.error_result.metadata.get("stage") == "map_arguments"


class TestBuiltinRuntimeDispatch:
    """Focused dispatch checks for newly added builtin tools."""

    def test_write_file_dispatches_to_builtin_handler(self):
        registry = ToolRegistry()
        registry.register(write_file_tool)
        runtime = ToolRuntime(registry)
        profile = ToolProfile(
            profile_id="base",
            tools=[ToolView(
                canonical_name="write_file",
                exposed_name="write_file",
                description="Write a file.",
                input_schema=write_file_tool.canonical_schema,
            )],
        )
        workspace = make_unique_test_dir("tools_runtime_dispatch")
        try:
            (workspace / "note.txt").write_text("old", encoding="utf-8")
            call = ToolCall(
                id="c1",
                name="write_file",
                arguments={"path": "note.txt", "content": "new"},
            )

            result = runtime.execute(
                call,
                profile,
                ctx=ToolContext(workspace_root=workspace),
            )

            assert result.ok
            assert (workspace / "note.txt").read_text(encoding="utf-8") == "new"
            assert result.metadata.get("created") is False
        finally:
            cleanup_test_path(workspace)

    def test_python_run_dispatches_to_builtin_handler(self):
        registry = ToolRegistry()
        registry.register(python_run_tool)
        runtime = ToolRuntime(registry)
        profile = ToolProfile(
            profile_id="base",
            tools=[ToolView(
                canonical_name="python_run",
                exposed_name="python_run",
                description="Run Python.",
                input_schema=python_run_tool.canonical_schema,
            )],
        )
        workspace = make_unique_test_dir("tools_runtime_dispatch")
        try:
            (workspace / "hello.py").write_text("print('hello runtime')\n", encoding="utf-8")
            call = ToolCall(
                id="c1",
                name="python_run",
                arguments={"target": "hello.py"},
            )

            result = runtime.execute(
                call,
                profile,
                ctx=ToolContext(workspace_root=workspace),
            )

            assert result.ok
            assert result.metadata.get("exit_code") == 0
            assert "hello runtime" in result.content
        finally:
            cleanup_test_path(workspace)
