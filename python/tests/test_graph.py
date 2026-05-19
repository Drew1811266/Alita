from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_service.graph import _node, run_agent, stream_agent_events
from agent_service.model_client import ChatMessage
from agent_service.schemas import Attachment, GraphNode, UserMessage


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


def test_missing_attachment_requests_input_for_document_task() -> None:
    events = run_agent(UserMessage(task_id="task-1", content="帮我处理这个文档"))

    assert len(events) == 1
    assert events[0].type == "input.required"
    assert events[0].payload["prompt"] == "请把需要处理的文件添加到聊天框里。"
    assert events[0].payload["missing"] == ["document_file"]


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
    assert set(graph) == {"graphId", "nodes", "edges"}
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
    assert graph["nodes"][2]["modelRef"] == "local-content-organizer"
    assert graph["nodes"][3]["modelRef"] == "local-report-writer"
    assert {
        "id": "typst-export-file-export",
        "source": "typst-export",
        "target": "file-export",
    } in graph["edges"]


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
