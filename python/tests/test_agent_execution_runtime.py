from __future__ import annotations

from typing import Any

import pytest

from agent_service.agent_execution_runtime import (
    AgentExecutionRunResult,
    review_agent_execution_result,
    run_graph_request_from_agent_compiled_graph,
    summarize_agent_execution_events,
)
from agent_service.agent_plan_compile import (
    AgentCompiledGraph,
    compile_confirmed_agent_plan_graph,
)
from agent_service.deep_agent_graph_compile import compile_agent_plan_graph
from agent_service.deep_agent_models import PlanDraft, PlanStep
from agent_service.harness_errors import HarnessError
from agent_service.schemas import AgentEvent, RunGraph
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
    steps = [
        _step(
            step_id,
            depends_on=[step_ids[index - 1]] if index else [],
            required_capabilities=capabilities_by_step.get(step_id),
        )
        for index, step_id in enumerate(step_ids)
    ]
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
) -> dict[str, Any]:
    return compile_agent_plan_graph(
        _draft(step_ids, capabilities_by_step=capabilities_by_step),
        task_id="task-1",
    )


def _deep_graph(
    step_ids: list[str],
    *,
    capabilities_by_step: dict[str, list[str]] | None = None,
    expected_artifact_path: str | None = None,
) -> RunGraph:
    payload = _graph_payload(step_ids, capabilities_by_step=capabilities_by_step)
    if expected_artifact_path is not None:
        payload["nodes"][0]["toolBinding"]["expectedArtifacts"] = [
            {
                "name": "report",
                "pathTemplate": expected_artifact_path,
                "mimeType": "text/markdown",
                "sourceArgument": "output_path",
            }
        ]
    return RunGraph.model_validate(payload)


def _compile(graph: RunGraph) -> AgentCompiledGraph:
    return compile_confirmed_agent_plan_graph(
        graph,
        task_id="task-1",
        run_id="run-1",
        thread_id="thread-1",
        confirmation_id="confirm-1",
        tool_registry=ToolRegistry([]),
    )


def _execution_ready(compiled: AgentCompiledGraph) -> AgentCompiledGraph:
    return compiled.model_copy(update={"status": "execution_ready"})


def _event(event_type: str, payload: dict[str, Any]) -> AgentEvent:
    return AgentEvent(type=event_type, payload=payload)


def test_execution_bridge_rejects_non_execution_ready_compiled_graph() -> None:
    compiled = _compile(_deep_graph(["reason"]))

    with pytest.raises(HarnessError) as error_info:
        run_graph_request_from_agent_compiled_graph(
            compiled,
            project_path="D:/work/project",
        )

    assert error_info.value.code == "agent_compiled_graph_not_execution_ready"


def test_execution_bridge_rejects_legacy_generated_graph() -> None:
    compiled = _execution_ready(_compile(_deep_graph(["reason"]))).model_copy(
        update={"metadata": {"generatedBy": "legacy_task_runtime"}}
    )

    with pytest.raises(HarnessError) as error_info:
        run_graph_request_from_agent_compiled_graph(
            compiled,
            project_path="D:/work/project",
        )

    assert error_info.value.code == "invalid_agent_execution_provenance"


def test_execution_bridge_builds_run_graph_request_from_agent_compiled_graph() -> None:
    source_graph = _deep_graph(["read", "reason"])
    compiled = _execution_ready(_compile(source_graph))

    request = run_graph_request_from_agent_compiled_graph(
        compiled,
        project_path="D:/work/project",
    )

    assert request.task_id == "task-1"
    assert request.run_id == "run-1"
    assert request.project_path == "D:/work/project"
    assert request.graph.graphId == source_graph.graphId
    assert request.graph.metadata == compiled.metadata
    assert request.graph.edges == compiled.edges
    assert [node.nodeId for node in request.graph.nodes] == ["read", "reason"]
    assert request.graph.nodes == [
        execution_node.public_node
        for execution_node in compiled.execution_graph.nodes
    ]


