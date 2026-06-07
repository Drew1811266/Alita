from __future__ import annotations

import json
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from agent_service.agent_plan_compile import AgentPlanCompileError
from agent_service.deep_agent_checkpointer import deep_planning_thread_config
from agent_service.deep_agent_runtime_graph import (
    build_deep_agent_runtime_graph,
    run_deep_agent_runtime,
)
from agent_service.deep_agent_runtime_models import PlanningResumeCommand
from agent_service.deep_agent_models import GraphReview
from agent_service.model_client import ChatDiagnosticsResponse, ModelCallDiagnostics
from agent_service.runtime_store import RuntimeStore
from agent_service.schemas import AgentEvent, UserMessage


class FakeModel:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.calls = 0
        self.messages: list[list] = []

    def chat_with_diagnostics(self, messages, *, policy=None, **kwargs):
        del policy, kwargs
        self.calls += 1
        self.messages.append(messages)
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


def _reasoning_payload() -> dict[str, str | bool | float | list[str]]:
    return {
        "task_id": "task-deep",
        "task_understanding": "User wants a tailored report.",
        "intent": "task",
        "complexity": "graph_task",
        "why_this_path": "The request should be reasoned before any action.",
        "confidence": 0.9,
        "needs_clarification": False,
        "required_capabilities": ["model.reasoning"],
        "next_action": "deep_planning",
    }


def _plan_payload(step_ids: list[str]) -> dict:
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


def _clarification_plan_payload() -> dict:
    payload = _plan_payload(["clarify"])
    payload["missing_information"] = ["target audience"]
    return payload


def _invalid_plan_payload_missing_step_verification(step_id: str = "draft") -> dict:
    payload = _plan_payload([step_id])
    payload["steps"][0]["verification_criteria"] = []
    return payload


def _confirmation_required_event(events):
    return next(
        event for event in events if event.type == "planning.confirmation_required"
    )


def test_checkpointed_deep_agent_runtime_has_state_history(tmp_path: Path) -> None:
    model = FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])
    checkpointer = InMemorySaver()
    project_path = tmp_path / "demo.alita"

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-deep", content="Write a tailored report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-history",
        thread_id="thread-history",
        checkpointer=checkpointer,
        require_confirmation=False,
    )

    assert events[-1].type == "node_graph.created"

    app = build_deep_agent_runtime_graph(checkpointer=checkpointer, model_client=model)
    history = list(app.get_state_history(deep_planning_thread_config("thread-history")))
    assert len(history) >= 4
    assert any("plan_draft" in snapshot.values for snapshot in history)


def test_clarification_interrupts_before_graph_creation(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel([_reasoning_payload(), _clarification_plan_payload()])
    checkpointer = InMemorySaver()

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-clarify", content="Make this into a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-clarify",
        thread_id="thread-clarify",
        checkpointer=checkpointer,
        require_confirmation=False,
    )

    assert model.calls == 2
    assert [event.type for event in events][-2:] == [
        "planning.clarification_required",
        "planning.interrupted",
    ]
    assert all(event.type != "node_graph.created" for event in events)


