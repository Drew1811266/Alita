from __future__ import annotations

import operator
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Annotated, Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from agent_service.agent_plan_compile import (
    AgentCompiledGraph,
    AgentPlanCompileError,
    compile_confirmed_agent_plan_graph,
    review_agent_compiled_graph,
)
from agent_service.agent_execution_runtime import (
    AgentExecutionReview,
    AgentExecutionRunResult,
    review_agent_execution_result,
    run_graph_request_from_agent_compiled_graph,
    summarize_agent_execution_events,
)
from agent_service.context_manager import build_context_bundle
from agent_service.deep_agent_graph_compile import (
    compile_agent_plan_graph,
    review_compiled_graph,
)
from agent_service.deep_agent_checkpoint_mirror import (
    planning_checkpoint_recorded_event,
    planning_checkpoint_summary_from_state,
)
from agent_service.deep_agent_checkpointer import (
    create_deep_planning_checkpointer,
    deep_planning_thread_config,
)
from agent_service.deep_agent_models import (
    GraphReview,
    PlanDraft,
    PlanReview,
    ReasoningDecision,
    ThinkingStatus,
)
from agent_service.deep_agent_planner import (
    DeepPlanningError,
    DeepPlanningEngine,
    ReasoningGateEngine,
    review_plan,
)
from agent_service.deep_agent_runtime_models import PlanningResumeCommand
from agent_service.execution import run_graph_events
from agent_service.goal_spec import parse_goal_spec
from agent_service.model_client import LlamaCppModelClient
from agent_service.node_catalog import (
    NodeAvailability,
    NodeCatalogBuilder,
    NodeCatalogSnapshot,
    NodeDefinition,
)
from agent_service.schemas import AgentEvent, RunGraph, RunGraphRequest, UserMessage
from agent_service.tool_execution import default_tool_packages_root
from agent_service.tool_protocol import equivalent_tool_ids
from agent_service.runtime_store import RuntimeStore
from agent_service.tool_registry import ToolRegistry


class DeepAgentRuntimeState(TypedDict, total=False):
    message: UserMessage
    project_path: str
    run_id: str
    thread_id: str
    reasoning_decision: ReasoningDecision
    context_bundle: dict[str, Any]
    node_catalog: dict[str, Any]
    disabled_tool_ids: list[str]
    available_capabilities: set[str]
    plan_draft: PlanDraft
    thinking_status: ThinkingStatus
    plan_review: PlanReview
    compiled_graph: dict[str, Any]
    graph_review: GraphReview
    agent_compiled_graph: dict[str, Any]
    agent_compile_review: dict[str, Any]
    execution_ready: bool
    execute_after_compile: bool
    agent_execution_result: dict[str, Any] | None
    agent_execution_review: dict[str, Any] | None
    execution_failure: dict[str, Any] | None
    execution_repair_plan: dict[str, Any] | None
    execution_repair_count: int
    compile_failure: dict[str, Any]
    revision_count: int
    revision_budget: int
    revision_instructions: Annotated[list[str], operator.add]
    clarification_answer: str
    clarification_history: list[dict[str, Any]]
    confirmation_revision_instructions: list[str]
    require_confirmation: bool
    confirmation: dict[str, Any]
    terminal_status: str
    events: Annotated[list[AgentEvent], operator.add]


class DirectDeepAgentRuntimeState(DeepAgentRuntimeState, total=False):
    model_client: Any


AgentExecutionEventRunner = Callable[[RunGraphRequest], Iterable[AgentEvent]]


def run_deep_agent_runtime(
    message: UserMessage,
    *,
    project_path: str,
    model_client: Any | None = None,
    run_id: str | None = None,
    thread_id: str | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    runtime_store: RuntimeStore | None = None,
    resume_command: PlanningResumeCommand | None = None,
    revision_budget: int = 2,
    require_confirmation: bool = True,
    execute_after_compile: bool = True,
    execution_event_runner: AgentExecutionEventRunner | None = None,
    disabled_tool_ids: list[str] | None = None,
    initial_reasoning_decision: ReasoningDecision | None = None,
) -> list[AgentEvent]:
    resolved_run_id = run_id or message.task_id
    resolved_thread_id = thread_id or f"thread-{message.task_id}"
    resolved_model_client = model_client or LlamaCppModelClient()
    default_bundle = None

    if checkpointer is None:
        checkpointer_bundle = create_deep_planning_checkpointer(
            project_path=project_path,
            run_id=resolved_run_id,
            mode="sqlite",
            allow_memory_fallback=False,
        )
        checkpointer = checkpointer_bundle.checkpointer
        default_bundle = checkpointer_bundle

    app = build_deep_agent_runtime_graph(
        checkpointer=checkpointer,
        model_client=resolved_model_client,
        execute_after_compile=execute_after_compile,
        execution_event_runner=execution_event_runner,
    )

    config = deep_planning_thread_config(resolved_thread_id)
    invoke_input = _runtime_invoke_input(
        message,
        project_path=project_path,
        run_id=resolved_run_id,
        thread_id=resolved_thread_id,
        resume_command=resume_command,
        revision_budget=revision_budget,
        require_confirmation=require_confirmation,
        execute_after_compile=execute_after_compile,
        disabled_tool_ids=disabled_tool_ids,
        initial_reasoning_decision=initial_reasoning_decision,
    )
    try:
        previous_state = app.get_state(config=config)
        previous_events = list(previous_state.values.get("events") or [])
        result = app.invoke(invoke_input, config=config)
        events = list(result.get("events") or [])[len(previous_events):]
        events.extend(_interrupted_events_from_result(result))
        checkpoint_event = _record_planning_checkpoint_event(
            app,
            config=config,
            runtime_store=runtime_store,
        )
        if checkpoint_event is not None:
            events.append(checkpoint_event)
        return events
    finally:
        if default_bundle is not None:
            default_bundle.close()


def stream_deep_agent_runtime_events(
    message: UserMessage,
    *,
    project_path: str,
    model_client: Any | None = None,
    run_id: str | None = None,
    thread_id: str | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    runtime_store: RuntimeStore | None = None,
    resume_command: PlanningResumeCommand | None = None,
    revision_budget: int = 2,
    require_confirmation: bool = True,
    execute_after_compile: bool = True,
    execution_event_runner: AgentExecutionEventRunner | None = None,
    disabled_tool_ids: list[str] | None = None,
    initial_reasoning_decision: ReasoningDecision | None = None,
):
    resolved_run_id = run_id or message.task_id
    resolved_thread_id = thread_id or f"thread-{message.task_id}"
    resolved_model_client = model_client or LlamaCppModelClient()
    default_bundle = None

    if checkpointer is None:
        checkpointer_bundle = create_deep_planning_checkpointer(
            project_path=project_path,
            run_id=resolved_run_id,
            mode="sqlite",
            allow_memory_fallback=False,
        )
        checkpointer = checkpointer_bundle.checkpointer
        default_bundle = checkpointer_bundle

    app = build_deep_agent_runtime_graph(
        checkpointer=checkpointer,
        model_client=resolved_model_client,
        execute_after_compile=execute_after_compile,
        execution_event_runner=execution_event_runner,
    )
    config = deep_planning_thread_config(resolved_thread_id)
    stream_input = _runtime_invoke_input(
        message,
        project_path=project_path,
        run_id=resolved_run_id,
        thread_id=resolved_thread_id,
        resume_command=resume_command,
        revision_budget=revision_budget,
        require_confirmation=require_confirmation,
        execute_after_compile=execute_after_compile,
        disabled_tool_ids=disabled_tool_ids,
        initial_reasoning_decision=initial_reasoning_decision,
    )

    try:
        for update in app.stream(stream_input, config=config, stream_mode="updates"):
            yield from _events_from_stream_update(update)

        checkpoint_event = _record_planning_checkpoint_event(
            app,
            config=config,
            runtime_store=runtime_store,
        )
        if checkpoint_event is not None:
            yield checkpoint_event
    finally:
        if default_bundle is not None:
            default_bundle.close()


