from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agent_service.agent_run_state import AgentRunState
from agent_service.action_graph import action_graph_from_run_graph
from agent_service.graph import run_agent_from_state, stream_agent_events_from_state
from agent_service.runtime_state import (
    RuntimeState,
    RuntimeStateDelta,
    initial_runtime_state,
)
from agent_service.runtime_store import RuntimeStore
from agent_service.schemas import AgentEvent, RunGraph, UserMessage


@dataclass(frozen=True)
class RuntimeEngineResult:
    state: RuntimeState
    events: list[AgentEvent]


RouteRunner = Callable[..., list[AgentEvent]]
StreamRunner = Callable[..., Any]


class AgentRuntimeEngine:
    def __init__(
        self,
        *,
        route_runner: RouteRunner = run_agent_from_state,
        stream_runner: StreamRunner = stream_agent_events_from_state,
        runtime_store: RuntimeStore | None = None,
    ) -> None:
        self.route_runner = route_runner
        self.stream_runner = stream_runner
        self.runtime_store = runtime_store

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

    def run_from_state(
        self,
        run_state: AgentRunState,
        *,
        model_client: Any | None = None,
        search_provider: Any | None = None,
        weather_provider: Any | None = None,
    ) -> RuntimeEngineResult:
        started = self.start_run(
            message=run_state.message,
            project_path=run_state.project_path or "project.alita",
            run_id=run_state.run_id,
        )
        self._write_state(started.state)
        route_events, next_state = self._legacy_route_and_plan(
            started.state,
            run_state,
            model_client=model_client,
            search_provider=search_provider,
            weather_provider=weather_provider,
        )
        return RuntimeEngineResult(
            state=next_state,
            events=[*started.events, *route_events],
        )

    def stream_from_state(
        self,
        run_state: AgentRunState,
        *,
        model_client: Any | None = None,
        search_provider: Any | None = None,
        weather_provider: Any | None = None,
    ):
        started = self.start_run(
            message=run_state.message,
            project_path=run_state.project_path or "project.alita",
            run_id=run_state.run_id,
        )
        self._write_state(started.state)
        for event in started.events:
            yield event

        emitted_events: list[AgentEvent] = []
        for event in self.stream_runner(
            run_state,
            model_client=model_client,
            search_provider=search_provider,
            weather_provider=weather_provider,
        ):
            emitted_events.append(event)
            yield event

        next_state = started.state.model_copy(update={"stage": "plan"})
        delta = RuntimeStateDelta(
            previous_checkpoint_id=None,
            checkpoint_id=f"{started.state.run_id}:route:0",
            stage_before=started.state.stage,
            stage_after=next_state.stage,
            decision={"kind": "legacy_route_and_plan"},
            emitted_events=[event.model_dump() for event in emitted_events],
        )
        self._write_delta(delta)
        self._write_state(next_state)
        yield AgentEvent(
            type="runtime.state_delta",
            payload={"delta": delta.model_dump()},
        )

    def step(self, state: RuntimeState) -> list[AgentEvent]:
        if state.stage == "route":
            return self._advance_stage(state, stage_after="context", decision={"kind": "route"})
        if state.stage == "context":
            return self._advance_stage(
                state,
                stage_after="plan",
                decision={"kind": "context.build"},
                writes=[{"kind": "context_bundle", "contextBundle": state.context_bundle or {}}],
            )
        if state.stage == "plan":
            return self._plan_legacy_action_graph(state)
        if state.stage == "act":
            return self._advance_stage(
                state,
                stage_after="observe",
                decision={"kind": "act.select"},
            )
        if state.stage == "observe":
            return self._advance_stage(
                state,
                stage_after="verify",
                decision={"kind": "observe"},
            )
        if state.stage == "verify":
            return self._advance_stage(
                state,
                stage_after="final",
                decision={"kind": "verify"},
            )
        return self._advance_stage(
            state,
            stage_after=state.stage,
            decision={"kind": "noop", "stage": state.stage},
        )

    def _plan_legacy_action_graph(self, state: RuntimeState) -> list[AgentEvent]:
        message = _message_from_state(state)
        run_state = AgentRunState.from_user_message(message).model_copy(
            update={
                "project_path": state.project_path,
                "run_id": state.run_id,
            }
        )
        routed_events = self.route_runner(run_state)
        action_graph = _action_graph_from_events(routed_events)
        writes: list[dict[str, Any]] = []
        if action_graph is not None:
            writes.append({"kind": "action_graph", "actionGraph": action_graph})
        next_state = state.model_copy(
            update={
                "stage": "act",
                "action_graph": action_graph,
            }
        )
        delta = RuntimeStateDelta(
            previous_checkpoint_id=None,
            checkpoint_id=f"{state.run_id}:plan:0",
            stage_before=state.stage,
            stage_after=next_state.stage,
            decision={"kind": "legacy_plan_action_graph"},
            writes=writes,
            emitted_events=[event.model_dump() for event in routed_events],
        )
        self._write_delta(delta)
        self._write_state(next_state)
        return [
            AgentEvent(type="runtime.state_delta", payload={"delta": delta.model_dump()}),
            *routed_events,
        ]

    def _advance_stage(
        self,
        state: RuntimeState,
        *,
        stage_after: str,
        decision: dict[str, Any],
        writes: list[dict[str, Any]] | None = None,
    ) -> list[AgentEvent]:
        next_state = state.model_copy(update={"stage": stage_after})
        delta = RuntimeStateDelta(
            previous_checkpoint_id=None,
            checkpoint_id=f"{state.run_id}:{state.stage}:0",
            stage_before=state.stage,
            stage_after=next_state.stage,
            decision=decision,
            writes=list(writes or []),
        )
        self._write_delta(delta)
        self._write_state(next_state)
        return [AgentEvent(type="runtime.state_delta", payload={"delta": delta.model_dump()})]

    def _legacy_route_and_plan(
        self,
        state: RuntimeState,
        run_state: AgentRunState,
        *,
        model_client: Any | None = None,
        search_provider: Any | None = None,
        weather_provider: Any | None = None,
    ) -> tuple[list[AgentEvent], RuntimeState]:
        routed_events = self.route_runner(
            run_state,
            model_client=model_client,
            search_provider=search_provider,
            weather_provider=weather_provider,
        )
        next_state = state.model_copy(update={"stage": "plan"})
        delta = RuntimeStateDelta(
            previous_checkpoint_id=None,
            checkpoint_id=f"{state.run_id}:route:0",
            stage_before=state.stage,
            stage_after=next_state.stage,
            decision={"kind": "legacy_route_and_plan"},
            emitted_events=[event.model_dump() for event in routed_events],
        )
        self._write_delta(delta)
        self._write_state(next_state)
        return [
            AgentEvent(
                type="runtime.state_delta",
                payload={"delta": delta.model_dump()},
            ),
            *routed_events,
        ], next_state

    def _write_state(self, state: RuntimeState) -> None:
        if self.runtime_store is not None:
            self.runtime_store.write_state(state)

    def _write_delta(self, delta: RuntimeStateDelta) -> None:
        if self.runtime_store is not None:
            self.runtime_store.write_delta(delta)

    def resume(
        self,
        state: RuntimeState,
        checkpoint_id: str | None = None,
    ) -> RuntimeEngineResult:
        events = [
            AgentEvent(
                type="runtime.resume_requested",
                payload={
                    "runId": state.run_id,
                    "threadId": state.thread_id,
                    "checkpointId": checkpoint_id,
                },
            )
        ]
        restored_state = None
        restored_checkpoint_id = checkpoint_id
        if self.runtime_store is not None:
            checkpoint = self.runtime_store.read_checkpoint_record(checkpoint_id)
            if checkpoint is not None:
                restored_checkpoint_id = str(checkpoint.get("checkpointId") or checkpoint_id)
                restored_state = self.runtime_store.restore_state(checkpoint_id)

        next_state = restored_state or state
        if restored_state is not None:
            events.append(
                AgentEvent(
                    type="runtime.resumed",
                    payload={
                        "runId": next_state.run_id,
                        "threadId": next_state.thread_id,
                        "checkpointId": restored_checkpoint_id,
                        "stage": next_state.stage,
                    },
                )
            )
            self._write_state(next_state)
        return RuntimeEngineResult(state=next_state, events=events)

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


def _action_graph_from_events(events: list[AgentEvent]) -> dict[str, Any] | None:
    graph_event = next(
        (event for event in events if event.type == "node_graph.created"),
        None,
    )
    if graph_event is None:
        return None
    graph_payload = graph_event.payload.get("graph")
    if not isinstance(graph_payload, dict):
        return None
    graph = RunGraph.model_validate(graph_payload)
    return action_graph_from_run_graph(graph).model_dump()
