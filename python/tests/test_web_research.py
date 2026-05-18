from __future__ import annotations

from agent_service.intent import classify_route
from agent_service.schemas import AgentEvent, RunGraph, UserMessage
from agent_service.web_search import SearchResponse, SearchResult


class FakeSearchProvider:
    def __init__(self, responses: list[SearchResponse]) -> None:
        self.responses = list(responses)
        self.queries: list[str] = []

    def search(self, query: str) -> SearchResponse:
        self.queries.append(query)
        if not self.responses:
            raise AssertionError("unexpected search call")
        return self.responses.pop(0)


def test_research_models_preserve_report_sections_and_source_decisions() -> None:
    from agent_service.web_research import (
        ResearchMode,
        ResearchQuery,
        ResearchReport,
        ResearchSourceSet,
    )

    accepted = {
        "title": "Python downloads",
        "url": "https://www.python.org/downloads/",
        "snippet": "Latest release information.",
        "sourceType": "vendor_page",
        "accepted": True,
        "rejectionReason": None,
    }
    rejected = {
        "title": "Top10 Python versions",
        "url": "https://top10.example/python",
        "snippet": "Low signal repost.",
        "sourceType": "software",
        "accepted": False,
        "rejectionReason": "content_farm",
    }

    report = ResearchReport(
        title="Python release research",
        mode=ResearchMode.RESEARCH_FLOW,
        queries=[ResearchQuery(query="latest Python release", purpose="freshness")],
        source_set=ResearchSourceSet(accepted=[accepted], rejected=[rejected]),
    )

    assert report.section_order == [
        "summary",
        "key_findings",
        "source_review",
        "open_questions",
        "references",
    ]
    assert report.source_set.accepted == [accepted]
    assert report.source_set.rejected == [rejected]


def test_build_research_graph_contains_expected_nodes_and_single_visible_search_node() -> None:
    from agent_service.web_research import build_research_graph

    message = UserMessage(
        task_id="research-task",
        content="Compare current Python packaging tools and write a research summary",
    )
    graph = build_research_graph(message, classify_route(message))

    parsed = RunGraph(**graph)
    node_ids = [node.nodeId for node in parsed.nodes]

    assert node_ids == [
        "research-intent-analysis",
        "research-privacy-guard",
        "research-query-plan",
        "research-parallel-search",
        "research-source-review",
        "research-report-synthesis",
        "research-markdown-output",
    ]
    assert [
        node.nodeId
        for node in parsed.nodes
        if node.nodeType == "fixed_tool" and node.toolRef == "web.search.parallel"
    ] == ["research-parallel-search"]
    assert parsed.nodes[0].nodeType == "planning"
    assert parsed.nodes[0].estimate is not None
    assert parsed.nodes[0].estimate.network == "none"
    search_node = parsed.nodes[3]
    assert search_node.estimate is not None
    assert search_node.estimate.network == "required"
    synthesis_node = parsed.nodes[5]
    assert synthesis_node.modelRef == "research-report-synthesizer"
    assert synthesis_node.estimate is not None
    assert synthesis_node.estimate.cpu == "medium"


def test_simple_web_inquiry_searches_and_returns_concise_answer_with_source_metadata() -> None:
    from agent_service.web_research import answer_simple_web_inquiry

    long_snippet = " ".join(["release details"] * 40)
    provider = FakeSearchProvider(
        [
            SearchResponse(
                results=[
                    SearchResult(
                        title="Python docs",
                        url="https://docs.python.org/3/",
                        snippet=long_snippet,
                    ),
                    SearchResult(
                        title="Top10 Python releases",
                        url="https://top10.example/python",
                        snippet="Copied release notes and ads.",
                    ),
                ]
            )
        ]
    )
    message = UserMessage(task_id="simple-web", content="What is the latest Python release?")

    event = answer_simple_web_inquiry(
        message,
        classify_route(message),
        search_provider=provider,
    )

    assert isinstance(event, AgentEvent)
    assert event.type == "message.created"
    assert provider.queries == ["What is the latest Python release?"]
    payload = event.payload
    assert "Python docs" in payload["message"]["content"]
    assert "[1]" in payload["message"]["content"]
    assert payload["sources"][0]["accepted"] is True
    assert payload["sources"][0]["ref"] == "[1]"
    assert len(payload["sources"][0]["snippet"]) <= 240
    assert payload["rejectedSources"][0]["rejectionReason"] == "content_farm"


def test_simple_web_inquiry_does_not_cite_rejected_sources() -> None:
    from agent_service.web_research import answer_simple_web_inquiry

    provider = FakeSearchProvider(
        [
            SearchResponse(
                results=[
                    SearchResult(
                        title="Top10 Python releases",
                        url="https://top10.example/python",
                        snippet="Copied release notes and ads.",
                    ),
                    SearchResult(
                        title="Old Python notes",
                        url="https://answers.example/python",
                        snippet="Last updated 2017.",
                    ),
                ]
            )
        ]
    )
    message = UserMessage(task_id="simple-web", content="What is the latest Python release?")

    event = answer_simple_web_inquiry(
        message,
        classify_route(message),
        search_provider=provider,
    )

    payload = event.payload
    assert payload["sources"] == []
    assert len(payload["rejectedSources"]) == 2
    assert "I could not find reliable web sources" in payload["message"]["content"]
    assert "Top10 Python releases" not in payload["message"]["content"]
