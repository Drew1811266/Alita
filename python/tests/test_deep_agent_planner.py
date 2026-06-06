from __future__ import annotations

import json
from typing import Any

import pytest

from agent_service.deep_agent_models import PlanDraft
from agent_service.deep_agent_planner import (
    DeepPlanningEngine,
    DeepPlanningError,
    ReasoningGateEngine,
    _planning_prompt,
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
from agent_service.schemas import Attachment, UserMessage


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
        "taskId": "context-task-should-not-drive-prompt",
        "attachments": [
            {
                "id": "context-att-1",
                "name": "context-contract.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 999,
                "path": "D:\\context-secret\\context-contract.pdf",
            }
        ],
        "notes": [
            {"note": "see D:\\secret\\file.pdf before planning"},
            {"source": "/Users/drew/private/file.pdf"},
            {"hint": "inspect D:\\Software Project\\Alita\\secret.txt next"},
            {"workspace": "open D:\\Software Project\\Alita\\secret folder"},
            {"directory": "read /Users/drew/private/secret folder"},
        ],
        "conversation": [{"role": "user", "content": "Review this contract."}],
    }


def _message(
    *,
    content: str = "Review this contract.",
    attachment_name: str = "contract.pdf",
) -> UserMessage:
    return UserMessage(
        task_id="task-1",
        content=content,
        attachments=[
            Attachment(
                attachment_id="att-1",
                name=attachment_name,
                path="D:\\secret\\contract.pdf",
                size_bytes=12345,
                mime_type="application/pdf",
            )
        ],
    )


def test_deep_planning_engine_calls_model_with_deep_reasoning_policy() -> None:
    model = FakeDeepModel()
    result = DeepPlanningEngine(model).plan(
        _message(),
        context_bundle=_context_bundle(),
    )

    assert result.plan_draft.plan_draft_id == "plan-contract-risk"
    assert len(model.calls) == 1
    assert model.calls[0]["policy"].profile == ModelCallProfile.DEEP_REASONING
    assert model.calls[0]["policy"] == DEEP_REASONING_POLICY
    assert result.thinking_status.effective_mode == "deep"
    assert result.thinking_status.enforced is True
    prompt = model.calls[0]["messages"][1].content
    prompt_payload = json.loads(prompt)
    assert "D:\\secret\\contract.pdf" not in prompt
    assert "D:\\context-secret\\context-contract.pdf" not in prompt
    assert "contract.pdf" in prompt
    assert prompt_payload["taskId"] == "task-1"
    assert prompt_payload["attachment_summaries"] == [
        {
            "attachment_id": "att-1",
            "name": "contract.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 12345,
        }
    ]


def test_reasoning_gate_engine_calls_model_and_parses_decision() -> None:
    model = FakeDeepModel(raw_content=json.dumps(_decision_payload()))
    decision = ReasoningGateEngine(model).decide(
        _message(),
        context_bundle=_context_bundle(),
    )

    assert decision.next_action == "deep_planning"
    assert decision.task_id == "task-1"
    assert len(model.calls) == 1
    assert model.calls[0]["policy"] == DEEP_REASONING_POLICY


def test_planning_prompt_scrubs_local_path_from_user_message_content() -> None:
    model = FakeDeepModel()
    message = _message(content="Review D:\\Software Project\\Alita\\case.pdf.")

    DeepPlanningEngine(model).plan(message, context_bundle=_context_bundle())

    prompt = model.calls[0]["messages"][1].content
    prompt_payload = json.loads(prompt)
    assert "D:\\Software Project\\Alita\\case.pdf" not in prompt
    assert "Software Project" not in prompt
    assert "Alita\\case.pdf" not in prompt
    assert prompt_payload["user_message"] == "Review [local_path_removed]."


def test_reasoning_prompt_scrubs_local_path_from_user_message_content() -> None:
    model = FakeDeepModel(raw_content=json.dumps(_decision_payload()))
    message = _message(content="Review D:\\Software Project\\Alita\\case.pdf.")

    ReasoningGateEngine(model).decide(message, context_bundle=_context_bundle())

    prompt = model.calls[0]["messages"][1].content
    prompt_payload = json.loads(prompt)
    assert "D:\\Software Project\\Alita\\case.pdf" not in prompt
    assert "Software Project" not in prompt
    assert "Alita\\case.pdf" not in prompt
    assert prompt_payload["user_message"] == "Review [local_path_removed]."


