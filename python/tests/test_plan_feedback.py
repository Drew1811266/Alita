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


def _graph_with_constraints() -> RunGraph:
    graph = _graph()
    graph.metadata = {"constraints": ["Use verified sources only."]}
    return graph


def _graph_with_network_constraint() -> RunGraph:
    graph = _graph()
    graph.metadata = {"constraints": ["Download the source data from the network."]}
    return graph


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


def test_local_modification_resets_affected_and_downstream_completed_state() -> None:
    payload = _graph().model_dump()
    for node in payload["nodes"]:
        if node["nodeId"] in {"extract-data", "summarize-data", "write-output"}:
            node["status"] = "completed"
            node["artifactRefs"] = [f"artifact-{node['nodeId']}"]
            node["resourceUsage"] = {"cpu": "high"}
            node["runtimeNotice"] = {
                "kind": "completed",
                "message": "Previous run completed.",
            }
            node["lastRun"] = {
                "runId": f"run-{node['nodeId']}",
                "completedAt": "2026-05-19T00:00:00Z",
            }
    graph = RunGraph.model_validate(payload)

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Change the Extract Data node to read JSON files."),
        graph,
    )

    updated_nodes = {node["nodeId"]: node for node in event.payload["graph"]["nodes"]}
    for node_id in ["extract-data", "summarize-data", "write-output"]:
        node = updated_nodes[node_id]
        assert node["status"] == "waiting"
        assert node["artifactRefs"] == []
        assert node.get("resourceUsage") is None
        assert node.get("runtimeNotice") is None
        assert node.get("lastRun") is None


def test_local_modification_preserves_unaffected_node_last_run() -> None:
    payload = _graph().model_dump()
    payload["nodes"].append(
        _node(
            "independent-output",
            "Independent Output",
            "Keep independent output.",
            node_type="output",
            status="completed",
        )
    )
    payload["nodes"][-1]["lastRun"] = {
        "runId": "run-independent",
        "completedAt": "2026-05-19T00:00:00Z",
    }
    graph = RunGraph.model_validate(payload)

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Change the Extract Data node to read JSON files."),
        graph,
    )

    updated_nodes = {node["nodeId"]: node for node in event.payload["graph"]["nodes"]}
    assert updated_nodes["independent-output"]["lastRun"] == {
        "runId": "run-independent",
        "completedAt": "2026-05-19T00:00:00Z",
    }


def test_constraint_update_regenerates_planning_and_replaces_changed_shape() -> None:
    graph = _graph()

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Use a concise style and keep extraction before summary."),
        graph,
    )

    assert event.type == "graph.replanned"
    updated = RunGraph.model_validate(event.payload["graph"])
    nodes = {node.nodeId: node for node in updated.nodes}
    assert nodes["task-analysis"].summary.count(
        "Use a concise style and keep extraction before summary."
    ) == 1
    assert "tool-selection" in nodes
    assert "execution-order-planning" in nodes
    assert [node.nodeId for node in updated.nodes] != [node.nodeId for node in graph.nodes]
    assert updated.metadata["constraints"] == ["Use a concise style and keep extraction before summary."]
    assert updated.metadata["feedbackRegeneratedPlanningNodeIds"] == [
        "capability-analysis",
        "context-gathering",
        "evidence-summary",
        "execution-order-planning",
        "plan-draft",
        "plan-review",
        "task-analysis",
        "tool-selection",
    ]


def test_constraint_update_replaces_graph_when_planner_adds_temporary_script() -> None:
    graph = _graph()

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Constraint: inspect a local CSV file and count rows."),
        graph,
    )

    assert event.type == "graph.replanned"
    updated = RunGraph.model_validate(event.payload["graph"])
    temporary_script_nodes = [
        node for node in updated.nodes if node.nodeType == "temporary_script"
    ]
    assert temporary_script_nodes
    assert temporary_script_nodes[0].scriptReview is not None
    assert "extract-data" not in {node.nodeId for node in updated.nodes}


