from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AgentRuntimeStage = Literal[
    "route",
    "plan",
    "execute",
    "observe",
    "verify",
    "replan",
    "final",
    "failed",
]


class AgentRuntimeGraphState(BaseModel):
    task_id: str
    message: str
    project_path: str
    stage: AgentRuntimeStage = "route"
    graph_payload: dict[str, Any] | None = None
    run_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRuntimeGraph:
    version = "agent_runtime_graph.v1"

    def route(self, state: AgentRuntimeGraphState) -> AgentRuntimeGraphState:
        return state.model_copy(update={"stage": "plan"})

    def plan_ready(self, state: AgentRuntimeGraphState) -> AgentRuntimeGraphState:
        if state.graph_payload is None:
            return state.model_copy(
                update={
                    "stage": "failed",
                    "error_code": "missing_graph",
                    "error_message": "runtime graph cannot execute without a graph payload",
                }
            )
        return state.model_copy(update={"stage": "execute"})

    def execution_ready(self, state: AgentRuntimeGraphState) -> AgentRuntimeGraphState:
        return state.model_copy(update={"stage": "observe"})

    def final(self, state: AgentRuntimeGraphState) -> AgentRuntimeGraphState:
        return state.model_copy(update={"stage": "final"})


def runtime_metadata(stage: AgentRuntimeStage) -> dict[str, str]:
    return {"version": AgentRuntimeGraph.version, "stage": stage}
