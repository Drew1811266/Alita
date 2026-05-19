from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from agent_service.goal_spec import GoalSpec, TaskType
from agent_service.schemas import UserMessage
from agent_service.tool_registry import ToolRegistry


class AttachmentContext(BaseModel):
    attachment_id: str
    name: str
    path: str
    size_bytes: int
    mime_type: str


class ToolCapability(BaseModel):
    tool_id: str
    name: str
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
) -> ContextBundle:
    project_file = Path(project_path)
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
        available_tools=[
            ToolCapability(
                tool_id=tool.tool_id,
                name=tool.name,
                capabilities=list(tool.capabilities),
                operations=[operation.name for operation in tool.operations],
                permissions=list(tool.permissions),
                runtime=tool.runtime,
            )
            for tool in tool_registry.enabled_tools()
        ],
        constraints=list(goal_spec.constraints),
    )
