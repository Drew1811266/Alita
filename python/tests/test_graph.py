from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_service.graph import (
    _classify_message,
    _node,
    build_graph,
    run_agent,
    stream_agent_events,
)
from agent_service.intent import IntentKind, classify_route
from agent_service.model_client import ChatMessage
from agent_service.schemas import Attachment, GraphNode, RunGraph, UserMessage
from agent_service.web_search import SearchResponse, SearchResult


class FakeModelClient:
    def __init__(self, reply: str = "本地模型回复") -> None:
        self.reply = reply
        self.calls: list[list[ChatMessage]] = []

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        self.calls.append(messages)
        return self.reply

    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ):
        self.calls.append(messages)
        yield "你好"
        yield "，本地模型"


class FakeSearchProvider:
    def __init__(self, response: SearchResponse) -> None:
        self.response = response
        self.queries: list[str] = []

    def search(self, query: str) -> SearchResponse:
        self.queries.append(query)
        return self.response


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
    assert result["events"][0].type == "message.created"


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


def test_web_complex_default_returns_research_choice_required() -> None:
    events = run_agent(
        UserMessage(
            task_id="complex-web",
            content="Research and compare current Python packaging tools",
        )
    )

    assert [event.type for event in events] == ["research.choice_required"]
    assert events[0].payload["choices"] == [
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
    ]


def test_web_complex_quick_answer_choice_searches_and_answers() -> None:
    provider = FakeSearchProvider(
        SearchResponse(
            results=[
                SearchResult(
                    title="Python packaging guide",
                    url="https://packaging.python.org/",
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
    assert events[0].payload["sources"][0]["url"] == "https://packaging.python.org/"


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
        "research-report-synthesis",
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
    assert parse_node["toolRef"] == "document.markitdown_convert"
    assert parse_node["outputPorts"][0]["label"] == "Markdown"
    assert graph["edges"][0] == {
        "id": "document-input-document-parse",
        "source": "document-input",
        "target": "document-parse",
    }
    assert [node["nodeId"] for node in graph["nodes"]] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]
    typst_node = graph["nodes"][4]
    assert typst_node["nodeType"] == "fixed_tool"
    assert typst_node["toolRef"] == "document.typst_compile"
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
    assert result["route_decision"]["intent"]["kind"] == "task"
    assert _classify_message(message) == "document_task"
    assert events[0].type == "node_graph.created"


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