def test_execution_bridge_rejects_compiled_node_without_plan_step_provenance() -> None:
    compiled = _execution_ready(_compile(_deep_graph(["reason"])))
    broken_node = compiled.nodes[0].model_copy(update={"source_plan_step_id": ""})
    compiled = compiled.model_copy(update={"nodes": [broken_node]})

    with pytest.raises(HarnessError) as error_info:
        run_graph_request_from_agent_compiled_graph(
            compiled,
            project_path="D:/work/project",
        )

    assert error_info.value.code == "missing_agent_execution_provenance"


def test_execution_summary_marks_completed_and_collects_runtime_outputs() -> None:
    compiled = _execution_ready(_compile(_deep_graph(["read", "reason"])))
    events = [
        _event(
            "runtime.checkpoint_recorded",
            {"checkpoint": {"checkpointId": "checkpoint-1"}},
        ),
        _event("checkpoint_recorded", {"checkpointId": "checkpoint-2"}),
        _event(
            "node.completed",
            {"nodeId": "read", "artifactRefs": ["artifacts/read.md"]},
        ),
        _event("artifact.created", {"path": "artifacts/final.pdf"}),
        _event("node.completed", {"nodeId": "reason"}),
        _event("task.completed", {"message": "Execution complete."}),
    ]

    result = summarize_agent_execution_events(compiled, events)

    assert result.status == "completed"
    assert result.task_id == "task-1"
    assert result.run_id == "run-1"
    assert result.thread_id == "thread-1"
    assert result.compile_id == compiled.compile_id
    assert result.graph_id == compiled.source_graph_id
    assert result.completed_node_ids == ["read", "reason"]
    assert result.checkpoint_ids == ["checkpoint-1", "checkpoint-2"]
    assert result.artifact_refs == ["artifacts/read.md", "artifacts/final.pdf"]
    assert result.final_message == "Execution complete."
    assert result.raw_events == events


def test_execution_summary_marks_interrupted_for_permission_events() -> None:
    compiled = _execution_ready(_compile(_deep_graph(["read"])))
    events = [
        _event("node.needs_permission", {"nodeId": "read"}),
        _event(
            "task.failed",
            {"errorCode": "permission_required", "message": "Approval required."},
        ),
    ]

    result = summarize_agent_execution_events(compiled, events)

    assert result.status == "interrupted"
    assert result.failed_node_id == "read"
    assert result.final_message is None


def test_execution_summary_preserves_permission_required_node_id() -> None:
    compiled = _execution_ready(_compile(_deep_graph(["read"])))
    events = [
        _event("permission.required", {"nodeId": "read"}),
        _event(
            "task.failed",
            {"errorCode": "permission_required", "message": "Approval required."},
        ),
    ]

    result = summarize_agent_execution_events(compiled, events)

    assert result.status == "interrupted"
    assert result.failed_node_id == "read"


def test_execution_summary_failed_terminal_dominates_completed_event() -> None:
    compiled = _execution_ready(_compile(_deep_graph(["read"])))
    events = [
        _event("task.completed", {"message": "Execution complete."}),
        _event("node.failed", {"nodeId": "read"}),
        _event("task.failed", {"errorCode": "tool_error", "message": "Tool failed."}),
    ]

    result = summarize_agent_execution_events(compiled, events)

    assert result.status == "failed"
    assert result.failed_node_id == "read"
    assert result.final_message is None


def test_execution_summary_interrupted_terminal_dominates_completed_event() -> None:
    compiled = _execution_ready(_compile(_deep_graph(["read"])))
    events = [
        _event("task.completed", {"message": "Execution complete."}),
        _event("permission.required", {"nodeId": "read"}),
        _event(
            "task.failed",
            {"errorCode": "permission_required", "message": "Approval required."},
        ),
    ]

    result = summarize_agent_execution_events(compiled, events)

    assert result.status == "interrupted"
    assert result.failed_node_id == "read"
    assert result.final_message is None