def test_clarification_resume_continues_same_thread(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel(
        [
            _reasoning_payload(),
            _clarification_plan_payload(),
            _plan_payload(["understand", "write"]),
        ]
    )
    checkpointer = InMemorySaver()

    first_events = run_deep_agent_runtime(
        UserMessage(task_id="task-clarify", content="Make this into a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-clarify-resume",
        thread_id="thread-clarify-resume",
        checkpointer=checkpointer,
        require_confirmation=False,
    )

    assert [event.type for event in first_events][-1] == "planning.interrupted"

    resumed_events = run_deep_agent_runtime(
        UserMessage(task_id="task-clarify", content="Make this into a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-clarify-resume",
        thread_id="thread-clarify-resume",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="clarification_answer",
            threadId="thread-clarify-resume",
            runId="run-clarify-resume",
            answer="The report is for executives.",
        ),
        require_confirmation=False,
    )

    assert "planning.resumed" in [event.type for event in resumed_events]
    assert resumed_events[-1].type == "node_graph.created"
    assert model.calls == 3
    assert "The report is for executives." in model.messages[2][1].content


def test_clarification_resume_accumulates_prior_answers_in_planning_prompt(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "demo.alita"
    first_clarification = _clarification_plan_payload()
    first_clarification["missing_information"] = ["target audience"]
    second_clarification = _clarification_plan_payload()
    second_clarification["missing_information"] = ["tone"]
    model = FakeModel(
        [
            _reasoning_payload(),
            first_clarification,
            second_clarification,
            _plan_payload(["understand", "write"]),
        ]
    )
    checkpointer = InMemorySaver()

    first_events = run_deep_agent_runtime(
        UserMessage(task_id="task-clarify-many", content="Make this into a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-clarify-many",
        thread_id="thread-clarify-many",
        checkpointer=checkpointer,
        require_confirmation=False,
    )
    assert first_events[-1].type == "planning.interrupted"

    second_events = run_deep_agent_runtime(
        UserMessage(task_id="task-clarify-many", content="Make this into a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-clarify-many",
        thread_id="thread-clarify-many",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="clarification_answer",
            threadId="thread-clarify-many",
            runId="run-clarify-many",
            answer="The report is for executives.",
        ),
        require_confirmation=False,
    )
    assert second_events[-1].type == "planning.interrupted"

    final_events = run_deep_agent_runtime(
        UserMessage(task_id="task-clarify-many", content="Make this into a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-clarify-many",
        thread_id="thread-clarify-many",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="clarification_answer",
            threadId="thread-clarify-many",
            runId="run-clarify-many",
            answer="Use a concise executive tone.",
        ),
        require_confirmation=False,
    )

    assert final_events[-1].type == "node_graph.created"
    final_planning_prompt = model.messages[3][1].content
    assert "The report is for executives." in final_planning_prompt
    assert "Use a concise executive tone." in final_planning_prompt
    assert "do not ask for the same or similar information again" in final_planning_prompt


def test_confirmation_interrupts_after_graph_creation(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])
    checkpointer = InMemorySaver()

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-confirm", content="Write a tailored report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm",
        thread_id="thread-confirm",
        checkpointer=checkpointer,
        require_confirmation=True,
    )

    assert [event.type for event in events][-3:] == [
        "node_graph.created",
        "planning.confirmation_required",
        "planning.interrupted",
    ]
    graph = events[-3].payload["graph"]
    payload = events[-2].payload
    assert payload["kind"] == "planning.confirmation"
    assert payload["taskId"] == "task-confirm"
    assert payload["runId"] == "run-confirm"
    assert payload["threadId"] == "thread-confirm"
    assert payload["graphId"] == graph["graphId"]
    assert payload["summary"]
    assert payload["pendingChoice"] == {
        "kind": "planning.confirmation",
        "runId": "run-confirm",
        "threadId": "thread-confirm",
        "graphId": graph["graphId"],
    }
    assert [choice["id"] for choice in payload["choices"]] == [
        "approve",
        "revise",
        "cancel",
    ]
    assert events[-1].payload == payload


def test_confirmation_approve_resume_confirms_without_replanning(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])
    checkpointer = InMemorySaver()

    run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-approve", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-approve",
        thread_id="thread-confirm-approve",
        checkpointer=checkpointer,
        require_confirmation=True,
        execute_after_compile=False,
    )

    resumed_events = run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-approve", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-approve",
        thread_id="thread-confirm-approve",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-confirm-approve",
            runId="run-confirm-approve",
            decision="approve",
        ),
        require_confirmation=True,
        execute_after_compile=False,
    )

    assert [event.type for event in resumed_events] == [
        "planning.confirmed",
        "agent_plan_graph.compile_started",
        "agent_plan_graph.compiled",
        "agent_plan_graph.compile_review_completed",
        "agent_plan_graph.execution_ready",
    ]
    assert model.calls == 2
    assert all(
        not event.type.startswith("agent_execution.")
        for event in resumed_events
    )
    confirmed = resumed_events[0]
    assert confirmed.payload["taskId"] == "task-confirm-approve"
    assert confirmed.payload["runId"] == "run-confirm-approve"
    assert confirmed.payload["threadId"] == "thread-confirm-approve"
    ready = resumed_events[-1]
    assert ready.payload["taskId"] == "task-confirm-approve"
    assert ready.payload["runId"] == "run-confirm-approve"
    assert ready.payload["threadId"] == "thread-confirm-approve"
    assert ready.payload["nodeCount"] == 2
    assert ready.payload["edgeCount"] == 1
    assert ready.payload["toolNodeCount"] == 0
    assert ready.payload["modelNodeCount"] == 2
    assert ready.payload["permissionsRequired"] == []
    assert ready.payload["expectedArtifacts"] == []
    app = build_deep_agent_runtime_graph(checkpointer=checkpointer, model_client=model)
    snapshot = app.get_state(deep_planning_thread_config("thread-confirm-approve"))
    assert snapshot.values["terminal_status"] == "execution_ready"
    assert snapshot.values["execution_ready"] is True
    assert snapshot.values["agent_compiled_graph"] is not None


