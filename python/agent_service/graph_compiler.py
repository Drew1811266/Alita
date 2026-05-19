from __future__ import annotations

from typing import Any

from agent_service.task_graph import TaskGraph, TaskNode


MODEL_REF_MAPPING = {
    "local.content_organizer": "local-content-organizer",
    "local.report_writer": "local-report-writer",
}


def compile_task_graph_to_node_graph(task_graph: TaskGraph) -> dict:
    return {
        "graphId": task_graph.graph_id,
        "nodes": [_compile_node(node) for node in task_graph.nodes],
        "edges": [
            {"id": edge.id, "source": edge.source, "target": edge.target}
            for edge in task_graph.edges
        ],
    }


def _compile_node(node: TaskNode) -> dict[str, Any]:
    if node.ui is None:
        raise ValueError(f"missing UI metadata for task node: {node.node_id}")

    compiled_node: dict[str, Any] = {
        "nodeId": node.node_id,
        "nodeType": _compile_node_type(node),
        "displayName": node.ui.display_name,
        "status": _compile_status(node),
        "inputPorts": list(node.ui.input_ports),
        "outputPorts": list(node.ui.output_ports),
        "dependencies": list(node.dependencies),
        "summary": node.ui.summary,
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "position": dict(node.ui.position),
    }

    if node.tool_binding is not None:
        compiled_node["toolRef"] = node.tool_binding.tool_id
    if node.model_binding is not None:
        compiled_node["modelRef"] = MODEL_REF_MAPPING.get(
            node.model_binding.model_ref,
            node.model_binding.model_ref,
        )

    return compiled_node


def _compile_node_type(node: TaskNode) -> str:
    if node.kind in {"input", "fixed_tool"}:
        return "fixed_tool"
    if node.kind in {"model", "output"}:
        return node.kind
    raise ValueError(f"unsupported task node kind for node {node.node_id}: {node.kind}")


def _compile_status(node: TaskNode) -> str:
    return "completed" if node.kind == "input" else "waiting"
