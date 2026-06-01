from __future__ import annotations

from copy import deepcopy

from agent_service.deep_agent_graph_compile import (
    compile_agent_plan_graph,
    review_compiled_graph,
)
from agent_service.deep_agent_models import PlanDraft, PlanStep
from agent_service.schemas import RunGraph


def _step(step_id: str, *, depends_on: list[str] | None = None) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        title=f"Title for {step_id}",
        objective=f"Objective for {step_id}.",
        rationale=f"Rationale for {step_id}.",
        inputs=["uploaded document"],
        required_capabilities=["model.reasoning"],
        expected_output=f"Expected output for {step_id}.",
        verification_criteria=[f"Verification criteria for {step_id}."],
        depends_on=list(depends_on or []),
    )


def _draft(step_ids: list[str]) -> PlanDraft:
    steps: list[PlanStep] = []
    for index, step_id in enumerate(step_ids):
        dependencies = [step_ids[index - 1]] if index else []
        steps.append(_step(step_id, depends_on=dependencies))

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


def test_compile_agent_plan_graph_traces_every_node_to_plan_step() -> None:
    draft = _draft(["read", "reason"])

    graph = compile_agent_plan_graph(draft, task_id="task-1")

    assert graph["metadata"] == {
        "generatedBy": "deep_agent_runtime",
        "sourcePlanDraftId": draft.plan_draft_id,
        "planningTraceId": "task-1",
        "modelPolicy": "deep_reasoning",
        "successCriteria": draft.success_criteria,
        "verificationPlan": draft.verification_plan,
    }
    assert [node["nodeId"] for node in graph["nodes"]] == ["read", "reason"]
    assert graph["edges"] == [
        {"id": "read->reason", "source": "read", "target": "reason"}
    ]

    first_node = graph["nodes"][0]
    first_step = draft.steps[0]
    assert first_node["displayName"] == first_step.title
    assert first_node["summary"] == first_step.objective
    assert first_node["dependencies"] == first_step.depends_on
    assert first_node["nodeType"] == "model"
    assert first_node["modelRef"] == "local-task-reasoner"
    assert first_node["status"] == "waiting"
    assert first_node["createdBy"] == "agent"
    assert first_node["artifactRefs"] == []
    assert first_node["retryCount"] == 0
    assert first_node["position"] == {"x": 0.0, "y": 0.0}
    assert first_node["metadata"] == {
        "sourcePlanDraftId": draft.plan_draft_id,
        "sourcePlanStepId": first_step.step_id,
        "rationale": first_step.rationale,
        "expectedOutput": first_step.expected_output,
        "verificationCriteria": first_step.verification_criteria,
        "requiredCapabilities": first_step.required_capabilities,
    }

    RunGraph.model_validate(graph)


def test_compile_agent_plan_graph_changes_when_plan_steps_change() -> None:
    first_graph = compile_agent_plan_graph(_draft(["read", "write"]), task_id="task-1")
    second_graph = compile_agent_plan_graph(_draft(["read", "verify"]), task_id="task-1")

    assert [node["nodeId"] for node in first_graph["nodes"]] != [
        node["nodeId"] for node in second_graph["nodes"]
    ]


def test_review_compiled_graph_rejects_extra_node_without_plan_provenance() -> None:
    draft = _draft(["read"])
    graph = compile_agent_plan_graph(draft, task_id="task-1")
    graph["nodes"].append(
        {
            "nodeId": "extra",
            "nodeType": "model",
            "displayName": "Extra",
            "status": "waiting",
            "inputPorts": [],
            "outputPorts": [],
            "dependencies": [],
            "modelRef": "local-task-reasoner",
            "summary": "Extra node.",
            "createdBy": "agent",
            "artifactRefs": [],
            "retryCount": 0,
            "position": {"x": 100.0, "y": 0.0},
            "metadata": {},
        }
    )

    review = review_compiled_graph(draft, graph)

    assert review.status == "invalid"
    assert review.extra_node_ids == ["extra"]


def test_review_compiled_graph_rejects_missing_plan_step() -> None:
    draft = _draft(["read", "write"])
    graph = compile_agent_plan_graph(draft, task_id="task-1")
    graph["nodes"] = graph["nodes"][:1]

    review = review_compiled_graph(draft, graph)

    assert review.status == "invalid"
    assert review.missing_plan_step_ids == ["write"]


def test_review_compiled_graph_rejects_dependency_mismatch() -> None:
    draft = _draft(["read", "write"])
    graph = compile_agent_plan_graph(draft, task_id="task-1")
    graph["nodes"][1]["dependencies"] = []

    review = review_compiled_graph(draft, graph)

    assert review.status == "invalid"
    assert review.findings == [
        "dependency_mismatch:write:missing=read:unexpected="
    ]


def test_review_compiled_graph_rejects_duplicate_valid_provenance_node() -> None:
    draft = _draft(["read"])
    graph = compile_agent_plan_graph(draft, task_id="task-1")
    duplicate_node = deepcopy(graph["nodes"][0])
    graph["nodes"].append(duplicate_node)

    review = review_compiled_graph(draft, graph)

    assert review.status == "invalid"
    assert review.findings == ["duplicate_plan_step_node:read"]


def test_review_compiled_graph_rejects_missing_expected_edge() -> None:
    draft = _draft(["read", "write"])
    graph = compile_agent_plan_graph(draft, task_id="task-1")
    graph["edges"] = []

    review = review_compiled_graph(draft, graph)

    assert review.status == "invalid"
    assert review.findings == ["missing_edge:read->write"]


