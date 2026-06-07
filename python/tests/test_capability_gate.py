from __future__ import annotations

from agent_service.capability_gate import CapabilityGateResult, evaluate_route_capabilities
from agent_service.schemas import UserMessage
from agent_service.semantic_router import SemanticRouteDecision


def _decision(**updates) -> SemanticRouteDecision:
    data = {
        "route": "web_answer",
        "intent": "latest_fact",
        "complexity": "simple",
        "requiresGraph": False,
        "requiresTools": True,
        "requiresWeb": True,
        "requiresFiles": False,
        "requiresClarification": False,
        "language": "zh",
        "confidence": 0.92,
        "contextUsed": ["current_message"],
        "missingInputs": [],
        "requiredCapabilities": ["web.search"],
        "toolCandidates": ["web.search.parallel"],
        "reason": "需要联网查询。",
    }
    data.update(updates)
    return SemanticRouteDecision.model_validate(data)


def test_capability_gate_allows_available_web_tool() -> None:
    result = evaluate_route_capabilities(
        _decision(),
        UserMessage(task_id="cap-ok", content="查一下最新版本"),
        available_capabilities=["web.search.parallel"],
    )

    assert result == CapabilityGateResult(allowed=True, reason="capabilities available")


def test_capability_gate_blocks_missing_web_tool_without_changing_intent() -> None:
    result = evaluate_route_capabilities(
        _decision(),
        UserMessage(task_id="cap-block", content="查一下最新版本"),
        available_capabilities=[],
    )

    assert result.allowed is False
    assert result.missing_capabilities == ["web.search.parallel"]
    assert "当前任务需要尚未接入的能力" in result.user_message


def test_capability_gate_blocks_missing_required_capability_without_tool_candidate() -> None:
    result = evaluate_route_capabilities(
        _decision(
            requiredCapabilities=["legal.database"],
            toolCandidates=[],
            reason="需要法律数据库能力。",
        ),
        UserMessage(task_id="cap-required", content="查询最新法律条文"),
        available_capabilities=[],
    )

    assert result.allowed is False
    assert result.missing_capabilities == ["legal.database"]
    assert "legal.database" in result.user_message


def test_capability_gate_blocks_required_file_without_attachment() -> None:
    result = evaluate_route_capabilities(
        _decision(
            route="deep_planning",
            requiresGraph=True,
            requiresTools=True,
            requiresWeb=False,
            requiresFiles=True,
            requiredCapabilities=["document.read"],
            toolCandidates=["document.read_write"],
            reason="需要处理附件。",
        ),
        UserMessage(task_id="cap-file", content="整理这个文档"),
        available_capabilities=["document.read_write"],
    )

    assert result.allowed is False
    assert result.missing_inputs == ["attachment"]
    assert result.user_message == "请先添加需要处理的文档。"


def test_capability_gate_reports_missing_attachment_and_capability() -> None:
    result = evaluate_route_capabilities(
        _decision(
            route="deep_planning",
            requiresGraph=True,
            requiresTools=True,
            requiresWeb=False,
            requiresFiles=True,
            requiredCapabilities=["document.read"],
            toolCandidates=["document.read_write"],
            reason="需要处理附件。",
        ),
        UserMessage(task_id="cap-file-tool", content="整理这个文档"),
        available_capabilities=[],
    )

    assert result.allowed is False
    assert result.missing_inputs == ["attachment"]
    assert result.missing_capabilities == ["document.read_write"]
    assert "文档" in result.user_message
    assert "document.read_write" in result.user_message


def test_capability_gate_normalizes_whitespace_and_skips_empty_candidates() -> None:
    result = evaluate_route_capabilities(
        _decision(toolCandidates=[" web.search.parallel ", "", "   "]),
        UserMessage(task_id="cap-normalized", content="查一下最新版本"),
        available_capabilities=["web.search.parallel"],
    )

    assert result.allowed is True
    assert result.missing_capabilities == []


def test_capability_gate_deduplicates_missing_candidates_in_order() -> None:
    result = evaluate_route_capabilities(
        _decision(
            toolCandidates=[
                "web.search.parallel",
                " document.read_write ",
                "web.search.parallel",
                "",
                "document.read_write",
                "calendar.lookup",
            ],
        ),
        UserMessage(task_id="cap-dedupe", content="查一下最新版本"),
        available_capabilities=[],
    )

    assert result.allowed is False
    assert result.missing_capabilities == [
        "web.search.parallel",
        "document.read_write",
        "calendar.lookup",
    ]
