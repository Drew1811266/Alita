from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_service.router_v2 import (
    STRUCTURED_ROUTER_ENV,
    RouterV2Decision,
    _build_model_router_messages,
    deterministic_route,
    effective_legacy_route_payload,
    parse_model_route_response,
    route_message,
    structured_router_enabled,
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
    }
    assert decision.legacy_route == {"intent": {"kind": "task"}}


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


def test_model_router_prompt_scrubs_windows_paths_with_spaces_and_path_fragments() -> None:
    windows_path_with_spaces = (
        r"D:\Software Project\Alita\python\agent_service\graph.py"
    )
    ordinary_windows_path = r"C:\Users\Drew\Projects\Alita\README.md"
    unix_path = "/Users/drew/Software Project/Alita/python/agent_service/graph.py"
    message = UserMessage(
        task_id="prompt-scrub",
        content=(
            f"Review {windows_path_with_spaces}, {ordinary_windows_path}, "
            f"and {unix_path}. The phrase Software Project alone is just a label."
        ),
    )

    prompt_dump = repr(_build_model_router_messages(message))

    assert windows_path_with_spaces not in prompt_dump
    assert ordinary_windows_path not in prompt_dump
    assert unix_path not in prompt_dump
    assert "Software Project\\Alita" not in prompt_dump
    assert "Software Project/Alita" not in prompt_dump
    assert "agent_service" not in prompt_dump
    assert "The phrase Software Project alone is just a label." in prompt_dump


def test_model_router_prompt_scrubs_attachment_name_path_fragments() -> None:
    attachment_name_path = r"D:\Software Project\Alita\python\agent_service\graph.py"
    message = UserMessage(
        task_id="attachment-name-scrub",
        content="Review the attached file.",
        attachments=[
            Attachment(
                attachment_id="path-name",
                name=attachment_name_path,
                path=r"C:\safe\staged\attachment.bin",
                size_bytes=128,
                mime_type="text/plain",
            )
        ],
    )

    prompt_dump = repr(_build_model_router_messages(message))

    assert attachment_name_path not in prompt_dump
    assert "Software Project" not in prompt_dump
    assert "agent_service" not in prompt_dump


def test_model_reason_and_tool_candidates_payload_scrub_path_fragments() -> None:
    windows_path_with_spaces = (
        r"D:\Software Project\Alita\python\agent_service\graph.py"
    )
    ordinary_windows_path = r"C:\Users\Drew\Projects\Alita\README.md"
    unix_path = "/Users/drew/Software Project/Alita/python/agent_service/graph.py"
    fallback = deterministic_route(
        UserMessage(task_id="fallback", content="What is the latest Python release?")
    )
    response = {
        "intent": "web_simple_inquiry",
        "confidence": 0.82,
        "task_type": "research",
        "reason": f"Use {windows_path_with_spaces} and {unix_path}",
        "tool_candidates": [
            f"inspect:{ordinary_windows_path}",
            f"inspect:{windows_path_with_spaces}",
            f"inspect:{unix_path}",
        ],
    }

    decision = parse_model_route_response(json.dumps(response), fallback=fallback)
    payload_dump = repr(decision.to_payload())

    assert windows_path_with_spaces not in payload_dump
    assert ordinary_windows_path not in payload_dump
    assert unix_path not in payload_dump
    assert "Software Project\\Alita" not in payload_dump
    assert "Software Project/Alita" not in payload_dump
    assert "agent_service" not in payload_dump


class FakeRouterModelClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    def chat(self, messages: list[object], **kwargs: object) -> str:
        self.calls += 1
        return self.response


def test_structured_router_enabled_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(STRUCTURED_ROUTER_ENV, raising=False)

    assert structured_router_enabled() is False


def test_route_message_env_off_does_not_call_model_and_returns_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(STRUCTURED_ROUTER_ENV, raising=False)
    model_client = FakeRouterModelClient(
        json.dumps(
            {
                "intent": "task",
                "confidence": 0.95,
                "task_type": "code_task",
                "reason": "model route",
            }
        )
    )

    decision = route_message(
        UserMessage(task_id="env-off", content="What is the latest Python release?"),
        model_client=model_client,
    )

    assert model_client.calls == 0
    assert decision.source == "deterministic"
    assert decision.intent == "web_simple_inquiry"


def test_route_message_malformed_model_output_falls_back_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STRUCTURED_ROUTER_ENV, "1")
    model_client = FakeRouterModelClient("not json")

    decision = route_message(
        UserMessage(task_id="bad-model", content="What is the latest Python release?"),
        model_client=model_client,
    )

    assert model_client.calls == 1
    assert decision.source == "fallback"
    assert decision.intent == "web_simple_inquiry"


def test_route_message_invalid_model_payload_falls_back_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STRUCTURED_ROUTER_ENV, "1")
    model_client = FakeRouterModelClient(
        json.dumps(
            {
                "intent": "unknown_intent",
                "confidence": 2.0,
                "task_type": "research",
                "reason": "bad",
            }
        )
    )

    decision = route_message(
        UserMessage(task_id="bad-payload", content="What is the latest Python release?"),
        model_client=model_client,
    )

    assert model_client.calls == 1
    assert decision.source == "fallback"
    assert decision.intent == "web_simple_inquiry"


