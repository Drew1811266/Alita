from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from agent_service.action_graph import RuntimeActionGraph
from agent_service.execution_graph import (
    ExecutionGraph,
    ExecutionGraphError,
    ExecutionNode,
    compile_execution_graph,
    validate_execution_graph_bindings,
)
from agent_service.harness_errors import HarnessError
from agent_service.schemas import GraphEdge, GraphNode, RunGraph, RunGraphRequest
from agent_service.tool_registry import ToolRegistry


PublicNodeType = Literal[
    "fixed_tool",
    "model",
    "output",
    "temporary_placeholder",
    "planning",
    "temporary_script",
]
CompiledGraphStatus = Literal[
    "compiled",
    "reviewed",
    "execution_ready",
    "failed",
]


class AgentPlanCompileError(HarnessError):
    pass


class ExpectedArtifact(BaseModel):
    name: str
    path_template: str
    mime_type: str | None = None
    source_argument: str | None = None


class AgentCompiledToolContract(BaseModel):
    tool_id: str
    provider_id: str
    operation: str
    arguments_template: dict[str, Any] = Field(default_factory=dict)
    input_mappings: list[dict[str, Any]] = Field(default_factory=list)
    output_schema: dict[str, Any] | None = None
    expected_artifacts: list[ExpectedArtifact] = Field(default_factory=list)
    permission_scope: dict[str, Any] = Field(default_factory=dict)


class AgentCompiledModelContract(BaseModel):
    model_ref: str
    policy_ref: str | None = None


class AgentCompiledNode(BaseModel):
    node_id: str
    node_type: PublicNodeType
    display_name: str
    binding_kind: Literal["tool", "model", "output", "control"]
    dependencies: list[str] = Field(default_factory=list)
    source_plan_draft_id: str
    source_plan_step_id: str
    rationale: str | None = None
    expected_output: str
    verification_criteria: list[str]
    required_capabilities: list[str]
    permissions_required: list[str] = Field(default_factory=list)
    expected_artifacts: list[ExpectedArtifact] = Field(default_factory=list)
    tool_contract: AgentCompiledToolContract | None = None
    model_contract: AgentCompiledModelContract | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentCompileIssue(BaseModel):
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    node_id: str | None = None
    edge_id: str | None = None
    dependency_id: str | None = None
    capability: str | None = None


class AgentCompileReview(BaseModel):
    status: Literal["approved", "invalid"]
    is_valid: bool
    unsupported_capabilities: list[str] = Field(default_factory=list)
    missing_bindings: list[str] = Field(default_factory=list)
    execution_ready: bool
    issues: list[AgentCompileIssue] = Field(default_factory=list)


class AgentCompiledGraph(BaseModel):
    status: CompiledGraphStatus = "compiled"
    compile_id: str
    compile_fingerprint: str
    source_graph_id: str
    source_plan_draft_id: str
    planning_trace_id: str | None = None
    task_id: str
    run_id: str
    thread_id: str
    confirmation_id: str
    success_criteria: list[str] = Field(default_factory=list)
    verification_plan: list[str] = Field(default_factory=list)
    nodes: list[AgentCompiledNode]
    edges: list[GraphEdge] = Field(default_factory=list)
    action_graph: RuntimeActionGraph
    execution_graph: ExecutionGraph
    metadata: dict[str, Any] = Field(default_factory=dict)

    def node_by_id(self, node_id: str) -> AgentCompiledNode:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise AgentPlanCompileError(
            "missing_compiled_node",
            f"compiled node not found: {node_id}",
        )


