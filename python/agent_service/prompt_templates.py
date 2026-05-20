from __future__ import annotations

from agent_service.model_client import ChatMessage


class PromptTemplateError(ValueError):
    pass


_SYSTEM_PROMPTS = {
    "document.content_organizer.zh.v1": (
        "你是文档内容整理助手。请基于用户提供的文档正文，提炼层级清晰、"
        "忠于原文的结构化提纲。"
    ),
    "document.report_writer.zh.v1": (
        "你是报告写作助手。请基于用户提供的文档正文，撰写清晰、完整、"
        "可用于交付的中文报告。"
    ),
}


def render_prompt_template(template_id: str, values: dict[str, str]) -> list[ChatMessage]:
    try:
        system_prompt = _SYSTEM_PROMPTS[template_id]
    except KeyError as error:
        raise PromptTemplateError(f"unknown prompt template: {template_id}") from error

    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=values.get("text", "")),
    ]
