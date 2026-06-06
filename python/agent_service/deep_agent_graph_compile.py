from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from agent_service.deep_agent_models import GraphReview, PlanDraft, PlanStep
from agent_service.node_catalog import (
    NodeCatalogBuilder,
    NodeCatalogSnapshot,
    NodeDefinition,
)
from agent_service.node_catalog_resolver import NodeCatalogResolver
from agent_service.schemas import RunGraph
from agent_service.tool_execution import default_tool_packages_root
from agent_service.tool_registry import ToolRegistry


def compile_agent_plan_graph(
    draft: PlanDraft,
    *,
    task_id: str,
    node_catalog: NodeCatalogSnapshot | None = None,
) -> dict:
    resolver = NodeCatalogResolver(node_catalog or _default_node_catalog())
    nodes = [
        _compile_step_node(
            step,
            index=index,
            source_plan_draft_id=draft.plan_draft_id,
            resolver=resolver,
        )
        for index, step in enumerate(draft.steps)
    ]
    edges = [
        {
            "id": f"{dependency_id}->{step.step_id}",
            "source": dependency_id,
            "target": step.step_id,
        }
        for step in draft.steps
        for dependency_id in step.depends_on
    ]
    graph = {
        "graphId": f"{task_id}-deep-agent-graph",
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "generatedBy": "deep_agent_runtime",
            "sourcePlanDraftId": draft.plan_draft_id,
            "planningTraceId": task_id,
            "modelPolicy": "deep_reasoning",
            "successCriteria": list(draft.success_criteria),
            "verificationPlan": list(draft.verification_plan),
        },
    }

    RunGraph.model_validate(graph)
    return graph


def review_compiled_graph(draft: PlanDraft, graph: dict) -> GraphReview:
    try:
        validated_graph = RunGraph.model_validate(graph)
    except ValidationError:
        return GraphReview(
            status="invalid",
            findings=["invalid_run_graph_schema"],
        )

    graph = validated_graph.model_dump(exclude_none=True)
    step_by_id = {step.step_id: step for step in draft.steps}
    plan_step_ids = set(step_by_id)
    seen_step_ids: set[str] = set()
    findings: list[str] = []
    extra_node_ids: list[str] = []

    for node in graph.get("nodes", []):
        if not isinstance(node, dict):
            findings.append("invalid_node_shape")
            continue

        node_id = _node_id(node)
        metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        source_plan_draft_id = metadata.get("sourcePlanDraftId")
        source_plan_step_id = metadata.get("sourcePlanStepId")

        if (
            source_plan_draft_id != draft.plan_draft_id
            or source_plan_step_id not in plan_step_ids
        ):
            extra_node_ids.append(node_id)
            continue

        if node_id != source_plan_step_id:
            findings.append(f"node_id_mismatch:{node_id}:{source_plan_step_id}")
        if source_plan_step_id in seen_step_ids:
            findings.append(f"duplicate_plan_step_node:{source_plan_step_id}")
        seen_step_ids.add(source_plan_step_id)
        step = step_by_id[source_plan_step_id]

        _review_required_metadata(node_id, metadata, step, findings)
        _review_fixed_tool_binding(node_id, node, findings)
        _review_dependencies(node_id, node, step, findings)

    _review_edges(draft, graph, findings)

    missing_plan_step_ids = [
        step.step_id for step in draft.steps if step.step_id not in seen_step_ids
    ]
    status = (
        "invalid"
        if findings or missing_plan_step_ids or extra_node_ids
        else "approved"
    )

    return GraphReview(
        status=status,
        findings=findings,
        missing_plan_step_ids=missing_plan_step_ids,
        extra_node_ids=extra_node_ids,
    )


