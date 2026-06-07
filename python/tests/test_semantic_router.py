from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_service.schemas import Attachment, GraphNode, RunGraph, UserMessage
from agent_service.semantic_router import (
    SEMANTIC_ROUTER_MAX_TOKENS,
    SEMANTIC_ROUTER_TIMEOUT_SECONDS,
    SemanticRouteDecision,
    build_semantic_router_messages,
    parse_semantic_route_response,
    route_semantically,
)


class FakeSemanticRouterModel:
    def __init__(
        self,
        responses: list[str] | None = None,
        error: Exception | None = None,
    ):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def chat(self, messages, *, temperature=None, max_tokens=None, policy=None) -> str:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "policy": policy,
            }
        )
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


class TimeoutAwareSemanticRouterModel(FakeSemanticRouterModel):
    def chat(
        self,
        messages,
        *,
        temperature=None,
        max_tokens=None,
        policy=None,
        timeout_seconds=None,
    ) -> str:
        result = super().chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            policy=policy,
        )
        self.calls[-1]["timeout_seconds"] = timeout_seconds
        return result


def _semantic_response(route: str, confidence: float = 0.95) -> str:
    return json.dumps(
        {
            "route": route,
            "intent": "greeting",
            "complexity": "simple",
            "requiresGraph": False,
            "requiresTools": False,
            "requiresWeb": False,
            "requiresFiles": False,
            "requiresClarification": False,
            "language": "zh",
            "confidence": confidence,
            "contextUsed": ["current_message"],
            "missingInputs": [],
            "requiredCapabilities": [],
            "toolCandidates": [],
            "reason": "用户是在问候。",
        }
    )


def test_route_semantically_accepts_compact_route_code() -> None:
    model = FakeSemanticRouterModel(["A"])

    decision = route_semantically(
        UserMessage(task_id="semantic-route-code", content="你好"),
        model_client=model,
    )

    assert decision.route == "response_only"
    assert decision.intent == "route_code"
    assert decision.language == "zh"


def test_semantic_route_decision_payload_is_frontend_safe() -> None:
    decision = SemanticRouteDecision(
        route="response_only",
        intent="greeting",
        complexity="simple",
        requires_graph=False,
        requires_tools=False,
        requires_web=False,
        requires_files=False,
        requires_clarification=False,
        language="zh",
        confidence=0.97,
        context_used=["current_message"],
        missing_inputs=[],
        required_capabilities=[],
        tool_candidates=[],
        reason="用户是在问候。",
    )

    assert decision.to_payload() == {
        "route": "response_only",
        "intent": "greeting",
        "complexity": "simple",
        "requiresGraph": False,
        "requiresTools": False,
        "requiresWeb": False,
        "requiresFiles": False,
        "requiresClarification": False,
        "language": "zh",
        "confidence": 0.97,
        "contextUsed": ["current_message"],
        "missingInputs": [],
        "requiredCapabilities": [],
        "toolCandidates": [],
        "reason": "用户是在问候。",
        "clarificationPrompt": None,
    }


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_semantic_route_decision_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(ValidationError):
        SemanticRouteDecision(
            route="response_only",
            intent="greeting",
            complexity="simple",
            requires_graph=False,
            requires_tools=False,
            requires_web=False,
            requires_files=False,
            requires_clarification=False,
            language="zh",
            confidence=confidence,
            reason="invalid",
        )


def test_parse_semantic_route_response_accepts_camel_and_snake_case() -> None:
    response = json.dumps(
        {
            "route": "deep_planning",
            "intent": "document_report",
            "complexity": "multi_step",
            "requiresGraph": True,
            "requiresTools": True,
            "requiresWeb": False,
            "requiresFiles": True,
            "requiresClarification": False,
            "language": "zh",
            "confidence": 0.91,
            "contextUsed": ["current_message", "attachments"],
            "missingInputs": [],
            "requiredCapabilities": ["document.read", "output.pdf"],
            "toolCandidates": ["document.read_write", "output.pdf"],
            "reason": "用户要求处理附件并导出报告。",
        }
    )

    decision = parse_semantic_route_response(response)

    assert decision.route == "deep_planning"
    assert decision.requires_graph is True
    assert decision.required_capabilities == ["document.read", "output.pdf"]
    assert decision.context_used == ["current_message", "attachments"]


