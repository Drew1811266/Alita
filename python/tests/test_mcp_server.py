from pathlib import Path

from agent_service.mcp_server import AlitaMcpServer
from agent_service.run_journal import RunJournal
from agent_service.tool_gateway import UnifiedToolGateway
from agent_service.tool_protocol import (
    ToolSafetyPolicy,
    UnifiedToolDefinition,
    UnifiedToolResult,
)


def allowed_tool() -> UnifiedToolDefinition:
    return UnifiedToolDefinition(
        id="internal:document.receive_attachment",
        source="internal",
        provider_id="internal",
        provider_tool_name="document.receive_attachment",
        display_name="Receive Attachment",
        description="Receive a document attachment.",
        capabilities=["document_input"],
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
        examples=[],
    )


def high_risk_tool() -> UnifiedToolDefinition:
    return UnifiedToolDefinition(
        **{
            **allowed_tool().__dict__,
            "id": "internal:danger.delete_files",
            "provider_tool_name": "danger.delete_files",
            "display_name": "Delete Files",
            "description": "Delete project files.",
            "capabilities": ["filesystem_write"],
            "permissions": ["delete_files"],
            "safety_policy": ToolSafetyPolicy(
                filesystem="project_write",
                network="none",
                user_approval="before_call",
                secrets="none",
                sandbox="required",
                max_runtime_ms=60000,
            ),
        }
    )


class FakeProvider:
    provider_id = "internal"
    source = "internal"

    def list_tools(self):
        return [
            allowed_tool(),
            UnifiedToolDefinition(
                **{
                    **allowed_tool().__dict__,
                    "id": "internal:document.markitdown_convert",
                    "provider_tool_name": "document.markitdown_convert",
                    "display_name": "Convert Document",
                }
            ),
            high_risk_tool(),
        ]

    def call_tool(self, invocation, *, timeout_ms=None):
        return UnifiedToolResult(
            ok=True,
            content=[],
            structured_content={"path": invocation.arguments.get("path")},
            artifacts=[],
            metadata={"source": "fake"},
        )


def fake_gateway() -> UnifiedToolGateway:
    return UnifiedToolGateway(providers=[FakeProvider()])


def test_alita_mcp_server_lists_only_allowed_tools() -> None:
    server = AlitaMcpServer(
        gateway=fake_gateway(),
        allowed_tool_ids=["internal:document.receive_attachment"],
        enabled=True,
    )

    tools = server.list_tools()

    assert [tool["name"] for tool in tools] == ["internal__document__receive_attachment"]


def test_alita_mcp_server_rejects_non_whitelisted_tool() -> None:
    server = AlitaMcpServer(
        gateway=fake_gateway(),
        allowed_tool_ids=["internal:document.receive_attachment"],
        enabled=True,
    )

    result = server.call_tool("internal__document__markitdown_convert", {})

    assert result["isError"] is True


def test_alita_mcp_server_does_not_expose_high_risk_tools() -> None:
    server = AlitaMcpServer(
        gateway=fake_gateway(),
        allowed_tool_ids=[
            "internal:document.receive_attachment",
            "internal:danger.delete_files",
        ],
        enabled=True,
    )

    tools = server.list_tools()

    assert [tool["name"] for tool in tools] == ["internal__document__receive_attachment"]


def test_alita_mcp_server_rejects_high_risk_tool_calls() -> None:
    server = AlitaMcpServer(
        gateway=fake_gateway(),
        allowed_tool_ids=["internal:danger.delete_files"],
        enabled=True,
    )

    result = server.call_tool("internal__danger__delete_files", {"path": "inputs/a.md"})

    assert result["isError"] is True


def test_external_mcp_call_writes_sanitized_audit(tmp_path: Path) -> None:
    journal = RunJournal(project_path=str(tmp_path / "demo.alita"), run_id="run-1")
    server = AlitaMcpServer(
        gateway=fake_gateway(),
        allowed_tool_ids=["internal:document.receive_attachment"],
        enabled=True,
        run_journal=journal,
    )

    server.call_tool(
        "internal__document__receive_attachment",
        {"path": "inputs/a.md", "apiKey": "secret-value"},
    )

    events = journal.read_audit_events()

    assert events[-1]["source"] == "external_mcp"
    assert "secret-value" not in str(events[-1])
    assert events[-1]["toolId"] == "internal:document.receive_attachment"