def test_constraint_update_reruns_planner_and_can_change_graph_shape() -> None:
    graph = _graph()

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Constraint: Download the source data from the network."),
        graph,
    )

    assert event.type == "graph.replanned"
    updated = RunGraph.model_validate(event.payload["graph"])
    nodes = {node.nodeId: node for node in updated.nodes}
    assert "network.fetch" in nodes["capability-analysis"].summary
    assert "network.fetch" in nodes["tool-selection"].summary
    assert any("network.fetch" in node.summary for node in updated.nodes)
    assert [node.nodeId for node in updated.nodes] != [node.nodeId for node in graph.nodes]
    assert updated.metadata["constraints"] == [
        "Constraint: Download the source data from the network."
    ]


def test_constraint_update_replaces_graph_for_unsupported_missing_tool_output() -> None:
    graph = _graph()

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Constraint: Must handle password credentials."),
        graph,
    )

    assert event.type == "graph.replanned"
    updated = RunGraph.model_validate(event.payload["graph"])
    nodes = {node.nodeId: node for node in updated.nodes}
    assert "credential.handle" in nodes["capability-analysis"].summary
    assert "credential.handle" in nodes["tool-selection"].summary
    assert "missing-tool-response" in nodes
    assert "unsupported unsafe capability" in nodes["missing-tool-response"].summary
    assert "extract-data" not in nodes


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
    assert event.payload["pendingChoice"]["previousGraphId"] == "graph-1"
    assert [choice["id"] for choice in event.payload["choices"]] == ["confirm_overwrite", "cancel"]


def test_local_modification_with_run_history_asks_before_overwrite() -> None:
    graph = _graph()

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Change the Extract Data node to read JSON files."),
        graph,
        has_run_history=True,
    )

    assert event.type == "graph.overwrite_confirmation_required"
    assert event.payload["pendingChoice"]["kind"] == "local_modification"
    assert event.payload["pendingChoice"]["previousGraphId"] == graph.graphId
    assert event.payload["pendingChoice"]["nodeId"] == "extract-data"


def test_constraint_update_with_artifacts_asks_before_overwrite() -> None:
    graph = _graph()

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Use only CSV sources and keep extraction before summary."),
        graph,
        artifact_refs=["artifact-1"],
    )

    assert event.type == "graph.overwrite_confirmation_required"
    assert event.payload["pendingChoice"]["kind"] == "constraint_update"


def test_confirmed_overwrite_emits_graph_replanned() -> None:
    graph = _graph()

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Restart, the direction is wrong."),
        graph,
        has_run_history=True,
        pending_choice={"id": "confirm_overwrite", "kind": "full_replan"},
    )

    assert event.type == "graph.replanned"


def test_confirmed_overwrite_uses_original_pending_feedback() -> None:
    graph = _graph()
    confirmation = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Restart, the direction is wrong."),
        graph,
        has_run_history=True,
    )
    assert confirmation.type == "graph.overwrite_confirmation_required"

    confirmed_choice = {
        **confirmation.payload["pendingChoice"],
        "id": "confirm_overwrite",
    }
    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="yes"),
        graph,
        has_run_history=True,
        pending_choice=confirmed_choice,
    )

    assert event.type == "graph.replanned"
    updated = RunGraph.model_validate(event.payload["graph"])
    assert updated.graphId != graph.graphId


def test_confirmed_local_overwrite_uses_pending_node_id() -> None:
    graph = _graph()
    confirmation = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Change the Extract Data node to read JSON files."),
        graph,
        has_run_history=True,
    )
    assert confirmation.type == "graph.overwrite_confirmation_required"

    confirmed_choice = {
        **confirmation.payload["pendingChoice"],
        "id": "confirm_overwrite",
    }
    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="yes"),
        graph,
        has_run_history=True,
        pending_choice=confirmed_choice,
    )

    assert event.type == "graph.replanned"
    updated = RunGraph.model_validate(event.payload["graph"])
    nodes = {node.nodeId: node for node in updated.nodes}
    assert updated.graphId == graph.graphId
    assert "read JSON files" in nodes["extract-data"].summary
    assert "read JSON files" not in nodes["summarize-data"].summary


