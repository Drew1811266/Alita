from __future__ import annotations

import tempfile
from pathlib import Path
from time import sleep

import pytest

from agent_service.agent_run_state import AgentRunState
from agent_service.intent import classify_route
from agent_service.execution import (
    DocumentFlowExecutor,
    NodeOutput,
    PlannedTaskExecutor,
    ResearchFlowExecutor,
    _runtime_notice_for_node,
    run_graph_events,
)
from agent_service.execution_graph import compile_execution_graph
from agent_service.graph import run_agent
from agent_service.harness_errors import HarnessError
from agent_service.model_client import ChatMessage, ChatWithToolsResponse
from agent_service.model_tool_adapter import ModelToolCall, model_safe_tool_name
from agent_service.model_policy import ModelCallPolicy, ModelCallProfile
from agent_service.memory_store import MemoryStore
from agent_service.research_evidence import evidence_from_search_results
from agent_service.run_journal import RunJournal
from agent_service.run_registry import RunRegistry
from agent_service.schemas import (
    Attachment,
    RunGraph,
    RunGraphRequest,
    ScriptReviewState,
    UserMessage,
)
from agent_service.script_review import script_review_fingerprint as canonical_script_review_fingerprint
from agent_service.tool_execution import ToolResult
from agent_service.tool_protocol import (
    ToolResultContent,
    ToolSafetyPolicy,
    UnifiedToolDefinition,
    UnifiedToolResult,
)
from agent_service.tool_registry import ToolManifestSpec, ToolOperationSpec, ToolRegistry
from agent_service.web_research import build_research_graph
from agent_service.web_search import SearchFailure, SearchResponse, SearchResult
from tests.helpers.tool_gateway import RecordingGateway


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
        self.policies: list[ModelCallPolicy | None] = []
        self.temperatures: list[float | None] = []
        self.max_tokens: list[int | None] = []

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> str:
        self.calls.append(messages)
        self.policies.append(policy)
        self.temperatures.append(temperature)
        self.max_tokens.append(max_tokens)
        if (
            "outline" in messages[0].content.lower()
            or "要点" in messages[0].content
            or "文档内容整理助手" in messages[0].content
        ):
            return "outline result"
        return "report result"


