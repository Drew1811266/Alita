from __future__ import annotations

from agent_service.graph import run_agent
from agent_service.plan_feedback import (
    GraphFeedbackKind,
    apply_graph_feedback,
    classify_graph_feedback,
)
from agent_service.schemas import RunGraph, ScriptReviewState, UserMessage


def _node(
    node_id: str,
    display_name: str,
    summary: str,
    *,
    node_type: str = "model",
    dependencies: list[str] | None = None,
    status: str = "waiting",
    script_review: dict | None = None,
) -> dict:
    node = {
        "nodeId": node_id,
        "nodeType": node_type,
        "displayName": display_name,
        "status": status,
        "summary": summary,
        "createdBy": "agent",
        "dependencies": dependencies or [],
        "inputPorts": [],
        "outputPorts": [],
        "artifactRefs": [],
        "retryCount": 0,
        "position": {"x": 0, "y": 0},
    }
    if script_review is not None:
        node["scriptReview"] = script_review
    return node


def _graph() -> RunGraph:
    return RunGraph(
        graphId="graph-1",
        nodes=[
            _node("task-analysis", "Task Analysis", "Understand the task.", node_type="planning"),
            _node("tool-selection", "Tool Selection", "Choose tools for the workflow.", node_type="planning"),
            _node(
                "execution-order-planning",
                "Execution Order Planning",
                "Order the workflow steps.",
                node_type="planning",
            ),
            _node("extract-data", "Extract Data", "Extract rows from the source."),
            _node(
                "summarize-data",
                "Summarize Data",
                "Summarize the extracted rows.",
                dependencies=["extract-data"],
            ),
            _node(
                "write-output",
                "Write Output",
                "Write the final report.",
                node_type="output",
                dependencies=["summarize-data"],
            ),
        ],
        edges=[
            {"id": "extract-data-summarize-data", "source": "extract-data", "target": "summarize-data"},
            {"id": "summarize-data-write-output", "source": "summarize-data", "target": "write-output"},
        ],
    )


def _script_graph() -> RunGraph:
    return RunGraph(
        graphId="script-graph",
        nodes=[
            _node("task-analysis", "Task Analysis", "Understand the task.", node_type="planning"),
            _node(
                "cleanup-script",
                "Cleanup Script",
                "Delete matching temporary files.",
                node_type="temporary_script",
                status="needs_permission",
                script_review={
                    "status": "approved",
                    "summary": "Approved destructive cleanup script.",
                    "permissions": ["write_workspace", "delete_files"],
                    "riskLevel": "high",
                    "requiresApproval": True,
                    "codePreview": "remove_files(pattern)",
                    "inputContract": {"pattern": "string"},
                    "outputContract": {"deleted": "integer"},
                    "approvalFingerprint": "fingerprint-1",
                },
            ),
        ],
        edges=[],
    )


def test_classifies_feedback_kinds() -> None:
    graph = _graph()

    assert (
        classify_graph_feedback("Change the Summarize Data step to include totals.", graph).kind
        == GraphFeedbackKind.LOCAL_MODIFICATION
    )
    assert (
        classify_graph_feedback("This direction is wrong, restart the plan.", graph).kind
        == GraphFeedbackKind.FULL_REPLAN
    )
    assert (
        classify_graph_feedback("Keep it under a $50 budget and use only CSV sources.", graph).kind
        == GraphFeedbackKind.CONSTRAINT_UPDATE
    )
    assert (
        classify_graph_feedback("Also create a weekly calendar reminder.", graph).kind
        == GraphFeedbackKind.NEW_TASK
    )


def test_classifies_ordinal_step_feedback_as_local_modification() -> None:
    graph = _graph()

    decision = classify_graph_feedback("Change step 2 to use the safer parser.", graph)

    assert decision.kind == GraphFeedbackKind.LOCAL_MODIFICATION
    assert decision.node_id == "summarize-data"


def test_ambiguous_feedback_can_use_model_hook() -> None:
    graph = _graph()

    decision = classify_graph_feedback(
        "Make it tighter.",
        graph,
        model_feedback_hook=lambda message, current_graph, has_run_history: GraphFeedbackKind.LOCAL_MODIFICATION,
    )

    assert decision.kind == GraphFeedbackKind.LOCAL_MODIFICATION


