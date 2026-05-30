from agent_service.runtime_state import (
    RuntimeAction,
    RuntimeStateDelta,
    initial_runtime_state,
)
from agent_service.schemas import UserMessage


def test_initial_runtime_state_uses_route_stage_and_thread_id():
    message = UserMessage(task_id="task-1", content="Create a report.")

    state = initial_runtime_state(
        message=message,
        project_path="D:/Project/demo.alita",
        run_id="run-1",
    )

    assert state.thread_id == "thread-task-1"
    assert state.run_id == "run-1"
    assert state.task_id == "task-1"
    assert state.stage == "route"
    assert state.messages[0]["role"] == "user"
    assert state.messages[0]["content"] == "Create a report."
    assert state.project_path == "D:/Project/demo.alita"


def test_runtime_action_records_model_tool_human_and_control_shape():
    action = RuntimeAction(
        action_id="act-1",
        action_type="tool",
        name="internal:test.echo_values",
        inputs={"message": "hello"},
        expected_outputs={"text": "string"},
        dependencies=["act-0"],
    )

    assert action.action_id == "act-1"
    assert action.action_type == "tool"
    assert action.permissions == []
    assert action.timeout_ms is None


def test_runtime_delta_records_stage_transition_and_writes():
    delta = RuntimeStateDelta(
        previous_checkpoint_id="ckpt-1",
        checkpoint_id="ckpt-2",
        stage_before="plan",
        stage_after="act",
        decision={"actionId": "act-1"},
        writes=[{"kind": "selected_action", "actionId": "act-1"}],
        emitted_events=[{"type": "runtime.state_delta"}],
    )

    assert delta.stage_before == "plan"
    assert delta.stage_after == "act"
    assert delta.writes[0]["kind"] == "selected_action"
