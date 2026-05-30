from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from agent_service.schemas import UserMessage
from agent_service.tool_router import route_tool_for_message


class IntentKind(str, Enum):
    CHAT = "chat"
    INQUIRY = "inquiry"
    TASK = "task"
    NEED_INPUT = "need_input"


class InquiryMode(str, Enum):
    LOCAL = "local"
    WEB_SIMPLE = "web_simple"
    WEB_COMPLEX = "web_complex"


@dataclass(frozen=True)
class IntentDecision:
    kind: IntentKind

    def to_payload(self) -> dict:
        return {"kind": self.kind.value}


@dataclass(frozen=True)
class InquiryDecision:
    mode: InquiryMode
    requires_web: bool

    def to_payload(self) -> dict:
        return {
            "mode": self.mode.value,
            "requires_web": self.requires_web,
        }


@dataclass(frozen=True)
class RouteDecision:
    intent: IntentDecision
    inquiry: InquiryDecision | None
    reason: str
    missing_inputs: list[str]

    def to_payload(self) -> dict:
        return {
            "intent": self.intent.to_payload(),
            "inquiry": self.inquiry.to_payload() if self.inquiry else None,
            "reason": self.reason,
            "missing_inputs": list(self.missing_inputs),
        }


def classify_route(message: UserMessage) -> RouteDecision:
    content = message.content.strip()
    has_attachments = bool(message.attachments)

    if not content:
        if has_attachments:
            return _route(IntentKind.TASK, "attached document task")
        return _route(IntentKind.NEED_INPUT, "empty input needs user content", ["message"])

    tool_route = route_tool_for_message(message)
    if tool_route is not None and tool_route.tool_name.startswith("weather."):
        return _route(
            IntentKind.INQUIRY,
            "message routes to weather tool",
            list(tool_route.missing_inputs),
            inquiry=InquiryDecision(InquiryMode.WEB_SIMPLE, True),
        )

    has_document_reference = _contains_any(content, _DOCUMENT_REFERENCES)
    has_document_action = _contains_any(content, _DOCUMENT_ACTIONS)

    if _is_complex_web_request(content):
        return _route(
            IntentKind.INQUIRY,
            "request needs web research and report synthesis",
            inquiry=InquiryDecision(InquiryMode.WEB_COMPLEX, True),
        )

    if has_attachments and (has_document_reference or has_document_action):
        return _route(IntentKind.TASK, "attached document task")

    if not has_attachments and has_document_reference and has_document_action:
        return _route(
            IntentKind.NEED_INPUT,
            "document task is missing a document attachment",
            ["document_file"],
        )

    if _is_polite_task_request(content):
        return _route(IntentKind.TASK, "user requested creation, modification, or execution")

    if _contains_any(content, _QUESTION_MARKERS):
        if _contains_any(content, _COMPLEX_WEB_MARKERS):
            return _route(
                IntentKind.INQUIRY,
                "question requests research, comparison, or design synthesis",
                inquiry=InquiryDecision(InquiryMode.WEB_COMPLEX, True),
            )
        if _contains_any(content, _WEB_NEEDED_MARKERS):
            return _route(
                IntentKind.INQUIRY,
                "question requests current or external factual data",
                inquiry=InquiryDecision(InquiryMode.WEB_SIMPLE, True),
            )
        return _route(
            IntentKind.INQUIRY,
            "question can be answered from local context or the model",
            inquiry=InquiryDecision(InquiryMode.LOCAL, False),
        )

    if _contains_any(content, _TASK_ACTIONS):
        return _route(IntentKind.TASK, "user requested creation, modification, or execution")

    if _contains_any(content, _COMPLEX_WEB_MARKERS):
        return _route(
            IntentKind.INQUIRY,
            "request needs research, comparison, or design synthesis",
            inquiry=InquiryDecision(InquiryMode.WEB_COMPLEX, True),
        )

    if _contains_any(content, _WEB_NEEDED_MARKERS):
        return _route(
            IntentKind.INQUIRY,
            "request needs current or external factual data",
            inquiry=InquiryDecision(InquiryMode.WEB_SIMPLE, True),
        )

    return _route(IntentKind.CHAT, "conversation")


def should_route_document_task(
    message: UserMessage,
    decision: RouteDecision | None = None,
) -> bool:
    route_decision = decision or classify_route(message)
    if route_decision.intent.kind != IntentKind.TASK or not message.attachments:
        return False

    content = message.content.strip()
    if not content:
        return True

    return _is_document_request(content)