def _runtime_invoke_input(
    message: UserMessage,
    *,
    project_path: str,
    run_id: str,
    thread_id: str,
    resume_command: PlanningResumeCommand | None,
    revision_budget: int,
    require_confirmation: bool,
    execute_after_compile: bool = True,
    disabled_tool_ids: list[str] | None = None,
    initial_reasoning_decision: ReasoningDecision | None = None,
) -> dict[str, Any] | Command:
    if resume_command is not None:
        return Command(
            update={"execute_after_compile": execute_after_compile},
            resume=resume_command.model_dump(by_alias=True),
        )

    return {
        "message": message,
        "project_path": project_path,
        "run_id": run_id,
        "thread_id": thread_id,
        "reasoning_decision": initial_reasoning_decision,
        "context_bundle": {},
        "disabled_tool_ids": list(disabled_tool_ids or []),
        "available_capabilities": set(),
        "plan_draft": None,
        "thinking_status": None,
        "plan_review": None,
        "compiled_graph": None,
        "graph_review": None,
        "agent_compiled_graph": None,
        "agent_compile_review": None,
        "execution_ready": False,
        "execute_after_compile": execute_after_compile,
        "agent_execution_result": None,
        "agent_execution_review": None,
        "execution_failure": None,
        "execution_repair_plan": None,
        "execution_repair_count": 0,
        "compile_failure": None,
        "revision_count": 0,
        "revision_budget": revision_budget,
        "revision_instructions": [],
        "clarification_answer": "",
        "clarification_history": [],
        "confirmation_revision_instructions": [],
        "require_confirmation": require_confirmation,
        "confirmation": {},
        "terminal_status": "",
        "events": [],
    }


def _events_from_stream_update(update: Any) -> list[AgentEvent]:
    if not isinstance(update, Mapping):
        return []

    events: list[AgentEvent] = []
    for node_update in update.values():
        if not isinstance(node_update, Mapping):
            continue
        for event in node_update.get("events") or []:
            if isinstance(event, AgentEvent):
                events.append(event)
            elif isinstance(event, Mapping):
                events.append(AgentEvent.model_validate(event))

    events.extend(_interrupted_events_from_result(update))
    return events


def _record_planning_checkpoint_event(
    app,
    *,
    config: dict[str, Any],
    runtime_store: RuntimeStore | None,
) -> AgentEvent | None:
    if runtime_store is None:
        return None

    snapshot = app.get_state(config=config)
    checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id")
    if checkpoint_id is None:
        return None

    summary = planning_checkpoint_summary_from_state(
        snapshot.values,
        checkpoint_id,
        None,
    )
    runtime_store.write_planning_checkpoint_summary(summary.model_dump(by_alias=True))
    return planning_checkpoint_recorded_event(summary)


def build_deep_agent_runtime_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    model_client: Any | None = None,
    execute_after_compile: bool = True,
    execution_event_runner: AgentExecutionEventRunner | None = None,
):
    use_checkpointed_model = checkpointer is not None
    state_schema = (
        DeepAgentRuntimeState
        if use_checkpointed_model
        else DirectDeepAgentRuntimeState
    )
    graph = StateGraph(state_schema)
    graph.add_node(
        "reasoning_gate",
        lambda state: reasoning_gate(
            state,
            model_client=_runtime_model_client(
                state,
                model_client,
                allow_state_model_client=not use_checkpointed_model,
            ),
        ),
    )
    graph.add_node("build_context", build_context)
    graph.add_node(
        "deep_plan",
        lambda state: deep_plan(
            state,
            model_client=_runtime_model_client(
                state,
                model_client,
                allow_state_model_client=not use_checkpointed_model,
            ),
        ),
    )
    graph.add_node(
        "revise_plan",
        lambda state: revise_plan_node(
            state,
            model_client=_runtime_model_client(
                state,
                model_client,
                allow_state_model_client=not use_checkpointed_model,
            ),
        ),
    )
    graph.add_node("review_plan", review_plan_node)
    graph.add_node("compile_agent_plan_graph", compile_agent_plan_graph_node)
    graph.add_node("review_graph", review_graph_node)
    graph.add_node("present_plan", present_plan)
    graph.add_node("confirm_plan", confirm_plan)
    graph.add_node("planning_confirmed", planning_confirmed)
    graph.add_node("compile_confirmed_plan_graph", compile_confirmed_plan_graph_node)
    graph.add_node("review_agent_compiled_graph", review_agent_compiled_graph_node)
    graph.add_node("execution_ready", execution_ready_node)
    graph.add_node(
        "execute_agent_compiled_graph",
        lambda state: execute_agent_compiled_graph_node(
            state,
            execution_event_runner=(
                execution_event_runner
                or _default_execution_event_runner_for_model_client(
                    _runtime_model_client(
                        state,
                        model_client,
                        allow_state_model_client=not use_checkpointed_model,
                    )
                )
            ),
        ),
    )
    graph.add_node("verify_agent_execution_result", verify_agent_execution_result_node)
    graph.add_node("agent_execution_final", agent_execution_final_node)
    graph.add_node("agent_execution_failed", agent_execution_failed_node)
    graph.add_node("agent_execution_interrupted", agent_execution_interrupted_node)
    graph.add_node(
        "agent_execution_repair_proposed",
        agent_execution_repair_proposed_node,
    )
    graph.add_node("compile_failed", compile_failed_node)
    graph.add_node("planning_cancelled", planning_cancelled)
    graph.add_node("clarify_required", clarify_required)
    graph.add_node("resume_after_clarification", resume_after_clarification)
    graph.add_node("simple_reasoning_final", simple_reasoning_final)
    graph.add_node("deep_agent_failed", deep_agent_failed)
    graph.set_entry_point("reasoning_gate")
    graph.add_edge("build_context", "deep_plan")
    graph.add_edge("compile_agent_plan_graph", "review_graph")
    graph.add_conditional_edges(
        "present_plan",
        _route_after_present_plan,
        {
            "confirm_plan": "confirm_plan",
            END: END,
        },
    )
    graph.add_edge("planning_confirmed", "compile_confirmed_plan_graph")
    graph.add_conditional_edges(
        "execution_ready",
        lambda state: _route_after_execution_ready(
            state,
            default_execute_after_compile=execute_after_compile,
        ),
        {
            "execute_agent_compiled_graph": "execute_agent_compiled_graph",
            END: END,
        },
    )
    graph.add_edge("agent_execution_final", END)
    graph.add_edge("agent_execution_failed", END)
    graph.add_edge("agent_execution_interrupted", END)
    graph.add_edge("agent_execution_repair_proposed", END)
    graph.add_edge("compile_failed", END)
    graph.add_edge("planning_cancelled", END)
    graph.add_edge("clarify_required", "resume_after_clarification")
    graph.add_edge("resume_after_clarification", "build_context")
    graph.add_edge("simple_reasoning_final", END)
    graph.add_edge("deep_agent_failed", END)

    compiled_graph = (
        graph.compile() if checkpointer is None else graph.compile(checkpointer=checkpointer)
    )

    if checkpointer is None:
        return compiled_graph
    return _SanitizedDeepAgentRuntimeGraph(compiled_graph)


def reasoning_gate(
    state: DeepAgentRuntimeState,
    *,
    model_client: Any,
) -> Command[
    Literal[
        "build_context",
        "clarify_required",
        "simple_reasoning_final",
        "deep_agent_failed",
    ]
    ]:
    preset_decision = _preset_reasoning_decision(state)
    if preset_decision is not None:
        return _command_for_reasoning_decision(state, preset_decision)

    try:
        decision = ReasoningGateEngine(model_client=model_client).decide(
            state["message"],
            context_bundle={},
        )
    except DeepPlanningError as error:
        return Command(
            update={
                "events": [
                    _planning_failed_event(error),
                ]
            },
            goto="deep_agent_failed",
        )

    return _command_for_reasoning_decision(state, decision)


def _preset_reasoning_decision(
    state: DeepAgentRuntimeState,
) -> ReasoningDecision | None:
    decision = state.get("reasoning_decision")
    if isinstance(decision, ReasoningDecision):
        return decision
    if isinstance(decision, Mapping):
        try:
            return ReasoningDecision.model_validate(decision)
        except ValidationError:
            return None
    return None


