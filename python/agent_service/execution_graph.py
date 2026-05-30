from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_service.harness_errors import HarnessError
from agent_service.schemas import GraphNode, RunGraphRequest
from agent_service.tool_protocol import provider_tool_id


class ExecutionGraphError(HarnessError):
    pass


class ExecutionToolBinding(BaseModel):
    tool_id: str
    operation: str | None = None
    arguments_template: dict[str, str] = Field(default_factory=dict)


class ExecutionModelBinding(BaseModel):
    model_ref: str
    policy_ref: str | None = None


class ExecutionNode(BaseModel):
    node_id: str
    node_type: str
    public_node: GraphNode
    dependencies: list[str] = Field(default_factory=list)
    tool_binding: ExecutionToolBinding | None = None
    model_binding: ExecutionModelBinding | None = None
    permissions_required: list[str] = Field(default_factory=list)


class ExecutionGraph(BaseModel):
    graph_id: str
    task_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    nodes: list[ExecutionNode]
    nodes_by_id: dict[str, ExecutionNode]

    def node_by_id(self, node_id: str) -> ExecutionNode:
        try:
            return self.nodes_by_id[node_id]
        except KeyError as error:
            raise ExecutionGraphError(
                "missing_execution_node",
                f"execution node not found: {node_id}",
            ) from error


def compile_execution_graph(request: RunGraphRequest) -> ExecutionGraph:
    nodes = [_compile_execution_node(node) for node in request.graph.nodes]
    return ExecutionGraph(
        graph_id=request.graph.graphId,
        task_id=request.task_id,
        metadata=dict(request.graph.metadata),
        nodes=nodes,
        nodes_by_id={node.node_id: node for node in nodes},
    )


def validate_execution_graph_bindings(execution_graph: ExecutionGraph) -> None:
    for node in execution_graph.nodes:
        if node.node_type == "fixed_tool" and node.tool_binding is None:
            raise ExecutionGraphError(
                "unsupported_binding",
                f"fixed_tool node {node.node_id} has no tool binding",
            )
        if node.node_type == "model" and node.model_binding is None:
            raise ExecutionGraphError(
                "unsupported_binding",
                f"model node {node.node_id} has no model binding",
            )


def _compile_execution_node(node: GraphNode) -> ExecutionNode:
    tool_binding = (
        ExecutionToolBinding(tool_id=provider_tool_id(node.toolRef))
        if node.nodeType == "fixed_tool" and node.toolRef
        else None
    )
    model_binding = (
        ExecutionModelBinding(model_ref=node.modelRef)
        if node.nodeType == "model" and node.modelRef
        else None
    )
    return ExecutionNode(
        node_id=node.nodeId,
        node_type=node.nodeType,
        public_node=node,
        dependencies=list(node.dependencies),
        tool_binding=tool_binding,
        model_binding=model_binding,
        permissions_required=list(node.permissionsRequired),
    )
