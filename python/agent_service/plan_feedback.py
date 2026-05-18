from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import uuid4

from agent_service.schemas import AgentEvent, RunGraph, UserMessage
from agent_service.task_planner import (
    analyze_task,
    build_task_graph,
    resolve_tool_gaps,
    select_tools,
)
from agent_service.tool_execution import default_tool_packages_root
from agent_service.tool_registry import ToolRegistry


class GraphFeedbackKind(str, Enum):
    LOCAL_MODIFICATION = "local_modification"
    FULL_REPLAN = "full_replan"
    CONSTRAINT_UPDATE = "constraint_update"
    NEW_TASK = "new_task"


@dataclass(frozen=True)
class GraphFeedbackDecision:
    kind: GraphFeedbackKind
    node_id: str | None = None
    reason: str = ""


ModelFeedbackHook = Callable[[str, RunGraph, bool], GraphFeedbackKind | GraphFeedbackDecision]

_FULL_REPLAN_KEYWORDS = ("direction is wrong", "restart", "start over", "replan", "wrong direction")
_CONSTRAINT_KEYWORDS = (
    "budget",
    "under $",
    "source type",
    "sources",
    "style",
    "tone",
    "order",
    "only ",
    "must ",
    "constraint",
)


def classify_graph_feedback(
    message: str,
    current_graph: RunGraph | None,
    has_run_history: bool = False,
    model_feedback_hook: ModelFeedbackHook | None = None,
) -> GraphFeedbackDecision:
    if current_graph is None:
        return GraphFeedbackDecision(GraphFeedbackKind.NEW_TASK, reason="no current graph")

    normalized = message.lower()
    if any(keyword in normalized for keyword in _FULL_REPLAN_KEYWORDS):
        return GraphFeedbackDecision(GraphFeedbackKind.FULL_REPLAN, reason="full replan keyword")

    mentioned_node_ids = _mentioned_node_ids(normalized, current_graph)
    if len(mentioned_node_ids) == 1 or ("step" in normalized and mentioned_node_ids):
        return GraphFeedbackDecision(
            GraphFeedbackKind.LOCAL_MODIFICATION,
            node_id=mentioned_node_ids[0],
            reason="single node mentioned",
        )

    if any(keyword in normalized for keyword in _CONSTRAINT_KEYWORDS):
        return GraphFeedbackDecision(GraphFeedbackKind.CONSTRAINT_UPDATE, reason="constraint keyword")

    if model_feedback_hook is not None:
        hook_decision = model_feedback_hook(message, current_graph, has_run_history)
        if isinstance(hook_decision, GraphFeedbackDecision):
            return hook_decision
        return GraphFeedbackDecision(hook_decision, reason="model hook")

    return GraphFeedbackDecision(GraphFeedbackKind.NEW_TASK, reason="unrelated request")


def apply_graph_feedback(
    message: UserMessage,
    current_graph: RunGraph,
    *,
    has_run_history: bool = False,
    artifact_refs: list[str] | None = None,
    pending_choice: dict[str, Any] | None = None,
    model_feedback_hook: ModelFeedbackHook | None = None,
) -> AgentEvent:
    decision = classify_graph_feedback(
        message.content,
        current_graph,
        has_run_history,
        model_feedback_hook=model_feedback_hook,
    )

    if decision.kind == GraphFeedbackKind.FULL_REPLAN:
        if _needs_overwrite_confirmation(has_run_history, artifact_refs, pending_choice):
            return _overwrite_confirmation_event(message, current_graph, decision)
        return _graph_replanned_event(
            _build_replanned_graph(message, current_graph),
            previous_graph_id=current_graph.graphId,
            summary="Replanned graph from user feedback.",
        )

    if decision.kind == GraphFeedbackKind.CONSTRAINT_UPDATE:
        return _graph_replanned_event(
            _apply_constraint_update(message, current_graph),
            previous_graph_id=current_graph.graphId,
            summary="Updated graph constraints.",
        )

    if decision.kind == GraphFeedbackKind.LOCAL_MODIFICATION and decision.node_id:
        return _graph_replanned_event(
            _apply_local_modification(message.content, current_graph, decision.node_id),
            previous_graph_id=current_graph.graphId,
            summary="Updated graph node from user feedback.",
        )

    return AgentEvent(
        type="node_graph.created",
        payload={"graph": _build_replanned_graph(message, current_graph).model_dump()},
    )


def _mentioned_node_ids(normalized_message: str, graph: RunGraph) -> list[str]:
    matches: list[str] = []
    for node in graph.nodes:
        if node.nodeId.lower() in normalized_message or node.displayName.lower() in normalized_message:
            matches.append(node.nodeId)
    return matches


