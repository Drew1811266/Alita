from __future__ import annotations

import pytest

from agent_service.model_client import ChatMessage
from agent_service.prompt_templates import PromptTemplateError, render_prompt_template


def test_render_content_organizer_prompt_includes_document_text() -> None:
    messages = render_prompt_template(
        "document.content_organizer.zh.v1",
        {"text": "document body"},
    )

    assert isinstance(messages, list)
    assert messages[0].role == "system"
    assert messages[1] == ChatMessage(role="user", content="document body")


def test_render_report_writer_prompt_prefers_text_input() -> None:
    messages = render_prompt_template(
        "document.report_writer.zh.v1",
        {"text": "document body", "outline": "outline"},
    )

    assert messages[1] == ChatMessage(role="user", content="document body")


@pytest.mark.parametrize("values", [{"text": "   "}, {}])
def test_render_prompt_template_rejects_missing_text(values: dict[str, str]) -> None:
    with pytest.raises(PromptTemplateError, match="missing required input.*text"):
        render_prompt_template("document.report_writer.zh.v1", values)


def test_render_prompt_template_rejects_unknown_template() -> None:
    with pytest.raises(PromptTemplateError, match="unknown prompt template"):
        render_prompt_template("document.unknown.zh.v1", {"text": "document body"})
