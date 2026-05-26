from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


JsonObject = dict[str, Any]
ToolSource = Literal["internal", "mcp"]
FilesystemPolicy = Literal[
    "none", "project_read", "project_write", "external_read", "external_write"
]
NetworkPolicy = Literal["none", "provider_declared", "any"]
ApprovalPolicy = Literal["never", "before_call", "high_risk_only"]
SecretsPolicy = Literal["none", "provider_managed", "user_configured"]
SandboxPolicy = Literal["not_required", "required"]


@dataclass(frozen=True)
class ToolSafetyPolicy:
    filesystem: FilesystemPolicy
    network: NetworkPolicy
    user_approval: ApprovalPolicy
    secrets: SecretsPolicy
    sandbox: SandboxPolicy
    max_runtime_ms: int

    def __post_init__(self) -> None:
        if self.max_runtime_ms <= 0:
            raise ValueError("max runtime must be positive")


@dataclass(frozen=True)
class UnifiedToolDefinition:
    id: str
    source: ToolSource
    provider_id: str
    provider_tool_name: str
    display_name: str
    description: str
    capabilities: list[str]
    input_schema: JsonObject
    output_schema: JsonObject | None
    permissions: list[str]
    safety_policy: ToolSafetyPolicy
    timeout_ms: int
    examples: list[JsonObject] = field(default_factory=list)
    version: str | None = None
    node_template: JsonObject | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("tool id is required")
        if not self.provider_id.strip():
            raise ValueError("provider id is required")
        if not self.provider_tool_name.strip():
            raise ValueError("provider tool name is required")
        if self.timeout_ms <= 0:
            raise ValueError("timeout must be positive")


@dataclass(frozen=True)
class UnifiedToolInvocation:
    invocation_id: str
    run_id: str
    task_id: str
    tool_id: str
    arguments: JsonObject
    allowed_roots: list[str]
    requested_permissions: list[str]
    project_path: str | None = None
    node_id: str | None = None
    approval_token: str | None = None
    model_session_id: str | None = None


@dataclass(frozen=True)
class ToolResultContent:
    type: Literal["text", "json", "artifact", "resource_link"]
    text: str | None = None
    value: Any | None = None
    path: str | None = None
    uri: str | None = None
    title: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class UnifiedToolError:
    code: str
    message: str
    recoverable: bool
    safe_details: JsonObject | None = None


@dataclass(frozen=True)
class UnifiedToolResult:
    ok: bool
    content: list[ToolResultContent]
    structured_content: JsonObject | None
    artifacts: list[str]
    metadata: dict[str, str]
    error: UnifiedToolError | None = None


class ToolProvider(Protocol):
    provider_id: str
    source: ToolSource

    def list_tools(self) -> list[UnifiedToolDefinition]:
        raise NotImplementedError

    def call_tool(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        raise NotImplementedError


def normalize_tool_id(tool_id: str) -> str:
    if tool_id.startswith("internal:") or tool_id.startswith("mcp:"):
        return tool_id
    return f"internal:{tool_id}"


def provider_tool_id(tool_id: str) -> str:
    if tool_id.startswith("internal:"):
        return tool_id.removeprefix("internal:")
    return tool_id


def equivalent_tool_ids(tool_id: str) -> set[str]:
    normalized = normalize_tool_id(tool_id)
    if normalized.startswith("internal:"):
        return {normalized, normalized.removeprefix("internal:")}
    return {normalized}
