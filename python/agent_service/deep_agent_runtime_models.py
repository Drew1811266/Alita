from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_service.schemas import AgentEvent


class DeepAgentRuntimeBaseModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


PlanningResumeKind = Literal["clarification_answer", "confirmation"]
PlanningConfirmationDecision = Literal["approve", "revise", "cancel"]


class PlanningResumeCommand(DeepAgentRuntimeBaseModel):
    kind: PlanningResumeKind
    thread_id: str = Field(alias="threadId")
    run_id: str | None = Field(default=None, alias="runId")
    answer: str | None = None
    decision: PlanningConfirmationDecision | None = None
    revision_instructions: list[str] = Field(
        default_factory=list,
        alias="revisionInstructions",
    )

    @model_validator(mode="after")
    def _validate_resume_command(self) -> "PlanningResumeCommand":
        if self.kind == "clarification_answer":
            if not self.answer:
                raise ValueError("clarification_answer requires answer")
            if self.decision is not None:
                raise ValueError("clarification_answer cannot include decision")
            if self.revision_instructions:
                raise ValueError(
                    "clarification_answer does not accept revision_instructions"
                )
            return self

        if self.kind == "confirmation":
            if self.answer is not None:
                raise ValueError("confirmation cannot include answer")
            if self.decision is None:
                raise ValueError("confirmation requires decision")
            if (
                self.decision in {"approve", "cancel"}
                and self.revision_instructions
            ):
                raise ValueError(
                    "approval or cancellation cannot include revision_instructions"
                )
            return self

        return self


class DeepAgentRunResult(DeepAgentRuntimeBaseModel):
    events: list[AgentEvent]
    run_id: str = Field(alias="runId")
    thread_id: str = Field(alias="threadId")
    latest_checkpoint_id: str | None = Field(default=None, alias="latestCheckpointId")
    interrupted: bool = False
    interrupt_payload: dict[str, Any] | None = Field(default=None, alias="interruptPayload")


class PlanningCheckpointSummary(DeepAgentRuntimeBaseModel):
    run_id: str = Field(alias="runId")
    thread_id: str = Field(alias="threadId")
    checkpoint_id: str = Field(alias="checkpointId")
    stage: str
    node: str | None = None
    revision_count: int = Field(default=0, alias="revisionCount")
    has_plan_draft: bool = Field(default=False, alias="hasPlanDraft")
    has_compiled_graph: bool = Field(default=False, alias="hasCompiledGraph")
    has_agent_compiled_graph: bool = Field(
        default=False,
        alias="hasAgentCompiledGraph",
    )
    execution_ready: bool = Field(default=False, alias="executionReady")
    created_at: str = Field(alias="createdAt")
