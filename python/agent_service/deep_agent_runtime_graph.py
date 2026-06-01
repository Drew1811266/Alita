from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Command

from agent_service.context_manager import build_context_bundle
from agent_service.deep_agent_graph_compile import (
    compile_agent_plan_graph,
    review_compiled_graph,
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
from agent_service.goal_spec import parse_goal_spec
from agent_service.model_client import LlamaCppModelClient
from agent_service.schemas import AgentEvent, UserMessage
from agent_service.tool_execution import default_tool_packages_root
from agent_service.tool_registry import ToolRegistry


class DeepAgentRuntimeState(TypedDict, total=False):
    message: UserMessage
    project_path: str
    model_client: Any
    reasoning_decision: ReasoningDecision
    context_bundle: dict[str, Any]
    available_capabilities: set[str]
    plan_draft: PlanDraft
    thinking_status: ThinkingStatus
    plan_review: PlanReview
    compiled_graph: dict[str, Any]
    graph_review: GraphReview
    events: list[AgentEvent]


def run_deep_agent_runtime(
    message: UserMessage,
    *,
    project_path: str,
    model_client: Any | None = None,
) -> list[AgentEvent]:
    app = build_deep_agent_runtime_graph()
    result = app.invoke(
        {
            "message": message,
            "project_path": project_path,
            "model_client": model_client or LlamaCppModelClient(),
            "events": [],
        }
    )
    return list(result.get("events") or [])


def build_deep_agent_runtime_graph():
    graph = StateGraph(DeepAgentRuntimeState)
    graph.add_node("reasoning_gate", reasoning_gate)
    graph.add_node("build_context", build_context)
    graph.add_node("deep_plan", deep_plan)
    graph.add_node("review_plan", review_plan_node)
    graph.add_node("compile_agent_plan_graph", compile_agent_plan_graph_node)
    graph.add_node("review_graph", review_graph_node)
    graph.add_node("present_plan", present_plan)
    graph.add_node("clarify_required", clarify_required)
    graph.add_node("simple_reasoning_final", simple_reasoning_final)
    graph.add_node("deep_agent_failed", deep_agent_failed)
    graph.set_entry_point("reasoning_gate")
    graph.add_edge("build_context", "deep_plan")
    graph.add_edge("compile_agent_plan_graph", "review_graph")
    graph.add_edge("present_plan", END)
    graph.add_edge("clarify_required", END)
    graph.add_edge("simple_reasoning_final", END)
    graph.add_edge("deep_agent_failed", END)
    return graph.compile()


def reasoning_gate(
    state: DeepAgentRuntimeState,
) -> Command[
    Literal[
        "build_context",
        "clarify_required",
        "simple_reasoning_final",
        "deep_agent_failed",
    ]
]:
    try:
        decision = ReasoningGateEngine(model_client=state["model_client"]).decide(
            state["message"],
            context_bundle={},
        )
    except DeepPlanningError as error:
        return Command(
            update={
                "events": [
                    *state.get("events", []),
                    _planning_failed_event(error),
                ]
            },
            goto="deep_agent_failed",
        )

    events = [
        *state.get("events", []),
        AgentEvent(
            type="reasoning.decision_created",
            payload={"decision": decision.model_dump()},
        ),
    ]

    if decision.next_action == "clarification":
        return Command(
            update={"reasoning_decision": decision, "events": events},
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
    goal_spec = parse_goal_spec(message)
    context = build_context_bundle(
        message=message,
        goal_spec=goal_spec,
        project_path=state["project_path"],
        tool_registry=tool_registry,
        memory_records=[],
        memory_store=None,
    )
    context_bundle = context.model_dump()
    return {
        "context_bundle": context_bundle,
        "available_capabilities": _available_capabilities(context_bundle),
    }


def deep_plan(
    state: DeepAgentRuntimeState,
) -> Command[Literal["review_plan", "deep_agent_failed"]]:
    events = [
        *state.get("events", []),
        AgentEvent(
            type="planning.started",
            payload={"taskId": state["message"].task_id},
        ),
    ]
    try:
        result = DeepPlanningEngine(model_client=state["model_client"]).plan(
            state["message"],
            context_bundle=state.get("context_bundle") or {},
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
) -> Command[Literal["compile_agent_plan_graph", "clarify_required"]]:
    review = review_plan(
        state["plan_draft"],
        available_capabilities=state.get("available_capabilities") or {"model.reasoning"},
    )
    events = [
        *state.get("events", []),
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
        events = [
            *events,
            AgentEvent(
                type="planning.failed",
                payload={"reason": "plan_review_invalid", "review": review.model_dump()},
            ),
        ]

    return Command(
        update={"plan_review": review, "events": events},
        goto="clarify_required",
    )


def compile_agent_plan_graph_node(state: DeepAgentRuntimeState) -> dict[str, Any]:
    graph = compile_agent_plan_graph(
        state["plan_draft"],
        task_id=state["message"].task_id,
    )
    return {
        "compiled_graph": graph,
        "events": [
            *state.get("events", []),
            AgentEvent(
                type="planning.graph_compiled",
                payload={"graph": graph},
            ),
        ],
    }


def review_graph_node(
    state: DeepAgentRuntimeState,
) -> Command[Literal["present_plan", "clarify_required"]]:
    review = review_compiled_graph(state["plan_draft"], state["compiled_graph"])
    events = [
        *state.get("events", []),
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

    return Command(
        update={
            "graph_review": review,
            "events": [
                *events,
                AgentEvent(
                    type="planning.failed",
                    payload={
                        "reason": "graph_review_invalid",
                        "review": review.model_dump(),
                    },
                ),
            ],
        },
        goto="clarify_required",
    )


def present_plan(state: DeepAgentRuntimeState) -> dict[str, Any]:
    return {
        "events": [
            *state.get("events", []),
            AgentEvent(
                type="node_graph.created",
                payload={"graph": state["compiled_graph"]},
            ),
        ]
    }


def clarify_required(state: DeepAgentRuntimeState) -> dict[str, Any]:
    review = state.get("plan_review")
    decision = state.get("reasoning_decision")
    prompt = "请补充任务目标或输入信息后我再生成执行图。"
    if review is not None and review.suggested_clarifying_question:
        prompt = review.suggested_clarifying_question
    elif decision is not None and decision.next_action == "clarification":
        prompt = decision.why_this_path

    return {
        "events": [
            *state.get("events", []),
            AgentEvent(
                type="planning.clarification_required",
                payload={"taskId": state["message"].task_id, "prompt": prompt},
            ),
        ]
    }


def simple_reasoning_final(state: DeepAgentRuntimeState) -> dict[str, Any]:
    return {
        "events": [
            *state.get("events", []),
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
    return {}


def _planning_failed_event(error: DeepPlanningError) -> AgentEvent:
    return AgentEvent(
        type="planning.failed",
        payload={"reason": error.code, "message": error.message},
    )


def _available_capabilities(context_bundle: dict[str, Any]) -> set[str]:
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
    return capabilities