def _command_for_reasoning_decision(
    state: DeepAgentRuntimeState,
    decision: ReasoningDecision,
) -> Command[
    Literal[
        "build_context",
        "clarify_required",
        "simple_reasoning_final",
        "deep_agent_failed",
    ]
]:
    events = [
        AgentEvent(
            type="reasoning.decision_created",
            payload={"decision": decision.model_dump()},
        ),
    ]

    if decision.next_action == "clarification":
        return Command(
            update={
                "reasoning_decision": decision,
                "events": [
                    *events,
                    _clarification_required_event(
                        state,
                        prompt=decision.why_this_path,
                        missing_inputs=[],
                    ),
                ],
            },
            goto="clarify_required",
        )

    if decision.next_action != "deep_planning":
        return Command(
            update={"reasoning_decision": decision, "events": events},
            goto="simple_reasoning_final",
        )

    return Command(
        update={"reasoning_decision": decision, "events": events},
        goto="build_context",
    )


def build_context(state: DeepAgentRuntimeState) -> dict[str, Any]:
    message = state["message"]
    tool_registry = ToolRegistry.from_packages_root(default_tool_packages_root())
    disabled_tool_ids = list(state.get("disabled_tool_ids") or [])
    node_catalog = _node_catalog_with_disabled_tools_unavailable(
        NodeCatalogBuilder(tool_registry=tool_registry).build(),
        disabled_tool_ids=disabled_tool_ids,
    )
    goal_spec = parse_goal_spec(message)
    context = build_context_bundle(
        message=message,
        goal_spec=goal_spec,
        project_path=state["project_path"],
        tool_registry=tool_registry,
        disabled_tool_ids=disabled_tool_ids,
        node_catalog=node_catalog,
        memory_records=[],
        memory_store=None,
    )
    context_bundle = context.model_dump()
    return {
        "context_bundle": context_bundle,
        "node_catalog": node_catalog.model_dump(),
        "disabled_tool_ids": disabled_tool_ids,
        "available_capabilities": _available_capabilities(
            context_bundle,
            node_catalog=node_catalog,
        ),
    }


def deep_plan(
    state: DeepAgentRuntimeState,
    *,
    model_client: Any,
) -> Command[Literal["review_plan", "deep_agent_failed"]]:
    events = [
        AgentEvent(
            type="planning.started",
            payload={"taskId": state["message"].task_id},
        ),
    ]
    try:
        result = DeepPlanningEngine(model_client=model_client).plan(
            state["message"],
            context_bundle=state.get("context_bundle") or {},
            revision_instructions=_planning_instructions_for_state(state),
        )
    except DeepPlanningError as error:
        return Command(
            update={"events": [*events, _planning_failed_event(error)]},
            goto="deep_agent_failed",
        )

    return Command(
        update={
            "plan_draft": result.plan_draft,
            "thinking_status": result.thinking_status,
            "events": [
                *events,
                AgentEvent(
                    type="planning.thinking_status",
                    payload={"thinkingStatus": result.thinking_status.model_dump()},
                ),
                AgentEvent(
                    type="planning.draft_created",
                    payload={"planDraft": result.plan_draft.model_dump()},
                ),
            ],
        },
        goto="review_plan",
    )


def review_plan_node(
    state: DeepAgentRuntimeState,
) -> Command[
    Literal[
        "compile_agent_plan_graph",
        "clarify_required",
        "revise_plan",
        "deep_agent_failed",
    ]
]:
    review = review_plan(
        state["plan_draft"],
        available_capabilities=(
            state.get("available_capabilities") or {"model.reasoning"}
        ),
        node_catalog=_node_catalog_from_state(state),
        message=state["message"],
    )
    events = [
        AgentEvent(
            type="planning.review_completed",
            payload={"review": review.model_dump()},
        ),
    ]

    if review.status == "approved":
        return Command(
            update={"plan_review": review, "events": events},
            goto="compile_agent_plan_graph",
        )

    if review.status == "invalid":
        if _revision_available(state):
            return Command(
                update={
                    "plan_review": review,
                    "events": [
                        *events,
                        AgentEvent(
                            type="planning.revision_requested",
                            payload={
                                "taskId": state["message"].task_id,
                                "reason": "plan_review_invalid",
                                "review": review.model_dump(),
                                "revisionCount": (
                                    int(state.get("revision_count", 0) or 0) + 1
                                ),
                                "revisionBudget": _revision_budget(state),
                                "instructions": list(review.revision_instructions),
                            },
                        ),
                    ],
                },
                goto="revise_plan",
            )

        return Command(
            update={
                "plan_review": review,
                "events": [
                    *events,
                    AgentEvent(
                        type="planning.revision_exhausted",
                        payload={
                            "taskId": state["message"].task_id,
                            "reason": "plan_review_invalid",
                            "review": review.model_dump(),
                            "revisionCount": int(
                                state.get("revision_count", 0) or 0
                            ),
                            "revisionBudget": _revision_budget(state),
                        },
                    ),
                    AgentEvent(
                        type="planning.failed",
                        payload={
                            "reason": "plan_review_invalid",
                            "review": review.model_dump(),
                        },
                    ),
                ],
            },
            goto="deep_agent_failed",
        )

    if _clarification_allowed(state):
        return Command(
            update={
                "plan_review": review,
                "events": [
                    *events,
                    _clarification_required_event(
                        state,
                        prompt=review.suggested_clarifying_question
                        or "请补充任务目标或输入信息后我再生成执行图。",
                        missing_inputs=list(review.missing_inputs),
                    ),
                ],
            },
            goto="clarify_required",
        )

    return Command(
        update={
            "plan_review": review,
            "events": [
                *events,
                AgentEvent(
                    type="planning.revision_exhausted",
                    payload={
                        "taskId": state["message"].task_id,
                        "reason": "plan_review_needs_clarification_after_revision",
                        "review": review.model_dump(),
                        "revisionCount": int(state.get("revision_count", 0) or 0),
                        "revisionBudget": _revision_budget(state),
                    },
                ),
                AgentEvent(
                    type="planning.failed",
                    payload={
                        "reason": "plan_review_needs_clarification_after_revision",
                        "review": review.model_dump(),
                    },
                ),
            ],
        },
        goto="deep_agent_failed",
    )


def revise_plan_node(
    state: DeepAgentRuntimeState,
    *,
    model_client: Any,
) -> Command[Literal["review_plan", "deep_agent_failed"]]:
    revision_count = int(state.get("revision_count", 0) or 0) + 1
    revision_instructions = _revision_instructions_for_state(state)
    events = [
        AgentEvent(
            type="planning.revision_started",
            payload={
                "taskId": state["message"].task_id,
                "revisionCount": revision_count,
                "revisionBudget": _revision_budget(state),
                "instructions": list(revision_instructions),
            },
        )
    ]

    try:
        result = DeepPlanningEngine(model_client=model_client).plan(
            state["message"],
            context_bundle=state.get("context_bundle") or {},
            revision_instructions=revision_instructions,
        )
    except DeepPlanningError as error:
        return Command(
            update={
                "revision_count": revision_count,
                "events": [*events, _planning_failed_event(error)],
            },
            goto="deep_agent_failed",
        )

    return Command(
        update={
            "plan_draft": result.plan_draft,
            "thinking_status": result.thinking_status,
            "revision_count": revision_count,
            "events": [
                *events,
                AgentEvent(
                    type="planning.thinking_status",
                    payload={"thinkingStatus": result.thinking_status.model_dump()},
                ),
                AgentEvent(
                    type="planning.draft_created",
                    payload={"planDraft": result.plan_draft.model_dump()},
                ),
                AgentEvent(
                    type="planning.revision_completed",
                    payload={
                        "taskId": state["message"].task_id,
                        "revisionCount": revision_count,
                        "revisionBudget": _revision_budget(state),
                        "planDraftId": result.plan_draft.plan_draft_id,
                    },
                ),
            ],
        },
        goto="review_plan",
    )


def compile_agent_plan_graph_node(state: DeepAgentRuntimeState) -> dict[str, Any]:
    graph = compile_agent_plan_graph(
        state["plan_draft"],
        task_id=state["message"].task_id,
        node_catalog=_node_catalog_from_state(state),
    )
    return {
        "compiled_graph": graph,
        "events": [
            AgentEvent(
                type="planning.graph_compiled",
                payload={"graph": graph},
            ),
        ],
    }


