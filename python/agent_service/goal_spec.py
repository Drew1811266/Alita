from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from agent_service.schemas import UserMessage


TaskType = Literal[
    "chat",
    "document_processing",
    "research",
    "local_file",
    "content_creation",
    "code_task",
    "automation",
    "unknown",
]
RiskLevel = Literal[
    "read_only",
    "local_write",
    "local_modify",
    "destructive",
    "network",
    "external_comm",
    "system",
]


class GoalSpec(BaseModel):
    goal: str
    task_type: TaskType
    deliverable: str
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    required_context: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    risk_level: RiskLevel
    permissions_required: list[str] = Field(default_factory=list)
    needs_web: bool = False
    needs_user_confirmation: bool = False
    confidence: float


DOCUMENT_ACTION_KEYWORDS = [
    "处理",
    "整理",
    "总结",
    "摘要",
    "提取",
    "分析",
    "改写",
    "翻译",
    "生成",
    "导出",
    "转换",
    "压缩",
    "剪辑",
    "识别",
    "report",
    "summarize",
    "summary",
    "convert",
    "export",
]

DOCUMENT_REFERENCE_KEYWORDS = [
    "文档",
    "文件",
    "附件",
    "资料",
    "报告",
    "图片",
    "图像",
    "音频",
    "视频",
    "表格",
    "pdf",
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "document",
    "file",
    "attachment",
    "spreadsheet",
    "presentation",
]

WEB_KEYWORDS = [
    "联网",
    "搜索",
    "查一下",
    "最新",
    "release",
    "version",
    "github",
    "search",
    "latest",
]


def parse_goal_spec(message: UserMessage) -> GoalSpec:
    content = message.content.strip()
    goal = content or "继续当前对话"
    has_attachments = bool(message.attachments)
    has_web_request = _contains_any(content, WEB_KEYWORDS)
    has_document_action = _contains_any(content, DOCUMENT_ACTION_KEYWORDS)
    has_document_reference = _contains_any(content, DOCUMENT_REFERENCE_KEYWORDS)

    if has_attachments and (not content or has_document_action or has_document_reference):
        deliverable = "pdf_report" if "pdf" in content.lower() else "markdown_report"
        return GoalSpec(
            goal=goal,
            task_type="document_processing",
            deliverable=deliverable,
            success_criteria=["生成可打开的本地 artifact"],
            required_context=["attachment"],
            risk_level="local_write",
            permissions_required=["read_attachment", "write_project_artifact"],
            confidence=0.85,
        )

    if not has_attachments and has_document_action and has_document_reference:
        return GoalSpec(
            goal=goal,
            task_type="document_processing",
            deliverable="markdown_report",
            success_criteria=["等待用户提供文档后生成报告"],
            required_context=["document_file"],
            missing_inputs=["document_file"],
            risk_level="read_only",
            confidence=0.75,
        )

    if has_web_request:
        return GoalSpec(
            goal=goal,
            task_type="research",
            deliverable="research_answer",
            success_criteria=["回答包含联网检索得到的信息"],
            risk_level="network",
            permissions_required=["network"],
            needs_web=True,
            needs_user_confirmation=True,
            confidence=0.8,
        )

    return GoalSpec(
        goal=goal,
        task_type="chat",
        deliverable="chat_answer",
        success_criteria=["回答用户的问题"],
        risk_level="read_only",
        confidence=0.7,
    )


def _contains_any(content: str, keywords: list[str]) -> bool:
    normalized = content.lower()
    return any(_contains_keyword(normalized, keyword.lower()) for keyword in keywords)


def _contains_keyword(normalized_content: str, keyword: str) -> bool:
    if keyword.isascii() and keyword.replace("_", "").isalnum():
        return re.search(rf"\b{re.escape(keyword)}\b", normalized_content) is not None

    return keyword in normalized_content
