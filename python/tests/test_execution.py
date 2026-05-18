from __future__ import annotations

import tempfile
from pathlib import Path

from agent_service.intent import classify_route
from agent_service.execution import NodeOutput, run_graph_events
from agent_service.graph import run_agent
from agent_service.model_client import ChatMessage
from agent_service.run_journal import RunJournal
from agent_service.run_registry import RunRegistry
from agent_service.schemas import RunGraphRequest, UserMessage
from agent_service.tool_execution import ToolResult
from agent_service.web_research import build_research_graph
from agent_service.web_search import SearchFailure, SearchResponse, SearchResult


class FakeNodeExecutor:
    def __init__(self) -> None:
        self._artifact_dir = Path(tempfile.mkdtemp(prefix="alita-fake-artifacts-"))

    def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
        if node_id == "file-export":
            artifact = self._artifact_dir / "report.md"
            artifact.write_text("report", encoding="utf-8")
            return NodeOutput(values={"artifact": str(artifact)}, artifacts=[str(artifact)])

        values_by_node_id = {
            "document-input": {"paths": "input.md"},
            "document-parse": {"text": "parsed text"},
            "content-organize": {"outline": "outline"},
            "report-generate": {"report": "report"},
        }
        return NodeOutput(values=values_by_node_id.get(node_id, {"text": node_id}))


class FakeModelClient:
    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        self.calls.append(messages)
        if "结构化中文要点" in messages[0].content:
            return "整理结果：标题和正文内容"
        return "报告正文：这是一份测试报告"


