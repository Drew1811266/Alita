from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field

from agent_service.node_output import NodeOutput


class RuntimeCheckpoint(BaseModel):
    checkpoint_id: str | None = None
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
    state_hash: str | None = None
    state_version: int = 1
    writes: list[dict[str, Any]] = Field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = Field(default_factory=list)
    runtime_state: dict[str, Any] = Field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        checkpoint_label = f"{self.node_id}:{self.status}:{self.recovery_count}"
        state_hash = self.state_hash or _checkpoint_state_hash(self)
        checkpoint_id = self.checkpoint_id
        if checkpoint_id is None:
            checkpoint_id = (
                f"ckpt-{self.run_id}-{self.sequence:06d}-{state_hash[:12]}"
                if self.sequence is not None
                else checkpoint_label
            )
        return {
            "checkpointId": checkpoint_id,
            "checkpointLabel": checkpoint_label,
            "threadId": self.thread_id,
            "runId": self.run_id,
            "nodeId": self.node_id,
            "status": self.status,
            "sequence": self.sequence,
            "parentCheckpointId": self.parent_checkpoint_id,
            "graphHash": self.graph_hash,
            "stateHash": state_hash,
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


def _checkpoint_state_hash(checkpoint: RuntimeCheckpoint) -> str:
    payload = {
        "run_id": checkpoint.run_id,
        "node_id": checkpoint.node_id,
        "status": checkpoint.status,
        "completed_outputs": checkpoint.completed_outputs,
        "pending_node_ids": checkpoint.pending_node_ids,
        "recovery_count": checkpoint.recovery_count,
        "thread_id": checkpoint.thread_id,
        "sequence": checkpoint.sequence,
        "parent_checkpoint_id": checkpoint.parent_checkpoint_id,
        "graph_hash": checkpoint.graph_hash,
        "state_version": checkpoint.state_version,
        "writes": checkpoint.writes,
        "pending_approvals": checkpoint.pending_approvals,
        "runtime_state": checkpoint.runtime_state,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
