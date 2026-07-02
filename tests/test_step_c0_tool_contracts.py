from __future__ import annotations

from pathlib import Path

from pycodeagent.agent.llm_client import (
    FakeLLMClient,
    GenerateRequest,
    GenerateResponse,
    ToolCallCandidate,
)
from pycodeagent.agent.parser import interpret_model_response
from pycodeagent.agent.runner import run_agent_task
from pycodeagent.env.task import CodingTask
from pycodeagent.mutations.profile_loader import load_tool_profile_from_dict
from pycodeagent.runtime_trace import RuntimeTraceWriter
from pycodeagent.rl.serializer import serialize_trajectory
from pycodeagent.tools.context import ToolContext
from pycodeagent.tools.contracts import ToolContractKind, ToolPayloadKind
from pycodeagent.tools.registry import ToolRegistry
from pycodeagent.tools.runtime import ToolRuntime
from pycodeagent.tools.spec import CanonicalTool, ToolProfile, ToolView
from pycodeagent.traces.tool_catalog import AgentToolCatalog, CatalogToolEntry
from pycodeagent.traces.tool_catalog_snapshot import catalog_to_base_tool_profile
from pycodeagent.trajectory.schema import ToolCall, Trajectory


def _freeform_handler(*, input_text: str, **kwargs) -> str:
    return f"freeform:{input_text.splitlines()[0]}"


def _make_freeform_profile() -> ToolProfile:
    return ToolProfile(
        profile_id="freeform_profile",
        tools=[
            ToolView(
                canonical_name="apply_patch",
                exposed_name="apply_patch",
                description="Apply a patch.",
                contract_kind=ToolContractKind.FREEFORM,
                input_format={"type": "grammar", "syntax": "lark"},
            )
        ],
        adapters={},
    )


def _make_freeform_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        CanonicalTool(
            canonical_name="apply_patch",
            description="Apply a patch.",
            contract_kind=ToolContractKind.FREEFORM,
            input_format={"type": "grammar", "syntax": "lark"},
            handler=_freeform_handler,
        )
    )
    return registry


