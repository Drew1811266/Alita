from __future__ import annotations

from typing import Any

from agent_service.tool_providers.mcp import McpProviderConfig, McpToolSpec


class UnavailableMcpClient:
    def __init__(self, *, error_code: str, message: str) -> None:
        self.error_code = error_code
        self.message = message

    def list_tools(self) -> list[McpToolSpec]:
        return []

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "isError": True,
            "content": [{"type": "text", "text": self.message}],
        }

    def health(self) -> dict[str, Any]:
        return {
            "ok": False,
            "errorCode": self.error_code,
            "message": self.message,
        }


def create_mcp_client(config: McpProviderConfig) -> UnavailableMcpClient:
    if config.transport == "stdio" and not config.command:
        return UnavailableMcpClient(
            error_code="missing_command",
            message="MCP stdio command is required",
        )
    if config.transport == "http" and not config.url:
        return UnavailableMcpClient(
            error_code="missing_url",
            message="MCP HTTP URL is required",
        )
    return UnavailableMcpClient(
        error_code="unsupported_transport_runtime",
        message="Real MCP client runtime is not enabled yet",
    )
