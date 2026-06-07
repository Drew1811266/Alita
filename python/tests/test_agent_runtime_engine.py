import json

from agent_service.agent_run_state import AgentRunState
from agent_service.agent_runtime_engine import AgentRuntimeEngine
from agent_service.runtime_loop import RuntimeCheckpoint
from agent_service.runtime_store import RuntimeStore
from agent_service.schemas import AgentEvent, UserMessage


class FakeSemanticModel:
    def __init__(self, route: str) -> None:
        self.route = route
        self.calls = 0

    def chat(self, messages, *, temperature=None, max_tokens=None, policy=None):
        del messages, temperature, max_tokens, policy
        self.calls += 1
        return json.dumps(
            {
                "route": self.route,
                "intent": "runtime_engine_test",
                "complexity": (
                    "simple" if self.route == "response_only" else "multi_step"
                ),
                "requiresGraph": self.route == "deep_planning",
                "requiresTools": self.route == "deep_planning",
                "requiresWeb": False,
                "requiresFiles": False,
                "requiresClarification": False,
                "language": "en",
                "confidence": 0.94,
                "contextUsed": ["current_message"],
                "missingInputs": [],
                "requiredCapabilities": [],
                "toolCandidates": [],
                "reason": "Semantic router test route.",
            }
        )


def _simple_deep_runtime(*args, **kwargs) -> list[AgentEvent]:
    del args, kwargs
    return [
        AgentEvent(
            type="reasoning.decision_created",
            payload={"decision": {"next_action": "simple_answer"}},
        ),
        AgentEvent(
            type="reasoning.completed",
            payload={"taskId": "task-runtime-entry", "nextAction": "simple_answer"},
        ),
    ]


def test_engine_start_run_creates_runtime_state_and_started_event():
    engine = AgentRuntimeEngine()
    message = UserMessage(task_id="task-engine", content="Create a Python script.")

    result = engine.start_run(
        message=message,
        project_path="D:/Project/demo.alita",
        run_id="run-engine",
    )

    assert result.state.stage == "route"
    assert result.state.run_id == "run-engine"
    assert [event.type for event in result.events] == ["runtime.run_started"]
    assert result.events[0].payload["runId"] == "run-engine"


def test_engine_step_route_advances_to_context_without_calling_legacy_runner():
    legacy_calls: list[AgentRunState] = []

    def fake_runner(run_state: AgentRunState, **kwargs) -> list[AgentEvent]:
        del kwargs
        legacy_calls.append(run_state)
        return []

    engine = AgentRuntimeEngine(
        route_runner=fake_runner,
        deep_runtime_runner=_simple_deep_runtime,
    )
    message = UserMessage(
        task_id="task-engine-plan",
        content="Create a Python script that counts CSV rows.",
    )

    started = engine.start_run(
        message=message,
        project_path="D:/Project/demo.alita",
        run_id="run-engine-plan",
    )
    events = engine.step(started.state)

    assert legacy_calls == []
    assert [event.type for event in events] == ["runtime.state_delta"]
    delta = events[0].payload["delta"]
    assert delta["stage_before"] == "route"
    assert delta["stage_after"] == "context"
    assert delta["decision"] == {"kind": "route"}


