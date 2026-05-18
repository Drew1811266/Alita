from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

from agent_service.harness_errors import HarnessError, harness_error_payload
from agent_service.model_client import (
    ChatMessage as ModelChatMessage,
    LlamaCppModelClient,
)
from agent_service.node_output import NodeOutput
from agent_service.privacy import sanitize_for_web_search
from agent_service.result_verifier import ResultVerifier
from agent_service.run_journal import RunJournal
from agent_service.run_registry import DEFAULT_RUN_REGISTRY, RunRegistry
from agent_service.schemas import (
    AgentEvent,
    GraphNode,
    RunGraphRequest,
    ScriptReviewState,
)
from agent_service.tool_execution import (
    ToolExecutor,
    ToolInvocation,
    default_tool_packages_root,
)
from agent_service.tool_registry import ToolRegistry
from agent_service.web_research import (
    REPORT_SECTION_ORDER,
    infer_question_type,
    source_payload,
)
from agent_service.web_search import (
    DuckDuckGoHtmlSearchProvider,
    SearchFailure,
    SearchProvider,
    SearchResponse,
    SearchResult,
    classify_sources,
    rank_sources,
)
from tools.document_tool import write_markdown


class NodeExecutor(Protocol):
    def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
        ...


class ModelClient(Protocol):
    def chat(
        self,
        messages: list[ModelChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        ...


DOCUMENT_FLOW_NODE_IDS = {
    "document-input",
    "document-parse",
    "content-organize",
    "report-generate",
    "typst-export",
    "file-export",
}


@dataclass(frozen=True)
class PartialNodeOutputError(HarnessError):
    output: NodeOutput = field(default_factory=NodeOutput)


class EmptyNodeExecutor:
    def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
        return NodeOutput(values={"text": node_id})


class DocumentFlowExecutor:
    def __init__(
        self,
        request: RunGraphRequest,
        *,
        model_client: ModelClient | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self.request = request
        self.model_client = model_client or LlamaCppModelClient()
        self.tool_executor = tool_executor or ToolExecutor()
        self.project_dir = Path(request.project_path).parent
        self.artifact_dir = self.project_dir / "artifacts"

    def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
        if node_id == "document-input":
            if not self.request.attachments:
                raise ValueError("缺少可执行的文档附件")
            return NodeOutput(
                values={
                    "paths": "\n".join(
                        attachment.path for attachment in self.request.attachments
                    )
                }
            )

        if node_id == "document-parse":
            texts: list[str] = []
            artifacts: list[str] = []
            for index, attachment in enumerate(self.request.attachments):
                input_path = Path(attachment.path)
                output_path = self._converted_output_path(index, input_path)
                result = self.tool_executor.run(
                    ToolInvocation(
                        tool_id="document.markitdown_convert",
                        operation="convert_local_file",
                        arguments={
                            "input_path": attachment.path,
                            "output_path": str(output_path),
                        },
                        project_path=self.request.project_path,
                        allowed_roots=self._allowed_roots(),
                    )
                )
                text = result.values.get("text", "")
                if text:
                    texts.append(text)
                artifacts.extend(result.artifacts)
            return NodeOutput(artifacts=artifacts, values={"text": "\n\n".join(texts)})

        if node_id == "content-organize":
            text = _first_input_value(inputs, "text")
            content = self.model_client.chat(
                [
                    ModelChatMessage(
                        role="system",
                        content="请把用户文档整理成结构化中文要点。",
                    ),
                    ModelChatMessage(role="user", content=text),
                ],
                temperature=0.2,
                max_tokens=1024,
            )
            return NodeOutput(values={"outline": content})

        if node_id == "report-generate":
            text = _first_input_value(inputs, "text")
            content = self.model_client.chat(
                [
                    ModelChatMessage(
                        role="system",
                        content="请根据用户文档生成一份简洁中文报告。",
                    ),
                    ModelChatMessage(role="user", content=text),
                ],
                temperature=0.2,
                max_tokens=1536,
            )
            return NodeOutput(values={"report": content})

        if node_id == "typst-export":
            outline = _first_input_value(inputs, "outline")
            report = _first_input_value(inputs, "report")
            output_stem = f"report-{uuid4().hex[:8]}"
            result = self.tool_executor.run(
                ToolInvocation(
                    tool_id="document.typst_compile",
                    operation="compile_report_pdf",
                    arguments={
                        "title": Path(self.request.project_path).stem or "Alita Report",
                        "outline": outline,
                        "report": report,
                        "source_output_path": str(
                            self.artifact_dir / "typst" / f"{output_stem}.typ"
                        ),
                        "pdf_output_path": str(
                            self.artifact_dir / "typst" / f"{output_stem}.pdf"
                        ),
                    },
                    project_path=self.request.project_path,
                    allowed_roots=self._allowed_roots(),
                )
            )
            return NodeOutput(artifacts=result.artifacts, values=result.values)

        if node_id == "file-export":
            compiled_artifact = _first_input_value(inputs, "artifact")
            if compiled_artifact:
                return NodeOutput(
                    artifacts=_unique_artifacts_from_inputs(inputs),
                    values={"artifact": compiled_artifact},
                )

            upstream_artifacts = _unique_artifacts_from_inputs(inputs)
            outline = _first_input_value(inputs, "outline")
            report = _first_input_value(inputs, "report")
            if upstream_artifacts and not outline and not report:
                return NodeOutput(
                    artifacts=upstream_artifacts,
                    values={"artifact": upstream_artifacts[0]},
                )

            output_path = self.artifact_dir / f"report-{uuid4().hex[:8]}.md"
            exported = write_markdown(
                (
                    "# 文档处理结果\n\n"
                    f"## 整理结果\n\n{outline}\n\n"
                    f"## 报告正文\n\n{report}\n"
                ),
                str(output_path),
            )
            return NodeOutput(artifacts=[exported], values={"artifact": exported})

        raise ValueError(f"未支持的节点: {node_id}")

    def _allowed_roots(self) -> list[str]:
        roots = {str(self.project_dir)}
        roots.update(str(Path(attachment.path).parent) for attachment in self.request.attachments)
        return sorted(roots)

    def _converted_output_path(self, index: int, input_path: Path) -> Path:
        unsafe_chars = '<>:"/\\|?*'
        stem = input_path.stem or "attachment"
        safe_stem = "".join(
            "-"
            if character.isspace()
            else character
            for character in stem
            if character not in unsafe_chars
        )
        if not safe_stem:
            safe_stem = "attachment"
        return self.artifact_dir / "converted" / f"{index + 1:02d}-{safe_stem}.md"


class PlannedTaskExecutor:
    def __init__(
        self,
        request: RunGraphRequest,
        *,
        model_client: ModelClient | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self.request = request
        self.nodes_by_id = {node.nodeId: node for node in request.graph.nodes}
        self.document_executor = DocumentFlowExecutor(
            request,
            model_client=model_client,
            tool_executor=tool_executor,
        )

    def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
        node = self.nodes_by_id[node_id]

        if node_id in DOCUMENT_FLOW_NODE_IDS:
            return self.document_executor.run(node_id, inputs)

        if node.nodeType == "planning":
            return NodeOutput(
                values={
                    "mode": "planned_task",
                    "nodeType": node.nodeType,
                    "summary": node.summary,
                }
            )

        if node.nodeType == "temporary_script":
            review = node.scriptReview
            if _script_requires_permission(node):
                raise HarnessError(
                    "permission_required",
                    f"temporary script requires approval before execution: {node_id}",
                )
            return NodeOutput(
                values={
                    "mode": "planned_task",
                    "nodeType": node.nodeType,
                    "summary": node.summary,
                    "scriptStatus": "preview_only",
                    "riskLevel": review.riskLevel if review is not None else "low",
                }
            )

        if node.nodeType == "model":
            return NodeOutput(
                values={
                    "mode": "planned_task",
                    "nodeType": node.nodeType,
                    "summary": node.summary,
                    "modelRef": node.modelRef or "",
                    "text": f"Planned model step: {node.summary}",
                }
            )

        if node.nodeType == "fixed_tool":
            return NodeOutput(
                values={
                    "mode": "planned_task",
                    "nodeType": node.nodeType,
                    "summary": node.summary,
                    "toolRef": node.toolRef or "",
                    "text": f"Planned tool step: {node.summary}",
                }
            )

        if node.nodeType == "output":
            return NodeOutput(
                artifacts=_unique_artifacts_from_inputs(inputs),
                values={
                    "mode": "planned_task",
                    "nodeType": node.nodeType,
                    "summary": node.summary,
                    "dependencyValues": {
                        dependency: output.values
                        for dependency, output in inputs.items()
                    },
                    "text": node.summary,
                },
            )

        return NodeOutput(
            values={
                "mode": "planned_task",
                "nodeType": node.nodeType,
                "summary": node.summary,
            }
        )


class ResearchFlowExecutor:
    def __init__(
        self,
        request: RunGraphRequest,
        *,
        search_provider: SearchProvider | None = None,
        max_search_attempts: int = 3,
    ) -> None:
        self.request = request
        self.search_provider = search_provider or DuckDuckGoHtmlSearchProvider()
        self.max_search_attempts = max(1, max_search_attempts)
        self.project_dir = Path(request.project_path).parent
        self.artifact_dir = self.project_dir / "artifacts" / "research"

    def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
        if node_id == "research-intent-analysis":
            question = self._question()
            return NodeOutput(
                values={
                    "question": question,
                    "mode": "research_flow",
                    "kind": "research",
                }
            )

        if node_id == "research-privacy-guard":
            question = _input_value(inputs, "question") or self._question()
            guard = sanitize_for_web_search(str(question))
            if guard.blocked:
                raise HarnessError(
                    "privacy_blocked",
                    guard.reason or "Research question was blocked by privacy guard.",
                )
            return NodeOutput(
                values={
                    "question": question,
                    "sanitizedQuestion": guard.sanitizedText,
                    "removedCategories": guard.removedCategories,
                }
            )

        if node_id == "research-query-plan":
            sanitized_question = str(_input_value(inputs, "sanitizedQuestion") or "")
            if not sanitized_question.strip():
                raise HarnessError("empty_node_output", "research query is empty")
            queries = [
                {"query": sanitized_question, "purpose": "primary"},
                {
                    "query": f"{sanitized_question} official sources",
                    "purpose": "official_sources",
                },
            ]
            return NodeOutput(
                values={
                    "sanitizedQuestion": sanitized_question,
                    "queries": queries,
                    "maxSearchAttempts": self.max_search_attempts,
                }
            )

        if node_id == "research-parallel-search":
            query_units = _input_value(inputs, "queries") or []
            results: list[dict[str, Any]] = list(_input_value(inputs, "results") or [])
            failures: list[dict[str, Any]] = list(_input_value(inputs, "failures") or [])
            successful_queries = {
                str(result.get("query", ""))
                for result in results
                if result.get("query")
            }
            successful_queries.update(
                str(query)
                for query in (_input_value(inputs, "completedQueries") or [])
                if query
            )
            for query_unit in query_units:
                query = str(query_unit["query"])
                purpose = str(query_unit.get("purpose", "research"))
                if query in successful_queries:
                    continue
                response = self._search_with_retry(query)
                if response.failure is not None:
                    failure = response.failure
                    next_failures = [
                        existing
                        for existing in failures
                        if existing.get("query") != query
                    ]
                    next_failures.append(_search_failure_payload(query, failure))
                    raise PartialNodeOutputError(
                        "web_search_failed",
                        (
                            f"search query failed after {self.max_search_attempts} "
                            f"attempts: {query}: {failure.message}"
                        ),
                        NodeOutput(
                            values={
                                "sanitizedQuestion": str(
                                    _input_value(inputs, "sanitizedQuestion")
                                    or self._question()
                                ),
                                "queries": query_units,
                                "results": results,
                                "failures": next_failures,
                                "completedQueries": sorted(successful_queries),
                            }
                        ),
                    )
                results.extend(
                    _search_result_payload(result, query=query, purpose=purpose)
                    for result in response.results
                )
                failures = [
                    existing
                    for existing in failures
                    if existing.get("query") != query
                ]
                successful_queries.add(query)
            return NodeOutput(
                values={
                    "sanitizedQuestion": str(
                        _input_value(inputs, "sanitizedQuestion") or self._question()
                    ),
                    "queries": query_units,
                    "results": results,
                    "failures": failures,
                    "completedQueries": sorted(successful_queries),
                }
            )

        if node_id == "research-source-review":
            question = self._question()
            question_type = infer_question_type(question)
            raw_results = _input_value(inputs, "results") or []
            search_results = [
                SearchResult(
                    title=str(result.get("title", "")),
                    url=str(result.get("url", "")),
                    snippet=str(result.get("snippet", "")),
                )
                for result in raw_results
            ]
            classified = classify_sources(
                question_type,
                rank_sources(question_type, search_results),
            )
            sources = [
                source_payload(result, index + 1)
                for index, result in enumerate(classified)
            ]
            accepted_sources = [source for source in sources if source["accepted"]]
            rejected_sources = [source for source in sources if not source["accepted"]]
            return NodeOutput(
                values={
                    "acceptedSources": accepted_sources,
                    "rejectedSources": rejected_sources,
                    "sourceCount": len(sources),
                }
            )

        if node_id == "research-report-synthesis":
            accepted_sources = list(_input_value(inputs, "acceptedSources") or [])
            rejected_sources = list(_input_value(inputs, "rejectedSources") or [])
            summary = self._summary(accepted_sources)
            markdown = _synthesize_research_markdown(
                self._question(),
                summary,
                accepted_sources,
                rejected_sources,
                self._section_order(),
            )
            return NodeOutput(
                values={
                    "markdown": markdown,
                    "summary": summary,
                    "acceptedSources": accepted_sources,
                    "rejectedSources": rejected_sources,
                    "sectionOrder": self._section_order(),
                }
            )

        if node_id == "research-markdown-output":
            markdown = str(_input_value(inputs, "markdown") or "")
            output_path = self.artifact_dir / f"research-report-{uuid4().hex[:8]}.md"
            exported = write_markdown(markdown, str(output_path))
            return NodeOutput(
                artifacts=[exported],
                values={
                    "artifact": exported,
                    "markdown": markdown,
                    "summary": _input_value(inputs, "summary") or "",
                    "acceptedSources": _input_value(inputs, "acceptedSources") or [],
                    "rejectedSources": _input_value(inputs, "rejectedSources") or [],
                },
            )

        raise ValueError(f"Unsupported research node: {node_id}")

    def _question(self) -> str:
        question = self.request.graph.metadata.get("question", "")
        if not isinstance(question, str) or not question.strip():
            raise HarnessError(
                "missing_research_question",
                "Research graph metadata is missing the original question.",
            )
        return question.strip()

    def _section_order(self) -> list[str]:
        configured = self.request.graph.metadata.get("sectionOrder")
        if isinstance(configured, list) and all(
            isinstance(section, str) for section in configured
        ):
            return list(configured)
        return list(REPORT_SECTION_ORDER)

    def _summary(self, accepted_sources: list[dict[str, Any]]) -> str:
        if not accepted_sources:
            return f"No reliable sources were accepted for: {self._question()}"
        return (
            f"Research completed for: {self._question()}. "
            f"{len(accepted_sources)} source(s) passed source review."
        )

    def _search_with_retry(self, query: str) -> SearchResponse:
        latest_failure: SearchFailure | None = None
        for _attempt in range(self.max_search_attempts):
            try:
                response = self.search_provider.search(query)
            except Exception as error:
                latest_failure = SearchFailure(
                    kind="provider_error",
                    message=str(error),
                )
                continue
            if response.failure is None:
                return response
            latest_failure = response.failure
        return SearchResponse(results=[], failure=latest_failure)


def run_graph_events(
    request: RunGraphRequest,
    *,
    executor: NodeExecutor | None = None,
    model_client: ModelClient | None = None,
    tool_executor: ToolExecutor | None = None,
    search_provider: SearchProvider | None = None,
    registry: RunRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
    result_verifier: ResultVerifier | None = None,
) -> Iterator[AgentEvent]:
    try:
        ordered_nodes = _topological_nodes(request)
        _validate_graph_tools(request, tool_registry or _default_tool_registry())
    except (ValueError, HarnessError) as error:
        payload = harness_error_payload(error)
        yield AgentEvent(
            type="task.failed",
            payload={
                "taskId": request.task_id,
                "runId": request.run_id,
                **payload,
            },
        )
        return

    selected_nodes = _selected_nodes_for_mode(request, ordered_nodes)
    if _is_planned_task_graph(request) and not _is_research_graph(request):
        selected_nodes = [
            node for node in selected_nodes if node.nodeType != "planning"
        ]
    if executor is not None:
        node_executor = executor
    elif _is_research_graph(request):
        node_executor = ResearchFlowExecutor(request, search_provider=search_provider)
    elif _is_planned_task_graph(request):
        node_executor = PlannedTaskExecutor(
            request,
            model_client=model_client,
            tool_executor=tool_executor,
        )
    else:
        node_executor = DocumentFlowExecutor(
            request,
            model_client=model_client,
            tool_executor=tool_executor,
        )
    verifier = result_verifier or ResultVerifier()
    run_registry = registry or DEFAULT_RUN_REGISTRY
    cancel_token = run_registry.start(request.run_id)
    journal = RunJournal(project_path=request.project_path, run_id=request.run_id)
    outputs: dict[str, NodeOutput] = {}
    outputs.update(_source_outputs_for_mode(request))

    started_at = _now_iso()
    disabled_tool_ids = set(request.disabled_tool_ids)
    journal.write_run(
        {
            "runId": request.run_id,
            "taskId": request.task_id,
            "status": "running",
            "startedAt": started_at,
            "mode": request.mode.model_dump(),
        }
    )
    yield AgentEvent(
        type="run.started",
        payload={
            "runId": request.run_id,
            "taskId": request.task_id,
            "startedAt": started_at,
        },
    )

    try:
        permission_node = _permission_blocking_node(selected_nodes)
        if permission_node is not None:
            completed_at = _now_iso()
            error = HarnessError(
                "permission_required",
                (
                    "temporary script requires approval before execution: "
                    f"{permission_node.nodeId}"
                ),
            )
            payload = harness_error_payload(error)
            review_payload = _script_review_event_payload(permission_node)
            journal.write_node(
                permission_node.nodeId,
                {
                    "nodeRunId": f"{request.run_id}-{permission_node.nodeId}",
                    "runId": request.run_id,
                    "nodeId": permission_node.nodeId,
                    "status": "needs_permission",
                    "startedAt": completed_at,
                    "completedAt": completed_at,
                    "artifactRefs": [],
                    "error": str(error),
                    "errorCode": payload.get("errorCode"),
                    "values": {},
                    "scriptReview": review_payload,
                },
            )
            journal.write_run(
                {
                    "runId": request.run_id,
                    "taskId": request.task_id,
                    "status": "failed",
                    "startedAt": started_at,
                    "completedAt": completed_at,
                    "mode": request.mode.model_dump(),
                }
            )
            yield AgentEvent(
                type="node.needs_permission",
                payload={
                    "nodeId": permission_node.nodeId,
                    "taskId": request.task_id,
                    "runId": request.run_id,
                    "permissions": review_payload.get("permissions", []),
                    "scriptReview": review_payload,
                    **payload,
                },
            )
            yield AgentEvent(
                type="task.failed",
                payload={
                    "taskId": request.task_id,
                    "runId": request.run_id,
                    **payload,
                },
            )
            return

        if _is_planned_task_graph(request) and not _is_research_graph(request):
            selected_nodes = [
                node for node in selected_nodes if is_executable_node(node)
            ]
        for node in selected_nodes:
            if node.toolRef and node.toolRef in disabled_tool_ids:
                completed_at = _now_iso()
                error = HarnessError("tool_disabled", f"tool disabled: {node.toolRef}")
                payload = harness_error_payload(error)
                record = {
                    "nodeRunId": f"{request.run_id}-{node.nodeId}",
                    "runId": request.run_id,
                    "nodeId": node.nodeId,
                    "status": "failed",
                    "startedAt": completed_at,
                    "completedAt": completed_at,
                    "artifactRefs": [],
                    "error": str(error),
                    "errorCode": payload.get("errorCode"),
                    "values": {},
                }
                journal.write_node(node.nodeId, record)
                journal.write_run(
                    {
                        "runId": request.run_id,
                        "taskId": request.task_id,
                        "status": "failed",
                        "startedAt": started_at,
                        "completedAt": completed_at,
                        "mode": request.mode.model_dump(),
                    }
                )
                yield AgentEvent(
                    type="node.failed",
                    payload={
                        "nodeId": node.nodeId,
                        "taskId": request.task_id,
                        "runId": request.run_id,
                        **payload,
                    },
                )
                yield AgentEvent(
                    type="node.run_recorded",
                    payload={"record": _event_record(record)},
                )
                yield AgentEvent(
                    type="task.failed",
                    payload={
                        "taskId": request.task_id,
                        "runId": request.run_id,
                        **payload,
                    },
                )
                return

            if cancel_token.cancelled:
                completed_at = _now_iso()
                journal.write_run(
                    {
                        "runId": request.run_id,
                        "taskId": request.task_id,
                        "status": "cancelled",
                        "startedAt": started_at,
                        "completedAt": completed_at,
                        "mode": request.mode.model_dump(),
                    }
                )
                yield AgentEvent(
                    type="run.cancelled",
                    payload={
                        "runId": request.run_id,
                        "taskId": request.task_id,
                        "completedAt": completed_at,
                    },
                )
                return

            node_started_at = _now_iso()
            node_run_id = f"{request.run_id}-{node.nodeId}"
            journal.write_node(
                node.nodeId,
                {
                    "nodeRunId": node_run_id,
                    "runId": request.run_id,
                    "nodeId": node.nodeId,
                    "status": "running",
                    "startedAt": node_started_at,
                    "artifactRefs": [],
                    "values": {},
                },
            )
            yield AgentEvent(type="node.running", payload={"nodeId": node.nodeId})
            node_perf_started = perf_counter()
            try:
                dependency_outputs = {
                    dependency: outputs[dependency]
                    for dependency in node.dependencies
                    if dependency in outputs
                }
                if node.nodeId in outputs:
                    dependency_outputs[node.nodeId] = outputs[node.nodeId]
                output = node_executor.run(node.nodeId, dependency_outputs)
                verifier.verify(node.nodeId, output)
            except Exception as error:
                completed_at = _now_iso()
                payload = harness_error_payload(error)
                partial_output = (
                    error.output
                    if isinstance(error, PartialNodeOutputError)
                    else NodeOutput()
                )
                record = {
                    "nodeRunId": node_run_id,
                    "runId": request.run_id,
                    "nodeId": node.nodeId,
                    "status": "failed",
                    "startedAt": node_started_at,
                    "completedAt": completed_at,
                    "artifactRefs": partial_output.artifacts,
                    "error": str(error),
                    "errorCode": payload.get("errorCode"),
                    "values": partial_output.values,
                }
                journal.write_node(node.nodeId, record)
                journal.write_run(
                    {
                        "runId": request.run_id,
                        "taskId": request.task_id,
                        "status": "failed",
                        "startedAt": started_at,
                        "completedAt": completed_at,
                        "mode": request.mode.model_dump(),
                    }
                )
                yield AgentEvent(
                    type="node.failed",
                    payload={
                        "nodeId": node.nodeId,
                        "taskId": request.task_id,
                        "runId": request.run_id,
                        **payload,
                    },
                )
                yield AgentEvent(
                    type="node.run_recorded",
                    payload={"record": _event_record(record)},
                )
                yield AgentEvent(
                    type="task.failed",
                    payload={
                        "taskId": request.task_id,
                        "runId": request.run_id,
                        **payload,
                    },
                )
                return

            completed_at = _now_iso()
            actual_duration_ms = int((perf_counter() - node_perf_started) * 1000)
            outputs[node.nodeId] = output
            runtime_notice = _runtime_notice_for_node(node, actual_duration_ms)
            record = {
                "nodeRunId": node_run_id,
                "runId": request.run_id,
                "nodeId": node.nodeId,
                "status": "completed",
                "startedAt": node_started_at,
                "completedAt": completed_at,
                "artifactRefs": output.artifacts,
                "values": output.values,
            }
            if runtime_notice is not None:
                record["runtimeNotice"] = runtime_notice
            journal.write_node(node.nodeId, record)
            yield AgentEvent(
                type="node.completed",
                payload={"nodeId": node.nodeId, "artifactRefs": output.artifacts},
            )
            if runtime_notice is not None:
                yield AgentEvent(
                    type="node.runtime_notice",
                    payload={
                        "nodeId": node.nodeId,
                        "notice": runtime_notice,
                    },
                )
            yield AgentEvent(
                type="node.run_recorded",
                payload={"record": _event_record(record)},
            )
            for artifact_path in output.artifacts:
                yield AgentEvent(
                    type="artifact.created",
                    payload={
                        "artifactId": Path(artifact_path).stem,
                        "path": artifact_path,
                        "sourceNodeId": node.nodeId,
                        "createdAt": completed_at,
                    },
                )

        completed_at = _now_iso()
        if _is_research_graph(request):
            final_output = outputs.get("research-markdown-output")
            if final_output is not None:
                report_artifact_path = str(final_output.values.get("artifact", ""))
                yield AgentEvent(
                    type="research.completed",
                    payload={
                        "taskId": request.task_id,
                        "runId": request.run_id,
                        "reportArtifactId": (
                            Path(report_artifact_path).stem
                            if report_artifact_path
                            else ""
                        ),
                        "reportArtifactPath": report_artifact_path,
                        "summary": final_output.values.get("summary", ""),
                        "acceptedSources": final_output.values.get(
                            "acceptedSources", []
                        ),
                        "rejectedSources": final_output.values.get(
                            "rejectedSources", []
                        ),
                    },
                )
        journal.write_run(
            {
                "runId": request.run_id,
                "taskId": request.task_id,
                "status": "completed",
                "startedAt": started_at,
                "completedAt": completed_at,
                "mode": request.mode.model_dump(),
            }
        )
        yield AgentEvent(
            type="task.completed",
            payload={"taskId": request.task_id, "runId": request.run_id},
        )
    finally:
        run_registry.finish(request.run_id)


def _topological_nodes(request: RunGraphRequest) -> list[GraphNode]:
    node_ids = {node.nodeId for node in request.graph.nodes}
    for node in request.graph.nodes:
        for dependency in node.dependencies:
            if dependency not in node_ids:
                raise ValueError(f"节点 {node.nodeId} 依赖不存在: {dependency}")

    ordered: list[GraphNode] = []
    completed: set[str] = set()

    while len(ordered) < len(request.graph.nodes):
        ready = [
            node
            for node in request.graph.nodes
            if node.nodeId not in completed
            and all(dependency in completed for dependency in node.dependencies)
        ]
        if not ready:
            raise ValueError("节点流程存在循环依赖或不可满足依赖")

        for node in ready:
            ordered.append(node)
            completed.add(node.nodeId)

    return ordered


def is_executable_node(node: GraphNode) -> bool:
    if node.nodeType == "planning":
        return False
    if node.nodeType not in {"fixed_tool", "model", "temporary_script", "output"}:
        return False
    if node.status in {"completed", "needs_permission", "needs_user_input", "skipped"}:
        return False
    if node.nodeType == "temporary_script" and _script_requires_permission(node):
        return False
    return True


def _permission_blocking_node(nodes: list[GraphNode]) -> GraphNode | None:
    for node in nodes:
        should_check = _should_check_permission_before_run(node)
        if should_check and _script_requires_permission(node):
            return node
    return None


def _should_check_permission_before_run(node: GraphNode) -> bool:
    return node.status not in {"completed", "needs_user_input", "skipped"}


def _script_requires_permission(node: GraphNode) -> bool:
    if node.nodeType != "temporary_script":
        return False
    review = node.scriptReview
    if review is not None and _has_valid_script_approval(review):
        return False
    if node.status == "needs_permission":
        return True
    if review is None:
        return False
    return review.riskLevel == "high" or review.requiresApproval


def _has_valid_script_approval(review: ScriptReviewState) -> bool:
    return (
        review.status == "approved"
        and review.approvalFingerprint == _script_review_fingerprint(review)
    )


def _script_review_event_payload(node: GraphNode) -> dict:
    review = node.scriptReview
    if review is None:
        return {}
    payload = review.model_dump()
    if review.status == "approved" and not _has_valid_script_approval(review):
        payload["status"] = "not_reviewed"
        payload["approvalFingerprint"] = None
    return payload


def _script_review_fingerprint(review: ScriptReviewState) -> str:
    payload = {
        "codePreview": review.codePreview,
        "permissions": review.permissions,
        "riskLevel": review.riskLevel,
        "inputContract": review.inputContract,
        "outputContract": review.outputContract,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _default_tool_registry() -> ToolRegistry:
    return ToolRegistry.from_packages_root(default_tool_packages_root())


def _validate_graph_tools(request: RunGraphRequest, registry: ToolRegistry) -> None:
    for node in request.graph.nodes:
        if node.nodeType != "fixed_tool" or not node.toolRef:
            continue
        if _is_research_graph(request) and node.toolRef == "web.search.parallel":
            continue
        try:
            registry.get(node.toolRef)
        except KeyError as error:
            raise HarnessError("unsupported_tool", str(error)) from error


def _is_research_graph(request: RunGraphRequest) -> bool:
    if request.graph.metadata.get("kind") == "research":
        return True
    graph_id = request.graph.graphId
    return "research-graph" in graph_id or any(
        node.nodeId.startswith("research-") for node in request.graph.nodes
    )


def _is_planned_task_graph(request: RunGraphRequest) -> bool:
    if request.graph.metadata.get("taskKind"):
        return True
    return any(node.nodeType == "planning" for node in request.graph.nodes)


def _selected_nodes_for_mode(
    request: RunGraphRequest,
    ordered_nodes: list[GraphNode],
) -> list[GraphNode]:
    if request.mode.type == "full":
        return ordered_nodes

    downstream = _downstream_node_ids(request)

    if request.mode.type == "from_node" and request.mode.node_id:
        selected = {request.mode.node_id, *downstream.get(request.mode.node_id, set())}
        return [node for node in ordered_nodes if node.nodeId in selected]

    if request.mode.type == "failed_only" and request.mode.source_run_id:
        failed = _failed_node_ids_from_journal(request)
        selected = set(failed)
        for node_id in failed:
            selected.update(downstream.get(node_id, set()))
        return [node for node in ordered_nodes if node.nodeId in selected]

    return ordered_nodes


def _downstream_node_ids(request: RunGraphRequest) -> dict[str, set[str]]:
    direct: dict[str, set[str]] = {node.nodeId: set() for node in request.graph.nodes}
    for edge in request.graph.edges:
        direct.setdefault(edge.source, set()).add(edge.target)
    for node in request.graph.nodes:
        for dependency in node.dependencies:
            direct.setdefault(dependency, set()).add(node.nodeId)

    downstream: dict[str, set[str]] = {node.nodeId: set() for node in request.graph.nodes}
    for node_id in downstream:
        pending = list(direct.get(node_id, set()))
        while pending:
            child = pending.pop()
            if child in downstream[node_id]:
                continue
            downstream[node_id].add(child)
            pending.extend(direct.get(child, set()))
    return downstream


def _failed_node_ids_from_journal(request: RunGraphRequest) -> list[str]:
    if not request.mode.source_run_id:
        return []
    journal = RunJournal(
        project_path=request.project_path,
        run_id=request.mode.source_run_id,
    )
    return [
        record["nodeId"]
        for record in journal.read_nodes()
        if record.get("status") == "failed" and "nodeId" in record
    ]


def _source_outputs_for_mode(request: RunGraphRequest) -> dict[str, NodeOutput]:
    if request.mode.type == "full" or not request.mode.source_run_id:
        return {}

    journal = RunJournal(
        project_path=request.project_path,
        run_id=request.mode.source_run_id,
    )
    outputs: dict[str, NodeOutput] = {}
    for record in journal.read_nodes():
        node_id = record.get("nodeId")
        if not isinstance(node_id, str):
            continue
        values = record.get("values")
        if not isinstance(values, dict):
            values = {}
        artifacts = record.get("artifactRefs")
        if not isinstance(artifacts, list):
            artifacts = []
        outputs[node_id] = NodeOutput(
            artifacts=[str(artifact) for artifact in artifacts],
            values={str(key): value for key, value in values.items()},
        )
    return outputs


def _first_input_value(inputs: dict[str, NodeOutput], key: str) -> str:
    for output in inputs.values():
        if key in output.values:
            return str(output.values[key])
    return ""


def _input_value(inputs: dict[str, NodeOutput], key: str) -> Any:
    for output in inputs.values():
        if key in output.values:
            return output.values[key]
    return None


def _unique_artifacts_from_inputs(inputs: dict[str, NodeOutput]) -> list[str]:
    artifacts: list[str] = []
    seen: set[str] = set()
    for output in inputs.values():
        for artifact in output.artifacts:
            if artifact in seen:
                continue
            artifacts.append(artifact)
            seen.add(artifact)
    return artifacts


def _event_record(record: dict) -> dict:
    return {
        "nodeRunId": record["nodeRunId"],
        "runId": record["runId"],
        "nodeId": record["nodeId"],
        "status": record["status"],
        "startedAt": record["startedAt"],
        "completedAt": record.get("completedAt"),
        "artifactRefs": record.get("artifactRefs", []),
        "error": record.get("error"),
        **({"errorCode": record["errorCode"]} if record.get("errorCode") else {}),
        **(
            {"runtimeNotice": record["runtimeNotice"]}
            if record.get("runtimeNotice")
            else {}
        ),
    }


def _runtime_notice_for_node(node: GraphNode, actual_duration_ms: int) -> dict | None:
    if node.estimate is None or node.estimate.durationMs is None:
        return None
    estimate_duration_ms = node.estimate.durationMs
    if actual_duration_ms <= estimate_duration_ms:
        return None
    return {
        "kind": "duration_exceeded",
        "message": (
            f"Node exceeded estimated duration: "
            f"{actual_duration_ms}ms actual vs {estimate_duration_ms}ms estimated."
        ),
        "actualDurationMs": actual_duration_ms,
    }


def _search_result_payload(
    result: SearchResult,
    *,
    query: str,
    purpose: str,
) -> dict[str, Any]:
    return {
        "title": result.title,
        "url": result.url,
        "snippet": result.snippet,
        "query": query,
        "purpose": purpose,
    }


def _search_failure_payload(query: str, failure: SearchFailure) -> dict[str, Any]:
    return {
        "query": query,
        "kind": failure.kind,
        "message": failure.message,
        "blocked": failure.blocked,
        "removedCategories": failure.removedCategories,
    }


def _synthesize_research_markdown(
    question: str,
    summary: str,
    accepted_sources: list[dict[str, Any]],
    rejected_sources: list[dict[str, Any]],
    section_order: list[str],
) -> str:
    section_renderers = {
        "summary": lambda: f"## Summary\n\n{summary}\n",
        "key_findings": lambda: _key_findings_section(accepted_sources),
        "source_review": lambda: _source_review_section(accepted_sources, rejected_sources),
        "open_questions": lambda: (
            "## Open Questions\n\n"
            "- Validate whether newer source material appeared after this run.\n"
        ),
        "references": lambda: _references_section(accepted_sources),
    }
    sections = [
        f"# Research Report\n\nQuestion: {question.strip()}\n",
    ]
    for section in section_order:
        renderer = section_renderers.get(section)
        if renderer is not None:
            sections.append(renderer())
    return "\n".join(sections).rstrip() + "\n"


def _key_findings_section(accepted_sources: list[dict[str, Any]]) -> str:
    lines = ["## Key Findings", ""]
    if not accepted_sources:
        lines.append("- No accepted sources were available for synthesis.")
    else:
        for source in accepted_sources:
            lines.append(
                f"- {source['title']}: {source.get('snippet') or 'No snippet available.'}"
            )
    return "\n".join(lines) + "\n"


def _source_review_section(
    accepted_sources: list[dict[str, Any]],
    rejected_sources: list[dict[str, Any]],
) -> str:
    lines = ["## Source Review", ""]
    lines.append(f"- Accepted sources: {len(accepted_sources)}")
    lines.append(f"- Rejected sources: {len(rejected_sources)}")
    for source in rejected_sources:
        lines.append(
            f"- Rejected {source['title']}: {source.get('rejectionReason') or 'not accepted'}"
        )
    return "\n".join(lines) + "\n"


def _references_section(accepted_sources: list[dict[str, Any]]) -> str:
    lines = ["## References", ""]
    if not accepted_sources:
        lines.append("- No accepted references.")
    else:
        for source in accepted_sources:
            ref = source.get("ref") or "-"
            lines.append(f"- {ref} {source['title']} - {source['url']}")
    return "\n".join(lines) + "\n"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
