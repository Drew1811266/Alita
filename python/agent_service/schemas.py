from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agent_service.risk_levels import RiskLevel


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
    model_session_id: str | None = None


class AgentMessageRequest(UserMessage):
    model_config = ConfigDict(populate_by_name=True)

    inquiry_choice: Literal["quick_answer", "research_flow"] | None = None
    currentGraph: "RunGraph | None" = Field(default=None, alias="current_graph")
    hasRunHistory: bool | None = Field(default=None, alias="has_run_history")
    artifactRefs: list[str] | None = Field(default=None, alias="artifact_refs")
    pendingChoice: dict[str, Any] | None = Field(default=None, alias="pending_choice")

    def to_user_message(self) -> UserMessage:
        return UserMessage(
            task_id=self.task_id,
            content=self.content,
            attachments=list(self.attachments),
            model_session_id=self.model_session_id,
        )


class ResearchChoiceRequest(AgentMessageRequest):
    inquiry_choice: Literal["quick_answer", "research_flow"]


class AgentEvent(BaseModel):
    type: str
    payload: dict


class AgentModelConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mode: Literal["local", "api"]
    base_url: str = Field(alias="baseUrl")
    model: str
    provider_id: str | None = Field(default=None, alias="providerId")
    provider_type: str | None = Field(default=None, alias="providerType")
    display_name: str | None = Field(default=None, alias="displayName")
    api_key: str | None = Field(default=None, alias="apiKey")


class RegisterModelSessionRequest(BaseModel):
    model_config_value: AgentModelConfig = Field(alias="modelConfig")


class RegisterModelSessionResponse(BaseModel):
    model_session_id: str = Field(alias="modelSessionId")


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


class GraphArgumentTemplate(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class GraphInputMapping(BaseModel):
    source: str
    sourceKey: str
    targetArgument: str
    required: bool = True


class GraphExpectedArtifact(BaseModel):
    name: str
    pathTemplate: str
    mimeType: str | None = None
    sourceArgument: str | None = None


class GraphPermissionScope(BaseModel):
    permissions: list[str] = Field(default_factory=list)
    filesystem: str | None = None
    network: bool = False
    sandbox: bool = False
    timeoutMs: int | None = None


class GraphToolBinding(BaseModel):
    toolId: str | None = None
    providerId: str | None = None
    operation: str | None = None
    argumentsTemplate: GraphArgumentTemplate | None = None
    inputMappings: list[GraphInputMapping] = Field(default_factory=list)
    outputSchema: dict[str, Any] | None = None
    expectedArtifacts: list[GraphExpectedArtifact] = Field(default_factory=list)
    permissionScope: GraphPermissionScope | None = None


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
    toolBinding: GraphToolBinding | None = None
    modelRef: str | None = None
    summary: str
    createdBy: str
    artifactRefs: list[str] = Field(default_factory=list)
    retryCount: int = 0
    scriptReview: ScriptReviewState | None = None
    estimate: NodeEstimate | None = None
    resourceUsage: dict[str, Any] | None = None
    runtimeNotice: RuntimeNotice | None = None
    lastRun: dict[str, Any] | None = None
    riskLevel: RiskLevel | None = None
    permissionsRequired: list[str] = Field(default_factory=list)
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


class ScriptApprovalRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_id: str
    node_id: str
    currentGraph: RunGraph = Field(alias="current_graph")
    approvalFingerprint: str = Field(alias="approval_fingerprint")


class ScriptRejectionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_id: str
    node_id: str
    currentGraph: RunGraph = Field(alias="current_graph")
    reason: str | None = None


class RunGraphRequest(BaseModel):
    task_id: str
    project_path: str
    graph: RunGraph
    attachments: list[RunAttachment] = Field(default_factory=list)
    run_id: str = Field(default_factory=lambda: f"run-{uuid4()}")
    mode: RunMode = Field(default_factory=RunMode)
    disabled_tool_ids: list[str] = Field(default_factory=list)
    approved_permissions: list[str] = Field(default_factory=list)
    model_session_id: str | None = None
