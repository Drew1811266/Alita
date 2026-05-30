from agent_service.action_graph import action_graph_from_run_graph
from agent_service.schemas import RunGraph


def test_action_graph_from_run_graph_maps_fixed_tool_model_and_output_nodes() -> None:
    graph = RunGraph(
        graphId="graph-1",
        nodes=[
            {
                "nodeId": "tool-a",
                "nodeType": "fixed_tool",
                "displayName": "Tool A",
                "status": "waiting",
                "toolRef": "internal:test.echo_values",
                "permissionsRequired": ["read_project_files"],
                "summary": "Echo values.",
                "createdBy": "agent",
                "position": {"x": 0, "y": 0},
            },
            {
                "nodeId": "reason",
                "nodeType": "model",
                "displayName": "Reason",
                "status": "waiting",
                "dependencies": ["tool-a"],
                "modelRef": "local-task-reasoner",
                "summary": "Reason over tool output.",
                "createdBy": "agent",
                "position": {"x": 100, "y": 0},
            },
            {
                "nodeId": "output",
                "nodeType": "output",
                "displayName": "Output",
                "status": "waiting",
                "dependencies": ["reason"],
                "summary": "Final output.",
                "createdBy": "agent",
                "position": {"x": 200, "y": 0},
            },
        ],
        edges=[],
    )

    action_graph = action_graph_from_run_graph(graph)

    assert action_graph.graph_id == "graph-1"
    assert [action.action_id for action in action_graph.actions] == [
        "tool-a",
        "reason",
        "output",
    ]
    assert [action.action_type for action in action_graph.actions] == [
        "tool",
        "model",
        "control",
    ]
    assert action_graph.actions[0].name == "internal:test.echo_values"
    assert action_graph.actions[0].permissions == [
        {"permission": "read_project_files"}
    ]
    assert action_graph.actions[1].dependencies == ["tool-a"]