class FakeToolExecutor:
    def __init__(self) -> None:
        self.calls = []

    def run(self, invocation):
        self.calls.append(invocation)
        if invocation.tool_id == "document.receive_attachment":
            return ToolResult(
                values={"paths": str(invocation.arguments.get("paths", ""))}
            )
        output_path = Path(invocation.arguments["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("# Markdown\n\nparsed text", encoding="utf-8")
        return ToolResult(
            values={"text": "# Markdown\n\n姝ｆ枃"},
            artifacts=[str(output_path)],
            metadata={"converter": "fake"},
        )


class TypstFlowToolExecutor:
    def __init__(self) -> None:
        self.calls = []

    def run(self, invocation):
        self.calls.append(invocation)
        if invocation.tool_id == "document.receive_attachment":
            return ToolResult(
                values={"paths": str(invocation.arguments.get("paths", ""))}
            )

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


class FakeSourceFetcher:
    def __init__(self, content_by_url: dict[str, str]) -> None:
        self.content_by_url = dict(content_by_url)
        self.urls: list[str] = []

    def fetch(self, url: str) -> str:
        self.urls.append(url)
        if url not in self.content_by_url:
            raise AssertionError(f"unexpected source fetch: {url}")
        return self.content_by_url[url]


class RecordingModelRuntime:
    def __init__(self) -> None:
        self.calls = []

    def run(self, binding, *, inputs):
        self.calls.append((binding, inputs))
        if binding.model_ref == "local.content_organizer":
            return NodeOutput(values={"outline": "runtime outline"})
        if binding.model_ref == "local.report_writer":
            return NodeOutput(values={"report": "runtime report"})
        raise AssertionError(binding.model_ref)


class RejectingFinalVerifier:
    def verify(self, request: RunGraphRequest, *, outputs: dict[str, NodeOutput]) -> None:
        raise HarnessError(
            "missing_final_output",
            "missing final output for node: file-export",
        )


def test_document_flow_model_nodes_use_model_runtime(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("document text", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)
    runtime = RecordingModelRuntime()
    executor = DocumentFlowExecutor(request, model_runtime=runtime)

    parse_output = NodeOutput(values={"text": "document text"})

    outline_output = executor.run("content-organize", {"document-parse": parse_output})
    report_output = executor.run("report-generate", {"document-parse": parse_output})

    assert outline_output.values == {"outline": "runtime outline"}
    assert report_output.values == {"report": "runtime report"}
    assert [call[0].model_ref for call in runtime.calls] == [
        "local.content_organizer",
        "local.report_writer",
    ]


def test_document_flow_executor_uses_injected_model_client_for_model_nodes() -> None:
    from agent_service.execution import DocumentFlowExecutor
    from agent_service.node_output import NodeOutput
    from agent_service.schemas import RunGraphRequest, RunGraph

    class FakeModelClient:
        def chat(self, messages, *, temperature=0.2, max_tokens=1024, policy=None):
            return "model output"

    request = RunGraphRequest(
        task_id="task-1",
        project_path="D:\\Project\\demo.alita",
        graph=RunGraph(graphId="graph-1", nodes=[], edges=[]),
    )
    executor = DocumentFlowExecutor(request, model_client=FakeModelClient())

    output = executor.run(
        "content-organize",
        {"document-parse": NodeOutput(values={"text": "source text"})},
    )

    assert output.values["outline"] == "model output"


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
    suggestion_event = next(
        event for event in events if event.type == "graph.patch_suggested"
    )
    assert suggestion_event.payload["operations"][0]["op"] == "request_tool_enablement"
    assert suggestion_event.payload["operations"][0]["node_id"] == "missing-tool"
    assert suggestion_event.payload["requires_user_approval"] is True
    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "unsupported_tool"
    assert "missing.tool" in events[-1].payload["error"]


def test_run_graph_events_accepts_matching_agent_run_state(tmp_path: Path) -> None:
    request = _single_output_run_request(tmp_path)
    run_state = AgentRunState.from_run_graph_request(request)

    events = list(
        run_graph_events(
            request,
            run_state=run_state,
            executor=FakeNodeExecutor(),
        )
    )

    assert events[0].type == "run.started"
    assert events[-1].type == "task.completed"


def test_run_graph_events_rejects_mismatched_agent_run_state(tmp_path: Path) -> None:
    request = _single_output_run_request(tmp_path)
    run_state = AgentRunState.from_run_graph_request(request).model_copy(
        update={"task_id": "different-task"}
    )

    events = list(run_graph_events(request, run_state=run_state))

    assert events[0].type == "task.failed"
    assert events[0].payload["taskId"] == request.task_id
    assert events[0].payload["runId"] == request.run_id
    assert events[0].payload["error"]["code"] == "run_state_mismatch"


def test_run_graph_events_rejects_run_id_mismatched_agent_run_state(
    tmp_path: Path,
) -> None:
    request = _single_output_run_request(tmp_path)
    run_state = AgentRunState.from_run_graph_request(request).model_copy(
        update={"run_id": "different-run"}
    )

    events = list(run_graph_events(request, run_state=run_state))

    assert events[0].type == "task.failed"
    assert events[0].payload["taskId"] == request.task_id
    assert events[0].payload["runId"] == request.run_id
    assert events[0].payload["error"]["code"] == "run_state_mismatch"
    assert "run_id" in events[0].payload["error"]["message"]


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
    planning_node_ids = [
        node["nodeId"]
        for node in graph_event.payload["graph"]["nodes"]
        if node["nodeType"] == "planning"
    ]
    assert planning_node_ids
    assert all(
        node["status"] == "completed"
        for node in graph_event.payload["graph"]["nodes"]
        if node["nodeType"] == "planning"
    )
    assert running_node_ids == ["temporary-script-file-inspect", "task-output"]
    assert not set(planning_node_ids) & set(running_node_ids)
    assert "node.failed" not in event_types
    assert "task.failed" not in event_types
    assert events[-1].type == "task.completed"
    recorded_node_ids = {
        record["nodeId"]
        for record in RunJournal(
            project_path=request.project_path,
            run_id=request.run_id,
        ).read_nodes()
    }
    assert not set(planning_node_ids) & recorded_node_ids
    assert {"temporary-script-file-inspect", "task-output"} <= recorded_node_ids


def test_planner_graph_skips_completed_planning_nodes_and_runs_executable_nodes(
    tmp_path: Path,
) -> None:
    request = build_planner_request(
        tmp_path,
        script_review=script_review(risk_level="low", requires_approval=False),
    )

    events = list(run_graph_events(request))

    running_node_ids = [
        event.payload["nodeId"] for event in events if event.type == "node.running"
    ]
    assert running_node_ids == ["temp-script", "task-output"]
    assert events[-1].type == "task.completed"


def test_high_risk_temporary_script_blocks_before_any_node_runs(
    tmp_path: Path,
) -> None:
    request = build_planner_request(
        tmp_path,
        script_review=script_review(risk_level="high", requires_approval=True),
    )

    events = list(run_graph_events(request))

    assert "node.running" not in [event.type for event in events]
    permission_event = next(
        event for event in events if event.type == "node.needs_permission"
    )
    assert permission_event.payload["nodeId"] == "temp-script"
    assert permission_event.payload["permissions"] == [
        "read_project_files",
        "write_project_files",
    ]
    assert permission_event.payload["scriptReview"]["status"] == "not_reviewed"
    assert permission_event.payload["scriptReview"]["riskLevel"] == "high"
    temp_script = next(
        node for node in request.graph.nodes if node.nodeId == "temp-script"
    )
    assert permission_event.payload["scriptReview"]["approvalFingerprint"] == (
        script_review_fingerprint(temp_script.scriptReview.model_dump())
    )
    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "permission_required"


def test_low_risk_temporary_script_runs_through_planned_executor(
    tmp_path: Path,
) -> None:
    request = build_planner_request(
        tmp_path,
        script_review=script_review(risk_level="low", requires_approval=False),
    )

    events = list(run_graph_events(request))

    assert [
        event.payload["nodeId"] for event in events if event.type == "node.running"
    ] == ["temp-script", "task-output"]
    script_record = RunJournal(
        project_path=request.project_path,
        run_id=request.run_id,
    ).read_node("temp-script")
    assert script_record["status"] == "completed"
    assert script_record["values"]["scriptStatus"] == "executed"
    assert script_record["values"]["answer"] == 42
    assert script_record["values"]["riskLevel"] == "low"


def test_approved_high_risk_temporary_script_with_matching_fingerprint_runs(
    tmp_path: Path,
) -> None:
    review = script_review(risk_level="high", requires_approval=True)
    review["status"] = "approved"
    review["approvalFingerprint"] = script_review_fingerprint(review)
    request = build_planner_request(tmp_path, script_review=review)

    events = list(run_graph_events(request))

    assert "node.needs_permission" not in [event.type for event in events]
    assert [
        event.payload["nodeId"] for event in events if event.type == "node.running"
    ] == ["temp-script", "task-output"]
    assert events[-1].type == "task.completed"


def test_changed_approved_script_fingerprint_returns_to_not_reviewed_and_blocks(
    tmp_path: Path,
) -> None:
    review = script_review(risk_level="high", requires_approval=True)
    review["status"] = "approved"
    review["approvalFingerprint"] = script_review_fingerprint(review)
    review["codePreview"] = "print('changed high risk script')\n"
    request = build_planner_request(tmp_path, script_review=review)

    events = list(run_graph_events(request))

    assert "node.running" not in [event.type for event in events]
    permission_event = next(
        event for event in events if event.type == "node.needs_permission"
    )
    assert permission_event.payload["nodeId"] == "temp-script"
    assert permission_event.payload["scriptReview"]["status"] == "not_reviewed"
    assert permission_event.payload["scriptReview"]["approvalFingerprint"] is None
    assert events[-1].type == "task.failed"


def test_stale_high_risk_script_blocks_even_when_requires_approval_is_false(
    tmp_path: Path,
) -> None:
    review = script_review(risk_level="high", requires_approval=False)
    review["status"] = "approved"
    review["approvalFingerprint"] = script_review_fingerprint(review)
    review["codePreview"] = "print('changed high risk script')\n"
    request = build_planner_request(tmp_path, script_review=review)

    events = list(run_graph_events(request))

    assert "node.running" not in [event.type for event in events]
    permission_event = next(
        event for event in events if event.type == "node.needs_permission"
    )
    assert permission_event.payload["nodeId"] == "temp-script"
    assert permission_event.payload["permissions"] == [
        "read_project_files",
        "write_project_files",
    ]
    assert permission_event.payload["scriptReview"]["status"] == "not_reviewed"
    assert permission_event.payload["scriptReview"]["approvalFingerprint"] is None
    assert events[-1].type == "task.failed"


def test_completed_stale_high_risk_script_does_not_block_downstream_execution(
    tmp_path: Path,
) -> None:
    review = script_review(risk_level="high", requires_approval=True)
    review["status"] = "approved"
    review["approvalFingerprint"] = script_review_fingerprint(review)
    review["codePreview"] = "print('changed high risk script')\n"
    request = build_planner_request(
        tmp_path,
        script_review=review,
        script_status="completed",
    )

    events = list(run_graph_events(request))

    assert "node.needs_permission" not in [event.type for event in events]
    assert [
        event.payload["nodeId"] for event in events if event.type == "node.running"
    ] == ["task-output"]
    assert events[-1].type == "task.completed"


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
    source_fetcher = FakeSourceFetcher(
        {
            "https://packaging.python.org/en/latest/": (
                "The Python Packaging User Guide explains pip, build backends, "
                "publishing workflows, and modern project metadata."
            ),
            "https://docs.python.org/3/": (
                "Python documentation describes packaging support, module "
                "installation, and related standard library references."
            ),
        }
    )

    events = list(
        run_graph_events(
            request,
            search_provider=provider,
            source_fetcher=source_fetcher,
        )
    )

    running_node_ids = [
        event.payload["nodeId"] for event in events if event.type == "node.running"
    ]
    assert running_node_ids == [
        "research-intent-analysis",
        "research-privacy-guard",
        "research-query-plan",
        "research-parallel-search",
        "research-source-review",
        "research-source-reading",
        "research-report-synthesis",
        "research-report-quality-check",
        "research-markdown-output",
    ]
    assert set(source_fetcher.urls) == {
        "https://packaging.python.org/en/latest/",
        "https://docs.python.org/3/",
    }
    artifact_event = next(event for event in events if event.type == "artifact.created")
    artifact_path = Path(artifact_event.payload["path"])
    assert artifact_path.is_file()
    assert artifact_path.parent == tmp_path / "artifacts" / "research"
    content = artifact_path.read_text(encoding="utf-8")
    headings = [
        content.index("## Summary"),
        content.index("## Key Findings"),
        content.index("## Project Summaries"),
        content.index("## Source Review"),
        content.index("## Open Questions"),
        content.index("## References"),
    ]
    assert headings == sorted(headings)
    assert "modern project metadata" in content
    completed_event = next(event for event in events if event.type == "research.completed")
    assert completed_event.payload["taskId"] == "task-research"
    assert completed_event.payload["reportArtifactId"] == artifact_event.payload["artifactId"]
    assert completed_event.payload["reportArtifactId"] == artifact_path.stem
    assert completed_event.payload["reportArtifactPath"] == str(artifact_path)
    assert completed_event.payload["qualityStatus"] == "passed"
    assert completed_event.payload["qualityIssues"] == []
    assert completed_event.payload["acceptedSources"]
    assert completed_event.payload["rejectedSources"]
    quality_record = RunJournal(
        project_path=request.project_path,
        run_id=request.run_id,
    ).read_node("research-report-quality-check")
    assert quality_record["values"]["qualityStatus"] == "passed"
    assert quality_record["values"]["checkedReferenceCount"] == 2
    assert events[-1].type == "task.completed"


def test_research_report_synthesis_includes_source_citations(tmp_path: Path) -> None:
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
                        )
                    ]
                )
            ],
            f"{question} official sources": [SearchResponse(results=[])],
        }
    )
    source_fetcher = FakeSourceFetcher(
        {
            "https://packaging.python.org/en/latest/": (
                "The Python Packaging User Guide explains pip, build backends, "
                "publishing workflows, and modern project metadata."
            )
        }
    )

    events = list(
        run_graph_events(
            request,
            search_provider=provider,
            source_fetcher=source_fetcher,
        )
    )

    artifact_event = next(event for event in events if event.type == "artifact.created")
    report = Path(artifact_event.payload["path"]).read_text(encoding="utf-8")

    assert "[S1]" in report
    assert "## References" in report
    assert "S1" in report
    assert "https://packaging.python.org/en/latest/" in report


