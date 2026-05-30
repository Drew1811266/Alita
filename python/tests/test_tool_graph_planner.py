from agent_service.tool_graph_planner import (
    PlannedToolNode,
    ToolActionGraph,
    validate_tool_action_graph,
)


def test_tool_action_graph_requires_dependency_outputs_for_mappings() -> None:
    graph = ToolActionGraph(
        nodes=[
            PlannedToolNode(
                node_id="extract",
                tool_id="internal:document.read",
                operation="read",
                arguments={
                    "input_paths": ["a.docx"],
                    "output_path": "artifacts/a.md",
                },
                output_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                },
            ),
            PlannedToolNode(
                node_id="report",
                tool_id="internal:test.echo_values",
                operation="echo_values",
                arguments={"source_text": "{extract.text}"},
                dependencies=["extract"],
                required_arguments=["source_text"],
            ),
        ]
    )

    diagnostics = validate_tool_action_graph(graph)

    assert diagnostics == []


def test_tool_action_graph_reports_missing_required_argument() -> None:
    graph = ToolActionGraph(
        nodes=[
            PlannedToolNode(
                node_id="report",
                tool_id="internal:test.echo_values",
                operation="echo_values",
                arguments={},
                required_arguments=["source_text"],
            )
        ]
    )

    diagnostics = validate_tool_action_graph(graph)

    assert diagnostics == ["node report missing required argument: source_text"]


def test_tool_action_graph_reports_missing_dependency_output_mapping() -> None:
    graph = ToolActionGraph(
        nodes=[
            PlannedToolNode(
                node_id="extract",
                tool_id="internal:document.read",
                operation="read",
                output_schema={
                    "type": "object",
                    "properties": {"artifacts": {"type": "array"}},
                },
            ),
            PlannedToolNode(
                node_id="report",
                tool_id="internal:test.echo_values",
                operation="echo_values",
                arguments={"source_text": "{extract.text}"},
                dependencies=["extract"],
                required_arguments=["source_text"],
            ),
        ]
    )

    diagnostics = validate_tool_action_graph(graph)

    assert diagnostics == ["node report maps missing output extract.text"]
