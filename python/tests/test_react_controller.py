from __future__ import annotations

from agent_service.model_client import ChatMessage
from agent_service.react_controller import ReActController, ReActPolicy
from agent_service.tool_protocol import (
    ToolResultContent,
    ToolSafetyPolicy,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)


class SequencedModel:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[list[ChatMessage]] = []

    def chat(self, messages, *, temperature=None, max_tokens=None, policy=None):
        self.calls.append(messages)
        return self.replies.pop(0)


class RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[UnifiedToolInvocation] = []

    def call_tool(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        self.calls.append(invocation)
        return UnifiedToolResult(
            ok=True,
            content=[ToolResultContent(type="json", value={"text": "tool observation"})],
            structured_content={"text": "tool observation", "secret": "sk-test"},
            artifacts=["D:\\Project\\artifacts\\result.md"],
            metadata={"gateway": "recording"},
        )


def _tool(tool_id: str = "internal:file.inspect") -> UnifiedToolDefinition:
    return UnifiedToolDefinition(
        id=tool_id,
        source="internal",
        provider_id="internal",
        provider_tool_name=tool_id.removeprefix("internal:"),
        display_name="Inspect file",
        description="Inspect a local project file.",
        capabilities=[],
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        output_schema={"type": "object"},
        permissions=["read_project_files"],
        safety_policy=ToolSafetyPolicy(
            filesystem="project_read",
            network="none",
            user_approval="never",
            secrets="none",
            sandbox="not_required",
            max_runtime_ms=60000,
        ),
        timeout_ms=60000,
    )


def _base_invocation() -> UnifiedToolInvocation:
    return UnifiedToolInvocation(
        invocation_id="react-base",
        run_id="run-react",
        task_id="task-react",
        node_id="model-node",
        tool_id="internal:file.inspect",
        arguments={},
        project_path="D:\\Project\\demo.alita",
        allowed_roots=["D:\\Project"],
        requested_permissions=["read_project_files"],
    )


def test_react_controller_runs_one_tool_call_then_final_answer() -> None:
    model = SequencedModel(
        [
            '{"kind":"tool","tool_id":"internal:file.inspect","arguments":{"path":"README.md"}}',
            '{"kind":"final","text":"The file has 10 rows."}',
        ]
    )
    gateway = RecordingGateway()
    result = ReActController(model_client=model, gateway=gateway).run(
        messages=[ChatMessage(role="user", content="Inspect the file.")],
        tools=[_tool()],
        base_invocation=_base_invocation(),
        policy=ReActPolicy(
            enabled=True,
            max_steps=3,
            max_tool_calls=2,
            allowed_tool_ids=["internal:file.inspect"],
            allowed_permissions=["read_project_files"],
        ),
    )

    assert result.ok is True
    assert result.text == "The file has 10 rows."
    assert result.tool_call_count == 1
    assert gateway.calls[0].tool_id == "internal:file.inspect"
    assert gateway.calls[0].arguments == {"path": "README.md"}
    assert result.observations[0]["values"]["text"] == "tool observation"
    assert "secret" not in result.observations[0]["values"]
    assert result.observations[0]["artifacts"] == ["result.md"]
    assert len(model.calls) == 2
    assert "tool observation" in model.calls[1][-1].content


def test_react_controller_rejects_disallowed_tool_id() -> None:
    model = SequencedModel(
        ['{"kind":"tool","tool_id":"internal:forbidden","arguments":{}}']
    )
    result = ReActController(model_client=model, gateway=RecordingGateway()).run(
        messages=[ChatMessage(role="user", content="Use a tool.")],
        tools=[_tool("internal:forbidden")],
        base_invocation=_base_invocation(),
        policy=ReActPolicy(enabled=True, allowed_tool_ids=["internal:file.inspect"]),
    )

    assert result.ok is False
    assert result.error_code == "tool_not_allowed"
    assert result.tool_call_count == 0


def test_react_controller_rejects_malformed_action() -> None:
    model = SequencedModel(["not json"])
    result = ReActController(model_client=model, gateway=RecordingGateway()).run(
        messages=[ChatMessage(role="user", content="Use a tool.")],
        tools=[_tool()],
        base_invocation=_base_invocation(),
        policy=ReActPolicy(enabled=True, allowed_tool_ids=["internal:file.inspect"]),
    )

    assert result.ok is False
    assert result.error_code == "malformed_action"