def test_planning_prompt_scrubs_common_local_path_forms_from_user_message_content() -> None:
    model = FakeDeepModel()
    message = _message(
        content=(
            "Review C:/Users/Drew/file.pdf, ~/private/file.pdf, /tmp/file.pdf, "
            "and \\\\server\\share\\file.pdf."
        )
    )

    DeepPlanningEngine(model).plan(message, context_bundle=_context_bundle())

    prompt = model.calls[0]["messages"][1].content
    assert "[local_path_removed]" in prompt
    assert "C:/Users" not in prompt
    assert "/tmp/file.pdf" not in prompt
    assert "~/private" not in prompt
    assert "\\\\server" not in prompt
    assert "share\\file.pdf" not in prompt


def test_planning_prompt_scrubs_local_path_from_revision_instructions() -> None:
    model = FakeDeepModel()

    DeepPlanningEngine(model).plan(
        _message(),
        context_bundle=_context_bundle(),
        revision_instructions=[
            "Revise using D:\\Software Project\\Alita\\case.pdf.",
        ],
    )

    prompt = model.calls[0]["messages"][1].content
    prompt_payload = json.loads(prompt)
    assert "D:\\Software Project\\Alita\\case.pdf" not in prompt
    assert "Software Project" not in prompt
    assert "Alita\\case.pdf" not in prompt
    assert prompt_payload["revision_instructions"] == [
        "Revise using [local_path_removed].",
    ]


def test_prompt_scrubs_local_path_from_attachment_name() -> None:
    model = FakeDeepModel()
    message = _message(attachment_name="D:\\Software Project\\Alita\\case.pdf")

    DeepPlanningEngine(model).plan(message, context_bundle=_context_bundle())

    prompt = model.calls[0]["messages"][1].content
    prompt_payload = json.loads(prompt)
    assert "D:\\Software Project\\Alita\\case.pdf" not in prompt
    assert "Software Project" not in prompt
    assert "Alita\\case.pdf" not in prompt
    assert prompt_payload["attachment_summaries"][0]["name"] == "[local_path_removed]"


def test_planning_prompt_scrubs_common_local_path_forms_from_nested_context() -> None:
    model = FakeDeepModel()
    context_bundle = {
        **_context_bundle(),
        "notes": [
            {"source": "open C:/Users/Drew/file.pdf"},
            {"source": "open ~/private/file.pdf"},
            {"source": "open /tmp/file.pdf"},
            {"source": "open \\\\server\\share\\file.pdf"},
        ],
    }

    DeepPlanningEngine(model).plan(_message(), context_bundle=context_bundle)

    prompt = model.calls[0]["messages"][1].content
    assert "[local_path_removed]" in prompt
    assert "C:/Users" not in prompt
    assert "/tmp/file.pdf" not in prompt
    assert "~/private" not in prompt
    assert "\\\\server" not in prompt
    assert "share\\file.pdf" not in prompt


def test_planning_prompt_scrubs_local_path_strings_under_non_path_keys() -> None:
    model = FakeDeepModel()
    DeepPlanningEngine(model).plan(_message(), context_bundle=_context_bundle())

    prompt = model.calls[0]["messages"][1].content
    prompt_payload = json.loads(prompt)
    assert "D:\\secret\\file.pdf" not in prompt
    assert "/Users/drew/private/file.pdf" not in prompt
    assert "D:\\Software Project\\Alita\\secret.txt" not in prompt
    assert "D:\\Software Project\\Alita\\secret folder" not in prompt
    assert "/Users/drew/private/secret folder" not in prompt
    assert "Software Project" not in prompt
    assert "Alita\\secret.txt" not in prompt
    assert "Alita\\secret folder" not in prompt
    assert "/Users/drew" not in prompt
    assert "private/secret folder" not in prompt
    assert "[local_path_removed]" in prompt
    assert prompt_payload["context_bundle"]["notes"] == [
        {"note": "see [local_path_removed] before planning"},
        {"source": "[local_path_removed]"},
        {"hint": "inspect [local_path_removed] next"},
        {"workspace": "open [local_path_removed]"},
        {"directory": "read [local_path_removed]"},
    ]


def test_reasoning_prompt_scrubs_local_path_strings_under_non_path_keys() -> None:
    model = FakeDeepModel(raw_content=json.dumps(_decision_payload()))
    ReasoningGateEngine(model).decide(_message(), context_bundle=_context_bundle())

    prompt = model.calls[0]["messages"][1].content
    prompt_payload = json.loads(prompt)
    assert "D:\\secret\\file.pdf" not in prompt
    assert "/Users/drew/private/file.pdf" not in prompt
    assert "D:\\Software Project\\Alita\\secret.txt" not in prompt
    assert "D:\\Software Project\\Alita\\secret folder" not in prompt
    assert "/Users/drew/private/secret folder" not in prompt
    assert "Software Project" not in prompt
    assert "Alita\\secret.txt" not in prompt
    assert "Alita\\secret folder" not in prompt
    assert "/Users/drew" not in prompt
    assert "private/secret folder" not in prompt
    assert "[local_path_removed]" in prompt
    assert prompt_payload["context_bundle"]["notes"] == [
        {"note": "see [local_path_removed] before planning"},
        {"source": "[local_path_removed]"},
        {"hint": "inspect [local_path_removed] next"},
        {"workspace": "open [local_path_removed]"},
        {"directory": "read [local_path_removed]"},
    ]


