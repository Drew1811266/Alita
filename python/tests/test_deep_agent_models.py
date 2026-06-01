import pytest
from pydantic import ValidationError

from agent_service.deep_agent_models import (
    GraphReview,
    PlanDraft,
    PlanReview,
    PlanStep,
    ReasoningDecision,
    ThinkingStatus,
)


def test_reasoning_decision_requires_explanation_and_next_action() -> None:
    decision = ReasoningDecision(
        task_id="task-1",
        task_understanding="User wants a contract risk report.",
        intent="task",
        complexity="graph_task",
        why_this_path="The request requires reading an attachment and producing a report.",
        confidence=0.91,
        needs_clarification=False,
        required_capabilities=["document.read", "model.reasoning"],
        next_action="deep_planning",
    )

    assert decision.next_action == "deep_planning"
    assert decision.required_capabilities == ["document.read", "model.reasoning"]


def test_plan_draft_requires_steps_and_success_criteria() -> None:
    draft = PlanDraft(
        plan_draft_id="plan-1",
        task_understanding="Analyze contract risk.",
        success_criteria=["Risks are grouped by severity.", "Final report has actions."],
        inputs=[{"kind": "attachment", "name": "contract.docx"}],
        assumptions=["The attached document is the contract to review."],
        missing_information=[],
        candidate_strategies=[
            {
                "strategyId": "strategy-risk-review",
                "summary": "Extract clauses, identify risks, and write a report.",
                "tradeoffs": ["Focused on legal/business risk, not legal advice."],
            }
        ],
        recommended_strategy="strategy-risk-review",
        steps=[
            PlanStep(
                step_id="step-read",
                title="Read contract",
                objective="Extract readable text from the uploaded contract.",
                rationale="Risk review requires clause-level text.",
                inputs=["contract.docx"],
                required_capabilities=["document.read"],
                expected_output="Normalized contract text.",
                verification_criteria=["Text output is non-empty."],
                depends_on=[],
            )
        ],
        required_capabilities=["document.read", "model.reasoning"],
        risks=["The contract may be scanned or unreadable."],
        verification_plan=["Confirm every risk cites a source clause."],
    )

    assert draft.steps[0].step_id == "step-read"
    assert draft.success_criteria[0] == "Risks are grouped by severity."


def test_plan_draft_rejects_empty_steps() -> None:
    with pytest.raises(ValidationError):
        PlanDraft(
            plan_draft_id="plan-empty",
            task_understanding="Analyze a document.",
            success_criteria=["Report exists."],
            inputs=[],
            assumptions=[],
            missing_information=[],
            candidate_strategies=[],
            recommended_strategy="",
            steps=[],
            required_capabilities=[],
            risks=[],
            verification_plan=[],
        )


def test_thinking_status_records_degraded_mode() -> None:
    status = ThinkingStatus(
        requested=True,
        model_policy="deep_reasoning",
        request_payload_had_thinking_params=True,
        enable_thinking_sent=True,
        preserve_thinking_sent=True,
        fallback_used="unsupported_request_body",
        effective_mode="degraded",
        raw_provider_status="HTTP 422",
    )

    assert status.effective_mode == "degraded"
    assert status.fallback_used == "unsupported_request_body"


def test_reviews_have_status_values() -> None:
    plan_review = PlanReview(
        status="approved",
        coverage_findings=[],
        missing_inputs=[],
        unsupported_capabilities=[],
        risk_findings=[],
        suggested_clarifying_question=None,
        revision_instructions=[],
    )
    graph_review = GraphReview(
        status="approved",
        findings=[],
        missing_plan_step_ids=[],
        extra_node_ids=[],
    )

    assert plan_review.status == "approved"
    assert graph_review.status == "approved"
