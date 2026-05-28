from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_service.context_manager import ContextBundle
from agent_service.graph_compiler import compile_task_graph_to_node_graph
from agent_service.goal_spec import GoalSpec, TaskType
from agent_service.model_runtime import SupportedModelRegistry
from agent_service.planner_v2 import PlannerV2, PlannerV2Error
from agent_service.router_v2 import AgentRouteIntent, RouteSource
from agent_service.schemas import RunGraph, UserMessage
from agent_service.tool_registry import ToolRegistry

try:
    from agent_service.model_runtime import DEFAULT_SUPPORTED_MODEL_REGISTRY
except ImportError:
    DEFAULT_SUPPORTED_MODEL_REGISTRY = SupportedModelRegistry.default()


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


class PlannerChain:
    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        model_registry: SupportedModelRegistry | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.model_registry = model_registry or DEFAULT_SUPPORTED_MODEL_REGISTRY

    def plan(self, request: PlannerChainRequest) -> PlannerChainResult:
        self._validate_request(request)
        if request.route.task_type == "document_processing" and not _is_markdown_conversion_only(
            request.message.content
        ):
            return self._plan_document_template(request)
        raise PlannerChainError(f"unsupported planner chain task type: {request.route.task_type}")

    def _validate_request(self, request: PlannerChainRequest) -> None:
        if request.route.intent != "task":
            raise PlannerChainError(f"cannot plan non-task route: {request.route.intent}")
        missing_inputs = _scrub_payload(
            [
                *request.route.missing_inputs,
                *request.goal_spec.missing_inputs,
            ]
        )
        if missing_inputs:
            raise PlannerChainError(
                f"missing inputs: {', '.join(str(item) for item in missing_inputs)}"
            )

    def _plan_document_template(self, request: PlannerChainRequest) -> PlannerChainResult:
        try:
            plan = PlannerV2(
                tool_registry=self.tool_registry,
                model_registry=self.model_registry,
            ).plan(
                task_id=request.task_id,
                goal_spec=request.goal_spec,
                context=request.context,
            )
        except PlannerV2Error as exc:
            raise PlannerChainError(_safe_text(str(exc))) from None

        graph_payload = compile_task_graph_to_node_graph(plan.task_graph)
        graph_payload = _with_planner_chain_metadata(
            graph_payload,
            request=request,
            planner=plan.planner,
            strategy="document_template",
        )
        _validate_graph_payload(graph_payload)
        return PlannerChainResult(
            planner=plan.planner,
            strategy="document_template",
            graph_payload=graph_payload,
            validation_warnings=list(plan.validation_warnings),
        )


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


def _with_planner_chain_metadata(
    graph_payload: dict[str, Any],
    *,
    request: PlannerChainRequest,
    planner: str,
    strategy: PlannerStrategy,
) -> dict[str, Any]:
    metadata = dict(graph_payload.get("metadata") or {})
    metadata["plannerChain"] = {
        "version": PLANNER_CHAIN_VERSION,
        "planner": planner,
        "strategy": strategy,
        "routeIntent": request.route.intent,
        "taskType": request.route.task_type,
        "routeSource": request.route.source,
        "routeConfidence": request.route.confidence,
        "toolCandidates": _scrub_payload(list(request.route.tool_candidates)),
        "requiredPermissions": _scrub_payload(list(request.route.required_permissions)),
    }
    return {**graph_payload, "metadata": metadata}


def _validate_graph_payload(graph_payload: dict[str, Any]) -> None:
    try:
        RunGraph.model_validate(graph_payload)
    except Exception:
        raise PlannerChainError("invalid node graph payload") from None


def _is_markdown_conversion_only(content: str) -> bool:
    normalized = content.lower()
    wants_markdown = bool(re.search(r"\bmarkdown\b|\.md\b|\bmd\b", normalized))
    wants_conversion = "convert" in normalized or "转换" in content or "转" in content
    wants_report = "report" in normalized or "pdf" in normalized or "报告" in content
    return wants_markdown and wants_conversion and not wants_report