def compile_confirmed_agent_plan_graph(
    graph: RunGraph,
    *,
    task_id: str,
    run_id: str,
    thread_id: str,
    confirmation_id: str,
    tool_registry: ToolRegistry | None = None,
) -> AgentCompiledGraph:
    source_plan_draft_id = _enforce_deep_planning_provenance(graph)
    _preflight_graph_nodes(graph)

    request = RunGraphRequest(
        task_id=task_id,
        project_path="D:/Software Project/Alita",
        graph=graph,
        run_id=run_id,
    )
    try:
        execution_graph = compile_execution_graph(
            request,
            tool_registry=tool_registry,
        )
        validate_execution_graph_bindings(execution_graph)
    except ExecutionGraphError as error:
        raise AgentPlanCompileError(error.code, error.message) from error

    action_graph = _runtime_action_graph_from_execution_metadata(execution_graph)
    compiled_nodes = [
        _compile_node(
            node,
            execution_graph.node_by_id(node.nodeId),
            source_plan_draft_id=source_plan_draft_id,
        )
        for node in graph.nodes
    ]
    fingerprint = _compile_fingerprint(graph)

    return AgentCompiledGraph(
        compile_id=_compile_id(
            graph_id=graph.graphId,
            run_id=run_id,
            confirmation_id=confirmation_id,
            fingerprint=fingerprint,
        ),
        compile_fingerprint=fingerprint,
        source_graph_id=graph.graphId,
        source_plan_draft_id=source_plan_draft_id,
        planning_trace_id=_string_or_none(graph.metadata.get("planningTraceId")),
        task_id=task_id,
        run_id=run_id,
        thread_id=thread_id,
        confirmation_id=confirmation_id,
        success_criteria=_string_list(graph.metadata.get("successCriteria")),
        verification_plan=_string_list(graph.metadata.get("verificationPlan")),
        nodes=compiled_nodes,
        edges=list(graph.edges),
        action_graph=action_graph,
        execution_graph=execution_graph,
        metadata={
            "generatedBy": graph.metadata.get("generatedBy"),
            "modelPolicy": graph.metadata.get("modelPolicy"),
            "sourcePlanDraftId": source_plan_draft_id,
            "planningTraceId": graph.metadata.get("planningTraceId"),
            "successCriteria": _string_list(graph.metadata.get("successCriteria")),
            "verificationPlan": _string_list(graph.metadata.get("verificationPlan")),
        },
    )


def review_agent_compiled_graph(
    compiled_graph: AgentCompiledGraph,
) -> AgentCompileReview:
    issues: list[AgentCompileIssue] = []
    node_ids = {node.node_id for node in compiled_graph.nodes}

    for node in compiled_graph.nodes:
        if node.binding_kind == "tool" and node.tool_contract is None:
            issues.append(
                _issue(
                    "missing_tool_contract",
                    f"tool node {node.node_id} has no tool contract",
                    node_id=node.node_id,
                )
            )
        if node.binding_kind == "model" and node.model_contract is None:
            issues.append(
                _issue(
                    "missing_model_contract",
                    f"model node {node.node_id} has no model contract",
                    node_id=node.node_id,
                )
            )
        if not node.verification_criteria:
            issues.append(
                _issue(
                    "missing_verification_criteria",
                    f"node {node.node_id} has no verification criteria",
                    node_id=node.node_id,
                )
            )

        for dependency_id in node.dependencies:
            if dependency_id not in node_ids:
                issues.append(
                    _issue(
                        "missing_dependency_node",
                        (
                            f"node {node.node_id} depends on missing node "
                            f"{dependency_id}"
                        ),
                        node_id=node.node_id,
                        dependency_id=dependency_id,
                    )
                )

    actual_edges = {(edge.source, edge.target) for edge in compiled_graph.edges}
    expected_edges = {
        (dependency_id, node.node_id)
        for node in compiled_graph.nodes
        for dependency_id in node.dependencies
    }
    for edge in compiled_graph.edges:
        if edge.source not in node_ids or edge.target not in node_ids:
            issues.append(
                _issue(
                    "bad_edge_endpoint",
                    (
                        f"edge {edge.id} references missing endpoint "
                        f"{edge.source}->{edge.target}"
                    ),
                    edge_id=edge.id,
                )
            )

    for source, target in sorted(expected_edges - actual_edges):
        issues.append(
            _issue(
                "missing_dependency_edge",
                f"missing dependency edge {source}->{target}",
                node_id=target,
                dependency_id=source,
            )
        )
    for source, target in sorted(actual_edges - expected_edges):
        issues.append(
            _issue(
                "unexpected_edge",
                f"unexpected edge {source}->{target}",
            )
        )

    action_ids = {
        action.action_id for action in compiled_graph.action_graph.actions
    }
    for node_id in sorted(node_ids - action_ids):
        issues.append(
            _issue(
                "missing_action_graph_action",
                f"action graph is missing action for node {node_id}",
                node_id=node_id,
            )
        )

    is_valid = not issues
    return AgentCompileReview(
        status="approved" if is_valid else "invalid",
        is_valid=is_valid,
        unsupported_capabilities=_unsupported_capabilities(issues),
        missing_bindings=_missing_bindings(issues),
        execution_ready=is_valid,
        issues=issues,
    )


