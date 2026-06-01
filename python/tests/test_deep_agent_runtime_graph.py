from __future__ import annotations

import json
from typing import Any

from agent_service.deep_agent_runtime_graph import run_deep_agent_runtime
from agent_service.model_client import ChatDiagnosticsResponse, ModelCallDiagnostics
from agent_service.schemas import UserMessage


class FakeModel:
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


def _reasoning_payload(next_action: str = "deep_planning") -> dict[str, Any]:
    return {
        "task_id": "task-deep",
        "task_understanding": "User wants a tailored report.",
        "intent": "task",
        "complexity": "graph_task" if next_action == "deep_planning" else "simple",
        "why_this_path": "The request should be reasoned before any action.",
        "confidence": 0.9,
        "needs_clarification": False,
        "required_capabilities": ["model.reasoning"],
        "next_action": next_action,
    }


def _plan_payload(step_ids: list[str]) -> dict[str, Any]:
    return {
        "plan_draft_id": "plan-dynamic",
        "task_understanding": "Create a custom document report.",
        "success_criteria": ["The report matches the requested structure."],
        "inputs": [],
        "assumptions": [],
        "missing_information": [],
        "candidate_strategies": [
            {
                "strategyId": "custom-plan",
                "summary": "Plan the report from the actual request.",
                "tradeoffs": ["More reasoning work before graph execution."],
            }
        ],
        "recommended_strategy": "custom-plan",
        "steps": [
            {
                "step_id": step_id,
                "title": f"Step {step_id}",
                "objective": f"Do {step_id}.",
                "rationale": f"Because {step_id} is needed.",
                "inputs": [],
                "required_capabilities": ["model.reasoning"],
                "expected_output": f"Output {step_id}.",
                "verification_criteria": [f"Verify {step_id}."],
                "depends_on": step_ids[:index],
            }
            for index, step_id in enumerate(step_ids)
        ],
        "required_capabilities": ["model.reasoning"],
        "risks": [],
        "verification_plan": ["Check final answer."],
    }


def test_deep_agent_runtime_calls_model_and_emits_graph_from_plan() -> None:
    model = FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-deep", content="Write a tailored report."),
        project_path="D:/Project/demo.alita",
        model_client=model,
    )

    assert model.calls == 2
    assert [event.type for event in events] == [
        "reasoning.decision_created",
        "planning.started",
        "planning.thinking_status",
        "planning.draft_created",
        "planning.review_completed",
        "planning.graph_compiled",
        "planning.graph_review_completed",
        "node_graph.created",
    ]
    graph = events[-1].payload["graph"]
    assert [node["nodeId"] for node in graph["nodes"]] == ["understand", "write"]
    assert graph["nodes"][0]["metadata"]["sourcePlanStepId"] == "understand"


def test_deep_agent_runtime_returns_clarification_without_graph() -> None:
    payload = _plan_payload(["clarify"])
    payload["missing_information"] = ["target audience"]
    model = FakeModel([_reasoning_payload(), payload])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-clarify", content="Make this into a report."),
        project_path="D:/Project/demo.alita",
        model_client=model,
    )

    assert model.calls == 2
    assert [event.type for event in events][-1] == "planning.clarification_required"
    assert all(event.type != "node_graph.created" for event in events)


def test_deep_agent_runtime_records_simple_reasoning_without_graph() -> None:
    model = FakeModel([_reasoning_payload("simple_answer")])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-simple", content="Say hello."),
        project_path="D:/Project/demo.alita",
        model_client=model,
    )

    assert model.calls == 1
    assert [event.type for event in events] == [
        "reasoning.decision_created",
        "reasoning.completed",
    ]
    assert all(event.type != "node_graph.created" for event in events)
