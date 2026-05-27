from __future__ import annotations

import pytest

from agent_service import intent
from agent_service.intent import (
    InquiryMode,
    IntentKind,
    classify_route,
)
from agent_service.schemas import Attachment, UserMessage


@pytest.mark.parametrize(
    ("content", "expected_reason"),
    [
        ("hello, thanks for your help", "conversation"),
        ("你好，谢谢你", "conversation"),
    ],
)
def test_classifies_direct_conversation_as_chat(
    content: str,
    expected_reason: str,
) -> None:
    decision = classify_route(UserMessage(task_id="chat", content=content))

    assert decision.intent.kind == IntentKind.CHAT
    assert decision.inquiry is None
    assert expected_reason in decision.reason
    assert decision.missing_inputs == []


@pytest.mark.parametrize(
    "content",
    [
        "What files are attached to this conversation?",
        "这个项目里的 agent_service/graph.py 是做什么的？",
    ],
)
def test_classifies_local_context_questions_as_local_inquiry(content: str) -> None:
    decision = classify_route(UserMessage(task_id="local", content=content))

    assert decision.intent.kind == IntentKind.INQUIRY
    assert decision.inquiry is not None
    assert decision.inquiry.mode == InquiryMode.LOCAL
    assert decision.inquiry.requires_web is False
    assert decision.missing_inputs == []


@pytest.mark.parametrize(
    "content",
    [
        "What is the latest Python release?",
        "今天 Qwen3 的官方模型信息是什么？",
    ],
)
def test_classifies_current_factual_questions_as_simple_web_inquiry(
    content: str,
) -> None:
    decision = classify_route(UserMessage(task_id="web-simple", content=content))

    assert decision.intent.kind == IntentKind.INQUIRY
    assert decision.inquiry is not None
    assert decision.inquiry.mode == InquiryMode.WEB_SIMPLE
    assert decision.inquiry.requires_web is True


@pytest.mark.parametrize(
    "content",
    [
        "Research and compare the best local LLM runtimes for a design proposal.",
        "调研并比较 RAG 方案，输出详细文档和流程图。",
    ],
)
def test_classifies_research_and_design_questions_as_complex_web_inquiry(
    content: str,
) -> None:
    decision = classify_route(UserMessage(task_id="web-complex", content=content))

    assert decision.intent.kind == IntentKind.INQUIRY
    assert decision.inquiry is not None
    assert decision.inquiry.mode == InquiryMode.WEB_COMPLEX
    assert decision.inquiry.requires_web is True


@pytest.mark.parametrize(
    "content",
    [
        "Can you create a Python script?",
        "Can you update graph.py?",
        "Create a Python script that summarizes these notes.",
        "帮我修改 graph.py 并生成测试。",
    ],
)
def test_classifies_creation_and_modification_requests_as_task(content: str) -> None:
    decision = classify_route(UserMessage(task_id="task", content=content))

    assert decision.intent.kind == IntentKind.TASK
    assert decision.inquiry is None
    assert decision.missing_inputs == []


@pytest.mark.parametrize(
    "content",
    [
        "",
        "请总结这个文件",
        "Please summarize the attached PDF",
    ],
)
def test_classifies_empty_or_missing_document_input_as_need_input(content: str) -> None:
    decision = classify_route(UserMessage(task_id="missing", content=content))

    assert decision.intent.kind == IntentKind.NEED_INPUT
    assert decision.inquiry is None
    if content:
        assert decision.missing_inputs == ["document_file"]
    else:
        assert decision.missing_inputs == ["message"]


@pytest.mark.parametrize(
    "content",
    [
        "How do I update Python?",
        "How do I fix this error?",
        "Can you explain how to update Python?",
        "Could you tell me how to fix this error?",
        "Please explain how to update Python.",
    ],
)
def test_classifies_how_to_questions_with_task_verbs_as_local_inquiry(
    content: str,
) -> None:
    decision = classify_route(UserMessage(task_id="how-to", content=content))

    assert decision.intent.kind == IntentKind.INQUIRY
    assert decision.inquiry is not None
    assert decision.inquiry.mode == InquiryMode.LOCAL
    assert decision.inquiry.requires_web is False
    assert decision.missing_inputs == []