def review_graph_node(
    state: DeepAgentRuntimeState,
) -> Command[Literal["present_plan", "revise_plan", "deep_agent_failed"]]:
    review = review_compiled_graph(state["plan_draft"], state["compiled_graph"])
    events = [
        AgentEvent(
            type="planning.graph_review_completed",
            payload={"review": review.model_dump()},
        ),
    ]

    if review.status == "approved":
        return Command(
            update={"graph_review": review, "events": events},
            goto="present_plan",
        )

    if _revision_available(state):
        instructions = _graph_review_revision_instructions(review)
        return Command(
            update={
                "graph_review": review,
                "events": [
                    *events,
                    AgentEvent(
                        type="planning.revision_requested",
                        payload={
                            "taskId": state["message"].task_id,
                            "reason": "graph_review_invalid",
                            "review": review.model_dump(),
                            "revisionCount": (
                                int(state.get("revision_count", 0) or 0) + 1
                            ),
                            "revisionBudget": _revision_budget(state),
                            "instructions": instructions,
                        },
                    ),
                ],
            },
            goto="revise_plan",
        )

    return Command(
        update={
            "graph_review": review,
            "events": [
                *events,
                AgentEvent(
                    type="planning.revision_exhausted",
                    payload={
                        "taskId": state["message"].task_id,
                        "reason": "graph_review_invalid",
                        "review": review.model_dump(),
                        "revisionCount": int(state.get("revision_count", 0) or 0),
                        "revisionBudget": _revision_budget(state),
                    },
                ),
                AgentEvent(
                    type="planning.failed",
                    payload={
                        "reason": "graph_review_invalid",
                        "review": review.model_dump(),
                    },
                ),
            ],
        },
        goto="deep_agent_failed",
    )


def present_plan(state: DeepAgentRuntimeState) -> dict[str, Any]:
    events = [
        AgentEvent(
            type="node_graph.created",
            payload={"graph": state["compiled_graph"]},
        ),
    ]
    if _confirmation_required(state):
        events.append(_confirmation_required_event(state))

    return {
        "clarification_answer": "",
        "confirmation_revision_instructions": [],
        "events": events,
    }


def confirm_plan(
    state: DeepAgentRuntimeState,
) -> Command[
    Literal[
        "planning_confirmed",
        "planning_cancelled",
        "revise_plan",
        "deep_agent_failed",
    ]
]:
    payload = _confirmation_interrupt_payload(state)
    resume_payload = interrupt(payload)
    if not isinstance(resume_payload, dict):
        resume_payload = {}

    decision = str(resume_payload.get("decision") or "").strip()
    if decision == "approve":
        return Command(
            update={
                "confirmation": {
                    "decision": "approve",
                    "confirmationId": _confirmation_id(state),
                }
            },
            goto="planning_confirmed",
        )

    if decision == "cancel":
        return Command(
            update={"confirmation": {"decision": "cancel"}},
            goto="planning_cancelled",
        )

    if decision == "revise":
        instructions = _confirmation_revision_instructions(resume_payload)
        resumed_event = _confirmation_resumed_event(
            state,
            decision="revise",
            revision_instructions=instructions,
        )
        if not _revision_available(state):
            return Command(
                update={
                    "confirmation": {
                        "decision": "revise",
                        "revisionInstructions": instructions,
                    },
                    "events": [
                        resumed_event,
                        AgentEvent(
                            type="planning.revision_exhausted",
                            payload={
                                "taskId": state["message"].task_id,
                                "reason": "confirmation_revision_budget_exhausted",
                                "revisionCount": int(
                                    state.get("revision_count", 0) or 0
                                ),
                                "revisionBudget": _revision_budget(state),
                                "instructions": instructions,
                            },
                        ),
                        AgentEvent(
                            type="planning.failed",
                            payload={
                                "reason": "confirmation_revision_budget_exhausted",
                                "revisionBudget": _revision_budget(state),
                            },
                        ),
                    ],
                },
                goto="deep_agent_failed",
            )

        revision_count = int(state.get("revision_count", 0) or 0) + 1
        return Command(
            update={
                "confirmation": {
                    "decision": "revise",
                    "revisionInstructions": instructions,
                },
                "confirmation_revision_instructions": instructions,
                "events": [
                    resumed_event,
                    AgentEvent(
                        type="planning.revision_requested",
                        payload={
                            "taskId": state["message"].task_id,
                            "reason": "planning_confirmation_revision",
                            "revisionCount": revision_count,
                            "revisionBudget": _revision_budget(state),
                            "instructions": instructions,
                        },
                    ),
                ],
            },
            goto="revise_plan",
        )

    return Command(
        update={
            "events": [
                AgentEvent(
                    type="planning.failed",
                    payload={
                        "reason": "invalid_confirmation_decision",
                        "decision": decision,
                    },
                ),
            ],
        },
        goto="deep_agent_failed",
    )


def planning_confirmed(state: DeepAgentRuntimeState) -> dict[str, Any]:
    return {
        "terminal_status": "planning_confirmed",
        "confirmation_revision_instructions": [],
        "events": [
            AgentEvent(
                type="planning.confirmed",
                payload=_confirmation_terminal_payload(state),
            ),
        ],
    }


def compile_confirmed_plan_graph_node(
    state: DeepAgentRuntimeState,
) -> Command[Literal["review_agent_compiled_graph", "compile_failed"]]:
    graph_id = _compiled_graph_id(state)
    events = [_agent_plan_graph_compile_started_event(state, graph_id=graph_id)]

    try:
        graph = RunGraph.model_validate(state.get("compiled_graph"))
        compiled_graph = compile_confirmed_agent_plan_graph(
            graph,
            task_id=state["message"].task_id,
            run_id=state["run_id"],
            thread_id=state["thread_id"],
            confirmation_id=_confirmation_id(state),
        )
    except (AgentPlanCompileError, ValidationError) as error:
        failure = _compile_failure_payload_from_error(
            state,
            graph_id=graph_id,
            error=error,
        )
        return Command(
            update={
                "agent_compiled_graph": None,
                "agent_compile_review": None,
                "execution_ready": False,
                "compile_failure": failure,
                "events": [
                    *events,
                    AgentEvent(
                        type="agent_plan_graph.compile_failed",
                        payload=failure,
                    ),
                ],
            },
            goto="compile_failed",
        )

    compiled_payload = compiled_graph.model_dump(mode="json")
    return Command(
        update={
            "agent_compiled_graph": compiled_payload,
            "agent_compile_review": None,
            "execution_ready": False,
            "agent_execution_result": None,
            "agent_execution_review": None,
            "execution_failure": None,
            "execution_repair_plan": None,
            "compile_failure": None,
            "events": [
                *events,
                AgentEvent(
                    type="agent_plan_graph.compiled",
                    payload=_compiled_graph_event_payload(
                        state,
                        graph_id=compiled_graph.source_graph_id,
                        compile_id=compiled_graph.compile_id,
                    ),
                ),
            ],
        },
        goto="review_agent_compiled_graph",
    )