def test_research_quality_check_flags_missing_evidence_citations(tmp_path: Path) -> None:
    question = "Compare current Python packaging tools"
    request = build_research_flow_request(tmp_path, question)
    evidence = evidence_from_search_results(
        question,
        [
            {
                "title": "Python packaging user guide",
                "url": "https://packaging.python.org/en/latest/",
                "snippet": "Official guide to Python packaging tools.",
                "accepted": True,
            }
        ],
    )
    output = ResearchFlowExecutor(request).run(
        "research-report-quality-check",
        {
            "research-report-synthesis": NodeOutput(
                values={
                    "markdown": "# Research Report\n\nNo citations here.",
                    "summary": "No citations here.",
                    "acceptedSources": [
                        {
                            "title": "Python packaging user guide",
                            "url": "https://packaging.python.org/en/latest/",
                            "snippet": "Official guide to Python packaging tools.",
                            "accepted": True,
                            "sourceContent": "Readable content.",
                        }
                    ],
                    "rejectedSources": [],
                    "evidenceSet": evidence.model_dump(),
                }
            )
        },
    )

    assert output.values["qualityStatus"] == "needs_review"
    assert "missing_citations" in output.values["qualityIssues"]


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
    source_fetcher = FakeSourceFetcher(
        {
            "https://langchain-ai.github.io/langgraph/": (
                "LangGraph documentation explains graph-based agent orchestration."
            ),
            "https://github.com/langchain-ai/langgraph": (
                "The LangGraph repository contains the project source and examples."
            ),
        }
    )
    first_request = build_research_flow_request(
        tmp_path,
        question,
        run_id="run-research-first",
    )

    first_events = list(
        run_graph_events(
            first_request,
            search_provider=provider,
            source_fetcher=source_fetcher,
        )
    )

    assert first_events[-1].type == "task.failed"
    retry_request = build_research_flow_request(
        tmp_path,
        question,
        run_id="run-research-retry",
    )
    retry_request.mode.type = "failed_only"
    retry_request.mode.source_run_id = "run-research-first"

    retry_events = list(
        run_graph_events(
            retry_request,
            search_provider=provider,
            source_fetcher=source_fetcher,
        )
    )

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
        "research-source-reading",
        "research-report-synthesis",
        "research-report-quality-check",
        "research-markdown-output",
    ]
    assert retry_events[-1].type == "task.completed"


def test_runtime_notice_uses_strict_exceeded_threshold(tmp_path: Path) -> None:
    request = build_request(
        tmp_path,
        nodes=[
            build_node(
                "zero-estimate",
                "fixed_tool",
                [],
                tool_ref="document.receive_attachment",
                estimate={"durationMs": 0},
            ),
            build_node(
                "equal-estimate",
                "fixed_tool",
                [],
                tool_ref="document.receive_attachment",
                estimate={"durationMs": 25},
            ),
        ],
    )
    zero_estimate, equal_estimate = request.graph.nodes

    assert _runtime_notice_for_node(zero_estimate, 0) is None
    assert _runtime_notice_for_node(equal_estimate, 25) is None


def test_emits_and_persists_runtime_notice_when_node_exceeds_estimate(
    tmp_path: Path,
) -> None:
    request = build_request(
        tmp_path,
        nodes=[
            build_node(
                "document-input",
                "fixed_tool",
                [],
                tool_ref="document.receive_attachment",
                estimate={"durationMs": 1},
            )
        ],
    )

    class SlowExecutor(FakeNodeExecutor):
        def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
            sleep(0.02)
            return super().run(node_id, inputs)

    events = list(run_graph_events(request, executor=SlowExecutor()))

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
    record = RunJournal(
        project_path=request.project_path,
        run_id=request.run_id,
    ).read_node("document-input")
    assert record["runtimeNotice"] == notice.payload["notice"]



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


def test_graph_tool_validation_uses_injected_tool_registry_catalog(
    tmp_path: Path,
) -> None:
    custom_registry = ToolRegistry(
        [
            ToolManifestSpec(
                tool_id="document.injected_custom",
                name="Injected Custom",
                description="A test-only injected registry tool.",
                version="1.0.0",
                source_type="test",
                license="internal",
                runtime=None,
                entrypoint=None,
                capabilities=["test_custom"],
                operations=[
                    ToolOperationSpec(
                        name="run",
                        description="Run the injected registry tool.",
                    )
                ],
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                permissions=["read_project_files"],
                error_codes=[],
                timeout_policy={},
                artifact_policy={},
                security_policy={},
                examples=[],
                node_templates=[],
            )
        ]
    )
    request = build_request(
        tmp_path,
        nodes=[
            build_node(
                "custom-tool",
                "fixed_tool",
                [],
                tool_ref="document.injected_custom",
            )
        ],
    )

    events = list(
        run_graph_events(
            request,
            executor=FakeNodeExecutor(),
            tool_registry=custom_registry,
        )
    )

    assert [event.type for event in events] == [
        "run.started",
        "node.running",
        "node.completed",
        "node.run_recorded",
        "task.completed",
    ]


def test_planned_executor_uses_execution_graph_tool_binding(tmp_path: Path) -> None:
    request = RunGraphRequest(
        task_id="task-binding-runtime",
        run_id="run-binding-runtime",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph=RunGraph(
            graphId="binding-graph",
            nodes=[
                build_node(
                    "tool-node",
                    "fixed_tool",
                    [],
                    tool_ref="internal:document.markitdown_convert",
                )
            ],
            edges=[],
            metadata={"plannerChain": {"strategy": "legacy_task_planner"}},
        ),
    )
    execution_graph = compile_execution_graph(request)
    request.graph.nodes[0].toolRef = "internal:missing.after.compile"
    executor = PlannedTaskExecutor(
        request,
        tool_gateway=RecordingGateway(),
        execution_graph=execution_graph,
    )

    with pytest.raises(HarnessError) as error:
        executor.run("tool-node", {})

    assert error.value.code == "missing_input"
    assert "requires at least one attachment" in error.value.message


