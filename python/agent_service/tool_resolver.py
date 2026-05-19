from __future__ import annotations

from pydantic import BaseModel, Field

from agent_service.tool_registry import ToolRegistry


class ToolResolutionError(ValueError):
    pass


class ResolvedToolBinding(BaseModel):
    tool_id: str
    operation: str
    arguments_template: dict[str, str] = Field(default_factory=dict)
    binding_reason: str
    required_permissions: list[str] = Field(default_factory=list)


def resolve_tool_binding(
    *,
    registry: ToolRegistry,
    required_capability: str,
    operation: str,
    disabled_tool_ids: list[str] | None = None,
) -> ResolvedToolBinding:
    for tool in registry.enabled_tools(disabled_tool_ids=disabled_tool_ids):
        if (
            required_capability in tool.capabilities
            and registry.has_operation(tool.tool_id, operation)
        ):
            return ResolvedToolBinding(
                tool_id=tool.tool_id,
                operation=operation,
                binding_reason=(
                    f"Resolved capability '{required_capability}' "
                    f"to tool '{tool.tool_id}'."
                ),
                required_permissions=list(tool.permissions),
            )

    raise ToolResolutionError(
        f"No enabled tool found for capability '{required_capability}' "
        f"and operation '{operation}'."
    )
