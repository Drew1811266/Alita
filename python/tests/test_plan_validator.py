from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.goal_spec import GoalSpec
from agent_service.model_runtime import SupportedModelRegistry
from agent_service.plan_validator import PlanValidationError, validate_plan
from agent_service.task_graph import ToolBinding, build_document_task_graph
from agent_service.tool_registry import ToolRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_PACKAGES_ROOT = PROJECT_ROOT / "tool-packages"


def _goal_spec() -> GoalSpec:
    return GoalSpec(
        goal="summarize document",
        task_type="document_processing",
        deliverable="pdf_report",
        risk_level="local_write",
        permissions_required=["read_attachment", "write_project_artifact"],
        confidence=0.9,
    )


def _document_graph():
    return build_document_task_graph("task-document", _goal_spec())


def _tool_registry() -> ToolRegistry:
    return ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)


def _model_registry() -> SupportedModelRegistry:
    return SupportedModelRegistry.default()


def test_validate_plan_accepts_document_task_graph() -> None:
    graph = _document_graph()

    validate_plan(
        graph,
        tool_registry=ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT),
        model_registry=SupportedModelRegistry.default(),
    )


def test_validate_plan_rejects_unknown_tool_binding() -> None:
    graph = _document_graph()
    graph.node_by_id("document-parse").tool_binding = ToolBinding(
        tool_id="document.missing",
        operation="run",
    )

    with pytest.raises(PlanValidationError, match="document.missing"):
        validate_plan(
            graph,
            tool_registry=_tool_registry(),
            model_registry=_model_registry(),
        )


def test_validate_plan_rejects_unsupported_model_binding() -> None:
    graph = _document_graph()
    model_binding = graph.node_by_id("content-organize").model_binding
    assert model_binding is not None
    model_binding.model_ref = "remote.unknown"

    with pytest.raises(PlanValidationError, match="remote.unknown"):
        validate_plan(
            graph,
            tool_registry=_tool_registry(),
            model_registry=_model_registry(),
        )


def test_validate_plan_rejects_missing_required_binding() -> None:
    graph = _document_graph()
    graph.node_by_id("document-parse").tool_binding = None

    with pytest.raises(PlanValidationError, match="document-parse.*tool_binding"):
        validate_plan(
            graph,
            tool_registry=_tool_registry(),
            model_registry=_model_registry(),
        )
