from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from agent_service.tool_protocol import (
    ToolResultContent,
    ToolSafetyPolicy,
    UnifiedToolDefinition,
    UnifiedToolError,
    UnifiedToolInvocation,
    UnifiedToolResult,
)


@dataclass(frozen=True)
class McpToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class McpProviderConfig:
    provider_id: str
    display_name: str
    enabled: bool = True
    transport: str = "stdio"
    command: str | None = None
    url: str | None = None
    timeout_seconds: float = 5.0


class McpClient(Protocol):
    def list_tools(self) -> list[McpToolSpec]:
        raise NotImplementedError

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


class McpToolProvider:
    source = "mcp"

    def __init__(
        self,
        *,
        provider_id: str,
        display_name: str,
        client: McpClient,
        enabled: bool,
    ) -> None:
        self.provider_id = provider_id
        self.display_name = display_name
        self.client = client
        self.enabled = enabled
        self._started = False

    def list_tools(self) -> list[UnifiedToolDefinition]:
        if not self.enabled:
            return []
        self._ensure_started()
        return [
            UnifiedToolDefinition(
                id=f"mcp:{self.provider_id}:{tool.name}",
                source="mcp",
                provider_id=self.provider_id,
                provider_tool_name=tool.name,
                display_name=tool.name,
                description=tool.description,
                capabilities=["external_mcp"],
                input_schema=dict(tool.input_schema),
                output_schema=dict(tool.output_schema or {}),
                permissions=["call_external_mcp_tool"],
                safety_policy=ToolSafetyPolicy(
                    filesystem="none",
                    network="provider_declared",
                    user_approval="high_risk_only",
                    secrets="provider_managed",
                    sandbox="not_required",
                    max_runtime_ms=60000,
                ),
                timeout_ms=60000,
                examples=[],
                enabled=True,
            )
            for tool in self.client.list_tools()
        ]

    def call_tool(
        self,
        invocation: UnifiedToolInvocation,
        *,
        timeout_ms: int | None = None,
    ) -> UnifiedToolResult:
        self._ensure_started()
        name = invocation.tool_id.removeprefix(f"mcp:{self.provider_id}:")
        try:
            raw = self.client.call_tool(
                name,
                invocation.arguments,
                timeout_ms=timeout_ms,
            )
        except Exception:
            return _mcp_error("mcp_call_failed", "MCP tool call failed")

        if raw.get("isError") is True:
            return _mcp_error(
                "mcp_tool_error", "MCP tool returned an error", recoverable=True
            )

        return UnifiedToolResult(
            ok=True,
            content=_map_content(raw.get("content", [])),
            structured_content=raw.get("structuredContent"),
            artifacts=[],
            metadata={"providerId": self.provider_id},
        )

    def health(self) -> dict[str, Any]:
        if hasattr(self.client, "health"):
            return dict(self.client.health())
        return {"ok": self.enabled}

    def stop(self) -> None:
        if hasattr(self.client, "stop"):
            self.client.stop()
        self._started = False

    def _ensure_started(self) -> None:
        if self._started:
            return
        if hasattr(self.client, "start"):
            self.client.start()
        self._started = True


def _map_content(items: list[dict[str, Any]]) -> list[ToolResultContent]:
    mapped: list[ToolResultContent] = []
    for item in items:
        if item.get("type") == "text":
            mapped.append(ToolResultContent(type="text", text=str(item.get("text", ""))))
        else:
            mapped.append(ToolResultContent(type="json", value=item))
    return mapped


def _mcp_error(code: str, message: str, *, recoverable: bool = False) -> UnifiedToolResult:
    return UnifiedToolResult(
        ok=False,
        content=[],
        structured_content=None,
        artifacts=[],
        metadata={},
        error=UnifiedToolError(code=code, message=message, recoverable=recoverable),
    )