def test_execution_ready_payload_expected_artifacts_are_path_strings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import agent_service.deep_agent_runtime_graph as runtime_graph
    from agent_service.agent_plan_compile import ExpectedArtifact

    original_compile = runtime_graph.compile_confirmed_agent_plan_graph

    def compile_with_expected_artifact(*args, **kwargs):
        compiled_graph = original_compile(*args, **kwargs)
        first_node = compiled_graph.nodes[0].model_copy(
            update={
                "expected_artifacts": [
                    ExpectedArtifact(
                        name="markdown",
                        path_template="artifacts/report.md",
                        mime_type="text/markdown",
                        source_argument="output_path",
                    )
                ]
            }
        )
        return compiled_graph.model_copy(
            update={
                "nodes": [
                    first_node,
                    *compiled_graph.nodes[1:],
                ]
            }
        )

    monkeypatch.setattr(
        runtime_graph,
        "compile_confirmed_agent_plan_graph",
        compile_with_expected_artifact,
    )

    project_path = tmp_path / "demo.alita"
    model = FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])
    checkpointer = InMemorySaver()

    run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-artifacts", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-artifacts",
        thread_id="thread-confirm-artifacts",
        checkpointer=checkpointer,
        require_confirmation=True,
        execute_after_compile=False,
    )

    resumed_events = run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-artifacts", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-artifacts",
        thread_id="thread-confirm-artifacts",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-confirm-artifacts",
            runId="run-confirm-artifacts",
            decision="approve",
        ),
        require_confirmation=True,
        execute_after_compile=False,
    )

    ready = next(
        event
        for event in resumed_events
        if event.type == "agent_plan_graph.execution_ready"
    )
    assert ready.payload["expectedArtifacts"] == ["artifacts/report.md"]
    assert all(
        isinstance(artifact, str)
        for artifact in ready.payload["expectedArtifacts"]
    )


def test_confirmation_approve_executes_agent_compiled_graph_when_enabled(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])
    checkpointer = InMemorySaver()
    requests = []

    def fake_execution_event_runner(request):
        requests.append(request)
        return [
            AgentEvent(type="run.started", payload={"runId": request.run_id}),
            AgentEvent(
                type="node.completed",
                payload={"nodeId": "understand", "artifactRefs": []},
            ),
            AgentEvent(
                type="node.completed",
                payload={
                    "nodeId": "write",
                    "artifactRefs": ["artifacts/final.md"],
                },
            ),
            AgentEvent(
                type="artifact.created",
                payload={"path": "artifacts/final.md"},
            ),
            AgentEvent(
                type="task.completed",
                payload={"taskId": request.task_id, "runId": request.run_id},
            ),
        ]

    run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-execute", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-execute",
        thread_id="thread-confirm-execute",
        checkpointer=checkpointer,
        require_confirmation=True,
        execute_after_compile=False,
    )

    resumed_events = run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-execute", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-execute",
        thread_id="thread-confirm-execute",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-confirm-execute",
            runId="run-confirm-execute",
            decision="approve",
        ),
        require_confirmation=True,
        execute_after_compile=True,
        execution_event_runner=fake_execution_event_runner,
    )

    assert len(requests) == 1
    request = requests[0]
    app = build_deep_agent_runtime_graph(checkpointer=checkpointer, model_client=model)
    snapshot = app.get_state(deep_planning_thread_config("thread-confirm-execute"))
    compiled_graph = snapshot.values["agent_compiled_graph"]
    assert request.task_id == compiled_graph["task_id"]
    assert request.run_id == compiled_graph["run_id"]
    assert request.project_path == str(project_path)
    assert request.graph.graphId == compiled_graph["source_graph_id"]
    assert request.graph.metadata == compiled_graph["metadata"]

    assert [event.type for event in resumed_events] == [
        "planning.confirmed",
        "agent_plan_graph.compile_started",
        "agent_plan_graph.compiled",
        "agent_plan_graph.compile_review_completed",
        "agent_plan_graph.execution_ready",
        "agent_execution.started",
        "run.started",
        "node.completed",
        "node.completed",
        "artifact.created",
        "task.completed",
        "agent_execution.completed",
        "agent_execution.verify_completed",
        "agent_execution.final",
    ]
    assert resumed_events[-3].payload["artifactRefs"] == ["artifacts/final.md"]
    assert snapshot.values["terminal_status"] == "final"
    assert snapshot.values["agent_execution_result"]["status"] == "completed"
    assert snapshot.values["agent_execution_review"]["status"] == "approved"


