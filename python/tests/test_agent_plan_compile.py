from __future__ import annotations

from copy import deepcopy

import pytest

from agent_service.agent_plan_compile import (
    AgentPlanCompileError,
    compile_confirmed_agent_plan_graph,
    review_agent_compiled_graph,
)
from agent_service.deep_agent_graph_compile import compile_agent_plan_graph
from agent_service.deep_agent_models import PlanDraft, PlanStep
from agent_service.schemas import RunGraph
from agent_service.tool_registry import ToolRegistry


def _step(
    step_id: str,
    *,
    depends_on: list[str] | None = None,
    required_capabilities: list[str] | None = None,
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        title=f"Title for {step_id}",
        objective=f"Objective for {step_id}.",
        rationale=f"Rationale for {step_id}.",
        inputs=["uploaded document"],
        required_capabilities=required_capabilities or ["model.reasoning"],
        expected_output=f"Expected output for {step_id}.",
        verification_criteria=[f"Verification criteria for {step_id}."],
        depends_on=list(depends_on or []),
    )


def _draft(
    step_ids: list[str],
    *,
    capabilities_by_step: dict[str, list[str]] | None = None,
) -> PlanDraft:
    capabilities_by_step = capabilities_by_step or {}
    steps: list[PlanStep] = []
    for index, step_id in enumerate(step_ids):
        dependencies = [step_ids[index - 1]] if index else []
        steps.append(
            _step(
                step_id,
                depends_on=dependencies,
                required_capabilities=capabilities_by_step.get(step_id),
            )
        )

    return PlanDraft(
        plan_draft_id=f"plan-{'-'.join(step_ids)}",
        task_understanding="Compile a strict plan draft into an executable graph.",
        success_criteria=["Every plan step is represented in the compiled graph."],
        inputs=[{"kind": "attachment", "name": "contract.docx"}],
        assumptions=["The plan draft has already passed plan review."],
        missing_information=[],
        candidate_strategies=[
            {
                "strategyId": "strategy-compile-plan",
                "summary": "Compile plan steps directly into graph nodes.",
                "tradeoffs": ["Preserves step order and dependencies."],
            }
        ],
        recommended_strategy="strategy-compile-plan",
        steps=steps,
        required_capabilities=["model.reasoning"],
        risks=["Graph provenance may drift from the reviewed plan."],
        verification_plan=["Validate graph nodes against plan step provenance."],
    )


def _graph_payload(
    step_ids: list[str],
    *,
    capabilities_by_step: dict[str, list[str]] | None = None,
) -> dict:
    return compile_agent_plan_graph(
        _draft(step_ids, capabilities_by_step=capabilities_by_step),
        task_id="task-1",
    )


def _deep_graph(
    step_ids: list[str],
    *,
    capabilities_by_step: dict[str, list[str]] | None = None,
) -> RunGraph:
    return RunGraph.model_validate(
        _graph_payload(step_ids, capabilities_by_step=capabilities_by_step)
    )


def _compile(graph: RunGraph):
    return compile_confirmed_agent_plan_graph(
        graph,
        task_id="task-1",
        run_id="run-1",
        thread_id="thread-1",
        confirmation_id="confirm-1",
        tool_registry=ToolRegistry([]),
    )


def test_valid_deep_planning_graph_compiles_and_preserves_provenance_verification() -> None:
    payload = _graph_payload(
        ["write", "reason"],
        capabilities_by_step={"write": ["document.convert.markdown"]},
    )
    payload["nodes"][0]["permissionsRequired"] = ["read_project_files"]
    payload["nodes"][0]["toolBinding"]["permissionScope"] = {
        "permissions": ["read_project_files", "write_project_files"],
        "filesystem": "project",
        "network": False,
        "sandbox": True,
        "timeoutMs": 1000,
    }
    payload["nodes"][0]["toolBinding"]["expectedArtifacts"] = [
        {
            "name": "markdown",
            "pathTemplate": "artifacts/report.md",
            "mimeType": "text/markdown",
            "sourceArgument": "output_path",
        }
    ]
    graph = RunGraph.model_validate(payload)

    compiled = _compile(graph)

    assert compiled.source_graph_id == graph.graphId
    assert compiled.source_plan_draft_id == graph.metadata["sourcePlanDraftId"]
    assert compiled.planning_trace_id == graph.metadata["planningTraceId"]
    assert compiled.success_criteria == graph.metadata["successCriteria"]
    assert compiled.verification_plan == graph.metadata["verificationPlan"]
    assert compiled.task_id == "task-1"
    assert compiled.run_id == "run-1"
    assert compiled.thread_id == "thread-1"
    assert compiled.confirmation_id == "confirm-1"
    assert compiled.status == "compiled"
    assert compiled.action_graph.graph_id == graph.graphId

    tool_node = compiled.node_by_id("write")
    assert tool_node.node_type == "fixed_tool"
    assert tool_node.binding_kind == "tool"
    assert tool_node.source_plan_step_id == "write"
    assert tool_node.expected_output == "Expected output for write."
    assert tool_node.verification_criteria == ["Verification criteria for write."]
    assert tool_node.required_capabilities == ["document.convert.markdown"]
    assert tool_node.permissions_required == [
        "read_project_files",
        "write_project_files",
    ]
    assert tool_node.tool_contract is not None
    assert tool_node.tool_contract.tool_id == "document.markitdown_convert"
    assert tool_node.tool_contract.operation == "convert_local_file"
    assert tool_node.expected_artifacts[0].path_template == "artifacts/report.md"

    model_node = compiled.node_by_id("reason")
    assert model_node.node_type == "model"
    assert model_node.binding_kind == "model"
    assert model_node.model_contract is not None
    assert model_node.model_contract.model_ref == "local-task-reasoner"


