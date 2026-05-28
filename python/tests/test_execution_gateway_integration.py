from __future__ import annotations

from pathlib import Path

from agent_service.agent_run_state import AgentRunState
from agent_service.execution import DocumentFlowExecutor, NodeOutput
from tests.helpers.tool_gateway import RecordingGateway
from tests.test_execution import (
    FakeModelClient,
    build_document_flow_request,
    build_document_flow_request_with_typst,
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
