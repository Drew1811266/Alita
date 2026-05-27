from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_service.goal_spec import GoalSpec
from agent_service.schemas import (
    AgentMessageRequest,
    RunGraph,
    RunGraphRequest,
    RunMode,
    UserMessage,
)


InquiryChoice = Literal["quick_answer", "research_flow"]


class AgentRunState(BaseModel):
    task_id: str
    message: UserMessage
    run_id: str | None = None
    goal_spec: GoalSpec | None = None
    current_graph: RunGraph | None = None
    has_run_history: bool = False
    artifact_refs: list[str] = Field(default_factory=list)
    pending_choice: dict[str, Any] | None = None
    inquiry_choice: InquiryChoice | None = None
    route_decision: dict[str, Any] | None = None
    intent: str | None = None
    project_path: str | None = None
    run_mode: RunMode | None = None
    disabled_tool_ids: list[str] = Field(default_factory=list)
    approved_permissions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_message_request(cls, request: AgentMessageRequest) -> "AgentRunState":
        return cls(
            task_id=request.task_id,
            message=request.to_user_message(),
            inquiry_choice=request.inquiry_choice,
            current_graph=request.currentGraph,
            has_run_history=bool(request.hasRunHistory),
            artifact_refs=list(request.artifactRefs or []),
            pending_choice=request.pendingChoice,
        )

    @classmethod
    def from_user_message(
        cls,
        message: UserMessage,
        *,
        inquiry_choice: InquiryChoice | None = None,
        current_graph: RunGraph | None = None,
        has_run_history: bool = False,
        artifact_refs: list[str] | None = None,
        pending_choice: dict[str, Any] | None = None,
    ) -> "AgentRunState":
        return cls(
            task_id=message.task_id,
            message=message,
            inquiry_choice=inquiry_choice,
            current_graph=current_graph,
            has_run_history=has_run_history,
            artifact_refs=list(artifact_refs or []),
            pending_choice=pending_choice,
        )

    @classmethod
    def from_run_graph_request(cls, request: RunGraphRequest) -> "AgentRunState":
        return cls(
            task_id=request.task_id,
            run_id=request.run_id,
            message=UserMessage(
                task_id=request.task_id,
                content=str(request.graph.metadata.get("question", "")),
                attachments=list(request.attachments),
                model_session_id=request.model_session_id,
            ),
            current_graph=request.graph,
            project_path=request.project_path,
            run_mode=request.mode,
            disabled_tool_ids=list(request.disabled_tool_ids),
            approved_permissions=list(request.approved_permissions),
        )

    def with_routing(
        self,
        *,
        intent: str,
        route_decision: dict[str, Any],
        goal_spec: GoalSpec,
    ) -> "AgentRunState":
        return self.model_copy(
            update={
                "intent": intent,
                "route_decision": route_decision,
                "goal_spec": goal_spec,
            }
        )