def _compile_step_node(
    step: PlanStep,
    *,
    index: int,
    source_plan_draft_id: str,
    resolver: NodeCatalogResolver,
) -> dict[str, Any]:
    resolution = resolver.resolve(
        required_capabilities=step.required_capabilities,
        preferred_node_ids=step.preferred_node_ids,
    )
    catalog_node = resolution.node
    node_type = _graph_node_type(catalog_node)
    node: dict[str, Any] = {
        "nodeId": step.step_id,
        "nodeType": node_type,
        "displayName": step.title,
        "status": "waiting",
        "inputPorts": [],
        "outputPorts": [],
        "dependencies": list(step.depends_on),
        "summary": step.objective,
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "permissionsRequired": list(catalog_node.permissions.permissions),
        "position": {"x": float(index * 240), "y": 0.0},
        "metadata": {
            "sourcePlanDraftId": source_plan_draft_id,
            "sourcePlanStepId": step.step_id,
            "rationale": step.rationale,
            "expectedOutput": step.expected_output,
            "verificationCriteria": list(step.verification_criteria),
            "requiredCapabilities": list(step.required_capabilities),
            "catalogNodeId": catalog_node.node_id,
            "catalogDisplayName": catalog_node.display_name,
            "nodeSelectionReason": resolution.selection_reason,
            "executionKind": catalog_node.execution.type,
            "catalogCapabilities": list(catalog_node.capabilities),
            "catalogRiskLevel": catalog_node.permissions.risk_level,
        },
    }

    if node_type == "fixed_tool":
        tool_ref = catalog_node.execution.tool_id
        operation = catalog_node.execution.operation
        node["toolRef"] = tool_ref
        node["toolBinding"] = {
            "toolId": tool_ref,
            "operation": operation,
        }
    elif node_type == "model":
        node["modelRef"] = "local-task-reasoner"

    return node


def _default_node_catalog() -> NodeCatalogSnapshot:
    return NodeCatalogBuilder(
        tool_registry=ToolRegistry.from_packages_root(default_tool_packages_root()),
    ).build()


def _graph_node_type(node: NodeDefinition) -> str:
    if node.execution.type == "tool":
        return "fixed_tool"
    if node.execution.type == "model":
        return "model"
    if node.execution.type == "output":
        return "output"
    return "planning"


def _review_required_metadata(
    node_id: str,
    metadata: dict[str, Any],
    step: PlanStep,
    findings: list[str],
) -> None:
    required_fields = (
        "rationale",
        "expectedOutput",
        "verificationCriteria",
        "catalogNodeId",
        "catalogDisplayName",
        "nodeSelectionReason",
        "executionKind",
        "catalogCapabilities",
        "catalogRiskLevel",
    )
    for field_name in required_fields:
        value = metadata.get(field_name)
        if value is None or value == "" or value == []:
            findings.append(f"missing_node_metadata:{node_id}:{field_name}")

    required_capabilities = metadata.get("requiredCapabilities")
    if not isinstance(required_capabilities, list) or (
        step.required_capabilities and not required_capabilities
    ):
        findings.append(f"missing_node_metadata:{node_id}:requiredCapabilities")


def _review_fixed_tool_binding(
    node_id: str,
    node: dict[str, Any],
    findings: list[str],
) -> None:
    if node.get("nodeType") != "fixed_tool":
        return

    tool_binding = node.get("toolBinding")
    operation = (
        tool_binding.get("operation") if isinstance(tool_binding, dict) else None
    )
    if not isinstance(operation, str) or not operation.strip():
        findings.append(f"missing_tool_binding_operation:{node_id}")


def _review_dependencies(
    node_id: str,
    node: dict[str, Any],
    step: PlanStep,
    findings: list[str],
) -> None:
    actual_dependencies = set(node.get("dependencies", []))
    expected_dependencies = set(step.depends_on)
    if actual_dependencies == expected_dependencies:
        return

    missing = ",".join(sorted(expected_dependencies - actual_dependencies))
    unexpected = ",".join(sorted(actual_dependencies - expected_dependencies))
    findings.append(
        f"dependency_mismatch:{node_id}:missing={missing}:unexpected={unexpected}"
    )


def _review_edges(
    draft: PlanDraft,
    graph: dict,
    findings: list[str],
) -> None:
    expected_edges = [
        (dependency_id, step.step_id)
        for step in draft.steps
        for dependency_id in step.depends_on
    ]
    actual_edges: set[tuple[str, str]] = set()

    for edge in graph.get("edges", []):
        if not isinstance(edge, dict):
            findings.append("invalid_edge_shape")
            continue

        source = edge.get("source")
        target = edge.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            findings.append("invalid_edge_shape")
            continue

        actual_edges.add((source, target))

    expected_edge_set = set(expected_edges)
    for source, target in expected_edges:
        if (source, target) not in actual_edges:
            findings.append(f"missing_edge:{source}->{target}")

    for source, target in sorted(actual_edges - expected_edge_set):
        findings.append(f"extra_edge:{source}->{target}")


def _node_id(node: dict[str, Any]) -> str:
    value = node.get("nodeId")
    return value if isinstance(value, str) and value else "<unknown>"
