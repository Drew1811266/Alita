from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


ReasoningComplexity = Literal["simple", "bounded_tool", "graph_task"]
ReasoningNextAction = Literal[
    "simple_answer",
    "tool_action",
    "clarification",
    "deep_planning",
]
ReviewStatus = Literal["approved", "needs_clarification", "invalid"]
GraphReviewStatus = Literal["approved", "invalid"]
ThinkingFallback = Literal[
    "none",
    "unsupported_request_body",
    "empty_reasoning_response",
    "provider_error",
]
ThinkingEffectiveMode = Literal["deep", "degraded", "unavailable"]


class ReasoningDecision(BaseModel):
    task_id: str
    task_understanding: str
    intent: str
    complexity: ReasoningComplexity
    why_this_path: str
    confidence: float = Field(ge=0.0, le=1.0)
    needs_clarification: bool
    required_capabilities: list[str] = Field(default_factory=list)
    next_action: ReasoningNextAction


class ThinkingStatus(BaseModel):
    requested: bool
    model_policy: str
    request_payload_had_thinking_params: bool
    enable_thinking_sent: bool
    preserve_thinking_sent: bool
    fallback_used: ThinkingFallback = "none"
    effective_mode: ThinkingEffectiveMode
    raw_provider_status: str | None = None


class CandidateStrategy(BaseModel):
    strategy_id: str = Field(alias="strategyId")
    summary: str
    tradeoffs: list[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    step_id: str
    title: str
    objective: str
    rationale: str
    inputs: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    expected_output: str
    verification_criteria: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class PlanDraft(BaseModel):
    plan_draft_id: str
    task_understanding: str
    success_criteria: list[str]
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    candidate_strategies: list[CandidateStrategy] = Field(default_factory=list)
    recommended_strategy: str
    steps: list[PlanStep]
    required_capabilities: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    verification_plan: list[str] = Field(default_factory=list)

    @field_validator("success_criteria", "steps", "verification_plan")
    @classmethod
    def _must_not_be_empty(cls, value: list[Any]) -> list[Any]:
        if not value:
            raise ValueError("field must not be empty")
        return value


class PlanReview(BaseModel):
    status: ReviewStatus
    coverage_findings: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    unsupported_capabilities: list[str] = Field(default_factory=list)
    risk_findings: list[str] = Field(default_factory=list)
    suggested_clarifying_question: str | None = None
    revision_instructions: list[str] = Field(default_factory=list)


class GraphReview(BaseModel):
    status: GraphReviewStatus
    findings: list[str] = Field(default_factory=list)
    missing_plan_step_ids: list[str] = Field(default_factory=list)
    extra_node_ids: list[str] = Field(default_factory=list)
