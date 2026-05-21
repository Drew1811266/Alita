from __future__ import annotations

from agent_service.model_runtime import SupportedModelRegistry
from agent_service.task_graph import (
    ModelBinding,
    TaskGraph,
    TaskGraphValidationError,
    ToolBinding,
    validate_task_graph,
)
from agent_service.tool_registry import ToolRegistry


class PlanValidationError(ValueError):
    pass


def validate_plan(
    task_graph: TaskGraph,
    *,
    tool_registry: ToolRegistry,
    model_registry: SupportedModelRegistry,
) -> None:
    try:
        validate_task_graph(task_graph)
    except TaskGraphValidationError as exc:
        raise PlanValidationError(str(exc)) from exc

    for node in task_graph.nodes:
        if node.kind in {"input", "fixed_tool"}:
            _validate_tool_binding(node.node_id, node.tool_binding, tool_registry)
        elif node.kind == "model":
            _validate_model_binding(node.node_id, node.model_binding, model_registry)


def _validate_tool_binding(
    node_id: str,
    binding: ToolBinding | None,
    registry: ToolRegistry,
) -> None:
    if binding is None:
        raise PlanValidationError(f"{node_id} is missing tool_binding")

    try:
        registry.get(binding.tool_id)
    except KeyError as exc:
        raise PlanValidationError(f"unknown tool binding: {binding.tool_id}") from exc

    if not registry.has_operation(binding.tool_id, binding.operation):
        raise PlanValidationError(
            f"{node_id} references unsupported operation "
            f"{binding.tool_id}.{binding.operation}"
        )


def _validate_model_binding(
    node_id: str,
    binding: ModelBinding | None,
    registry: SupportedModelRegistry,
) -> None:
    if binding is None:
        raise PlanValidationError(f"{node_id} is missing model_binding")

    if not registry.supports(binding.model_ref):
        raise PlanValidationError(
            f"{node_id} references unsupported model {binding.model_ref}"
        )
