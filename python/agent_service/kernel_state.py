from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_service.goal_spec import GoalSpec, parse_goal_spec
from agent_service.intent import classify_route
from agent_service.schemas import AgentEvent, RunGraph, UserMessage


ExecutionMode = Literal["message", "stream", "graph_run"]


class AgentRunBudget(BaseModel):
    max_planning_steps: int = 16
    max_react_steps: int = 0
    max_tool_calls: int = 0
    max_runtime_ms: int = 120_000


class AgentRunState(BaseModel):
    task_id: str
    run_id: str | None = None
    message: UserMessage
    goal_spec: GoalSpec
    route_decision: dict[str, Any]
    current_graph: RunGraph | None = None
    execution_mode: ExecutionMode = "message"
    model_session_id: str | None = None
    disabled_tool_ids: list[str] = Field(default_factory=list)
    approved_permissions: list[str] = Field(default_factory=list)
    has_run_history: bool = False
    artifact_refs: list[str] = Field(default_factory=list)
    pending_choice: dict[str, Any] | None = None
    budget: AgentRunBudget = Field(default_factory=AgentRunBudget)
    events: list[AgentEvent] = Field(default_factory=list)
    journal_ref: str | None = None


def build_agent_run_state(
    message: UserMessage,
    *,
    run_id: str | None = None,
    current_graph: RunGraph | None = None,
    execution_mode: ExecutionMode = "message",
    model_session_id: str | None = None,
    disabled_tool_ids: list[str] | None = None,
    approved_permissions: list[str] | None = None,
    has_run_history: bool = False,
    artifact_refs: list[str] | None = None,
    pending_choice: dict[str, Any] | None = None,
    budget: AgentRunBudget | None = None,
    journal_ref: str | None = None,
) -> AgentRunState:
    goal_spec = parse_goal_spec(message)
    route_decision = classify_route(message).to_payload()
    return AgentRunState(
        task_id=message.task_id,
        run_id=run_id,
        message=message,
        goal_spec=goal_spec,
        route_decision=route_decision,
        current_graph=current_graph,
        execution_mode=execution_mode,
        model_session_id=model_session_id or message.model_session_id,
        disabled_tool_ids=list(disabled_tool_ids or []),
        approved_permissions=list(approved_permissions or []),
        has_run_history=has_run_history,
        artifact_refs=list(artifact_refs or []),
        pending_choice=pending_choice,
        budget=budget or AgentRunBudget(),
        journal_ref=journal_ref,
    )
