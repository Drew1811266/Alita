from __future__ import annotations

import pytest

from agent_service.goal_spec import GoalSpec
from agent_service.graph_compiler import compile_task_graph_to_node_graph
from agent_service.schemas import RunGraph
from agent_service.task_graph import (
    TaskGraph,
    TaskNode,
    TaskNodeUi,
    build_document_task_graph,
)


def _document_goal_spec() -> GoalSpec:
    return GoalSpec(
        goal="summarize this document as a PDF report",
        task_type="document_processing",
        deliverable="pdf_report",
        constraints=["write artifacts locally"],
        success_criteria=["A PDF report exists"],
        required_context=["attachment"],
        risk_level="local_write",
        permissions_required=["read_attachment", "write_project_artifact"],
        confidence=0.9,
    )


def test_compile_document_task_graph_to_existing_node_graph_shape() -> None:
    task_graph = build_document_task_graph("task-document", _document_goal_spec())

    node_graph = compile_task_graph_to_node_graph(task_graph)

    RunGraph.model_validate(node_graph)
    assert node_graph["graphId"] == "task-document-graph"
    assert [node["nodeId"] for node in node_graph["nodes"]] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]
    assert [edge["id"] for edge in node_graph["edges"]] == [
        "document-input-document-parse",
        "document-parse-content-organize",
        "document-parse-report-generate",
        "content-organize-typst-export",
        "report-generate-typst-export",
        "typst-export-file-export",
    ]
    assert node_graph["edges"] == [
        {"id": edge.id, "source": edge.source, "target": edge.target}
        for edge in task_graph.edges
    ]

    nodes_by_id = {node["nodeId"]: node for node in node_graph["nodes"]}
    task_nodes_by_id = {node.node_id: node for node in task_graph.nodes}

    assert nodes_by_id["document-input"]["status"] == "completed"
    assert [
        nodes_by_id[node_id]["status"]
        for node_id in [
            "document-parse",
            "content-organize",
            "report-generate",
            "typst-export",
            "file-export",
        ]
    ] == ["waiting", "waiting", "waiting", "waiting", "waiting"]

    assert nodes_by_id["document-input"]["nodeType"] == "fixed_tool"
    assert nodes_by_id["document-parse"]["nodeType"] == "fixed_tool"
    assert nodes_by_id["content-organize"]["nodeType"] == "model"
    assert nodes_by_id["report-generate"]["nodeType"] == "model"
    assert nodes_by_id["typst-export"]["nodeType"] == "fixed_tool"
    assert nodes_by_id["file-export"]["nodeType"] == "output"

    for node_id, node in nodes_by_id.items():
        task_node = task_nodes_by_id[node_id]
        assert task_node.ui is not None
        assert node["displayName"] == task_node.ui.display_name
        assert node["summary"] == task_node.ui.summary
        assert node["inputPorts"] == task_node.ui.input_ports
        assert node["outputPorts"] == task_node.ui.output_ports
        assert node["position"] == task_node.ui.position
        assert node["dependencies"] == task_node.dependencies
        assert node["createdBy"] == "agent"
        assert node["artifactRefs"] == []
        assert node["retryCount"] == 0

    assert nodes_by_id["document-input"]["toolRef"] == "document.receive_attachment"
    assert nodes_by_id["document-parse"]["toolRef"] == "document.markitdown_convert"
    assert nodes_by_id["typst-export"]["toolRef"] == "document.typst_compile"
    assert (
        nodes_by_id["content-organize"]["modelRef"] == "local-content-organizer"
    )
    assert nodes_by_id["report-generate"]["modelRef"] == "local-report-writer"
    assert "toolRef" not in nodes_by_id["file-export"]
    assert "modelRef" not in nodes_by_id["file-export"]
    assert set(node_graph) == {"graphId", "nodes", "edges"}


def test_compile_task_graph_requires_node_ui() -> None:
    task_graph = TaskGraph(
        graph_id="missing-ui-graph",
        task_id="missing-ui",
        objective="compile graph with missing UI",
        nodes=[
            TaskNode(
                node_id="node-without-ui",
                objective="missing UI should fail",
                kind="model",
                risk_level="read_only",
            )
        ],
    )

    with pytest.raises(ValueError, match="missing UI metadata.*node-without-ui"):
        compile_task_graph_to_node_graph(task_graph)


def test_compile_task_graph_requires_tool_binding_for_fixed_tool() -> None:
    task_graph = TaskGraph(
        graph_id="missing-tool-binding-graph",
        task_id="missing-tool-binding",
        objective="compile graph with a missing tool binding",
        nodes=[
            TaskNode(
                node_id="fixed-tool-without-binding",
                objective="missing tool binding should fail",
                kind="fixed_tool",
                risk_level="read_only",
                ui=TaskNodeUi(
                    display_name="Fixed Tool",
                    summary="Fixed tool missing binding.",
                ),
            )
        ],
    )

    with pytest.raises(
        ValueError,
        match="fixed-tool-without-binding.*tool_binding",
    ):
        compile_task_graph_to_node_graph(task_graph)


def test_compile_task_graph_requires_model_binding_for_model() -> None:
    task_graph = TaskGraph(
        graph_id="missing-model-binding-graph",
        task_id="missing-model-binding",
        objective="compile graph with a missing model binding",
        nodes=[
            TaskNode(
                node_id="model-without-binding",
                objective="missing model binding should fail",
                kind="model",
                risk_level="read_only",
                ui=TaskNodeUi(
                    display_name="Model",
                    summary="Model missing binding.",
                ),
            )
        ],
    )

    with pytest.raises(
        ValueError,
        match="model-without-binding.*model_binding",
    ):
        compile_task_graph_to_node_graph(task_graph)


def test_compile_task_graph_uses_model_ref_fallback_for_unknown_model() -> None:
    task_graph = TaskGraph(
        graph_id="unknown-model-graph",
        task_id="unknown-model",
        objective="compile graph with an unknown model ref",
        nodes=[
            TaskNode(
                node_id="unknown-model-node",
                objective="unknown model",
                kind="model",
                risk_level="read_only",
                model_binding={"model_ref": "custom.model", "purpose": "test"},
                ui=TaskNodeUi(display_name="Unknown", summary="Unknown model."),
            )
        ],
    )

    node_graph = compile_task_graph_to_node_graph(task_graph)

    assert node_graph["nodes"][0]["modelRef"] == "custom.model"