def test_default_execution_runner_reuses_runtime_model_client(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import agent_service.deep_agent_runtime_graph as runtime_graph

    project_path = tmp_path / "demo.alita"
    model = FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])
    checkpointer = InMemorySaver()
    captured_model_clients: list[object | None] = []

    def fake_run_graph_events(request, **kwargs):
        captured_model_clients.append(kwargs.get("model_client"))
        return [
            AgentEvent(
                type="task.completed",
                payload={
                    "taskId": request.task_id,
                    "runId": request.run_id,
                    "message": "done",
                },
            )
        ]

    monkeypatch.setattr(runtime_graph, "run_graph_events", fake_run_graph_events)

    run_deep_agent_runtime(
        UserMessage(task_id="task-default-execute", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-default-execute",
        thread_id="thread-default-execute",
        checkpointer=checkpointer,
        require_confirmation=True,
        execute_after_compile=False,
    )

    resumed_events = run_deep_agent_runtime(
        UserMessage(task_id="task-default-execute", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-default-execute",
        thread_id="thread-default-execute",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-default-execute",
            runId="run-default-execute",
            decision="approve",
        ),
        require_confirmation=True,
        execute_after_compile=True,
    )

    assert captured_model_clients == [model]
    assert resumed_events[-1].type == "agent_execution.final"


def test_agent_execution_failure_with_recovery_proposes_repair(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])
    checkpointer = InMemorySaver()
    recovery_action = {
        "type": "retry_node",
        "nodeId": "write",
        "reason": "Write step failed.",
    }

    def fake_execution_event_runner(request):
        return [
            AgentEvent(
                type="node.failed",
                payload={"nodeId": "write", "message": "Write step failed."},
            ),
            AgentEvent(
                type="recovery.action_proposed",
                payload={"action": recovery_action},
            ),
            AgentEvent(
                type="task.failed",
                payload={
                    "taskId": request.task_id,
                    "runId": request.run_id,
                    "nodeId": "write",
                    "message": "Write step failed.",
                },
            ),
        ]

    run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-repair", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-repair",
        thread_id="thread-confirm-repair",
        checkpointer=checkpointer,
        require_confirmation=True,
        execute_after_compile=False,
    )

    resumed_events = run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-repair", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-repair",
        thread_id="thread-confirm-repair",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-confirm-repair",
            runId="run-confirm-repair",
            decision="approve",
        ),
        require_confirmation=True,
        execute_after_compile=True,
        execution_event_runner=fake_execution_event_runner,
    )

    event_types = [event.type for event in resumed_events]
    assert "agent_execution.failed" in event_types
    assert "agent_execution.verify_completed" in event_types
    assert "agent_execution.repair_proposed" in event_types
    app = build_deep_agent_runtime_graph(checkpointer=checkpointer, model_client=model)
    snapshot = app.get_state(deep_planning_thread_config("thread-confirm-repair"))
    assert snapshot.values["terminal_status"] == "execution_repair_proposed"
    assert snapshot.values["execution_repair_plan"]["actions"] == [recovery_action]


def test_agent_execution_permission_failure_sets_interrupted_terminal_status(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])
    checkpointer = InMemorySaver()

    def fake_execution_event_runner(request):
        return [
            AgentEvent(
                type="permission.required",
                payload={"nodeId": "write", "permission": "filesystem.write"},
            ),
            AgentEvent(
                type="task.failed",
                payload={
                    "taskId": request.task_id,
                    "runId": request.run_id,
                    "errorCode": "permission_required",
                    "message": "Permission required.",
                },
            ),
        ]

    run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-permission", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-permission",
        thread_id="thread-confirm-permission",
        checkpointer=checkpointer,
        require_confirmation=True,
        execute_after_compile=False,
    )

    resumed_events = run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-permission", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-permission",
        thread_id="thread-confirm-permission",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-confirm-permission",
            runId="run-confirm-permission",
            decision="approve",
        ),
        require_confirmation=True,
        execute_after_compile=True,
        execution_event_runner=fake_execution_event_runner,
    )

    event_types = [event.type for event in resumed_events]
    assert "agent_execution.interrupted" in event_types
    assert "agent_execution.verify_completed" in event_types
    app = build_deep_agent_runtime_graph(checkpointer=checkpointer, model_client=model)
    snapshot = app.get_state(deep_planning_thread_config("thread-confirm-permission"))
    assert snapshot.values["terminal_status"] == "execution_interrupted"
    assert snapshot.values["agent_execution_result"]["failed_node_id"] == "write"


def test_agent_execution_runner_exception_records_failed_terminal_state(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])
    checkpointer = InMemorySaver()

    def fake_execution_event_runner(request):
        del request
        raise RuntimeError("runner exploded")

    run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-runner-error", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-runner-error",
        thread_id="thread-confirm-runner-error",
        checkpointer=checkpointer,
        require_confirmation=True,
        execute_after_compile=False,
    )

    resumed_events = run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-runner-error", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-runner-error",
        thread_id="thread-confirm-runner-error",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-confirm-runner-error",
            runId="run-confirm-runner-error",
            decision="approve",
        ),
        require_confirmation=True,
        execute_after_compile=True,
        execution_event_runner=fake_execution_event_runner,
    )

    event_types = [event.type for event in resumed_events]
    assert "agent_execution.started" in event_types
    assert "agent_execution.failed" in event_types
    assert "agent_execution.verify_completed" not in event_types
    failed = next(event for event in resumed_events if event.type == "agent_execution.failed")
    assert failed.payload["taskId"] == "task-confirm-runner-error"
    assert failed.payload["runId"] == "run-confirm-runner-error"
    assert failed.payload["threadId"] == "thread-confirm-runner-error"
    assert failed.payload["compileId"]
    assert failed.payload["graphId"]
    assert failed.payload["reason"] == "execution_bridge_failed"
    assert failed.payload["errorCode"] == "RuntimeError"
    app = build_deep_agent_runtime_graph(checkpointer=checkpointer, model_client=model)
    snapshot = app.get_state(deep_planning_thread_config("thread-confirm-runner-error"))
    assert snapshot.values["terminal_status"] == "execution_failed"
    assert snapshot.values["execution_failure"]["reason"] == "execution_bridge_failed"
    assert snapshot.values["execution_failure"]["errorCode"] == "RuntimeError"


