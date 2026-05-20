from __future__ import annotations

from pydantic import BaseModel, Field

from agent_service.context_manager import ContextBundle
from agent_service.goal_spec import GoalSpec
from agent_service.model_runtime import SupportedModelRegistry
from agent_service.plan_validator import PlanValidationError, validate_plan
from agent_service.task_graph import TaskGraph, build_document_task_graph
from agent_service.tool_registry import ToolRegistry

try:
    from agent_service.model_runtime import DEFAULT_SUPPORTED_MODEL_REGISTRY
except ImportError:
    DEFAULT_SUPPORTED_MODEL_REGISTRY = SupportedModelRegistry.default()


class PlannerV2Error(ValueError):
    pass


class PlanResult(BaseModel):
    planner: str
    task_graph: TaskGraph
    validation_warnings: list[str] = Field(default_factory=list)


class PlannerV2:
    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        model_registry: SupportedModelRegistry | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.model_registry = model_registry or DEFAULT_SUPPORTED_MODEL_REGISTRY

    def plan(
        self,
        *,
        task_id: str,
        goal_spec: GoalSpec,
        context: ContextBundle,
    ) -> PlanResult:
        _ = context

        if goal_spec.missing_inputs:
            missing_inputs = ", ".join(goal_spec.missing_inputs)
            raise PlannerV2Error(f"missing inputs: {missing_inputs}")

        if goal_spec.task_type != "document_processing":
            raise PlannerV2Error(f"unsupported task type: {goal_spec.task_type}")

        task_graph = build_document_task_graph(task_id, goal_spec)
        try:
            validate_plan(
                task_graph,
                tool_registry=self.tool_registry,
                model_registry=self.model_registry,
            )
        except PlanValidationError as exc:
            raise PlannerV2Error(f"invalid plan: {exc}") from exc

        return PlanResult(
            planner="template.document.v1",
            task_graph=task_graph,
            validation_warnings=[],
        )
