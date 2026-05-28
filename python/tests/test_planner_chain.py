from __future__ import annotations

import pytest

from agent_service.planner_chain import (
    PlannerChainError,
    StructuredRouteContext,
    route_context_from_payload,
)


def _route_payload(**overrides):
    payload = {
        "intent": "task",
        "confidence": 0.88,
        "taskType": "code_task",
        "missingInputs": [],
        "requiredPermissions": ["read_project_files"],
        "toolCandidates": ["internal:file.inspect"],
        "reason": "User asks for a coding task.",
        "source": "deterministic",
        "shouldClarify": False,
        "clarificationPrompt": None,
    }
    payload.update(overrides)
    return payload


def test_route_context_parses_phase_d_payload_keys() -> None:
    route = route_context_from_payload(_route_payload())

    assert route.intent == "task"
    assert route.task_type == "code_task"
    assert route.required_permissions == ["read_project_files"]
    assert route.tool_candidates == ["internal:file.inspect"]


def test_route_context_safe_payload_scrubs_path_values() -> None:
    local_path = r"D:\Software Project\Alita\python\agent_service\graph.py"
    route = route_context_from_payload(
        _route_payload(
            missingInputs=[local_path],
            toolCandidates=[local_path],
            reason=f"Need {local_path}",
        )
    )

    payload_dump = repr(route.safe_payload())

    assert local_path not in payload_dump
    assert "Software Project" not in payload_dump
    assert "agent_service" not in payload_dump


def test_route_context_rejects_invalid_payload() -> None:
    with pytest.raises(PlannerChainError, match="invalid structured route payload"):
        route_context_from_payload({"intent": "task"})


def test_route_context_validation_error_does_not_leak_path_values() -> None:
    local_path = r"D:\Software Project\Alita\python\agent_service\graph.py"

    with pytest.raises(PlannerChainError) as exc_info:
        route_context_from_payload(_route_payload(taskType=local_path))

    message = str(exc_info.value)

    assert "invalid structured route payload" in message
    assert local_path not in message
    assert "Software Project" not in message
    assert "agent_service" not in message
    assert exc_info.value.__cause__ is None
