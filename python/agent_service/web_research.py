from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

from agent_service.intent import RouteDecision
from agent_service.schemas import AgentEvent, UserMessage
from agent_service.web_search import (
    DuckDuckGoHtmlSearchProvider,
    SearchFailure,
    SearchProvider,
    SearchResult,
    classify_sources,
    rank_sources,
)


SNIPPET_LIMIT = 240
REPORT_SECTION_ORDER = [
    "summary",
    "key_findings",
    "source_review",
    "open_questions",
    "references",
]


class ResearchMode(str, Enum):
    QUICK_ANSWER = "quick_answer"
    RESEARCH_FLOW = "research_flow"


@dataclass(frozen=True)
class ResearchQuery:
    query: str
    purpose: str


@dataclass(frozen=True)
class ResearchPlan:
    mode: ResearchMode
    question: str
    queries: list[ResearchQuery]
    section_order: list[str] = field(default_factory=lambda: list(REPORT_SECTION_ORDER))


@dataclass(frozen=True)
class ResearchSourceSet:
    accepted: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ResearchReport:
    title: str
    mode: ResearchMode
    queries: list[ResearchQuery]
    source_set: ResearchSourceSet
    section_order: list[str] = field(default_factory=lambda: list(REPORT_SECTION_ORDER))
    markdown: str = ""


def build_research_graph(
    message: UserMessage,
    route_decision: RouteDecision | dict,
) -> dict:
    del route_decision
    graph_id = f"{message.task_id}-research-graph"
    nodes = [
        _node(
            node_id="research-intent-analysis",
            node_type="planning",
            display_name="Research intent analysis",
            status="completed",
            input_ports=[],
            output_ports=[_port("intent-output", "Research intent", "json")],
            dependencies=[],
            summary="Classifies the inquiry and confirms that a research flow is appropriate.",
            position={"x": 260, "y": 20},
            estimate=_estimate(180, "low", "low", "none"),
        ),
        _node(
            node_id="research-privacy-guard",
            node_type="planning",
            display_name="Privacy guard",
            status="waiting",
            input_ports=[_port("intent-input", "Research intent", "json")],
            output_ports=[_port("privacy-output", "Sanitized research scope", "json")],
            dependencies=["research-intent-analysis"],
            summary="Checks the research request before any web query is generated.",
            position={"x": 260, "y": 170},
            estimate=_estimate(150, "low", "low", "none"),
        ),
        _node(
            node_id="research-query-plan",
            node_type="planning",
            display_name="Query plan",
            status="waiting",
            input_ports=[_port("privacy-input", "Sanitized research scope", "json")],
            output_ports=[_port("queries-output", "Internal web queries", "json")],
            dependencies=["research-privacy-guard"],
            summary="Builds internal search queries and retry boundaries for the research node.",
            position={"x": 260, "y": 320},
            estimate=_estimate(250, "low", "low", "none"),
        ),
        _node(
            node_id="research-parallel-search",
            node_type="fixed_tool",
            display_name="Parallel web search",
            status="waiting",
            input_ports=[_port("queries-input", "Internal web queries", "json")],
            output_ports=[_port("search-results-output", "Search results", "json")],
            dependencies=["research-query-plan"],
            summary="Runs planned web queries in parallel internally while exposing one graph node.",
            position={"x": 260, "y": 480},
            tool_ref="web.search.parallel",
            estimate=_estimate(8000, "low", "medium", "required"),
            resource_usage={"cpu": "low", "memory": "medium", "network": "required"},
        ),
        _node(
            node_id="research-source-review",
            node_type="model",
            display_name="Source review",
            status="waiting",
            input_ports=[_port("search-results-input", "Search results", "json")],
            output_ports=[_port("source-set-output", "Accepted and rejected sources", "json")],
            dependencies=["research-parallel-search"],
            summary="Reviews search results and separates accepted sources from rejected ones.",
            position={"x": 90, "y": 650},
            model_ref="research-source-reviewer",
            estimate=_estimate(1200, "medium", "low", "none"),
        ),
        _node(
            node_id="research-report-synthesis",
            node_type="model",
            display_name="Report synthesis",
            status="waiting",
            input_ports=[_port("source-set-input", "Accepted and rejected sources", "json")],
            output_ports=[_port("report-output", "Research report", "text")],
            dependencies=["research-source-review"],
            summary="Synthesizes the reviewed sources into the confirmed report section order.",
            position={"x": 430, "y": 650},
            model_ref="research-report-synthesizer",
            estimate=_estimate(2500, "medium", "medium", "none"),
        ),
        _node(
            node_id="research-markdown-output",
            node_type="output",
            display_name="Markdown output",
            status="waiting",
            input_ports=[_port("report-input", "Research report", "text")],
            output_ports=[_port("markdown-output", "Markdown artifact", "artifact")],
            dependencies=["research-report-synthesis"],
            summary="Publishes the research report as Markdown.",
            position={"x": 260, "y": 820},
            estimate=_estimate(200, "low", "low", "none"),
        ),
    ]
    return {"graphId": graph_id, "nodes": nodes, "edges": _edges(nodes)}