def test_route_message_string_list_model_payload_falls_back_without_character_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STRUCTURED_ROUTER_ENV, "1")
    model_client = FakeRouterModelClient(
        json.dumps(
            {
                "intent": "missing_input",
                "confidence": 0.9,
                "task_type": "document_processing",
                "missing_inputs": "document_file",
                "reason": "bad list",
            }
        )
    )

    decision = route_message(
        UserMessage(task_id="bad-list", content="What is the latest Python release?"),
        model_client=model_client,
    )

    assert model_client.calls == 1
    assert decision.source == "fallback"
    assert decision.intent == "web_simple_inquiry"
    assert decision.missing_inputs == []


def test_route_message_string_bool_model_payload_falls_back_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STRUCTURED_ROUTER_ENV, "1")
    model_client = FakeRouterModelClient(
        json.dumps(
            {
                "intent": "web_simple_inquiry",
                "confidence": 0.9,
                "task_type": "research",
                "reason": "bad bool",
                "should_clarify": "false",
            }
        )
    )

    decision = route_message(
        UserMessage(task_id="bad-bool", content="What is the latest Python release?"),
        model_client=model_client,
    )

    assert model_client.calls == 1
    assert decision.source == "fallback"
    assert decision.intent == "web_simple_inquiry"


def test_route_message_high_confidence_model_route_returns_model_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STRUCTURED_ROUTER_ENV, "1")
    model_client = FakeRouterModelClient(
        json.dumps(
            {
                "intent": "task",
                "confidence": 0.9,
                "task_type": "code_task",
                "reason": "model selected task",
            }
        )
    )

    decision = route_message(
        UserMessage(task_id="model-task", content="What is the latest Python release?"),
        model_client=model_client,
    )

    assert model_client.calls == 1
    assert decision.source == "model"
    assert decision.intent == "task"
    assert decision.legacy_route["intent"]["kind"] == "task"


def test_route_message_medium_confidence_model_route_asks_for_clarification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STRUCTURED_ROUTER_ENV, "1")
    model_client = FakeRouterModelClient(
        json.dumps(
            {
                "intent": "task",
                "confidence": 0.61,
                "task_type": "code_task",
                "reason": "model selected task but needs confirmation",
            }
        )
    )

    decision = route_message(
        UserMessage(task_id="model-medium", content="Please handle the Python thing."),
        model_client=model_client,
    )

    assert model_client.calls == 1
    assert decision.source == "model"
    assert decision.intent == "missing_input"
    assert decision.missing_inputs == ["clarification"]
    assert decision.should_clarify is True
    assert decision.clarification_prompt is not None
    assert "确认" in decision.clarification_prompt
    assert decision.legacy_route["intent"]["kind"] == "need_input"
    assert decision.legacy_route["missing_inputs"] == ["clarification"]


def test_route_message_low_confidence_model_route_uses_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STRUCTURED_ROUTER_ENV, "1")
    model_client = FakeRouterModelClient(
        json.dumps(
            {
                "intent": "task",
                "confidence": 0.3,
                "task_type": "code_task",
                "reason": "uncertain model route",
            }
        )
    )

    decision = route_message(
        UserMessage(task_id="model-low", content="What is the latest Python release?"),
        model_client=model_client,
    )

    assert model_client.calls == 1
    assert decision.source == "fallback"
    assert decision.intent == "web_simple_inquiry"


def test_route_message_protected_document_processing_does_not_call_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STRUCTURED_ROUTER_ENV, "1")
    model_client = FakeRouterModelClient("not json")

    decision = route_message(
        UserMessage(
            task_id="doc",
            content="请整理这个文档",
            attachments=[
                Attachment(
                    attachment_id="doc-1",
                    name="notes.docx",
                    path=r"C:\Users\Drew\Desktop\notes.docx",
                    size_bytes=128,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        ),
        model_client=model_client,
    )

    assert model_client.calls == 0
    assert decision.source == "deterministic"
    assert decision.task_type == "document_processing"


def test_route_message_protected_weather_route_does_not_call_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STRUCTURED_ROUTER_ENV, "1")
    model_client = FakeRouterModelClient("not json")

    decision = route_message(
        UserMessage(task_id="weather", content="What's the weather in Seattle today?"),
        model_client=model_client,
    )

    assert model_client.calls == 0
    assert decision.source == "deterministic"
    assert decision.intent == "web_simple_inquiry"


def test_route_message_protected_inquiry_choice_does_not_call_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(STRUCTURED_ROUTER_ENV, "1")
    model_client = FakeRouterModelClient("not json")

    decision = route_message(
        UserMessage(
            task_id="choice",
            content="Research and compare local LLM runtimes for a design proposal.",
        ),
        inquiry_choice="quick_answer",
        model_client=model_client,
    )

    assert model_client.calls == 0
    assert decision.source == "deterministic"
    assert decision.intent == "web_simple_inquiry"
