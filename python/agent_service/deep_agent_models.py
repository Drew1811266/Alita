from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DeepAgentBaseModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


ReasoningComplexity = Literal["simple", "bounded_tool", "graph_task"]
ReasoningNextAction = Literal[
    "simple_answer",
    "tool_action",
    "clarification",
    "deep_planning",
]
ReviewStatus = Literal["approved", "clarification", "invalid"]
GraphReviewStatus = Literal["approved", "invalid"]
ThinkingFallback = Literal[
    "none",
    "unsupported_request_body",
    "empty_reasoning_response",
    "provider_error",
]
ThinkingEffectiveMode = Literal["deep", "degraded", "unavailable"]


class ReasoningDecision(DeepAgentBaseModel):
    task_id: NonEmptyStr
    task_understanding: NonEmptyStr
    intent: NonEmptyStr
    complexity: ReasoningComplexity
    why_this_path: NonEmptyStr
    confidence: float = Field(ge=0.0, le=1.0)
    needs_clarification: bool
    required_capabilities: list[NonEmptyStr] = Field(default_factory=list)
    next_action: ReasoningNextAction


class ThinkingStatus(DeepAgentBaseModel):
    requested: bool
    model_policy: NonEmptyStr
    request_payload_had_thinking_params: bool
    enable_thinking_sent: bool
    preserve_thinking_sent: bool
    enforced: bool
    fallback_used: ThinkingFallback = "none"
    effective_mode: ThinkingEffectiveMode
    raw_provider_status: NonEmptyStr | None = None


class CandidateStrategy(DeepAgentBaseModel):
    strategy_id: NonEmptyStr = Field(alias="strategyId")
    summary: NonEmptyStr
    tradeoffs: list[NonEmptyStr] = Field(default_factory=list)


class PlanStep(DeepAgentBaseModel):
    step_id: NonEmptyStr
    title: NonEmptyStr
    objective: NonEmptyStr
    rationale: NonEmptyStr
    inputs: list[NonEmptyStr] = Field(default_factory=list)
    required_capabilities: list[NonEmptyStr] = Field(default_factory=list)
    expected_output: NonEmptyStr
    verification_criteria: list[NonEmptyStr] = Field(default_factory=list)
    depends_on: list[NonEmptyStr] = Field(default_factory=list)


class PlanDraft(DeepAgentBaseModel):
    plan_draft_id: NonEmptyStr
    task_understanding: NonEmptyStr
    success_criteria: list[NonEmptyStr]
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[NonEmptyStr] = Field(default_factory=list)
    missing_information: list[NonEmptyStr] = Field(default_factory=list)
    candidate_strategies: list[CandidateStrategy] = Field(default_factory=list)
    recommended_strategy: NonEmptyStr
    steps: list[PlanStep]
    required_capabilities: list[NonEmptyStr] = Field(default_factory=list)
    risks: list[NonEmptyStr] = Field(default_factory=list)
    verification_plan: list[NonEmptyStr] = Field(default_factory=list)

    @field_validator("success_criteria", "steps", "verification_plan")
    @classmethod
    def _must_not_be_empty(cls, value: list[Any]) -> list[Any]:
        if not value:
            raise ValueError("field must not be empty")
        return value

    @model_validator(mode="after")
    def _validate_plan_graph(self) -> PlanDraft:
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step_id values must be unique")

        known_step_ids = set(step_ids)
        missing_dependencies = [
            dependency_id
            for step in self.steps
            for dependency_id in step.depends_on
            if dependency_id not in known_step_ids
        ]
        if missing_dependencies:
            raise ValueError("depends_on ids must reference existing steps")

        strategy_ids = {strategy.strategy_id for strategy in self.candidate_strategies}
        if self.recommended_strategy not in strategy_ids:
            raise ValueError("recommended_strategy must reference a candidate strategy")

        return self


class PlanReview(DeepAgentBaseModel):
    status: ReviewStatus
    findings: list[NonEmptyStr] = Field(default_factory=list)
    coverage_findings: list[NonEmptyStr] = Field(default_factory=list)
    missing_inputs: list[NonEmptyStr] = Field(default_factory=list)
    unsupported_capabilities: list[NonEmptyStr] = Field(default_factory=list)
    risk_findings: list[NonEmptyStr] = Field(default_factory=list)
    suggested_clarifying_question: NonEmptyStr | None = None
    revision_instructions: list[NonEmptyStr] = Field(default_factory=list)


class GraphReview(DeepAgentBaseModel):
    status: GraphReviewStatus
    findings: list[NonEmptyStr] = Field(default_factory=list)
    missing_plan_step_ids: list[NonEmptyStr] = Field(default_factory=list)
    extra_node_ids: list[NonEmptyStr] = Field(default_factory=list)