def test_deep_planning_engine_rejects_invalid_json_without_template_fallback() -> None:
    model = FakeDeepModel(raw_content="{not json")

    with pytest.raises(DeepPlanningError) as error:
        DeepPlanningEngine(model).plan(_message(), context_bundle=_context_bundle())

    assert error.value.code == "invalid_plan_json"
    assert len(model.calls) == 1


def test_reasoning_gate_rejects_invalid_json() -> None:
    model = FakeDeepModel(raw_content="{not json")

    with pytest.raises(DeepPlanningError) as error:
        ReasoningGateEngine(model).decide(_message(), context_bundle=_context_bundle())

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
        DeepPlanningEngine(model).plan(_message(), context_bundle=_context_bundle())

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


def test_review_plan_blocks_missing_verification_plan() -> None:
    draft = PlanDraft.model_construct(
        **{
            **_plan_payload(),
            "steps": PlanDraft.model_validate(_plan_payload()).steps,
            "verification_plan": [],
        }
    )

    review = review_plan(
        draft,
        available_capabilities={"document.read", "model.reasoning"},
    )

    assert review.status == "invalid"
    assert "missing_verification_plan" in review.coverage_findings
    assert "verification plan" in " ".join(review.findings).lower()
    assert "verification plan" in " ".join(review.revision_instructions).lower()


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


def test_review_plan_blocks_jointly_unsatisfied_step_capability_set() -> None:
    payload = _plan_payload()
    payload["steps"][0]["required_capabilities"] = [
        "document.convert.markdown",
        "document.render.typst_pdf",
    ]
    payload["required_capabilities"] = [
        "document.convert.markdown",
        "document.render.typst_pdf",
        "model.reasoning",
    ]
    draft = PlanDraft.model_validate(payload)

    review = review_plan(
        draft,
        available_capabilities={
            "document.convert.markdown",
            "document.render.typst_pdf",
            "model.reasoning",
        },
    )

    assert review.status == "invalid"
    assert review.unsupported_capabilities == [
        "document.convert.markdown",
        "document.render.typst_pdf",
    ]
    assert (
        "unsupported_capability_set:step-extract:"
        "document.convert.markdown,document.render.typst_pdf"
    ) in review.coverage_findings


def test_review_plan_approves_catalog_available_output_capability() -> None:
    payload = _plan_payload()
    payload["steps"] = [
        {
            "step_id": "step-respond",
            "title": "Return final answer",
            "objective": "Return the final response to the user.",
            "rationale": "The requested deliverable is a final response.",
            "inputs": ["report"],
            "required_capabilities": ["output.final_response"],
            "expected_output": "Final response delivered to the user.",
            "verification_criteria": ["The response satisfies the request."],
            "depends_on": [],
        }
    ]
    payload["required_capabilities"] = ["output.final_response"]
    draft = PlanDraft.model_validate(payload)

    review = review_plan(
        draft,
        available_capabilities=set(),
    )

    assert review.status == "approved"
    assert review.unsupported_capabilities == []


def test_revision_instructions_appear_in_planning_prompt_and_local_path_is_scrubbed() -> None:
    model = FakeDeepModel()
    DeepPlanningEngine(model).plan(
        _message(),
        context_bundle=_context_bundle(),
        revision_instructions=["Add a verification step for citations."],
    )

    prompt = model.calls[0]["messages"][1].content
    assert "Add a verification step for citations." in prompt
    assert "D:\\secret\\contract.pdf" not in prompt
    assert "D:\\context-secret\\context-contract.pdf" not in prompt


def test_planning_prompt_includes_all_revision_instructions() -> None:
    prompt = _planning_prompt(
        _message(),
        context_bundle=_context_bundle(),
        revision_instructions=[
            "Add verification criteria for step analyze.",
            "Add a verification plan for the full plan.",
            "Revise the plan to use only available capabilities or request support.",
        ],
    )

    prompt_payload = json.loads(prompt)
    assert prompt_payload["revision_instructions"] == [
        "Add verification criteria for step analyze.",
        "Add a verification plan for the full plan.",
        "Revise the plan to use only available capabilities or request support.",
    ]