def answer_simple_web_inquiry(
    message: UserMessage,
    route_decision: RouteDecision | dict,
    *,
    search_provider: SearchProvider | None = None,
) -> AgentEvent:
    del route_decision
    provider = search_provider or DuckDuckGoHtmlSearchProvider()
    response = provider.search(message.content.strip())
    question_type = _infer_question_type(message.content)
    classified = classify_sources(question_type, rank_sources(question_type, response.results))
    sources = [_source_payload(result, index + 1) for index, result in enumerate(classified)]
    accepted_sources = [source for source in sources if source["accepted"]]
    rejected_sources = [source for source in sources if not source["accepted"]]
    cited_sources = accepted_sources or sources[:3]

    content = _synthesize_answer(message.content, cited_sources, response.failure)
    return AgentEvent(
        type="message.created",
        payload={
            "message": _assistant_message(content),
            "sources": cited_sources,
            "rejectedSources": rejected_sources,
            "sourceMetadata": {
                "accepted": accepted_sources,
                "rejected": rejected_sources,
                "failure": _failure_payload(response.failure),
            },
        },
    )


def _synthesize_answer(
    question: str,
    sources: list[dict[str, Any]],
    failure: SearchFailure | None,
) -> str:
    if failure is not None and not sources:
        return f"I could not complete the web search: {failure.message}"
    if not sources:
        return "I could not find reliable web sources for this question."

    lines = [f"Based on the web results for: {question.strip()}"]
    for source in sources[:3]:
        snippet = source["snippet"]
        lines.append(f"{source['ref']} {source['title']}: {snippet}")
    lines.append("Sources are listed with each reference.")
    return "\n".join(lines)


def _source_payload(result: SearchResult, index: int) -> dict[str, Any]:
    return {
        "ref": f"[{index}]",
        "title": result.title,
        "url": result.url,
        "snippet": _truncate_snippet(result.snippet),
        "sourceType": result.sourceType,
        "accepted": bool(result.accepted),
        "rejectionReason": result.rejectionReason,
    }


def _truncate_snippet(snippet: str) -> str:
    normalized = " ".join(snippet.split())
    if len(normalized) <= SNIPPET_LIMIT:
        return normalized
    return normalized[: SNIPPET_LIMIT - 3].rstrip() + "..."


def _failure_payload(failure: SearchFailure | None) -> dict[str, Any] | None:
    if failure is None:
        return None
    return {
        "kind": failure.kind,
        "message": failure.message,
        "blocked": failure.blocked,
        "removedCategories": failure.removedCategories,
    }


def _infer_question_type(content: str) -> str:
    normalized = content.lower()
    if any(marker in normalized for marker in ("law", "policy", "regulation")):
        return "policy"
    if any(marker in normalized for marker in ("paper", "study", "research", "academic")):
        return "academic"
    if any(marker in normalized for marker in ("model", "llama", "gpt", "qwen")):
        return "model"
    if any(marker in normalized for marker in ("price", "buy", "product", "spec")):
        return "product"
    return "software"


def _assistant_message(content: str) -> dict[str, Any]:
    from datetime import datetime, timezone

    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "messageId": f"assistant-{uuid4()}",
        "role": "assistant",
        "content": content,
        "attachments": [],
        "createdAt": created_at,
    }


def _node(
    *,
    node_id: str,
    node_type: str,
    display_name: str,
    status: str,
    input_ports: list[dict[str, Any]],
    output_ports: list[dict[str, Any]],
    dependencies: list[str],
    summary: str,
    position: dict[str, float],
    tool_ref: str | None = None,
    model_ref: str | None = None,
    estimate: dict[str, Any] | None = None,
    resource_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    node = {
        "nodeId": node_id,
        "nodeType": node_type,
        "displayName": display_name,
        "status": status,
        "inputPorts": input_ports,
        "outputPorts": output_ports,
        "dependencies": dependencies,
        "summary": summary,
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "position": position,
    }
    if tool_ref:
        node["toolRef"] = tool_ref
    if model_ref:
        node["modelRef"] = model_ref
    if estimate is not None:
        node["estimate"] = estimate
    if resource_usage is not None:
        node["resourceUsage"] = resource_usage
    return node


def _port(port_id: str, label: str, data_type: str) -> dict[str, str]:
    return {"id": port_id, "label": label, "dataType": data_type}


def _estimate(duration_ms: int, cpu: str, memory: str, network: str) -> dict[str, Any]:
    return {
        "durationMs": duration_ms,
        "cpu": cpu,
        "memory": memory,
        "network": network,
    }


def _edges(nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for node in nodes:
        for dependency in node["dependencies"]:
            edges.append(
                {
                    "id": f"{dependency}-{node['nodeId']}",
                    "source": dependency,
                    "target": node["nodeId"],
                }
            )
    return edges
