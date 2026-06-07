from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_service.schemas import GraphNode, RunGraph, UserMessage
from agent_service.semantic_router import (
    SemanticRouteDecision,
    build_semantic_router_messages,
    parse_semantic_route_response,
)


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