def test_planned_fixed_tool_executes_from_runtime_binding_without_tool_id_branch(
    tmp_path: Path,
) -> None:
    class EchoGateway:
        provider_id = "echo"

        def __init__(self) -> None:
            self.calls = []

        def list_tools(self):
            return [
                UnifiedToolDefinition(
                    id="internal:test.echo_values",
                    source="internal",
                    provider_id="internal",
                    provider_tool_name="test.echo_values",
                    display_name="Echo Values",
                    description="Echo rendered values.",
                    capabilities=["test.echo"],
                    input_schema={
                        "type": "object",
                        "required": [
                            "operation",
                            "message",
                            "source_text",
                            "metadata_value",
                        ],
                        "properties": {
                            "operation": {
                                "type": "string",
                                "enum": ["echo_values"],
                            },
                            "message": {"type": "string"},
                            "source_text": {"type": "string"},
                            "metadata_value": {"type": "string"},
                        },
                    },
                    output_schema={"type": "object"},
                    permissions=[],
                    safety_policy=ToolSafetyPolicy(
                        filesystem="none",
                        network="none",
                        user_approval="never",
                        secrets="none",
                        sandbox="not_required",
                        max_runtime_ms=5000,
                    ),
                    timeout_ms=5000,
                )
            ]

        def call_tool(self, invocation):
            self.calls.append(invocation)
            return UnifiedToolResult(
                ok=True,
                content=[
                    ToolResultContent(
                        type="json",
                        value={
                            "echo": invocation.arguments["message"],
                            "source_text": invocation.arguments["source_text"],
                            "metadata_value": invocation.arguments["metadata_value"],
                        },
                    )
                ],
                structured_content={
                    "echo": invocation.arguments["message"],
                    "source_text": invocation.arguments["source_text"],
                    "metadata_value": invocation.arguments["metadata_value"],
                },
                artifacts=[],
                metadata={"gateway": "echo"},
            )

    echo_node = build_node(
        "echo-node",
        "fixed_tool",
        ["source-node"],
        tool_ref="internal:test.echo_values",
    )
    echo_node["toolBinding"] = {
        "operation": "echo_values",
        "argumentsTemplate": {
            "values": {
                "operation": "echo_values",
                "message": "hello from binding",
                "metadata_value": "{graph.metadata.echoLabel}",
            },
            "required": ["operation", "message", "source_text", "metadata_value"],
        },
        "inputMappings": [
            {
                "source": "source-node",
                "sourceKey": "text",
                "targetArgument": "source_text",
            }
        ],
    }
    request = RunGraphRequest(
        task_id="task-generic-fixed-tool",
        run_id="run-generic-fixed-tool",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph=RunGraph(
            graphId="generic-fixed-tool-graph",
            nodes=[
                build_node("source-node", "planning", []),
                echo_node,
            ],
            edges=[],
            metadata={
                "taskKind": "generic_tool",
                "echoLabel": "phase3",
            },
        ),
    )
    gateway = EchoGateway()
    executor = PlannedTaskExecutor(
        request,
        tool_gateway=gateway,
        execution_graph=compile_execution_graph(request),
    )

    output = executor.run(
        "echo-node",
        {"source-node": NodeOutput(values={"text": "upstream text"})},
    )

    assert len(gateway.calls) == 1
    invocation = gateway.calls[0]
    assert invocation.tool_id == "internal:test.echo_values"
    assert invocation.arguments == {
        "operation": "echo_values",
        "message": "hello from binding",
        "metadata_value": "phase3",
        "source_text": "upstream text",
    }
    assert output.values == {
        "echo": "hello from binding",
        "source_text": "upstream text",
        "metadata_value": "phase3",
    }


def test_missing_fixed_tool_binding_fails_before_run_started(tmp_path: Path) -> None:
    request = RunGraphRequest(
        task_id="task-missing-binding",
        run_id="run-missing-binding",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph=RunGraph(
            graphId="missing-binding-graph",
            nodes=[
                build_node("missing-tool", "fixed_tool", []),
                build_node("task-output", "output", ["missing-tool"]),
            ],
            edges=[
                {
                    "id": "missing-tool-task-output",
                    "source": "missing-tool",
                    "target": "task-output",
                }
            ],
            metadata={"plannerChain": {"strategy": "legacy_task_planner"}},
        ),
    )

    events = list(run_graph_events(request))

    assert [event.type for event in events] == ["task.failed"]
    assert events[0].payload["errorCode"] == "unsupported_binding"
    assert "missing-tool" in events[0].payload["error"]


def test_execution_graph_does_not_change_run_event_shape(tmp_path: Path) -> None:
    graph_event = run_agent(
        UserMessage(
            task_id="execution-graph-event-shape",
            content="Create a Python script that counts rows in a CSV file.",
        )
    )[0]
    graph = graph_event.payload["graph"]
    request = RunGraphRequest(
        task_id="execution-graph-event-shape",
        run_id="execution-graph-run",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph=RunGraph.model_validate(graph),
    )

    events = list(run_graph_events(request))

    assert events[0].type == "run.started"
    assert set(events[0].payload.keys()) == {"runId", "taskId", "startedAt"}
    assert all("executionGraph" not in event.payload for event in events)


def test_react_enabled_model_node_records_observations(tmp_path: Path) -> None:
    class SequencedExecutionModel:
        def __init__(self) -> None:
            self.replies = [
                (
                    '{"kind":"tool","tool_id":"internal:document.receive_attachment",'
                    '"arguments":{"paths":"README.md"}}'
                ),
                '{"kind":"final","text":"Inspected README."}',
            ]
            self.calls: list[list[ChatMessage]] = []

        def chat(
            self,
            messages: list[ChatMessage],
            *,
            temperature=None,
            max_tokens=None,
            policy=None,
        ) -> str:
            self.calls.append(messages)
            return self.replies.pop(0)

    request = build_request(
        tmp_path,
        nodes=[
            build_node(
                "model-reasoning",
                "model",
                [],
                model_ref="local-task-reasoner",
            ),
            build_node("task-output", "output", ["model-reasoning"]),
        ],
        graph_metadata={
            "plannerChain": {"strategy": "legacy_task_planner"},
            "react": {
                "enabled": True,
                "allowedToolIds": ["internal:document.receive_attachment"],
                "maxSteps": 2,
                "maxToolCalls": 1,
            },
        },
    )
    gateway = RecordingGateway()

    events = list(
        run_graph_events(
            request,
            model_client=SequencedExecutionModel(),
            tool_gateway=gateway,
        )
    )

    assert events[-1].type == "task.completed"
    model_record = RunJournal(
        project_path=request.project_path,
        run_id=request.run_id,
    ).read_node("model-reasoning")
    assert model_record["values"]["text"] == "Inspected README."
    assert model_record["values"]["react"]["toolCallCount"] == 1
    assert (
        model_record["values"]["react"]["observations"][0]["tool_id"]
        == "internal:document.receive_attachment"
    )
    assert gateway.calls[0].tool_id == "internal:document.receive_attachment"