def _needs_overwrite_confirmation(
    has_run_history: bool,
    artifact_refs: list[str] | None,
    pending_choice: dict[str, Any] | None,
) -> bool:
    if pending_choice and pending_choice.get("id") == "confirm_overwrite":
        return False
    return has_run_history or bool(artifact_refs)


def _overwrite_confirmation_event(
    message: UserMessage,
    graph: RunGraph,
    decision: GraphFeedbackDecision,
) -> AgentEvent:
    return AgentEvent(
        type="graph.overwrite_confirmation_required",
        payload={
            "taskId": message.task_id,
            "previousGraphId": graph.graphId,
            "summary": "This change will replace the current graph.",
            "pendingChoice": {
                "id": "pending-graph-overwrite",
                "kind": decision.kind.value,
                "message": message.content,
            },
            "choices": [
                {
                    "id": "confirm_overwrite",
                    "label": "Overwrite graph",
                    "description": "Replace the current graph and keep run history as historical context.",
                },
                {
                    "id": "cancel",
                    "label": "Cancel",
                    "description": "Keep the current graph unchanged.",
                },
            ],
        },
    )


def _graph_replanned_event(
    graph: RunGraph,
    *,
    previous_graph_id: str,
    summary: str,
) -> AgentEvent:
    return AgentEvent(
        type="graph.replanned",
        payload={
            "graph": graph.model_dump(),
            "previousGraphId": previous_graph_id,
            "summary": summary,
        },
    )


def _apply_local_modification(message: str, graph: RunGraph, node_id: str) -> RunGraph:
    updated = graph.model_copy(deep=True)
    changed = {node_id}
    downstream = _downstream_node_ids(updated, node_id)
    for node in updated.nodes:
        if node.nodeId == node_id:
            node.summary = _append_feedback_note(node.summary, message)
            if node.scriptReview is not None and _apply_script_review_changes(message, node.scriptReview):
                changed.add(node.nodeId)
        elif node.nodeId in downstream:
            node.summary = _append_unique_note(
                node.summary,
                f"Upstream feedback changed {node_id}.",
            )

    if changed:
        updated.metadata = {
            **updated.metadata,
            "feedbackUpdatedNodeIds": sorted(changed),
        }
    return updated


def _apply_constraint_update(message: UserMessage, graph: RunGraph) -> RunGraph:
    updated = graph.model_copy(deep=True)
    target = next((node for node in updated.nodes if node.nodeId == "task-analysis"), None)
    if target is None:
        target = next((node for node in updated.nodes if node.nodeType == "planning"), None)
    if target is not None:
        target.summary = _append_unique_note(target.summary, f"Constraint: {message.content}")
    updated.metadata = {
        **updated.metadata,
        "constraints": [*updated.metadata.get("constraints", []), message.content],
    }
    return updated


def _build_replanned_graph(message: UserMessage, previous_graph: RunGraph) -> RunGraph:
    task_plan = analyze_task(message.content, message.attachments)
    task_plan.task_id = message.task_id
    registry = ToolRegistry.from_packages_root(default_tool_packages_root())
    task_plan.selected_tools = select_tools(task_plan.requirements, registry.enabled_tools())
    task_plan.tool_gaps = resolve_tool_gaps(task_plan.requirements, task_plan.selected_tools)
    graph_payload = build_task_graph(task_plan)
    if graph_payload.get("graphId") == previous_graph.graphId:
        graph_payload["graphId"] = f"{previous_graph.graphId}-replanned-{uuid4().hex[:8]}"
    graph_payload.setdefault("metadata", {})["previousGraphId"] = previous_graph.graphId
    return RunGraph.model_validate(graph_payload)


def _downstream_node_ids(graph: RunGraph, node_id: str) -> set[str]:
    downstream: set[str] = set()
    frontier = [node_id]
    while frontier:
        source = frontier.pop()
        for edge in graph.edges:
            if edge.source == source and edge.target not in downstream:
                downstream.add(edge.target)
                frontier.append(edge.target)
    return downstream


def _append_feedback_note(summary: str, message: str) -> str:
    return _append_unique_note(summary, f"Feedback: {message}")


def _append_unique_note(summary: str, note: str) -> str:
    if note in summary:
        return summary
    return f"{summary}\n{note}"


def _apply_script_review_changes(message: str, review: Any) -> bool:
    code_preview = _extract_after_keyword(message, "codePreview to")
    changed = False
    if code_preview and code_preview != review.codePreview:
        review.codePreview = code_preview
        changed = True

    if changed:
        review.status = "not_reviewed"
        review.approvalFingerprint = None
    return changed


def _extract_after_keyword(message: str, keyword: str) -> str | None:
    index = message.lower().find(keyword.lower())
    if index < 0:
        return None
    value = message[index + len(keyword) :].strip()
    return value or None