def test_confirmation_approve_compile_failure_sets_compile_failed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import agent_service.deep_agent_runtime_graph as runtime_graph

    project_path = tmp_path / "demo.alita"
    model = FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])
    checkpointer = InMemorySaver()

    def fail_compile(*args, **kwargs):
        del args, kwargs
        raise AgentPlanCompileError("test_compile_failed", "compile failed for test")

    monkeypatch.setattr(
        runtime_graph,
        "compile_confirmed_agent_plan_graph",
        fail_compile,
    )

    run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-compile-fail", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-compile-fail",
        thread_id="thread-confirm-compile-fail",
        checkpointer=checkpointer,
        require_confirmation=True,
    )

    resumed_events = run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-compile-fail", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-compile-fail",
        thread_id="thread-confirm-compile-fail",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-confirm-compile-fail",
            runId="run-confirm-compile-fail",
            decision="approve",
        ),
        require_confirmation=True,
    )

    assert [event.type for event in resumed_events] == [
        "planning.confirmed",
        "agent_plan_graph.compile_started",
        "agent_plan_graph.compile_failed",
    ]
    assert model.calls == 2
    assert all(
        not event.type.startswith("agent_execution.")
        for event in resumed_events
    )
    failure = resumed_events[-1]
    assert failure.payload["taskId"] == "task-confirm-compile-fail"
    assert failure.payload["runId"] == "run-confirm-compile-fail"
    assert failure.payload["threadId"] == "thread-confirm-compile-fail"
    assert failure.payload["reason"] == "test_compile_failed"
    assert failure.payload["issues"] == [
        {
            "code": "test_compile_failed",
            "message": "compile failed for test",
            "severity": "error",
        }
    ]
    assert failure.payload["unsupportedCapabilities"] == []
    assert failure.payload["missingBindings"] == []

    app = build_deep_agent_runtime_graph(checkpointer=checkpointer, model_client=model)
    snapshot = app.get_state(
        deep_planning_thread_config("thread-confirm-compile-fail")
    )
    assert snapshot.values["terminal_status"] == "compile_failed"
    assert snapshot.values["execution_ready"] is False
    assert snapshot.values["compile_failure"]["reason"] == "test_compile_failed"


def test_confirmation_cancel_resume_sets_cancelled_terminal_status(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])
    checkpointer = InMemorySaver()

    run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-cancel", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-cancel",
        thread_id="thread-confirm-cancel",
        checkpointer=checkpointer,
        require_confirmation=True,
    )

    resumed_events = run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-cancel", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-cancel",
        thread_id="thread-confirm-cancel",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-confirm-cancel",
            runId="run-confirm-cancel",
            decision="cancel",
        ),
        require_confirmation=True,
    )

    assert [event.type for event in resumed_events] == ["planning.cancelled"]
    assert all(
        not event.type.startswith("agent_plan_graph.")
        for event in resumed_events
    )
    assert model.calls == 2
    app = build_deep_agent_runtime_graph(checkpointer=checkpointer, model_client=model)
    snapshot = app.get_state(deep_planning_thread_config("thread-confirm-cancel"))
    assert snapshot.values["terminal_status"] == "cancelled"


def test_confirmation_revise_resume_uses_revision_budget(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel(
        [
            _reasoning_payload(),
            _plan_payload(["draft"]),
            _plan_payload(["draft", "verify"]),
        ]
    )
    checkpointer = InMemorySaver()
    message = UserMessage(task_id="task-confirm-revise", content="Write a report.")

    run_deep_agent_runtime(
        message,
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-revise",
        thread_id="thread-confirm-revise",
        revision_budget=1,
        checkpointer=checkpointer,
        require_confirmation=True,
    )

    resumed_events = run_deep_agent_runtime(
        message,
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-revise",
        thread_id="thread-confirm-revise",
        revision_budget=1,
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-confirm-revise",
            runId="run-confirm-revise",
            decision="revise",
            revisionInstructions=["Add an explicit verification step."],
        ),
        require_confirmation=True,
    )

    event_types = [event.type for event in resumed_events]
    assert "planning.resumed" in event_types
    assert "planning.revision_started" in event_types
    assert all(
        not event_type.startswith("agent_plan_graph.")
        for event_type in event_types
    )
    assert event_types[-3:] == [
        "node_graph.created",
        "planning.confirmation_required",
        "planning.interrupted",
    ]
    assert model.calls == 3
    revision_prompt = json.loads(model.messages[2][1].content)
    assert "Add an explicit verification step." in (
        revision_prompt["revision_instructions"]
    )

    exhausted_events = run_deep_agent_runtime(
        message,
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-revise",
        thread_id="thread-confirm-revise",
        revision_budget=1,
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-confirm-revise",
            runId="run-confirm-revise",
            decision="revise",
            revisionInstructions=["Revise again."],
        ),
        require_confirmation=True,
    )

    assert model.calls == 3
    assert [event.type for event in exhausted_events][-2:] == [
        "planning.revision_exhausted",
        "planning.failed",
    ]