def review_agent_compiled_graph_node(
    state: DeepAgentRuntimeState,
) -> Command[Literal["execution_ready", "compile_failed"]]:
    raw_compiled_graph = state.get("agent_compiled_graph")
    graph_id = _agent_compiled_graph_source_graph_id(state)
    compile_id = _agent_compiled_graph_compile_id(state)

    try:
        compiled_graph = AgentCompiledGraph.model_validate(raw_compiled_graph)
        review = review_agent_compiled_graph(compiled_graph)
    except ValidationError as error:
        failure = _compile_failure_payload_from_error(
            state,
            graph_id=graph_id,
            compile_id=compile_id,
            error=error,
        )
        return Command(
            update={
                "agent_compile_review": None,
                "execution_ready": False,
                "compile_failure": failure,
                "events": [
                    AgentEvent(
                        type="agent_plan_graph.compile_failed",
                        payload=failure,
                    ),
                ],
            },
            goto="compile_failed",
        )

    review_payload = review.model_dump(mode="json")
    review_completed = AgentEvent(
        type="agent_plan_graph.compile_review_completed",
        payload=_compiled_graph_event_payload(
            state,
            graph_id=compiled_graph.source_graph_id,
            compile_id=compiled_graph.compile_id,
        ),
    )

    if review.is_valid and review.execution_ready:
        ready_graph = compiled_graph.model_copy(update={"status": "execution_ready"})
        ready_payload = ready_graph.model_dump(mode="json")
        return Command(
            update={
                "agent_compiled_graph": ready_payload,
                "agent_compile_review": review_payload,
                "execution_ready": True,
                "compile_failure": None,
                "events": [
                    review_completed,
                    AgentEvent(
                        type="agent_plan_graph.execution_ready",
                        payload=_execution_ready_payload(ready_graph),
                    ),
                ],
            },
            goto="execution_ready",
        )

    failure = _compile_failure_payload_from_review(
        state,
        graph_id=compiled_graph.source_graph_id,
        compile_id=compiled_graph.compile_id,
        review=review_payload,
    )
    return Command(
        update={
            "agent_compile_review": review_payload,
            "execution_ready": False,
            "compile_failure": failure,
            "events": [
                review_completed,
                AgentEvent(
                    type="agent_plan_graph.compile_failed",
                    payload=failure,
                ),
            ],
        },
        goto="compile_failed",
    )


def execution_ready_node(state: DeepAgentRuntimeState) -> dict[str, Any]:
    del state
    return {"terminal_status": "execution_ready"}


def execute_agent_compiled_graph_node(
    state: DeepAgentRuntimeState,
    *,
    execution_event_runner: AgentExecutionEventRunner,
) -> Command[Literal["verify_agent_execution_result", "agent_execution_failed"]]:
    compiled_graph: AgentCompiledGraph | None = None
    events: list[AgentEvent] = []

    try:
        compiled_graph = AgentCompiledGraph.model_validate(
            state.get("agent_compiled_graph")
        )
        events.append(
            AgentEvent(
                type="agent_execution.started",
                payload=_agent_execution_base_payload(compiled_graph),
            )
        )
        request = run_graph_request_from_agent_compiled_graph(
            compiled_graph,
            project_path=state["project_path"],
        )
        execution_events = _agent_execution_events_from_runner(
            execution_event_runner,
            request,
        )
        result = summarize_agent_execution_events(compiled_graph, execution_events)
    except Exception as error:
        failure = _agent_execution_exception_payload(
            state,
            compiled_graph=compiled_graph,
            error=error,
        )
        return Command(
            update={
                "agent_execution_result": None,
                "agent_execution_review": None,
                "execution_failure": failure,
                "events": [
                    *events,
                    AgentEvent(
                        type="agent_execution.failed",
                        payload=failure,
                    ),
                ],
            },
            goto="agent_execution_failed",
        )

    status_event = _agent_execution_status_event(compiled_graph, result)
    status_payload = status_event.payload

    return Command(
        update={
            "agent_execution_result": result.model_dump(mode="json"),
            "agent_execution_review": None,
            "execution_failure": (
                status_payload if result.status in {"failed", "interrupted"} else None
            ),
            "events": [
                *events,
                *execution_events,
                status_event,
            ],
        },
        goto="verify_agent_execution_result",
    )


def verify_agent_execution_result_node(
    state: DeepAgentRuntimeState,
) -> Command[
    Literal[
        "agent_execution_final",
        "agent_execution_failed",
        "agent_execution_interrupted",
        "agent_execution_repair_proposed",
    ]
]:
    compiled_graph = AgentCompiledGraph.model_validate(
        state.get("agent_compiled_graph")
    )
    result = AgentExecutionRunResult.model_validate(
        state.get("agent_execution_result")
    )
    review = review_agent_execution_result(compiled_graph, result)
    review_payload = _agent_execution_review_payload(compiled_graph, review)

    if review.status == "approved":
        goto = "agent_execution_final"
    elif review.status == "needs_repair":
        goto = "agent_execution_repair_proposed"
    elif result.status == "interrupted":
        goto = "agent_execution_interrupted"
    else:
        goto = "agent_execution_failed"

    return Command(
        update={
            "agent_execution_review": review.model_dump(mode="json"),
            "events": [
                AgentEvent(
                    type="agent_execution.verify_completed",
                    payload=review_payload,
                ),
            ],
        },
        goto=goto,
    )


def agent_execution_final_node(state: DeepAgentRuntimeState) -> dict[str, Any]:
    compiled_graph = AgentCompiledGraph.model_validate(
        state.get("agent_compiled_graph")
    )
    result = AgentExecutionRunResult.model_validate(
        state.get("agent_execution_result")
    )
    return {
        "terminal_status": "final",
        "events": [
            AgentEvent(
                type="agent_execution.final",
                payload={
                    **_agent_execution_result_payload(compiled_graph, result),
                    "message": result.final_message or "Agent execution completed.",
                    "artifactRefs": list(result.artifact_refs),
                    "finalMessage": (
                        result.final_message or "Agent execution completed."
                    ),
                },
            ),
        ],
    }


def agent_execution_repair_proposed_node(
    state: DeepAgentRuntimeState,
) -> dict[str, Any]:
    compiled_graph = AgentCompiledGraph.model_validate(
        state.get("agent_compiled_graph")
    )
    result = AgentExecutionRunResult.model_validate(
        state.get("agent_execution_result")
    )
    review = AgentExecutionReview.model_validate(
        state.get("agent_execution_review")
    )
    actions = list(result.recovery_actions)
    issues = [_agent_execution_issue_payload(issue) for issue in review.issues]
    repair_plan = {"actions": actions, "issues": issues}
    return {
        "terminal_status": "execution_repair_proposed",
        "execution_repair_plan": repair_plan,
        "execution_repair_count": int(state.get("execution_repair_count", 0) or 0) + 1,
        "events": [
            AgentEvent(
                type="agent_execution.repair_proposed",
                payload={
                    **_agent_execution_result_payload(compiled_graph, result),
                    "actions": actions,
                    "issues": issues,
                    "reason": "execution_repair_available",
                },
            ),
        ],
    }


def agent_execution_interrupted_node(state: DeepAgentRuntimeState) -> dict[str, Any]:
    del state
    return {"terminal_status": "execution_interrupted"}


def agent_execution_failed_node(state: DeepAgentRuntimeState) -> dict[str, Any]:
    del state
    return {"terminal_status": "execution_failed"}


def compile_failed_node(state: DeepAgentRuntimeState) -> dict[str, Any]:
    del state
    return {"terminal_status": "compile_failed"}


def planning_cancelled(state: DeepAgentRuntimeState) -> dict[str, Any]:
    return {
        "terminal_status": "cancelled",
        "confirmation_revision_instructions": [],
        "events": [
            AgentEvent(
                type="planning.cancelled",
                payload=_confirmation_terminal_payload(state),
            ),
        ],
    }


def clarify_required(state: DeepAgentRuntimeState) -> dict[str, Any]:
    review = state.get("plan_review")
    decision = state.get("reasoning_decision")
    prompt = "请补充任务目标或输入信息后我再生成执行图。"
    missing_inputs: list[str] = []
    if review is not None and review.suggested_clarifying_question:
        missing_inputs = list(review.missing_inputs)
        prompt = review.suggested_clarifying_question
    elif review is not None:
        missing_inputs = list(review.missing_inputs)
    elif decision is not None and decision.next_action == "clarification":
        prompt = decision.why_this_path

    payload = _clarification_interrupt_payload(
        state,
        prompt=prompt,
        missing_inputs=missing_inputs,
    )
    resume_payload = interrupt(payload)
    answer = str(
        resume_payload.get("answer")
        if isinstance(resume_payload, dict)
        else resume_payload
    ).strip()
    clarification_record = {
        "question": prompt,
        "answer": answer,
        "missing_inputs": list(missing_inputs),
    }
    clarification_history = [
        record
        for record in list(state.get("clarification_history") or [])
        if not _same_clarification_slot(
            record,
            question=prompt,
            missing_inputs=missing_inputs,
        )
    ]

    return {
        "clarification_answer": answer,
        "clarification_history": [*clarification_history, clarification_record],
        "events": [
            AgentEvent(
                type="planning.resumed",
                payload={
                    "taskId": state["message"].task_id,
                    "runId": state["run_id"],
                    "threadId": state["thread_id"],
                    "kind": "planning.clarification",
                },
            ),
        ]
    }


