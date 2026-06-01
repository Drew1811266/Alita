from __future__ import annotations

from typing import Any

from agent_service.deep_agent_models import GraphReview, PlanDraft, PlanStep
from agent_service.schemas import RunGraph


_DOCUMENT_TOOL_REFS = {
    "document.read": "document.read_write",
    "document.write": "document.read_write",
    "document.read_write": "document.read_write",
    "document.convert": "document.markitdown_convert",
    "document.markitdown_convert": "document.markitdown_convert",
    "document.render": "document.typst_compile",
    "document.typst_compile": "document.typst_compile",
}


def compile_agent_plan_graph(draft: PlanDraft, *, task_id: str) -> dict:
    nodes = [
        _compile_step_node(
            step,
            index=index,
            source_plan_draft_id=draft.plan_draft_id,
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

        if source_plan_step_id in seen_step_ids:
            findings.append(f"duplicate_plan_step_node:{source_plan_step_id}")
        seen_step_ids.add(source_plan_step_id)
        step = step_by_id[source_plan_step_id]

        _review_required_metadata(node_id, metadata, step, findings)
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
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "nodeId": step.step_id,
        "nodeType": "fixed_tool" if _document_tool_ref(step) else "model",
        "displayName": step.title,
        "status": "waiting",
        "inputPorts": [],
        "outputPorts": [],
        "dependencies": list(step.depends_on),
        "summary": step.objective,
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "position": {"x": float(index * 240), "y": 0.0},
        "metadata": {
            "sourcePlanDraftId": source_plan_draft_id,
            "sourcePlanStepId": step.step_id,
            "rationale": step.rationale,
            "expectedOutput": step.expected_output,
            "verificationCriteria": list(step.verification_criteria),
            "requiredCapabilities": list(step.required_capabilities),
        },
    }

    tool_ref = _document_tool_ref(step)
    if tool_ref is not None:
        node["toolRef"] = tool_ref
    else:
        node["modelRef"] = "local-task-reasoner"

    return node


def _document_tool_ref(step: PlanStep) -> str | None:
    for capability in step.required_capabilities:
        if capability in _DOCUMENT_TOOL_REFS:
            return _DOCUMENT_TOOL_REFS[capability]
    for capability in step.required_capabilities:
        if capability.startswith("document."):
            return "document.read_write"
    return None


def _review_required_metadata(
    node_id: str,
    metadata: dict[str, Any],
    step: PlanStep,
    findings: list[str],
) -> None:
    required_fields = ("rationale", "expectedOutput", "verificationCriteria")
    for field_name in required_fields:
        value = metadata.get(field_name)
        if value is None or value == "" or value == []:
            findings.append(f"missing_node_metadata:{node_id}:{field_name}")

    required_capabilities = metadata.get("requiredCapabilities")
    if not isinstance(required_capabilities, list) or (
        step.required_capabilities and not required_capabilities
    ):
        findings.append(f"missing_node_metadata:{node_id}:requiredCapabilities")


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
