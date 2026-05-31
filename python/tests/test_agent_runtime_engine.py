from agent_service.agent_run_state import AgentRunState
from agent_service.agent_runtime_engine import AgentRuntimeEngine
from agent_service.runtime_loop import RuntimeCheckpoint
from agent_service.runtime_store import RuntimeStore
from agent_service.schemas import AgentEvent, UserMessage


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

    engine = AgentRuntimeEngine(route_runner=fake_runner)
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

    engine = AgentRuntimeEngine(route_runner=fake_runner)
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

    engine = AgentRuntimeEngine(route_runner=fake_runner)
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="task-runtime-entry", content="hello")
    ).model_copy(
        update={"project_path": "D:/Project/demo.alita", "run_id": "run-entry"}
    )

    result = engine.run_from_state(run_state)

    assert captured[0].task_id == "task-runtime-entry"
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "runtime.state_delta",
        "message.created",
    ]
    assert result.state.stage == "plan"
    assert result.events[1].payload["delta"]["decision"]["kind"] == (
        "legacy_route_and_plan"
    )


def test_engine_run_from_agent_state_persists_runtime_state_and_delta(tmp_path):
    def fake_runner(
        run_state: AgentRunState,
        **kwargs,
    ) -> list[AgentEvent]:
        del run_state, kwargs
        return [
            AgentEvent(
                type="node_graph.created",
                payload={"graph": {"graphId": "graph-1", "nodes": [], "edges": []}},
            )
        ]

    project_path = str(tmp_path / "demo.alita")
    store = RuntimeStore(project_path=project_path, run_id="run-store-engine")
    engine = AgentRuntimeEngine(route_runner=fake_runner, runtime_store=store)
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
    assert deltas[0].decision == {"kind": "legacy_route_and_plan"}


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
