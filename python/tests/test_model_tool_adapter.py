from agent_service.model_tool_adapter import (
    ModelToolCall,
    ModelToolNameMap,
    build_model_tool_invocation,
    execute_model_tool_calls,
    safe_observation_payload,
    to_openai_tool_schema,
)
from agent_service.tool_gateway import UnifiedToolGateway
from agent_service.tool_protocol import (
    ToolSafetyPolicy,
    UnifiedToolDefinition,
    UnifiedToolResult,
    UnifiedToolInvocation,
)


def tool_definition(
    tool_id: str = "internal:document.markitdown_convert",
    *,
    enabled: bool = True,
) -> UnifiedToolDefinition:
    return UnifiedToolDefinition(
        id=tool_id,
        source="internal",
        provider_id="internal",
        provider_tool_name="document.markitdown_convert",
        display_name="Convert Document",
        description="Convert a project document to Markdown.",
        capabilities=["document_conversion"],
        input_schema={
            "type": "object",
            "required": ["input_path"],
            "properties": {"input_path": {"type": "string"}},
        },
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
        examples=[],
        enabled=enabled,
    )


def test_unified_tool_converts_to_openai_tool_schema() -> None:
    schema = to_openai_tool_schema(tool_definition())

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "internal__document__markitdown_convert"
    assert schema["function"]["parameters"]["required"] == ["input_path"]


def test_model_tool_name_map_round_trips_tool_id() -> None:
    mapping = ModelToolNameMap.from_tools([tool_definition()])

    model_name = mapping.model_name_for_tool_id("internal:document.markitdown_convert")

    assert mapping.tool_id_for_model_name(model_name) == "internal:document.markitdown_convert"


def test_model_tool_call_rejects_unavailable_tool_before_execution() -> None:
    gateway = UnifiedToolGateway(providers=[])
    mapping = ModelToolNameMap.from_tools([tool_definition()])

    results = execute_model_tool_calls(
        [
            ModelToolCall(
                id="call-1",
                name=mapping.model_name_for_tool_id(
                    "internal:document.markitdown_convert"
                ),
                arguments={"input_path": "inputs/a.docx"},
            )
        ],
        name_map=mapping,
        gateway=gateway,
        base_invocation=UnifiedToolInvocation(
            invocation_id="inv-base",
            run_id="run-1",
            task_id="task-1",
            tool_id="internal:document.markitdown_convert",
            arguments={},
            allowed_roots=[],
            requested_permissions=[],
        ),
    )

    assert results[0].ok is False
    assert results[0].error is not None
    assert results[0].error.code == "unsupported_tool"


def test_model_tool_call_executes_through_gateway_provider() -> None:
    tool = tool_definition()

    class Provider:
        provider_id = "internal"
        source = "internal"

        def list_tools(self):
            return [tool]

        def call_tool(self, invocation):
            return UnifiedToolResult(
                ok=True,
                content=[],
                structured_content={"text": "converted"},
                artifacts=[],
                metadata={"tool": invocation.tool_id},
            )

    gateway = UnifiedToolGateway(providers=[Provider()])
    mapping = ModelToolNameMap.from_tools([tool])

    results = execute_model_tool_calls(
        [
            ModelToolCall(
                id="call-1",
                name=mapping.model_name_for_tool_id(tool.id),
                arguments={"input_path": "inputs/a.docx"},
            )
        ],
        name_map=mapping,
        gateway=gateway,
        base_invocation=UnifiedToolInvocation(
            invocation_id="inv-base",
            run_id="run-1",
            task_id="task-1",
            tool_id=tool.id,
            arguments={},
            allowed_roots=[],
            requested_permissions=[],
        ),
    )

    assert results[0].ok is True
    assert results[0].metadata == {"tool": "internal:document.markitdown_convert"}


def test_safe_observation_payload_omits_secret_values_and_uses_artifact_names() -> None:
    invocation = UnifiedToolInvocation(
        invocation_id="inv-1",
        run_id="run-1",
        task_id="task-1",
        tool_id="internal:file.inspect",
        arguments={},
        allowed_roots=[],
        requested_permissions=[],
    )
    result = UnifiedToolResult(
        ok=True,
        content=[],
        structured_content={"text": "ok", "api_key": "sk-secret"},
        artifacts=["D:\\Project\\artifacts\\report.md"],
        metadata={},
    )

    payload = safe_observation_payload(invocation, result)

    assert payload["toolId"] == "internal:file.inspect"
    assert payload["ok"] is True
    assert payload["values"] == {"text": "ok"}
    assert payload["artifacts"] == ["report.md"]
    assert payload["errorCode"] is None


def test_build_model_tool_invocation_copies_base_runtime_context() -> None:
    tool = tool_definition()
    base_invocation = UnifiedToolInvocation(
        invocation_id="base",
        run_id="run-1",
        task_id="task-1",
        node_id="model-node",
        tool_id="internal:old",
        arguments={"old": True},
        project_path="D:\\Project\\demo.alita",
        allowed_roots=["D:\\Project"],
        requested_permissions=["old_permission"],
        approval_token="approval",
        model_session_id="model-session",
    )

    invocation = build_model_tool_invocation(
        base_invocation=base_invocation,
        tool=tool,
        invocation_id="call-1",
        arguments={"input_path": "input.docx"},
    )

    assert invocation.invocation_id == "call-1"
    assert invocation.tool_id == "internal:document.markitdown_convert"
    assert invocation.arguments == {"input_path": "input.docx"}
    assert invocation.run_id == "run-1"
    assert invocation.task_id == "task-1"
    assert invocation.node_id == "model-node"
    assert invocation.project_path == "D:\\Project\\demo.alita"
    assert invocation.allowed_roots == ["D:\\Project"]
    assert invocation.requested_permissions == ["read_project_files"]
    assert invocation.approval_token == "approval"
    assert invocation.model_session_id == "model-session"
