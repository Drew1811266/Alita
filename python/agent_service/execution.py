from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from agent_service.agent_run_state import AgentRunState
from agent_service.final_verifier import FinalVerifier
from agent_service.goal_spec import GoalSpec
from agent_service.harness_errors import HarnessError, harness_error_payload
from agent_service.model_client import (
    ChatMessage as ModelChatMessage,
    LlamaCppModelClient,
)
from agent_service.model_policy import ModelCallPolicy, policy_for_graph_node
from agent_service.model_runtime import ModelRuntime
from agent_service.node_output import NodeOutput
from agent_service.permission_gate import PermissionGate
from agent_service.privacy import sanitize_for_web_search
from agent_service.replan import FailureReplanner
from agent_service.result_verifier import ResultVerifier
from agent_service.run_journal import RunJournal
from agent_service.run_registry import DEFAULT_RUN_REGISTRY, RunRegistry
from agent_service.schemas import (
    AgentEvent,
    GraphNode,
    RunGraphRequest,
    ScriptReviewState,
)
from agent_service.script_review import script_review_fingerprint
from agent_service.task_graph import build_document_task_graph
from agent_service.tool_execution import (
    ToolExecutor,
    default_tool_packages_root,
)
from agent_service.tool_gateway import (
    UnifiedToolGateway,
    default_unified_tool_gateway,
)
from agent_service.tool_providers.web_search import default_search_provider
from agent_service.tool_protocol import (
    UnifiedToolInvocation,
    UnifiedToolResult,
    equivalent_tool_ids,
    normalize_tool_id,
    provider_tool_id,
)
from agent_service.tool_registry import ToolRegistry
from agent_service.web_research import (
    REPORT_SECTION_ORDER,
    infer_question_type,
    source_payload,
)
from agent_service.web_search import (
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
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> str:
        ...


class SourceContentFetcher(Protocol):
    def fetch(self, url: str) -> str:
        ...


DOCUMENT_FLOW_NODE_IDS = {
    "document-input",
    "document-parse",
    "content-organize",
    "report-generate",
    "typst-export",
    "file-export",
}

DATA_DEPENDENT_NODE_IDS = {
    *DOCUMENT_FLOW_NODE_IDS.difference({"document-input"}),
    "research-privacy-guard",
    "research-query-plan",
    "research-parallel-search",
    "research-source-review",
    "research-source-reading",
    "research-report-synthesis",
    "research-report-quality-check",
    "research-markdown-output",
}
SUPPORTED_PLANNED_MODEL_REFS = {"local-task-reasoner"}
SOURCE_CONTENT_LIMIT = 4000


@dataclass(frozen=True)
class PartialNodeOutputError(HarnessError):
    output: NodeOutput = field(default_factory=NodeOutput)


class EmptyNodeExecutor:
    def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
        return NodeOutput(values={"text": node_id})


class UrlSourceContentFetcher:
    def __init__(self, *, timeout: float = 8.0, max_bytes: int = 250_000) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes

    def fetch(self, url: str) -> str:
        request = Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; alita-research/1.0)"},
        )
        with urlopen(request, timeout=self.timeout) as response:
            raw = response.read(self.max_bytes)
            content_type = response.headers.get("Content-Type", "")
            charset = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        if "html" in content_type.lower() or "<html" in text[:1000].lower():
            return _extract_text_from_html(text)
        return _normalize_source_text(text)


