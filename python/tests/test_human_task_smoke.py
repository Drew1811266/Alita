from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_service.agent_run_state import AgentRunState
from agent_service.agent_runtime_engine import AgentRuntimeEngine
from agent_service.execution import PlannedTaskExecutor
from agent_service.execution_graph import compile_execution_graph
from agent_service.intent import classify_route
from agent_service.schemas import AgentEvent, RunGraph, RunGraphRequest, UserMessage
from agent_service.tool_protocol import ToolResultContent, UnifiedToolResult
from agent_service.web_research import answer_simple_web_inquiry, build_research_graph
from agent_service.web_search import SearchResponse, SearchResult


ENGLISH_FIXED_ERRORS = (
    "I could not complete",
    "I could not find reliable",
    "The input is empty",
    "Search provider failed.",
)


class FakeSearchProvider:
    def __init__(self, response: SearchResponse) -> None:
        self.response = response
        self.queries: list[str] = []

    def search(self, query: str) -> SearchResponse:
        self.queries.append(query)
        return self.response


class FakeWeatherProvider:
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
                "observedAt": "2026-06-07T10:00",
            },
            sources=[{"title": "Open-Meteo", "url": "https://open-meteo.com/"}],
            metadata={"provider": "open_meteo"},
        )

    def forecast(self, location: str, *, locale: str = "zh-CN"):
        return self.current(location, locale=locale)


class FakeHumanModel:
    def __init__(self, route: str, *, reply: str = "你好，我在。") -> None:
        self.route = route
        self.reply = reply
        self.semantic_calls = 0
        self.answer_calls = 0

    def chat(self, messages, *, temperature=None, max_tokens=None, policy=None) -> str:
        del temperature, max_tokens, policy
        if _is_semantic_router_call(messages):
            self.semantic_calls += 1
            return json.dumps(_semantic_route_payload(self.route))
        self.answer_calls += 1
        return self.reply

    def stream_chat(self, messages, *, temperature=None, max_tokens=None, policy=None):
        del messages, temperature, max_tokens, policy
        yield self.reply


def test_human_smoke_empty_input_and_missing_document_are_chinese_guards() -> None:
    def deep_runtime(message: UserMessage, **kwargs):
        del message, kwargs
        raise AssertionError("deterministic input guard should run before model")

    engine = AgentRuntimeEngine(deep_runtime_runner=deep_runtime)
    empty = engine.run_from_state(
        AgentRunState.from_user_message(
            UserMessage(task_id="human-empty", content=" ")
        ).model_copy(update={"project_path": "D:/Project/demo.alita"})
    )
    missing_doc = engine.run_from_state(
        AgentRunState.from_user_message(
            UserMessage(task_id="human-doc", content="帮我把这个文档整理成中文报告")
        ).model_copy(update={"project_path": "D:/Project/demo.alita"})
    )

    assert empty.events[-1].type == "input.required"
    assert empty.events[-1].payload["prompt"] == "请先输入你想让我处理的问题或任务。"
    assert missing_doc.events[-1].type == "input.required"
    assert missing_doc.events[-1].payload["prompt"] == "请先添加需要处理的文档。"
    assert _language_ok([*empty.events, *missing_doc.events])


def test_human_smoke_weather_and_simple_web_use_tools_with_chinese_output() -> None:
    weather_message = UserMessage(task_id="human-weather", content="今天上海天气怎么样？")
    weather_event = answer_simple_web_inquiry(
        weather_message,
        classify_route(weather_message),
        weather_provider=FakeWeatherProvider(),
    )
    web_provider = FakeSearchProvider(
        SearchResponse(
            results=[
                SearchResult(
                    title="Python Downloads",
                    url="https://www.python.org/downloads/",
                    snippet="Official Python downloads page.",
                    sourceType="official",
                    accepted=True,
                )
            ]
        )
    )
    web_message = UserMessage(
        task_id="human-web",
        content="现在最新的 Python 稳定版本是什么？请给出来源。",
    )
    web_event = answer_simple_web_inquiry(
        web_message,
        classify_route(web_message),
        search_provider=web_provider,
    )

    assert weather_event.type == "message.created"
    assert "上海当前天气" in weather_event.payload["message"]["content"]
    assert web_provider.queries == [web_message.content]
    assert web_event.type == "message.created"
    assert "Python Downloads" in web_event.payload["message"]["content"]
    assert web_event.payload["sources"][0]["url"] == "https://www.python.org/downloads/"
    assert _language_ok([weather_event, web_event])


