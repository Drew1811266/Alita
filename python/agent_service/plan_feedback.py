from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
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

    ordinal_step_node_id = _ordinal_step_node_id(normalized, current_graph)
    if ordinal_step_node_id is not None:
        return GraphFeedbackDecision(
            GraphFeedbackKind.LOCAL_MODIFICATION,
            node_id=ordinal_step_node_id,
            reason="ordinal step mentioned",
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
    if _is_cancelled_pending_choice(pending_choice):
        return _overwrite_cancelled_event()

    effective_message = _message_for_pending_choice(message, pending_choice)
    decision = _decision_for_pending_choice(pending_choice, effective_message, current_graph)
    if decision is None:
        decision = classify_graph_feedback(
            effective_message.content,
            current_graph,
            has_run_history,
            model_feedback_hook=model_feedback_hook,
        )

    if _needs_overwrite_confirmation(has_run_history, artifact_refs, pending_choice):
        return _overwrite_confirmation_event(effective_message, current_graph, decision)

    if decision.kind == GraphFeedbackKind.FULL_REPLAN:
        return _graph_replanned_event(
            _build_replanned_graph(effective_message, current_graph),
            previous_graph_id=current_graph.graphId,
            summary="Replanned graph from user feedback.",
        )

    if decision.kind == GraphFeedbackKind.CONSTRAINT_UPDATE:
        return _graph_replanned_event(
            _apply_constraint_update(effective_message, current_graph),
            previous_graph_id=current_graph.graphId,
            summary="Updated graph constraints.",
        )

    if decision.kind == GraphFeedbackKind.LOCAL_MODIFICATION and decision.node_id:
        return _graph_replanned_event(
            _apply_local_modification(effective_message.content, current_graph, decision.node_id),
            previous_graph_id=current_graph.graphId,
            summary="Updated graph node from user feedback.",
        )

    return AgentEvent(
        type="node_graph.created",
        payload={"graph": _build_replanned_graph(effective_message, current_graph).model_dump()},
    )


def _message_for_pending_choice(
    message: UserMessage,
    pending_choice: dict[str, Any] | None,
) -> UserMessage:
    if not _is_confirmed_pending_choice(pending_choice):
        return message
    pending_message = pending_choice.get("message") if pending_choice else None
    if not isinstance(pending_message, str) or not pending_message.strip():
        return message
    return message.model_copy(update={"content": pending_message})


def _decision_for_pending_choice(
    pending_choice: dict[str, Any] | None,
    message: UserMessage,
    current_graph: RunGraph,
) -> GraphFeedbackDecision | None:
    if not _is_confirmed_pending_choice(pending_choice):
        return None

    kind_value = pending_choice.get("kind") if pending_choice else None
    try:
        kind = GraphFeedbackKind(kind_value)
    except (TypeError, ValueError):
        return classify_graph_feedback(message.content, current_graph)

    classified = classify_graph_feedback(message.content, current_graph)
    if kind == GraphFeedbackKind.LOCAL_MODIFICATION:
        return GraphFeedbackDecision(
            kind,
            node_id=classified.node_id,
            reason="confirmed pending overwrite",
        )
    return GraphFeedbackDecision(kind, reason="confirmed pending overwrite")


def _is_confirmed_pending_choice(pending_choice: dict[str, Any] | None) -> bool:
    return bool(pending_choice and pending_choice.get("id") == "confirm_overwrite")


def _is_cancelled_pending_choice(pending_choice: dict[str, Any] | None) -> bool:
    return bool(pending_choice and pending_choice.get("id") == "cancel")


def _overwrite_cancelled_event() -> AgentEvent:
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return AgentEvent(
        type="message.created",
        payload={
            "message": {
                "messageId": f"assistant-{uuid4()}",
                "role": "assistant",
                "content": "Graph overwrite cancelled; the current graph was kept unchanged.",
                "attachments": [],
                "createdAt": created_at,
            }
        },
    )


def _mentioned_node_ids(normalized_message: str, graph: RunGraph) -> list[str]:
    matches: list[str] = []
    for node in graph.nodes:
        if node.nodeId.lower() in normalized_message or node.displayName.lower() in normalized_message:
            matches.append(node.nodeId)
    return matches


def _ordinal_step_node_id(normalized_message: str, graph: RunGraph) -> str | None:
    match = re.search(r"\bstep\s+(\d+)\b", normalized_message)
    if match is None:
        return None

    step_number = int(match.group(1))
    executable_nodes = [node for node in graph.nodes if node.nodeType != "planning"]
    if step_number < 1 or step_number > len(executable_nodes):
        return None
    return executable_nodes[step_number - 1].nodeId


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
    graph_with_constraints = graph.model_copy(deep=True)
    graph_with_constraints.metadata = {
        **graph_with_constraints.metadata,
        "constraints": [
            *graph_with_constraints.metadata.get("constraints", []),
            message.content,
        ],
    }
    regenerated = _build_replanned_graph(message, graph_with_constraints)
    if _regenerated_plan_changes_executable_shape(graph, regenerated):
        regenerated.metadata = {
            **regenerated.metadata,
            "feedbackRegeneratedPlanningNodeIds": _planning_node_ids(regenerated),
        }
        return regenerated

    updated = graph.model_copy(deep=True)
    target = next((node for node in updated.nodes if node.nodeId == "task-analysis"), None)
    if target is None:
        target = next((node for node in updated.nodes if node.nodeType == "planning"), None)
    if target is not None:
        target.summary = _append_unique_note(target.summary, f"Constraint: {message.content}")

    regenerated_node_ids: list[str] = []
    selection_node = next((node for node in updated.nodes if node.nodeId == "tool-selection"), None)
    if selection_node is not None:
        selection_node.summary = _append_unique_note(
            selection_node.summary,
            f"Regenerated selection for constraint: {message.content}",
        )
        regenerated_node_ids.append(selection_node.nodeId)

    order_node = next((node for node in updated.nodes if node.nodeId == "execution-order-planning"), None)
    if order_node is not None:
        order_node.summary = _append_unique_note(
            order_node.summary,
            f"Regenerated execution order for constraint: {message.content}",
        )
        regenerated_node_ids.append(order_node.nodeId)

    updated.metadata = {
        **updated.metadata,
        "constraints": graph_with_constraints.metadata["constraints"],
        "feedbackRegeneratedPlanningNodeIds": sorted(regenerated_node_ids),
    }
    return updated


def _regenerated_plan_changes_executable_shape(
    current_graph: RunGraph,
    regenerated_graph: RunGraph,
) -> bool:
    current_node_ids = {node.nodeId for node in current_graph.nodes}
    regenerated_capability_summary = _node_summary(regenerated_graph, "capability-analysis")
    regenerated_tool_summary = _node_summary(regenerated_graph, "tool-selection")
    current_text = " ".join(node.summary for node in current_graph.nodes)
    regenerated_text = f"{regenerated_capability_summary} {regenerated_tool_summary}"

    if "network.fetch" in regenerated_text and "network.fetch" not in current_text:
        return True

    return any(
        node.nodeType == "temporary_placeholder" and node.nodeId not in current_node_ids
        for node in regenerated_graph.nodes
    )


def _node_summary(graph: RunGraph, node_id: str) -> str:
    node = next((candidate for candidate in graph.nodes if candidate.nodeId == node_id), None)
    return node.summary if node is not None else ""


def _planning_node_ids(graph: RunGraph) -> list[str]:
    return sorted(node.nodeId for node in graph.nodes if node.nodeType == "planning")


def _build_replanned_graph(message: UserMessage, previous_graph: RunGraph) -> RunGraph:
    prior_constraints = list(previous_graph.metadata.get("constraints", []))
    planning_message = _message_with_prior_constraints(message.content, prior_constraints)
    task_plan = analyze_task(planning_message, message.attachments)
    task_plan.task_id = message.task_id
    registry = ToolRegistry.from_packages_root(default_tool_packages_root())
    task_plan.selected_tools = select_tools(task_plan.requirements, registry.enabled_tools())
    task_plan.tool_gaps = resolve_tool_gaps(task_plan.requirements, task_plan.selected_tools)
    graph_payload = build_task_graph(task_plan)
    if graph_payload.get("graphId") == previous_graph.graphId:
        graph_payload["graphId"] = f"{previous_graph.graphId}-replanned-{uuid4().hex[:8]}"
    metadata = graph_payload.setdefault("metadata", {})
    metadata["previousGraphId"] = previous_graph.graphId
    if prior_constraints:
        metadata["constraints"] = prior_constraints
        _append_prior_constraints_to_planning_summary(graph_payload, prior_constraints)
    return RunGraph.model_validate(graph_payload)


def _message_with_prior_constraints(message: str, prior_constraints: list[str]) -> str:
    if not prior_constraints:
        return message
    constraints = "\n".join(f"- {constraint}" for constraint in prior_constraints)
    return f"{message}\n\nExisting constraints to preserve:\n{constraints}"


def _append_prior_constraints_to_planning_summary(
    graph_payload: dict[str, Any],
    prior_constraints: list[str],
) -> None:
    target = next(
        (node for node in graph_payload.get("nodes", []) if node.get("nodeId") == "task-analysis"),
        None,
    )
    if target is None:
        return
    for constraint in prior_constraints:
        target["summary"] = _append_unique_note(
            target.get("summary", ""),
            f"Prior constraint: {constraint}",
        )


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
