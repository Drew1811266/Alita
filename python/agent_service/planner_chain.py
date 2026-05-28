from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_service.context_manager import ContextBundle
from agent_service.goal_spec import GoalSpec, TaskType
from agent_service.router_v2 import AgentRouteIntent, RouteSource
from agent_service.schemas import UserMessage


PlannerStrategy = Literal["document_template", "legacy_task_planner"]
PLANNER_CHAIN_VERSION = "planner_chain.v1"
LOCAL_PATH_PATTERN = re.compile(
    r"(?ix)"
    r"(?:"
    r"\b[a-z]:[\\/](?:[^\\/:\r\n,;<>\"|?*]+[\\/])+[^\\/\s:\r\n,;<>\"|?*]+"
    r"|"
    r"/(?:[^/\r\n,;<>\"|?*]+/){2,}[^/\s\r\n,;<>\"|?*]+"
    r")"
)


class PlannerChainError(ValueError):
    pass


class StructuredRouteContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    intent: AgentRouteIntent
    confidence: float = Field(ge=0.0, le=1.0)
    task_type: TaskType = Field(alias="taskType")
    missing_inputs: list[str] = Field(default_factory=list, alias="missingInputs")
    required_permissions: list[str] = Field(default_factory=list, alias="requiredPermissions")
    tool_candidates: list[str] = Field(default_factory=list, alias="toolCandidates")
    reason: str
    source: RouteSource
    should_clarify: bool = Field(default=False, alias="shouldClarify")
    clarification_prompt: str | None = Field(default=None, alias="clarificationPrompt")

    def safe_payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "taskType": self.task_type,
            "missingInputs": _scrub_payload(list(self.missing_inputs)),
            "requiredPermissions": _scrub_payload(list(self.required_permissions)),
            "toolCandidates": _scrub_payload(list(self.tool_candidates)),
            "reason": _safe_text(self.reason),
            "source": self.source,
            "shouldClarify": self.should_clarify,
            "clarificationPrompt": (
                _safe_text(self.clarification_prompt)
                if self.clarification_prompt is not None
                else None
            ),
        }


class PlannerChainRequest(BaseModel):
    task_id: str
    message: UserMessage
    goal_spec: GoalSpec
    route: StructuredRouteContext
    context: ContextBundle


class PlannerChainResult(BaseModel):
    planner: str
    strategy: PlannerStrategy
    graph_payload: dict[str, Any]
    validation_warnings: list[str] = Field(default_factory=list)


def route_context_from_payload(payload: dict[str, Any]) -> StructuredRouteContext:
    try:
        return StructuredRouteContext.model_validate(payload)
    except ValidationError:
        raise PlannerChainError("invalid structured route payload") from None


def _safe_text(value: str) -> str:
    return LOCAL_PATH_PATTERN.sub("[local_path]", value)


def _scrub_payload(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, list):
        return [_scrub_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _scrub_payload(item) for key, item in value.items()}
    return value