def test_review_compiled_graph_rejects_extra_undeclared_edge() -> None:
    draft = _draft(["read", "write"])
    graph = compile_agent_plan_graph(draft, task_id="task-1")
    graph["edges"].append({"id": "write->read", "source": "write", "target": "read"})

    review = review_compiled_graph(draft, graph)

    assert review.status == "invalid"
    assert review.findings == ["extra_edge:write->read"]


def test_review_compiled_graph_approves_clean_compiled_graph() -> None:
    draft = _draft(["read", "write"])
    graph = compile_agent_plan_graph(draft, task_id="task-1")

    review = review_compiled_graph(draft, graph)

    assert review.status == "approved"
    assert review.findings == []
    assert review.missing_plan_step_ids == []
    assert review.extra_node_ids == []


def test_compile_document_capability_uses_fixed_tool_binding() -> None:
    draft = _draft(["read"])
    document_step = draft.steps[0].model_copy(
        update={"required_capabilities": ["document.read"]}
    )
    draft = draft.model_copy(update={"steps": [document_step]})

    graph = compile_agent_plan_graph(draft, task_id="task-1")

    assert graph["nodes"][0]["nodeType"] == "fixed_tool"
    assert graph["nodes"][0]["toolRef"] == "document.read_write"
    assert graph["nodes"][0]["toolBinding"] == {
        "toolId": "document.read_write",
        "operation": "read",
    }
    assert "modelRef" not in graph["nodes"][0]
    RunGraph.model_validate(graph)


def test_compile_document_write_capability_uses_explicit_write_operation() -> None:
    draft = _draft(["write"])
    document_step = draft.steps[0].model_copy(
        update={"required_capabilities": ["document.write"]}
    )
    draft = draft.model_copy(update={"steps": [document_step]})

    graph = compile_agent_plan_graph(draft, task_id="task-1")

    assert graph["nodes"][0]["nodeType"] == "fixed_tool"
    assert graph["nodes"][0]["toolRef"] == "document.read_write"
    assert graph["nodes"][0]["toolBinding"] == {
        "toolId": "document.read_write",
        "operation": "write_markdown",
    }
    RunGraph.model_validate(graph)


def test_compile_unknown_document_capability_falls_back_to_model_node() -> None:
    draft = _draft(["inspect"])
    document_step = draft.steps[0].model_copy(
        update={"required_capabilities": ["document.unknown_operation"]}
    )
    draft = draft.model_copy(update={"steps": [document_step]})

    graph = compile_agent_plan_graph(draft, task_id="task-1")

    assert graph["nodes"][0]["nodeType"] == "model"
    assert graph["nodes"][0]["modelRef"] == "local-task-reasoner"
    assert "toolRef" not in graph["nodes"][0]
    assert "toolBinding" not in graph["nodes"][0]
    RunGraph.model_validate(graph)


def test_review_compiled_graph_rejects_missing_provenance_detail() -> None:
    draft = _draft(["read"])
    graph = compile_agent_plan_graph(draft, task_id="task-1")
    graph = deepcopy(graph)
    del graph["nodes"][0]["metadata"]["rationale"]

    review = review_compiled_graph(draft, graph)

    assert review.status == "invalid"
    assert review.findings == ["missing_node_metadata:read:rationale"]


def test_review_compiled_graph_rejects_missing_required_capabilities() -> None:
    draft = _draft(["read"])
    graph = compile_agent_plan_graph(draft, task_id="task-1")
    graph = deepcopy(graph)
    del graph["nodes"][0]["metadata"]["requiredCapabilities"]

    review = review_compiled_graph(draft, graph)

    assert review.status == "invalid"
    assert review.findings == ["missing_node_metadata:read:requiredCapabilities"]


def test_review_compiled_graph_treats_missing_source_step_id_as_extra() -> None:
    draft = _draft(["read"])
    graph = compile_agent_plan_graph(draft, task_id="task-1")
    graph = deepcopy(graph)
    del graph["nodes"][0]["metadata"]["sourcePlanStepId"]

    review = review_compiled_graph(draft, graph)

    assert review.status == "invalid"
    assert review.extra_node_ids == ["read"]
    assert review.missing_plan_step_ids == ["read"]


def test_review_compiled_graph_returns_invalid_for_schema_errors() -> None:
    draft = _draft(["read"])
    graph = compile_agent_plan_graph(draft, task_id="task-1")
    del graph["graphId"]

    review = review_compiled_graph(draft, graph)

    assert review.status == "invalid"
    assert review.findings == ["invalid_run_graph_schema"]


def test_review_compiled_graph_rejects_node_id_mismatch() -> None:
    draft = _draft(["read"])
    graph = compile_agent_plan_graph(draft, task_id="task-1")
    graph["nodes"][0]["nodeId"] = "different-node"

    review = review_compiled_graph(draft, graph)

    assert review.status == "invalid"
    assert review.findings == ["node_id_mismatch:different-node:read"]


def test_review_compiled_graph_rejects_fixed_tool_without_operation() -> None:
    draft = _draft(["read"])
    document_step = draft.steps[0].model_copy(
        update={"required_capabilities": ["document.read"]}
    )
    draft = draft.model_copy(update={"steps": [document_step]})
    graph = compile_agent_plan_graph(draft, task_id="task-1")
    del graph["nodes"][0]["toolBinding"]["operation"]

    review = review_compiled_graph(draft, graph)

    assert review.status == "invalid"
    assert review.findings == ["missing_tool_binding_operation:read"]