def test_semantic_router_handles_non_keyword_greeting_and_task_forms() -> None:
    greeting_model = FakeHumanModel(route="response_only")
    greeting_result = AgentRuntimeEngine().run_from_state(
        AgentRunState.from_user_message(
            UserMessage(task_id="human-semantic-greeting", content="早啊，今天状态怎么样")
        ).model_copy(update={"project_path": "D:/Project/demo.alita"}),
        model_client=greeting_model,
    )

    greeting_types = [event.type for event in greeting_result.events]
    assert "message.created" in greeting_types
    assert "node_graph.created" not in greeting_types
    assert greeting_model.semantic_calls == 1
    assert greeting_model.answer_calls == 1

    deep_calls: list[UserMessage] = []

    def deep_runtime(message: UserMessage, **kwargs):
        del kwargs
        deep_calls.append(message)
        return [
            AgentEvent(
                type="node_graph.created",
                payload={
                    "graph": {
                        "graphId": "human-semantic-task",
                        "nodes": [],
                        "edges": [],
                    }
                },
            )
        ]

    task_model = FakeHumanModel(route="deep_planning")
    task_result = AgentRuntimeEngine(deep_runtime_runner=deep_runtime).run_from_state(
        AgentRunState.from_user_message(
            UserMessage(
                task_id="human-semantic-task",
                content="我想把这件事整理成一个能交付给同事的结果",
            )
        ).model_copy(update={"project_path": "D:/Project/demo.alita"}),
        model_client=task_model,
    )

    assert task_model.semantic_calls == 1
    assert len(deep_calls) == 1
    assert any(event.type == "node_graph.created" for event in task_result.events)


def test_human_smoke_complex_web_planning_contains_executable_web_nodes() -> None:
    message = UserMessage(
        task_id="human-pc-build",
        content="请联网搜集电脑配件价格，组装一台一万元左右的电脑，并写成中文文档。",
    )

    graph_payload = build_research_graph(message, classify_route(message))
    request = RunGraphRequest(
        task_id=message.task_id,
        project_path="D:/Project/demo.alita",
        graph=RunGraph.model_validate(graph_payload),
        approved_permissions=["network"],
    )
    execution_graph = compile_execution_graph(request)

    tool_ids = [
        node.tool_binding.tool_id
        for node in execution_graph.nodes
        if node.tool_binding is not None
    ]
    assert "web.search.parallel" in tool_ids
    assert "web.fetch.sources" in tool_ids
    assert execution_graph.node_by_id("research-parallel-search").tool_binding is not None


def test_human_smoke_confirmed_web_graph_executes_search_and_fetch(tmp_path: Path) -> None:
    request = _web_execution_request(tmp_path)
    gateway = _FakeWebGateway()
    executor = PlannedTaskExecutor(
        request,
        tool_gateway=gateway,
        execution_graph=compile_execution_graph(request),
    )

    search_output = executor.run("web-search", {})
    fetch_output = executor.run("web-fetch", {"web-search": search_output})

    assert gateway.tool_ids == [
        "internal:web.search.parallel",
        "internal:web.fetch.sources",
    ]
    assert search_output.values["results"][0]["url"] == "https://example.com/cpu"
    assert fetch_output.values["sourceContents"][0]["text"] == "CPU price page"


def test_human_smoke_current_graph_feedback_routes_to_replanned() -> None:
    def deep_runtime(message: UserMessage, **kwargs):
        del message, kwargs
        raise AssertionError("graph feedback should run before Deep Agent")

    engine = AgentRuntimeEngine(deep_runtime_runner=deep_runtime)
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="human-feedback",
            content="Add constraint: use only CSV sources.",
        ),
        current_graph=_existing_graph(),
    ).model_copy(update={"project_path": "D:/Project/demo.alita"})

    result = engine.run_from_state(run_state)

    assert [event.type for event in result.events][-1:] == ["graph.replanned"]
    assert result.events[-2].payload["delta"]["decision"]["kind"] == "graph_feedback"


