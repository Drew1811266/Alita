from __future__ import annotations

from agent_service.goal_spec import parse_goal_spec
from agent_service.schemas import Attachment, UserMessage


def _attachment() -> Attachment:
    return Attachment(
        attachment_id="att-1",
        name="source.docx",
        path="workspace/inputs/source.docx",
        size_bytes=1024,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def test_plain_chat_parses_to_read_only_chat_goal() -> None:
    spec = parse_goal_spec(
        UserMessage(task_id="task-chat", content="你好，请介绍一下你自己")
    )

    assert spec.goal == "你好，请介绍一下你自己"
    assert spec.task_type == "chat"
    assert spec.deliverable == "chat_answer"
    assert spec.missing_inputs == []
    assert spec.needs_web is False
    assert spec.risk_level == "read_only"


def test_document_task_with_attachment_requests_pdf_report_artifact() -> None:
    spec = parse_goal_spec(
        UserMessage(
            task_id="task-document",
            content="请总结这个文档并生成 PDF 报告",
            attachments=[_attachment()],
        )
    )

    assert spec.task_type == "document_processing"
    assert spec.deliverable == "pdf_report"
    assert spec.missing_inputs == []
    assert "read_attachment" in spec.permissions_required
    assert "write_project_artifact" in spec.permissions_required
    assert "生成可打开的本地 artifact" in spec.success_criteria


def test_document_task_without_attachment_requests_missing_document_file() -> None:
    spec = parse_goal_spec(
        UserMessage(task_id="task-document", content="请总结这个文档并生成报告")
    )

    assert spec.task_type == "document_processing"
    assert spec.deliverable == "markdown_report"
    assert spec.missing_inputs == ["document_file"]
    assert spec.needs_user_confirmation is False


def test_english_profile_summary_remains_chat() -> None:
    spec = parse_goal_spec(
        UserMessage(task_id="task-chat", content="please summarize my profile")
    )

    assert spec.task_type == "chat"
    assert spec.deliverable == "chat_answer"


def test_english_files_summary_requests_missing_document_file() -> None:
    spec = parse_goal_spec(
        UserMessage(task_id="task-document", content="please summarize my files")
    )

    assert spec.task_type == "document_processing"
    assert spec.missing_inputs == ["document_file"]


def test_explicit_network_request_requires_web_confirmation() -> None:
    spec = parse_goal_spec(
        UserMessage(task_id="task-research", content="联网搜索最新的 Tauri 发布版本")
    )

    assert spec.task_type == "research"
    assert spec.needs_web is True
    assert spec.needs_user_confirmation is True
    assert spec.risk_level == "network"
    assert "network" in spec.permissions_required
