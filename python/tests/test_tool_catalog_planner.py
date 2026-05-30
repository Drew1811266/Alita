from __future__ import annotations

from pathlib import Path

from agent_service.context_manager import build_context_bundle
from agent_service.goal_spec import parse_goal_spec
from agent_service.schemas import RunGraph, UserMessage
from agent_service.tool_catalog_planner import (
    ToolCatalogPlanner,
    ToolCatalogPlanningRequest,
)
from agent_service.tool_registry import ToolRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_PACKAGES_ROOT = PROJECT_ROOT / "tool-packages"


def test_tool_catalog_planner_creates_executable_fixed_tool_node() -> None:
    message = UserMessage(
        task_id="task-echo-values",
        content="Use the echo values tool to echo this request.",
    )
    registry = ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)
    goal_spec = parse_goal_spec(message)
    context = build_context_bundle(
        message,
        goal_spec,
        str(PROJECT_ROOT / "project.alita"),
        registry,
    )

    result = ToolCatalogPlanner(tool_registry=registry).plan(
        ToolCatalogPlanningRequest(
            task_id=message.task_id,
            message=message,
            goal_spec=goal_spec,
            context=context,
        )
    )

    assert result.planned is True
    assert result.diagnostics == []
    assert result.graph_payload is not None
    RunGraph.model_validate(result.graph_payload)
    tool_node = result.graph_payload["nodes"][0]
    assert tool_node["nodeId"] == "tool-test-echo-values"
    assert tool_node["nodeType"] == "fixed_tool"
    assert tool_node["toolRef"] == "internal:test.echo_values"
    assert tool_node["toolBinding"]["operation"] == "echo_values"
    assert tool_node["toolBinding"]["argumentsTemplate"]["values"] == {
        "operation": "echo_values",
        "message": message.content,
        "source_text": message.content,
        "metadata_value": "tool_catalog",
    }
    assert result.graph_payload["nodes"][1]["nodeType"] == "output"


def test_tool_catalog_planner_returns_diagnostics_without_matching_tool() -> None:
    message = UserMessage(
        task_id="task-no-catalog-match",
        content="Write an implementation summary.",
    )
    registry = ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)
    goal_spec = parse_goal_spec(message)
    context = build_context_bundle(
        message,
        goal_spec,
        str(PROJECT_ROOT / "project.alita"),
        registry,
    )

    result = ToolCatalogPlanner(tool_registry=registry).plan(
        ToolCatalogPlanningRequest(
            task_id=message.task_id,
            message=message,
            goal_spec=goal_spec,
            context=context,
        )
    )

    assert result.planned is False
    assert result.graph_payload is None
    assert result.diagnostics == ["no catalog tool matched the task"]