def test_confirmation_revise_without_instructions_uses_default_instruction(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel(
        [
            _reasoning_payload(),
            _plan_payload(["draft"]),
            _plan_payload(["draft", "verify"]),
        ]
    )
    checkpointer = InMemorySaver()
    message = UserMessage(task_id="task-confirm-default-revise", content="Write a report.")

    run_deep_agent_runtime(
        message,
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-default-revise",
        thread_id="thread-confirm-default-revise",
        revision_budget=1,
        checkpointer=checkpointer,
        require_confirmation=True,
    )

    run_deep_agent_runtime(
        message,
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-default-revise",
        thread_id="thread-confirm-default-revise",
        revision_budget=1,
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-confirm-default-revise",
            runId="run-confirm-default-revise",
            decision="revise",
        ),
        require_confirmation=True,
    )

    revision_prompt = json.loads(model.messages[2][1].content)
    assert "Revise the plan based on the user's confirmation feedback." in (
        revision_prompt["revision_instructions"]
    )


def test_fresh_invoke_same_thread_clears_confirmation_revision_instructions(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel(
        [
            _reasoning_payload(),
            _plan_payload(["draft"]),
            _plan_payload(["draft", "verify"]),
            _reasoning_payload(),
            _plan_payload(["fresh"]),
        ]
    )
    checkpointer = InMemorySaver()
    first_message = UserMessage(
        task_id="task-confirm-stale-revise",
        content="Write a report.",
    )

    run_deep_agent_runtime(
        first_message,
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-stale-revise",
        thread_id="thread-confirm-stale-revise",
        revision_budget=1,
        checkpointer=checkpointer,
        require_confirmation=True,
    )
    run_deep_agent_runtime(
        first_message,
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-stale-revise",
        thread_id="thread-confirm-stale-revise",
        revision_budget=1,
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-confirm-stale-revise",
            runId="run-confirm-stale-revise",
            decision="revise",
            revisionInstructions=["Add an explicit verification step."],
        ),
        require_confirmation=True,
    )
    run_deep_agent_runtime(
        first_message,
        project_path=str(project_path),
        model_client=model,
        run_id="run-confirm-stale-revise",
        thread_id="thread-confirm-stale-revise",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-confirm-stale-revise",
            runId="run-confirm-stale-revise",
            decision="approve",
        ),
        require_confirmation=True,
    )

    fresh_events = run_deep_agent_runtime(
        UserMessage(task_id="task-fresh-after-confirm", content="Write another report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-fresh-after-confirm",
        thread_id="thread-confirm-stale-revise",
        checkpointer=checkpointer,
        require_confirmation=False,
    )

    assert fresh_events[-1].type == "node_graph.created"
    fresh_prompt = json.loads(model.messages[4][1].content)
    assert fresh_prompt["revision_instructions"] == []
    assert "Add an explicit verification step." not in json.dumps(fresh_prompt)


def test_invalid_plan_revises_once_and_then_creates_graph(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel(
        [
            _reasoning_payload(),
            _invalid_plan_payload_missing_step_verification("analyze"),
            _plan_payload(["analyze", "write"]),
        ]
    )
    checkpointer = InMemorySaver()

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-revise-once", content="Write a tailored report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-revise-once",
        thread_id="thread-revise-once",
        revision_budget=2,
        checkpointer=checkpointer,
        require_confirmation=False,
    )

    event_types = [event.type for event in events]
    assert "planning.revision_requested" in event_types
    assert "planning.revision_started" in event_types
    assert "planning.revision_completed" in event_types
    assert events[-1].type == "node_graph.created"
    assert model.calls == 3

    requested = next(
        event for event in events if event.type == "planning.revision_requested"
    )
    started = next(event for event in events if event.type == "planning.revision_started")
    completed = next(
        event for event in events if event.type == "planning.revision_completed"
    )
    assert requested.payload["taskId"] == "task-revise-once"
    assert requested.payload["revisionCount"] == 1
    assert requested.payload["instructions"] == [
        "Add verification criteria for step analyze."
    ]
    assert "revisionInstructions" not in requested.payload
    assert started.payload["taskId"] == "task-revise-once"
    assert started.payload["instructions"] == [
        "Add verification criteria for step analyze."
    ]
    assert completed.payload["taskId"] == "task-revise-once"

    revision_prompt = json.loads(model.messages[2][1].content)
    assert (
        "Add verification criteria for step analyze."
        in revision_prompt["revision_instructions"]
    )


def test_revision_budget_exhaustion_fails_without_graph(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel(
        [
            _reasoning_payload(),
            _invalid_plan_payload_missing_step_verification("analyze"),
            _invalid_plan_payload_missing_step_verification("analyze"),
        ]
    )
    checkpointer = InMemorySaver()

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-revision-budget", content="Write a tailored report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-revision-budget",
        thread_id="thread-revision-budget",
        revision_budget=1,
        checkpointer=checkpointer,
        require_confirmation=False,
    )

    event_types = [event.type for event in events]
    assert "planning.revision_exhausted" in event_types
    assert events[-1].type == "planning.failed"
    assert all(event.type != "node_graph.created" for event in events)
    exhausted = next(
        event for event in events if event.type == "planning.revision_exhausted"
    )
    assert exhausted.payload["taskId"] == "task-revision-budget"
    assert exhausted.payload["revisionCount"] == 1
    assert exhausted.payload["revisionBudget"] == 1


def test_revised_plan_needing_clarification_fails_instead_of_looping(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel(
        [
            _reasoning_payload(),
            _invalid_plan_payload_missing_step_verification("analyze"),
            _clarification_plan_payload(),
        ]
    )

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-revision-clarify", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-revision-clarify",
        thread_id="thread-revision-clarify",
        revision_budget=1,
        checkpointer=InMemorySaver(),
        require_confirmation=False,
    )

    event_types = [event.type for event in events]
    assert "planning.revision_exhausted" in event_types
    assert "planning.interrupted" not in event_types
    assert events[-1].type == "planning.failed"
    assert events[-1].payload["reason"] == (
        "plan_review_needs_clarification_after_revision"
    )


def test_multiple_clarifications_use_latest_answer_for_revision(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel(
        [
            _reasoning_payload(),
            _clarification_plan_payload(),
            _clarification_plan_payload(),
            _invalid_plan_payload_missing_step_verification("analyze"),
            _plan_payload(["analyze", "write"]),
        ]
    )
    checkpointer = InMemorySaver()
    message = UserMessage(task_id="task-multi-clarify", content="Write a report.")

    run_deep_agent_runtime(
        message,
        project_path=str(project_path),
        model_client=model,
        run_id="run-multi-clarify",
        thread_id="thread-multi-clarify",
        checkpointer=checkpointer,
        require_confirmation=False,
    )
    run_deep_agent_runtime(
        message,
        project_path=str(project_path),
        model_client=model,
        run_id="run-multi-clarify",
        thread_id="thread-multi-clarify",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="clarification_answer",
            threadId="thread-multi-clarify",
            runId="run-multi-clarify",
            answer="The report is for executives.",
        ),
        require_confirmation=False,
    )
    run_deep_agent_runtime(
        message,
        project_path=str(project_path),
        model_client=model,
        run_id="run-multi-clarify",
        thread_id="thread-multi-clarify",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="clarification_answer",
            threadId="thread-multi-clarify",
            runId="run-multi-clarify",
            answer="The report is for engineers.",
        ),
        require_confirmation=False,
    )

    revision_prompt = json.loads(model.messages[4][1].content)
    revision_instructions = revision_prompt["revision_instructions"]
    assert any("engineers" in instruction for instruction in revision_instructions)
    assert all("executives" not in instruction for instruction in revision_instructions)


