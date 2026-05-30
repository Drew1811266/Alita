from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from agent_service.agent_run_state import AgentRunState
from agent_service.graph import run_agent_from_state
from agent_service.runtime_state import (
    RuntimeState,
    RuntimeStateDelta,
    initial_runtime_state,
)
from agent_service.schemas import AgentEvent, UserMessage


@dataclass(frozen=True)
class RuntimeEngineResult:
    state: RuntimeState
    events: list[AgentEvent]


class AgentRuntimeEngine:
    def start_run(
        self,
        *,
        message: UserMessage,
        project_path: str,
        run_id: str | None = None,
        thread_id: str | None = None,
    ) -> RuntimeEngineResult:
        state = initial_runtime_state(
            message=message,
            project_path=project_path,
            run_id=run_id or f"run-{uuid4()}",
            thread_id=thread_id,
        )
        return RuntimeEngineResult(
            state=state,
            events=[
                AgentEvent(
                    type="runtime.run_started",
                    payload={
                        "runId": state.run_id,
                        "threadId": state.thread_id,
                        "taskId": state.task_id,
                        "stage": state.stage,
                    },
                )
            ],
        )

    def step(self, state: RuntimeState) -> list[AgentEvent]:
        message = _message_from_state(state)
        run_state = AgentRunState.from_user_message(message).model_copy(
            update={
                "project_path": state.project_path,
                "run_id": state.run_id,
            }
        )
        routed_events = run_agent_from_state(run_state)
        delta = RuntimeStateDelta(
            previous_checkpoint_id=None,
            checkpoint_id=f"{state.run_id}:route:0",
            stage_before=state.stage,
            stage_after="plan",
            decision={"kind": "route_and_plan"},
            emitted_events=[event.model_dump() for event in routed_events],
        )
        return [
            AgentEvent(
                type="runtime.state_delta",
                payload={"delta": delta.model_dump()},
            ),
            *routed_events,
        ]

    def resume(
        self,
        state: RuntimeState,
        checkpoint_id: str | None = None,
    ) -> list[AgentEvent]:
        return [
            AgentEvent(
                type="runtime.resume_requested",
                payload={
                    "runId": state.run_id,
                    "threadId": state.thread_id,
                    "checkpointId": checkpoint_id,
                },
            )
        ]

    def interrupt(self, state: RuntimeState, *, reason: str) -> RuntimeEngineResult:
        interrupted = state.model_copy(update={"stage": "interrupted"})
        return RuntimeEngineResult(
            state=interrupted,
            events=[
                AgentEvent(
                    type="runtime.interrupted",
                    payload={
                        "runId": state.run_id,
                        "threadId": state.thread_id,
                        "reason": reason,
                    },
                )
            ],
        )


def _message_from_state(state: RuntimeState) -> UserMessage:
    first_message = state.messages[0] if state.messages else {}
    return UserMessage(
        task_id=state.task_id,
        content=str(first_message.get("content") or ""),
    )