def test_generate_request_normalizes_function_and_freeform_specs() -> None:
    function_request = GenerateRequest(
        messages=[{"role": "user", "content": "read"}],
        tools=[
            {
                "name": "read_file",
                "description": "Read a file.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }
        ],
    )
    assert function_request.tools == [
        {
            "name": "read_file",
            "description": "Read a file.",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }
    ]

    freeform_request = GenerateRequest(
        messages=[{"role": "user", "content": "patch"}],
        tools=[
            {
                "name": "apply_patch",
                "description": "Apply a patch.",
                "kind": "freeform",
                "input_format": {"type": "grammar", "syntax": "lark"},
            }
        ],
    )
    assert freeform_request.tools == [
        {
            "name": "apply_patch",
            "description": "Apply a patch.",
            "kind": "freeform",
            "input_format": {"type": "grammar", "syntax": "lark"},
        }
    ]


def test_parser_accepts_freeform_tool_call_candidate() -> None:
    response = GenerateResponse.from_native_tool_calling(
        assistant_text="Applying patch.",
        tool_calls=[
            ToolCallCandidate(
                call_id="call_patch_1",
                name="apply_patch",
                input_text="*** Begin Patch\n*** End Patch\n",
                source="native",
            )
        ],
        finish_reason="tool_calls",
    )

    parsed = interpret_model_response(response)

    assert parsed.ok is True
    assert len(parsed.tool_calls) == 1
    call = parsed.tool_calls[0]
    assert call.payload_kind == ToolPayloadKind.INPUT_TEXT
    assert call.input_text == "*** Begin Patch\n*** End Patch\n"
    assert call.arguments == {}


def test_runtime_executes_freeform_tool_call() -> None:
    runtime = ToolRuntime(_make_freeform_registry())
    profile = _make_freeform_profile()
    call = ToolCall(
        id="call_patch_1",
        name="apply_patch",
        input_text="*** Begin Patch\n*** End Patch\n",
    )

    result = runtime.execute(call, profile)

    assert result.ok is True
    assert result.content == "freeform:*** Begin Patch"


def test_serialize_trajectory_preserves_freeform_tool_call_payload() -> None:
    trajectory = Trajectory(
        task_id="step_c0",
        repo="/tmp/repo",
        tool_profile_id="freeform_profile",
    )
    call = ToolCall(
        id="call_patch_1",
        name="apply_patch",
        input_text="*** Begin Patch\n*** End Patch\n",
    )
    trajectory.add_assistant("Applying patch.", [call])

    serialized = serialize_trajectory(trajectory)

    tool_call_segment = next(
        segment for segment in serialized.segments if segment.kind == "assistant_tool_call"
    )
    assert '"payload_kind": "input_text"' in tool_call_segment.text
    assert '"input_text": "*** Begin Patch\\n*** End Patch\\n"' in tool_call_segment.text


def test_catalog_and_profile_loader_support_freeform_contracts() -> None:
    catalog = AgentToolCatalog(
        catalog_id="catalog_freeform",
        agent_name="codex",
        agent_version="v1",
        capture_mode="test",
        source_kind="unit_test",
        tools=[
            CatalogToolEntry(
                raw_tool_name="apply_patch",
                description="Apply a patch.",
                contract_kind=ToolContractKind.FREEFORM,
                input_format={"type": "grammar", "syntax": "lark"},
            )
        ],
    )

    profile = catalog_to_base_tool_profile(catalog)

    assert profile.tools[0].contract_kind == ToolContractKind.FREEFORM
    assert profile.get_exposed_specs()[0] == {
        "name": "apply_patch",
        "description": "Apply a patch.",
        "kind": "freeform",
        "input_format": {"type": "grammar", "syntax": "lark"},
    }

    loaded = load_tool_profile_from_dict(
        {
            "profile_id": "loaded_freeform",
            "tools": [
                {
                    "canonical": "apply_patch",
                    "exposed_name": "apply_patch",
                    "description": "Apply a patch.",
                    "kind": "freeform",
                    "input_format": {"type": "grammar", "syntax": "lark"},
                    "adapter": {},
                }
            ],
        }
    )

    assert loaded.tools[0].contract_kind == ToolContractKind.FREEFORM
    assert loaded.tools[0].input_format == {"type": "grammar", "syntax": "lark"}


def test_runtime_trace_preserves_freeform_payload(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n", encoding="utf-8")

    task = CodingTask(
        task_id="step_c0_runner_trace",
        repo_path=repo,
        prompt="Apply the patch.",
        max_turns=1,
    )
    ctx = ToolContext(workspace_root=repo, task=task)
    trace_writer = RuntimeTraceWriter.create(
        run_dir=tmp_path / "trace",
        run_id="step_c0_run",
        task_id=task.task_id,
        tool_profile_id="freeform_profile",
        workspace_root=str(repo),
    )
    client = FakeLLMClient(
        responses=[
            GenerateResponse.from_native_tool_calling(
                assistant_text="Applying patch.",
                tool_calls=[
                    ToolCallCandidate(
                        call_id="call_patch_1",
                        name="apply_patch",
                        input_text="*** Begin Patch\n*** End Patch\n",
                        source="native",
                    )
                ],
                finish_reason="tool_calls",
            )
        ]
    )

    trajectory = run_agent_task(
        task,
        client,
        ToolRuntime(_make_freeform_registry()),
        _make_freeform_profile(),
        ctx,
        trace_writer=trace_writer,
    )
    trace_writer.finalize()

    event_log_text = (tmp_path / "trace" / "runtime_trace.jsonl").read_text(
        encoding="utf-8"
    )
    payload_texts = [
        payload.read_text(encoding="utf-8")
        for payload in sorted((tmp_path / "trace" / "payloads").glob("*.json"))
    ]

    assert "exposed_input_text" in event_log_text
    assert any("*** Begin Patch" in payload for payload in payload_texts)
    assert trajectory.tool_calls[0].input_text == "*** Begin Patch\n*** End Patch\n"