def resume_after_clarification(state: DeepAgentRuntimeState) -> dict[str, Any]:
    return {
        "plan_draft": None,
        "plan_review": None,
        "compiled_graph": None,
        "graph_review": None,
        "agent_compiled_graph": None,
        "agent_compile_review": None,
        "execution_ready": False,
        "compile_failure": None,
        "revision_instructions": [],
        "events": [
            AgentEvent(
                type="planning.stage_changed",
                payload={
                    "taskId": state["message"].task_id,
                    "stage": "build_context",
                    "label": "构建上下文",
                },
            )
        ],
    }


def simple_reasoning_final(state: DeepAgentRuntimeState) -> dict[str, Any]:
    return {
        "events": [
            AgentEvent(
                type="reasoning.completed",
                payload={
                    "taskId": state["message"].task_id,
                    "nextAction": state["reasoning_decision"].next_action,
                },
            ),
        ]
    }


def deep_agent_failed(state: DeepAgentRuntimeState) -> dict[str, Any]:
    del state
    return {"clarification_answer": "", "confirmation_revision_instructions": []}


def _planning_failed_event(error: DeepPlanningError) -> AgentEvent:
    return AgentEvent(
        type="planning.failed",
        payload={"reason": error.code, "message": error.message},
    )


def _clarification_required_event(
    state: DeepAgentRuntimeState,
    *,
    prompt: str,
    missing_inputs: list[str],
) -> AgentEvent:
    return AgentEvent(
        type="planning.clarification_required",
        payload=_clarification_interrupt_payload(
            state,
            prompt=prompt,
            missing_inputs=missing_inputs,
        ),
    )


def _clarification_interrupt_payload(
    state: DeepAgentRuntimeState,
    *,
    prompt: str,
    missing_inputs: list[str],
) -> dict[str, Any]:
    return {
        "kind": "planning.clarification",
        "taskId": state["message"].task_id,
        "runId": state["run_id"],
        "threadId": state["thread_id"],
        "question": prompt,
        "missingInputs": list(missing_inputs),
        "prompt": prompt,
    }


def _route_after_present_plan(state: DeepAgentRuntimeState):
    return "confirm_plan" if _confirmation_required(state) else END


def _route_after_execution_ready(
    state: DeepAgentRuntimeState,
    *,
    default_execute_after_compile: bool,
):
    if bool(state.get("execute_after_compile", default_execute_after_compile)):
        return "execute_agent_compiled_graph"
    return END


def _confirmation_required(state: DeepAgentRuntimeState) -> bool:
    return bool(state.get("require_confirmation", False))


def _confirmation_required_event(state: DeepAgentRuntimeState) -> AgentEvent:
    return AgentEvent(
        type="planning.confirmation_required",
        payload=_confirmation_interrupt_payload(state),
    )


def _confirmation_interrupt_payload(state: DeepAgentRuntimeState) -> dict[str, Any]:
    graph_id = _compiled_graph_id(state)
    pending_choice = {
        "kind": "planning.confirmation",
        "runId": state["run_id"],
        "threadId": state["thread_id"],
        "graphId": graph_id,
    }
    return {
        "kind": "planning.confirmation",
        "taskId": state["message"].task_id,
        "runId": state["run_id"],
        "threadId": state["thread_id"],
        "graphId": graph_id,
        "summary": _confirmation_summary_text(state),
        "pendingChoice": pending_choice,
        "choices": [
            {
                "id": "approve",
                "label": "确认执行",
            },
            {
                "id": "revise",
                "label": "要求修订",
            },
            {
                "id": "cancel",
                "label": "取消",
            },
        ],
    }


def _confirmation_summary_text(state: DeepAgentRuntimeState) -> str:
    plan = state.get("plan_draft")
    if plan is None:
        return "Review the generated execution graph before it runs."

    understanding = str(getattr(plan, "task_understanding", "") or "").strip()
    step_titles: list[str] = []
    for step in list(getattr(plan, "steps", []) or [])[:3]:
        title = (
            str(step.get("title") or "").strip()
            if isinstance(step, dict)
            else str(getattr(step, "title", "") or "").strip()
        )
        if title:
            step_titles.append(title)

    if step_titles:
        steps_summary = f"Steps: {', '.join(step_titles)}."
        if understanding:
            return f"{understanding} {steps_summary}"
        return steps_summary
    return understanding or "Review the generated execution graph before it runs."


def _compiled_graph_id(state: DeepAgentRuntimeState) -> str:
    graph = state.get("compiled_graph") or {}
    if isinstance(graph, dict):
        graph_id = graph.get("graphId") or graph.get("graph_id")
        if graph_id:
            return str(graph_id)
    return f"graph-{state['message'].task_id}"


def _confirmation_revision_instructions(payload: dict[str, Any]) -> list[str]:
    raw_instructions = payload.get("revisionInstructions")
    if raw_instructions is None:
        raw_instructions = payload.get("revision_instructions")

    if raw_instructions is None:
        instructions: list[str] = []
    elif isinstance(raw_instructions, list):
        instructions = [str(instruction) for instruction in raw_instructions]
    else:
        instructions = [str(raw_instructions)]

    return _deduplicate_instructions(instructions) or [
        "Revise the plan based on the user's confirmation feedback."
    ]


def _confirmation_resumed_event(
    state: DeepAgentRuntimeState,
    *,
    decision: str,
    revision_instructions: list[str],
) -> AgentEvent:
    return AgentEvent(
        type="planning.resumed",
        payload={
            "taskId": state["message"].task_id,
            "runId": state["run_id"],
            "threadId": state["thread_id"],
            "kind": "planning.confirmation",
            "decision": decision,
            "revisionInstructions": list(revision_instructions),
        },
    )


def _confirmation_terminal_payload(state: DeepAgentRuntimeState) -> dict[str, Any]:
    return {
        "taskId": state["message"].task_id,
        "runId": state["run_id"],
        "threadId": state["thread_id"],
        "graphId": _compiled_graph_id(state),
    }


def _confirmation_id(state: DeepAgentRuntimeState) -> str:
    confirmation = state.get("confirmation")
    if isinstance(confirmation, dict):
        confirmation_id = (
            confirmation.get("confirmationId")
            or confirmation.get("confirmation_id")
        )
        if confirmation_id:
            return str(confirmation_id)
    return f"confirmation-{state['run_id']}-{_compiled_graph_id(state)}"


def _agent_plan_graph_compile_started_event(
    state: DeepAgentRuntimeState,
    *,
    graph_id: str,
) -> AgentEvent:
    return AgentEvent(
        type="agent_plan_graph.compile_started",
        payload={
            "taskId": state["message"].task_id,
            "runId": state["run_id"],
            "threadId": state["thread_id"],
            "graphId": graph_id,
        },
    )


def _compiled_graph_event_payload(
    state: DeepAgentRuntimeState,
    *,
    graph_id: str,
    compile_id: str,
) -> dict[str, Any]:
    return {
        "taskId": state["message"].task_id,
        "runId": state["run_id"],
        "threadId": state["thread_id"],
        "graphId": graph_id,
        "compileId": compile_id,
    }


def _execution_ready_payload(compiled_graph: AgentCompiledGraph) -> dict[str, Any]:
    permissions_required: list[str] = []
    expected_artifacts: list[str] = []
    for node in compiled_graph.nodes:
        permissions_required.extend(list(node.permissions_required))
        expected_artifacts.extend(
            artifact.path_template
            for artifact in node.expected_artifacts
        )

    return {
        "taskId": compiled_graph.task_id,
        "runId": compiled_graph.run_id,
        "threadId": compiled_graph.thread_id,
        "graphId": compiled_graph.source_graph_id,
        "compileId": compiled_graph.compile_id,
        "nodeCount": len(compiled_graph.nodes),
        "edgeCount": len(compiled_graph.edges),
        "toolNodeCount": sum(
            1 for node in compiled_graph.nodes if node.binding_kind == "tool"
        ),
        "modelNodeCount": sum(
            1 for node in compiled_graph.nodes if node.binding_kind == "model"
        ),
        "permissionsRequired": _deduplicate_instructions(permissions_required),
        "expectedArtifacts": expected_artifacts,
    }