def test_execution_summary_marks_failed_and_collects_recovery_actions() -> None:
    compiled = _execution_ready(_compile(_deep_graph(["read"])))
    action = {"type": "retry", "nodeId": "read", "automatic": False}
    events = [
        _event("node.failed", {"nodeId": "read"}),
        _event("recovery.action_proposed", {"action": action}),
        _event("task.failed", {"errorCode": "tool_error", "message": "Tool failed."}),
    ]

    result = summarize_agent_execution_events(compiled, events)

    assert result.status == "failed"
    assert result.failed_node_id == "read"
    assert result.recovery_actions == [action]


def test_execution_review_approves_completed_result_with_expected_artifact() -> None:
    compiled = _execution_ready(
        _compile(
            _deep_graph(
                ["write"],
                capabilities_by_step={"write": ["document.write"]},
                expected_artifact_path="artifacts/report.md",
            )
        )
    )
    result = _completed_result(compiled, artifact_refs=["artifacts/report.md"])

    review = review_agent_execution_result(compiled, result)

    assert review.status == "approved"
    assert review.is_valid is True
    assert review.repair_required is False
    assert review.final_artifacts == ["artifacts/report.md"]
    assert review.issues == []


def test_execution_review_approves_expanded_template_expected_artifact() -> None:
    compiled = _execution_ready(
        _compile(
            _deep_graph(
                ["write"],
                capabilities_by_step={"write": ["document.write"]},
                expected_artifact_path=(
                    "artifacts/converted/{index:02d}-{attachment_stem}.md"
                ),
            )
        )
    )
    result = _completed_result(
        compiled,
        artifact_refs=["artifacts/converted/01-contract.md"],
    )

    review = review_agent_execution_result(compiled, result)

    assert review.status == "approved"
    assert review.is_valid is True
    assert review.issues == []


def test_execution_review_fails_when_template_expected_artifact_has_no_match() -> None:
    compiled = _execution_ready(
        _compile(
            _deep_graph(
                ["write"],
                capabilities_by_step={"write": ["document.write"]},
                expected_artifact_path=(
                    "artifacts/converted/{index:02d}-{attachment_stem}.md"
                ),
            )
        )
    )
    result = _completed_result(
        compiled,
        artifact_refs=["artifacts/other/01-contract.md"],
    )

    review = review_agent_execution_result(compiled, result)

    assert review.status == "failed"
    assert [issue.code for issue in review.issues] == ["missing_expected_artifact"]


def test_execution_review_requires_repair_for_recovery_suggestion() -> None:
    compiled = _execution_ready(_compile(_deep_graph(["read"])))
    result = _completed_result(compiled).model_copy(
        update={
            "status": "failed",
            "failed_node_id": "read",
            "recovery_actions": [{"type": "retry", "nodeId": "read"}],
        }
    )

    review = review_agent_execution_result(compiled, result)

    assert review.status == "needs_repair"
    assert review.is_valid is False
    assert review.repair_required is True
    assert [issue.code for issue in review.issues] == ["execution_repair_available"]


def test_execution_review_fails_when_expected_artifact_missing() -> None:
    compiled = _execution_ready(
        _compile(
            _deep_graph(
                ["write"],
                capabilities_by_step={"write": ["document.write"]},
                expected_artifact_path="artifacts/report.md",
            )
        )
    )
    result = _completed_result(compiled, artifact_refs=["artifacts/other.md"])

    review = review_agent_execution_result(compiled, result)

    assert review.status == "failed"
    assert review.is_valid is False
    assert review.repair_required is False
    assert review.final_artifacts == ["artifacts/other.md"]
    assert [issue.code for issue in review.issues] == ["missing_expected_artifact"]
    assert review.issues[0].node_id == "write"


def _completed_result(
    compiled: AgentCompiledGraph,
    *,
    artifact_refs: list[str] | None = None,
) -> AgentExecutionRunResult:
    return AgentExecutionRunResult(
        status="completed",
        task_id=compiled.task_id,
        run_id=compiled.run_id,
        thread_id=compiled.thread_id,
        compile_id=compiled.compile_id,
        graph_id=compiled.source_graph_id,
        artifact_refs=list(artifact_refs or []),
    )
