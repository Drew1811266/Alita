from agent_service.tool_graph_planner import (
    PlannedToolNode,
    ToolActionGraph,
    validate_tool_action_graph,
)
from agent_service.tool_ports import port_type_for_schema


def test_port_type_inference_normalizes_common_tool_schema_fields() -> None:
    assert port_type_for_schema("source_text", {"type": "string"}) == "text"
    assert port_type_for_schema("input_path", {"type": "string"}) == "file_path"
    assert port_type_for_schema("input_paths", {"type": "array", "items": {"type": "string"}}) == "file_paths"
    assert port_type_for_schema("pdf_output_path", {"type": "string"}) == "pdf"
    assert port_type_for_schema("metadata", {"type": "object"}) == "json"


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


def test_tool_action_graph_reports_incompatible_output_mapping() -> None:
    graph = ToolActionGraph(
        nodes=[
            PlannedToolNode(
                node_id="extract",
                tool_id="internal:document.read",
                operation="read",
                output_schema={
                    "type": "object",
                    "properties": {"artifact": {"type": "string"}},
                },
            ),
            PlannedToolNode(
                node_id="report",
                tool_id="internal:test.echo_values",
                operation="echo_values",
                arguments={"source_text": "{extract.artifact}"},
                dependencies=["extract"],
                required_arguments=["source_text"],
                input_schema={
                    "type": "object",
                    "properties": {"source_text": {"type": "string"}},
                },
            ),
        ]
    )

    diagnostics = validate_tool_action_graph(graph)

    assert diagnostics == [
        "node report maps incompatible port extract.artifact -> source_text"
    ]
