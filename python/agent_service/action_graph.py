from __future__ import annotations

from pydantic import BaseModel, Field

from agent_service.runtime_state import RuntimeAction
from agent_service.schemas import RunGraph


ACTION_GRAPH_VERSION = "runtime_action_graph.v1"


class RuntimeActionGraph(BaseModel):
    graph_id: str
    actions: list[RuntimeAction] = Field(default_factory=list)


def action_graph_from_run_graph(graph: RunGraph) -> RuntimeActionGraph:
    actions: list[RuntimeAction] = []
    for node in graph.nodes:
        if node.nodeType == "fixed_tool":
            action_type = "tool"
            name = node.toolRef or node.nodeId
        elif node.nodeType == "model":
            action_type = "model"
            name = node.modelRef or node.nodeId
        else:
            action_type = "control"
            name = node.nodeId

        actions.append(
            RuntimeAction(
                action_id=node.nodeId,
                action_type=action_type,
                name=name,
                dependencies=list(node.dependencies),
                permissions=[
                    {"permission": permission}
                    for permission in node.permissionsRequired
                ],
            )
        )
    return RuntimeActionGraph(graph_id=graph.graphId, actions=actions)
