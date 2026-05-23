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
        "project_summaries",
        "source_review",
        "open_questions",
        "references",
    ]
    assert report.source_set.accepted == [accepted]
    assert report.source_set.rejected == [rejected]


def test_build_research_graph_contains_source_reading_and_quality_check_nodes() -> None:
    from agent_service.web_research import build_research_graph

    message = UserMessage(
        task_id="research-task",
        content="Compare current Python packaging tools and write a research summary",
    )
    graph = build_research_graph(message, classify_route(message))

    parsed = RunGraph(**graph)
    node_ids = [node.nodeId for node in parsed.nodes]

    assert parsed.metadata == {
        "kind": "research",
        "question": "Compare current Python packaging tools and write a research summary",
        "sectionOrder": [
            "summary",
            "key_findings",
            "project_summaries",
            "source_review",
            "open_questions",
            "references",
        ],
    }
    assert node_ids == [
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
    assert [
        (node.nodeId, node.toolRef)
        for node in parsed.nodes
        if node.nodeType == "fixed_tool"
    ] == [
        ("research-parallel-search", "web.search.parallel"),
        ("research-source-reading", "web.fetch.sources"),
    ]
    assert parsed.nodes[0].nodeType == "planning"
    assert parsed.nodes[0].estimate is not None
    assert parsed.nodes[0].estimate.network == "none"
    search_node = parsed.nodes[3]
    assert search_node.estimate is not None
    assert search_node.estimate.network == "required"
    source_reading_node = parsed.nodes[5]
    assert source_reading_node.toolRef == "web.fetch.sources"
    assert source_reading_node.estimate is not None
    assert source_reading_node.estimate.network == "required"
    synthesis_node = parsed.nodes[6]
    assert synthesis_node.modelRef == "research-report-synthesizer"
    assert synthesis_node.estimate is not None
    assert synthesis_node.estimate.cpu == "medium"
    quality_node = parsed.nodes[7]
    assert quality_node.modelRef == "research-report-verifier"
    assert quality_node.dependencies == ["research-report-synthesis"]


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
    assert payload["sourceMetadata"]["answerStatus"] == "no-reliable-sources"
    assert payload["sourceMetadata"]["rejected"] == payload["rejectedSources"]
    assert payload["sourceMetadata"]["rejected"][0]["rejectionReason"] == "content_farm"
    assert "I could not find reliable web sources" in payload["message"]["content"]
    assert "Top10 Python releases" not in payload["message"]["content"]


class FakeWeatherProvider:
    def __init__(self) -> None:
        self.current_locations: list[str] = []
        self.forecast_locations: list[str] = []

    def current(self, location: str, *, locale: str = "zh-CN"):
        from agent_service.tool_result import ToolResult

        self.current_locations.append(location)
        return ToolResult(
            tool_name="weather.current",
            status="ok",
            data={
                "location": "上海",
                "country": "CN",
                "temperatureC": 26.1,
                "apparentTemperatureC": 27.3,
                "condition": "局部多云",
                "precipitationMm": 0.0,
                "windSpeedKmh": 12.4,
                "observedAt": "2026-05-23T15:00",
                "timezone": "Asia/Shanghai",
            },
            sources=[
                {
                    "title": "Open-Meteo",
                    "url": "https://open-meteo.com/",
                    "provider": "open_meteo",
                }
            ],
            metadata={"provider": "open_meteo"},
        )

    def forecast(self, location: str, *, locale: str = "zh-CN"):
        self.forecast_locations.append(location)
        return self.current(location, locale=locale)


class FailingSearchProvider:
    def search(self, query: str):
        raise AssertionError(f"search should not be called for weather: {query}")


class RaisingWeatherProvider:
    def current(self, location: str, *, locale: str = "zh-CN"):
        del location, locale
        raise RuntimeError("private provider detail")

    def forecast(self, location: str, *, locale: str = "zh-CN"):
        del location, locale
        raise RuntimeError("private provider detail")


class WeatherProviderWithUntitledSource:
    def current(self, location: str, *, locale: str = "zh-CN"):
        from agent_service.tool_result import ToolResult

        del locale
        return ToolResult(
            tool_name="weather.current",
            status="ok",
            data={
                "location": location,
                "temperatureC": 26.1,
                "apparentTemperatureC": 27.3,
                "condition": "局部多云",
                "precipitationMm": 0.0,
                "windSpeedKmh": 12.4,
                "observedAt": "2026-05-23T15:00",
            },
            sources=[{"url": "https://open-meteo.com/"}],
            metadata={"provider": "open_meteo"},
        )

    def forecast(self, location: str, *, locale: str = "zh-CN"):
        return self.current(location, locale=locale)


def test_simple_weather_inquiry_uses_weather_provider_without_search() -> None:
    from agent_service.web_research import answer_simple_web_inquiry

    weather_provider = FakeWeatherProvider()
    message = UserMessage(task_id="weather", content="今天上海天气怎么样？")
    event = answer_simple_web_inquiry(
        message,
        classify_route(message),
        search_provider=FailingSearchProvider(),
        weather_provider=weather_provider,
    )

    assert event.type == "message.created"
    assert weather_provider.current_locations == ["上海"]
    assert "上海当前天气" in event.payload["message"]["content"]
    assert "26.1°C" in event.payload["message"]["content"]
    assert event.payload["sources"][0]["provider"] == "open_meteo"
    assert event.payload["sourceMetadata"]["toolName"] == "weather.current"


def test_weather_provider_exception_returns_failure_message_without_raising() -> None:
    from agent_service.web_research import answer_simple_web_inquiry

    message = UserMessage(task_id="weather", content="今天上海天气怎么样？")
    event = answer_simple_web_inquiry(
        message,
        classify_route(message),
        search_provider=FailingSearchProvider(),
        weather_provider=RaisingWeatherProvider(),
    )

    assert event.type == "message.created"
    assert event.payload["message"]["content"].startswith("天气查询失败：")
    assert "private provider detail" not in event.payload["message"]["content"]
    assert event.payload["sourceMetadata"]["toolName"] == "weather.current"
    assert event.payload["sourceMetadata"]["status"] == "failed"


def test_weather_answer_uses_default_source_title_when_source_has_no_title() -> None:
    from agent_service.web_research import answer_simple_web_inquiry

    message = UserMessage(task_id="weather", content="今天上海天气怎么样？")
    event = answer_simple_web_inquiry(
        message,
        classify_route(message),
        search_provider=FailingSearchProvider(),
        weather_provider=WeatherProviderWithUntitledSource(),
    )

    assert event.type == "message.created"
    assert "上海当前天气" in event.payload["message"]["content"]
    assert "数据来源：Open-Meteo。" in event.payload["message"]["content"]


def test_weather_inquiry_without_location_asks_for_city() -> None:
    from agent_service.web_research import answer_simple_web_inquiry

    message = UserMessage(task_id="weather", content="今天的天气怎么样？")
    event = answer_simple_web_inquiry(
        message,
        classify_route(message),
        search_provider=FailingSearchProvider(),
        weather_provider=FakeWeatherProvider(),
    )

    assert event.type == "input.required"
    assert event.payload == {"prompt": "请告诉我要查询哪个城市的天气。", "missing": ["location"]}


def test_simple_web_inquiry_uses_default_search_provider_factory(monkeypatch) -> None:
    import agent_service.web_research as web_research

    provider = FakeSearchProvider(
        [
            SearchResponse(
                results=[
                    SearchResult(
                        title="Python docs",
                        url="https://docs.python.org/3/",
                        snippet="Official release information.",
                    )
                ],
                metadata={"provider": "chain"},
            )
        ]
    )
    monkeypatch.setattr(web_research, "default_search_provider", lambda: provider)

    event = web_research.answer_simple_web_inquiry(
        UserMessage(task_id="simple-web", content="What is the latest Python release?"),
        classify_route(
            UserMessage(
                task_id="simple-web",
                content="What is the latest Python release?",
            )
        ),
    )

    assert provider.queries == ["What is the latest Python release?"]
    assert "Python docs" in event.payload["message"]["content"]