def _enforce_deep_planning_provenance(graph: RunGraph) -> str:
    metadata = graph.metadata
    source_plan_draft_id = metadata.get("sourcePlanDraftId")
    if (
        metadata.get("generatedBy") != "deep_agent_runtime"
        or metadata.get("modelPolicy") != "deep_reasoning"
        or not _is_non_empty_string(source_plan_draft_id)
    ):
        raise AgentPlanCompileError(
            "invalid_agent_plan_provenance",
            (
                "confirmed agent plan graph must be generated by deep_agent_runtime "
                "with deep_reasoning model policy and sourcePlanDraftId"
            ),
        )
    return source_plan_draft_id


def _preflight_graph_nodes(graph: RunGraph) -> None:
    for node in graph.nodes:
        _require_node_metadata(node)
        if node.nodeType == "fixed_tool":
            _require_fixed_tool_contract(node)
        if node.nodeType == "model":
            _require_model_contract(node)


def _require_node_metadata(node: GraphNode) -> None:
    required_fields = (
        "sourcePlanStepId",
        "expectedOutput",
        "verificationCriteria",
        "requiredCapabilities",
    )
    for field_name in required_fields:
        value = node.metadata.get(field_name)
        if _metadata_value_is_missing(value):
            raise AgentPlanCompileError(
                "missing_node_metadata",
                f"node {node.nodeId} is missing metadata.{field_name}",
            )


def _require_fixed_tool_contract(node: GraphNode) -> None:
    if not _is_non_empty_string(node.toolRef):
        raise AgentPlanCompileError(
            "missing_tool_ref",
            f"fixed_tool node {node.nodeId} is missing toolRef",
        )

    operation = node.toolBinding.operation if node.toolBinding is not None else None
    if not _is_non_empty_string(operation):
        raise AgentPlanCompileError(
            "missing_tool_binding_operation",
            f"fixed_tool node {node.nodeId} is missing toolBinding.operation",
        )


def _require_model_contract(node: GraphNode) -> None:
    if not _is_non_empty_string(node.modelRef):
        raise AgentPlanCompileError(
            "missing_model_ref",
            f"model node {node.nodeId} is missing modelRef",
        )


def _runtime_action_graph_from_execution_metadata(
    execution_graph: ExecutionGraph,
) -> RuntimeActionGraph:
    action_graph = execution_graph.metadata.get("actionGraph")
    if not isinstance(action_graph, dict):
        raise AgentPlanCompileError(
            "missing_action_graph",
            "execution graph metadata is missing actionGraph",
        )
    try:
        return RuntimeActionGraph.model_validate(action_graph)
    except ValidationError as error:
        raise AgentPlanCompileError(
            "invalid_action_graph",
            str(error),
        ) from error


def _compile_node(
    node: GraphNode,
    execution_node: ExecutionNode,
    *,
    source_plan_draft_id: str,
) -> AgentCompiledNode:
    tool_contract = _tool_contract(execution_node)
    model_contract = _model_contract(execution_node)
    expected_artifacts = (
        list(tool_contract.expected_artifacts)
        if tool_contract is not None
        else []
    )

    return AgentCompiledNode(
        node_id=node.nodeId,
        node_type=node.nodeType,
        display_name=node.displayName,
        binding_kind=_binding_kind(node),
        dependencies=list(node.dependencies),
        source_plan_draft_id=(
            _string_or_none(node.metadata.get("sourcePlanDraftId"))
            or source_plan_draft_id
        ),
        source_plan_step_id=str(node.metadata["sourcePlanStepId"]),
        rationale=_string_or_none(node.metadata.get("rationale")),
        expected_output=str(node.metadata["expectedOutput"]),
        verification_criteria=_string_list(node.metadata["verificationCriteria"]),
        required_capabilities=_string_list(node.metadata["requiredCapabilities"]),
        permissions_required=_compiled_permissions(execution_node),
        expected_artifacts=expected_artifacts,
        tool_contract=tool_contract,
        model_contract=model_contract,
        metadata=dict(node.metadata),
    )


