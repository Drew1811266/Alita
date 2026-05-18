from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    attachment_id: str
    name: str
    path: str
    size_bytes: int
    mime_type: str


class UserMessage(BaseModel):
    task_id: str
    content: str
    attachments: list[Attachment] = Field(default_factory=list)


class AgentMessageRequest(UserMessage):
    inquiry_choice: Literal["quick_answer", "research_flow"] | None = None

    def to_user_message(self) -> UserMessage:
        return UserMessage(
            task_id=self.task_id,
            content=self.content,
            attachments=list(self.attachments),
        )


class AgentEvent(BaseModel):
    type: str
    payload: dict


class RunAttachment(Attachment):
    pass


class ScriptReviewState(BaseModel):
    status: Literal["not_reviewed", "reviewing", "approved", "rejected"] = "not_reviewed"
    summary: str
    permissions: list[str] = Field(default_factory=list)
    riskLevel: Literal["low", "medium", "high"] = "low"
    requiresApproval: bool = False
    codePreview: str | None = None
    inputContract: dict[str, Any] = Field(default_factory=dict)
    outputContract: dict[str, Any] = Field(default_factory=dict)
    approvalFingerprint: str | None = None


class NodeEstimate(BaseModel):
    durationMs: int | None = None
    cpu: str | None = None
    memory: str | None = None
    network: str | None = None


class RuntimeNotice(BaseModel):
    kind: str
    message: str
    actualDurationMs: int | None = None


class GraphNode(BaseModel):
    nodeId: str
    nodeType: Literal[
        "fixed_tool",
        "model",
        "output",
        "temporary_placeholder",
        "planning",
        "temporary_script",
    ]
    displayName: str
    status: Literal[
        "waiting",
        "ready",
        "running",
        "completed",
        "failed",
        "needs_user_input",
        "needs_permission",
        "skipped",
    ]
    inputPorts: list[dict[str, Any]] = Field(default_factory=list)
    outputPorts: list[dict[str, Any]] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    toolRef: str | None = None
    modelRef: str | None = None
    summary: str
    createdBy: str
    artifactRefs: list[str] = Field(default_factory=list)
    retryCount: int = 0
    scriptReview: ScriptReviewState | None = None
    estimate: NodeEstimate | None = None
    resourceUsage: dict[str, Any] | None = None
    runtimeNotice: RuntimeNotice | None = None
    position: dict[str, float]


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str


class RunGraph(BaseModel):
    graphId: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunMode(BaseModel):
    type: Literal["full", "failed_only", "from_node"] = "full"
    source_run_id: str | None = None
    node_id: str | None = None


class CancelRunRequest(BaseModel):
    run_id: str


class RunGraphRequest(BaseModel):
    task_id: str
    project_path: str
    graph: RunGraph
    attachments: list[RunAttachment] = Field(default_factory=list)
    run_id: str = Field(default_factory=lambda: f"run-{uuid4()}")
    mode: RunMode = Field(default_factory=RunMode)
    disabled_tool_ids: list[str] = Field(default_factory=list)