def test_fresh_invoke_same_thread_clears_stale_clarification_answer(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel(
        [
            _reasoning_payload(),
            _clarification_plan_payload(),
            _clarification_plan_payload(),
            _reasoning_payload(),
            _plan_payload(["fresh"]),
        ]
    )
    checkpointer = InMemorySaver()
    message = UserMessage(task_id="task-stale-clarify", content="Write a report.")

    first_events = run_deep_agent_runtime(
        message,
        project_path=str(project_path),
        model_client=model,
        run_id="run-stale-clarify",
        thread_id="thread-stale-clarify",
        checkpointer=checkpointer,
        require_confirmation=False,
    )
    assert first_events[-1].type == "planning.interrupted"

    second_events = run_deep_agent_runtime(
        message,
        project_path=str(project_path),
        model_client=model,
        run_id="run-stale-clarify",
        thread_id="thread-stale-clarify",
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="clarification_answer",
            threadId="thread-stale-clarify",
            runId="run-stale-clarify",
            answer="The report is for executives.",
        ),
        require_confirmation=False,
    )
    assert second_events[-1].type == "planning.interrupted"
    resumed_prompt = json.loads(model.messages[2][1].content)
    assert any(
        "executives" in instruction
        for instruction in resumed_prompt["revision_instructions"]
    )

    fresh_events = run_deep_agent_runtime(
        UserMessage(task_id="task-fresh", content="Write a different report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-fresh",
        thread_id="thread-stale-clarify",
        checkpointer=checkpointer,
        require_confirmation=False,
    )

    assert fresh_events[-1].type == "node_graph.created"
    fresh_prompt = json.loads(model.messages[4][1].content)
    assert fresh_prompt["revision_instructions"] == []
    assert "executives" not in json.dumps(fresh_prompt)


def test_fresh_invoke_same_thread_clears_stale_graph_review_for_revision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import agent_service.deep_agent_runtime_graph as runtime_graph

    project_path = tmp_path / "demo.alita"
    model = FakeModel(
        [
            _reasoning_payload(),
            _plan_payload(["analyze", "write"]),
            _reasoning_payload(),
            _invalid_plan_payload_missing_step_verification("fresh"),
            _plan_payload(["fresh"]),
        ]
    )
    checkpointer = InMemorySaver()
    review_calls = 0

    def review_graph_once_invalid(draft, graph):
        del draft, graph
        nonlocal review_calls
        review_calls += 1
        if review_calls == 1:
            return GraphReview(
                status="invalid",
                findings=["missing_edge:analyze->write"],
            )
        return GraphReview(status="approved")

    monkeypatch.setattr(
        runtime_graph,
        "review_compiled_graph",
        review_graph_once_invalid,
    )

    first_events = run_deep_agent_runtime(
        UserMessage(task_id="task-stale-graph", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-stale-graph",
        thread_id="thread-stale-graph",
        revision_budget=0,
        checkpointer=checkpointer,
        require_confirmation=False,
    )
    assert first_events[-1].type == "planning.failed"
    assert first_events[-1].payload["reason"] == "graph_review_invalid"

    fresh_events = run_deep_agent_runtime(
        UserMessage(task_id="task-fresh-graph", content="Write another report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-fresh-graph",
        thread_id="thread-stale-graph",
        revision_budget=1,
        checkpointer=checkpointer,
        require_confirmation=False,
    )

    assert fresh_events[-1].type == "node_graph.created"
    revision_prompt = json.loads(model.messages[4][1].content)
    revision_instructions = revision_prompt["revision_instructions"]
    assert "Add verification criteria for step fresh." in revision_instructions
    assert "Add the missing graph edge from analyze to write." not in (
        revision_instructions
    )


def test_graph_review_revision_prompt_uses_concrete_instructions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import agent_service.deep_agent_runtime_graph as runtime_graph

    project_path = tmp_path / "demo.alita"
    model = FakeModel(
        [
            _reasoning_payload(),
            _plan_payload(["analyze", "write"]),
            _plan_payload(["analyze", "write"]),
        ]
    )
    calls = 0

    def review_graph_once_invalid(draft, graph):
        del draft, graph
        nonlocal calls
        calls += 1
        if calls == 1:
            return GraphReview(
                status="invalid",
                findings=["missing_edge:analyze->write"],
            )
        return GraphReview(status="approved")

    monkeypatch.setattr(
        runtime_graph,
        "review_compiled_graph",
        review_graph_once_invalid,
    )

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-graph-review", content="Write a report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-graph-review",
        thread_id="thread-graph-review",
        revision_budget=1,
        checkpointer=InMemorySaver(),
        require_confirmation=False,
    )

    assert events[-1].type == "node_graph.created"
    requested = next(
        event for event in events if event.type == "planning.revision_requested"
    )
    assert requested.payload["reason"] == "graph_review_invalid"
    assert requested.payload["instructions"] == [
        "Add the missing graph edge from analyze to write."
    ]
    revision_prompt = json.loads(model.messages[2][1].content)
    assert "Add the missing graph edge from analyze to write." in (
        revision_prompt["revision_instructions"]
    )


def test_run_deep_agent_runtime_creates_default_sqlite_checkpoint(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.alita"
    model = FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])

    run_deep_agent_runtime(
        UserMessage(task_id="task-deep", content="Write a tailored report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-default-sqlite",
        thread_id="thread-default-sqlite",
        require_confirmation=False,
    )

    assert (
        tmp_path / "node-runs" / "run-default-sqlite" / "deep-planning.sqlite"
    ).exists()


def test_runtime_store_mirrors_latest_planning_checkpoint_summary(
    tmp_path: Path,
) -> None:
    model = FakeModel([_reasoning_payload(), _plan_payload(["understand", "write"])])
    project_path = tmp_path / "demo.alita"
    store = RuntimeStore(project_path=str(project_path), run_id="run-store-mirror")
    checkpointer = InMemorySaver()

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-deep", content="Write a tailored report."),
        project_path=str(project_path),
        model_client=model,
        run_id="run-store-mirror",
        thread_id="thread-store-mirror",
        checkpointer=checkpointer,
        runtime_store=store,
        require_confirmation=False,
    )

    checkpoint_events = [
        event for event in events if event.type == "planning.checkpoint_recorded"
    ]
    assert checkpoint_events
    assert "checkpoint" in checkpoint_events[-1].payload
    assert "summary" not in checkpoint_events[-1].payload

    summary = store.read_latest_planning_checkpoint_summary()
    assert summary is not None
    assert summary["runId"] == "run-store-mirror"
    assert summary["threadId"] == "thread-store-mirror"
    assert "checkpointId" in summary
    assert summary["stage"] in {"planning", "reasoning", "build_context", "deep_plan"}
    assert "revisionCount" in summary
    assert "hasPlanDraft" in summary
    assert "hasCompiledGraph" in summary
    assert "createdAt" in summary
    assert "rawReasoning" not in summary
    assert "projectPath" not in summary
    assert "planDraft" not in summary