def _route(
    intent: IntentKind,
    reason: str,
    missing_inputs: list[str] | None = None,
    inquiry: InquiryDecision | None = None,
) -> RouteDecision:
    return RouteDecision(
        intent=IntentDecision(intent),
        inquiry=inquiry,
        reason=reason,
        missing_inputs=missing_inputs or [],
    )


def _contains_any(content: str, keywords: list[str]) -> bool:
    normalized = content.lower()
    return any(_contains_keyword(normalized, keyword.lower()) for keyword in keywords)


def _contains_keyword(normalized_content: str, normalized_keyword: str) -> bool:
    if normalized_keyword.isascii() and any(
        character.isalpha() for character in normalized_keyword
    ):
        pattern = rf"(?<![a-z0-9_]){re.escape(normalized_keyword)}(?![a-z0-9_])"
        return re.search(pattern, normalized_content) is not None
    return normalized_keyword in normalized_content


def _is_document_request(content: str) -> bool:
    return _contains_any(content, _DOCUMENT_ACTIONS) or _contains_any(
        content,
        _DOCUMENT_REFERENCES,
    )


def _is_complex_web_request(content: str) -> bool:
    if not _contains_any(content, [*_WEB_NEEDED_MARKERS, *_ADDITIONAL_WEB_NEEDED_MARKERS]):
        return False
    return _contains_any(
        content,
        [*_COMPLEX_WEB_MARKERS, *_ADDITIONAL_COMPLEX_WEB_MARKERS],
    )


def _is_polite_task_request(content: str) -> bool:
    if not _contains_any(content, _TASK_ACTIONS):
        return False
    if _is_instructional_inquiry(content):
        return False

    normalized = content.strip().lower()
    return normalized.startswith(
        (
            "can you ",
            "could you ",
            "please ",
            "帮我",
            "请你",
            "能不能",
            "可以帮我",
        )
    )


def _is_instructional_inquiry(content: str) -> bool:
    return _contains_any(
        content,
        [
            "how do i",
            "how can i",
            "how should i",
            "how to",
            "explain how",
            "tell me how",
            "如何",
            "怎么",
            "解释一下怎么",
            "告诉我怎么",
        ],
    )


_QUESTION_MARKERS = [
    "?",
    "what",
    "why",
    "how",
    "when",
    "where",
    "which",
    "who",
    "tell me",
    "explain",
    "is there",
    "are there",
    "什么",
    "为什么",
    "怎么",
    "如何",
    "多少",
    "哪",
    "谁",
    "是否",
    "吗",
    "？",
]

_ADDITIONAL_WEB_NEEDED_MARKERS = [
    "\u4eca\u5929",
    "\u5f53\u524d",
    "\u6700\u65b0",
    "\u70ed\u95e8",
    "\u6392\u884c",
    "\u6392\u540d",
]

_ADDITIONAL_COMPLEX_WEB_MARKERS = [
    "\u7814\u7a76",
    "\u8c03\u7814",
    "\u5206\u6790",
    "\u6bd4\u8f83",
    "\u5bf9\u6bd4",
    "\u603b\u7ed3",
    "\u6587\u6863",
    "\u62a5\u544a",
    "\u9879\u76ee",
]

_WEB_NEEDED_MARKERS = [
    "current",
    "latest",
    "today",
    "price",
    "ranking",
    "release",
    "law",
    "official docs",
    "github",
    "library version",
    "model info",
    "up to date",
    "recent",
    "现在",
    "当前",
    "最新",
    "今天",
    "价格",
    "排行",
    "排名",
    "发布",
    "版本",
    "法律",
    "法规",
    "官方文档",
    "模型信息",
]

_COMPLEX_WEB_MARKERS = [
    "research",
    "compare",
    "comparison",
    "design",
    "proposal",
    "detailed document",
    "flowchart",
    "architecture",
    "调研",
    "比较",
    "对比",
    "设计",
    "方案",
    "流程图",
    "详细文档",
    "架构",
]

_TASK_ACTIONS = [
    "create",
    "modify",
    "edit",
    "update",
    "write",
    "generate",
    "run",
    "execute",
    "build",
    "fix",
    "implement",
    "refactor",
    "生成",
    "创建",
    "新建",
    "修改",
    "编辑",
    "更新",
    "运行",
    "执行",
    "构建",
    "修复",
    "实现",
    "重构",
]

_DOCUMENT_ACTIONS = [
    "summarize",
    "summary",
    "organize",
    "extract",
    "process",
    "convert",
    "translate",
    "rewrite",
    "analyze",
    "generate",
    "export",
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
]

_DOCUMENT_REFERENCES = [
    "document",
    "file",
    "attachment",
    "attached",
    "material",
    "report",
    "image",
    "audio",
    "video",
    "spreadsheet",
    "pdf",
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
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
]
