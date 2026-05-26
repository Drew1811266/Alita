from __future__ import annotations

from pydantic import BaseModel, Field

from agent_service.risk_levels import RiskLevel
from agent_service.schemas import RunGraph


class ExecutionGraphError(ValueError):
    pass


class ExecutionNode(BaseModel):
    node_id: str
    node_type: str
    dependencies: list[str] = Field(default_factory=list)
    tool_id: str | None = None
    model_ref: str | None = None
    verifier_id: str | None = None
    permissions_required: list[str] = Field(default_factory=list)
    risk_level: RiskLevel | None = None


class ExecutionGraph(BaseModel):
    graph_id: str
    nodes: list[ExecutionNode]

    @classmethod
    def from_run_graph(cls, graph: RunGraph) -> "ExecutionGraph":
        node_ids = [node.nodeId for node in graph.nodes]
        duplicate_ids = sorted(
            node_id for node_id in set(node_ids) if node_ids.count(node_id) > 1
        )
        if duplicate_ids:
            raise ExecutionGraphError(f"duplicate node id: {duplicate_ids[0]}")

        known_node_ids = set(node_ids)
        execution_nodes: list[ExecutionNode] = []
        for node in graph.nodes:
            for dependency in node.dependencies:
                if dependency not in known_node_ids:
                    raise ExecutionGraphError(
                        f"missing dependency for {node.nodeId}: {dependency}"
                    )
            execution_nodes.append(
                ExecutionNode(
                    node_id=node.nodeId,
                    node_type=node.nodeType,
                    dependencies=list(node.dependencies),
                    tool_id=node.toolRef,
                    model_ref=node.modelRef,
                    permissions_required=list(node.permissionsRequired),
                    risk_level=node.riskLevel,
                )
            )
        return cls(graph_id=graph.graphId, nodes=execution_nodes)

    def node_by_id(self, node_id: str) -> ExecutionNode:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise ExecutionGraphError(f"node not found: {node_id}")

    def ordered_nodes(self) -> list[ExecutionNode]:
        ordered: list[ExecutionNode] = []
        completed: set[str] = set()
        while len(ordered) < len(self.nodes):
            ready = [
                node
                for node in self.nodes
                if node.node_id not in completed
                and all(dependency in completed for dependency in node.dependencies)
            ]
            if not ready:
                raise ExecutionGraphError("cycle detected or dependency not satisfiable")
            for node in ready:
                ordered.append(node)
                completed.add(node.node_id)
        return ordered
