from __future__ import annotations

from pydantic import BaseModel, Field

from agent_service.authority import extract_invocation_paths
from agent_service.tool_protocol import UnifiedToolDefinition, UnifiedToolInvocation


class CapabilityRequest(BaseModel):
    capability: str
    provider_id: str | None = None
    tool_id: str | None = None
    operation: str | None = None
    read_roots: list[str] = Field(default_factory=list)
    write_roots: list[str] = Field(default_factory=list)
    network_domains: list[str] = Field(default_factory=list)
    runtime_budget_ms: int | None = None
    reason: str = ""


def capability_request_for_tool_invocation(
    invocation: UnifiedToolInvocation,
    tool: UnifiedToolDefinition,
) -> CapabilityRequest:
    paths = extract_invocation_paths(
        invocation.arguments,
        project_path=invocation.project_path,
    )
    network_domain = invocation.metadata.get("networkDomain")
    return CapabilityRequest(
        capability="tool",
        provider_id=tool.provider_id,
        tool_id=invocation.tool_id,
        operation=str(invocation.arguments.get("operation") or ""),
        read_roots=[path.path for path in paths if path.kind == "read"],
        write_roots=[path.path for path in paths if path.kind == "write"],
        network_domains=[str(network_domain)] if network_domain else [],
        runtime_budget_ms=tool.timeout_ms,
        reason=f"Invoke {invocation.tool_id}",
    )
