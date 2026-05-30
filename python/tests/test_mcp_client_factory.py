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
