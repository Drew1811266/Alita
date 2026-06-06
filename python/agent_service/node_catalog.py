from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_service.tool_registry import ToolManifestSpec, ToolRegistry


NodeKind = Literal["tool", "model", "human", "verifier", "output"]
NodeCategory = Literal[
    "document",
    "web",
    "data",
    "reasoning",
    "human",
    "verification",
    "output",
]
NodeSource = Literal["internal_tool", "system", "mcp", "plugin"]
AvailabilityStatus = Literal["available", "degraded", "unavailable"]
RiskLevel = Literal["low", "medium", "high"]


class NodeCatalogModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class NodeAvailability(NodeCatalogModel):
    status: AvailabilityStatus = "available"
    reason_code: str | None = None
    message: str | None = None


class NodePortDefinition(NodeCatalogModel):
    id: str
    label: str
    data_type: Literal[
        "text",
        "markdown",
        "document",
        "table",
        "json",
        "artifact",
        "url",
        "query",
        "decision",
    ]
    required: bool = True
    multiple: bool = False
    description: str = ""


class NodeExecutionBinding(NodeCatalogModel):
    type: Literal["tool", "model", "human", "verifier", "output"]
    tool_id: str | None = None
    operation: str | None = None
    model_policy: Literal[
        "deep_reasoning",
        "node_reasoning",
        "fast_chat",
        "fast_factual",
    ] | None = None
    verifier_type: Literal[
        "artifact_exists",
        "citation_check",
        "schema_check",
        "coverage_check",
    ] | None = None
    output_type: Literal[
        "markdown",
        "docx",
        "pdf",
        "table",
        "checklist",
        "final_response",
    ] | None = None


class NodePermissionProfile(NodeCatalogModel):
    permissions: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "low"
    requires_approval: bool = False
    filesystem: Literal["none", "project_read", "project_write"] = "none"
    network: Literal["none", "external"] = "none"
    sandbox: Literal["none", "sidecar", "external"] = "none"


class NodeExample(NodeCatalogModel):
    title: str
    input: dict[str, Any] = Field(default_factory=dict)


class NodeDefinition(NodeCatalogModel):
    node_id: str
    kind: NodeKind
    display_name: str
    description: str
    category: NodeCategory
    capabilities: list[str] = Field(default_factory=list)
    input_ports: list[NodePortDefinition] = Field(default_factory=list)
    output_ports: list[NodePortDefinition] = Field(default_factory=list)
    execution: NodeExecutionBinding
    permissions: NodePermissionProfile = Field(default_factory=NodePermissionProfile)
    examples: list[NodeExample] = Field(default_factory=list)
    source: NodeSource
    version: str = "1.0.0"
    availability: NodeAvailability = Field(default_factory=NodeAvailability)


class NodeCatalogDiagnostic(NodeCatalogModel):
    code: str
    message: str
    node_id: str | None = None


class NodeCatalogSourceSummary(NodeCatalogModel):
    internal_tool_count: int = 0
    system_node_count: int = 0
    mcp_node_count: int = 0
    plugin_node_count: int = 0


class NodeCatalogSnapshot(NodeCatalogModel):
    schema_version: int = 1
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    nodes: list[NodeDefinition] = Field(default_factory=list)
    diagnostics: list[NodeCatalogDiagnostic] = Field(default_factory=list)
    source_summary: NodeCatalogSourceSummary = Field(
        default_factory=NodeCatalogSourceSummary,
    )

    def node_by_id(self, node_id: str) -> NodeDefinition:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(f"unknown catalog node: {node_id}")

    def available_capabilities(self) -> set[str]:
        capabilities: set[str] = set()
        for node in self.nodes:
            if node.availability.status != "available":
                continue
            capabilities.add(node.node_id)
            capabilities.update(node.capabilities)
        return capabilities


