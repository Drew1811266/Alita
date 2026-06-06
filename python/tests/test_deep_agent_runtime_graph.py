from __future__ import annotations

import json
from collections import Counter
from typing import Any

import pytest
from pydantic import ValidationError
from langgraph.checkpoint.memory import InMemorySaver

from agent_service.deep_agent_checkpoint_mirror import (
    planning_checkpoint_summary_from_state,
)
from agent_service.deep_agent_runtime_models import (
    DeepAgentRunResult,
    PlanningCheckpointSummary,
    PlanningResumeCommand,
)
from agent_service.deep_agent_runtime_graph import (
    _runtime_invoke_input,
    build_context,
    build_deep_agent_runtime_graph,
    run_deep_agent_runtime,
)
from agent_service.model_client import (
    ChatDiagnosticsResponse,
    ModelCallDiagnostics,
    ModelRuntimeDisabled,
)
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


class UnavailableModel:
    def chat_with_diagnostics(self, messages, *, policy=None, **kwargs):
        del messages, policy, kwargs
        raise ModelRuntimeDisabled("model is not configured")


def _new_input_model() -> FakeModel:
    return FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])


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
        checkpointer=InMemorySaver(),
        require_confirmation=False,
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


def test_build_deep_agent_runtime_graph_accepts_state_model_client() -> None:
    model = _new_input_model()
    app = build_deep_agent_runtime_graph()

    result = app.invoke(
        {
            "message": UserMessage(task_id="task-direct", content="Write a report."),
            "project_path": "D:/Project/demo.alita",
            "model_client": model,
            "events": [],
        }
    )

    assert model.calls == 2
    assert [event.type for event in result.get("events", [])][-1] == "node_graph.created"


def test_build_context_stores_node_catalog_and_catalog_available_capabilities() -> None:
    update = build_context(
        {
            "message": UserMessage(
                task_id="task-catalog",
                content="Convert this document to markdown.",
            ),
            "project_path": "D:/Project/demo.alita",
        }
    )

    node_catalog = update["node_catalog"]
    assert isinstance(node_catalog, dict)
    catalog_node_ids = {node["node_id"] for node in node_catalog["nodes"]}
    assert "document.convert.markdown" in catalog_node_ids

    context_node_ids = {
        node["node_id"] for node in update["context_bundle"]["available_nodes"]
    }
    assert "document.convert.markdown" in context_node_ids

    assert "document.convert.markdown" in update["available_capabilities"]
    assert "document.read" not in update["available_capabilities"]


def test_runtime_invoke_input_defaults_to_execute_after_compile() -> None:
    invoke_input = _runtime_invoke_input(
        UserMessage(task_id="task-default-execute", content="Write a report."),
        project_path="D:/Project/demo.alita",
        run_id="run-default-execute",
        thread_id="thread-default-execute",
        resume_command=None,
        revision_budget=2,
        require_confirmation=True,
    )

    assert isinstance(invoke_input, dict)
    assert invoke_input["execute_after_compile"] is True


def test_build_deep_agent_runtime_graph_with_checkpoint_uses_builder_model_client() -> None:
    builder_model = _new_input_model()
    injected_model = _new_input_model()
    app = build_deep_agent_runtime_graph(
        checkpointer=InMemorySaver(),
        model_client=builder_model,
    )
    config = {"configurable": {"thread_id": "thread-checkpoint"}}

    result = app.invoke(
        {
            "message": UserMessage(task_id="task-checkpoint", content="Write a report."),
            "project_path": "D:/Project/demo.alita",
            "model_client": injected_model,
            "events": [],
            "thread_id": "thread-checkpoint",
        },
        config=config,
    )

    assert builder_model.calls == 2
    assert injected_model.calls == 0
    assert [event.type for event in result.get("events", [])][-1] == "node_graph.created"
    assert "model_client" not in app.get_state(config).values


def test_deep_agent_runtime_returns_clarification_without_graph() -> None:
    payload = _plan_payload(["clarify"])
    payload["missing_information"] = ["target audience"]
    model = FakeModel([_reasoning_payload(), payload])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-clarify", content="Make this into a report."),
        project_path="D:/Project/demo.alita",
        model_client=model,
        checkpointer=InMemorySaver(),
    )

    assert model.calls == 2
    assert [event.type for event in events][-2:] == [
        "planning.clarification_required",
        "planning.interrupted",
    ]
    assert all(event.type != "node_graph.created" for event in events)


def test_deep_agent_runtime_records_simple_reasoning_without_graph() -> None:
    model = FakeModel([_reasoning_payload("simple_answer")])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-simple", content="Say hello."),
        project_path="D:/Project/demo.alita",
        model_client=model,
        checkpointer=InMemorySaver(),
    )

    assert model.calls == 1
    assert [event.type for event in events] == [
        "reasoning.decision_created",
        "reasoning.completed",
    ]
    assert all(event.type != "node_graph.created" for event in events)


def test_deep_agent_runtime_returns_failed_event_when_reasoning_unavailable() -> None:
    events = run_deep_agent_runtime(
        UserMessage(task_id="task-unavailable", content="Create a report."),
        project_path="D:/Project/demo.alita",
        model_client=UnavailableModel(),
        checkpointer=InMemorySaver(),
    )

    assert [event.type for event in events] == ["planning.failed"]
    assert events[0].payload["reason"] == "reasoning_unavailable"
    assert "model is not configured" in events[0].payload["message"]


def test_deep_agent_runtime_returns_failed_event_when_plan_json_is_invalid() -> None:
    model = FakeModel([_reasoning_payload(), {"not": "a plan draft"}])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-invalid-plan", content="Create a report."),
        project_path="D:/Project/demo.alita",
        model_client=model,
        checkpointer=InMemorySaver(),
    )

    assert [event.type for event in events] == [
        "reasoning.decision_created",
        "planning.started",
        "planning.failed",
    ]
    assert events[-1].payload["reason"] == "invalid_plan_json"
    assert all(event.type != "node_graph.created" for event in events)


