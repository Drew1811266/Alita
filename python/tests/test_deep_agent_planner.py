from __future__ import annotations

import json
from typing import Any

import pytest

from agent_service.deep_agent_models import PlanDraft
from agent_service.deep_agent_planner import (
    DeepPlanningEngine,
    DeepPlanningError,
    ReasoningGateEngine,
    review_plan,
)
from agent_service.model_client import (
    ChatDiagnosticsResponse,
    ChatMessage,
    ModelCallDiagnostics,
    ModelRuntimeDisabled,
    ModelRuntimeRequestFailed,
)
from agent_service.model_policy import DEEP_REASONING_POLICY, ModelCallPolicy, ModelCallProfile


class FakeDeepModel:
    def __init__(
        self,
        *,
        raw_content: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.raw_content = raw_content or json.dumps(_plan_payload())
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def chat_with_diagnostics(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        policy: ModelCallPolicy | None = None,
    ) -> ChatDiagnosticsResponse:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "policy": policy,
            }
        )
        if self.error is not None:
            raise self.error
        return ChatDiagnosticsResponse(
            content=self.raw_content,
            diagnostics=ModelCallDiagnostics(
                request_payload_had_thinking_params=True,
                enable_thinking_sent=True,
                preserve_thinking_sent=True,
                enable_thinking_value=True,
                preserve_thinking_value=True,
                fallback_used="none",
                effective_mode="deep",
                raw_provider_status="native-thinking-enabled",
            ),
        )


def _plan_payload() -> dict[str, Any]:
    return {
        "plan_draft_id": "plan-contract-risk",
        "task_understanding": "Review the supplied contract and produce a risk report.",
        "success_criteria": [
            "Every material contract risk is grouped by severity.",
            "Each recommendation is actionable and tied to the contract text.",
        ],
        "inputs": [{"kind": "attachment", "name": "contract.pdf"}],
        "assumptions": ["The attached PDF is the contract to review."],
        "missing_information": [],
        "candidate_strategies": [
            {
                "strategyId": "strategy-risk-review",
                "summary": "Extract clauses, identify risks, and synthesize a report.",
                "tradeoffs": ["Prioritizes coverage over speed."],
            }
        ],
        "recommended_strategy": "strategy-risk-review",
        "steps": [
            {
                "step_id": "step-extract",
                "title": "Extract contract text",
                "objective": "Read the supplied contract and normalize its clause text.",
                "rationale": "Risk analysis needs reliable clause-level source text.",
                "inputs": ["contract.pdf"],
                "required_capabilities": ["document.read"],
                "expected_output": "Normalized contract text grouped by section.",
                "verification_criteria": ["Extracted text is non-empty and sectioned."],
                "depends_on": [],
            },
            {
                "step_id": "step-report",
                "title": "Write risk report",
                "objective": "Identify contract risks and write an actionable report.",
                "rationale": "The user asked for a risk review, not just extraction.",
                "inputs": ["Normalized contract text grouped by section."],
                "required_capabilities": ["model.reasoning"],
                "expected_output": "Contract risk report with severities and actions.",
                "verification_criteria": ["Every risk cites or references source text."],
                "depends_on": ["step-extract"],
            },
        ],
        "required_capabilities": ["document.read", "model.reasoning"],
        "risks": ["The PDF may contain scanned pages."],
        "verification_plan": ["Confirm the final report maps risks to source clauses."],
    }


def _decision_payload() -> dict[str, Any]:
    return {
        "task_id": "task-1",
        "task_understanding": "User wants a contract risk report.",
        "intent": "task",
        "complexity": "graph_task",
        "why_this_path": "The request requires attachment analysis and a multi-step report.",
        "confidence": 0.92,
        "needs_clarification": False,
        "required_capabilities": ["document.read", "model.reasoning"],
        "next_action": "deep_planning",
    }


def _context_bundle() -> dict[str, Any]:
    return {
        "taskId": "task-1",
        "attachments": [
            {
                "id": "att-1",
                "name": "contract.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 12345,
                "path": "D:\\secret\\contract.pdf",
            }
        ],
        "conversation": [{"role": "user", "content": "Review this contract."}],
    }


