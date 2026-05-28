from __future__ import annotations

from pathlib import Path

from agent_service.agent_run_state import AgentRunState
from agent_service.execution import DocumentFlowExecutor, NodeOutput, run_graph_events
from agent_service.schemas import RunGraphRequest
from tests.helpers.tool_gateway import RecordingGateway
from tests.test_execution import (
    FakeModelClient,
    build_document_flow_request,
    build_document_flow_request_with_typst,
    build_node,
)


def test_document_flow_parse_calls_unified_tool_gateway(tmp_path: Path) -> None:
    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    request = build_document_flow_request(tmp_path, source)
    run_state = AgentRunState.from_run_graph_request(request)
    gateway = RecordingGateway()
    executor = DocumentFlowExecutor(
        request,
        run_state=run_state,
        model_client=FakeModelClient(),
        tool_gateway=gateway,
    )

    output = executor.run("document-parse", {})

    assert output.values == {"text": "parsed text"}
    assert output.artifacts == [
        str(tmp_path / "artifacts" / "converted" / "01-input.md")
    ]
    assert len(gateway.calls) == 1
    invocation = gateway.calls[0]
    assert invocation.run_id == request.run_id
    assert invocation.task_id == request.task_id
    assert invocation.node_id == "document-parse"
    assert invocation.tool_id == "internal:document.markitdown_convert"
    assert invocation.arguments == {
        "operation": "convert_local_file",
        "input_path": str(source),
        "output_path": str(tmp_path / "artifacts" / "converted" / "01-input.md"),
    }
    assert invocation.project_path == request.project_path
    assert str(tmp_path) in invocation.allowed_roots
    assert "read_project_files" in invocation.requested_permissions
    assert invocation.model_session_id is None


def test_document_flow_typst_export_calls_unified_tool_gateway(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("# Title\n\nBody", encoding="utf-8")
    request = build_document_flow_request_with_typst(tmp_path, source)
    gateway = RecordingGateway()
    executor = DocumentFlowExecutor(
        request,
        run_state=AgentRunState.from_run_graph_request(request),
        model_client=FakeModelClient(),
        tool_gateway=gateway,
    )

    output = executor.run(
        "typst-export",
        {
            "content-organize": NodeOutput(values={"outline": "outline"}),
            "report-generate": NodeOutput(values={"report": "report"}),
        },
    )

    assert len(gateway.calls) == 1
    invocation = gateway.calls[0]
    assert invocation.node_id == "typst-export"
    assert invocation.tool_id == "internal:document.typst_compile"
    assert invocation.arguments["operation"] == "compile_report_pdf"
    assert invocation.arguments["title"] == "project"
    assert invocation.arguments["outline"] == "outline"
    assert invocation.arguments["report"] == "report"
    assert invocation.arguments["source_output_path"].endswith(".typ")
    assert invocation.arguments["pdf_output_path"].endswith(".pdf")
    assert output.values["artifact"].endswith(".pdf")
    assert any(Path(path).suffix == ".pdf" for path in output.artifacts)


def test_planned_fixed_tool_node_executes_through_unified_gateway(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.docx"
    source.write_bytes(b"fake docx")
    request = RunGraphRequest(
        task_id="task-planned-tool",
        run_id="run-planned-tool",
        project_path=str(tmp_path / "project.alita"),
        attachments=[
            {
                "attachment_id": "a1",
                "name": source.name,
                "path": str(source),
                "size_bytes": source.stat().st_size,
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }
        ],
        graph={
            "graphId": "planned-tool-graph",
            "metadata": {"taskKind": "document_processing"},
            "nodes": [
                build_node(
                    "execution-order-planning",
                    "planning",
                    [],
                ),
                build_node(
                    "tool-document-markitdown-convert",
                    "fixed_tool",
                    ["execution-order-planning"],
                    tool_ref="internal:document.markitdown_convert",
                    permissions=["read_project_files", "write_project_outputs"],
                ),
                build_node(
                    "task-output",
                    "output",
                    ["tool-document-markitdown-convert"],
                ),
            ],
            "edges": [],
        },
    )
    gateway = RecordingGateway()

    events = list(
        run_graph_events(
            request,
            run_state=AgentRunState.from_run_graph_request(request),
            tool_gateway=gateway,
        )
    )

    assert events[-1].type == "task.completed"
    assert len(gateway.calls) == 1
    invocation = gateway.calls[0]
    assert invocation.node_id == "tool-document-markitdown-convert"
    assert invocation.tool_id == "internal:document.markitdown_convert"
    assert invocation.arguments["operation"] == "convert_local_file"
    assert invocation.arguments["input_path"] == str(source)
    assert invocation.arguments["output_path"] == str(
        tmp_path / "artifacts" / "converted" / "01-input.md"
    )


def test_planned_fixed_tool_gateway_error_becomes_node_failure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.docx"
    source.write_bytes(b"fake docx")
    request = RunGraphRequest(
        task_id="task-planned-tool-error",
        run_id="run-planned-tool-error",
        project_path=str(tmp_path / "project.alita"),
        attachments=[
            {
                "attachment_id": "a1",
                "name": source.name,
                "path": str(source),
                "size_bytes": source.stat().st_size,
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }
        ],
        graph={
            "graphId": "planned-tool-error-graph",
            "metadata": {"taskKind": "document_processing"},
            "nodes": [
                build_node(
                    "tool-document-markitdown-convert",
                    "fixed_tool",
                    [],
                    tool_ref="document.markitdown_convert",
                    permissions=["read_project_files", "write_project_outputs"],
                ),
                build_node(
                    "task-output",
                    "output",
                    ["tool-document-markitdown-convert"],
                ),
            ],
            "edges": [],
        },
    )

    events = list(
        run_graph_events(
            request,
            run_state=AgentRunState.from_run_graph_request(request),
            tool_gateway=RecordingGateway(fail_code="conversion_failed"),
        )
    )

    assert "node.failed" in [event.type for event in events]
    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "conversion_failed"
    assert "gateway failed: conversion_failed" in events[-1].payload["error"]
