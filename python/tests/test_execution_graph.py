from __future__ import annotations

import pytest

from agent_service.execution_graph import (
    ExecutionGraphError,
    compile_execution_graph,
    validate_execution_graph_bindings,
)
from agent_service.schemas import GraphEdge, GraphNode, RunGraph, RunGraphRequest


def _node(
    node_id: str,
    node_type: str,
    *,
    dependencies: list[str] | None = None,
    tool_ref: str | None = None,
    model_ref: str | None = None,
    permissions: list[str] | None = None,
) -> GraphNode:
    return GraphNode(
        nodeId=node_id,
        nodeType=node_type,
        displayName=node_id,
        status="waiting",
        summary=f"{node_id} summary",
        createdBy="test",
        inputPorts=[],
        outputPorts=[],
        dependencies=list(dependencies or []),
        toolRef=tool_ref,
        modelRef=model_ref,
        permissionsRequired=list(permissions or []),
        position={"x": 0, "y": 0},
    )


def _request(nodes: list[GraphNode]) -> RunGraphRequest:
    return RunGraphRequest(
        task_id="task-execution-graph",
        run_id="run-execution-graph",
        project_path="D:\\Project\\demo.alita",
        attachments=[],
        graph=RunGraph(
            graphId="graph-execution",
            nodes=nodes,
            edges=[
                GraphEdge(
                    id=f"{source.nodeId}-{target.nodeId}",
                    source=source.nodeId,
                    target=target.nodeId,
                )
                for source in nodes
                for target in nodes
                if source.nodeId in target.dependencies
            ],
            metadata={
                "kind": "task",
                "plannerChain": {"strategy": "legacy_task_planner"},
            },
        ),
    )


def test_compile_execution_graph_maps_tool_and_model_bindings() -> None:
    request = _request(
        [
            _node(
                "inspect",
                "fixed_tool",
                tool_ref="internal:document.markitdown_convert",
                permissions=["read_attachment"],
            ),
            _node(
                "reason",
                "model",
                dependencies=["inspect"],
                model_ref="local-task-reasoner",
            ),
            _node("output", "output", dependencies=["reason"]),
        ]
    )

    graph = compile_execution_graph(request)

    assert graph.graph_id == "graph-execution"
    assert graph.task_id == "task-execution-graph"
    assert graph.metadata["plannerChain"]["strategy"] == "legacy_task_planner"
    inspect = graph.node_by_id("inspect")
    reason = graph.node_by_id("reason")
    output = graph.node_by_id("output")
    assert inspect.tool_binding is not None
    assert inspect.tool_binding.tool_id == "document.markitdown_convert"
    assert inspect.permissions_required == ["read_attachment"]
    assert reason.model_binding is not None
    assert reason.model_binding.model_ref == "local-task-reasoner"
    assert reason.dependencies == ["inspect"]
    assert output.tool_binding is None
    assert output.model_binding is None


def test_validate_execution_graph_rejects_fixed_tool_without_binding() -> None:
    graph = compile_execution_graph(_request([_node("broken-tool", "fixed_tool")]))

    with pytest.raises(
        ExecutionGraphError,
        match="fixed_tool node broken-tool has no tool binding",
    ):
        validate_execution_graph_bindings(graph)


def test_validate_execution_graph_rejects_model_without_binding() -> None:
    graph = compile_execution_graph(_request([_node("broken-model", "model")]))

    with pytest.raises(
        ExecutionGraphError,
        match="model node broken-model has no model binding",
    ):
        validate_execution_graph_bindings(graph)


def test_execution_graph_node_by_id_reports_missing_node() -> None:
    graph = compile_execution_graph(_request([_node("output", "output")]))

    with pytest.raises(ExecutionGraphError, match="execution node not found: missing"):
        graph.node_by_id("missing")
