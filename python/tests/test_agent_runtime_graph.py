from agent_service.agent_runtime_graph import AgentRuntimeGraph, AgentRuntimeGraphState


def test_runtime_graph_routes_task_to_planning_state():
    graph = AgentRuntimeGraph()
    state = AgentRuntimeGraphState(
        task_id="task-1",
        message="summarize this",
        project_path="demo.alita",
    )

    result = graph.route(state)

    assert result.stage == "plan"
    assert result.task_id == "task-1"


def test_runtime_graph_marks_execution_ready_when_graph_exists():
    graph = AgentRuntimeGraph()
    state = AgentRuntimeGraphState(
        task_id="task-1",
        message="summarize this",
        project_path="demo.alita",
        graph_payload={"graphId": "graph-1"},
    )

    result = graph.plan_ready(state)

    assert result.stage == "execute"
    assert result.graph_payload == {"graphId": "graph-1"}


def test_runtime_graph_fails_execution_ready_without_graph():
    graph = AgentRuntimeGraph()
    state = AgentRuntimeGraphState(
        task_id="task-1",
        message="summarize this",
        project_path="demo.alita",
    )

    result = graph.plan_ready(state)

    assert result.stage == "failed"
    assert result.error_code == "missing_graph"