def test_legacy_graph_without_deep_planning_metadata_raises() -> None:
    graph = _deep_graph(["read"]).model_copy(update={"metadata": {}})

    with pytest.raises(AgentPlanCompileError) as error_info:
        _compile(graph)

    assert error_info.value.code == "invalid_agent_plan_provenance"


def test_fixed_tool_node_without_tool_binding_operation_raises() -> None:
    payload = _graph_payload(
        ["write"],
        capabilities_by_step={"write": ["document.convert.markdown"]},
    )
    del payload["nodes"][0]["toolBinding"]["operation"]
    graph = RunGraph.model_validate(payload)

    with pytest.raises(AgentPlanCompileError) as error_info:
        _compile(graph)

    assert error_info.value.code == "missing_tool_binding_operation"


def test_fingerprint_is_stable_and_changes_when_verification_criteria_changes() -> None:
    graph = _deep_graph(["read"])
    same_graph = RunGraph.model_validate(graph.model_dump(mode="json"))

    first = _compile(graph)
    second = _compile(same_graph)

    assert first.compile_fingerprint == second.compile_fingerprint
    assert first.compile_id == second.compile_id

    changed_payload = deepcopy(graph.model_dump(mode="json"))
    changed_payload["nodes"][0]["metadata"]["verificationCriteria"] = [
        "Changed verification criteria."
    ]
    changed = _compile(RunGraph.model_validate(changed_payload))

    assert changed.compile_fingerprint != first.compile_fingerprint
    assert changed.compile_id != first.compile_id


def test_review_passes_for_valid_compile() -> None:
    compiled = _compile(_deep_graph(["read", "reason"]))

    review = review_agent_compiled_graph(compiled)

    assert review.status == "approved"
    assert review.is_valid is True
    assert review.execution_ready is True
    assert review.missing_bindings == []
    assert review.unsupported_capabilities == []
    assert review.issues == []


def test_review_reports_missing_bindings_for_missing_contract() -> None:
    compiled = _compile(
        _deep_graph(
            ["write"],
            capabilities_by_step={"write": ["document.convert.markdown"]},
        )
    )
    broken_node = compiled.node_by_id("write").model_copy(
        update={"tool_contract": None}
    )
    compiled = compiled.model_copy(update={"nodes": [broken_node]})

    review = review_agent_compiled_graph(compiled)

    assert review.status == "invalid"
    assert review.is_valid is False
    assert review.execution_ready is False
    assert review.missing_bindings == ["write"]
    assert review.unsupported_capabilities == []
    assert [issue.code for issue in review.issues] == ["missing_tool_contract"]


def test_model_nodes_preserve_contract_and_fixed_tool_failures_are_not_converted() -> None:
    compiled = _compile(_deep_graph(["reason"]))

    model_node = compiled.node_by_id("reason")
    assert model_node.binding_kind == "model"
    assert model_node.model_contract is not None
    assert model_node.model_contract.model_ref == "local-task-reasoner"
    assert model_node.tool_contract is None

    bad_payload = _graph_payload(
        ["write"],
        capabilities_by_step={"write": ["document.convert.markdown"]},
    )
    bad_payload["nodes"][0]["toolBinding"] = {"toolId": "document.markitdown_convert"}

    with pytest.raises(AgentPlanCompileError) as error_info:
        _compile(RunGraph.model_validate(bad_payload))

    assert error_info.value.code == "missing_tool_binding_operation"
