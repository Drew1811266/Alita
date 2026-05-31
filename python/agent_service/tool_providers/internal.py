from __future__ import annotations

from agent_service.tool_execution import ToolExecutor, ToolInvocation
from agent_service.tool_protocol import (
    ToolResultContent,
    UnifiedToolError,
    ToolSafetyPolicy,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from agent_service.tool_registry import ToolRegistry


class InternalToolProvider:
    provider_id = "internal"
    source = "internal"

    def __init__(
        self, *, registry: ToolRegistry, executor: ToolExecutor | None = None
    ) -> None:
        self.registry = registry
        self.executor = executor or ToolExecutor(registry=registry)

    def list_tools(self) -> list[UnifiedToolDefinition]:
        tools: list[UnifiedToolDefinition] = []
        for manifest in self.registry.enabled_tools():
            max_runtime_ms = int(manifest.timeout_policy.get("seconds", 60)) * 1000
            tools.append(
                UnifiedToolDefinition(
                    id=f"internal:{manifest.tool_id}",
                    source="internal",
                    provider_id=self.provider_id,
                    provider_tool_name=manifest.tool_id,
                    display_name=manifest.name,
                    description=manifest.description,
                    version=manifest.version,
                    capabilities=list(manifest.capabilities),
                    input_schema=dict(manifest.input_schema),
                    output_schema=dict(manifest.output_schema),
                    permissions=list(manifest.permissions),
                    safety_policy=ToolSafetyPolicy(
                        filesystem=_filesystem_policy(manifest.permissions),
                        network="provider_declared"
                        if manifest.security_policy.get("network") is True
                        else "none",
                        user_approval="high_risk_only",
                        secrets="none",
                        sandbox="not_required",
                        max_runtime_ms=max_runtime_ms,
                    ),
                    timeout_ms=max_runtime_ms,
                    examples=list(manifest.examples),
                    node_template=manifest.node_templates[0]
                    if manifest.node_templates
                    else None,
                    enabled=True,
                )
            )
        return tools

    def call_tool(
        self,
        invocation: UnifiedToolInvocation,
        *,
        timeout_ms: int | None = None,
    ) -> UnifiedToolResult:
        provider_tool_id = invocation.tool_id.removeprefix("internal:")
        operation = str(invocation.arguments.get("operation", ""))
        arguments = {
            key: value
            for key, value in invocation.arguments.items()
            if key != "operation"
        }

        try:
            result = self.executor.run(
                ToolInvocation(
                    tool_id=provider_tool_id,
                    operation=operation,
                    arguments=arguments,
                    project_path=invocation.project_path or "",
                    allowed_roots=invocation.allowed_roots,
                    timeout_ms=timeout_ms,
                )
            )
        except Exception as error:
            return UnifiedToolResult(
                ok=False,
                content=[],
                structured_content=None,
                artifacts=[],
                metadata={},
                error=UnifiedToolError(
                    code=getattr(error, "code", "tool_failed"),
                    message=str(error),
                    recoverable=False,
                ),
            )

        return UnifiedToolResult(
            ok=True,
            content=[
                ToolResultContent(type="json", value=result.values),
                *[
                    ToolResultContent(type="artifact", path=artifact)
                    for artifact in result.artifacts
                ],
            ],
            structured_content=dict(result.values),
            artifacts=list(result.artifacts),
            metadata=dict(result.metadata),
        )


def _filesystem_policy(permissions: list[str]) -> str:
    if "write_project_outputs" in permissions:
        return "project_write"
    if "read_project_files" in permissions:
        return "project_read"
    return "none"
