from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_service.harness_errors import HarnessError
from agent_service.schemas import GraphNode, RunGraphRequest
from agent_service.tool_execution import default_tool_packages_root
from agent_service.tool_protocol import provider_id_for_tool_id, provider_tool_id
from agent_service.tool_registry import ToolManifestSpec, ToolRegistry


class ExecutionGraphError(HarnessError):
    pass


class ExecutionArgumentTemplate(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class ExecutionInputMapping(BaseModel):
    source: str
    source_key: str
    target_argument: str
    required: bool = True


class ExpectedArtifact(BaseModel):
    name: str
    path_template: str
    mime_type: str | None = None
    source_argument: str | None = None


class ExecutionPermissionScope(BaseModel):
    permissions: list[str] = Field(default_factory=list)
    filesystem: str | None = None
    network: bool = False
    sandbox: bool = False
    timeout_ms: int | None = None


class ExecutionToolBinding(BaseModel):
    tool_id: str
    provider_id: str = "internal"
    operation: str | None = None
    arguments_template: ExecutionArgumentTemplate = Field(
        default_factory=ExecutionArgumentTemplate
    )
    input_mappings: list[ExecutionInputMapping] = Field(default_factory=list)
    output_schema: dict[str, Any] | None = None
    expected_artifacts: list[ExpectedArtifact] = Field(default_factory=list)
    permission_scope: ExecutionPermissionScope = Field(
        default_factory=ExecutionPermissionScope
    )


class ExecutionModelBinding(BaseModel):
    model_ref: str
    policy_ref: str | None = None


class ExecutionNode(BaseModel):
    node_id: str
    node_type: str
    public_node: GraphNode
    dependencies: list[str] = Field(default_factory=list)
    tool_binding: ExecutionToolBinding | None = None
    model_binding: ExecutionModelBinding | None = None
    permissions_required: list[str] = Field(default_factory=list)


class ExecutionGraph(BaseModel):
    graph_id: str
    task_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    nodes: list[ExecutionNode]
    nodes_by_id: dict[str, ExecutionNode]

    def node_by_id(self, node_id: str) -> ExecutionNode:
        try:
            return self.nodes_by_id[node_id]
        except KeyError as error:
            raise ExecutionGraphError(
                "missing_execution_node",
                f"execution node not found: {node_id}",
            ) from error


def compile_execution_graph(
    request: RunGraphRequest,
    *,
    tool_registry: ToolRegistry | None = None,
) -> ExecutionGraph:
    _validate_graph_shape(request.graph.nodes)
    registry = tool_registry or ToolRegistry.from_packages_root(default_tool_packages_root())
    nodes = [
        _compile_execution_node(node, tool_registry=registry)
        for node in request.graph.nodes
    ]
    return ExecutionGraph(
        graph_id=request.graph.graphId,
        task_id=request.task_id,
        metadata=dict(request.graph.metadata),
        nodes=nodes,
        nodes_by_id={node.node_id: node for node in nodes},
    )


def validate_execution_graph_bindings(execution_graph: ExecutionGraph) -> None:
    for node in execution_graph.nodes:
        if node.node_type == "fixed_tool" and node.tool_binding is None:
            raise ExecutionGraphError(
                "unsupported_binding",
                f"fixed_tool node {node.node_id} has no tool binding",
            )
        if (
            node.node_type == "fixed_tool"
            and node.tool_binding is not None
            and node.tool_binding.operation is None
        ):
            raise ExecutionGraphError(
                "unsupported_binding",
                (
                    f"fixed_tool node {node.node_id} references unsupported "
                    f"tool binding: {node.tool_binding.tool_id}"
                ),
            )
        if node.node_type == "model" and node.model_binding is None:
            raise ExecutionGraphError(
                "unsupported_binding",
                f"model node {node.node_id} has no model binding",
            )


def _compile_execution_node(
    node: GraphNode,
    *,
    tool_registry: ToolRegistry,
) -> ExecutionNode:
    tool_binding = (
        _compile_tool_binding(node, tool_registry=tool_registry)
        if node.nodeType == "fixed_tool" and node.toolRef
        else None
    )
    model_binding = (
        ExecutionModelBinding(model_ref=node.modelRef)
        if node.nodeType == "model" and node.modelRef
        else None
    )
    return ExecutionNode(
        node_id=node.nodeId,
        node_type=node.nodeType,
        public_node=node,
        dependencies=list(node.dependencies),
        tool_binding=tool_binding,
        model_binding=model_binding,
        permissions_required=list(node.permissionsRequired),
    )


def _validate_graph_shape(nodes: list[GraphNode]) -> None:
    known_ids: set[str] = set()
    for node in nodes:
        if node.nodeId in known_ids:
            raise ExecutionGraphError(
                "invalid_execution_graph",
                f"duplicate execution node id: {node.nodeId}",
            )
        known_ids.add(node.nodeId)

    for node in nodes:
        for dependency in node.dependencies:
            if dependency not in known_ids:
                raise ExecutionGraphError(
                    "invalid_execution_graph",
                    f"node {node.nodeId} depends on missing node: {dependency}",
                )


def _compile_tool_binding(
    node: GraphNode,
    *,
    tool_registry: ToolRegistry,
) -> ExecutionToolBinding:
    assert node.toolRef is not None
    tool_id = provider_tool_id(node.toolRef)
    provider_id = provider_id_for_tool_id(node.toolRef)
    try:
        manifest = tool_registry.get(tool_id)
    except KeyError:
        return _apply_explicit_tool_binding(
            ExecutionToolBinding(
                tool_id=tool_id,
                provider_id=provider_id,
                permission_scope=ExecutionPermissionScope(
                    permissions=list(node.permissionsRequired)
                ),
            ),
            node,
        )

    operation = _operation_for_manifest(tool_id, manifest)
    return _apply_explicit_tool_binding(
        ExecutionToolBinding(
            tool_id=tool_id,
            provider_id=provider_id,
            operation=operation,
            arguments_template=_argument_template_for_tool(tool_id, manifest, operation),
            input_mappings=_input_mappings_for_tool(tool_id),
            output_schema=dict(manifest.output_schema) if manifest.output_schema else None,
            expected_artifacts=_expected_artifacts_for_tool(tool_id),
            permission_scope=_permission_scope_for_tool(node, manifest),
        ),
        node,
    )


def _apply_explicit_tool_binding(
    binding: ExecutionToolBinding,
    node: GraphNode,
) -> ExecutionToolBinding:
    explicit = node.toolBinding
    if explicit is None:
        return binding

    updates: dict[str, Any] = {}
    if explicit.toolId:
        updates["tool_id"] = provider_tool_id(explicit.toolId)
    if explicit.providerId:
        updates["provider_id"] = explicit.providerId
    elif explicit.toolId:
        updates["provider_id"] = provider_id_for_tool_id(explicit.toolId)
    if explicit.operation:
        updates["operation"] = explicit.operation
    if explicit.argumentsTemplate is not None:
        updates["arguments_template"] = ExecutionArgumentTemplate(
            values=dict(explicit.argumentsTemplate.values),
            required=list(explicit.argumentsTemplate.required),
        )
    if explicit.inputMappings:
        updates["input_mappings"] = [
            ExecutionInputMapping(
                source=mapping.source,
                source_key=mapping.sourceKey,
                target_argument=mapping.targetArgument,
                required=mapping.required,
            )
            for mapping in explicit.inputMappings
        ]
    if explicit.outputSchema is not None:
        updates["output_schema"] = dict(explicit.outputSchema)
    if explicit.expectedArtifacts:
        updates["expected_artifacts"] = [
            ExpectedArtifact(
                name=artifact.name,
                path_template=artifact.pathTemplate,
                mime_type=artifact.mimeType,
                source_argument=artifact.sourceArgument,
            )
            for artifact in explicit.expectedArtifacts
        ]
    if explicit.permissionScope is not None:
        updates["permission_scope"] = ExecutionPermissionScope(
            permissions=list(explicit.permissionScope.permissions),
            filesystem=explicit.permissionScope.filesystem,
            network=explicit.permissionScope.network,
            sandbox=explicit.permissionScope.sandbox,
            timeout_ms=explicit.permissionScope.timeoutMs,
        )
    return binding.model_copy(update=updates)


def _operation_for_manifest(
    tool_id: str,
    manifest: ToolManifestSpec,
) -> str | None:
    if len(manifest.operations) == 1:
        return manifest.operations[0].name

    operation_values = (
        manifest.input_schema.get("properties", {})
        .get("operation", {})
        .get("enum", [])
    )
    if len(operation_values) == 1:
        return str(operation_values[0])

    return _DEFAULT_OPERATION_BY_TOOL.get(tool_id)


def _argument_template_for_tool(
    tool_id: str,
    manifest: ToolManifestSpec,
    operation: str | None,
) -> ExecutionArgumentTemplate:
    if tool_id in _DOCUMENT_ARGUMENT_TEMPLATES:
        return ExecutionArgumentTemplate(
            values=dict(_DOCUMENT_ARGUMENT_TEMPLATES[tool_id]),
            required=_schema_required_arguments(manifest.input_schema),
        )

    values: dict[str, Any] = {}
    if operation is not None:
        values["operation"] = operation
    for argument_name in _schema_required_arguments(manifest.input_schema):
        if argument_name == "operation":
            continue
        values[argument_name] = f"{{{argument_name}}}"
    return ExecutionArgumentTemplate(
        values=values,
        required=_schema_required_arguments(manifest.input_schema),
    )


def _input_mappings_for_tool(tool_id: str) -> list[ExecutionInputMapping]:
    return [
        ExecutionInputMapping(**mapping)
        for mapping in _DOCUMENT_INPUT_MAPPINGS.get(tool_id, [])
    ]


def _expected_artifacts_for_tool(tool_id: str) -> list[ExpectedArtifact]:
    return [
        ExpectedArtifact(**artifact)
        for artifact in _DOCUMENT_EXPECTED_ARTIFACTS.get(tool_id, [])
    ]


def _permission_scope_for_tool(
    node: GraphNode,
    manifest: ToolManifestSpec,
) -> ExecutionPermissionScope:
    timeout_seconds = manifest.timeout_policy.get("seconds")
    timeout_ms = int(timeout_seconds * 1000) if timeout_seconds is not None else None
    security_policy = manifest.security_policy
    return ExecutionPermissionScope(
        permissions=_dedupe(
            [*node.permissionsRequired, *manifest.permissions]
        ),
        filesystem=str(security_policy.get("allowedInput") or security_policy.get("allowedOutput") or ""),
        network=security_policy.get("network") is True,
        sandbox=security_policy.get("plugins") is True,
        timeout_ms=timeout_ms,
    )


def _schema_required_arguments(schema: dict[str, Any]) -> list[str]:
    return [str(argument) for argument in schema.get("required", [])]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


_DEFAULT_OPERATION_BY_TOOL = {
    "document.receive_attachment": "receive_attachment",
    "document.markitdown_convert": "convert_local_file",
    "document.typst_compile": "compile_report_pdf",
}


_DOCUMENT_ARGUMENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "document.receive_attachment": {
        "operation": "receive_attachment",
        "paths": "{attachments.paths}",
    },
    "document.markitdown_convert": {
        "operation": "convert_local_file",
        "input_path": "{attachment.path}",
        "output_path": "{artifact_dir}/converted/{index:02d}-{attachment_stem}.md",
    },
    "document.typst_compile": {
        "operation": "compile_report_pdf",
        "title": "{project.name}",
        "outline": "{content-organize.outline}",
        "report": "{report-generate.report}",
        "source_output_path": "{artifact_dir}/typst/{output_stem}.typ",
        "pdf_output_path": "{artifact_dir}/typst/{output_stem}.pdf",
    },
}


