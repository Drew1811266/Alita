from __future__ import annotations

import pytest

from agent_service.execution_graph import ExecutionGraph, ExecutionGraphError
from agent_service.schemas import RunGraph


def test_execution_graph_projects_run_graph_nodes() -> None:
    graph = RunGraph(
        graphId="graph-1",
        nodes=[
            {
                "nodeId": "document-parse",
                "nodeType": "fixed_tool",
                "displayName": "Document parse",
                "status": "waiting",
                "dependencies": [],
                "toolRef": "internal:document.markitdown_convert",
                "summary": "Convert document.",
                "createdBy": "agent",
                "permissionsRequired": ["read_attachment"],
                "riskLevel": "read_only",
                "position": {"x": 0, "y": 0},
            },
            {
                "nodeId": "file-export",
                "nodeType": "output",
                "displayName": "Export",
                "status": "waiting",
                "dependencies": ["document-parse"],
                "summary": "Export artifact.",
                "createdBy": "agent",
                "position": {"x": 180, "y": 0},
            },
        ],
        edges=[
            {
                "id": "document-parse-file-export",
                "source": "document-parse",
                "target": "file-export",
            }
        ],
    )

    execution_graph = ExecutionGraph.from_run_graph(graph)

    assert execution_graph.graph_id == "graph-1"
    assert [node.node_id for node in execution_graph.ordered_nodes()] == [
        "document-parse",
        "file-export",
    ]
    parse_node = execution_graph.node_by_id("document-parse")
    assert parse_node.node_type == "fixed_tool"
    assert parse_node.tool_id == "internal:document.markitdown_convert"
    assert parse_node.permissions_required == ["read_attachment"]
    assert parse_node.risk_level == "read_only"


def test_execution_graph_rejects_duplicate_node_ids() -> None:
    graph = RunGraph(
        graphId="graph-dup",
        nodes=[
            _node("same"),
            _node("same"),
        ],
        edges=[],
    )

    with pytest.raises(ExecutionGraphError, match="duplicate node id: same"):
        ExecutionGraph.from_run_graph(graph)


def test_execution_graph_rejects_missing_dependency() -> None:
    graph = RunGraph(
        graphId="graph-missing-dep",
        nodes=[
            _node("child", dependencies=["missing-parent"]),
        ],
        edges=[],
    )

    with pytest.raises(ExecutionGraphError, match="missing dependency"):
        ExecutionGraph.from_run_graph(graph)


def _node(node_id: str, dependencies: list[str] | None = None) -> dict:
    return {
        "nodeId": node_id,
        "nodeType": "model",
        "displayName": node_id,
        "status": "waiting",
        "dependencies": dependencies or [],
        "summary": "Test node.",
        "createdBy": "agent",
        "position": {"x": 0, "y": 0},
    }
