from agent_service.tool_protocol import UnifiedToolInvocation
from agent_service.tool_providers.mcp import McpProviderConfig, McpToolProvider, McpToolSpec


class FakeMcpClient:
    def list_tools(self):
        return [
            McpToolSpec(
                name="search_docs",
                description="Search an external documentation source.",
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                },
                output_schema={"type": "object"},
            )
        ]

    def call_tool(self, name, arguments, *, timeout_ms=None):
        assert name == "search_docs"
        assert arguments == {"query": "alita"}
        return {
            "content": [{"type": "text", "text": "result"}],
            "structuredContent": {"matches": 1},
            "isError": False,
        }


class FakeLifecycleMcpClient(FakeMcpClient):
    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> None:
        self.start_calls += 1

    def health(self):
        return {"ok": self.start_calls > 0}

    def stop(self) -> None:
        self.stop_calls += 1


class RecordingTimeoutMcpClient(FakeMcpClient):
    def __init__(self) -> None:
        self.timeout_ms = None

    def call_tool(self, name, arguments, *, timeout_ms=None):
        self.timeout_ms = timeout_ms
        return super().call_tool(name, arguments, timeout_ms=timeout_ms)


def test_mcp_provider_maps_tools_to_unified_catalog() -> None:
    provider = McpToolProvider(
        provider_id="mcp-docs",
        display_name="Docs MCP",
        client=FakeMcpClient(),
        enabled=True,
    )

    tools = provider.list_tools()

    assert tools[0].id == "mcp:mcp-docs:search_docs"
    assert tools[0].source == "mcp"
    assert tools[0].provider_tool_name == "search_docs"
    assert tools[0].input_schema["required"] == ["query"]


def test_mcp_provider_starts_lifecycle_client_once_before_listing() -> None:
    client = FakeLifecycleMcpClient()
    provider = McpToolProvider(
        provider_id="mcp-docs",
        display_name="Docs MCP",
        client=client,
        enabled=True,
    )

    provider.list_tools()
    provider.list_tools()

    assert client.start_calls == 1
    assert provider.health() == {"ok": True}


def test_mcp_provider_calls_tool_and_maps_result() -> None:
    provider = McpToolProvider(
        provider_id="mcp-docs",
        display_name="Docs MCP",
        client=FakeMcpClient(),
        enabled=True,
    )

    result = provider.call_tool(
        UnifiedToolInvocation(
            invocation_id="inv-1",
            run_id="run-1",
            task_id="task-1",
            tool_id="mcp:mcp-docs:search_docs",
            arguments={"query": "alita"},
            allowed_roots=[],
            requested_permissions=["call_external_mcp_tool"],
        )
    )

    assert result.ok is True
    assert result.structured_content == {"matches": 1}
    assert result.content[0].text == "result"


def test_mcp_provider_passes_timeout_to_client() -> None:
    client = RecordingTimeoutMcpClient()
    provider = McpToolProvider(
        provider_id="mcp-docs",
        display_name="Docs MCP",
        client=client,
        enabled=True,
    )

    result = provider.call_tool(
        UnifiedToolInvocation(
            invocation_id="inv-timeout",
            run_id="run-timeout",
            task_id="task-timeout",
            tool_id="mcp:mcp-docs:search_docs",
            arguments={"query": "alita"},
            allowed_roots=[],
            requested_permissions=["call_external_mcp_tool"],
        ),
        timeout_ms=1234,
    )

    assert result.ok is True
    assert client.timeout_ms == 1234


def test_mcp_provider_starts_lifecycle_client_once_before_calling() -> None:
    client = FakeLifecycleMcpClient()
    provider = McpToolProvider(
        provider_id="mcp-docs",
        display_name="Docs MCP",
        client=client,
        enabled=True,
    )

    result = provider.call_tool(
        UnifiedToolInvocation(
            invocation_id="inv-1",
            run_id="run-1",
            task_id="task-1",
            tool_id="mcp:mcp-docs:search_docs",
            arguments={"query": "alita"},
            allowed_roots=[],
            requested_permissions=["call_external_mcp_tool"],
        )
    )

    assert result.ok is True
    assert client.start_calls == 1


def test_mcp_provider_config_carries_transport_details() -> None:
    config = McpProviderConfig(
        provider_id="mcp-docs",
        display_name="Docs MCP",
        transport="http",
        url="https://mcp.example.test",
    )

    assert config.enabled is True
    assert config.transport == "http"
    assert config.command is None
    assert config.url == "https://mcp.example.test"
