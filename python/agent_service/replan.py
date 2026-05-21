from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent_service.harness_errors import HarnessError
from agent_service.schemas import GraphNode, RunGraphRequest


GraphPatchOpName = Literal[
    "retry_node",
    "rerun_node",
    "rerun_from_node",
    "request_tool_enablement",
]


class GraphPatchOperation(BaseModel):
    op: GraphPatchOpName
    node_id: str
    reason: str


class ReplanSuggestion(BaseModel):
    reason: str
    operations: list[GraphPatchOperation] = Field(default_factory=list)
    requires_user_approval: bool = False


class FailureReplanner:
    def propose(
        self,
        *,
        request: RunGraphRequest,
        failed_node: GraphNode | None,
        error: Exception,
    ) -> ReplanSuggestion | None:
        if failed_node is None:
            return None

        code = error.code if isinstance(error, HarnessError) else "execution_failed"
        reason = str(error)

        if code == "empty_node_output":
            return _suggestion(reason, "retry_node", failed_node.nodeId)

        if code == "missing_artifact":
            return _suggestion(reason, "rerun_node", failed_node.nodeId)

        if code == "missing_dependency_output":
            return _suggestion(reason, "rerun_from_node", failed_node.nodeId)

        if code in {"tool_disabled", "unsupported_tool"}:
            return ReplanSuggestion(
                reason=reason,
                operations=[
                    GraphPatchOperation(
                        op="request_tool_enablement",
                        node_id=failed_node.nodeId,
                        reason=reason,
                    )
                ],
                requires_user_approval=True,
            )

        return None


def _suggestion(
    reason: str,
    op: GraphPatchOpName,
    node_id: str,
) -> ReplanSuggestion:
    return ReplanSuggestion(
        reason=reason,
        operations=[
            GraphPatchOperation(
                op=op,
                node_id=node_id,
                reason=reason,
            )
        ],
    )