def _default_execution_event_runner_for_model_client(
    model_client: Any,
) -> AgentExecutionEventRunner:
    def runner(request: RunGraphRequest) -> Iterable[AgentEvent]:
        return run_graph_events(request, model_client=model_client)

    return runner


def _agent_execution_events_from_runner(
    execution_event_runner: AgentExecutionEventRunner,
    request: RunGraphRequest,
) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    for event in execution_event_runner(request):
        if isinstance(event, AgentEvent):
            events.append(event)
        elif isinstance(event, Mapping):
            events.append(AgentEvent.model_validate(event))
        else:
            raise TypeError(
                f"execution_event_runner yielded unsupported event: {event!r}"
            )
    return events


def _agent_execution_base_payload(
    compiled_graph: AgentCompiledGraph,
) -> dict[str, Any]:
    return {
        "taskId": compiled_graph.task_id,
        "runId": compiled_graph.run_id,
        "threadId": compiled_graph.thread_id,
        "compileId": compiled_graph.compile_id,
        "graphId": compiled_graph.source_graph_id,
    }


def _agent_execution_status_event(
    compiled_graph: AgentCompiledGraph,
    result: AgentExecutionRunResult,
) -> AgentEvent:
    payload = _agent_execution_result_payload(compiled_graph, result)
    if result.status == "completed":
        return AgentEvent(type="agent_execution.completed", payload=payload)

    payload["reason"] = _agent_execution_failure_reason(result)

    event_type = (
        "agent_execution.interrupted"
        if result.status == "interrupted"
        else "agent_execution.failed"
    )
    return AgentEvent(type=event_type, payload=payload)


def _agent_execution_failure_reason(result: AgentExecutionRunResult) -> str:
    if result.status == "interrupted":
        return "permission_required" if result.failed_node_id else "interrupted"
    return "execution_failed"


def _agent_execution_result_payload(
    compiled_graph: AgentCompiledGraph,
    result: AgentExecutionRunResult,
) -> dict[str, Any]:
    payload = {
        **_agent_execution_base_payload(compiled_graph),
        "status": result.status,
        "artifactRefs": list(result.artifact_refs),
        "completedNodeIds": list(result.completed_node_ids),
        "checkpointIds": list(result.checkpoint_ids),
        "recoveryActions": list(result.recovery_actions),
    }
    if result.failed_node_id is not None:
        payload["failedNodeId"] = result.failed_node_id
    if result.final_message is not None:
        payload["finalMessage"] = result.final_message
    return payload


def _agent_execution_review_payload(
    compiled_graph: AgentCompiledGraph,
    review: AgentExecutionReview,
) -> dict[str, Any]:
    return {
        **_agent_execution_base_payload(compiled_graph),
        "status": review.status,
        "isValid": review.is_valid,
        "issues": [
            _agent_execution_issue_payload(issue)
            for issue in review.issues
        ],
        "finalArtifacts": list(review.final_artifacts),
        "repairRequired": review.repair_required,
    }


def _agent_execution_issue_payload(issue) -> dict[str, Any]:
    payload = {
        "code": issue.code,
        "message": issue.message,
        "severity": issue.severity,
    }
    if issue.node_id is not None:
        payload["nodeId"] = issue.node_id
    return payload


def _agent_execution_exception_payload(
    state: DeepAgentRuntimeState,
    *,
    compiled_graph: AgentCompiledGraph | None,
    error: Exception,
) -> dict[str, Any]:
    if compiled_graph is not None:
        payload = _agent_execution_base_payload(compiled_graph)
    else:
        payload = {
            "taskId": state["message"].task_id,
            "runId": state["run_id"],
            "threadId": state["thread_id"],
            "graphId": _agent_compiled_graph_source_graph_id(state),
        }
        compile_id = _agent_compiled_graph_compile_id(state)
        if compile_id:
            payload["compileId"] = compile_id

    error_code = str(getattr(error, "code", "") or error.__class__.__name__)
    message = str(getattr(error, "message", "") or error)
    payload.update(
        {
            "status": "failed",
            "reason": "execution_bridge_failed",
            "errorCode": error_code,
            "issues": [
                {
                    "code": error_code,
                    "message": message,
                    "severity": "error",
                }
            ],
        }
    )
    return payload


def _compile_failure_payload_from_error(
    state: DeepAgentRuntimeState,
    *,
    graph_id: str,
    error: AgentPlanCompileError | ValidationError,
    compile_id: str | None = None,
) -> dict[str, Any]:
    if isinstance(error, AgentPlanCompileError):
        reason = error.code
        message = error.message
    else:
        reason = "invalid_run_graph_schema"
        message = str(error)

    payload = _compile_failure_base_payload(
        state,
        graph_id=graph_id,
        compile_id=compile_id,
        reason=reason,
    )
    payload["issues"] = [
        {
            "code": reason,
            "message": message,
            "severity": "error",
        }
    ]
    return payload


def _compile_failure_payload_from_review(
    state: DeepAgentRuntimeState,
    *,
    graph_id: str,
    compile_id: str,
    review: dict[str, Any],
) -> dict[str, Any]:
    payload = _compile_failure_base_payload(
        state,
        graph_id=graph_id,
        compile_id=compile_id,
        reason="compile_review_invalid",
    )
    payload["issues"] = [
        _compact_issue_payload(issue)
        for issue in list(review.get("issues") or [])
        if isinstance(issue, dict)
    ]
    payload["unsupportedCapabilities"] = list(
        review.get("unsupported_capabilities") or []
    )
    payload["missingBindings"] = list(review.get("missing_bindings") or [])
    return payload


def _compile_failure_base_payload(
    state: DeepAgentRuntimeState,
    *,
    graph_id: str,
    reason: str,
    compile_id: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "taskId": state["message"].task_id,
        "runId": state["run_id"],
        "threadId": state["thread_id"],
        "graphId": graph_id,
        "reason": reason,
        "issues": [],
        "unsupportedCapabilities": [],
        "missingBindings": [],
    }
    if compile_id:
        payload["compileId"] = compile_id
    return payload


def _compact_issue_payload(issue: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in issue.items() if value is not None}


def _agent_compiled_graph_source_graph_id(state: DeepAgentRuntimeState) -> str:
    graph = state.get("agent_compiled_graph") or {}
    if isinstance(graph, dict):
        graph_id = graph.get("source_graph_id") or graph.get("sourceGraphId")
        if graph_id:
            return str(graph_id)
    return _compiled_graph_id(state)


def _agent_compiled_graph_compile_id(state: DeepAgentRuntimeState) -> str | None:
    graph = state.get("agent_compiled_graph") or {}
    if isinstance(graph, dict):
        compile_id = graph.get("compile_id") or graph.get("compileId")
        if compile_id:
            return str(compile_id)
    return None


def _interrupted_events_from_result(result: dict[str, Any]) -> list[AgentEvent]:
    interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
    if not interrupts:
        return []

    events: list[AgentEvent] = []
    for item in interrupts:
        payload = getattr(item, "value", item)
        if not isinstance(payload, dict):
            continue
        kind = payload.get("kind")
        if kind in {"planning.clarification", "planning.confirmation"}:
            events.append(AgentEvent(type="planning.interrupted", payload=payload))
    return events


def _runtime_model_client(
    state: DeepAgentRuntimeState,
    model_client: Any | None,
    *,
    allow_state_model_client: bool,
) -> Any:
    if model_client is not None:
        return model_client
    if allow_state_model_client:
        return state.get("model_client") or LlamaCppModelClient()
    return LlamaCppModelClient()


