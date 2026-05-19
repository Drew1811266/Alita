from __future__ import annotations

import pytest

from agent_service.goal_spec import GoalSpec
from agent_service.task_graph import (
    TaskGraph,
    TaskGraphValidationError,
    TaskNode,
    build_document_task_graph,
    validate_task_graph,
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


def _task_node(node_id: str, dependencies: list[str] | None = None) -> TaskNode:
    return TaskNode(
        node_id=node_id,
        objective=f"Run {node_id}",
        kind="model",
        inputs=[],
        outputs=[],
        dependencies=dependencies or [],
        success_criteria=[],
        risk_level="read_only",
        permissions_required=[],
    )


def test_build_document_task_graph_preserves_existing_node_ids() -> None:
    graph = build_document_task_graph("task-document", _document_goal_spec())

    assert graph.graph_id == "task-document-graph"
    assert graph.task_id == "task-document"
    assert graph.objective == "summarize this document as a PDF report"
    assert [node.node_id for node in graph.nodes] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]
    assert graph.edges[0].id == "document-input-document-parse"
    assert "content-organize-report-generate" not in [
        edge.id for edge in graph.edges
    ]
    assert graph.node_by_id("report-generate").dependencies == ["document-parse"]

    assert graph.node_by_id("document-input").tool_binding is not None
    assert (
        graph.node_by_id("document-input").tool_binding.tool_id
        == "document.receive_attachment"
    )
    assert graph.node_by_id("document-input").tool_binding.operation == (
        "receive_attachment"
    )
    assert graph.node_by_id("document-parse").tool_binding is not None
    assert (
        graph.node_by_id("document-parse").tool_binding.tool_id
        == "document.markitdown_convert"
    )
    assert graph.node_by_id("typst-export").tool_binding is not None
    assert graph.node_by_id("typst-export").tool_binding.operation == "compile_report_pdf"
    assert graph.node_by_id("content-organize").model_binding is not None
    assert (
        graph.node_by_id("content-organize").model_binding.model_ref
        == "local.content_organizer"
    )
    assert graph.node_by_id("report-generate").model_binding is not None
    assert (
        graph.node_by_id("report-generate").model_binding.model_ref
        == "local.report_writer"
    )
    assert graph.node_by_id("file-export").risk_level == "local_write"

    document_parse_ui = graph.node_by_id("document-parse").ui
    assert document_parse_ui is not None
    assert (
        document_parse_ui.summary
        == "把用户提供的本地文档转换为适合模型读取的 Markdown 正文。"
    )
    assert document_parse_ui.input_ports == [
        {"id": "document-input", "label": "文档", "dataType": "document"}
    ]
    assert document_parse_ui.output_ports == [
        {"id": "markdown-output", "label": "Markdown", "dataType": "text"}
    ]

    typst_export_ui = graph.node_by_id("typst-export").ui
    assert typst_export_ui is not None
    assert {"id": "pdf-output", "label": "PDF 文件", "dataType": "artifact"} in (
        typst_export_ui.output_ports
    )

    validate_task_graph(graph)


def test_validate_task_graph_rejects_missing_dependency() -> None:
    graph = TaskGraph(
        graph_id="graph-missing-dependency",
        task_id="task-missing-dependency",
        objective="test missing dependency",
        nodes=[_task_node("first", dependencies=["missing"])],
        edges=[],
    )

    with pytest.raises(TaskGraphValidationError, match="missing dependency"):
        validate_task_graph(graph)


def test_validate_task_graph_rejects_cycles() -> None:
    graph = TaskGraph(
        graph_id="graph-cycle",
        task_id="task-cycle",
        objective="test cycle",
        nodes=[
            _task_node("first", dependencies=["second"]),
            _task_node("second", dependencies=["first"]),
        ],
        edges=[],
    )

    with pytest.raises(TaskGraphValidationError, match="cycle"):
        validate_task_graph(graph)