def test_react_native_tool_calls_metadata_routes_through_gateway(tmp_path: Path) -> None:
    class NativeExecutionModel:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def chat(
            self,
            messages: list[ChatMessage],
            *,
            temperature=None,
            max_tokens=None,
            policy=None,
        ) -> str:
            raise AssertionError("native metadata should call chat_with_tools()")

        def chat_with_tools(
            self,
            messages: list[ChatMessage],
            *,
            tools,
            tool_choice="auto",
            temperature=None,
            max_tokens=None,
            policy=None,
        ) -> ChatWithToolsResponse:
            self.calls.append(
                {"messages": messages, "tools": tools, "tool_choice": tool_choice}
            )
            if len(self.calls) == 1:
                return ChatWithToolsResponse(
                    content="",
                    tool_calls=[
                        ModelToolCall(
                            id="call-native-receive",
                            name=model_safe_tool_name(
                                "internal:document.receive_attachment"
                            ),
                            arguments={
                                "operation": "receive_attachment",
                                "paths": "README.md",
                            },
                        )
                    ],
                )
            return ChatWithToolsResponse(
                content="Native inspection complete.",
                tool_calls=[],
            )

    request = build_request(
        tmp_path,
        nodes=[
            build_node(
                "model-reasoning",
                "model",
                [],
                model_ref="local-task-reasoner",
            ),
            build_node("task-output", "output", ["model-reasoning"]),
        ],
        graph_metadata={
            "plannerChain": {"strategy": "legacy_task_planner"},
            "react": {
                "enabled": True,
                "nativeToolCalls": True,
                "allowedToolIds": ["internal:document.receive_attachment"],
                "maxSteps": 2,
                "maxToolCalls": 1,
            },
        },
    )
    gateway = RecordingGateway()
    model = NativeExecutionModel()

    events = list(
        run_graph_events(
            request,
            model_client=model,
            tool_gateway=gateway,
        )
    )

    assert events[-1].type == "task.completed"
    model_record = RunJournal(
        project_path=request.project_path,
        run_id=request.run_id,
    ).read_node("model-reasoning")
    assert model_record["values"]["text"] == "Native inspection complete."
    assert model_record["values"]["react"]["toolCallCount"] == 1
    assert gateway.calls[0].invocation_id == "call-native-receive"
    assert gateway.calls[0].tool_id == "internal:document.receive_attachment"
    assert gateway.calls[0].arguments == {
        "operation": "receive_attachment",
        "paths": "README.md",
    }
    assert model.calls[0]["tool_choice"] == "auto"


def test_react_metadata_string_false_does_not_enable_react(tmp_path: Path) -> None:
    class SequencedExecutionModel:
        def __init__(self) -> None:
            self.replies = [
                (
                    '{"kind":"tool","tool_id":"internal:document.receive_attachment",'
                    '"arguments":{"paths":"README.md"}}'
                ),
                '{"kind":"final","text":"React should not run."}',
            ]
            self.calls: list[list[ChatMessage]] = []

        def chat(
            self,
            messages: list[ChatMessage],
            *,
            temperature=None,
            max_tokens=None,
            policy=None,
        ) -> str:
            self.calls.append(messages)
            return self.replies.pop(0)

    request = build_request(
        tmp_path,
        nodes=[
            build_node(
                "model-reasoning",
                "model",
                [],
                model_ref="local-task-reasoner",
            ),
            build_node("task-output", "output", ["model-reasoning"]),
        ],
        graph_metadata={
            "plannerChain": {"strategy": "legacy_task_planner"},
            "react": {
                "enabled": "false",
                "allowedToolIds": ["internal:document.receive_attachment"],
            },
        },
    )
    gateway = RecordingGateway()

    events = list(
        run_graph_events(
            request,
            model_client=SequencedExecutionModel(),
            tool_gateway=gateway,
        )
    )

    assert events[-1].type == "task.completed"
    model_record = RunJournal(
        project_path=request.project_path,
        run_id=request.run_id,
    ).read_node("model-reasoning")
    assert "react" not in model_record["values"]
    assert model_record["values"]["text"].startswith('{"kind":"tool"')
    assert gateway.calls == []


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
                permissions=["read_attachment"],
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


def test_execution_emits_permission_required_before_running_blocked_node(
    tmp_path: Path,
) -> None:
    request = build_request(
        tmp_path,
        nodes=[
            build_node(
                "network-node",
                "model",
                [],
                permissions=["network"],
            )
        ],
    )

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert "node.running" not in [event.type for event in events]
    assert events[0].type == "run.started"
    assert events[1].type == "permission.required"
    assert events[1].payload["nodeId"] == "network-node"
    assert events[1].payload["permissions"] == ["network"]
    assert "graph.patch_suggested" not in [event.type for event in events]
    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "permission_required"


def test_execution_runs_blocked_permission_when_approved(tmp_path: Path) -> None:
    request = build_request(
        tmp_path,
        nodes=[
            build_node(
                "network-node",
                "model",
                [],
                permissions=["network"],
            )
        ],
    )
    request.approved_permissions = ["network"]

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert "node.running" in [event.type for event in events]
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


def test_accepts_unified_internal_tool_refs_for_existing_tools(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)
    for node in request.graph.nodes:
        if node.toolRef:
            node.toolRef = f"internal:{node.toolRef}"

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert events[-1].type == "task.completed"


def test_disabled_old_tool_id_blocks_unified_internal_tool_ref(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)
    for node in request.graph.nodes:
        if node.toolRef:
            node.toolRef = f"internal:{node.toolRef}"
    request.disabled_tool_ids = ["document.receive_attachment"]

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "tool_disabled"


def test_disabled_tool_failure_emits_replan_suggestion(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)
    request.disabled_tool_ids = ["document.receive_attachment"]

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    suggestion_event = next(
        event for event in events if event.type == "graph.patch_suggested"
    )
    assert suggestion_event.payload["requires_user_approval"] is True
    assert suggestion_event.payload["operations"][0]["op"] == "request_tool_enablement"
    assert suggestion_event.payload["operations"][0]["node_id"] == "document-input"
    assert events[-1].type == "task.failed"


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
    source.write_text("姝ｆ枃", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)

    class EmptyContentExecutor(FakeNodeExecutor):
        def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
            if node_id == "content-organize":
                return NodeOutput(values={"outline": ""})
            return super().run(node_id, inputs)

    events = list(run_graph_events(request, executor=EmptyContentExecutor()))

    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "empty_node_output"


