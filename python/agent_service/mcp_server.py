from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_service.model_tool_adapter import ModelToolNameMap, model_safe_tool_name
from agent_service.run_journal import RunJournal
from agent_service.tool_gateway import UnifiedToolGateway
from agent_service.tool_protocol import (
    ToolResultContent,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)


class AlitaMcpServer:
    def __init__(
        self,
        *,
        gateway: UnifiedToolGateway,
        allowed_tool_ids: list[str],
        enabled: bool,
        run_journal: RunJournal | None = None,
    ) -> None:
        self.gateway = gateway
        self.allowed_tool_ids = set(allowed_tool_ids)
        self.enabled = enabled
        self.run_journal = run_journal

    def list_tools(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        return [
            {
                "name": model_safe_tool_name(tool.id),
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool in self._allowed_tools()
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return _mcp_error("Alita MCP server is disabled")

        name_map = ModelToolNameMap.from_tools(self._allowed_tools())
        try:
            tool_id = name_map.tool_id_for_model_name(name)
        except KeyError:
            return _mcp_error("Tool is not allowed")

        result = self.gateway.call_tool(
            UnifiedToolInvocation(
                invocation_id=f"external-mcp-{datetime.now(timezone.utc).timestamp()}",
                run_id="external-mcp",
                task_id="external-mcp",
                tool_id=tool_id,
                arguments=dict(arguments),
                allowed_roots=[],
                requested_permissions=[],
            )
        )
        self._write_audit(tool_id=tool_id, arguments=arguments, result=result)
        return _unified_result_to_mcp(result)

    def _allowed_tools(self) -> list[UnifiedToolDefinition]:
        return [
            tool
            for tool in self.gateway.list_tools()
            if tool.id in self.allowed_tool_ids and _is_externally_callable(tool)
        ]

    def _write_audit(
        self,
        *,
        tool_id: str,
        arguments: dict[str, Any],
        result: UnifiedToolResult,
    ) -> None:
        if self.run_journal is None:
            return
        self.run_journal.write_audit_event(
            {
                "source": "external_mcp",
                "toolId": tool_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "arguments": _safe_argument_summary(arguments),
                "ok": result.ok,
                "errorCode": result.error.code if result.error else None,
            }
        )


def _unified_result_to_mcp(result: UnifiedToolResult) -> dict[str, Any]:
    if not result.ok:
        return _mcp_error(result.error.message if result.error else "Tool call failed")
    return {
        "content": [_content_to_mcp(item) for item in result.content],
        "structuredContent": result.structured_content,
        "isError": False,
    }


def _content_to_mcp(content: ToolResultContent) -> dict[str, Any]:
    if content.type == "text":
        return {"type": "text", "text": content.text or ""}
    if content.type == "artifact":
        return {"type": "resource_link", "uri": content.path or ""}
    if content.type == "resource_link":
        return {"type": "resource_link", "uri": content.uri or "", "title": content.title}
    return {"type": "text", "text": str(content.value)}


def _mcp_error(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "structuredContent": None,
        "isError": True,
    }


def _is_externally_callable(tool: UnifiedToolDefinition) -> bool:
    policy = tool.safety_policy
    if policy.user_approval != "never":
        return False
    if policy.filesystem in {"project_write", "external_write"}:
        return False
    if policy.network != "none":
        return False
    if policy.secrets != "none":
        return False

    high_risk_markers = (
        "write",
        "delete",
        "remove",
        "network",
        "external",
        "shell",
        "process",
        "credential",
        "secret",
    )
    declared_markers = [*tool.permissions, *tool.capabilities]
    return not any(
        marker in declared.lower()
        for declared in declared_markers
        for marker in high_risk_markers
    )


def _safe_argument_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in arguments.items():
        lowered = key.lower()
        if "secret" in lowered or "token" in lowered or "apikey" in lowered or "api_key" in lowered:
            safe[key] = "<redacted>"
        else:
            safe[key] = value
    return safe
