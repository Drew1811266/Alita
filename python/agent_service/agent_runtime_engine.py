from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from agent_service.agent_run_state import AgentRunState
from agent_service.action_graph import action_graph_from_run_graph
from agent_service.deep_agent_runtime_graph import (
    run_deep_agent_runtime,
    stream_deep_agent_runtime_events,
)
from agent_service.deep_agent_runtime_models import PlanningResumeCommand
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
DeepRuntimeRunner = Callable[..., list[AgentEvent]]
DeepRuntimeStreamRunner = Callable[..., Any]
StreamRunner = Callable[..., Any]
_DEFAULT_DEEP_RUNTIME_STREAM_RUNNER = object()


@dataclass(frozen=True)
class DeepAgentProductPathDecision:
    kind: Literal["handled", "allow_legacy_response", "blocked"]
    reason: str


class AgentRuntimeEngine:
    def __init__(
        self,
        *,
        route_runner: RouteRunner = run_agent_from_state,
        deep_runtime_runner: DeepRuntimeRunner = run_deep_agent_runtime,
        deep_runtime_stream_runner: DeepRuntimeStreamRunner
        | object = _DEFAULT_DEEP_RUNTIME_STREAM_RUNNER,
        stream_runner: StreamRunner = stream_agent_events_from_state,
        runtime_store: RuntimeStore | None = None,
        allow_legacy_task_product_path: bool = False,
    ) -> None:
        self.route_runner = route_runner
        self.deep_runtime_runner = deep_runtime_runner
        if deep_runtime_stream_runner is _DEFAULT_DEEP_RUNTIME_STREAM_RUNNER:
            self.deep_runtime_stream_runner = (
                stream_deep_agent_runtime_events
                if deep_runtime_runner is run_deep_agent_runtime
                else deep_runtime_runner
            )
        else:
            self.deep_runtime_stream_runner = deep_runtime_stream_runner
        self.stream_runner = stream_runner
        self.runtime_store = runtime_store
        self.allow_legacy_task_product_path = allow_legacy_task_product_path

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
            thread_id=run_state.thread_id,
        )
        self._write_state(started.state)
        deep_events = self.deep_runtime_runner(
            run_state.message,
            project_path=run_state.project_path or "project.alita",
            run_id=started.state.run_id,
            thread_id=started.state.thread_id,
            model_client=model_client,
            runtime_store=self.runtime_store,
            resume_command=planning_resume_command_from_pending_choice(
                run_state.pending_choice,
                answer_fallback=run_state.message.content,
            ),
        )
        decision = _deep_agent_product_path_decision(deep_events)
        if decision.kind == "handled":
            next_state = started.state.model_copy(
                update={"stage": _deep_agent_handled_stage(deep_events)}
            )
            self._write_state(next_state)
            return RuntimeEngineResult(
                state=next_state,
                events=[*started.events, *deep_events],
            )
        if decision.kind == "blocked":
            next_state = started.state.model_copy(update={"stage": "failed"})
            blocked_events = _deep_agent_product_path_blocked_events(
                next_state,
                reason=decision.reason,
            )
            delta_event = self._record_transition(
                started.state,
                next_state,
                checkpoint_label="deep-agent-product-path-blocked",
                decision={
                    "kind": "deep_agent_product_path_blocked",
                    "reason": decision.reason,
                },
                emitted_events=blocked_events,
            )
            return RuntimeEngineResult(
                state=next_state,
                events=[*started.events, *deep_events, delta_event, *blocked_events],
            )
        route_events, next_state = self._legacy_response_only(
            started.state,
            run_state,
            model_client=model_client,
            search_provider=search_provider,
            weather_provider=weather_provider,
        )
        return RuntimeEngineResult(
            state=next_state,
            events=[*started.events, *deep_events, *route_events],
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
            thread_id=run_state.thread_id,
        )
        self._write_state(started.state)
        for event in started.events:
            yield event

        deep_events: list[AgentEvent] = []
        for event in self.deep_runtime_stream_runner(
            run_state.message,
            project_path=run_state.project_path or "project.alita",
            run_id=started.state.run_id,
            thread_id=started.state.thread_id,
            model_client=model_client,
            runtime_store=self.runtime_store,
            resume_command=planning_resume_command_from_pending_choice(
                run_state.pending_choice,
                answer_fallback=run_state.message.content,
            ),
        ):
            deep_events.append(event)
            yield event
        decision = _deep_agent_product_path_decision(deep_events)
        if decision.kind == "handled":
            next_state = started.state.model_copy(
                update={"stage": _deep_agent_handled_stage(deep_events)}
            )
            self._write_state(next_state)
            return
        if decision.kind == "blocked":
            next_state = started.state.model_copy(update={"stage": "failed"})
            blocked_events = _deep_agent_product_path_blocked_events(
                next_state,
                reason=decision.reason,
            )
            yield self._record_transition(
                started.state,
                next_state,
                checkpoint_label="deep-agent-product-path-blocked",
                decision={
                    "kind": "deep_agent_product_path_blocked",
                    "reason": decision.reason,
                },
                emitted_events=blocked_events,
            )
            for event in blocked_events:
                yield event
            return

        emitted_events: list[AgentEvent] = []
        for event in self.stream_runner(
            run_state,
            model_client=model_client,
            search_provider=search_provider,
            weather_provider=weather_provider,
        ):
            emitted_events.append(event)
            blocked_event_types = _legacy_graph_event_types(emitted_events)
            if blocked_event_types:
                next_state = started.state.model_copy(update={"stage": "failed"})
                blocked_events = _legacy_graph_blocked_events(
                    next_state,
                    blocked_event_types=blocked_event_types,
                )
                yield self._record_transition(
                    started.state,
                    next_state,
                    checkpoint_label="legacy-stream-blocked",
                    decision={
                        "kind": "legacy_graph_blocked",
                        "blockedEventTypes": blocked_event_types,
                    },
                    emitted_events=blocked_events,
                )
                for blocked_event in blocked_events:
                    yield blocked_event
                return
            yield event

        next_state = started.state.model_copy(update={"stage": "plan"})
        delta = RuntimeStateDelta(
            previous_checkpoint_id=None,
            checkpoint_id=f"{started.state.run_id}:route:0",
            stage_before=started.state.stage,
            stage_after=next_state.stage,
            decision={"kind": "legacy_response_only"},
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
            if not self.allow_legacy_task_product_path:
                blocked_events = _legacy_graph_blocked_events(
                    state,
                    blocked_event_types=["legacy_plan_action_graph"],
                    reason=(
                        "legacy plan action graph is blocked from the Agent Runtime "
                        "product path"
                    ),
                )
                next_state = state.model_copy(update={"stage": "failed"})
                return [
                    self._record_transition(
                        state,
                        next_state,
                        checkpoint_label="legacy-plan-blocked",
                        decision={
                            "kind": "legacy_graph_blocked",
                            "blockedEventTypes": ["legacy_plan_action_graph"],
                        },
                        emitted_events=blocked_events,
                    ),
                    *blocked_events,
                ]
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

    def _record_transition(
        self,
        state: RuntimeState,
        next_state: RuntimeState,
        *,
        checkpoint_label: str,
        decision: dict[str, Any],
        writes: list[dict[str, Any]] | None = None,
        emitted_events: list[AgentEvent] | None = None,
    ) -> AgentEvent:
        delta = RuntimeStateDelta(
            previous_checkpoint_id=None,
            checkpoint_id=f"{state.run_id}:{checkpoint_label}:0",
            stage_before=state.stage,
            stage_after=next_state.stage,
            decision=decision,
            writes=list(writes or []),
            emitted_events=[
                event.model_dump() for event in list(emitted_events or [])
            ],
        )
        self._write_delta(delta)
        self._write_state(next_state)
        return AgentEvent(type="runtime.state_delta", payload={"delta": delta.model_dump()})

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

    def _legacy_response_only(
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
        blocked_event_types = _legacy_graph_event_types(routed_events)
        if blocked_event_types:
            blocked_events = _legacy_graph_blocked_events(
                state,
                blocked_event_types=blocked_event_types,
            )
            next_state = state.model_copy(update={"stage": "failed"})
            return [
                self._record_transition(
                    state,
                    next_state,
                    checkpoint_label="legacy-response-blocked",
                    decision={
                        "kind": "legacy_graph_blocked",
                        "blockedEventTypes": blocked_event_types,
                    },
                    emitted_events=blocked_events,
                ),
                *blocked_events,
            ], next_state
        next_state = state.model_copy(update={"stage": "plan"})
        delta = RuntimeStateDelta(
            previous_checkpoint_id=None,
            checkpoint_id=f"{state.run_id}:route:0",
            stage_before=state.stage,
            stage_after=next_state.stage,
            decision={"kind": "legacy_response_only"},
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


_LEGACY_GRAPH_EVENT_TYPES = {
    "node_graph.created",
    "planning.graph_compiled",
    "planning.graph_review_completed",
    "agent_plan_graph.compile_started",
    "agent_plan_graph.compiled",
    "agent_plan_graph.compile_review_completed",
    "agent_plan_graph.execution_ready",
    "graph.replanned",
    "graph.overwrite_confirmation_required",
}


def _deep_agent_product_path_decision(
    events: list[AgentEvent],
) -> DeepAgentProductPathDecision:
    handled_event_types = {
        "node_graph.created",
        "planning.clarification_required",
        "planning.confirmation_required",
        "planning.interrupted",
        "planning.confirmed",
        "planning.cancelled",
        "planning.failed",
        "agent_plan_graph.compile_failed",
        "agent_plan_graph.execution_ready",
    }
    if any(event.type in handled_event_types for event in events):
        return DeepAgentProductPathDecision(
            kind="handled",
            reason="deep_agent_runtime_emitted_terminal_event",
        )

    for event in reversed(events):
        if event.type == "reasoning.completed":
            next_action = _event_next_action(event)
            if next_action in {"simple_answer", "tool_action", "bounded_tool"}:
                return DeepAgentProductPathDecision(
                    kind="allow_legacy_response",
                    reason=f"deep_agent_runtime_allowed_response_path:{next_action}",
                )
            return DeepAgentProductPathDecision(
                kind="blocked",
                reason=f"deep_agent_runtime_incomplete_for:{next_action or 'unknown'}",
            )
        if event.type == "reasoning.decision_created":
            next_action = _event_next_action(event)
            if next_action in {"deep_planning", "clarification"}:
                return DeepAgentProductPathDecision(
                    kind="blocked",
                    reason=f"deep_agent_runtime_missing_terminal_event:{next_action}",
                )

    return DeepAgentProductPathDecision(
        kind="blocked",
        reason="deep_agent_runtime_emitted_no_product_path_decision",
    )


def _deep_agent_handled_stage(events: list[AgentEvent]) -> Literal["plan", "failed"]:
    failure_event_types = {
        "planning.failed",
        "agent_plan_graph.compile_failed",
    }
    if any(event.type in failure_event_types for event in events):
        return "failed"
    return "plan"


def _event_next_action(event: AgentEvent) -> str:
    payload = event.payload if isinstance(event.payload, dict) else {}
    decision = payload.get("decision")
    source = decision if isinstance(decision, dict) else payload
    return str(source.get("nextAction") or source.get("next_action") or "")


def _deep_agent_product_path_blocked_events(
    state: RuntimeState,
    *,
    reason: str,
) -> list[AgentEvent]:
    return [
        AgentEvent(
            type="runtime.deep_agent_product_path_blocked",
            payload={
                "runId": state.run_id,
                "threadId": state.thread_id,
                "taskId": state.task_id,
                "reason": reason,
            },
        ),
        AgentEvent(
            type="task.failed",
            payload={
                "taskId": state.task_id,
                "runId": state.run_id,
                "errorCode": "deep_agent_product_path_incomplete",
                "error": (
                    "Deep Agent runtime did not emit a terminal product-path event; "
                    "legacy graph fallback is blocked."
                ),
                "reason": reason,
            },
        ),
    ]


def _legacy_graph_event_types(events: list[AgentEvent]) -> list[str]:
    return [
        event.type for event in events if event.type in _LEGACY_GRAPH_EVENT_TYPES
    ]


def _legacy_graph_blocked_events(
    state: RuntimeState,
    *,
    blocked_event_types: list[str],
    reason: str | None = None,
) -> list[AgentEvent]:
    if reason is None:
        reason = _legacy_graph_blocked_reason(blocked_event_types)
    return [
        AgentEvent(
            type="runtime.legacy_graph_blocked",
            payload={
                "runId": state.run_id,
                "threadId": state.thread_id,
                "taskId": state.task_id,
                "reason": reason,
                "blockedEventTypes": blocked_event_types,
            },
        ),
        AgentEvent(
            type="task.failed",
            payload={
                "taskId": state.task_id,
                "runId": state.run_id,
                "errorCode": "legacy_graph_blocked",
                "error": (
                    "Legacy graph creation is blocked from the Agent Runtime "
                    "product path."
                ),
                "blockedEventTypes": blocked_event_types,
            },
        ),
    ]


def _legacy_graph_blocked_reason(blocked_event_types: list[str]) -> str:
    if "legacy_plan_action_graph" in blocked_event_types:
        return "legacy plan action graph is blocked from the Agent Runtime product path"
    return "legacy graph event emitted from response-only fallback"


def planning_resume_command_from_pending_choice(
    pending_choice: dict[str, Any] | None,
    *,
    answer_fallback: str | None = None,
) -> PlanningResumeCommand | None:
    if not pending_choice:
        return None
    kind = str(pending_choice.get("kind") or "")
    if kind == "planning.clarification":
        return PlanningResumeCommand.model_validate(
            {
                "kind": "clarification_answer",
                "threadId": pending_choice.get("threadId"),
                "runId": pending_choice.get("runId"),
                "answer": pending_choice.get("answer") or answer_fallback or "",
            }
        )
    if kind == "planning.confirmation":
        return PlanningResumeCommand.model_validate(
            {
                "kind": "confirmation",
                "threadId": pending_choice.get("threadId"),
                "runId": pending_choice.get("runId"),
                "decision": pending_choice.get("decision"),
                "revisionInstructions": (
                    pending_choice.get("revisionInstructions")
                    or pending_choice.get("revision_instructions")
                    or []
                ),
            }
        )
    return None


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
