from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import agent_service.graph as graph_module
from agent_service.agent_run_state import AgentRunState
from agent_service.graph import (
    _classify_message,
    _node,
    build_graph,
    run_agent,
    run_agent_from_state,
    stream_agent_events,
    stream_agent_events_from_state,
)
from agent_service.graph_compiler import compile_task_graph_to_node_graph
from agent_service.goal_spec import parse_goal_spec
from agent_service.intent import IntentKind, classify_route
from agent_service.memory_store import MemoryRecord, MemoryStore
from agent_service.model_client import ChatMessage
from agent_service.model_policy import ModelCallPolicy, ModelCallProfile
from agent_service.router_v2 import STRUCTURED_ROUTER_ENV
from agent_service.schemas import Attachment, GraphNode, RunGraph, UserMessage
from agent_service.task_graph import build_document_task_graph
from agent_service.web_search import SearchResponse, SearchResult


class FakeModelClient:
    def __init__(self, reply: str = "本地模型回复") -> None:
        self.reply = reply
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
        return self.reply

    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ):
        self.calls.append(messages)
        self.policies.append(policy)
        self.temperatures.append(temperature)
        self.max_tokens.append(max_tokens)
        yield "你好"
        yield "，本地模型"


class FakeSearchProvider:
    def __init__(self, response: SearchResponse) -> None:
        self.response = response
        self.queries: list[str] = []

    def search(self, query: str) -> SearchResponse:
        self.queries.append(query)
        return self.response


class FailingSearchProvider:
    def search(self, query: str):
        raise AssertionError(f"generic search should not run for weather: {query}")


def _existing_graph() -> RunGraph:
    return RunGraph(
        graphId="existing-graph",
        nodes=[
            {
                "nodeId": "task-analysis",
                "nodeType": "planning",
                "displayName": "Task Analysis",
                "status": "completed",
                "summary": "Existing plan.",
                "createdBy": "agent",
                "position": {"x": 0, "y": 0},
            }
        ],
        edges=[],
    )


def test_plain_chat_returns_local_model_message() -> None:
    client = FakeModelClient("你好，我是本地模型。")

    events = run_agent(
        UserMessage(task_id="task-chat", content="你好，请介绍一下你自己"),
        model_client=client,
    )

    assert len(events) == 1
    assert events[0].type == "message.created"
    message = events[0].payload["message"]
    assert message["role"] == "assistant"
    assert message["content"] == "你好，我是本地模型。"
    assert message["attachments"] == []
    assert message["messageId"].startswith("assistant-")
    assert client.calls
    assert client.calls[0][0].role == "system"
    assert client.calls[0][1] == ChatMessage(
        role="user",
        content="你好，请介绍一下你自己",
    )


def test_plain_chat_uses_fast_chat_policy() -> None:
    client = FakeModelClient("hello")

    run_agent(UserMessage(task_id="task-chat", content="hello"), model_client=client)

    assert client.calls
    assert client.policies[0] is not None
    assert client.policies[0].profile == ModelCallProfile.FAST_CHAT
    assert client.temperatures[0] is None
    assert client.max_tokens[0] is None


def test_plain_chat_after_graph_exists_uses_chat_router() -> None:
    client = FakeModelClient("chat answer")

    events = run_agent(
        UserMessage(task_id="task-chat", content="hello"),
        model_client=client,
        current_graph=_existing_graph(),
    )

    assert [event.type for event in events] == ["message.created"]
    assert events[0].payload["message"]["content"] == "chat answer"
    assert client.calls


def test_plain_chat_streams_local_model_message_deltas() -> None:
    client = FakeModelClient()

    events = list(
        stream_agent_events(
            UserMessage(task_id="task-chat", content="hello"),
            model_client=client,
        )
    )

    assert [event.type for event in events] == [
        "message.started",
        "message.delta",
        "message.delta",
        "message.completed",
    ]
    message = events[0].payload["message"]
    assert message["role"] == "assistant"
    assert message["content"] == ""
    assert events[1].payload == {
        "messageId": message["messageId"],
        "delta": "你好",
    }
    assert events[2].payload == {
        "messageId": message["messageId"],
        "delta": "，本地模型",
    }
    assert events[3].payload == {"messageId": message["messageId"]}


def test_plain_chat_stream_uses_fast_chat_policy() -> None:
    client = FakeModelClient()

    list(
        stream_agent_events(
            UserMessage(task_id="task-chat", content="hello"),
            model_client=client,
        )
    )

    assert client.calls
    assert client.policies[0] is not None
    assert client.policies[0].profile == ModelCallProfile.FAST_CHAT
    assert client.temperatures[0] is None
    assert client.max_tokens[0] is None


def test_graph_state_preserves_structured_route_decision_for_inquiries() -> None:
    client = FakeModelClient("local answer")
    provider = FakeSearchProvider(
        SearchResponse(
            results=[
                SearchResult(
                    title="Python release",
                    url="https://www.python.org/downloads/",
                    snippet="Latest Python release.",
                )
            ]
        )
    )
    app = build_graph(model_client=client, search_provider=provider)

    result = app.invoke(
        {
            "message": UserMessage(
                task_id="task-route",
                content="What is the latest Python release?",
            ),
            "events": [],
        }
    )

    assert result["intent"] == "web_simple_inquiry"
    assert result["route_decision"] == {
        "intent": {"kind": "inquiry"},
        "inquiry": {"mode": "web_simple", "requires_web": True},
        "reason": "question requests current or external factual data",
        "missing_inputs": [],
    }
    assert result["structured_route_decision"]["intent"] == "web_simple_inquiry"
    assert result["structured_route_decision"]["taskType"] == "research"
    assert result["structured_route_decision"]["missingInputs"] == []
    assert result["structured_route_decision"]["source"] == "deterministic"
    assert result["run_state"].structured_route_decision == result["structured_route_decision"]
    assert result["events"][0].type == "message.created"