def test_confirmed_new_task_overwrite_emits_graph_replanned() -> None:
    graph = _graph()
    confirmation = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Also create a weekly calendar reminder."),
        graph,
        has_run_history=True,
    )
    assert confirmation.type == "graph.overwrite_confirmation_required"
    assert confirmation.payload["pendingChoice"]["kind"] == "new_task"

    confirmed_choice = {
        **confirmation.payload["pendingChoice"],
        "id": "confirm_overwrite",
    }
    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="yes"),
        graph,
        has_run_history=True,
        pending_choice=confirmed_choice,
    )

    assert event.type == "graph.replanned"
    assert event.payload["previousGraphId"] == graph.graphId


def test_cancelled_overwrite_returns_message_without_replacing_graph() -> None:
    graph = _graph()
    confirmation = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Restart, the direction is wrong."),
        graph,
        has_run_history=True,
    )
    assert confirmation.type == "graph.overwrite_confirmation_required"

    cancelled_choice = {
        **confirmation.payload["pendingChoice"],
        "id": "cancel",
    }
    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="no"),
        graph,
        has_run_history=True,
        pending_choice=cancelled_choice,
    )

    assert event.type == "message.created"
    assert "kept unchanged" in event.payload["message"]["content"]


def test_stale_overwrite_confirmation_does_not_apply_to_different_graph() -> None:
    graph = _graph()
    confirmation = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Restart, the direction is wrong."),
        graph,
        has_run_history=True,
    )
    other_graph = _graph()
    other_graph.graphId = "graph-2"
    stale_choice = {
        **confirmation.payload["pendingChoice"],
        "id": "confirm_overwrite",
    }

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="yes"),
        other_graph,
        has_run_history=True,
        pending_choice=stale_choice,
    )

    assert event.type == "message.created"
    assert "stale" in event.payload["message"]["content"].lower()


def test_full_replan_preserves_prior_constraints_in_metadata_and_planning_summary() -> None:
    graph = _graph_with_constraints()

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Restart with a plan to create a Python script that counts CSV rows."),
        graph,
    )

    assert event.type == "graph.replanned"
    updated = RunGraph.model_validate(event.payload["graph"])
    assert updated.metadata["constraints"] == ["Use verified sources only."]
    task_analysis = next(node for node in updated.nodes if node.nodeId == "task-analysis")
    assert "Prior constraint: Use verified sources only." in task_analysis.summary


def test_full_replan_uses_prior_constraints_as_planning_input() -> None:
    graph = _graph_with_network_constraint()

    event = apply_graph_feedback(
        UserMessage(task_id="task-1", content="Restart with a plan to count CSV rows."),
        graph,
    )

    assert event.type == "graph.replanned"
    updated = RunGraph.model_validate(event.payload["graph"])
    capability_analysis = next(node for node in updated.nodes if node.nodeId == "capability-analysis")
    tool_selection = next(node for node in updated.nodes if node.nodeId == "tool-selection")
    assert "network.fetch" in capability_analysis.summary
    assert "network.fetch" in tool_selection.summary


def test_changed_high_risk_script_requires_reapproval() -> None:
    payload = _script_graph().model_dump()
    payload["nodes"][1]["status"] = "completed"
    payload["nodes"][1]["artifactRefs"] = ["artifact-script"]
    payload["nodes"][1]["resourceUsage"] = {"cpu": "high"}
    payload["nodes"][1]["runtimeNotice"] = {
        "kind": "completed",
        "message": "Previous run completed.",
    }
    payload["nodes"][1]["lastRun"] = {
        "runId": "run-script",
        "completedAt": "2026-05-19T00:00:00Z",
    }
    graph = RunGraph.model_validate(payload)

    event = apply_graph_feedback(
        UserMessage(
            task_id="task-1",
            content="Change the Cleanup Script codePreview to remove_files(pattern, dry_run=False).",
        ),
        graph,
    )

    updated = RunGraph.model_validate(event.payload["graph"])
    script_node = next(node for node in updated.nodes if node.nodeId == "cleanup-script")
    assert script_node.status == "needs_permission"
    assert script_node.artifactRefs == []
    assert script_node.resourceUsage is None
    assert script_node.runtimeNotice is None
    assert script_node.lastRun is None
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