def _tool_contract(
    execution_node: ExecutionNode,
) -> AgentCompiledToolContract | None:
    binding = execution_node.tool_binding
    if binding is None:
        return None

    expected_artifacts = [
        ExpectedArtifact(
            name=artifact.name,
            path_template=artifact.path_template,
            mime_type=artifact.mime_type,
            source_argument=artifact.source_argument,
        )
        for artifact in binding.expected_artifacts
    ]
    return AgentCompiledToolContract(
        tool_id=binding.tool_id,
        provider_id=binding.provider_id,
        operation=str(binding.operation),
        arguments_template=binding.arguments_template.model_dump(mode="json"),
        input_mappings=[
            mapping.model_dump(mode="json") for mapping in binding.input_mappings
        ],
        output_schema=(
            dict(binding.output_schema)
            if binding.output_schema is not None
            else None
        ),
        expected_artifacts=expected_artifacts,
        permission_scope=binding.permission_scope.model_dump(mode="json"),
    )


def _model_contract(
    execution_node: ExecutionNode,
) -> AgentCompiledModelContract | None:
    binding = execution_node.model_binding
    if binding is None:
        return None
    return AgentCompiledModelContract(
        model_ref=binding.model_ref,
        policy_ref=binding.policy_ref,
    )


def _compiled_permissions(execution_node: ExecutionNode) -> list[str]:
    permissions = list(execution_node.permissions_required)
    if execution_node.tool_binding is not None:
        permissions.extend(execution_node.tool_binding.permission_scope.permissions)
    return _dedupe(permissions)


def _binding_kind(
    node: GraphNode,
) -> Literal["tool", "model", "output", "control"]:
    if node.nodeType == "fixed_tool":
        return "tool"
    if node.nodeType == "model":
        return "model"
    if node.nodeType == "output":
        return "output"
    return "control"


def _compile_fingerprint(graph: RunGraph) -> str:
    payload = {
        "graphId": graph.graphId,
        "metadata": graph.metadata,
        "nodes": [
            node.model_dump(mode="json", exclude_none=True)
            for node in graph.nodes
        ],
        "edges": [
            edge.model_dump(mode="json", exclude_none=True)
            for edge in graph.edges
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _compile_id(
    *,
    graph_id: str,
    run_id: str,
    confirmation_id: str,
    fingerprint: str,
) -> str:
    seed = json.dumps(
        {
            "graphId": graph_id,
            "runId": run_id,
            "confirmationId": confirmation_id,
            "fingerprint": fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"compile-{hashlib.sha256(seed).hexdigest()[:16]}"


def _issue(
    code: str,
    message: str,
    *,
    node_id: str | None = None,
    edge_id: str | None = None,
    dependency_id: str | None = None,
    capability: str | None = None,
) -> AgentCompileIssue:
    return AgentCompileIssue(
        code=code,
        message=message,
        node_id=node_id,
        edge_id=edge_id,
        dependency_id=dependency_id,
        capability=capability,
    )


def _missing_bindings(issues: list[AgentCompileIssue]) -> list[str]:
    return _dedupe(
        [
            issue.node_id
            for issue in issues
            if issue.code in {"missing_tool_contract", "missing_model_contract"}
            and issue.node_id is not None
        ]
    )


def _unsupported_capabilities(issues: list[AgentCompileIssue]) -> list[str]:
    return _dedupe(
        [
            issue.capability
            for issue in issues
            if issue.code.startswith("unsupported_capability")
            and issue.capability is not None
        ]
    )


def _metadata_value_is_missing(value: Any) -> bool:
    if not _is_non_empty_string(value) and not isinstance(value, list):
        return True
    if isinstance(value, list):
        return not value or any(not _is_non_empty_string(item) for item in value)
    return False


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