def test_graph_state_updates_agent_run_state_with_routing_metadata() -> None:
    provider = FakeSearchProvider(
        SearchResponse(
            results=[
                SearchResult(
                    title="Python release",
                    url="https://www.python.org/downloads/",
                    snippet="Latest Python release.",
                )
            ]
        )
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-run-state-route",
            content="What is the latest Python release?",
        )
    )
    app = build_graph(search_provider=provider)

    result = app.invoke(
        {
            "run_state": run_state,
            "message": run_state.message,
            "events": [],
        }
    )

    updated = result["run_state"]
    assert isinstance(updated, AgentRunState)
    assert updated.task_id == "task-run-state-route"
    assert updated.intent == "web_simple_inquiry"
    assert updated.goal_spec is not None
    assert updated.goal_spec.needs_web is True
    assert updated.route_decision == {
        "intent": {"kind": "inquiry"},
        "inquiry": {"mode": "web_simple", "requires_web": True},
        "reason": "question requests current or external factual data",
        "missing_inputs": [],
    }
    assert updated.structured_route_decision is not None
    assert updated.structured_route_decision["intent"] == "web_simple_inquiry"
    assert updated.structured_route_decision["taskType"] == "research"
    assert result["structured_route_decision"] == updated.structured_route_decision
    assert result["intent"] == "web_simple_inquiry"


def test_medium_confidence_structured_model_route_requests_clarification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STRUCTURED_ROUTER_ENV, "1")
    client = FakeModelClient(
        (
            '{"intent":"task","confidence":0.61,"task_type":"code_task",'
            '"reason":"model selected task but needs confirmation"}'
        )
    )

    events = run_agent(
        UserMessage(task_id="medium-model-route", content="Please handle the Python thing."),
        model_client=client,
    )

    assert [event.type for event in events] == ["input.required"]
    assert events[0].payload["missing"] == ["clarification"]
    assert "确认" in events[0].payload["prompt"]
    assert len(client.calls) == 1
    assert client.temperatures == [0.0]
    assert client.max_tokens == [512]


def test_structured_model_router_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(STRUCTURED_ROUTER_ENV, raising=False)
    model_reply = (
        '{"intent":"task","confidence":0.95,"task_type":"code_task",'
        '"reason":"model route should be ignored"}'
    )
    client = FakeModelClient(model_reply)

    events = run_agent(
        UserMessage(task_id="default-router-off", content="hello"),
        model_client=client,
    )

    assert [event.type for event in events] == ["message.created"]
    assert events[0].payload["message"]["content"] == model_reply
    assert len(client.calls) == 1
    assert client.calls[0][0].role == "system"
    assert "本地 AI 助手" in client.calls[0][0].content
    assert client.calls[0][1] == ChatMessage(role="user", content="hello")
    assert client.temperatures == [None]
    assert client.max_tokens == [None]


def test_graph_state_records_effective_route_decision_for_quick_answer_choice() -> None:
    provider = FakeSearchProvider(
        SearchResponse(
            results=[
                SearchResult(
                    title="Packaging tools",
                    url="https://packaging.python.org/",
                    snippet="Python packaging tools guide.",
                )
            ]
        )
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-effective-route",
            content="Research and compare current Python packaging tools",
        ),
        inquiry_choice="quick_answer",
    )
    app = build_graph(search_provider=provider)

    result = app.invoke(
        {
            "run_state": run_state,
            "message": run_state.message,
            "events": [],
        }
    )

    updated = result["run_state"]
    assert updated.intent == "web_simple_inquiry"
    assert updated.route_decision["inquiry"]["mode"] == "web_simple"
    assert result["route_decision"]["inquiry"]["mode"] == "web_simple"
    assert updated.structured_route_decision["intent"] == "web_simple_inquiry"
    assert result["structured_route_decision"] == updated.structured_route_decision


def test_build_graph_still_accepts_legacy_state_without_run_state() -> None:
    provider = FakeSearchProvider(
        SearchResponse(
            results=[
                SearchResult(
                    title="Python release",
                    url="https://www.python.org/downloads/",
                    snippet="Latest Python release.",
                )
            ]
        )
    )
    message = UserMessage(
        task_id="task-legacy-route",
        content="What is the latest Python release?",
    )
    app = build_graph(search_provider=provider)

    result = app.invoke({"message": message, "events": []})

    assert isinstance(result["run_state"], AgentRunState)
    assert result["run_state"].task_id == "task-legacy-route"
    assert result["run_state"].intent == "web_simple_inquiry"
    assert result["intent"] == "web_simple_inquiry"


def test_run_agent_from_state_matches_public_research_choice_behavior() -> None:
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="complex-web-from-state",
            content="Research and compare current Python packaging tools",
        )
    )

    events = run_agent_from_state(run_state)

    assert [event.type for event in events] == ["research.choice_required"]
    assert events[0].payload["taskId"] == "complex-web-from-state"
    assert [choice["id"] for choice in events[0].payload["choices"]] == [
        "quick_answer",
        "research_flow",
    ]