def test_engine_step_plan_uses_legacy_planner_and_records_action_graph():
    def fake_runner(run_state: AgentRunState, **kwargs) -> list[AgentEvent]:
        del run_state, kwargs
        return [
            AgentEvent(
                type="node_graph.created",
                payload={
                    "graph": {
                        "graphId": "task-engine-plan-graph",
                        "nodes": [
                            {
                                "nodeId": "tool-node",
                                "nodeType": "fixed_tool",
                                "displayName": "Tool",
                                "status": "waiting",
                                "inputPorts": [],
                                "outputPorts": [],
                                "dependencies": [],
                                "toolRef": "document.read_write",
                                "summary": "Read and write.",
                                "createdBy": "agent",
                                "artifactRefs": [],
                                "retryCount": 0,
                                "position": {"x": 0, "y": 0},
                            }
                        ],
                        "edges": [],
                    }
                },
            )
        ]

    engine = AgentRuntimeEngine(
        route_runner=fake_runner,
        deep_runtime_runner=_simple_deep_runtime,
        allow_legacy_task_product_path=True,
    )
    started = engine.start_run(
        message=UserMessage(
            task_id="task-engine-action-graph",
            content="Use a document tool.",
        ),
        project_path="D:/Project/demo.alita",
        run_id="run-engine-action-graph",
    )
    plan_state = started.state.model_copy(update={"stage": "plan"})

    events = engine.step(plan_state)

    assert [event.type for event in events] == [
        "runtime.state_delta",
        "node_graph.created",
    ]
    delta = events[0].payload["delta"]
    assert delta["stage_before"] == "plan"
    assert delta["stage_after"] == "act"
    assert delta["writes"][0]["kind"] == "action_graph"
    assert delta["writes"][0]["actionGraph"]["actions"][0]["action_type"] == "tool"


def test_engine_run_from_agent_state_wraps_legacy_events_with_runtime_events():
    captured: list[AgentRunState] = []

    def fake_runner(
        run_state: AgentRunState,
        **kwargs,
    ) -> list[AgentEvent]:
        del kwargs
        captured.append(run_state)
        return [
            AgentEvent(
                type="message.created",
                payload={"message": {"content": "ok"}},
            )
        ]

    engine = AgentRuntimeEngine(
        route_runner=fake_runner,
        deep_runtime_runner=_simple_deep_runtime,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-runtime-entry",
            content="Create a one sentence greeting for the user.",
        )
    ).model_copy(
        update={"project_path": "D:/Project/demo.alita", "run_id": "run-entry"}
    )

    result = engine.run_from_state(
        run_state,
        model_client=FakeSemanticModel("response_only"),
    )

    assert captured[0].task_id == "task-runtime-entry"
    assert captured[0].intent == "chat"
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "runtime.state_delta",
        "message.created",
    ]
    assert result.state.stage == "plan"
    assert (
        result.events[1].payload["delta"]["decision"]["kind"]
        == "legacy_response_only"
    )


def test_engine_run_from_agent_state_persists_runtime_state_and_delta(tmp_path):
    def fake_runner(
        run_state: AgentRunState,
        **kwargs,
    ) -> list[AgentEvent]:
        del run_state, kwargs
        return [
            AgentEvent(
                type="message.created",
                payload={"message": {"content": "ok"}},
            )
        ]

    project_path = str(tmp_path / "demo.alita")
    store = RuntimeStore(project_path=project_path, run_id="run-store-engine")
    engine = AgentRuntimeEngine(
        route_runner=fake_runner,
        deep_runtime_runner=_simple_deep_runtime,
        runtime_store=store,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="task-store-engine", content="Create a graph.")
    ).model_copy(update={"project_path": project_path, "run_id": "run-store-engine"})

    engine.run_from_state(run_state)

    restored = store.read_state()
    deltas = store.read_deltas()
    assert restored is not None
    assert restored.stage == "plan"
    assert restored.run_id == "run-store-engine"
    assert [delta.stage_after for delta in deltas] == ["plan"]
    assert deltas[0].decision == {"kind": "legacy_response_only"}