class NodeCatalogBuilder:
    def __init__(self, *, tool_registry: ToolRegistry) -> None:
        self.tool_registry = tool_registry

    def build(
        self,
        *,
        additional_system_nodes: list[NodeDefinition] | None = None,
    ) -> NodeCatalogSnapshot:
        candidate_nodes = [
            node
            for tool in self.tool_registry.enabled_tools()
            for node in _nodes_from_tool_manifest(tool)
        ]
        candidate_nodes.extend(_system_nodes())
        candidate_nodes.extend(additional_system_nodes or [])

        nodes, diagnostics = _deduplicate_nodes(candidate_nodes)

        return NodeCatalogSnapshot(
            nodes=nodes,
            diagnostics=diagnostics,
            source_summary=NodeCatalogSourceSummary(
                internal_tool_count=sum(
                    1 for node in nodes if node.source == "internal_tool"
                ),
                system_node_count=sum(1 for node in nodes if node.source == "system"),
            ),
        )


def _nodes_from_tool_manifest(tool: ToolManifestSpec) -> list[NodeDefinition]:
    if tool.tool_id != "document.markitdown_convert":
        return []

    return [
        NodeDefinition(
            node_id="document.convert.markdown",
            kind="tool",
            display_name=tool.name,
            description=tool.description,
            category="document",
            capabilities=["document.convert.markdown"],
            input_ports=[
                NodePortDefinition(
                    id="document-input",
                    label="Document",
                    data_type="document",
                    description="Project or attachment document to convert.",
                )
            ],
            output_ports=[
                NodePortDefinition(
                    id="markdown-output",
                    label="Markdown",
                    data_type="markdown",
                    description="Converted Markdown text or artifact.",
                )
            ],
            execution=NodeExecutionBinding(
                type="tool",
                tool_id=tool.tool_id,
                operation="convert_local_file",
            ),
            permissions=_permissions_from_tool(tool),
            examples=_examples_from_tool(tool),
            source="internal_tool",
            version=tool.version,
        )
    ]


def _system_nodes() -> list[NodeDefinition]:
    return [
        _model_node(
            node_id="document.summarize",
            display_name="Summarize Document",
            description="Summarize document content into concise Markdown.",
            category="document",
            capabilities=["document.summarize"],
            input_ports=[
                NodePortDefinition(
                    id="document-input",
                    label="Document",
                    data_type="document",
                )
            ],
            output_ports=[
                NodePortDefinition(
                    id="summary-output",
                    label="Summary",
                    data_type="markdown",
                )
            ],
        ),
        _model_node(
            node_id="research.synthesize",
            display_name="Synthesize Research",
            description="Synthesize collected evidence into a reasoned answer.",
            category="reasoning",
            capabilities=["research.synthesize"],
            input_ports=[
                NodePortDefinition(
                    id="evidence-input",
                    label="Evidence",
                    data_type="json",
                    multiple=True,
                )
            ],
            output_ports=[
                NodePortDefinition(
                    id="synthesis-output",
                    label="Synthesis",
                    data_type="markdown",
                )
            ],
        ),
        NodeDefinition(
            node_id="human.clarify",
            kind="human",
            display_name="Clarify With User",
            description="Ask the user for missing information needed to continue.",
            category="human",
            capabilities=["human.clarify"],
            input_ports=[
                NodePortDefinition(
                    id="question-input",
                    label="Question",
                    data_type="text",
                )
            ],
            output_ports=[
                NodePortDefinition(
                    id="answer-output",
                    label="Answer",
                    data_type="text",
                )
            ],
            execution=NodeExecutionBinding(type="human"),
            permissions=NodePermissionProfile(),
            examples=[],
            source="system",
        ),
        NodeDefinition(
            node_id="verify.artifact_exists",
            kind="verifier",
            display_name="Verify Artifact Exists",
            description="Verify that an expected artifact was created.",
            category="verification",
            capabilities=["verify.artifact_exists"],
            input_ports=[
                NodePortDefinition(
                    id="artifact-input",
                    label="Artifact",
                    data_type="artifact",
                )
            ],
            output_ports=[
                NodePortDefinition(
                    id="decision-output",
                    label="Decision",
                    data_type="decision",
                )
            ],
            execution=NodeExecutionBinding(
                type="verifier",
                verifier_type="artifact_exists",
            ),
            permissions=NodePermissionProfile(),
            examples=[],
            source="system",
        ),
        NodeDefinition(
            node_id="output.final_response",
            kind="output",
            display_name="Final Response",
            description="Return the final response to the user.",
            category="output",
            capabilities=["output.final_response"],
            input_ports=[
                NodePortDefinition(
                    id="response-input",
                    label="Response",
                    data_type="markdown",
                )
            ],
            output_ports=[],
            execution=NodeExecutionBinding(
                type="output",
                output_type="final_response",
            ),
            permissions=NodePermissionProfile(),
            examples=[],
            source="system",
        ),
    ]


