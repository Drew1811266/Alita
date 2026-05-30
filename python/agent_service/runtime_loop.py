from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_service.node_output import NodeOutput


class RuntimeCheckpoint(BaseModel):
    run_id: str
    node_id: str
    status: str
    completed_outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    pending_node_ids: list[str] = Field(default_factory=list)
    created_at: str
    recovery_count: int = 0

    def to_record(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "nodeId": self.node_id,
            "status": self.status,
            "completedOutputs": self.completed_outputs,
            "pendingNodeIds": list(self.pending_node_ids),
            "createdAt": self.created_at,
            "recoveryCount": self.recovery_count,
        }


def checkpoint_outputs(outputs: dict[str, NodeOutput]) -> dict[str, dict[str, Any]]:
    return {
        node_id: {
            "values": dict(output.values),
            "artifactRefs": list(output.artifacts),
        }
        for node_id, output in outputs.items()
    }