def test_deep_planning_engine_calls_model_with_deep_reasoning_policy() -> None:
    model = FakeDeepModel()
    result = DeepPlanningEngine(model).plan(
        "Review this contract.",
        context_bundle=_context_bundle(),
    )

    assert result.plan_draft.plan_draft_id == "plan-contract-risk"
    assert len(model.calls) == 1
    assert model.calls[0]["policy"].profile == ModelCallProfile.DEEP_REASONING
    assert model.calls[0]["policy"] == DEEP_REASONING_POLICY
    assert result.thinking_status.effective_mode == "deep"
    assert result.thinking_status.enforced is True
    prompt = model.calls[0]["messages"][1].content
    assert "D:\\secret\\contract.pdf" not in prompt
    assert "contract.pdf" in prompt


def test_reasoning_gate_engine_calls_model_and_parses_decision() -> None:
    model = FakeDeepModel(raw_content=json.dumps(_decision_payload()))
    decision = ReasoningGateEngine(model).decide(
        "Review this contract.",
        context_bundle=_context_bundle(),
    )

    assert decision.next_action == "deep_planning"
    assert decision.task_id == "task-1"
    assert len(model.calls) == 1
    assert model.calls[0]["policy"] == DEEP_REASONING_POLICY


def test_deep_planning_engine_rejects_invalid_json_without_template_fallback() -> None:
    model = FakeDeepModel(raw_content="{not json")

    with pytest.raises(DeepPlanningError) as error:
        DeepPlanningEngine(model).plan("Review this contract.", context_bundle=_context_bundle())

    assert error.value.code == "invalid_plan_json"
    assert len(model.calls) == 1


def test_reasoning_gate_rejects_invalid_json() -> None:
    model = FakeDeepModel(raw_content="{not json")

    with pytest.raises(DeepPlanningError) as error:
        ReasoningGateEngine(model).decide("Review this contract.", context_bundle=_context_bundle())

    assert error.value.code == "invalid_reasoning_json"
    assert len(model.calls) == 1


@pytest.mark.parametrize(
    "runtime_error",
    [
        ModelRuntimeRequestFailed("network failure"),
        ModelRuntimeDisabled("disabled"),
    ],
)
def test_deep_planning_engine_reports_unavailable_model(runtime_error: Exception) -> None:
    model = FakeDeepModel(error=runtime_error)

    with pytest.raises(DeepPlanningError) as error:
        DeepPlanningEngine(model).plan("Review this contract.", context_bundle=_context_bundle())

    assert error.value.code == "deep_planning_unavailable"


def test_review_plan_blocks_missing_success_criteria() -> None:
    draft = PlanDraft.model_construct(
        **{
            **_plan_payload(),
            "success_criteria": [],
            "steps": PlanDraft.model_validate(_plan_payload()).steps,
        }
    )

    review = review_plan(
        draft,
        available_capabilities={"document.read", "model.reasoning"},
    )

    assert review.status == "invalid"
    assert "missing_success_criteria" in review.coverage_findings
    assert review.revision_instructions


def test_review_plan_requests_clarification_for_declared_missing_information() -> None:
    draft = PlanDraft.model_validate(
        {
            **_plan_payload(),
            "missing_information": ["Which jurisdiction should govern the legal review?"],
        }
    )

    review = review_plan(
        draft,
        available_capabilities={"document.read", "model.reasoning"},
    )

    assert review.status == "needs_clarification"
    assert review.missing_inputs == ["Which jurisdiction should govern the legal review?"]
    assert "Which jurisdiction" in review.suggested_clarifying_question


def test_review_plan_blocks_step_unsupported_capability() -> None:
    payload = _plan_payload()
    payload["steps"][1]["required_capabilities"] = ["legal.database"]
    draft = PlanDraft.model_validate(payload)

    review = review_plan(
        draft,
        available_capabilities={"document.read", "model.reasoning"},
    )

    assert review.status == "invalid"
    assert "legal.database" in review.unsupported_capabilities
    assert "unsupported_capability:legal.database" in review.coverage_findings


def test_revision_instructions_appear_in_planning_prompt_and_local_path_is_scrubbed() -> None:
    model = FakeDeepModel()
    DeepPlanningEngine(model).plan(
        "Review this contract.",
        context_bundle=_context_bundle(),
        revision_instructions=["Add a verification step for citations."],
    )

    prompt = model.calls[0]["messages"][1].content
    assert "Add a verification step for citations." in prompt
    assert "D:\\secret\\contract.pdf" not in prompt