class FakeToolExecutor:
    def __init__(self) -> None:
        self.calls = []

    def run(self, invocation):
        self.calls.append(invocation)
        output_path = Path(invocation.arguments["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("# Markdown\n\nparsed text", encoding="utf-8")
        return ToolResult(
            values={"text": "# Markdown\n\n正文"},
            artifacts=[str(output_path)],
            metadata={"converter": "fake"},
        )


class TypstFlowToolExecutor:
    def __init__(self) -> None:
        self.calls = []

    def run(self, invocation):
        self.calls.append(invocation)
        if invocation.tool_id == "document.markitdown_convert":
            output_path = Path(invocation.arguments["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("# Markdown\n\nparsed text", encoding="utf-8")
            return ToolResult(values={"text": "parsed text"}, artifacts=[str(output_path)])

        if invocation.tool_id == "document.typst_compile":
            source_path = Path(invocation.arguments["source_output_path"])
            pdf_path = Path(invocation.arguments["pdf_output_path"])
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text("typst source", encoding="utf-8")
            pdf_path.write_bytes(b"%PDF-1.7\n")
            return ToolResult(
                values={"source": str(source_path), "artifact": str(pdf_path)},
                artifacts=[str(source_path), str(pdf_path)],
                metadata={"compiler": "typst"},
            )

        raise AssertionError(f"unexpected tool invocation: {invocation.tool_id}")


class FailingNodeExecutor:
    def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
        raise RuntimeError(f"boom from {node_id}")


class SequencedSearchProvider:
    def __init__(self, responses_by_query: dict[str, list[SearchResponse]]) -> None:
        self.responses_by_query = {
            query: list(responses)
            for query, responses in responses_by_query.items()
        }
        self.queries: list[str] = []

    def search(self, query: str) -> SearchResponse:
        self.queries.append(query)
        responses = self.responses_by_query.get(query)
        if not responses:
            raise AssertionError(f"unexpected search call: {query}")
        return responses.pop(0)


def test_rejects_graph_with_missing_dependency(tmp_path: Path) -> None:
    request = RunGraphRequest(
        task_id="task-1",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph={
            "graphId": "graph-1",
            "nodes": [
                build_node(
                    "document-parse",
                    "fixed_tool",
                    ["missing-node"],
                    tool_ref="document.extract_text",
                )
            ],
            "edges": [],
        },
    )

    events = list(run_graph_events(request))

    assert events[0].type == "task.failed"
    assert events[0].payload["taskId"] == "task-1"
    assert "missing-node" in events[0].payload["error"]


def test_rejects_graph_with_unknown_tool_ref_before_running_nodes(tmp_path: Path) -> None:
    request = build_request(
        tmp_path,
        nodes=[
            build_node(
                "missing-tool",
                "fixed_tool",
                [],
                tool_ref="missing.tool",
            )
        ],
    )

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert "node.running" not in [event.type for event in events]
    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "unsupported_tool"
    assert "missing.tool" in events[-1].payload["error"]


def test_run_graph_events_executes_generic_planner_graph_from_run_agent(
    tmp_path: Path,
) -> None:
    graph_event = run_agent(
        UserMessage(
            task_id="task-generic-run",
            content="Can you create a Python script that counts rows in a CSV file?",
        )
    )[0]
    request = RunGraphRequest(
        task_id="task-generic-run",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph=graph_event.payload["graph"],
    )

    events = list(run_graph_events(request))

    event_types = [event.type for event in events]
    running_node_ids = [
        event.payload["nodeId"] for event in events if event.type == "node.running"
    ]
    assert running_node_ids[0] == "task-analysis"
    assert "node.failed" not in event_types
    assert "task.failed" not in event_types
    assert events[-1].type == "task.completed"
    recorded_task_analysis = [
        record
        for record in RunJournal(
            project_path=request.project_path,
            run_id=request.run_id,
        ).read_nodes()
        if record["nodeId"] == "task-analysis"
    ][0]
    assert recorded_task_analysis["values"]["mode"] == "planned_task"


def test_research_graph_executes_nodes_and_writes_markdown_report(tmp_path: Path) -> None:
    question = "Compare current Python packaging tools"
    request = build_research_flow_request(tmp_path, question)
    provider = SequencedSearchProvider(
        {
            question: [
                SearchResponse(
                    results=[
                        SearchResult(
                            title="Python packaging user guide",
                            url="https://packaging.python.org/en/latest/",
                            snippet="Official guide to Python packaging tools.",
                        ),
                        SearchResult(
                            title="Top10 packaging tools",
                            url="https://top10.example/python-packaging",
                            snippet="Copied list with ads.",
                        ),
                    ]
                )
            ],
            f"{question} official sources": [
                SearchResponse(
                    results=[
                        SearchResult(
                            title="Python docs",
                            url="https://docs.python.org/3/",
                            snippet="Python documentation and tooling references.",
                        )
                    ]
                )
            ],
        }
    )

    events = list(run_graph_events(request, search_provider=provider))

    running_node_ids = [
        event.payload["nodeId"] for event in events if event.type == "node.running"
    ]
    assert running_node_ids == [
        "research-intent-analysis",
        "research-privacy-guard",
        "research-query-plan",
        "research-parallel-search",
        "research-source-review",
        "research-report-synthesis",
        "research-markdown-output",
    ]
    artifact_event = next(event for event in events if event.type == "artifact.created")
    artifact_path = Path(artifact_event.payload["path"])
    assert artifact_path.is_file()
    assert artifact_path.parent == tmp_path / "artifacts" / "research"
    content = artifact_path.read_text(encoding="utf-8")
    headings = [
        content.index("## Summary"),
        content.index("## Key Findings"),
        content.index("## Source Review"),
        content.index("## Open Questions"),
        content.index("## References"),
    ]
    assert headings == sorted(headings)
    completed_event = next(event for event in events if event.type == "research.completed")
    assert completed_event.payload["taskId"] == "task-research"
    assert completed_event.payload["reportArtifactId"] == artifact_event.payload["artifactId"]
    assert completed_event.payload["reportArtifactId"] == artifact_path.stem
    assert completed_event.payload["reportArtifactPath"] == str(artifact_path)
    assert completed_event.payload["acceptedSources"]
    assert completed_event.payload["rejectedSources"]
    assert events[-1].type == "task.completed"


def test_research_search_retries_failed_query_without_repeating_success(
    tmp_path: Path,
) -> None:
    question = "Compare current LangGraph documentation"
    retry_failure = SearchResponse(
        results=[],
        failure=SearchFailure(kind="timeout", message="Search request timed out."),
    )
    provider = SequencedSearchProvider(
        {
            question: [
                SearchResponse(
                    results=[
                        SearchResult(
                            title="LangGraph docs",
                            url="https://langchain-ai.github.io/langgraph/",
                            snippet="Official LangGraph documentation.",
                        )
                    ]
                )
            ],
            f"{question} official sources": [
                retry_failure,
                retry_failure,
                SearchResponse(
                    results=[
                        SearchResult(
                            title="LangGraph repository",
                            url="https://github.com/langchain-ai/langgraph",
                            snippet="Primary project repository.",
                        )
                    ]
                ),
            ],
        }
    )
    request = build_research_flow_request(tmp_path, question)

    events = list(run_graph_events(request, search_provider=provider))

    assert provider.queries == [
        question,
        f"{question} official sources",
        f"{question} official sources",
        f"{question} official sources",
    ]
    assert events[-1].type == "task.completed"


def test_research_search_fails_after_retry_budget_is_exhausted(tmp_path: Path) -> None:
    question = "Compare current LangGraph documentation"
    retry_failure = SearchResponse(
        results=[],
        failure=SearchFailure(kind="timeout", message="Search request timed out."),
    )
    provider = SequencedSearchProvider(
        {
            question: [
                SearchResponse(
                    results=[
                        SearchResult(
                            title="LangGraph docs",
                            url="https://langchain-ai.github.io/langgraph/",
                            snippet="Official LangGraph documentation.",
                        )
                    ]
                )
            ],
            f"{question} official sources": [
                retry_failure,
                retry_failure,
                retry_failure,
            ],
        }
    )
    request = build_research_flow_request(tmp_path, question)

    events = list(run_graph_events(request, search_provider=provider))

    assert provider.queries == [
        question,
        f"{question} official sources",
        f"{question} official sources",
        f"{question} official sources",
    ]
    node_failed = next(event for event in events if event.type == "node.failed")
    assert node_failed.payload["nodeId"] == "research-parallel-search"
    assert node_failed.payload["errorCode"] == "web_search_failed"
    node_run_recorded = next(
        event
        for event in events
        if event.type == "node.run_recorded"
        and event.payload["record"]["nodeId"] == "research-parallel-search"
    )
    assert node_run_recorded.payload["record"]["errorCode"] == "web_search_failed"
    journal = RunJournal(project_path=request.project_path, run_id=request.run_id)
    assert journal.read_node("research-parallel-search")["errorCode"] == (
        "web_search_failed"
    )
    assert events[-1].type == "task.failed"


def test_failed_only_research_retry_reuses_successful_query_units(
    tmp_path: Path,
) -> None:
    question = "Compare current LangGraph documentation"
    retry_failure = SearchResponse(
        results=[],
        failure=SearchFailure(kind="timeout", message="Search request timed out."),
    )
    provider = SequencedSearchProvider(
        {
            question: [
                SearchResponse(
                    results=[
                        SearchResult(
                            title="LangGraph docs",
                            url="https://langchain-ai.github.io/langgraph/",
                            snippet="Official LangGraph documentation.",
                        )
                    ]
                )
            ],
            f"{question} official sources": [
                retry_failure,
                retry_failure,
                retry_failure,
                SearchResponse(
                    results=[
                        SearchResult(
                            title="LangGraph repository",
                            url="https://github.com/langchain-ai/langgraph",
                            snippet="Primary project repository.",
                        )
                    ]
                ),
            ],
        }
    )
    first_request = build_research_flow_request(
        tmp_path,
        question,
        run_id="run-research-first",
    )

    first_events = list(run_graph_events(first_request, search_provider=provider))

    assert first_events[-1].type == "task.failed"
    retry_request = build_research_flow_request(
        tmp_path,
        question,
        run_id="run-research-retry",
    )
    retry_request.mode.type = "failed_only"
    retry_request.mode.source_run_id = "run-research-first"

    retry_events = list(run_graph_events(retry_request, search_provider=provider))

    assert provider.queries == [
        question,
        f"{question} official sources",
        f"{question} official sources",
        f"{question} official sources",
        f"{question} official sources",
    ]
    running = [
        event.payload["nodeId"] for event in retry_events if event.type == "node.running"
    ]
    assert running == [
        "research-parallel-search",
        "research-source-review",
        "research-report-synthesis",
        "research-markdown-output",
    ]
    assert retry_events[-1].type == "task.completed"


def test_emits_runtime_notice_when_node_exceeds_estimate(tmp_path: Path) -> None:
    request = build_request(
        tmp_path,
        nodes=[
            build_node(
                "document-input",
                "fixed_tool",
                [],
                tool_ref="document.receive_attachment",
                estimate={"durationMs": 0},
            )
        ],
    )

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    notice = next(event for event in events if event.type == "node.runtime_notice")
    assert set(notice.payload.keys()) == {"nodeId", "notice"}
    assert notice.payload["nodeId"] == "document-input"
    assert set(notice.payload["notice"].keys()) == {
        "kind",
        "message",
        "actualDurationMs",
    }
    assert notice.payload["notice"]["kind"] == "duration_exceeded"
    assert notice.payload["notice"]["actualDurationMs"] >= 0



def test_graph_tool_validation_uses_configured_tool_packages_root(
    tmp_path: Path, monkeypatch
) -> None:
    packages_root = tmp_path / "tool-packages"
    custom_tool_root = packages_root / "custom"
    custom_tool_root.mkdir(parents=True)
    (custom_tool_root / "manifest.json").write_text(
        """
{
  "tool_id": "document.custom_test",
  "name": "Custom Test",
  "description": "A test-only tool manifest.",
  "version": "1.0.0",
  "source_type": "test",
  "license": "internal",
  "operations": [
    {
      "name": "run",
      "description": "Run the test tool."
    }
  ],
  "input_schema": {
    "type": "object"
  },
  "output_schema": {
    "type": "object"
  }
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALITA_TOOL_PACKAGES_ROOT", str(packages_root))
    request = build_request(
        tmp_path,
        nodes=[
            build_node(
                "custom-tool",
                "fixed_tool",
                [],
                tool_ref="document.custom_test",
            )
        ],
    )

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert [event.type for event in events] == [
        "run.started",
        "node.running",
        "node.completed",
        "node.run_recorded",
        "task.completed",
    ]


def test_runs_nodes_after_all_dependencies_complete(tmp_path: Path) -> None:
    request = build_request(
        tmp_path,
        nodes=[
            build_node(
                "document-input",
                "fixed_tool",
                [],
                tool_ref="document.receive_attachment",
            ),
            build_node(
                "document-parse",
                "fixed_tool",
                ["document-input"],
                tool_ref="document.markitdown_convert",
            ),
            build_node(
                "content-organize",
                "model",
                ["document-parse"],
                model_ref="local-content-organizer",
            ),
            build_node(
                "report-generate",
                "model",
                ["document-parse"],
                model_ref="local-report-writer",
            ),
            build_node("file-export", "output", ["content-organize", "report-generate"]),
        ],
    )

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    running_node_ids = [
        event.payload["nodeId"] for event in events if event.type == "node.running"
    ]
    assert running_node_ids == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "file-export",
    ]
    assert events[-1].type == "task.completed"


def test_rejects_disabled_tool_nodes(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)
    request.disabled_tool_ids = ["document.receive_attachment"]

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert "node.running" not in [event.type for event in events]
    assert events[-1].type == "task.failed"
    assert "document.receive_attachment" in events[-1].payload["error"]


def test_failed_events_include_standard_error_code(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)
    request.disabled_tool_ids = ["document.receive_attachment"]

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "tool_disabled"
    assert "document.receive_attachment" in events[-1].payload["error"]


def test_disabled_tool_node_failed_event_includes_run_context(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source, run_id="run-disabled-tool")
    request.disabled_tool_ids = ["document.receive_attachment"]

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    node_failed = next(event for event in events if event.type == "node.failed")
    assert node_failed.payload["nodeId"] == "document-input"
    assert node_failed.payload["taskId"] == "task-document-flow"
    assert node_failed.payload["runId"] == "run-disabled-tool"
    assert node_failed.payload["errorCode"] == "tool_disabled"
    assert "document.receive_attachment" in node_failed.payload["error"]


def test_exception_node_failed_event_includes_run_context(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source, run_id="run-exception")

    events = list(run_graph_events(request, executor=FailingNodeExecutor()))

    node_failed = next(event for event in events if event.type == "node.failed")
    assert node_failed.payload["nodeId"] == "document-input"
    assert node_failed.payload["taskId"] == "task-document-flow"
    assert node_failed.payload["runId"] == "run-exception"
    assert node_failed.payload["errorCode"] == "execution_failed"
    assert "boom from document-input" in node_failed.payload["error"]


def test_execution_fails_when_result_verifier_rejects_empty_output(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.md"
    source.write_text("正文", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)

    class EmptyContentExecutor(FakeNodeExecutor):
        def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
            if node_id == "content-organize":
                return NodeOutput(values={"outline": ""})
            return super().run(node_id, inputs)

    events = list(run_graph_events(request, executor=EmptyContentExecutor()))

    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "empty_node_output"


def test_document_flow_exports_markdown_artifact(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("# 标题\n\n正文内容", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)

    events = list(
        run_graph_events(
            request,
            model_client=FakeModelClient(),
            tool_executor=FakeToolExecutor(),
        )
    )

    artifact_events = [
        event
        for event in events
        if event.type == "artifact.created"
        and event.payload["sourceNodeId"] == "file-export"
    ]
    assert len(artifact_events) == 1
    exported_path = Path(artifact_events[0].payload["path"])
    assert exported_path.exists()
    assert exported_path.suffix == ".md"
    exported_content = exported_path.read_text(encoding="utf-8")
    assert "整理结果：标题和正文内容" in exported_content
    assert "报告正文：这是一份测试报告" in exported_content
    assert events[-1].type == "task.completed"


def test_document_parse_uses_markitdown_tool_executor(tmp_path: Path) -> None:
    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    request = build_document_flow_request(tmp_path, source)
    tool_executor = FakeToolExecutor()

    events = list(
        run_graph_events(
            request,
            model_client=FakeModelClient(),
            tool_executor=tool_executor,
        )
    )

    assert tool_executor.calls
    invocation = tool_executor.calls[0]
    assert invocation.tool_id == "document.markitdown_convert"
    assert invocation.operation == "convert_local_file"
    assert invocation.arguments["input_path"] == str(source)
    assert invocation.arguments["output_path"] == str(
        tmp_path / "artifacts" / "converted" / "01-input.md"
    )
    assert events[-1].type == "task.completed"


def test_document_flow_runs_typst_export_and_file_export_passes_pdf_artifact(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.md"
    source.write_text("# Title\n\nBody", encoding="utf-8")
    request = build_document_flow_request_with_typst(tmp_path, source)
    tool_executor = TypstFlowToolExecutor()

    events = list(
        run_graph_events(
            request,
            model_client=FakeModelClient(),
            tool_executor=tool_executor,
        )
    )

    assert [call.tool_id for call in tool_executor.calls] == [
        "document.markitdown_convert",
        "document.typst_compile",
    ]
    typst_call = tool_executor.calls[1]
    assert typst_call.operation == "compile_report_pdf"
    assert typst_call.arguments["source_output_path"].endswith(".typ")
    assert typst_call.arguments["pdf_output_path"].endswith(".pdf")

    export_events = [
        event
        for event in events
        if event.type == "artifact.created"
        and event.payload["sourceNodeId"] == "file-export"
    ]
    assert any(Path(event.payload["path"]).suffix == ".pdf" for event in export_events)
    assert events[-1].type == "task.completed"


def test_document_parse_uses_unique_output_paths_for_duplicate_attachment_names(
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "a" / "report.pdf"
    source_b = tmp_path / "b" / "report.docx"
    source_a.parent.mkdir()
    source_b.parent.mkdir()
    source_a.write_bytes(b"%PDF-1.4\n")
    source_b.write_bytes(b"docx")
    request = build_document_flow_request(tmp_path, [source_a, source_b])
    tool_executor = FakeToolExecutor()

    list(
        run_graph_events(
            request,
            model_client=FakeModelClient(),
            tool_executor=tool_executor,
        )
    )

    assert len(tool_executor.calls) == 2
    output_paths = [
        Path(invocation.arguments["output_path"])
        for invocation in tool_executor.calls
    ]
    assert output_paths[0] != output_paths[1]
    for output_path in output_paths:
        assert output_path.parent == tmp_path / "artifacts" / "converted"
        assert output_path.suffix == ".md"


def test_run_emits_started_and_cancelled_between_nodes(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("正文", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source, run_id="run-cancel")
    registry = RunRegistry()

    class CancellingExecutor(FakeNodeExecutor):
        def __init__(self) -> None:
            self.calls = 0

        def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
            self.calls += 1
            if self.calls == 1:
                registry.cancel("run-cancel")
            return super().run(node_id, inputs)

    events = list(
        run_graph_events(
            request,
            executor=CancellingExecutor(),
            registry=registry,
        )
    )

    assert events[0].type == "run.started"
    assert events[0].payload["runId"] == "run-cancel"
    assert "run.cancelled" in [event.type for event in events]
    assert "task.completed" not in [event.type for event in events]


def test_failed_only_reruns_failed_node_and_downstream(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("正文", encoding="utf-8")
    source_run = "run-original"
    journal = RunJournal(project_path=str(tmp_path / "project.alita"), run_id=source_run)
    journal.write_node(
        "document-input",
        {"nodeId": "document-input", "status": "completed", "values": {"paths": str(source)}},
    )
    journal.write_node(
        "document-parse",
        {"nodeId": "document-parse", "status": "completed", "values": {"text": "正文"}},
    )
    journal.write_node(
        "content-organize",
        {"nodeId": "content-organize", "status": "failed", "error": "model failed"},
    )
    request = build_document_flow_request(tmp_path, source, run_id="run-retry")
    request.mode.type = "failed_only"
    request.mode.source_run_id = source_run

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    running = [event.payload["nodeId"] for event in events if event.type == "node.running"]
    assert running == ["content-organize", "file-export"]


def test_from_node_reruns_target_and_downstream(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("正文", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source, run_id="run-from-node")
    request.mode.type = "from_node"
    request.mode.node_id = "report-generate"

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    running = [event.payload["nodeId"] for event in events if event.type == "node.running"]
    assert running == ["report-generate", "file-export"]


def build_request(tmp_path: Path, *, nodes: list[dict]) -> RunGraphRequest:
    return RunGraphRequest(
        task_id="task-run",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph={
            "graphId": "graph-run",
            "nodes": nodes,
            "edges": [
                {
                    "id": f"{dependency}-{node['nodeId']}",
                    "source": dependency,
                    "target": node["nodeId"],
                }
                for node in nodes
                for dependency in node["dependencies"]
            ],
        },
    )


def build_document_flow_request(
    tmp_path: Path,
    source: Path | list[Path],
    *,
    run_id: str = "run-document-flow",
) -> RunGraphRequest:
    sources = source if isinstance(source, list) else [source]
    return RunGraphRequest(
        task_id="task-document-flow",
        project_path=str(tmp_path / "project.alita"),
        run_id=run_id,
        attachments=[
            {
                "attachment_id": f"a{index + 1}",
                "name": source_path.name,
                "path": str(source_path),
                "size_bytes": source_path.stat().st_size,
                "mime_type": "text/markdown",
            }
            for index, source_path in enumerate(sources)
        ],
        graph={
            "graphId": "graph-document-flow",
            "nodes": [
                build_node(
                    "document-input",
                    "fixed_tool",
                    [],
                    tool_ref="document.receive_attachment",
                ),
                build_node(
                    "document-parse",
                    "fixed_tool",
                    ["document-input"],
                    tool_ref="document.markitdown_convert",
                ),
                build_node(
                    "content-organize",
                    "model",
                    ["document-parse"],
                    model_ref="local-content-organizer",
                ),
                build_node(
                    "report-generate",
                    "model",
                    ["document-parse"],
                    model_ref="local-report-writer",
                ),
                build_node(
                    "file-export",
                    "output",
                    ["content-organize", "report-generate"],
                ),
            ],
            "edges": [],
        },
    )


def build_document_flow_request_with_typst(
    tmp_path: Path,
    source: Path,
    *,
    run_id: str = "run-document-flow",
) -> RunGraphRequest:
    nodes = [
        build_node(
            "document-input",
            "fixed_tool",
            [],
            tool_ref="document.receive_attachment",
        ),
        build_node(
            "document-parse",
            "fixed_tool",
            ["document-input"],
            tool_ref="document.markitdown_convert",
        ),
        build_node(
            "content-organize",
            "model",
            ["document-parse"],
            model_ref="local-content-organizer",
        ),
        build_node(
            "report-generate",
            "model",
            ["document-parse"],
            model_ref="local-report-writer",
        ),
        build_node(
            "typst-export",
            "fixed_tool",
            ["content-organize", "report-generate"],
            tool_ref="document.typst_compile",
        ),
        build_node("file-export", "output", ["typst-export"]),
    ]
    return RunGraphRequest(
        task_id="task-document-flow",
        project_path=str(tmp_path / "project.alita"),
        run_id=run_id,
        attachments=[
            {
                "attachment_id": "a1",
                "name": source.name,
                "path": str(source),
                "size_bytes": source.stat().st_size,
                "mime_type": "text/markdown",
            }
        ],
        graph={
            "graphId": "graph-document-flow",
            "nodes": nodes,
            "edges": [
                {
                    "id": f"{dependency}-{node['nodeId']}",
                    "source": dependency,
                    "target": node["nodeId"],
                }
                for node in nodes
                for dependency in node["dependencies"]
            ],
        },
    )


def build_research_flow_request(
    tmp_path: Path,
    question: str,
    *,
    run_id: str = "run-research-flow",
) -> RunGraphRequest:
    message = UserMessage(task_id="task-research", content=question)
    return RunGraphRequest(
        task_id="task-research",
        project_path=str(tmp_path / "project.alita"),
        run_id=run_id,
        graph=build_research_graph(message, classify_route(message)),
    )


def build_node(
    node_id: str,
    node_type: str,
    dependencies: list[str],
    *,
    tool_ref: str | None = None,
    model_ref: str | None = None,
    estimate: dict | None = None,
) -> dict:
    node = {
        "nodeId": node_id,
        "nodeType": node_type,
        "displayName": node_id,
        "status": "waiting",
        "inputPorts": [],
        "outputPorts": [],
        "dependencies": dependencies,
        "summary": "测试节点",
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "position": {"x": 0, "y": 0},
    }
    if tool_ref:
        node["toolRef"] = tool_ref
    if model_ref:
        node["modelRef"] = model_ref
    if estimate is not None:
        node["estimate"] = estimate
    return node