class DocumentFlowExecutor:
    def __init__(
        self,
        request: RunGraphRequest,
        *,
        run_state: AgentRunState | None = None,
        model_client: ModelClient | None = None,
        model_runtime: ModelRuntime | None = None,
        tool_gateway: UnifiedToolGateway | None = None,
        tool_executor: ToolExecutor | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.request = request
        self.run_state = run_state or AgentRunState.from_run_graph_request(request)
        self.model_client = model_client or LlamaCppModelClient()
        self.model_runtime = model_runtime or ModelRuntime(model_client=self.model_client)
        self.tool_registry = tool_registry or _default_tool_registry()
        self.tool_gateway = tool_gateway or _default_tool_gateway(
            tool_executor=tool_executor
        )
        self.nodes_by_id = {node.nodeId: node for node in request.graph.nodes}
        self.project_dir = Path(request.project_path).parent
        self.artifact_dir = self.project_dir / "artifacts"
        self.task_graph = build_document_task_graph(
            request.task_id,
            GoalSpec(
                goal="Process attached documents into a report artifact.",
                task_type="document_processing",
                deliverable="markdown_report",
                success_criteria=["Generate a local project artifact."],
                required_context=["attachment"],
                risk_level="local_write",
                permissions_required=["read_attachment", "write_project_artifact"],
                confidence=0.85,
            ),
        )

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
                output = self._call_tool(
                    "document-parse",
                    tool_id="document.markitdown_convert",
                    operation="convert_local_file",
                    arguments={
                        "input_path": attachment.path,
                        "output_path": str(output_path),
                    },
                )
                text = str(output.values.get("text", ""))
                if text:
                    texts.append(text)
                artifacts.extend(output.artifacts)
            return NodeOutput(artifacts=artifacts, values={"text": "\n\n".join(texts)})

        if node_id == "content-organize":
            node = self.task_graph.node_by_id(node_id)
            if node.model_binding is None:
                raise ValueError(f"{node_id} is missing model binding")
            return self.model_runtime.run(node.model_binding, inputs=inputs)

        if node_id == "report-generate":
            node = self.task_graph.node_by_id(node_id)
            if node.model_binding is None:
                raise ValueError(f"{node_id} is missing model binding")
            return self.model_runtime.run(node.model_binding, inputs=inputs)

        if node_id == "typst-export":
            outline = _first_input_value(inputs, "outline")
            report = _first_input_value(inputs, "report")
            output_stem = f"report-{uuid4().hex[:8]}"
            output = self._call_tool(
                "typst-export",
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
            )
            return output

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

    def _call_tool(
        self,
        node_id: str,
        *,
        tool_id: str,
        operation: str,
        arguments: dict[str, object],
    ) -> NodeOutput:
        node = self.nodes_by_id.get(node_id)
        permissions = (
            _required_permissions_for_tool_node(
                node,
                tool_registry=self.tool_registry,
            )
            if node is not None
            else []
        )
        result = self.tool_gateway.call_tool(
            UnifiedToolInvocation(
                invocation_id=(
                    f"{self.run_state.run_id or self.request.run_id}-"
                    f"{node_id}-{operation}"
                ),
                run_id=self.run_state.run_id or self.request.run_id,
                task_id=self.run_state.task_id,
                node_id=node_id,
                tool_id=normalize_tool_id(tool_id),
                arguments={"operation": operation, **arguments},
                project_path=self.run_state.project_path or self.request.project_path,
                allowed_roots=self._allowed_roots(),
                requested_permissions=permissions,
                model_session_id=self.run_state.message.model_session_id,
            )
        )
        return _node_output_from_unified_result(result)

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
        run_state: AgentRunState | None = None,
        model_client: ModelClient | None = None,
        tool_gateway: UnifiedToolGateway | None = None,
        tool_executor: ToolExecutor | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.request = request
        self.run_state = run_state or AgentRunState.from_run_graph_request(request)
        self.nodes_by_id = {node.nodeId: node for node in request.graph.nodes}
        self.model_client = model_client or LlamaCppModelClient()
        self.tool_registry = tool_registry or _default_tool_registry()
        self.tool_gateway = tool_gateway or _default_tool_gateway(
            tool_executor=tool_executor
        )
        self.document_executor = DocumentFlowExecutor(
            request,
            run_state=self.run_state,
            model_client=model_client,
            tool_gateway=self.tool_gateway,
            tool_executor=tool_executor,
            tool_registry=self.tool_registry,
        )

    def _call_tool(
        self,
        node: GraphNode,
        *,
        operation: str,
        arguments: dict[str, object],
    ) -> NodeOutput:
        if not node.toolRef:
            raise HarnessError(
                "unsupported_runtime",
                f"tool node {node.nodeId} has no bound runtime: <missing>",
            )
        result = self.tool_gateway.call_tool(
            UnifiedToolInvocation(
                invocation_id=(
                    f"{self.run_state.run_id or self.request.run_id}-"
                    f"{node.nodeId}-{operation}"
                ),
                run_id=self.run_state.run_id or self.request.run_id,
                task_id=self.run_state.task_id,
                node_id=node.nodeId,
                tool_id=normalize_tool_id(node.toolRef),
                arguments={"operation": operation, **arguments},
                project_path=self.run_state.project_path or self.request.project_path,
                allowed_roots=self.document_executor._allowed_roots(),
                requested_permissions=_required_permissions_for_tool_node(
                    node,
                    tool_registry=self.tool_registry,
                ),
                model_session_id=self.run_state.message.model_session_id,
            )
        )
        return _node_output_from_unified_result(result)

    def _run_fixed_tool_node(
        self,
        node: GraphNode,
        inputs: dict[str, NodeOutput],
    ) -> NodeOutput:
        tool_id = provider_tool_id(node.toolRef or "")

        if tool_id == "document.receive_attachment":
            if not self.request.attachments:
                raise HarnessError(
                    "missing_input",
                    f"tool node {node.nodeId} requires at least one attachment",
                )
            return NodeOutput(
                values={
                    "paths": "\n".join(
                        attachment.path for attachment in self.request.attachments
                    )
                }
            )

        if tool_id == "document.markitdown_convert":
            if not self.request.attachments:
                raise HarnessError(
                    "missing_input",
                    f"tool node {node.nodeId} requires at least one attachment",
                )
            texts: list[str] = []
            artifacts: list[str] = []
            for index, attachment in enumerate(self.request.attachments):
                input_path = Path(attachment.path)
                output_path = self.document_executor._converted_output_path(
                    index,
                    input_path,
                )
                output = self._call_tool(
                    node,
                    operation="convert_local_file",
                    arguments={
                        "input_path": attachment.path,
                        "output_path": str(output_path),
                    },
                )
                text = str(output.values.get("text", ""))
                if text:
                    texts.append(text)
                artifacts.extend(output.artifacts)
            return NodeOutput(
                artifacts=artifacts,
                values={"text": "\n\n".join(texts)},
            )

        if tool_id == "document.typst_compile":
            outline = _first_input_value(inputs, "outline")
            report = _first_input_value(inputs, "report")
            output_stem = f"report-{uuid4().hex[:8]}"
            return self._call_tool(
                node,
                operation="compile_report_pdf",
                arguments={
                    "title": Path(self.request.project_path).stem or "Alita Report",
                    "outline": outline,
                    "report": report,
                    "source_output_path": str(
                        self.document_executor.artifact_dir
                        / "typst"
                        / f"{output_stem}.typ"
                    ),
                    "pdf_output_path": str(
                        self.document_executor.artifact_dir
                        / "typst"
                        / f"{output_stem}.pdf"
                    ),
                },
            )

        raise HarnessError(
            "unsupported_runtime",
            f"tool node {node.nodeId} has no bound runtime: {node.toolRef or '<missing>'}",
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
            if node.modelRef not in SUPPORTED_PLANNED_MODEL_REFS:
                raise HarnessError(
                    "unsupported_runtime",
                    f"model node {node_id} has no bound runtime: {node.modelRef or '<missing>'}",
                )
            content = self.model_client.chat(
                [
                    ModelChatMessage(
                        role="system",
                        content=(
                            "Execute the planned model step. Return only the useful "
                            "task result, not a description of the plan."
                        ),
                    ),
                    ModelChatMessage(
                        role="user",
                        content=_planned_model_prompt(node, inputs),
                    ),
                ],
                temperature=0.2,
                max_tokens=1536,
                policy=policy_for_graph_node(
                    node,
                    graph_metadata=self.request.graph.metadata,
                ),
            )
            return NodeOutput(
                values={
                    "mode": "planned_task",
                    "nodeType": node.nodeType,
                    "summary": node.summary,
                    "modelRef": node.modelRef or "",
                    "text": content,
                }
            )

        if node.nodeType == "fixed_tool":
            return self._run_fixed_tool_node(node, inputs)

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
        source_fetcher: SourceContentFetcher | None = None,
        max_search_attempts: int = 3,
    ) -> None:
        self.request = request
        self.search_provider = search_provider or default_search_provider()
        self.source_fetcher = source_fetcher or UrlSourceContentFetcher()
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
            queries = _research_queries_for_question(sanitized_question)
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

        if node_id == "research-source-reading":
            accepted_sources = [
                dict(source)
                for source in (_input_value(inputs, "acceptedSources") or [])
            ]
            rejected_sources = [
                dict(source)
                for source in (_input_value(inputs, "rejectedSources") or [])
            ]
            enriched_sources: list[dict[str, Any]] = []
            source_contents: list[dict[str, Any]] = []
            failed_reads: list[dict[str, str]] = []

            for source in accepted_sources:
                url = str(source.get("url") or "")
                content = ""
                status = "skipped"
                error_message = ""
                if url:
                    try:
                        content = _truncate_source_content(
                            self.source_fetcher.fetch(url)
                        )
                        status = "read" if content else "empty"
                    except (HTTPError, URLError, TimeoutError, socket.timeout, OSError) as error:
                        status = "failed"
                        error_message = str(error)
                    except Exception as error:
                        status = "failed"
                        error_message = str(error)

                enriched = {
                    **source,
                    "sourceContent": content,
                    "readStatus": status,
                    "contentChars": len(content),
                }
                if error_message:
                    enriched["readError"] = error_message
                    failed_reads.append(
                        {
                            "ref": str(source.get("ref") or ""),
                            "url": url,
                            "error": error_message,
                        }
                    )
                enriched_sources.append(enriched)
                source_contents.append(
                    {
                        "ref": str(source.get("ref") or ""),
                        "title": str(source.get("title") or ""),
                        "url": url,
                        "status": status,
                        "content": content,
                    }
                )

            return NodeOutput(
                values={
                    "acceptedSources": enriched_sources,
                    "rejectedSources": rejected_sources,
                    "sourceContents": source_contents,
                    "readSourceCount": sum(
                        1 for source in enriched_sources
                        if source.get("readStatus") == "read"
                    ),
                    "failedSourceReads": failed_reads,
                }
            )

        if node_id == "research-report-synthesis":
            accepted_sources = list(_input_value(inputs, "acceptedSources") or [])
            rejected_sources = list(_input_value(inputs, "rejectedSources") or [])
            failed_source_reads = list(_input_value(inputs, "failedSourceReads") or [])
            read_source_count = int(_input_value(inputs, "readSourceCount") or 0)
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
                    "readSourceCount": read_source_count,
                    "failedSourceReads": failed_source_reads,
                    "sectionOrder": self._section_order(),
                }
            )

        if node_id == "research-report-quality-check":
            markdown = str(_input_value(inputs, "markdown") or "")
            accepted_sources = list(_input_value(inputs, "acceptedSources") or [])
            rejected_sources = list(_input_value(inputs, "rejectedSources") or [])
            failed_source_reads = list(_input_value(inputs, "failedSourceReads") or [])
            issues = _research_quality_issues(markdown, accepted_sources)
            return NodeOutput(
                values={
                    "markdown": markdown,
                    "summary": _input_value(inputs, "summary") or "",
                    "acceptedSources": accepted_sources,
                    "rejectedSources": rejected_sources,
                    "readSourceCount": _input_value(inputs, "readSourceCount") or 0,
                    "failedSourceReads": failed_source_reads,
                    "qualityStatus": "passed" if not issues else "needs_review",
                    "qualityIssues": issues,
                    "checkedReferenceCount": len(accepted_sources),
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
                    "readSourceCount": _input_value(inputs, "readSourceCount") or 0,
                    "failedSourceReads": _input_value(inputs, "failedSourceReads") or [],
                    "qualityStatus": _input_value(inputs, "qualityStatus") or "",
                    "qualityIssues": _input_value(inputs, "qualityIssues") or [],
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
    run_state: AgentRunState | None = None,
    executor: NodeExecutor | None = None,
    model_client: ModelClient | None = None,
    tool_gateway: UnifiedToolGateway | None = None,
    tool_executor: ToolExecutor | None = None,
    search_provider: SearchProvider | None = None,
    source_fetcher: SourceContentFetcher | None = None,
    registry: RunRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
    permission_gate: PermissionGate | None = None,
    result_verifier: ResultVerifier | None = None,
    final_verifier: FinalVerifier | None = None,
    failure_replanner: FailureReplanner | None = None,
) -> Iterator[AgentEvent]:
    run_state = run_state or AgentRunState.from_run_graph_request(request)
    mismatch = _run_state_mismatch(request, run_state)
    if mismatch is not None:
        yield AgentEvent(
            type="task.failed",
            payload={
                "taskId": request.task_id,
                "runId": request.run_id,
                "error": {
                    "code": "run_state_mismatch",
                    "message": mismatch,
                },
            },
        )
        return

    replanner = failure_replanner or FailureReplanner()
    try:
        ordered_nodes = _topological_nodes(request)
        effective_tool_registry = tool_registry or _default_tool_registry()
        effective_tool_gateway = tool_gateway or _default_tool_gateway(
            tool_executor=tool_executor
        )
        _validate_graph_tools(request, effective_tool_registry)
    except (ValueError, HarnessError) as error:
        payload = harness_error_payload(error)
        failed_node = _unsupported_tool_node(request, error)
        suggestion = replanner.propose(
            request=request,
            failed_node=failed_node,
            error=error,
        )
        if suggestion is not None:
            yield AgentEvent(
                type="graph.patch_suggested",
                payload=suggestion.model_dump(),
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

    selected_nodes = _selected_nodes_for_mode(request, ordered_nodes)
    if _is_planned_task_graph(request) and not _is_research_graph(request):
        selected_nodes = [
            node for node in selected_nodes if node.nodeType != "planning"
        ]
    if executor is not None:
        node_executor = executor
    elif _is_research_graph(request):
        node_executor = ResearchFlowExecutor(
            request,
            search_provider=search_provider,
            source_fetcher=source_fetcher,
        )
    elif _is_planned_task_graph(request):
        node_executor = PlannedTaskExecutor(
            request,
            run_state=run_state,
            model_client=model_client,
            tool_gateway=effective_tool_gateway,
            tool_executor=tool_executor,
            tool_registry=effective_tool_registry,
        )
    else:
        node_executor = DocumentFlowExecutor(
            request,
            run_state=run_state,
            model_client=model_client,
            tool_gateway=effective_tool_gateway,
            tool_executor=tool_executor,
            tool_registry=effective_tool_registry,
        )
    verifier = result_verifier or ResultVerifier()
    graph_verifier = final_verifier or FinalVerifier()
    run_registry = registry or DEFAULT_RUN_REGISTRY
    cancel_token = run_registry.start(request.run_id)
    journal = RunJournal(project_path=request.project_path, run_id=request.run_id)
    outputs: dict[str, NodeOutput] = {}
    outputs.update(_source_outputs_for_mode(request))

    started_at = _now_iso()
    disabled_tool_ids = _expanded_tool_ids(request.disabled_tool_ids)
    gate = permission_gate or PermissionGate(
        approved_permissions=request.approved_permissions
    )
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
            if node.toolRef and equivalent_tool_ids(node.toolRef) & disabled_tool_ids:
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
                suggestion = replanner.propose(
                    request=request,
                    failed_node=node,
                    error=error,
                )
                if suggestion is not None:
                    yield AgentEvent(
                        type="graph.patch_suggested",
                        payload=suggestion.model_dump(),
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

            denied_permissions = gate.denied_permissions(
                node,
                tool_registry=effective_tool_registry,
            )
            if denied_permissions:
                completed_at = _now_iso()
                error = HarnessError(
                    "permission_required",
                    (
                        f"node {node.nodeId} requires permission approval: "
                        f"{', '.join(denied_permissions)}"
                    ),
                )
                payload = harness_error_payload(error)
                record = {
                    "nodeRunId": f"{request.run_id}-{node.nodeId}",
                    "runId": request.run_id,
                    "nodeId": node.nodeId,
                    "status": "needs_permission",
                    "startedAt": completed_at,
                    "completedAt": completed_at,
                    "artifactRefs": [],
                    "error": str(error),
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
                    type="permission.required",
                    payload={
                        "nodeId": node.nodeId,
                        "taskId": request.task_id,
                        "runId": request.run_id,
                        "permissions": denied_permissions,
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
                missing_dependencies = _missing_required_dependency_outputs(
                    node,
                    request.graph.nodes,
                    outputs,
                )
                if missing_dependencies:
                    raise HarnessError(
                        "missing_dependency_output",
                        (
                            f"node {node.nodeId} is missing dependency output(s): "
                            + ", ".join(missing_dependencies)
                        ),
                    )
                dependency_outputs = {
                    dependency: outputs[dependency]
                    for dependency in node.dependencies
                    if dependency in outputs
                }
                if node.nodeId in outputs:
                    dependency_outputs[node.nodeId] = outputs[node.nodeId]
                unsatisfied_ports = _unsatisfied_input_ports(node, dependency_outputs)
                if unsatisfied_ports:
                    raise HarnessError(
                        "input_contract_unsatisfied",
                        (
                            f"node {node.nodeId} input port(s) are not satisfied: "
                            + ", ".join(unsatisfied_ports)
                        ),
                    )
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
                suggestion = replanner.propose(
                    request=request,
                    failed_node=node,
                    error=error,
                )
                if suggestion is not None:
                    yield AgentEvent(
                        type="graph.patch_suggested",
                        payload=suggestion.model_dump(),
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

        try:
            graph_verifier.verify(request, outputs=outputs)
        except Exception as error:
            completed_at = _now_iso()
            payload = harness_error_payload(error)
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
            output_node = _final_failure_output_node(request, outputs, error)
            suggestion = replanner.propose(
                request=request,
                failed_node=output_node,
                error=error,
            )
            if suggestion is not None:
                yield AgentEvent(
                    type="graph.patch_suggested",
                    payload=suggestion.model_dump(),
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
                        "readSourceCount": final_output.values.get(
                            "readSourceCount", 0
                        ),
                        "failedSourceReads": final_output.values.get(
                            "failedSourceReads", []
                        ),
                        "qualityStatus": final_output.values.get("qualityStatus", ""),
                        "qualityIssues": final_output.values.get("qualityIssues", []),
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


def _run_state_mismatch(
    request: RunGraphRequest,
    run_state: AgentRunState,
) -> str | None:
    if run_state.task_id != request.task_id:
        return (
            "AgentRunState task_id does not match RunGraphRequest task_id: "
            f"{run_state.task_id} != {request.task_id}"
        )
    if run_state.run_id != request.run_id:
        return (
            "AgentRunState run_id does not match RunGraphRequest run_id: "
            f"{run_state.run_id} != {request.run_id}"
        )
    return None


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


def _missing_required_dependency_outputs(
    node: GraphNode,
    graph_nodes: list[GraphNode],
    outputs: dict[str, NodeOutput],
) -> list[str]:
    if node.nodeId not in DATA_DEPENDENT_NODE_IDS:
        return []

    nodes_by_id = {candidate.nodeId: candidate for candidate in graph_nodes}
    missing: list[str] = []
    for dependency in node.dependencies:
        dependency_node = nodes_by_id.get(dependency)
        if dependency_node is not None and dependency_node.nodeType == "planning":
            continue
        if dependency not in outputs:
            missing.append(dependency)
    return missing


def _unsatisfied_input_ports(
    node: GraphNode,
    dependency_outputs: dict[str, NodeOutput],
) -> list[str]:
    if not node.inputPorts:
        return []

    unsatisfied: list[str] = []
    for port in node.inputPorts:
        port_id = str(port.get("id") or "<unnamed>")
        data_type = str(port.get("dataType") or "").lower()
        if not data_type:
            continue
        if not any(
            _node_output_satisfies_data_type(output, data_type)
            for output in dependency_outputs.values()
        ):
            unsatisfied.append(port_id)
    return unsatisfied


def _node_output_satisfies_data_type(output: NodeOutput, data_type: str) -> bool:
    if data_type in {"artifact", "file"}:
        return bool(output.artifacts) or _has_nonempty_value(output, {"artifact", "source"})
    if data_type == "document":
        return _has_nonempty_value(output, {"paths", "path"}) or bool(output.artifacts)
    if data_type in {"text", "markdown"}:
        return _has_nonempty_value(
            output,
            {"text", "markdown", "report", "summary"},
        )
    if data_type == "json":
        if _has_nonempty_value(output, {"outline", "queries", "results"}):
            return True
        return bool(output.values)
    return bool(output.values) or bool(output.artifacts)


def _has_nonempty_value(output: NodeOutput, keys: set[str]) -> bool:
    for key in keys:
        value = output.values.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (dict, list)) and value:
            return True
    return False


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
        and review.approvalFingerprint == script_review_fingerprint(review)
    )


def _script_review_event_payload(node: GraphNode) -> dict:
    review = node.scriptReview
    if review is None:
        return {}
    payload = review.model_dump()
    if review.status == "approved" and not _has_valid_script_approval(review):
        payload["status"] = "not_reviewed"
        payload["approvalFingerprint"] = None
    elif review.status != "approved":
        payload["approvalFingerprint"] = script_review_fingerprint(review)
    return payload


def _default_tool_registry() -> ToolRegistry:
    return ToolRegistry.from_packages_root(default_tool_packages_root())


def _default_tool_gateway(
    *,
    tool_executor: ToolExecutor | None = None,
) -> UnifiedToolGateway:
    return default_unified_tool_gateway(internal_executor=tool_executor)


def _node_output_from_unified_result(result: UnifiedToolResult) -> NodeOutput:
    if not result.ok:
        error = result.error
        raise HarnessError(
            error.code if error is not None else "tool_failed",
            error.message if error is not None else "tool failed",
        )
    return NodeOutput(
        values=dict(result.structured_content or {}),
        artifacts=list(result.artifacts),
    )


def _required_permissions_for_tool_node(
    node: GraphNode,
    *,
    tool_registry: ToolRegistry,
) -> list[str]:
    permissions = list(node.permissionsRequired)
    if node.toolRef:
        try:
            permissions.extend(tool_registry.get(provider_tool_id(node.toolRef)).permissions)
        except KeyError:
            pass
    return _dedupe(permissions)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _validate_graph_tools(request: RunGraphRequest, registry: ToolRegistry) -> None:
    for node in request.graph.nodes:
        if node.nodeType != "fixed_tool" or not node.toolRef:
            continue
        if _is_research_graph(request) and node.toolRef in {
            "web.search.parallel",
            "web.fetch.sources",
        }:
            continue
        registry_tool_id = provider_tool_id(node.toolRef)
        try:
            registry.get(registry_tool_id)
        except KeyError as error:
            raise HarnessError(
                "unsupported_tool",
                f"unsupported tool: {node.toolRef}",
            ) from error


def _unsupported_tool_node(
    request: RunGraphRequest,
    error: Exception,
) -> GraphNode | None:
    if not isinstance(error, HarnessError) or error.code != "unsupported_tool":
        return None

    prefix = "unsupported tool: "
    if not error.message.startswith(prefix):
        return None
    tool_ref = error.message.removeprefix(prefix).strip()
    if not tool_ref:
        return None
    return next(
        (
            node
            for node in request.graph.nodes
            if node.nodeType == "fixed_tool"
            and node.toolRef
            and equivalent_tool_ids(node.toolRef) & equivalent_tool_ids(tool_ref)
        ),
        None,
    )


def _expanded_tool_ids(tool_ids: list[str]) -> set[str]:
    expanded: set[str] = set()
    for tool_id in tool_ids:
        expanded.update(equivalent_tool_ids(tool_id))
    return expanded


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
        if not request.mode.source_run_id:
            selected.update(_upstream_node_ids(request).get(request.mode.node_id, set()))
        return [node for node in ordered_nodes if node.nodeId in selected]

    if request.mode.type == "failed_only" and request.mode.source_run_id:
        failed = _failed_node_ids_from_journal(request)
        selected = set(failed)
        for node_id in failed:
            selected.update(downstream.get(node_id, set()))
        return [node for node in ordered_nodes if node.nodeId in selected]

    return ordered_nodes


def _final_failure_output_node(
    request: RunGraphRequest,
    outputs: dict[str, NodeOutput],
    error: Exception,
) -> GraphNode | None:
    output_nodes = [node for node in request.graph.nodes if node.nodeType == "output"]
    if not output_nodes:
        return None

    if isinstance(error, HarnessError):
        if error.code == "missing_final_output":
            parsed_node_id = _missing_final_output_node_id(str(error))
            if parsed_node_id:
                parsed_node = _node_by_id(output_nodes, parsed_node_id)
                if parsed_node is not None:
                    return parsed_node
            return next(
                (node for node in output_nodes if node.nodeId not in outputs),
                output_nodes[0],
            )

        if error.code == "missing_artifact":
            artifact_path = _missing_artifact_path(str(error))
            if artifact_path:
                implicated_node = _output_node_for_artifact(
                    output_nodes,
                    outputs,
                    artifact_path,
                )
                if implicated_node is not None:
                    return implicated_node
            return (
                _output_node_with_invalid_artifact(output_nodes, outputs)
                or output_nodes[0]
            )

    return output_nodes[0]


def _missing_final_output_node_id(message: str) -> str | None:
    prefix = "missing final output for node: "
    if prefix not in message:
        return None
    return message.split(prefix, 1)[1].strip() or None


def _missing_artifact_path(message: str) -> Path | None:
    for prefix in ("final artifact is not listed: ", "artifact does not exist: "):
        if prefix in message:
            value = message.split(prefix, 1)[1].strip()
            return Path(value) if value else None
    return None


def _output_node_for_artifact(
    output_nodes: list[GraphNode],
    outputs: dict[str, NodeOutput],
    artifact_path: Path,
) -> GraphNode | None:
    target = artifact_path.expanduser().resolve(strict=False)
    for node in output_nodes:
        output = outputs.get(node.nodeId)
        if output is None:
            continue
        artifact_value = output.values.get("artifact")
        candidate_paths = [Path(path) for path in output.artifacts]
        if artifact_value:
            candidate_paths.append(Path(artifact_value))
        if any(
            path.expanduser().resolve(strict=False) == target
            for path in candidate_paths
        ):
            return node
    return None


def _output_node_with_invalid_artifact(
    output_nodes: list[GraphNode],
    outputs: dict[str, NodeOutput],
) -> GraphNode | None:
    for node in output_nodes:
        output = outputs.get(node.nodeId)
        if output is None:
            continue
        artifact_value = output.values.get("artifact", "")
        artifact_paths = {
            Path(path).expanduser().resolve(strict=False)
            for path in output.artifacts
        }
        if artifact_value:
            normalized_artifact = Path(artifact_value).expanduser().resolve(strict=False)
            if normalized_artifact not in artifact_paths:
                return node
        if any(not Path(path).is_file() for path in output.artifacts):
            return node
    return None


def _node_by_id(nodes: list[GraphNode], node_id: str) -> GraphNode | None:
    return next((node for node in nodes if node.nodeId == node_id), None)


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


def _upstream_node_ids(request: RunGraphRequest) -> dict[str, set[str]]:
    reverse: dict[str, set[str]] = {node.nodeId: set() for node in request.graph.nodes}
    for edge in request.graph.edges:
        reverse.setdefault(edge.target, set()).add(edge.source)
    for node in request.graph.nodes:
        for dependency in node.dependencies:
            reverse.setdefault(node.nodeId, set()).add(dependency)

    upstream: dict[str, set[str]] = {node.nodeId: set() for node in request.graph.nodes}
    for node_id in upstream:
        pending = list(reverse.get(node_id, set()))
        while pending:
            parent = pending.pop()
            if parent in upstream[node_id]:
                continue
            upstream[node_id].add(parent)
            pending.extend(reverse.get(parent, set()))
    return upstream


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
        values = record.get("values")
        has_partial_values = record.get("status") == "failed" and isinstance(
            values,
            dict,
        ) and bool(values)
        if record.get("status") != "completed" and not has_partial_values:
            continue
        node_id = record.get("nodeId")
        if not isinstance(node_id, str):
            continue
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


def _planned_model_prompt(node: GraphNode, inputs: dict[str, NodeOutput]) -> str:
    dependency_payload = {
        dependency: output.values for dependency, output in inputs.items()
    }
    return (
        f"Node: {node.displayName}\n"
        f"Goal: {node.summary}\n"
        f"Dependency outputs: {json.dumps(dependency_payload, ensure_ascii=False)}"
    )


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


def _research_queries_for_question(question: str) -> list[dict[str, str]]:
    normalized = question.lower()
    if "github" in normalized and any(
        marker in question for marker in ("热门", "趋势", "排行榜", "trending", "popular")
    ):
        return [
            {"query": question, "purpose": "primary"},
            {
                "query": "GitHub Trending repositories today",
                "purpose": "project_discovery",
            },
            {
                "query": "GitHub trending repositories developers daily",
                "purpose": "project_discovery",
            },
            {
                "query": "GitHub trending repositories official",
                "purpose": "official_sources",
            },
        ]

    return [
        {"query": question, "purpose": "primary"},
        {
            "query": f"{question} official sources",
            "purpose": "official_sources",
        },
    ]


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
        "project_summaries": lambda: _project_summaries_section(accepted_sources),
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
            ref = source.get("ref") or "[-]"
            lines.append(
                f"- {ref} {source['title']}: {source.get('snippet') or 'No snippet available.'}"
            )
    return "\n".join(lines) + "\n"


def _project_summaries_section(accepted_sources: list[dict[str, Any]]) -> str:
    lines = ["## Project Summaries", ""]
    if not accepted_sources:
        lines.append("- No accepted source content was available for project summaries.")
    else:
        for source in accepted_sources:
            ref = source.get("ref") or "[-]"
            excerpt = _source_excerpt(source)
            lines.append(f"- {ref} {source['title']}: {excerpt}")
    return "\n".join(lines) + "\n"


def _source_review_section(
    accepted_sources: list[dict[str, Any]],
    rejected_sources: list[dict[str, Any]],
) -> str:
    lines = ["## Source Review", ""]
    lines.append(f"- Accepted sources: {len(accepted_sources)}")
    lines.append(f"- Rejected sources: {len(rejected_sources)}")
    for source in accepted_sources:
        ref = source.get("ref") or "[-]"
        lines.append(f"- Accepted {ref} {source['title']}: {source.get('sourceType')}")
    for source in rejected_sources:
        ref = source.get("ref") or "[-]"
        lines.append(
            f"- Rejected {ref} {source['title']}: {source.get('rejectionReason') or 'not accepted'}"
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


def _source_excerpt(source: dict[str, Any]) -> str:
    content = str(source.get("sourceContent") or source.get("snippet") or "").strip()
    if not content:
        return "No readable source content was available."
    return _truncate_source_content(content, limit=700)


def _truncate_source_content(content: str, *, limit: int = SOURCE_CONTENT_LIMIT) -> str:
    normalized = _normalize_source_text(content)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _normalize_source_text(text: str) -> str:
    return " ".join(text.split())


def _extract_text_from_html(html: str) -> str:
    parser = _HtmlTextExtractor()
    parser.feed(html)
    parser.close()
    return _normalize_source_text(" ".join(parser.parts))


class _HtmlTextExtractor(HTMLParser):
    _SKIPPED_TAGS = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in self._SKIPPED_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = data.strip()
        if cleaned:
            self.parts.append(cleaned)


def _research_quality_issues(
    markdown: str,
    accepted_sources: list[dict[str, Any]],
) -> list[str]:
    issues: list[str] = []
    if not markdown.strip():
        issues.append("empty_report")
    if accepted_sources and "## References" not in markdown:
        issues.append("missing_references_section")

    missing_refs = [
        str(source.get("ref"))
        for source in accepted_sources
        if source.get("ref") and str(source.get("ref")) not in markdown
    ]
    if missing_refs:
        issues.append("missing_source_references:" + ",".join(missing_refs))

    if accepted_sources and not any(
        str(source.get("sourceContent") or "").strip()
        for source in accepted_sources
    ):
        issues.append("no_read_source_content")
    return issues


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