def test_execution_emits_replan_suggestion_for_empty_node_output(
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

    suggestion_event = next(
        event for event in events if event.type == "graph.patch_suggested"
    )
    assert suggestion_event.payload["operations"][0]["op"] == "retry_node"
    assert suggestion_event.payload["operations"][0]["node_id"] == "content-organize"
    assert suggestion_event.payload["actions"][0]["kind"] == "retry"
    assert events[-1].type == "task.failed"
    failure_record = RunJournal(
        project_path=request.project_path,
        run_id=request.run_id,
    ).read_node("content-organize")
    assert failure_record["verifierDiagnostics"][0]["code"] == "empty_node_output"


def test_execution_fails_when_final_verifier_rejects_output(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)

    events = list(
        run_graph_events(
            request,
            executor=FakeNodeExecutor(),
            final_verifier=RejectingFinalVerifier(),
        )
    )

    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "missing_final_output"


def test_final_verifier_replan_suggestion_uses_implicated_output_node(
    tmp_path: Path,
) -> None:
    first_artifact = tmp_path / "first.md"
    first_artifact.write_text("first", encoding="utf-8")
    second_artifact = tmp_path / "second.md"
    request = build_request(
        tmp_path,
        nodes=[
            build_node("source", "model", []),
            build_node("first-output", "output", ["source"]),
            build_node("second-output", "output", ["source"]),
        ],
    )

    class MultiOutputExecutor(FakeNodeExecutor):
        def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
            if node_id == "first-output":
                return NodeOutput(
                    values={"artifact": str(first_artifact)},
                    artifacts=[str(first_artifact)],
                )
            if node_id == "second-output":
                return NodeOutput(values={"artifact": str(second_artifact)})
            return super().run(node_id, inputs)

    events = list(
        run_graph_events(
            request,
            executor=MultiOutputExecutor(),
        )
    )

    suggestion_event = next(
        event for event in events if event.type == "graph.patch_suggested"
    )
    assert suggestion_event.payload["operations"][0]["node_id"] == "second-output"
    assert events[-1].type == "task.failed"


def test_document_flow_exports_markdown_artifact(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("# 鏍囬\n\n姝ｆ枃鍐呭", encoding="utf-8")
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
    assert "outline result" in exported_content
    assert "report result" in exported_content
    assert events[-1].type == "task.completed"


def test_run_completion_auto_writes_memory_records(tmp_path: Path) -> None:
    request = build_request(
        tmp_path,
        nodes=[build_node("task-output", "output", [])],
        graph_metadata={"memory": {"autoWrite": True}},
    )

    class OutputExecutor:
        def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
            return NodeOutput(values={"text": "api_key=sk-secret completed"})

    events = list(run_graph_events(request, executor=OutputExecutor()))

    assert events[-1].type == "task.completed"
    records = MemoryStore(request.project_path).list()
    assert [record.kind for record in records] == ["graph_summary"]
    assert records[0].source_refs == [request.run_id, request.task_id]
    assert "sk-secret" not in records[0].summary


def test_planned_output_node_fails_when_non_planning_dependency_output_is_missing(
    tmp_path: Path,
) -> None:
    request = build_request(
        tmp_path,
        nodes=[
            {
                **build_node("execution-order-planning", "planning", []),
                "status": "completed",
            },
            {
                **build_node(
                    "document-input",
                    "fixed_tool",
                    ["execution-order-planning"],
                    tool_ref="document.receive_attachment",
                ),
                "status": "completed",
            },
            build_node("file-export", "output", ["document-input"]),
        ],
    )
    request.graph.metadata["taskKind"] = "document"

    events = list(run_graph_events(request))

    running = [event.payload["nodeId"] for event in events if event.type == "node.running"]
    assert running == ["file-export"]
    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "missing_dependency_output"
    assert "document-input" in events[-1].payload["error"]


def test_planned_model_node_uses_runtime_model_client_instead_of_placeholder(
    tmp_path: Path,
) -> None:
    request = build_request(
        tmp_path,
        nodes=[
            build_node("model-reasoning", "model", [], model_ref="local-task-reasoner"),
            build_node("task-output", "output", ["model-reasoning"]),
        ],
    )
    request.graph.metadata["taskKind"] = "content"
    class RuntimeModelClient(FakeModelClient):
        def chat(
            self,
            messages: list[ChatMessage],
            *,
            temperature: float | None = None,
            max_tokens: int | None = None,
            policy: ModelCallPolicy | None = None,
        ) -> str:
            self.calls.append(messages)
            self.policies.append(policy)
            self.temperatures.append(temperature)
            self.max_tokens.append(max_tokens)
            return "real model result"

    client = RuntimeModelClient()

    events = list(run_graph_events(request, model_client=client))

    assert events[-1].type == "task.completed"
    model_record = RunJournal(
        project_path=request.project_path,
        run_id=request.run_id,
    ).read_node("model-reasoning")
    assert client.calls
    assert model_record["values"]["text"] == "real model result"
    assert "Planned model step" not in model_record["values"]["text"]


def test_planned_model_nodes_use_node_reasoning_policy(tmp_path: Path) -> None:
    request = build_request(
        tmp_path,
        nodes=[
            build_node("model-reasoning", "model", [], model_ref="local-task-reasoner"),
            build_node("task-output", "output", ["model-reasoning"]),
        ],
        graph_metadata={"taskKind": "content"},
    )
    client = FakeModelClient()

    events = list(run_graph_events(request, model_client=client))

    assert events[-1].type == "task.completed"
    assert [policy.profile if policy else None for policy in client.policies] == [
        ModelCallProfile.NODE_REASONING
    ]
    assert client.temperatures == [0.2]
    assert client.max_tokens == [1536]


def test_planned_model_node_fails_without_bound_runtime(
    tmp_path: Path,
) -> None:
    request = build_request(
        tmp_path,
        nodes=[
            build_node("model-reasoning", "model", [], model_ref="unknown-model"),
            build_node("task-output", "output", ["model-reasoning"]),
        ],
    )
    request.graph.metadata["taskKind"] = "content"

    events = list(run_graph_events(request, model_client=FakeModelClient()))

    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "unsupported_runtime"
    assert "unknown-model" in events[-1].payload["error"]


def test_input_port_contract_rejects_artifact_input_without_artifact_output(
    tmp_path: Path,
) -> None:
    text_node = {
        **build_node("text-only-model", "model", [], model_ref="local-task-reasoner"),
        "outputPorts": [{"id": "text-output", "label": "Text", "dataType": "text"}],
    }
    file_export = {
        **build_node("file-export", "output", ["text-only-model"]),
        "inputPorts": [{"id": "artifact-input", "label": "Artifact", "dataType": "artifact"}],
    }
    request = build_request(tmp_path, nodes=[text_node, file_export])

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "input_contract_unsatisfied"
    assert "artifact-input" in events[-1].payload["error"]


def test_github_research_query_plan_expands_project_discovery_queries(
    tmp_path: Path,
) -> None:
    question = (
        "\u5e2e\u6211\u67e5\u8be2\u4eca\u5929GitHub\u7f51\u7ad9"
        "\u4e0a\u9762\u6709\u54ea\u4e9b\u70ed\u95e8\u7684\u9879\u76ee\uff0c"
        "\u7136\u540e\u7814\u7a76\u6bcf\u4e00\u4e2a\u9879\u76ee\u3002"
    )
    provider = SequencedSearchProvider(
        {
            question: [SearchResponse(results=[])],
            "GitHub Trending repositories today": [SearchResponse(results=[])],
            "GitHub trending repositories developers daily": [
                SearchResponse(results=[])
            ],
            "GitHub trending repositories official": [SearchResponse(results=[])],
        }
    )
    request = build_research_flow_request(tmp_path, question)

    events = list(run_graph_events(request, search_provider=provider))

    assert provider.queries == [
        question,
        "GitHub Trending repositories today",
        "GitHub trending repositories developers daily",
        "GitHub trending repositories official",
    ]
    assert events[-1].type == "task.completed"


def test_research_report_binds_each_key_finding_to_source_reference(
    tmp_path: Path,
) -> None:
    question = "Research and compare current Python packaging tools"
    provider = SequencedSearchProvider(
        {
            question: [
                SearchResponse(
                    results=[
                        SearchResult(
                            title="Python packaging docs",
                            url="https://docs.python.org/3/",
                            snippet="Official guide to Python packaging tools.",
                        )
                    ]
                )
            ],
            f"{question} official sources": [SearchResponse(results=[])],
        }
    )
    request = build_research_flow_request(tmp_path, question)

    events = list(run_graph_events(request, search_provider=provider))

    artifact_event = next(event for event in events if event.type == "artifact.created")
    content = Path(artifact_event.payload["path"]).read_text(encoding="utf-8")
    assert "- [S1] Python packaging docs:" in content
    assert "- S1 Python packaging docs - https://docs.python.org/3/" in content


def test_generated_markdown_conversion_graph_exports_converted_artifact(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.docx"
    source.write_bytes(b"fake docx")
    attachment = Attachment(
        attachment_id="a1",
        name=source.name,
        path=str(source),
        size_bytes=source.stat().st_size,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    graph_event = run_agent(
        UserMessage(
            task_id="task-markdown-convert",
            content="Please convert this document to Markdown.",
            attachments=[attachment],
        )
    )[0]
    request = RunGraphRequest(
        task_id="task-markdown-convert",
        project_path=str(tmp_path / "project.alita"),
        attachments=[attachment.model_dump()],
        graph=graph_event.payload["graph"],
    )

    events = list(run_graph_events(request, tool_executor=FakeToolExecutor()))

    file_export_events = [
        event
        for event in events
        if event.type == "artifact.created"
        and event.payload["sourceNodeId"] == "file-export"
    ]
    assert len(file_export_events) == 1
    final_artifact = Path(file_export_events[0].payload["path"])
    assert final_artifact == tmp_path / "artifacts" / "converted" / "01-input.md"
    assert final_artifact.read_text(encoding="utf-8") == "# Markdown\n\nparsed text"
    assert not list((tmp_path / "artifacts").glob("report-*.md"))
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
    invocation = next(
        call
        for call in tool_executor.calls
        if call.tool_id == "document.markitdown_convert"
    )
    assert invocation.tool_id == "document.markitdown_convert"
    assert invocation.operation == "convert_local_file"
    assert invocation.arguments["input_path"] == str(source)
    assert invocation.arguments["output_path"] == str(
        tmp_path / "artifacts" / "converted" / "01-input.md"
    )
    assert events[-1].type == "task.completed"


def test_tool_executor_injection_is_wrapped_by_unified_gateway(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent_service.tool_gateway import (
        default_unified_tool_gateway as real_default_unified_tool_gateway,
    )

    class StrictGatewayTranslatedExecutor:
        def __init__(self) -> None:
            self.calls = []

        def run(self, invocation):
            self.calls.append(invocation)
            if invocation.tool_id == "document.receive_attachment":
                assert invocation.operation == "receive_attachment"
                assert "operation" not in invocation.arguments
                return ToolResult(
                    values={"paths": str(invocation.arguments.get("paths", ""))}
                )

            assert invocation.tool_id == "document.markitdown_convert"
            assert invocation.operation == "convert_local_file"
            assert "operation" not in invocation.arguments
            output_path = Path(invocation.arguments["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("# Markdown\n\nparsed text", encoding="utf-8")
            return ToolResult(
                values={"text": "# Markdown\n\nparsed text"},
                artifacts=[str(output_path)],
                metadata={"converter": "strict"},
            )

    class SpyGateway:
        def __init__(self, gateway) -> None:
            self.gateway = gateway
            self.calls = []

        def list_tools(self):
            return self.gateway.list_tools()

        def call_tool(self, invocation):
            self.calls.append(invocation)
            if invocation.tool_id == "internal:document.receive_attachment":
                assert invocation.arguments["operation"] == "receive_attachment"
                assert "paths" in invocation.arguments
            else:
                assert invocation.tool_id == "internal:document.markitdown_convert"
                assert invocation.arguments["operation"] == "convert_local_file"
                assert "input_path" in invocation.arguments
                assert "output_path" in invocation.arguments
            return self.gateway.call_tool(invocation)

    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    request = build_document_flow_request(tmp_path, source)
    tool_executor = StrictGatewayTranslatedExecutor()
    factory_calls = []
    spy_gateways = []

    def spy_default_unified_tool_gateway(
        *,
        packages_root=None,
        registry=None,
        internal_executor=None,
    ):
        factory_calls.append(
            {
                "packages_root": packages_root,
                "registry": registry,
                "internal_executor": internal_executor,
            }
        )
        spy_gateway = SpyGateway(
            real_default_unified_tool_gateway(
                packages_root=packages_root,
                registry=registry,
                internal_executor=internal_executor,
            )
        )
        spy_gateways.append(spy_gateway)
        return spy_gateway

    monkeypatch.setattr(
        "agent_service.execution.default_unified_tool_gateway",
        spy_default_unified_tool_gateway,
    )

    events = list(
        run_graph_events(
            request,
            model_client=FakeModelClient(),
            tool_executor=tool_executor,
        )
    )

    assert events[-1].type == "task.completed"
    assert len(factory_calls) == 1
    assert factory_calls[0]["internal_executor"] is tool_executor
    assert len(spy_gateways) == 1
    assert [call.tool_id for call in spy_gateways[0].calls] == [
        "internal:document.receive_attachment",
        "internal:document.markitdown_convert",
    ]
    assert [call.tool_id for call in tool_executor.calls] == [
        "document.receive_attachment",
        "document.markitdown_convert",
    ]


def test_explicit_tool_gateway_takes_precedence_over_tool_executor(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    request = build_document_flow_request(tmp_path, source)
    gateway = RecordingGateway()
    tool_executor = FakeToolExecutor()

    events = list(
        run_graph_events(
            request,
            model_client=FakeModelClient(),
            tool_gateway=gateway,
            tool_executor=tool_executor,
        )
    )

    assert events[-1].type == "task.completed"
    assert gateway.calls
    assert tool_executor.calls == []


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
        "document.receive_attachment",
        "document.markitdown_convert",
        "document.typst_compile",
    ]
    typst_call = tool_executor.calls[2]
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

    convert_calls = [
        call
        for call in tool_executor.calls
        if call.tool_id == "document.markitdown_convert"
    ]
    assert len(convert_calls) == 2
    output_paths = [
        Path(invocation.arguments["output_path"])
        for invocation in convert_calls
    ]
    assert output_paths[0] != output_paths[1]
    for output_path in output_paths:
        assert output_path.parent == tmp_path / "artifacts" / "converted"
        assert output_path.suffix == ".md"


def test_run_emits_started_and_cancelled_between_nodes(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("姝ｆ枃", encoding="utf-8")
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
    source.write_text("姝ｆ枃", encoding="utf-8")
    source_run = "run-original"
    journal = RunJournal(project_path=str(tmp_path / "project.alita"), run_id=source_run)
    journal.write_node(
        "document-input",
        {"nodeId": "document-input", "status": "completed", "values": {"paths": str(source)}},
    )
    journal.write_node(
        "document-parse",
        {"nodeId": "document-parse", "status": "completed", "values": {"text": "姝ｆ枃"}},
    )
    journal.write_node(
        "content-organize",
        {"nodeId": "content-organize", "status": "failed", "error": "model failed"},
    )
    journal.write_node(
        "report-generate",
        {"nodeId": "report-generate", "status": "completed", "values": {"report": "report"}},
    )
    request = build_document_flow_request(tmp_path, source, run_id="run-retry")
    request.mode.type = "failed_only"
    request.mode.source_run_id = source_run

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    running = [event.payload["nodeId"] for event in events if event.type == "node.running"]
    assert running == ["content-organize", "file-export"]


def test_failed_only_with_no_failed_nodes_verifies_source_final_output(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "report.md"
    artifact.write_text("report", encoding="utf-8")
    source_run = "run-all-completed"
    journal = RunJournal(project_path=str(tmp_path / "project.alita"), run_id=source_run)
    journal.write_node(
        "file-export",
        {
            "nodeId": "file-export",
            "status": "completed",
            "values": {"artifact": str(artifact)},
            "artifactRefs": [str(artifact)],
        },
    )
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source, run_id="run-no-failed")
    request.mode.type = "failed_only"
    request.mode.source_run_id = source_run

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert [event.type for event in events] == [
        "run.started",
        "task.completed",
    ]


def test_failed_only_with_missing_source_final_artifact_fails_final_verification(
    tmp_path: Path,
) -> None:
    source_run = "run-missing-final-artifact"
    missing_artifact = tmp_path / "missing.md"
    journal = RunJournal(project_path=str(tmp_path / "project.alita"), run_id=source_run)
    journal.write_node(
        "file-export",
        {
            "nodeId": "file-export",
            "status": "completed",
            "values": {"artifact": str(missing_artifact)},
            "artifactRefs": [str(missing_artifact)],
        },
    )
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source, run_id="run-missing-final")
    request.mode.type = "failed_only"
    request.mode.source_run_id = source_run

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert "node.running" not in [event.type for event in events]
    assert "node.failed" not in [event.type for event in events]
    suggestion_event = next(
        event for event in events if event.type == "graph.patch_suggested"
    )
    assert suggestion_event.payload["operations"][0]["op"] == "rerun_node"
    assert suggestion_event.payload["operations"][0]["node_id"] == "file-export"
    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "missing_artifact"


def test_from_node_reruns_target_and_downstream(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("正文", encoding="utf-8")
    source_run = "run-from-node-source"
    journal = RunJournal(project_path=str(tmp_path / "project.alita"), run_id=source_run)
    journal.write_node(
        "document-parse",
        {"nodeId": "document-parse", "status": "completed", "values": {"text": "正文"}},
    )
    journal.write_node(
        "content-organize",
        {"nodeId": "content-organize", "status": "completed", "values": {"outline": "outline"}},
    )
    request = build_document_flow_request(tmp_path, source, run_id="run-from-node")
    request.mode.type = "from_node"
    request.mode.node_id = "report-generate"
    request.mode.source_run_id = source_run

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    running = [event.payload["nodeId"] for event in events if event.type == "node.running"]
    assert running == ["report-generate", "file-export"]


def test_from_node_real_executor_fails_when_dependency_output_missing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.md"
    source.write_text("document text", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)
    request.mode.type = "from_node"
    request.mode.node_id = "report-generate"

    events = list(
        run_graph_events(
            request,
            model_client=FakeModelClient(),
            tool_executor=FakeToolExecutor(),
        )
    )

    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "missing_dependency_output"
    assert "file-export" in events[-1].payload["error"]
    assert "content-organize" in events[-1].payload["error"]


def test_from_node_with_source_outputs_runs_real_document_flow_executor(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.md"
    source.write_text("document text", encoding="utf-8")
    source_run = "run-real-from-node-source"
    journal = RunJournal(project_path=str(tmp_path / "project.alita"), run_id=source_run)
    journal.write_node(
        "document-parse",
        {
            "nodeId": "document-parse",
            "status": "completed",
            "values": {"text": "parsed text"},
        },
    )
    journal.write_node(
        "content-organize",
        {
            "nodeId": "content-organize",
            "status": "completed",
            "values": {"outline": "prior outline"},
        },
    )
    request = build_document_flow_request(tmp_path, source, run_id="run-real-from-node")
    request.mode.type = "from_node"
    request.mode.node_id = "report-generate"
    request.mode.source_run_id = source_run

    events = list(
        run_graph_events(
            request,
            model_client=FakeModelClient(),
            tool_executor=FakeToolExecutor(),
        )
    )

    running = [event.payload["nodeId"] for event in events if event.type == "node.running"]
    assert running == ["report-generate", "file-export"]
    assert events[-1].type == "task.completed"


def build_request(
    tmp_path: Path,
    *,
    nodes: list[dict],
    graph_metadata: dict | None = None,
) -> RunGraphRequest:
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
            "metadata": graph_metadata or {},
        },
    )


def build_planner_request(
    tmp_path: Path,
    *,
    script_review: dict,
    script_status: str = "waiting",
) -> RunGraphRequest:
    temp_script = build_node(
        "temp-script",
        "temporary_script",
        ["execution-order-planning"],
    )
    temp_script["scriptReview"] = script_review
    temp_script["status"] = script_status
    return build_request(
        tmp_path,
        nodes=[
            {
                **build_node("task-analysis", "planning", []),
                "status": "completed",
            },
            {
                **build_node(
                    "execution-order-planning",
                    "planning",
                    ["task-analysis"],
                ),
                "status": "completed",
            },
            temp_script,
            build_node("task-output", "output", ["temp-script"]),
        ],
    )


def script_review(*, risk_level: str, requires_approval: bool) -> dict:
    return {
        "status": "not_reviewed",
        "summary": "Review generated script before execution.",
        "permissions": ["read_project_files", "write_project_files"],
        "riskLevel": risk_level,
        "requiresApproval": requires_approval,
        "codePreview": (
            "import json, sys\n"
            "json.load(sys.stdin)\n"
            "print(json.dumps({'values': {'answer': 42}}))\n"
        ),
        "inputContract": {"targetPath": "project-relative path"},
        "outputContract": {"summary": "text"},
        "approvalFingerprint": None,
    }


def script_review_fingerprint(review: dict) -> str:
    return canonical_script_review_fingerprint(ScriptReviewState(**review))


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
                    permissions=["read_attachment"],
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
            permissions=["read_attachment"],
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
            permissions=["write_project_artifact"],
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
    permissions: list[str] | None = None,
) -> dict:
    node = {
        "nodeId": node_id,
        "nodeType": node_type,
        "displayName": node_id,
        "status": "waiting",
        "inputPorts": [],
        "outputPorts": [],
        "dependencies": dependencies,
        "summary": "娴嬭瘯鑺傜偣",
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "position": {"x": 0, "y": 0},
        "permissionsRequired": permissions or [],
    }
    if tool_ref:
        node["toolRef"] = tool_ref
    if model_ref:
        node["modelRef"] = model_ref
    if estimate is not None:
        node["estimate"] = estimate
    return node


def _single_output_run_request(tmp_path: Path) -> RunGraphRequest:
    return RunGraphRequest(
        task_id="execution-state-task",
        run_id="execution-state-run",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph={
            "graphId": "execution-state-graph",
            "nodes": [
                {
                    "nodeId": "task-output",
                    "nodeType": "output",
                    "displayName": "Task output",
                    "status": "waiting",
                    "inputPorts": [],
                    "outputPorts": [],
                    "dependencies": [],
                    "summary": "Return final output.",
                    "createdBy": "agent",
                    "artifactRefs": [],
                    "retryCount": 0,
                    "position": {"x": 0, "y": 0},
                }
            ],
            "edges": [],
        },
    )


def test_research_flow_executor_uses_default_search_provider_factory(monkeypatch) -> None:
    import agent_service.execution as execution
    from agent_service.execution import ResearchFlowExecutor
    from agent_service.schemas import RunGraph, RunGraphRequest, RunMode, UserMessage
    from agent_service.web_research import build_research_graph
    from agent_service.web_search import SearchResponse, SearchResult

    class Provider:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def search(self, query: str) -> SearchResponse:
            self.queries.append(query)
            return SearchResponse(
                results=[
                    SearchResult(
                        title="Python",
                        url="https://www.python.org/",
                        snippet="Official site.",
                    )
                ]
            )

    provider = Provider()
    monkeypatch.setattr(execution, "default_search_provider", lambda: provider)
    message = UserMessage(task_id="research", content="Compare current Python packaging tools")
    graph = RunGraph(**build_research_graph(message, {}))
    request = RunGraphRequest(
        task_id="research",
        graph=graph,
        project_path="D:/Software Project/Alita/test.alita",
        mode=RunMode(type="full"),
        attachments=[],
    )

    executor = ResearchFlowExecutor(request)
    output = executor.run(
        "research-parallel-search",
        {
            "research-query-plan": execution.NodeOutput(
                values={
                    "sanitizedQuestion": message.content,
                    "queries": [{"query": message.content, "purpose": "primary"}],
                }
            )
        },
    )

    assert provider.queries == ["Compare current Python packaging tools"]
    assert output.values["results"][0]["title"] == "Python"