def test_local_modification_preserves_unaffected_nodes_and_marks_downstream() -> None:
    graph = _graph()

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Change the Extract Data node to read JSON files."),
        graph,
    )

    assert event.type == "graph.replanned"
    updated = RunGraph.model_validate(event.payload["graph"])
    nodes = {node.nodeId: node for node in updated.nodes}
    assert nodes["task-analysis"].summary == "Understand the task."
    assert "read JSON files" in nodes["extract-data"].summary
    assert "Upstream feedback changed extract-data." in nodes["summarize-data"].summary
    assert "Upstream feedback changed extract-data." in nodes["write-output"].summary
    assert updated.graphId == graph.graphId


def test_constraint_update_regenerates_selection_planning_and_preserves_execution_nodes() -> None:
    graph = _graph()
    original_nodes = {node.nodeId: node for node in graph.nodes}

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Use only CSV sources and keep extraction before summary."),
        graph,
    )

    assert event.type == "graph.replanned"
    updated = RunGraph.model_validate(event.payload["graph"])
    nodes = {node.nodeId: node for node in updated.nodes}
    assert "Constraint: Use only CSV sources and keep extraction before summary." in nodes["task-analysis"].summary
    assert nodes["tool-selection"].summary != original_nodes["tool-selection"].summary
    assert "Regenerated selection for constraint" in nodes["tool-selection"].summary
    assert nodes["execution-order-planning"].summary != original_nodes["execution-order-planning"].summary
    assert "Regenerated execution order for constraint" in nodes["execution-order-planning"].summary
    assert nodes["extract-data"] == original_nodes["extract-data"]
    assert nodes["summarize-data"] == original_nodes["summarize-data"]
    assert nodes["write-output"] == original_nodes["write-output"]
    assert updated.metadata["constraints"] == ["Use only CSV sources and keep extraction before summary."]
    assert updated.metadata["feedbackRegeneratedPlanningNodeIds"] == [
        "execution-order-planning",
        "tool-selection",
    ]


def test_full_replan_replaces_graph() -> None:
    graph = _graph()

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Restart with a plan to create a Python script that counts CSV rows."),
        graph,
    )

    assert event.type == "graph.replanned"
    assert event.payload["previousGraphId"] == "graph-1"
    updated = RunGraph.model_validate(event.payload["graph"])
    assert updated.graphId != graph.graphId
    assert [node.nodeId for node in updated.nodes] != [node.nodeId for node in graph.nodes]


def test_graph_with_run_history_asks_before_overwrite() -> None:
    graph = _graph()

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Restart, the direction is wrong."),
        graph,
        has_run_history=True,
        artifact_refs=["artifact-1"],
    )

    assert event.type == "graph.overwrite_confirmation_required"
    assert event.payload["previousGraphId"] == "graph-1"
    assert event.payload["pendingChoice"]["kind"] == "full_replan"
    assert [choice["id"] for choice in event.payload["choices"]] == ["confirm_overwrite", "cancel"]


def test_confirmed_overwrite_emits_graph_replanned() -> None:
    graph = _graph()

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Restart, the direction is wrong."),
        graph,
        has_run_history=True,
        pending_choice={"id": "confirm_overwrite", "kind": "full_replan"},
    )

    assert event.type == "graph.replanned"


def test_changed_high_risk_script_requires_reapproval() -> None:
    graph = _script_graph()

    event = apply_graph_feedback(
        UserMessage(
            task_id="task-1",
            content="Change the Cleanup Script codePreview to remove_files(pattern, dry_run=False).",
        ),
        graph,
    )

    updated = RunGraph.model_validate(event.payload["graph"])
    script_node = next(node for node in updated.nodes if node.nodeId == "cleanup-script")
    assert script_node.scriptReview == ScriptReviewState(
        status="not_reviewed",
        summary="Approved destructive cleanup script.",
        permissions=["write_workspace", "delete_files"],
        riskLevel="high",
        requiresApproval=True,
        codePreview="remove_files(pattern, dry_run=False).",
        inputContract={"pattern": "string"},
        outputContract={"deleted": "integer"},
        approvalFingerprint=None,
    )


def test_run_agent_routes_feedback_when_current_graph_exists() -> None:
    graph = _graph()

    events = run_agent(
        UserMessage(task_id="task-1", content="Change the Summarize Data step to include totals."),
        current_graph=graph,
    )

    assert [event.type for event in events] == ["graph.replanned"]
