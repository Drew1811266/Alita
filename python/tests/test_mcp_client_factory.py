from pathlib import Path
import sys

from agent_service.mcp_client_factory import create_mcp_client
from agent_service.tool_providers.mcp import McpProviderConfig


def test_create_mcp_client_rejects_missing_stdio_command() -> None:
    config = McpProviderConfig(
        provider_id="docs",
        display_name="Docs",
        transport="stdio",
    )

    client = create_mcp_client(config)

    assert client.health()["ok"] is False
    assert client.health()["errorCode"] == "missing_command"


def test_create_mcp_client_rejects_missing_http_url() -> None:
    config = McpProviderConfig(
        provider_id="docs",
        display_name="Docs",
        transport="http",
    )

    client = create_mcp_client(config)

    assert client.health()["ok"] is False
    assert client.health()["errorCode"] == "missing_url"


def test_create_mcp_client_reports_real_runtime_not_enabled() -> None:
    config = McpProviderConfig(
        provider_id="docs",
        display_name="Docs",
        transport="http",
        url="https://mcp.example.test",
    )

    client = create_mcp_client(config)

    assert client.list_tools() == []
    assert client.health()["ok"] is False
    assert client.health()["errorCode"] == "unsupported_transport_runtime"


def test_stdio_mcp_client_lists_and_calls_fixture_tool() -> None:
    server_path = Path(__file__).parent / "fixtures" / "mcp_stdio_server.py"
    config = McpProviderConfig(
        provider_id="fixture",
        display_name="Fixture MCP",
        transport="stdio",
        command=f'"{sys.executable}" "{server_path}"',
    )
    client = create_mcp_client(config)

    try:
        tools = client.list_tools()
        result = client.call_tool("echo", {"message": "hello"})
    finally:
        client.stop()

    assert client.health()["ok"] is False
    assert tools[0].name == "echo"
    assert tools[0].input_schema["required"] == ["message"]
    assert result["isError"] is False
    assert result["structuredContent"] == {"echo": "hello"}
