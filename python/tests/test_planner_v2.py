from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.context_manager import build_context_bundle
from agent_service.goal_spec import parse_goal_spec
from agent_service.planner_v2 import PlannerV2, PlannerV2Error
from agent_service.schemas import Attachment, UserMessage
from agent_service.tool_registry import ToolRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_PACKAGES_ROOT = PROJECT_ROOT / "tool-packages"


def _document_message() -> UserMessage:
    return UserMessage(
        task_id="task-document",
        content="summarize this document as a PDF report",
        attachments=[
            Attachment(
                attachment_id="attachment-1",
                name="source.pdf",
                path=str(PROJECT_ROOT / "fixtures" / "source.pdf"),
                size_bytes=1024,
                mime_type="application/pdf",
            )
        ],
    )


def _tool_registry() -> ToolRegistry:
    return ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)


def test_planner_v2_returns_document_template_plan() -> None:
    message = _document_message()
    goal_spec = parse_goal_spec(message)
    tool_registry = _tool_registry()
    context = build_context_bundle(
        message,
        goal_spec,
        str(PROJECT_ROOT),
        tool_registry,
    )
    planner = PlannerV2(tool_registry=tool_registry)

    result = planner.plan(
        task_id=message.task_id,
        goal_spec=goal_spec,
        context=context,
    )

    assert result.planner == "template.document.v1"
    assert result.validation_warnings == []
    assert [node.node_id for node in result.task_graph.nodes] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]


def test_planner_v2_rejects_missing_inputs() -> None:
    message = UserMessage(
        task_id="task-missing-document",
        content="summarize this document",
    )
    goal_spec = parse_goal_spec(message)
    tool_registry = _tool_registry()
    context = build_context_bundle(
        message,
        goal_spec,
        str(PROJECT_ROOT),
        tool_registry,
    )
    planner = PlannerV2(tool_registry=tool_registry)

    with pytest.raises(PlannerV2Error, match="missing inputs: document_file"):
        planner.plan(
            task_id=message.task_id,
            goal_spec=goal_spec,
            context=context,
        )


def test_planner_v2_rejects_unsupported_task_type() -> None:
    message = UserMessage(
        task_id="task-chat",
        content="hello",
    )
    goal_spec = parse_goal_spec(message)
    tool_registry = _tool_registry()
    context = build_context_bundle(
        message,
        goal_spec,
        str(PROJECT_ROOT),
        tool_registry,
    )
    planner = PlannerV2(tool_registry=tool_registry)

    with pytest.raises(PlannerV2Error, match="unsupported task type: chat"):
        planner.plan(
            task_id=message.task_id,
            goal_spec=goal_spec,
            context=context,
        )


def test_planner_v2_wraps_plan_validation_errors() -> None:
    message = _document_message()
    goal_spec = parse_goal_spec(message)
    empty_tool_registry = ToolRegistry([])
    context = build_context_bundle(
        message,
        goal_spec,
        str(PROJECT_ROOT),
        empty_tool_registry,
    )
    planner = PlannerV2(tool_registry=empty_tool_registry)

    with pytest.raises(PlannerV2Error, match="invalid plan: unknown tool binding"):
        planner.plan(
            task_id=message.task_id,
            goal_spec=goal_spec,
            context=context,
        )
