from __future__ import annotations

from pydantic import BaseModel, Field

from agent_service.tool_protocol import UnifiedToolDefinition, equivalent_tool_ids
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


def resolve_tools_for_task(
    tools: list[UnifiedToolDefinition],
    *,
    task_text: str,
    disabled_tool_ids: list[str] | None = None,
    approved_permissions: list[str] | None = None,
) -> list[UnifiedToolDefinition]:
    disabled = _expand_tool_id_set(disabled_tool_ids or [])
    approved = set(approved_permissions or [])
    task_text_lower = task_text.lower()
    selected: list[UnifiedToolDefinition] = []

    for tool in tools:
        if equivalent_tool_ids(tool.id) & disabled:
            continue
        if _requires_unapproved_permission(tool, approved):
            continue
        if _tool_matches_task(tool, task_text_lower):
            selected.append(tool)

    return selected


def _expand_tool_id_set(tool_ids: list[str]) -> set[str]:
    expanded: set[str] = set()
    for tool_id in tool_ids:
        expanded.update(equivalent_tool_ids(tool_id))
    return expanded


def _requires_unapproved_permission(
    tool: UnifiedToolDefinition, approved_permissions: set[str]
) -> bool:
    if tool.safety_policy.user_approval == "never":
        return False
    if tool.safety_policy.user_approval == "high_risk_only":
        high_risk_permissions = {
            permission
            for permission in tool.permissions
            if "delete" in permission
            or "external" in permission
            or "network" in permission
        }
        return bool(high_risk_permissions - approved_permissions)
    return bool(set(tool.permissions) - approved_permissions)


def _tool_matches_task(tool: UnifiedToolDefinition, task_text_lower: str) -> bool:
    capabilities = set(tool.capabilities)
    if _looks_like_document_task(task_text_lower):
        return bool(
            capabilities
            & {
                "document_conversion",
                "document.convert.markdown",
                "document_input",
            }
        )
    if _looks_like_web_task(task_text_lower):
        return bool(capabilities & {"web_search", "documentation_search"})
    return "external_mcp" not in capabilities


def _looks_like_document_task(task_text_lower: str) -> bool:
    return any(
        token in task_text_lower
        for token in ["document", "docx", "pdf", "markdown", "report", "convert"]
    )


def _looks_like_web_task(task_text_lower: str) -> bool:
    return any(
        token in task_text_lower
        for token in ["search", "research", "current", "website", "docs"]
    )
