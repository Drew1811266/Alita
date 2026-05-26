from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.context_manager import build_context_bundle
from agent_service.goal_spec import parse_goal_spec
from agent_service.planning import (
    DocumentTemplatePlanner,
    GenericTaskPlanner,
    PlannerChain,
    PlanningError,
    PlanningRequest,
    ResearchTemplatePlanner,
    default_planner_chain,
)
from agent_service.schemas import Attachment, UserMessage
from agent_service.tool_registry import ToolRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_PACKAGES_ROOT = PROJECT_ROOT / "tool-packages"


def _registry() -> ToolRegistry:
    return ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)


def _request(message: UserMessage) -> PlanningRequest:
    registry = _registry()
    goal_spec = parse_goal_spec(message)
    context = build_context_bundle(
        message,
        goal_spec,
        str(PROJECT_ROOT / "project.alita"),
        registry,
    )
    return PlanningRequest(
        task_id=message.task_id,
        message=message,
        goal_spec=goal_spec,
        context=context,
        route_decision={},
        tool_registry=registry,
    )


def test_document_template_planner_returns_existing_document_graph_shape() -> None:
    request = _request(
        UserMessage(
            task_id="task-doc",
            content="summarize this document as PDF",
            attachments=[
                Attachment(
                    attachment_id="a1",
                    name="input.pdf",
                    path=str(PROJECT_ROOT / "input.pdf"),
                    size_bytes=128,
                    mime_type="application/pdf",
                )
            ],
        )
    )

    result = DocumentTemplatePlanner().plan(request)

    assert result.planner == "template.document.v1"
    assert result.graph_payload["graphId"] == "task-doc-graph"
    assert [node["nodeId"] for node in result.graph_payload["nodes"]] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]
    assert result.task_graph is not None
    assert result.confidence >= 0.8


def test_document_template_planner_skips_markdown_conversion_only_request() -> None:
    request = _request(
        UserMessage(
            task_id="task-doc-markdown",
            content="把这个文件转 markdown",
            attachments=[
                Attachment(
                    attachment_id="a1",
                    name="input.docx",
                    path=str(PROJECT_ROOT / "input.docx"),
                    size_bytes=128,
                    mime_type=(
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                )
            ],
        )
    )

    assert DocumentTemplatePlanner().can_plan(request) is False


def test_document_template_planner_keeps_export_markdown_request() -> None:
    request = _request(
        UserMessage(
            task_id="task-doc-export-markdown",
            content="export this docx to markdown",
            attachments=[
                Attachment(
                    attachment_id="a1",
                    name="input.docx",
                    path=str(PROJECT_ROOT / "input.docx"),
                    size_bytes=128,
                    mime_type=(
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                )
            ],
        )
    )

    assert DocumentTemplatePlanner().can_plan(request) is True


def test_research_template_planner_returns_existing_research_graph_shape() -> None:
    request = _request(
        UserMessage(
            task_id="task-research",
            content="Research and compare current Python packaging tools",
        )
    )

    result = ResearchTemplatePlanner().plan(request)

    assert result.planner == "template.research.v1"
    assert result.task_graph is None
    assert result.graph_payload["metadata"]["kind"] == "research"
    assert [node["nodeId"] for node in result.graph_payload["nodes"]] == [
        "research-intent-analysis",
        "research-privacy-guard",
        "research-query-plan",
        "research-parallel-search",
        "research-source-review",
        "research-source-reading",
        "research-report-synthesis",
        "research-report-quality-check",
        "research-markdown-output",
    ]


def test_generic_task_planner_preserves_existing_planning_nodes() -> None:
    request = _request(
        UserMessage(
            task_id="task-general",
            content="Can you create a Python script that counts rows in a CSV file?",
        )
    )

    result = GenericTaskPlanner().plan(request)

    assert result.planner == "heuristic.task.v1"
    assert result.task_graph is None
    assert result.graph_payload["metadata"]["planningMode"] == "deep"
    assert [
        node["nodeId"]
        for node in result.graph_payload["nodes"]
        if node["nodeType"] == "planning"
    ] == [
        "task-analysis",
        "context-gathering",
        "evidence-summary",
        "plan-draft",
        "capability-analysis",
        "tool-selection",
        "plan-review",
        "execution-order-planning",
    ]


def test_default_planner_chain_selects_document_before_generic_task() -> None:
    request = _request(
        UserMessage(
            task_id="task-doc",
            content="整理成报告",
            attachments=[
                Attachment(
                    attachment_id="a1",
                    name="input.docx",
                    path=str(PROJECT_ROOT / "input.docx"),
                    size_bytes=128,
                    mime_type=(
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                )
            ],
        )
    )

    result = default_planner_chain(_registry()).plan(request)

    assert result.planner == "template.document.v1"
    assert result.graph_payload["nodes"][0]["nodeId"] == "document-input"


def test_planner_chain_raises_when_no_planner_can_handle_request() -> None:
    request = _request(UserMessage(task_id="task-chat", content="hello"))

    with pytest.raises(PlanningError, match="no planner can handle task type: chat"):
        PlannerChain([]).plan(request)