def test_stream_agent_events_from_state_matches_public_stream_behavior() -> None:
    client = FakeModelClient()
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="task-chat-from-state", content="hello")
    )

    events = list(stream_agent_events_from_state(run_state, model_client=client))

    assert [event.type for event in events] == [
        "message.started",
        "message.delta",
        "message.delta",
        "message.completed",
    ]
    message = events[0].payload["message"]
    assert events[1].payload == {
        "messageId": message["messageId"],
        "delta": "你好",
    }
    assert events[2].payload == {
        "messageId": message["messageId"],
        "delta": "，本地模型",
    }
    assert events[3].payload == {"messageId": message["messageId"]}
    assert client.calls


def test_stream_agent_events_from_state_routes_non_chat_through_router_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original_classify_route = graph_module.classify_route

    def counting_classify_route(message: UserMessage):
        nonlocal calls
        calls += 1
        return original_classify_route(message)

    monkeypatch.setattr(graph_module, "classify_route", counting_classify_route)
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="stream-quick-answer-once",
            content="Research and compare current Python packaging tools",
        ),
        inquiry_choice="quick_answer",
    )
    provider = FakeSearchProvider(
        SearchResponse(
            results=[
                SearchResult(
                    title="Packaging tools",
                    url="https://packaging.python.org/",
                    snippet="Python packaging tools guide.",
                )
            ]
        )
    )

    events = list(stream_agent_events_from_state(run_state, search_provider=provider))

    assert calls == 0
    assert [event.type for event in events] == ["message.created"]


def test_graph_feedback_guard_still_uses_legacy_classifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original_classify_route = graph_module.classify_route

    def counting_classify_route(message: UserMessage):
        nonlocal calls
        calls += 1
        return original_classify_route(message)

    monkeypatch.setattr(graph_module, "classify_route", counting_classify_route)

    events = run_agent(
        UserMessage(task_id="task-feedback-guard", content="hello"),
        current_graph=_existing_graph(),
    )

    assert calls == 1
    assert [event.type for event in events] == ["message.created"]


def test_web_simple_route_auto_searches_and_returns_sources_without_graph() -> None:
    provider = FakeSearchProvider(
        SearchResponse(
            results=[
                SearchResult(
                    title="Python docs",
                    url="https://docs.python.org/3/",
                    snippet="Latest Python release.",
                ),
                SearchResult(
                    title="Top10 Python versions",
                    url="https://top10.example/python",
                    snippet="Copied-release-notes.",
                ),
            ]
        )
    )

    events = run_agent(
        UserMessage(task_id="simple-web", content="What is the latest Python release?"),
        search_provider=provider,
    )

    assert provider.queries == ["What is the latest Python release?"]
    assert [event.type for event in events] == ["message.created"]
    assert events[0].payload["sources"][0]["ref"] == "[1]"
    assert events[0].payload["sources"][0]["accepted"] is True
    assert events[0].payload["rejectedSources"][0]["rejectionReason"] == "content_farm"


def test_weather_simple_route_uses_weather_provider_without_generic_search() -> None:
    from agent_service.tool_result import ToolResult

    class WeatherProvider:
        def __init__(self) -> None:
            self.locations: list[str] = []

        def current(self, location: str, *, locale: str = "zh-CN") -> ToolResult:
            self.locations.append(location)
            return ToolResult(
                tool_name="weather.current",
                status="ok",
                data={
                    "location": "上海",
                    "temperatureC": 26.1,
                    "apparentTemperatureC": 27.3,
                    "condition": "局部多云",
                    "precipitationMm": 0.0,
                    "windSpeedKmh": 12.4,
                    "observedAt": "2026-05-23T15:00",
                    "timezone": "Asia/Shanghai",
                },
                sources=[{"title": "Open-Meteo", "url": "https://open-meteo.com/"}],
                metadata={"provider": "open_meteo"},
            )

        def forecast(self, location: str, *, locale: str = "zh-CN") -> ToolResult:
            return self.current(location, locale=locale)

    class SearchProvider:
        def search(self, query: str):
            raise AssertionError("generic search should not run for weather")

    weather_provider = WeatherProvider()
    events = run_agent(
        UserMessage(task_id="weather", content="今天上海天气怎么样？"),
        search_provider=SearchProvider(),
        weather_provider=weather_provider,
    )

    assert weather_provider.locations == ["上海"]
    assert events[0].type == "message.created"
    assert "上海当前天气" in events[0].payload["message"]["content"]


def test_english_weather_simple_route_uses_weather_provider_without_generic_search() -> None:
    from agent_service.tool_result import ToolResult

    class WeatherProvider:
        def __init__(self) -> None:
            self.locations: list[str] = []

        def current(self, location: str, *, locale: str = "zh-CN") -> ToolResult:
            del locale
            self.locations.append(location)
            return ToolResult(
                tool_name="weather.current",
                status="ok",
                data={
                    "location": "New York",
                    "temperatureC": 18.5,
                    "apparentTemperatureC": 18.1,
                    "condition": "晴",
                    "precipitationMm": 0.0,
                    "windSpeedKmh": 9.2,
                    "observedAt": "2026-05-23T09:00",
                },
                sources=[{"title": "Open-Meteo", "url": "https://open-meteo.com/"}],
                metadata={"provider": "open_meteo"},
            )

        def forecast(self, location: str, *, locale: str = "zh-CN") -> ToolResult:
            return self.current(location, locale=locale)

    weather_provider = WeatherProvider()
    model_client = FakeModelClient("model should not run")
    events = run_agent(
        UserMessage(task_id="weather", content="What is the weather in New York?"),
        model_client=model_client,
        search_provider=FailingSearchProvider(),
        weather_provider=weather_provider,
    )

    assert weather_provider.locations == ["New York"]
    assert model_client.calls == []
    assert events[0].type == "message.created"
    assert "New York当前天气" in events[0].payload["message"]["content"]


