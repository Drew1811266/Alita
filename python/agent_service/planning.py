from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_service.context_manager import ContextBundle
from agent_service.goal_spec import GoalSpec
from agent_service.graph_compiler import compile_task_graph_to_node_graph
from agent_service.planner_v2 import PlannerV2
from agent_service.schemas import UserMessage
from agent_service.task_graph import TaskGraph
from agent_service.task_planner import (
    analyze_task,
    build_task_graph,
    resolve_tool_gaps,
    select_tools,
)
from agent_service.tool_registry import ToolRegistry
from agent_service.web_research import build_research_graph


class PlanningError(ValueError):
    pass


class PlanningRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_id: str
    message: UserMessage
    goal_spec: GoalSpec
    context: ContextBundle
    route_decision: dict[str, Any] = Field(default_factory=dict)
    tool_registry: ToolRegistry
    disabled_tool_ids: list[str] = Field(default_factory=list)
    approved_permissions: list[str] = Field(default_factory=list)


class PlanningResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    planner: str
    graph_payload: dict[str, Any]
    task_graph: TaskGraph | None = None
    confidence: float = 0.7
    metadata: dict[str, Any] = Field(default_factory=dict)


class Planner(Protocol):
    name: str

    def can_plan(self, request: PlanningRequest) -> bool:
        ...

    def plan(self, request: PlanningRequest) -> PlanningResult:
        ...


class PlannerChain:
    def __init__(self, planners: list[Planner]) -> None:
        self.planners = list(planners)

    def plan(self, request: PlanningRequest) -> PlanningResult:
        for planner in self.planners:
            if planner.can_plan(request):
                return planner.plan(request)

        raise PlanningError(
            f"no planner can handle task type: {request.goal_spec.task_type}"
        )


class DocumentTemplatePlanner:
    name = "template.document.v1"

    def can_plan(self, request: PlanningRequest) -> bool:
        return (
            request.goal_spec.task_type == "document_processing"
            and not request.goal_spec.missing_inputs
            and not _is_markdown_conversion_only(request.message.content)
        )

    def plan(self, request: PlanningRequest) -> PlanningResult:
        result = PlannerV2(tool_registry=request.tool_registry).plan(
            task_id=request.task_id,
            goal_spec=request.goal_spec,
            context=request.context,
        )
        graph_payload = compile_task_graph_to_node_graph(result.task_graph)
        return PlanningResult(
            planner=result.planner,
            graph_payload=graph_payload,
            task_graph=result.task_graph,
            confidence=request.goal_spec.confidence,
            metadata={"validationWarnings": result.validation_warnings},
        )


class ResearchTemplatePlanner:
    name = "template.research.v1"

    def can_plan(self, request: PlanningRequest) -> bool:
        return request.goal_spec.task_type == "research"

    def plan(self, request: PlanningRequest) -> PlanningResult:
        graph_payload = build_research_graph(request.message, request.route_decision)
        return PlanningResult(
            planner=self.name,
            graph_payload=graph_payload,
            task_graph=None,
            confidence=request.goal_spec.confidence,
            metadata={"kind": "research"},
        )


class GenericTaskPlanner:
    name = "heuristic.task.v1"

    def can_plan(self, request: PlanningRequest) -> bool:
        return request.goal_spec.task_type != "chat"

    def plan(self, request: PlanningRequest) -> PlanningResult:
        task_plan = analyze_task(request.message.content, request.message.attachments)
        task_plan.task_id = request.task_id
        task_plan.selected_tools = select_tools(
            task_plan.requirements,
            request.tool_registry.enabled_tools(
                disabled_tool_ids=request.disabled_tool_ids
            ),
        )
        task_plan.tool_gaps = resolve_tool_gaps(
            task_plan.requirements,
            task_plan.selected_tools,
        )
        graph_payload = build_task_graph(task_plan)
        return PlanningResult(
            planner=self.name,
            graph_payload=graph_payload,
            task_graph=None,
            confidence=request.goal_spec.confidence,
            metadata={"taskKind": task_plan.kind.value},
        )


def default_planner_chain(tool_registry: ToolRegistry) -> PlannerChain:
    del tool_registry
    return PlannerChain(
        [
            DocumentTemplatePlanner(),
            ResearchTemplatePlanner(),
            GenericTaskPlanner(),
        ]
    )


def _is_markdown_conversion_only(content: str) -> bool:
    normalized = content.lower()
    wants_markdown = "markdown" in normalized or "md" in normalized
    wants_conversion = "convert" in normalized or "转换" in content or "转" in content
    wants_report = "report" in normalized or "pdf" in normalized or "报告" in content
    return wants_markdown and wants_conversion and not wants_report