def test_parse_semantic_route_response_accepts_snake_case() -> None:
    response = json.dumps(
        {
            "route": "clarification_required",
            "intent": "missing_attachment",
            "complexity": "bounded_tool",
            "requires_graph": False,
            "requires_tools": True,
            "requires_web": False,
            "requires_files": True,
            "requires_clarification": True,
            "language": "zh",
            "confidence": 0.82,
            "context_used": ["current_message"],
            "missing_inputs": ["attachment"],
            "required_capabilities": ["document.read"],
            "tool_candidates": ["document.read_write"],
            "reason": "用户提到附件，但没有提供附件。",
            "clarification_prompt": "请上传需要处理的附件。",
        }
    )

    decision = parse_semantic_route_response(response)

    assert decision.requires_graph is False
    assert decision.requires_tools is True
    assert decision.requires_files is True
    assert decision.requires_clarification is True
    assert decision.context_used == ["current_message"]
    assert decision.missing_inputs == ["attachment"]
    assert decision.required_capabilities == ["document.read"]
    assert decision.tool_candidates == ["document.read_write"]
    assert decision.clarification_prompt == "请上传需要处理的附件。"


def test_capability_ids_survive_parse_and_payload_scrubbing() -> None:
    windows_path = r"D:\Software Project\Alita\python\agent_service\graph.py"
    posix_path = "/Users/drew/Software Project/Alita/python/agent_service/graph.py"
    response = json.dumps(
        {
            "route": "simple_tool_answer",
            "intent": "tool_lookup",
            "complexity": "bounded_tool",
            "requiresGraph": False,
            "requiresTools": True,
            "requiresWeb": False,
            "requiresFiles": False,
            "requiresClarification": False,
            "language": "en",
            "confidence": 0.9,
            "requiredCapabilities": [
                "agent_service.debug",
                "web.search.parallel",
                windows_path,
            ],
            "toolCandidates": [
                "weather.current",
                "document.read_write",
                posix_path,
            ],
            "reason": "Use available tools.",
        }
    )

    decision = parse_semantic_route_response(response)
    payload = decision.to_payload()

    assert decision.required_capabilities == [
        "agent_service.debug",
        "web.search.parallel",
        "[local_path]",
    ]
    assert decision.tool_candidates == [
        "weather.current",
        "document.read_write",
        "[local_path]",
    ]
    assert payload["requiredCapabilities"] == [
        "agent_service.debug",
        "web.search.parallel",
        "[local_path]",
    ]
    assert payload["toolCandidates"] == [
        "weather.current",
        "document.read_write",
        "[local_path]",
    ]


def test_router_prompt_does_not_include_raw_local_paths() -> None:
    local_path = r"D:\Software Project\Alita\python\agent_service\graph.py"
    message = UserMessage(task_id="semantic-scrub", content=f"请看看 {local_path}")

    prompt_dump = repr(build_semantic_router_messages(message))

    assert local_path not in prompt_dump
    assert "Software Project\\Alita" not in prompt_dump
    assert "agent_service" not in prompt_dump


def test_router_prompt_scrubs_available_capabilities_and_path_fragments() -> None:
    message = UserMessage(
        task_id="semantic-capability-scrub",
        content=r"请检查 Software Project\Alita 下面的 agent_service 模块",
    )

    messages = build_semantic_router_messages(
        message,
        available_capabilities=[
            r"D:\Software Project\Alita\python\agent_service\graph.py",
            r"agent_service.debug",
            "weather.current",
            "web.search.parallel",
        ],
    )
    envelope = json.loads(messages[1].content)
    prompt_dump = json.dumps(envelope, ensure_ascii=False)

    assert "Software Project\\Alita" not in prompt_dump
    assert r"D:\Software Project\Alita\python\agent_service\graph.py" not in prompt_dump
    assert envelope["availableCapabilities"] == [
        "[local_path]",
        "agent_service.debug",
        "weather.current",
        "web.search.parallel",
    ]


def test_router_system_prompt_lists_allowed_enum_values() -> None:
    system_prompt = build_semantic_router_messages(
        UserMessage(task_id="semantic-enums", content="hello")
    )[0].content

    for route in [
        "response_only",
        "local_answer",
        "simple_tool_answer",
        "web_answer",
        "graph_feedback",
        "clarification_required",
        "deep_planning",
        "research_planning",
    ]:
        assert route in system_prompt

    for complexity in ["simple", "bounded_tool", "multi_step", "research"]:
        assert complexity in system_prompt


def test_router_system_prompt_separates_answers_from_deliverable_tasks() -> None:
    system_prompt = build_semantic_router_messages(
        UserMessage(task_id="semantic-deliverable-boundary", content="你好")
    )[0].content

    assert "If the user wants an answer, choose A/B/C/D/H as appropriate." in system_prompt
    assert "If the user wants Alita to produce or change an artifact, choose G/H." in system_prompt
    assert "Python 如何统计 CSV 行数？ -> B" in system_prompt
    assert "帮我创建一个 Python 脚本，统计 CSV 文件的行数。 -> G" in system_prompt


