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
    thread_id: str | None = None
    sequence: int | None = None
    parent_checkpoint_id: str | None = None
    graph_hash: str | None = None
    state_version: int = 1
    writes: list[dict[str, Any]] = Field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = Field(default_factory=list)
    runtime_state: dict[str, Any] = Field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "checkpointId": f"{self.node_id}:{self.status}:{self.recovery_count}",
            "threadId": self.thread_id,
            "runId": self.run_id,
            "nodeId": self.node_id,
            "status": self.status,
            "sequence": self.sequence,
            "parentCheckpointId": self.parent_checkpoint_id,
            "graphHash": self.graph_hash,
            "stateVersion": self.state_version,
            "completedOutputs": self.completed_outputs,
            "pendingNodeIds": list(self.pending_node_ids),
            "writes": list(self.writes),
            "pendingApprovals": list(self.pending_approvals),
            "runtimeState": dict(self.runtime_state),
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


def outputs_from_checkpoint_record(record: dict[str, Any]) -> dict[str, NodeOutput]:
    restored: dict[str, NodeOutput] = {}
    for node_id, payload in dict(record.get("completedOutputs") or {}).items():
        restored[str(node_id)] = NodeOutput(
            values=dict(payload.get("values") or {}),
            artifacts=list(payload.get("artifactRefs") or []),
        )
    return restored


def pending_node_ids_from_checkpoint_record(record: dict[str, Any]) -> list[str]:
    return [str(value) for value in record.get("pendingNodeIds") or []]
