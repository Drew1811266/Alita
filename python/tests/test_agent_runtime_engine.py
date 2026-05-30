from agent_service.agent_runtime_engine import AgentRuntimeEngine
from agent_service.schemas import UserMessage


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


def test_engine_step_routes_and_plans_task_with_existing_planner():
    engine = AgentRuntimeEngine()
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

    event_types = [event.type for event in events]
    assert "runtime.state_delta" in event_types
    assert "node_graph.created" in event_types


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
