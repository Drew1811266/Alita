from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from agent_service.goal_spec import GoalSpec, TaskType
from agent_service.schemas import UserMessage
from agent_service.tool_gateway import UnifiedToolGateway
from agent_service.tool_protocol import UnifiedToolDefinition
from agent_service.tool_registry import ToolRegistry
from agent_service.tool_resolver import resolve_tools_for_task


class AttachmentContext(BaseModel):
    attachment_id: str
    name: str
    path: str
    size_bytes: int
    mime_type: str


class ToolCapability(BaseModel):
    tool_id: str
    name: str
    source: str = "internal"
    provider_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    operations: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    runtime: str | None = None


class ContextBundle(BaseModel):
    project_path: str
    artifact_dir: str
    goal: str
    task_type: TaskType
    attachments: list[AttachmentContext] = Field(default_factory=list)
    available_tools: list[ToolCapability] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


def build_context_bundle(
    message: UserMessage,
    goal_spec: GoalSpec,
    project_path: str,
    tool_registry: ToolRegistry,
    tool_gateway: UnifiedToolGateway | None = None,
    disabled_tool_ids: list[str] | None = None,
) -> ContextBundle:
    project_file = Path(project_path)
    available_tools = (
        _tool_capabilities_from_unified_catalog(
            resolve_tools_for_task(
                tool_gateway.list_tools(),
                task_text=message.content,
                disabled_tool_ids=disabled_tool_ids or [],
                approved_permissions=[],
            )
        )
        if tool_gateway is not None
        else _tool_capabilities_from_registry(tool_registry)
    )
    return ContextBundle(
        project_path=project_path,
        artifact_dir=str(project_file.parent / "artifacts"),
        goal=goal_spec.goal,
        task_type=goal_spec.task_type,
        attachments=[
            AttachmentContext(
                attachment_id=attachment.attachment_id,
                name=attachment.name,
                path=attachment.path,
                size_bytes=attachment.size_bytes,
                mime_type=attachment.mime_type,
            )
            for attachment in message.attachments
        ],
        available_tools=available_tools,
        constraints=list(goal_spec.constraints),
    )


def _tool_capabilities_from_registry(tool_registry: ToolRegistry) -> list[ToolCapability]:
    return [
        ToolCapability(
            tool_id=tool.tool_id,
            name=tool.name,
            capabilities=list(tool.capabilities),
            operations=[operation.name for operation in tool.operations],
            permissions=list(tool.permissions),
            runtime=tool.runtime,
        )
        for tool in tool_registry.enabled_tools()
    ]


def _tool_capabilities_from_unified_catalog(
    tools: list[UnifiedToolDefinition],
) -> list[ToolCapability]:
    return [
        ToolCapability(
            tool_id=tool.id,
            name=tool.display_name,
            source=tool.source,
            provider_id=tool.provider_id,
            capabilities=list(tool.capabilities),
            operations=_operation_names_from_schema(tool.input_schema),
            permissions=list(tool.permissions),
            runtime=tool.source,
        )
        for tool in tools
    ]


def _operation_names_from_schema(schema: dict) -> list[str]:
    operation = schema.get("properties", {}).get("operation", {})
    enum_values = operation.get("enum", [])
    return [str(value) for value in enum_values]