def _web_execution_request(tmp_path: Path) -> RunGraphRequest:
    nodes = [
        _node("web-search", "fixed_tool", [], tool_ref="web.search.parallel"),
        _node("web-fetch", "fixed_tool", ["web-search"], tool_ref="web.fetch.sources"),
    ]
    return RunGraphRequest(
        task_id="human-web-execution",
        project_path=str(tmp_path / "project.alita"),
        approved_permissions=["network"],
        graph={
            "graphId": "human-web-execution-graph",
            "nodes": nodes,
            "edges": [
                {"id": "web-search-web-fetch", "source": "web-search", "target": "web-fetch"}
            ],
            "metadata": {
                "taskKind": "web_research",
                "objective": "组装一台一万元左右的电脑配置",
            },
        },
    )


def _node(
    node_id: str,
    node_type: str,
    dependencies: list[str],
    *,
    tool_ref: str | None = None,
) -> dict:
    node = {
        "nodeId": node_id,
        "nodeType": node_type,
        "displayName": node_id,
        "status": "waiting",
        "inputPorts": [],
        "outputPorts": [],
        "dependencies": dependencies,
        "summary": node_id,
        "createdBy": "agent",
        "position": {"x": 0, "y": 0},
        "permissionsRequired": ["network"] if tool_ref else [],
    }
    if tool_ref:
        node["toolRef"] = tool_ref
    return node


class _FakeWebGateway:
    def __init__(self) -> None:
        self.tool_ids: list[str] = []

    def call_tool(self, invocation, *, timeout_ms=None):
        del timeout_ms
        self.tool_ids.append(invocation.tool_id)
        if invocation.tool_id == "internal:web.search.parallel":
            return UnifiedToolResult(
                ok=True,
                content=[
                    ToolResultContent(
                        type="json",
                        value={
                            "results": [
                                {
                                    "title": "CPU",
                                    "url": "https://example.com/cpu",
                                    "snippet": "CPU price",
                                }
                            ]
                        },
                    )
                ],
                structured_content={
                    "results": [
                        {
                            "title": "CPU",
                            "url": "https://example.com/cpu",
                            "snippet": "CPU price",
                        }
                    ]
                },
                artifacts=[],
                metadata={},
            )
        return UnifiedToolResult(
            ok=True,
            content=[
                ToolResultContent(
                    type="json",
                    value={
                        "sourceContents": [
                            {
                                "url": "https://example.com/cpu",
                                "title": "CPU",
                                "text": "CPU price page",
                            }
                        ]
                    },
                )
            ],
            structured_content={
                "sourceContents": [
                    {
                        "url": "https://example.com/cpu",
                        "title": "CPU",
                        "text": "CPU price page",
                    }
                ]
            },
            artifacts=[],
            metadata={},
        )


def _existing_graph() -> RunGraph:
    return RunGraph(
        graphId="human-existing-graph",
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


def _language_ok(events: list[AgentEvent]) -> bool:
    payload = json.dumps(
        [event.model_dump() for event in events],
        ensure_ascii=False,
    )
    return not any(marker in payload for marker in ENGLISH_FIXED_ERRORS)


def _semantic_route_payload(route: str) -> dict[str, Any]:
    requires_graph = route in {"deep_planning", "research_planning"}
    requires_web = route in {"web_answer", "research_planning"}
    return {
        "route": route,
        "intent": "human_smoke",
        "complexity": "simple" if route == "response_only" else "multi_step",
        "requiresGraph": requires_graph,
        "requiresTools": requires_graph or requires_web,
        "requiresWeb": requires_web,
        "requiresFiles": False,
        "requiresClarification": False,
        "language": "zh",
        "confidence": 0.95,
        "contextUsed": ["current_message"],
        "missingInputs": [],
        "requiredCapabilities": [],
        "toolCandidates": [],
        "reason": "语义路由烟测。",
    }


def _is_semantic_router_call(messages) -> bool:
    return bool(messages and "Semantic Router" in getattr(messages[0], "content", ""))