def test_engine_step_plan_blocks_legacy_planner_by_default():
    legacy_calls: list[AgentRunState] = []

    def fake_runner(run_state: AgentRunState, **kwargs) -> list[AgentEvent]:
        del kwargs
        legacy_calls.append(run_state)
        return [
            AgentEvent(
                type="node_graph.created",
                payload={"graph": {"graphId": "graph-1", "nodes": [], "edges": []}},
            )
        ]

    engine = AgentRuntimeEngine(
        route_runner=fake_runner,
        deep_runtime_runner=_simple_deep_runtime,
    )
    started = engine.start_run(
        message=UserMessage(
            task_id="task-engine-plan-default-blocked",
            content="Use a document tool.",
        ),
        project_path="D:/Project/demo.alita",
        run_id="run-engine-plan-default-blocked",
    )
    plan_state = started.state.model_copy(update={"stage": "plan"})

    events = engine.step(plan_state)

    assert legacy_calls == []
    assert [event.type for event in events] == [
        "runtime.state_delta",
        "runtime.legacy_graph_blocked",
        "task.failed",
    ]
    delta = events[0].payload["delta"]
    assert delta["stage_before"] == "plan"
    assert delta["stage_after"] == "failed"
    assert delta["decision"] == {
        "kind": "legacy_graph_blocked",
        "blockedEventTypes": ["legacy_plan_action_graph"],
    }
    assert events[-2].payload["reason"] == (
        "legacy plan action graph is blocked from the Agent Runtime product path"
    )
    assert events[-1].payload["errorCode"] == "legacy_graph_blocked"


def test_engine_stream_terminal_deep_runtime_persists_plan_state(tmp_path):
    def deep_runtime(*args, **kwargs) -> list[AgentEvent]:
        del args, kwargs
        return [
            AgentEvent(
                type="node_graph.created",
                payload={"graph": {"graphId": "graph-1", "nodes": [], "edges": []}},
            )
        ]

    def stream_runner(*args, **kwargs):
        del args, kwargs
        raise AssertionError("legacy stream runner must not run after terminal graph")

    project_path = str(tmp_path / "demo.alita")
    store = RuntimeStore(project_path=project_path, run_id="run-stream-store")
    engine = AgentRuntimeEngine(
        deep_runtime_runner=deep_runtime,
        stream_runner=stream_runner,
        runtime_store=store,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="task-stream-store", content="Create a graph.")
    ).model_copy(update={"project_path": project_path, "run_id": "run-stream-store"})

    events = list(
        engine.stream_from_state(
            run_state,
            model_client=FakeSemanticModel("deep_planning"),
        )
    )

    assert [event.type for event in events] == [
        "runtime.run_started",
        "node_graph.created",
    ]
    restored = store.read_state()
    assert restored is not None
    assert restored.stage == "plan"


def test_engine_resume_restores_state_from_runtime_store(tmp_path):
    project_path = str(tmp_path / "demo.alita")
    state = AgentRuntimeEngine().start_run(
        message=UserMessage(task_id="task-resume-engine", content="Resume this."),
        project_path=project_path,
        run_id="run-resume-engine",
    ).state
    planned_state = state.model_copy(update={"stage": "plan"})
    store = RuntimeStore(project_path=project_path, run_id="run-resume-engine")
    store.write_checkpoint(
        RuntimeCheckpoint(
            run_id="run-resume-engine",
            node_id="plan",
            status="after_node",
            completed_outputs={},
            pending_node_ids=[],
            created_at="2026-05-31T00:00:00Z",
            sequence=1,
            runtime_state=planned_state.model_dump(),
        )
    )

    result = AgentRuntimeEngine(runtime_store=store).resume(
        state,
        checkpoint_id="plan:after_node:0",
    )

    assert result.state.stage == "plan"
    assert [event.type for event in result.events] == [
        "runtime.resume_requested",
        "runtime.resumed",
    ]
    assert result.events[1].payload["checkpointId"].startswith(
        "ckpt-run-resume-engine-000001-"
    )


def test_engine_interrupt_marks_state_interrupted():
    engine = AgentRuntimeEngine()
    message = UserMessage(task_id="task-interrupt", content="Create a report.")
    started = engine.start_run(
        message=message,
        project_path="D:/Project/demo.alita",
        run_id="run-interrupt",
    )

    result = engine.interrupt(started.state, reason="user_cancelled")

    assert result.state.stage == "interrupted"
    assert result.events[0].type == "runtime.interrupted"
