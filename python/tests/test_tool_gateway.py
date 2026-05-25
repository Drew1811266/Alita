from pathlib import Path

from agent_service.tool_execution import ToolResult
from agent_service.tool_providers.internal import InternalToolProvider
from agent_service.tool_registry import ToolRegistry


def _packages_root() -> Path:
    return Path(__file__).resolve().parents[2] / "tool-packages"


def test_internal_provider_lists_existing_manifest_tools() -> None:
    registry = ToolRegistry.from_packages_root(_packages_root())
    provider = InternalToolProvider(registry=registry)

    tools = provider.list_tools()
    tool_ids = {tool.id for tool in tools}

    assert "internal:document.markitdown_convert" in tool_ids
    assert "internal:document.typst_compile" in tool_ids


def test_internal_provider_preserves_manifest_permissions() -> None:
    registry = ToolRegistry.from_packages_root(_packages_root())
    provider = InternalToolProvider(registry=registry)

    markitdown = next(
        tool
        for tool in provider.list_tools()
        if tool.id == "internal:document.markitdown_convert"
    )

    assert "read_project_files" in markitdown.permissions
    assert markitdown.provider_id == "internal"
    assert markitdown.source == "internal"


def test_gateway_rejects_unknown_tool() -> None:
    from agent_service.tool_gateway import UnifiedToolGateway
    from agent_service.tool_protocol import UnifiedToolInvocation

    gateway = UnifiedToolGateway(providers=[])
    invocation = UnifiedToolInvocation(
        invocation_id="inv-1",
        run_id="run-1",
        task_id="task-1",
        tool_id="internal:missing.tool",
        arguments={},
        allowed_roots=[],
        requested_permissions=[],
    )

    result = gateway.call_tool(invocation)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "unsupported_tool"


def test_gateway_validates_input_schema_before_provider_call() -> None:
    from agent_service.tool_gateway import UnifiedToolGateway
    from agent_service.tool_protocol import UnifiedToolInvocation

    registry = ToolRegistry.from_packages_root(_packages_root())
    provider = InternalToolProvider(registry=registry)
    gateway = UnifiedToolGateway(providers=[provider])
    invocation = UnifiedToolInvocation(
        invocation_id="inv-1",
        run_id="run-1",
        task_id="task-1",
        tool_id="internal:document.markitdown_convert",
        arguments={"operation": "convert_local_file"},
        allowed_roots=[],
        requested_permissions=["read_project_files"],
    )

    result = gateway.call_tool(invocation)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "invalid_tool_input"


def test_gateway_calls_internal_tool_adapter_and_normalizes_result() -> None:
    from agent_service.tool_execution import ToolExecutor
    from agent_service.tool_gateway import UnifiedToolGateway
    from agent_service.tool_protocol import UnifiedToolInvocation

    registry = ToolRegistry.from_packages_root(_packages_root())

    def adapter(invocation):
        assert invocation.tool_id == "document.markitdown_convert"
        assert invocation.operation == "convert_local_file"
        assert invocation.arguments["input_path"] == "inputs/source.docx"
        return ToolResult(
            values={"text": "converted text"},
            artifacts=["outputs/source.md"],
            metadata={"mime": "text/markdown"},
        )

    executor = ToolExecutor(
        registry=registry,
        adapters={("document.markitdown_convert", "convert_local_file"): adapter},
    )
    provider = InternalToolProvider(registry=registry, executor=executor)
    gateway = UnifiedToolGateway(providers=[provider])

    result = gateway.call_tool(
        UnifiedToolInvocation(
            invocation_id="inv-1",
            run_id="run-1",
            task_id="task-1",
            tool_id="internal:document.markitdown_convert",
            arguments={
                "operation": "convert_local_file",
                "input_path": "inputs/source.docx",
                "output_path": "outputs/source.md",
            },
            project_path="D:\\Project\\demo.alita",
            allowed_roots=["D:\\Project"],
            requested_permissions=["read_project_files"],
        )
    )

    assert result.ok is True
    assert result.structured_content == {"text": "converted text"}
    assert result.artifacts == ["outputs/source.md"]
    assert result.content[0].type == "json"
    assert result.content[1].path == "outputs/source.md"
