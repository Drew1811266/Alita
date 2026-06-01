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


def _valid_plan_step() -> PlanStep:
    return PlanStep(
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


def _valid_plan_draft_kwargs() -> dict:
    return {
        "plan_draft_id": "plan-1",
        "task_understanding": "Analyze contract risk.",
        "success_criteria": [
            "Risks are grouped by severity.",
            "Final report has actions.",
        ],
        "inputs": [{"kind": "attachment", "name": "contract.docx"}],
        "assumptions": ["The attached document is the contract to review."],
        "missing_information": [],
        "candidate_strategies": [
            {
                "strategyId": "strategy-risk-review",
                "summary": "Extract clauses, identify risks, and write a report.",
                "tradeoffs": ["Focused on legal/business risk, not legal advice."],
            }
        ],
        "recommended_strategy": "strategy-risk-review",
        "steps": [_valid_plan_step()],
        "required_capabilities": ["document.read", "model.reasoning"],
        "risks": ["The contract may be scanned or unreadable."],
        "verification_plan": ["Confirm every risk cites a source clause."],
    }


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
    draft = PlanDraft(**_valid_plan_draft_kwargs())

    assert draft.steps[0].step_id == "step-read"
    assert draft.success_criteria[0] == "Risks are grouped by severity."


def test_plan_draft_rejects_empty_steps() -> None:
    with pytest.raises(ValidationError):
        PlanDraft(**{**_valid_plan_draft_kwargs(), "steps": []})


def test_plan_draft_rejects_empty_success_criteria() -> None:
    with pytest.raises(ValidationError):
        PlanDraft(**{**_valid_plan_draft_kwargs(), "success_criteria": []})


def test_plan_draft_rejects_empty_verification_plan() -> None:
    with pytest.raises(ValidationError):
        PlanDraft(**{**_valid_plan_draft_kwargs(), "verification_plan": []})


def test_thinking_status_records_degraded_mode() -> None:
    status = ThinkingStatus(
        requested=True,
        model_policy="deep_reasoning",
        request_payload_had_thinking_params=True,
        enable_thinking_sent=True,
        preserve_thinking_sent=True,
        enforced=True,
        fallback_used="unsupported_request_body",
        effective_mode="degraded",
        raw_provider_status="HTTP 422",
    )

    assert status.enforced is True
    assert status.effective_mode == "degraded"
    assert status.fallback_used == "unsupported_request_body"


def test_reviews_have_status_values() -> None:
    plan_review = PlanReview(
        status="approved",
        findings=[],
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


def test_plan_review_accepts_clarification_with_findings() -> None:
    review = PlanReview(
        status="clarification",
        findings=["The plan cannot proceed without the source document."],
        missing_inputs=["contract.docx"],
        unsupported_capabilities=[],
        risk_findings=[],
        suggested_clarifying_question="Please upload the contract to review.",
        revision_instructions=[],
    )

    assert review.status == "clarification"
    assert review.findings == ["The plan cannot proceed without the source document."]
    assert review.suggested_clarifying_question == "Please upload the contract to review."


def test_plan_review_rejects_old_needs_clarification_status() -> None:
    with pytest.raises(ValidationError):
        PlanReview(
            status="needs_clarification",
            findings=["Use the Phase 1 clarification status instead."],
            missing_inputs=[],
            unsupported_capabilities=[],
            risk_findings=[],
            suggested_clarifying_question=None,
            revision_instructions=[],
        )