def test_classifies_how_to_question_with_current_marker_as_simple_web_inquiry() -> None:
    decision = classify_route(
        UserMessage(task_id="how-to-web", content="How do I update to the latest Python?")
    )

    assert decision.intent.kind == IntentKind.INQUIRY
    assert decision.inquiry is not None
    assert decision.inquiry.mode == InquiryMode.WEB_SIMPLE
    assert decision.inquiry.requires_web is True
    assert decision.missing_inputs == []


def test_classifies_latest_stable_release_question_as_simple_web_inquiry() -> None:
    decision = classify_route(
        UserMessage(
            task_id="latest-release",
            content="What is the latest stable Python release?",
        )
    )

    assert decision.intent.kind == IntentKind.INQUIRY
    assert decision.inquiry is not None
    assert decision.inquiry.mode == InquiryMode.WEB_SIMPLE
    assert decision.inquiry.requires_web is True
    assert decision.missing_inputs == []


def test_route_payload_does_not_leak_local_paths_into_external_query_fields() -> None:
    local_path = r"C:\Users\Drew\Projects\Alita\python\agent_service\graph.py"
    project_path = r"D:\Software Project\Alita"
    model_path = r"C:\models\qwen\qwen2.5-coder.gguf"
    decision = classify_route(
        UserMessage(
            task_id="privacy",
            content=(
                f"Using {local_path} in project {project_path}, explain "
                f"the local model at {model_path} with the latest official docs."
            ),
        )
    )

    assert decision.intent.kind == IntentKind.INQUIRY
    assert decision.inquiry is not None
    assert decision.inquiry.mode == InquiryMode.WEB_SIMPLE

    payload = decision.to_payload()
    assert "query" not in payload
    assert "web_query" not in payload
    assert "search_query" not in payload
    assert local_path not in repr(payload)
    assert project_path not in repr(payload)
    assert model_path not in repr(payload)


def test_attachment_document_processing_request_is_structured_task_without_path_leak() -> None:
    attachment_path = r"C:\Users\Drew\Projects\Alita\inputs\notes.docx"
    decision = classify_route(
        UserMessage(
            task_id="attached-document-task",
            content="请整理这个文档",
            attachments=[
                Attachment(
                    attachment_id="doc-1",
                    name="notes.docx",
                    path=attachment_path,
                    size_bytes=128,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        )
    )

    assert decision.intent.kind == IntentKind.TASK
    assert decision.inquiry is None
    assert decision.missing_inputs == []
    assert attachment_path not in decision.reason
    assert attachment_path not in repr(decision.to_payload())


def test_document_keyword_tables_do_not_contain_mojibake_tokens() -> None:
    keyword_dump = "\n".join(
        [*intent._DOCUMENT_ACTIONS, *intent._DOCUMENT_REFERENCES]
    )

    for marker in ["澶", "鏁", "鎬", "鎽", "鎻", "鍒", "鏀", "缈", "闄", "璧", "鍥", "闊", "瑙", "琛"]:
        assert marker not in keyword_dump


def test_chinese_document_request_without_attachment_requires_document_file() -> None:
    decision = classify_route(UserMessage(task_id="cn-doc-missing", content="请总结这个文档"))

    assert decision.intent.kind == IntentKind.NEED_INPUT
    assert decision.missing_inputs == ["document_file"]


def test_chinese_document_request_with_attachment_routes_to_task() -> None:
    decision = classify_route(
        UserMessage(
            task_id="cn-doc-task",
            content="请整理附件并导出报告",
            attachments=[
                Attachment(
                    attachment_id="doc-1",
                    name="notes.docx",
                    path=r"C:\Users\Drew\Desktop\notes.docx",
                    size_bytes=128,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        )
    )

    assert decision.intent.kind == IntentKind.TASK
    assert decision.missing_inputs == []


@pytest.mark.parametrize("with_attachment", [False, True])
def test_chinese_web_research_document_output_routes_to_complex_web_before_document_task(
    with_attachment: bool,
) -> None:
    attachments = []
    if with_attachment:
        attachments.append(
            Attachment(
                attachment_id="old-doc",
                name="old-context.docx",
                path=r"C:\Users\Drew\Desktop\old-context.docx",
                size_bytes=128,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        )

    decision = classify_route(
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
            attachments=attachments,
        )
    )

    assert decision.intent.kind == IntentKind.INQUIRY
    assert decision.inquiry is not None
    assert decision.inquiry.mode == InquiryMode.WEB_COMPLEX
    assert decision.inquiry.requires_web is True
    assert decision.missing_inputs == []
