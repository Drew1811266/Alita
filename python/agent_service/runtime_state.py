from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_service.schemas import UserMessage


RuntimeStage = Literal[
    "route",
    "context",
    "plan",
    "approve",
    "act",
    "observe",
    "verify",
    "replan",
    "final",
    "failed",
    "interrupted",
]
RuntimeActionType = Literal["model", "tool", "human", "control"]


class RuntimeAction(BaseModel):
    action_id: str
    action_type: RuntimeActionType
    name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected_outputs: dict[str, Any] = Field(default_factory=dict)
    permissions: list[dict[str, Any]] = Field(default_factory=list)
    timeout_ms: int | None = None
    retry_policy: dict[str, Any] | None = None
    dependencies: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeState(BaseModel):
    thread_id: str
    run_id: str
    task_id: str
    project_path: str
    stage: RuntimeStage = "route"
    messages: list[dict[str, Any]] = Field(default_factory=list)
    goal_spec: dict[str, Any] | None = None
    context_bundle: dict[str, Any] | None = None
    action_graph: dict[str, Any] | None = None
    selected_action: RuntimeAction | None = None
    observations: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] | None = None
    pending_approvals: list[dict[str, Any]] = Field(default_factory=list)
    memory_writes: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeStateDelta(BaseModel):
    previous_checkpoint_id: str | None = None
    checkpoint_id: str
    stage_before: RuntimeStage | str
    stage_after: RuntimeStage | str
    decision: dict[str, Any] = Field(default_factory=dict)
    writes: list[dict[str, Any]] = Field(default_factory=list)
    emitted_events: list[dict[str, Any]] = Field(default_factory=list)


def initial_runtime_state(
    *,
    message: UserMessage,
    project_path: str,
    run_id: str,
    thread_id: str | None = None,
) -> RuntimeState:
    return RuntimeState(
        thread_id=thread_id or f"thread-{message.task_id}",
        run_id=run_id,
        task_id=message.task_id,
        project_path=project_path,
        stage="route",
        messages=[
            {
                "role": "user",
                "content": message.content,
                "attachments": [
                    attachment.model_dump() for attachment in message.attachments
                ],
            }
        ],
    )