def test_english_weather_without_location_requests_location_without_search_or_model() -> None:
    class WeatherProvider:
        def current(self, location: str, *, locale: str = "zh-CN"):
            del location, locale
            raise AssertionError("weather provider should not run without location")

        def forecast(self, location: str, *, locale: str = "zh-CN"):
            del location, locale
            raise AssertionError("weather provider should not run without location")

    model_client = FakeModelClient("model should not run")

    events = run_agent(
        UserMessage(task_id="weather", content="What's the weather?"),
        model_client=model_client,
        search_provider=FailingSearchProvider(),
        weather_provider=WeatherProvider(),
    )

    assert model_client.calls == []
    assert events[0].type == "input.required"
    assert events[0].payload == {"prompt": "请告诉我要查询哪个城市的天气。", "missing": ["location"]}


def test_web_simple_inquiry_after_graph_exists_uses_inquiry_router() -> None:
    provider = FakeSearchProvider(
        SearchResponse(
            results=[
                SearchResult(
                    title="Python docs",
                    url="https://docs.python.org/3/",
                    snippet="Latest Python release.",
                )
            ]
        )
    )

    events = run_agent(
        UserMessage(task_id="simple-web", content="What is the latest Python release?"),
        search_provider=provider,
        current_graph=_existing_graph(),
    )

    assert provider.queries == ["What is the latest Python release?"]
    assert [event.type for event in events] == ["message.created"]
    assert events[0].payload["sources"][0]["url"] == "https://docs.python.org/3/"


def test_sources_question_after_graph_exists_uses_web_inquiry_router() -> None:
    provider = FakeSearchProvider(
        SearchResponse(
            results=[
                SearchResult(
                    title="Python release notes",
                    url="https://docs.python.org/3/",
                    snippet="Latest Python release details.",
                )
            ]
        )
    )

    events = run_agent(
        UserMessage(
            task_id="simple-web",
            content="What sources discuss the latest Python release?",
        ),
        search_provider=provider,
        current_graph=_existing_graph(),
    )

    assert provider.queries == ["What sources discuss the latest Python release?"]
    assert [event.type for event in events] == ["message.created"]
    assert events[0].payload["sources"][0]["url"] == "https://docs.python.org/3/"


@pytest.mark.parametrize(
    "content",
    [
        "What is the order of operations in Python?",
        "What style guide does Python use?",
        "What is a constraint?",
        "What constraints apply in Python packaging?",
        "Can you explain what a constraint means?",
    ],
)
def test_local_questions_with_constraint_words_after_graph_exists_use_inquiry_router(
    content: str,
) -> None:
    client = FakeModelClient("local inquiry answer")

    events = run_agent(
        UserMessage(task_id="task-chat", content=content),
        model_client=client,
        current_graph=_existing_graph(),
    )

    assert [event.type for event in events] == ["message.created"]
    assert events[0].payload["message"]["content"] == "local inquiry answer"
    assert client.calls


@pytest.mark.parametrize(
    "content",
    [
        "Use only CSV sources for this graph.",
        "Can you use only CSV sources for this graph?",
        "Add constraint: use only CSV sources.",
        "Please add constraint: use only CSV sources.",
        "Add the constraint to use only CSV sources.",
        "Set constraint: verified sources only.",
        "Constraint: use only CSV sources.",
    ],
)
def test_explicit_graph_constraint_after_graph_exists_routes_to_feedback(
    content: str,
) -> None:
    events = run_agent(
        UserMessage(
            task_id="task-1",
            content=content,
        ),
        current_graph=_existing_graph(),
    )

    assert [event.type for event in events] == ["graph.replanned"]


def test_web_complex_default_returns_research_choice_required() -> None:
    events = run_agent(
        UserMessage(
            task_id="complex-web",
            content="Research and compare current Python packaging tools",
        )
    )

    assert [event.type for event in events] == ["research.choice_required"]
    assert events[0].payload == {
        "taskId": "complex-web",
        "prompt": "This question can be answered quickly or turned into a research flow. Choose how to proceed.",
        "choices": [
            {
                "id": "quick_answer",
                "label": "Quick answer",
                "description": "Search the web now and return a concise sourced answer.",
            },
            {
                "id": "research_flow",
                "label": "Research flow",
                "description": "Create a research graph for planning, source review, and report synthesis.",
            },
        ],
    }


def test_web_complex_quick_answer_choice_searches_and_answers() -> None:
    provider = FakeSearchProvider(
        SearchResponse(
            results=[
                SearchResult(
                    title="Python packaging guide",
                    url="https://docs.python.org/3/",
                    snippet="Official Python packaging guidance.",
                )
            ]
        )
    )

    events = run_agent(
        UserMessage(
            task_id="complex-web",
            content="Research and compare current Python packaging tools",
        ),
        inquiry_choice="quick_answer",
        search_provider=provider,
    )

    assert provider.queries == ["Research and compare current Python packaging tools"]
    assert [event.type for event in events] == ["message.created"]
    assert events[0].payload["sources"][0]["url"] == "https://docs.python.org/3/"


