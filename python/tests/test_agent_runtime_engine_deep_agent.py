from __future__ import annotations

import json
from typing import Any

from agent_service.agent_run_state import AgentRunState
from agent_service.agent_runtime_engine import AgentRuntimeEngine
from agent_service.model_client import ChatDiagnosticsResponse, ModelCallDiagnostics
from agent_service.schemas import AgentEvent, UserMessage


class FakeDeepModel:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls = 0

    def chat_with_diagnostics(self, messages, *, policy=None, **kwargs):
        del messages, policy, kwargs
        self.calls += 1
        payload = self.payloads[self.calls - 1]
        return ChatDiagnosticsResponse(
            content=json.dumps(payload),
            diagnostics=ModelCallDiagnostics(
                request_payload_had_thinking_params=True,
                enable_thinking_sent=True,
                preserve_thinking_sent=True,
                enable_thinking_value=True,
                preserve_thinking_value=True,
                fallback_used="none",
                effective_mode="deep",
            ),
        )


def _reasoning_payload(next_action: str) -> dict[str, Any]:
    return {
        "task_id": "task-engine",
        "task_understanding": "Reason about the user request before acting.",
        "intent": "task",
        "complexity": "graph_task" if next_action == "deep_planning" else "simple",
        "why_this_path": "The request must pass through the Agent reasoning gate.",
        "confidence": 0.9,
        "needs_clarification": False,
        "required_capabilities": ["model.reasoning"],
        "next_action": next_action,
    }


def _plan_payload() -> dict[str, Any]:
    return {
        "plan_draft_id": "plan-engine",
        "task_understanding": "Create a custom report.",
        "success_criteria": ["Report is structured."],
        "inputs": [],
        "assumptions": [],
        "missing_information": [],
        "candidate_strategies": [
            {
                "strategyId": "custom",
                "summary": "Create a dynamic report plan.",
                "tradeoffs": ["Requires model planning before graph creation."],
            }
        ],
        "recommended_strategy": "custom",
        "steps": [
            {
                "step_id": "draft",
                "title": "Draft report",
                "objective": "Write report.",
                "rationale": "The user requested a report.",
                "inputs": [],
                "required_capabilities": ["model.reasoning"],
                "expected_output": "Report draft.",
                "verification_criteria": ["Report has sections."],
                "depends_on": [],
            }
        ],
        "required_capabilities": ["model.reasoning"],
        "risks": [],
        "verification_plan": ["Check report sections."],
    }


def test_runtime_engine_task_request_uses_deep_agent_runtime_not_legacy_runner() -> None:
    legacy_calls: list[AgentRunState] = []

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        raise AssertionError("legacy runner must not be used for task graph creation")

    model = FakeDeepModel([_reasoning_payload("deep_planning"), _plan_payload()])
    engine = AgentRuntimeEngine(route_runner=legacy_runner)
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-engine-deep",
            content="Create a structured report from my project notes.",
        )
    ).model_copy(update={"project_path": "D:/Project/demo.alita", "run_id": "run-deep"})

    result = engine.run_from_state(run_state, model_client=model)

    assert legacy_calls == []
    assert model.calls == 2
    assert [event.type for event in result.events][-1] == "node_graph.created"
    graph = result.events[-1].payload["graph"]
    assert graph["metadata"]["generatedBy"] == "deep_agent_runtime"
    assert graph["nodes"][0]["metadata"]["sourcePlanStepId"] == "draft"


def test_runtime_engine_simple_request_passes_reasoning_gate_before_legacy_answer() -> None:
    legacy_calls: list[AgentRunState] = []

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        return [
            AgentEvent(
                type="message.created",
                payload={"message": {"content": "hello"}},
            )
        ]

    model = FakeDeepModel([_reasoning_payload("simple_answer")])
    engine = AgentRuntimeEngine(route_runner=legacy_runner)
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="task-simple-gate", content="Say hello.")
    ).model_copy(update={"project_path": "D:/Project/demo.alita", "run_id": "run-simple"})

    result = engine.run_from_state(run_state, model_client=model)

    assert model.calls == 1
    assert len(legacy_calls) == 1
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "reasoning.decision_created",
        "reasoning.completed",
        "runtime.state_delta",
        "message.created",
    ]
