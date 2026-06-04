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
    thread_id: str | None = None
    goal_spec: GoalSpec | None = None
    current_graph: RunGraph | None = None
    has_run_history: bool = False
    artifact_refs: list[str] = Field(default_factory=list)
    pending_choice: dict[str, Any] | None = None
    inquiry_choice: InquiryChoice | None = None
    route_decision: dict[str, Any] | None = None
    structured_route_decision: dict[str, Any] | None = None
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
            thread_id=_thread_id_from_pending_choice(request.pendingChoice),
            run_id=_run_id_from_pending_choice(request.pendingChoice),
            project_path=request.projectPath,
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
        run_id: str | None = None,
        thread_id: str | None = None,
        project_path: str | None = None,
    ) -> "AgentRunState":
        return cls(
            task_id=message.task_id,
            message=message,
            run_id=run_id or _run_id_from_pending_choice(pending_choice),
            thread_id=thread_id or _thread_id_from_pending_choice(pending_choice),
            inquiry_choice=inquiry_choice,
            current_graph=current_graph,
            has_run_history=has_run_history,
            artifact_refs=list(artifact_refs or []),
            pending_choice=pending_choice,
            project_path=project_path,
        )

    @classmethod
    def from_run_graph_request(cls, request: RunGraphRequest) -> "AgentRunState":
        return cls(
            task_id=request.task_id,
            run_id=request.run_id,
            thread_id=None,
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
        structured_route_decision: dict[str, Any] | None = None,
    ) -> "AgentRunState":
        update: dict[str, Any] = {
            "intent": intent,
            "route_decision": route_decision,
            "goal_spec": goal_spec,
        }
        if structured_route_decision is not None:
            update["structured_route_decision"] = structured_route_decision
        return self.model_copy(update=update)


def _thread_id_from_pending_choice(
    pending_choice: dict[str, Any] | None,
) -> str | None:
    if not pending_choice:
        return None
    thread_id = pending_choice.get("threadId")
    return str(thread_id) if thread_id else None


def _run_id_from_pending_choice(
    pending_choice: dict[str, Any] | None,
) -> str | None:
    if not pending_choice:
        return None
    run_id = pending_choice.get("runId")
    return str(run_id) if run_id else None