def test_web_complex_research_flow_choice_creates_research_graph() -> None:
    events = run_agent(
        UserMessage(
            task_id="complex-web",
            content="Research and compare current Python packaging tools",
        ),
        inquiry_choice="research_flow",
    )

    assert [event.type for event in events] == ["node_graph.created"]
    graph = events[0].payload["graph"]
    assert [node["nodeId"] for node in graph["nodes"]] == [
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
    assert len(
        [
            node
            for node in graph["nodes"]
            if node["nodeType"] == "fixed_tool"
            and node.get("toolRef") == "web.search.parallel"
        ]
    ) == 1
    assert len(
        [
            node
            for node in graph["nodes"]
            if node["nodeType"] == "fixed_tool"
            and node.get("toolRef") == "web.fetch.sources"
        ]
    ) == 1


def test_research_graph_records_deep_reasoning_policy_metadata() -> None:
    events = run_agent(
        UserMessage(
            task_id="complex-web",
            content="Research and compare current Python packaging tools",
        ),
        inquiry_choice="research_flow",
    )

    created_event = next(event for event in events if event.type == "node_graph.created")
    graph = created_event.payload["graph"]
    assert graph["metadata"].get("modelPolicy") == ModelCallProfile.DEEP_REASONING.value


def test_research_graph_records_structured_route_decision_metadata() -> None:
    events = run_agent(
        UserMessage(
            task_id="complex-web",
            content="Research and compare current Python packaging tools",
        ),
        inquiry_choice="research_flow",
    )

    created_event = next(event for event in events if event.type == "node_graph.created")
    graph = created_event.payload["graph"]
    route_decision = graph["metadata"]["routeDecision"]
    assert route_decision["intent"] == "web_complex_research_flow"
    assert route_decision["source"] == "deterministic"
    assert route_decision["taskType"] == "research"
    assert graph["metadata"]["kind"] == "research"


def test_chinese_github_research_with_context_attachment_asks_for_research_choice() -> None:
    events = run_agent(
        UserMessage(
            task_id="github-research",
            content=(
                "\u5e2e\u6211\u67e5\u8be2\u4eca\u5929GitHub\u7f51\u7ad9"
                "\u4e0a\u9762\u6709\u54ea\u4e9b\u70ed\u95e8\u7684\u9879\u76ee\uff0c"
                "\u7136\u540e\u7814\u7a76\u4e00\u4e0b\u6bcf\u4e00\u4e2a"
                "\u9879\u76ee\u5177\u4f53\u662f\u5e72\u4ec0\u4e48\u7684\uff0c"
                "\u7136\u540e\u6700\u540e\u5e2e\u6211\u603b\u7ed3\u4e00\u4e0b\uff0c"
                "\u5199\u6210\u4e00\u4e2a\u6587\u6863\u3002"
            ),
            attachments=[
                Attachment(
                    attachment_id="old-doc",
                    name="old-context.docx",
                    path=r"C:\Users\Drew\Desktop\old-context.docx",
                    size_bytes=128,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        )
    )

    assert [event.type for event in events] == ["research.choice_required"]


def test_missing_attachment_requests_input_for_document_task() -> None:
    events = run_agent(UserMessage(task_id="task-1", content="帮我处理这个文档"))

    assert len(events) == 1
    assert events[0].type == "input.required"
    assert events[0].payload["prompt"] == "请把需要处理的文件添加到聊天框里。"
    assert events[0].payload["missing"] == ["document_file"]


def test_empty_message_requests_message_input_not_document_file() -> None:
    events = run_agent(UserMessage(task_id="empty-message", content=""))

    assert len(events) == 1
    assert events[0].type == "input.required"
    assert events[0].payload["missing"] == ["message"]
    assert "document_file" not in events[0].payload["missing"]


def test_attachment_generates_node_graph_for_document_task() -> None:
    events = run_agent(
        UserMessage(
            task_id="task-2",
            content="整理成报告",
            attachments=[
                Attachment(
                    attachment_id="a1",
                    name="input.docx",
                    path="workspace/inputs/input.docx",
                    size_bytes=100,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        )
    )

    assert len(events) == 1
    assert events[0].type == "node_graph.created"
    graph = events[0].payload["graph"]
    assert graph["graphId"] == "task-2-graph"
    assert graph["nodes"][0]["nodeId"] == "document-input"
    assert graph["nodes"][0]["displayName"] == "文档输入"
    assert graph["nodes"][0]["nodeType"] == "fixed_tool"
    assert graph["nodes"][0]["outputPorts"][0]["dataType"] == "document"
    parse_node = graph["nodes"][1]
    assert parse_node["nodeId"] == "document-parse"
    assert parse_node["displayName"] == "文档转 Markdown"
    assert parse_node["toolRef"] == "internal:document.markitdown_convert"
    assert parse_node["outputPorts"][0]["label"] == "Markdown"
    assert graph["nodes"][0]["dependencies"] == []
    assert {
        "id": "document-input-document-parse",
        "source": "document-input",
        "target": "document-parse",
    } in graph["edges"]
    assert [node["nodeId"] for node in graph["nodes"][:6]] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]
    typst_node = graph["nodes"][4]
    assert typst_node["nodeType"] == "fixed_tool"
    assert typst_node["toolRef"] == "internal:document.typst_compile"
    assert typst_node["dependencies"] == ["content-organize", "report-generate"]
    assert {
        "id": "typst-export-file-export",
        "source": "typst-export",
        "target": "file-export",
    } in graph["edges"]


def test_attachment_document_task_route_decision_matches_document_graph_route() -> None:
    message = UserMessage(
        task_id="task-attached-route",
        content="请整理这个文档",
        attachments=[
            Attachment(
                attachment_id="a1",
                name="input.docx",
                path="workspace/inputs/input.docx",
                size_bytes=100,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ],
    )

    decision = classify_route(message)
    result = build_graph().invoke({"message": message, "events": []})
    events = result["events"]

    assert decision.intent.kind == IntentKind.TASK
    assert result["intent"] == "task"
    assert result["route_decision"]["intent"]["kind"] == "task"
    assert _classify_message(message) == "task"
    assert events[0].type == "node_graph.created"
    assert [node["nodeId"] for node in events[0].payload["graph"]["nodes"]] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]


def test_attachment_document_task_graph_uses_planner_chain_shape(monkeypatch) -> None:
    planner_calls: list[dict[str, object]] = []

    class RecordingPlannerChain:
        def __init__(self, *, tool_registry) -> None:
            self.tool_registry = tool_registry

        def plan(self, request):
            planner_calls.append(
                {
                    "task_id": request.task_id,
                    "goal_spec": request.goal_spec,
                    "context": request.context,
                    "route": request.route,
                    "tool_registry": self.tool_registry,
                }
            )
            graph_payload = compile_task_graph_to_node_graph(
                build_document_task_graph(request.task_id, request.goal_spec)
            )
            graph_payload["metadata"] = {
                "plannerChain": {
                    "version": "planner_chain.v1",
                    "planner": "template.document.v1",
                    "strategy": "document_template",
                    "routeIntent": request.route.intent,
                    "taskType": request.route.task_type,
                    "routeSource": request.route.source,
                    "routeConfidence": request.route.confidence,
                    "toolCandidates": list(request.route.tool_candidates),
                    "requiredPermissions": list(request.route.required_permissions),
                }
            }
            return SimpleNamespace(graph_payload=graph_payload)

    monkeypatch.setattr(graph_module, "PlannerChain", RecordingPlannerChain)

    events = run_agent(
        UserMessage(
            task_id="task-planner-chain",
            content="summarize this document as a PDF report",
            attachments=[
                Attachment(
                    attachment_id="a-planner-chain",
                    name="planner-chain.docx",
                    path="workspace/inputs/planner-chain.docx",
                    size_bytes=100,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        )
    )

    assert planner_calls
    assert planner_calls[0]["route"].task_type == "document_processing"
    assert len(events) == 1
    assert events[0].type == "node_graph.created"
    graph = events[0].payload["graph"]
    assert graph["graphId"] == "task-planner-chain-graph"
    assert graph["metadata"]["plannerChain"]["strategy"] == "document_template"
    assert graph["metadata"]["modelPolicy"] == ModelCallProfile.DEEP_REASONING.value
    assert [edge["id"] for edge in graph["edges"]] == [
        "document-input-document-parse",
        "document-parse-content-organize",
        "document-parse-report-generate",
        "content-organize-typst-export",
        "report-generate-typst-export",
        "typst-export-file-export",
    ]
    nodes_by_id = {node["nodeId"]: node for node in graph["nodes"]}
    assert nodes_by_id["content-organize"]["modelRef"] == "local-content-organizer"
    assert nodes_by_id["report-generate"]["modelRef"] == "local-report-writer"
    assert nodes_by_id["typst-export"]["permissionsRequired"] == [
        "write_project_artifact"
    ]


def test_task_planning_loads_project_memory_by_default(
    monkeypatch,
    tmp_path,
) -> None:
    project_path = tmp_path / "project.alita"
    MemoryStore(str(project_path)).append(
        MemoryRecord(
            memory_id="preference-1",
            kind="preference",
            summary="Prefer concise implementation notes.",
            source_ref="user",
            created_at="2026-05-30T00:00:00Z",
            tags=["planning"],
        )
    )
    captured: dict[str, object] = {}
    real_build_context_bundle = graph_module.build_context_bundle

    def recording_build_context_bundle(*args, **kwargs):
        captured["project_path"] = kwargs.get("project_path")
        captured["memory_records"] = list(kwargs.get("memory_records") or [])
        return real_build_context_bundle(*args, **kwargs)

    monkeypatch.setattr(
        graph_module,
        "build_context_bundle",
        recording_build_context_bundle,
    )
    message = UserMessage(
        task_id="task-memory-plan",
        content="Create a Python script that counts rows in a CSV file.",
    )
    run_state = AgentRunState.from_user_message(message).model_copy(
        update={"project_path": str(project_path)}
    )

    graph_module._graph_payload_for_task(message, run_state=run_state)

    assert captured["project_path"] == str(project_path)
    memory_records = captured["memory_records"]
    assert len(memory_records) == 1
    assert memory_records[0].summary == "Prefer concise implementation notes."


def test_attachment_with_latest_keyword_still_generates_node_graph() -> None:
    events = run_agent(
        UserMessage(
            task_id="task-latest-doc",
            content="请总结这个文档里的最新内容",
            attachments=[
                Attachment(
                    attachment_id="a-latest",
                    name="latest.docx",
                    path="workspace/inputs/latest.docx",
                    size_bytes=100,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        )
    )

    assert len(events) == 1
    assert events[0].type == "node_graph.created"


def test_attachment_with_only_latest_keyword_generates_node_graph() -> None:
    events = run_agent(
        UserMessage(
            task_id="task-latest-only-doc",
            content="最新",
            attachments=[
                Attachment(
                    attachment_id="a-latest-only",
                    name="latest-only.docx",
                    path="workspace/inputs/latest-only.docx",
                    size_bytes=100,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        )
    )

    assert len(events) == 1
    assert events[0].type == "node_graph.created"


def test_general_task_classification_creates_planner_graph_instead_of_answer() -> None:
    client = FakeModelClient("this should not be used")

    events = run_agent(
        UserMessage(
            task_id="task-general",
            content="Can you create a Python script that counts rows in a CSV file?",
        ),
        model_client=client,
    )

    assert client.calls == []
    assert [event.type for event in events] == ["node_graph.created"]
    graph = events[0].payload["graph"]
    assert graph["graphId"] == "task-general-graph"
    assert [node["nodeId"] for node in graph["nodes"][:4]] == [
        "task-analysis",
        "context-gathering",
        "evidence-summary",
        "plan-draft",
    ]
    assert [
        node["nodeId"]
        for node in graph["nodes"]
        if node["nodeType"] == "planning"
    ] == [
        "task-analysis",
        "context-gathering",
        "evidence-summary",
        "plan-draft",
        "capability-analysis",
        "tool-selection",
        "plan-review",
        "execution-order-planning",
    ]


def test_task_graph_records_deep_reasoning_policy_metadata() -> None:
    events = run_agent(
        UserMessage(
            task_id="task-general",
            content="Can you create a Python script that counts rows in a CSV file?",
        )
    )

    created_event = next(event for event in events if event.type == "node_graph.created")
    graph = created_event.payload["graph"]
    assert graph["metadata"].get("modelPolicy") == ModelCallProfile.DEEP_REASONING.value


def test_task_graph_records_structured_route_decision_metadata() -> None:
    events = list(
        stream_agent_events(
            UserMessage(
                task_id="task-general",
                content="Can you create a Python script that counts rows in a CSV file?",
            )
        )
    )

    created_event = next(event for event in events if event.type == "node_graph.created")
    graph = created_event.payload["graph"]
    route_decision = graph["metadata"]["routeDecision"]
    assert route_decision["intent"] == "task"
    assert route_decision["source"] == "deterministic"
    assert route_decision["confidence"] >= 0.75
    assert route_decision["taskType"]


def test_task_graph_records_planner_chain_metadata() -> None:
    events = run_agent(
        UserMessage(
            task_id="planner-chain-code",
            content="Create a Python script that counts rows in a CSV file.",
        )
    )

    graph = events[0].payload["graph"]
    planner_chain = graph["metadata"]["plannerChain"]
    assert planner_chain["version"] == "planner_chain.v1"
    assert planner_chain["planner"] == "legacy.task_planner.v1"
    assert planner_chain["strategy"] == "legacy_task_planner"
    assert planner_chain["routeIntent"] == "task"
    assert planner_chain["taskType"] == "code_task"
    assert graph["metadata"]["routeDecision"]["intent"] == "task"


def test_planner_chain_metadata_does_not_change_node_graph_event_shape() -> None:
    events = run_agent(
        UserMessage(
            task_id="planner-chain-event-shape",
            content="Create a Python script that counts rows in a CSV file.",
        )
    )

    assert [event.type for event in events] == ["node_graph.created"]
    event = events[0]
    assert set(event.payload.keys()) == {"graph"}
    graph = event.payload["graph"]
    assert "plannerChain" in graph["metadata"]
    assert "routeDecision" in graph["metadata"]


def test_prerouted_task_state_without_structured_route_records_route_metadata() -> None:
    message = UserMessage(
        task_id="pre-routed-task",
        content="Create a Python script that counts rows in a CSV file.",
    )
    run_state = AgentRunState.from_user_message(message).model_copy(
        update={
            "intent": "task",
            "goal_spec": parse_goal_spec(message),
        }
    )

    events = run_agent_from_state(run_state)

    graph = events[0].payload["graph"]
    assert graph["metadata"]["plannerChain"]["routeSource"] == "deterministic"
    assert graph["metadata"]["routeDecision"]["source"] == "deterministic"
    assert graph["metadata"]["routeDecision"]["taskType"] == "code_task"


def test_prerouted_task_route_decision_metadata_scrubs_structured_route_paths() -> None:
    message = UserMessage(
        task_id="pre-routed-task-paths",
        content="Create a Python script that counts rows in a CSV file.",
    )
    structured_route_decision = {
        "intent": "task",
        "confidence": 0.88,
        "taskType": "code_task",
        "missingInputs": [],
        "requiredPermissions": [r"D:\Software Project\Alita\secret.docx"],
        "toolCandidates": [r"D:\secret.docx"],
        "reason": r"Need D:\Software Project\Alita\secret.docx",
        "source": "deterministic",
        "shouldClarify": False,
        "clarificationPrompt": None,
    }
    run_state = AgentRunState.from_user_message(message).model_copy(
        update={
            "intent": "task",
            "goal_spec": parse_goal_spec(message),
            "structured_route_decision": structured_route_decision,
        }
    )

    events = run_agent_from_state(run_state)

    graph = events[0].payload["graph"]
    route_decision_dump = repr(graph["metadata"]["routeDecision"])
    assert r"D:\Software Project\Alita\secret.docx" not in route_decision_dump
    assert r"D:\secret.docx" not in route_decision_dump
    assert "secret.docx" not in route_decision_dump
    assert "Software Project" not in route_decision_dump
    assert graph["metadata"]["plannerChain"]["routeSource"] == (
        graph["metadata"]["routeDecision"]["source"]
    )
    assert graph["metadata"]["plannerChain"]["taskType"] == (
        graph["metadata"]["routeDecision"]["taskType"]
    )


def test_document_task_graph_records_document_planner_chain_metadata() -> None:
    events = run_agent(
        UserMessage(
            task_id="planner-chain-document",
            content="summarize this document as a PDF report",
            attachments=[
                Attachment(
                    attachment_id="a-planner-chain",
                    name="planner-chain.docx",
                    path="workspace/inputs/planner-chain.docx",
                    size_bytes=100,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        )
    )

    graph = events[0].payload["graph"]
    planner_chain = graph["metadata"]["plannerChain"]
    assert planner_chain["version"] == "planner_chain.v1"
    assert planner_chain["planner"] == "template.document.v1"
    assert planner_chain["strategy"] == "document_template"
    assert planner_chain["taskType"] == "document_processing"
    assert [node["nodeId"] for node in graph["nodes"]] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]


def test_temporary_placeholder_node_gets_default_script_review_state() -> None:
    node = _node(
        node_id="temp-script",
        node_type="temporary_placeholder",
        display_name="临时脚本",
        status="waiting",
        input_ports=[],
        output_ports=[],
        dependencies=[],
        summary="待审查的临时脚本。",
        position={"x": 0, "y": 0},
    )

    assert node["scriptReview"]["status"] == "not_reviewed"
    assert node["scriptReview"]["summary"] == "临时脚本节点当前仅可审查，尚不能执行。"
    assert isinstance(node["scriptReview"]["permissions"], list)


def test_graph_node_parses_planning_temporary_script_estimates_and_runtime_notices() -> None:
    graph = RunGraph(
        graphId="routing-plan",
        nodes=[
            {
                "nodeId": "plan-task",
                "nodeType": "planning",
                "displayName": "Plan task",
                "status": "completed",
                "summary": "Decides the execution shape.",
                "createdBy": "agent",
                "position": {"x": 0, "y": 0},
                "estimate": {
                    "durationMs": 250,
                    "cpu": "low",
                    "memory": "low",
                    "network": "none",
                },
                "resourceUsage": {
                    "cpu": "low",
                    "memory": "low",
                    "network": "none",
                },
            },
            {
                "nodeId": "script-gap-fill",
                "nodeType": "temporary_script",
                "displayName": "Temporary script",
                "status": "needs_permission",
                "summary": "Reviews a temporary script before execution.",
                "createdBy": "agent",
                "dependencies": ["plan-task"],
                "position": {"x": 120, "y": 120},
                "scriptReview": {
                    "status": "not_reviewed",
                    "summary": "Needs approval before running.",
                    "permissions": ["read_workspace"],
                    "riskLevel": "high",
                    "requiresApproval": True,
                    "codePreview": "print('preview')",
                    "inputContract": {"path": "string"},
                    "outputContract": {"result": "string"},
                    "approvalFingerprint": None,
                },
                "estimate": {
                    "durationMs": 1000,
                    "cpu": "medium",
                    "memory": "low",
                    "network": "none",
                },
                "resourceUsage": {
                    "cpu": "medium",
                    "memory": "low",
                    "network": "none",
                },
                "runtimeNotice": {
                    "kind": "estimate_exceeded",
                    "message": "Node exceeded its estimate.",
                    "actualDurationMs": 1500,
                },
            },
        ],
        edges=[
            {
                "id": "plan-task-script-gap-fill",
                "source": "plan-task",
                "target": "script-gap-fill",
            }
        ],
    )

    assert graph.nodes[0].nodeType == "planning"
    assert graph.nodes[0].estimate is not None
    assert graph.nodes[0].estimate.durationMs == 250
    assert graph.nodes[0].resourceUsage == {
        "cpu": "low",
        "memory": "low",
        "network": "none",
    }
    script_node = graph.nodes[1]
    assert script_node.nodeType == "temporary_script"
    assert script_node.scriptReview is not None
    assert script_node.scriptReview.riskLevel == "high"
    assert script_node.scriptReview.requiresApproval is True
    assert script_node.scriptReview.codePreview == "print('preview')"
    assert script_node.scriptReview.inputContract == {"path": "string"}
    assert script_node.scriptReview.outputContract == {"result": "string"}
    assert script_node.runtimeNotice is not None
    assert script_node.runtimeNotice.actualDurationMs == 1500


def test_graph_node_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        GraphNode(
            nodeId="node-invalid-status",
            nodeType="fixed_tool",
            displayName="Invalid status",
            status="invalid",
            summary="Invalid status should be rejected.",
            createdBy="test",
            position={"x": 0, "y": 0},
        )