def _model_node(
    *,
    node_id: str,
    display_name: str,
    description: str,
    category: NodeCategory,
    capabilities: list[str],
    input_ports: list[NodePortDefinition],
    output_ports: list[NodePortDefinition],
) -> NodeDefinition:
    return NodeDefinition(
        node_id=node_id,
        kind="model",
        display_name=display_name,
        description=description,
        category=category,
        capabilities=capabilities,
        input_ports=input_ports,
        output_ports=output_ports,
        execution=NodeExecutionBinding(
            type="model",
            model_policy="node_reasoning",
        ),
        permissions=NodePermissionProfile(),
        examples=[],
        source="system",
    )


def _examples_from_tool(tool: ToolManifestSpec) -> list[NodeExample]:
    examples: list[NodeExample] = []
    for example in tool.examples:
        title = str(example.get("title", "")).strip()
        if not title:
            continue
        input_value = example.get("input", {})
        examples.append(
            NodeExample(
                title=title,
                input=dict(input_value) if isinstance(input_value, dict) else {},
            )
        )
    return examples


def _permissions_from_tool(tool: ToolManifestSpec) -> NodePermissionProfile:
    permissions = list(tool.permissions)
    high_risk_permissions = {
        "run_local_cli",
        "run_python_plugin",
        "call_external_mcp_tool",
    }
    medium_risk_permissions = {
        "read_project_files",
        "write_project_outputs",
        "network",
    }

    if any(permission in high_risk_permissions for permission in permissions):
        risk_level: RiskLevel = "high"
    elif any(permission in medium_risk_permissions for permission in permissions):
        risk_level = "medium"
    else:
        risk_level = "low"

    filesystem: Literal["none", "project_read", "project_write"] = "none"
    if "write_project_outputs" in permissions:
        filesystem = "project_write"
    elif "read_project_files" in permissions:
        filesystem = "project_read"

    network = "external" if "network" in permissions else "none"
    if tool.security_policy.get("network") is True:
        network = "external"

    sandbox: Literal["none", "sidecar", "external"] = "none"
    if "call_external_mcp_tool" in permissions:
        sandbox = "external"
    elif {"run_local_cli", "run_python_plugin"} & set(permissions):
        sandbox = "sidecar"

    return NodePermissionProfile(
        permissions=permissions,
        risk_level=risk_level,
        requires_approval=risk_level == "high",
        filesystem=filesystem,
        network=network,
        sandbox=sandbox,
    )


def _deduplicate_nodes(
    nodes: list[NodeDefinition],
) -> tuple[list[NodeDefinition], list[NodeCatalogDiagnostic]]:
    seen: set[str] = set()
    deduplicated: list[NodeDefinition] = []
    diagnostics: list[NodeCatalogDiagnostic] = []

    for node in nodes:
        if node.node_id in seen:
            diagnostics.append(
                NodeCatalogDiagnostic(
                    code="duplicate_node_id",
                    node_id=node.node_id,
                    message=f"Skipped duplicate catalog node '{node.node_id}'.",
                )
            )
            continue
        seen.add(node.node_id)
        deduplicated.append(node)

    return deduplicated, diagnostics
