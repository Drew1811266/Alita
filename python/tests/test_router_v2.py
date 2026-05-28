from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_service.router_v2 import (
    RouterV2Decision,
    deterministic_route,
    effective_legacy_route_payload,
)
from agent_service.schemas import Attachment, UserMessage


def test_router_v2_decision_payload_uses_frontend_safe_keys() -> None:
    decision = RouterV2Decision(
        intent="task",
        confidence=0.8,
        task_type="code_task",
        missing_inputs=["message"],
        required_permissions=["network"],
        tool_candidates=["weather.current"],
        reason="test route",
        source="deterministic",
        should_clarify=True,
        clarification_prompt="What should I do?",
        legacy_route={"intent": {"kind": "task"}},
    )

    assert decision.to_payload() == {
        "intent": "task",
        "confidence": 0.8,
        "taskType": "code_task",
        "missingInputs": ["message"],
        "requiredPermissions": ["network"],
        "toolCandidates": ["weather.current"],
        "reason": "test route",
        "source": "deterministic",
        "shouldClarify": True,
        "clarificationPrompt": "What should I do?",
        "legacyRoute": {"intent": {"kind": "task"}},
    }


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_router_v2_decision_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(ValidationError):
        RouterV2Decision(
            intent="chat",
            confidence=confidence,
            task_type="chat",
            reason="invalid confidence",
            source="deterministic",
        )


@pytest.mark.parametrize(
    ("content", "expected_intent", "expected_task_type"),
    [
        ("hello, thanks for your help", "chat", "chat"),
        ("What files are attached to this conversation?", "local_inquiry", "chat"),
        ("What is the latest Python release?", "web_simple_inquiry", "research"),
        (
            "Research and compare the best local LLM runtimes for a design proposal.",
            "web_complex_choice",
            "research",
        ),
        ("Can you create a Python script?", "task", "code_task"),
        ("请总结这个文档", "missing_input", "document_processing"),
    ],
)
def test_deterministic_route_matches_existing_router_parity_cases(
    content: str,
    expected_intent: str,
    expected_task_type: str,
) -> None:
    decision = deterministic_route(UserMessage(task_id="parity", content=content))

    assert decision.intent == expected_intent
    assert decision.task_type == expected_task_type


def test_attached_document_route_does_not_leak_attachment_path() -> None:
    attachment_path = r"C:\Users\Drew\Projects\Alita\inputs\notes.docx"
    message = UserMessage(
        task_id="attached-document-task",
        content=f"请整理这个文档 {attachment_path}",
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

    decision = deterministic_route(message)
    payload = decision.to_payload()

    assert decision.intent == "task"
    assert decision.task_type == "document_processing"
    assert attachment_path not in repr(payload)
    assert attachment_path not in decision.reason
    assert all(attachment_path not in candidate for candidate in decision.tool_candidates)


def test_effective_legacy_route_payload_converts_complex_quick_answer_to_simple() -> None:
    message = UserMessage(
        task_id="quick-answer",
        content="Research and compare the best local LLM runtimes for a design proposal.",
    )
    decision = deterministic_route(message, inquiry_choice="quick_answer")

    payload = effective_legacy_route_payload(decision)

    assert decision.intent == "web_simple_inquiry"
    assert payload["inquiry"]["mode"] == "web_simple"
    assert payload["inquiry"]["requires_web"] is True