_DOCUMENT_INPUT_MAPPINGS: dict[str, list[dict[str, Any]]] = {
    "document.receive_attachment": [
        {
            "source": "attachments",
            "source_key": "paths",
            "target_argument": "paths",
            "required": True,
        }
    ],
    "document.markitdown_convert": [
        {
            "source": "attachments",
            "source_key": "path",
            "target_argument": "input_path",
            "required": True,
        }
    ],
    "document.typst_compile": [
        {
            "source": "content-organize",
            "source_key": "outline",
            "target_argument": "outline",
            "required": True,
        },
        {
            "source": "report-generate",
            "source_key": "report",
            "target_argument": "report",
            "required": True,
        },
    ],
}


_DOCUMENT_EXPECTED_ARTIFACTS: dict[str, list[dict[str, Any]]] = {
    "document.markitdown_convert": [
        {
            "name": "markdown",
            "path_template": "artifacts/converted/{index:02d}-{attachment_stem}.md",
            "mime_type": "text/markdown",
            "source_argument": "output_path",
        }
    ],
    "document.typst_compile": [
        {
            "name": "typst_source",
            "path_template": "artifacts/typst/{output_stem}.typ",
            "mime_type": "text/plain",
            "source_argument": "source_output_path",
        },
        {
            "name": "pdf",
            "path_template": "artifacts/typst/{output_stem}.pdf",
            "mime_type": "application/pdf",
            "source_argument": "pdf_output_path",
        },
    ],
}