def test_deep_agent_runtime_uses_reducer_events_without_duplicates() -> None:
    model = FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-deep", content="Write a tailored report."),
        project_path="D:/Project/demo.alita",
        model_client=model,
        run_id="run-reducer",
        thread_id="thread-reducer",
        checkpointer=InMemorySaver(),
        require_confirmation=False,
    )

    event_counts = Counter(event.type for event in events)
    assert event_counts["reasoning.decision_created"] == 1
    assert event_counts["planning.draft_created"] == 1
    assert event_counts["node_graph.created"] == 1


def test_deep_agent_runtime_checkpointer_invocation_is_current_invocation_only() -> None:
    model = FakeModel(
        [
            _reasoning_payload(),
            _plan_payload(["understand", "write"]),
            _reasoning_payload(),
            _plan_payload(["understand", "write"]),
        ]
    )
    checkpointer = InMemorySaver()

    run_deep_agent_runtime(
        UserMessage(task_id="task-deep", content="Write a tailored report."),
        project_path="D:/Project/demo.alita",
        model_client=model,
        run_id="run-reducer",
        thread_id="thread-reducer-repeat",
        checkpointer=checkpointer,
        require_confirmation=False,
    )

    second_events = run_deep_agent_runtime(
        UserMessage(task_id="task-deep", content="Write a tailored report."),
        project_path="D:/Project/demo.alita",
        model_client=model,
        run_id="run-reducer",
        thread_id="thread-reducer-repeat",
        checkpointer=checkpointer,
        require_confirmation=False,
    )

    event_counts = Counter(event.type for event in second_events)
    assert len(second_events) == 8
    assert event_counts["reasoning.decision_created"] == 1
    assert event_counts["planning.draft_created"] == 1
    assert event_counts["node_graph.created"] == 1
    assert model.calls == 4


def test_planning_resume_command_aliases() -> None:
    command = PlanningResumeCommand(
        kind="clarification_answer",
        threadId="thread-1",
        runId="run-1",
        answer="clarify this",
    )
    payload = command.model_dump(by_alias=True)
    assert payload["threadId"] == "thread-1"
    assert payload["runId"] == "run-1"
    assert payload["revisionInstructions"] == []


def test_planning_resume_command_aliases_with_confirmation_revision() -> None:
    command = PlanningResumeCommand(
        kind="confirmation",
        threadId="thread-1",
        runId="run-1",
        decision="revise",
        revisionInstructions=["revise section X"],
    )
    payload = command.model_dump(by_alias=True)
    assert payload["revisionInstructions"] == ["revise section X"]


def test_planning_resume_command_validation_rejects_invalid_combinations() -> None:
    with pytest.raises(ValidationError):
        PlanningResumeCommand(
            kind="clarification_answer",
            threadId="thread-1",
        )

    with pytest.raises(ValidationError):
        PlanningResumeCommand(
            kind="clarification_answer",
            threadId="thread-1",
            answer="need details",
            decision="approve",
        )

    with pytest.raises(ValidationError):
        PlanningResumeCommand(
            kind="clarification_answer",
            threadId="thread-1",
            answer="need details",
            revisionInstructions=["revise"],
        )

    with pytest.raises(ValidationError):
        PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-1",
        )

    with pytest.raises(ValidationError):
        PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-1",
            answer="oops",
            decision="approve",
        )

    with pytest.raises(ValidationError):
        PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-1",
            decision="approve",
            revisionInstructions=["revise"],
        )


def test_deep_agent_run_result_aliases() -> None:
    result = DeepAgentRunResult(
        events=[],
        runId="run-1",
        threadId="thread-1",
        latestCheckpointId="ckpt-1",
        interrupted=True,
    )
    payload = result.model_dump(by_alias=True)
    assert payload["runId"] == "run-1"
    assert payload["threadId"] == "thread-1"
    assert payload["latestCheckpointId"] == "ckpt-1"
    assert payload["interrupted"] is True


def test_planning_checkpoint_summary_aliases() -> None:
    summary = PlanningCheckpointSummary(
        runId="run-1",
        threadId="thread-1",
        checkpointId="checkpoint-1",
        stage="reasoning",
        createdAt="2026-06-02T00:00:00Z",
    )
    payload = summary.model_dump(by_alias=True)
    assert payload["runId"] == "run-1"
    assert payload["threadId"] == "thread-1"
    assert payload["revisionCount"] == 0
    assert payload["hasPlanDraft"] is False
    assert payload["hasCompiledGraph"] is False
    assert payload["hasAgentCompiledGraph"] is False
    assert payload["executionReady"] is False


def test_planning_checkpoint_summary_from_state_includes_agent_compile_status() -> None:
    summary = planning_checkpoint_summary_from_state(
        {
            "run_id": "run-1",
            "thread_id": "thread-1",
            "revision_count": 1,
            "plan_draft": {"plan_draft_id": "plan-1"},
            "compiled_graph": {"graphId": "graph-1"},
            "agent_compiled_graph": {"compile_id": "compile-1"},
            "execution_ready": True,
            "terminal_status": "execution_ready",
        },
        "checkpoint-1",
        None,
    )

    payload = summary.model_dump(by_alias=True)
    assert payload["stage"] == "execution_ready"
    assert payload["revisionCount"] == 1
    assert payload["hasPlanDraft"] is True
    assert payload["hasCompiledGraph"] is True
    assert payload["hasAgentCompiledGraph"] is True
    assert payload["executionReady"] is True