def test_router_graph_summary_scrubs_user_controlled_string_fields() -> None:
    local_path = r"D:\Software Project\Alita\python\agent_service\graph.py"
    graph = RunGraph(
        graphId=local_path,
        nodes=[
            GraphNode(
                nodeId=local_path,
                nodeType="model",
                displayName=f"Review {local_path}",
                status="waiting",
                summary="summary",
                createdBy="test",
                position={"x": 0.0, "y": 0.0},
            )
        ],
        edges=[],
    )

    messages = build_semantic_router_messages(
        UserMessage(task_id="semantic-graph-scrub", content="inspect graph"),
        current_graph=graph,
    )
    envelope = json.loads(messages[1].content)
    prompt_dump = json.dumps(envelope, ensure_ascii=False)

    assert local_path not in prompt_dump
    assert "Software Project\\Alita" not in prompt_dump
    assert "agent_service" not in prompt_dump
    assert envelope["currentGraph"]["graphId"] == "[local_path]"
    assert envelope["currentGraph"]["nodes"][0]["nodeId"] == "[local_path]"
    assert envelope["currentGraph"]["nodes"][0]["displayName"] == "Review [local_path]"


def test_route_semantically_uses_model_decision() -> None:
    model = FakeSemanticRouterModel([_semantic_response("response_only")])

    decision = route_semantically(
        UserMessage(task_id="semantic-greeting", content="早上好"),
        model_client=model,
    )

    assert decision.route == "response_only"
    assert decision.language == "zh"
    assert len(model.calls) == 1
    assert model.calls[0]["temperature"] == 0.0
    assert model.calls[0]["max_tokens"] == SEMANTIC_ROUTER_MAX_TOKENS
    assert model.calls[0]["policy"] is not None
    assert model.calls[0]["policy"].thinking == "off"


def test_route_semantically_uses_short_timeout_when_client_supports_it() -> None:
    model = TimeoutAwareSemanticRouterModel([_semantic_response("response_only")])

    route_semantically(
        UserMessage(task_id="semantic-timeout-budget", content="你好"),
        model_client=model,
    )

    assert model.calls[0]["timeout_seconds"] == SEMANTIC_ROUTER_TIMEOUT_SECONDS


def test_route_semantically_model_failure_keeps_nonempty_message_in_response_path() -> None:
    model = FakeSemanticRouterModel(error=TimeoutError("router timed out"))

    decision = route_semantically(
        UserMessage(task_id="semantic-timeout-greeting", content="你好"),
        model_client=model,
    )

    assert decision.route == "response_only"
    assert decision.requires_clarification is False
    assert decision.missing_inputs == []
    assert decision.confidence == 0.0
    assert len(model.calls) == 1


def test_route_semantically_repairs_malformed_json_once() -> None:
    model = FakeSemanticRouterModel(
        [
            "not json",
            _semantic_response("response_only"),
        ]
    )

    decision = route_semantically(
        UserMessage(task_id="semantic-repair", content="你好"),
        model_client=model,
    )

    assert decision.route == "response_only"
    assert len(model.calls) == 2
    assert (
        "Repair this invalid Semantic Router response"
        in model.calls[1]["messages"][0].content
    )


def test_route_semantically_model_failure_with_attachment_returns_clarification() -> None:
    model = FakeSemanticRouterModel(error=TimeoutError("router timed out"))

    decision = route_semantically(
        UserMessage(
            task_id="semantic-timeout",
            content="帮我看看这个事情",
            attachments=[
                Attachment(
                    attachment_id="attachment-1",
                    name="report.pdf",
                    path="C:/Temp/report.pdf",
                    size_bytes=1234,
                    mime_type="application/pdf",
                )
            ],
        ),
        model_client=model,
    )

    assert decision.route == "clarification_required"
    assert decision.requires_clarification is True
    assert decision.confidence == 0.0
    assert decision.missing_inputs == ["router_decision"]
    assert "我需要确认你的目标" in (decision.clarification_prompt or "")


def test_route_semantically_without_model_keeps_nonempty_message_in_response_path() -> None:
    decision = route_semantically(
        UserMessage(task_id="semantic-no-model", content="研究一下这个问题"),
        model_client=None,
    )

    assert decision.route == "response_only"
    assert decision.requires_clarification is False
    assert decision.required_capabilities == []
