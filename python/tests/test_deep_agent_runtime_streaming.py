from __future__ import annotations

import json
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from agent_service.deep_agent_runtime_graph import (
    run_deep_agent_runtime,
    stream_deep_agent_runtime_events,
)
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
        "task_id": "task-streaming",
        "task_understanding": "Reason about the request before acting.",
        "intent": "task",
        "complexity": "graph_task" if next_action == "deep_planning" else "simple",
        "why_this_path": "The request should be reasoned before any action.",
        "confidence": 0.9,
        "needs_clarification": False,
        "required_capabilities": ["model.reasoning"],
        "next_action": next_action,
    }


def _plan_payload(*, missing_information: list[str] | None = None) -> dict[str, Any]:
    return {
        "plan_draft_id": "plan-streaming",
        "task_understanding": "Create a custom document report.",
        "success_criteria": ["The report matches the requested structure."],
        "inputs": [],
        "assumptions": [],
        "missing_information": list(missing_information or []),
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
                "step_id": "understand",
                "title": "Understand request",
                "objective": "Capture report requirements.",
                "rationale": "The output must match the user request.",
                "inputs": [],
                "required_capabilities": ["model.reasoning"],
                "expected_output": "Report requirements.",
                "verification_criteria": ["Requirements are clear."],
                "depends_on": [],
            },
            {
                "step_id": "write",
                "title": "Write report",
                "objective": "Draft the report.",
                "rationale": "The user needs the deliverable.",
                "inputs": [],
                "required_capabilities": ["model.reasoning"],
                "expected_output": "Report draft.",
                "verification_criteria": ["Report follows requirements."],
                "depends_on": ["understand"],
            },
        ],
        "required_capabilities": ["model.reasoning"],
        "risks": [],
        "verification_plan": ["Check final answer."],
    }


def test_stream_deep_agent_runtime_events_matches_non_stream_event_order() -> None:
    message = UserMessage(task_id="task-streaming", content="Write a tailored report.")
    non_stream_model = FakeModel([_reasoning_payload(), _plan_payload()])
    stream_model = FakeModel([_reasoning_payload(), _plan_payload()])

    non_stream_events = run_deep_agent_runtime(
        message,
        project_path="D:/Project/demo.alita",
        model_client=non_stream_model,
        run_id="run-non-stream",
        thread_id="thread-non-stream",
        checkpointer=InMemorySaver(),
        require_confirmation=False,
    )
    stream_events = list(
        stream_deep_agent_runtime_events(
            message,
            project_path="D:/Project/demo.alita",
            model_client=stream_model,
            run_id="run-stream",
            thread_id="thread-stream",
            checkpointer=InMemorySaver(),
            require_confirmation=False,
        )
    )

    assert [event.type for event in stream_events] == [
        event.type for event in non_stream_events
    ]
    assert [event.type for event in stream_events] == [
        "reasoning.decision_created",
        "planning.started",
        "planning.thinking_status",
        "planning.draft_created",
        "planning.review_completed",
        "planning.graph_compiled",
        "planning.graph_review_completed",
        "node_graph.created",
    ]
    assert stream_model.calls == non_stream_model.calls == 2
    assert stream_events[-1].payload["graph"]["nodes"][0]["nodeId"] == "understand"


def test_stream_deep_agent_runtime_events_surfaces_planning_interrupts() -> None:
    model = FakeModel([_reasoning_payload(), _plan_payload()])

    events = list(
        stream_deep_agent_runtime_events(
            UserMessage(task_id="task-confirm-stream", content="Write a tailored report."),
            project_path="D:/Project/demo.alita",
            model_client=model,
            checkpointer=InMemorySaver(),
        )
    )

    assert [event.type for event in events][-2:] == [
        "planning.confirmation_required",
        "planning.interrupted",
    ]
    assert events[-1].payload["kind"] == "planning.confirmation"