def _planning_instructions_for_state(state: DeepAgentRuntimeState) -> list[str]:
    instructions = list(state.get("revision_instructions") or [])
    instructions.extend(list(state.get("confirmation_revision_instructions") or []))
    clarification_history = list(state.get("clarification_history") or [])
    recorded_answers: set[str] = set()
    for item in clarification_history:
        if not isinstance(item, dict):
            continue
        answer = str(item.get("answer") or "").strip()
        if not answer:
            continue
        recorded_answers.add(answer)
        question = str(item.get("question") or "").strip()
        missing_inputs = item.get("missing_inputs")
        missing_text = (
            ", ".join(str(value) for value in missing_inputs)
            if isinstance(missing_inputs, list)
            else ""
        )
        instructions.append(
            "User has already answered this clarification; use it as fixed "
            "task context and do not ask for the same or similar information again. "
            f"Question: {question}. Missing inputs: {missing_text}. Answer: {answer}"
        )
    clarification_answer = str(state.get("clarification_answer") or "").strip()
    if clarification_answer and clarification_answer not in recorded_answers:
        instructions.append(
            "Use this user clarification while revising the plan: "
            f"{clarification_answer}"
        )
    return _deduplicate_instructions(instructions)


def _same_clarification_slot(
    record: Any,
    *,
    question: str,
    missing_inputs: list[str],
) -> bool:
    if not isinstance(record, dict):
        return False
    if str(record.get("question") or "").strip() == question:
        return True
    current_missing = {str(value).strip() for value in missing_inputs if str(value).strip()}
    previous_missing = {
        str(value).strip()
        for value in record.get("missing_inputs", [])
        if str(value).strip()
    } if isinstance(record.get("missing_inputs"), list) else set()
    return bool(current_missing and previous_missing and current_missing & previous_missing)


def _clarification_allowed(state: DeepAgentRuntimeState) -> bool:
    return int(state.get("revision_count", 0) or 0) == 0


def _revision_available(state: DeepAgentRuntimeState) -> bool:
    return int(state.get("revision_count", 0) or 0) < _revision_budget(state)


def _revision_budget(state: DeepAgentRuntimeState) -> int:
    return int(state.get("revision_budget", 2) or 0)


def _revision_instructions_for_state(state: DeepAgentRuntimeState) -> list[str]:
    instructions: list[str] = _planning_instructions_for_state(state)
    plan_review = state.get("plan_review")
    if plan_review is not None:
        instructions.extend(list(plan_review.revision_instructions))
    graph_review = state.get("graph_review")
    if graph_review is not None:
        instructions.extend(_graph_review_revision_instructions(graph_review))

    return _deduplicate_instructions(instructions)


def _graph_review_revision_instructions(review: GraphReview) -> list[str]:
    instructions: list[str] = []
    for step_id in review.missing_plan_step_ids:
        instructions.append(f"Add a graph node for plan step {step_id}.")
    for node_id in review.extra_node_ids:
        instructions.append(f"Remove graph node {node_id} because it is not in the plan.")
    for finding in review.findings:
        instructions.append(_graph_finding_to_instruction(str(finding)))
    return _deduplicate_instructions(instructions)


def _graph_finding_to_instruction(finding: str) -> str:
    if finding == "invalid_run_graph_schema":
        return "Revise the plan so the compiled graph satisfies the RunGraph schema."
    if finding == "invalid_node_shape":
        return "Revise the plan so every compiled graph node has a valid node shape."
    if finding == "invalid_edge_shape":
        return "Revise the plan so every compiled graph edge has a valid edge shape."
    if finding.startswith("missing_edge:"):
        edge = finding.removeprefix("missing_edge:")
        if "->" in edge:
            source, target = edge.split("->", 1)
            return f"Add the missing graph edge from {source} to {target}."
    if finding.startswith("extra_edge:"):
        edge = finding.removeprefix("extra_edge:")
        if "->" in edge:
            source, target = edge.split("->", 1)
            return f"Remove the unexpected graph edge from {source} to {target}."
    if finding.startswith("missing_node_metadata:"):
        _, node_id, field_name = finding.split(":", 2)
        return f"Add {field_name} metadata to graph node {node_id}."
    if finding.startswith("missing_tool_binding_operation:"):
        node_id = finding.removeprefix("missing_tool_binding_operation:")
        return f"Add a valid tool binding operation for graph node {node_id}."
    if finding.startswith("node_id_mismatch:"):
        parts = finding.split(":")
        if len(parts) == 3:
            return (
                f"Make graph node id {parts[1]} match source plan step id {parts[2]}."
            )
    if finding.startswith("duplicate_plan_step_node:"):
        step_id = finding.removeprefix("duplicate_plan_step_node:")
        return f"Remove duplicate graph nodes for plan step {step_id}."
    if finding.startswith("dependency_mismatch:"):
        return f"Fix graph dependency metadata for {finding.removeprefix('dependency_mismatch:')}."
    return f"Fix graph review finding: {finding}."


def _deduplicate_instructions(instructions: list[str]) -> list[str]:
    deduplicated: list[str] = []
    seen: set[str] = set()
    for instruction in instructions:
        cleaned = str(instruction).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduplicated.append(cleaned)
    return deduplicated


def _node_catalog_from_state(
    state: DeepAgentRuntimeState,
) -> NodeCatalogSnapshot | None:
    payload = state.get("node_catalog")
    if not payload:
        return None
    if isinstance(payload, NodeCatalogSnapshot):
        return payload
    if isinstance(payload, Mapping):
        return NodeCatalogSnapshot.model_validate(payload)
    return None


def _node_catalog_with_disabled_tools_unavailable(
    node_catalog: NodeCatalogSnapshot,
    *,
    disabled_tool_ids: list[str],
) -> NodeCatalogSnapshot:
    disabled = _expanded_tool_ids(disabled_tool_ids)
    if not disabled:
        return node_catalog

    return node_catalog.model_copy(
        update={
            "nodes": [
                _node_with_disabled_availability(node, disabled)
                for node in node_catalog.nodes
            ]
        }
    )


def _node_with_disabled_availability(
    node: NodeDefinition,
    disabled_tool_ids: set[str],
) -> NodeDefinition:
    tool_id = node.execution.tool_id
    if not tool_id or not (equivalent_tool_ids(tool_id) & disabled_tool_ids):
        return node

    return node.model_copy(
        update={
            "availability": NodeAvailability(
                status="unavailable",
                reason_code="disabled_tool",
                message="The backing tool is disabled for this run.",
            )
        }
    )


def _available_capabilities(
    context_bundle: dict[str, Any],
    *,
    node_catalog: NodeCatalogSnapshot | None = None,
) -> set[str]:
    capabilities = {"model.reasoning"}
    for tool in context_bundle.get("available_tools", []):
        if not isinstance(tool, dict):
            continue
        tool_id = str(tool.get("tool_id") or "")
        if tool_id:
            capabilities.add(tool_id)
        capabilities.update(str(value) for value in tool.get("capabilities", []))
        operations = {str(value) for value in tool.get("operations", [])}
        if tool_id == "document.read_write":
            if "read" in operations:
                capabilities.add("document.read")
            if {"write_markdown", "write_docx"} & operations:
                capabilities.add("document.write")
        elif tool_id == "document.markitdown_convert":
            capabilities.update({"document.convert", "document.convert.markdown"})
        elif tool_id == "document.typst_compile":
            capabilities.update({"document.render", "document.render.typst_pdf"})
    if node_catalog is None:
        return capabilities

    catalog_declared_capabilities = _catalog_declared_capabilities(node_catalog)
    return (
        capabilities - catalog_declared_capabilities
    ) | node_catalog.available_capabilities()


def _catalog_declared_capabilities(node_catalog: NodeCatalogSnapshot) -> set[str]:
    capabilities: set[str] = set()
    for node in node_catalog.nodes:
        capabilities.add(node.node_id)
        capabilities.update(node.capabilities)
    return capabilities


def _expanded_tool_ids(tool_ids: Iterable[str]) -> set[str]:
    expanded: set[str] = set()
    for tool_id in tool_ids:
        expanded.update(equivalent_tool_ids(str(tool_id)))
    return expanded


class _SanitizedDeepAgentRuntimeGraph:
    def __init__(self, graph):
        self._graph = graph

    def invoke(
        self,
        input: Mapping[str, Any] | Command,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if isinstance(input, Command):
            return self._graph.invoke(input, *args, **kwargs)
        sanitized_input = dict(input or {})
        sanitized_input.pop("model_client", None)
        return self._graph.invoke(sanitized_input, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._graph, name)
