from __future__ import annotations

from pathlib import Path

from agent_service.schemas import Attachment
from agent_service.task_planner import (
    CapabilityRequirement,
    TaskKind,
    analyze_task,
    build_task_graph,
    resolve_tool_gaps,
    select_tools,
)
from agent_service.tool_registry import ToolRegistry


TOOL_PACKAGES_ROOT = Path(__file__).resolve().parents[2] / "tool-packages"


def _docx_attachment() -> Attachment:
    return Attachment(
        attachment_id="doc-1",
        name="notes.docx",
        path="workspace/inputs/notes.docx",
        size_bytes=1200,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def test_planner_emits_visible_planning_nodes() -> None:
    task_plan = analyze_task(
        "Can you create a Python script that summarizes a CSV file?",
        [],
    )

    graph = build_task_graph(task_plan)
    planning_nodes = [node for node in graph["nodes"] if node["nodeType"] == "planning"]

    assert [node["nodeId"] for node in planning_nodes] == [
        "task-analysis",
        "capability-analysis",
        "tool-selection",
        "execution-order-planning",
    ]
    assert all(node["status"] == "completed" for node in planning_nodes)
    assert all(node["summary"] for node in planning_nodes)


def test_analyze_task_detects_document_conversion_requirements() -> None:
    task_plan = analyze_task("Please convert this document to Markdown.", [_docx_attachment()])

    assert task_plan.kind == TaskKind.DOCUMENT
    assert [requirement.capability for requirement in task_plan.requirements] == [
        "document_input",
        "document.convert.markdown",
    ]


def test_builtin_tool_selection_prefers_enabled_integrated_tools() -> None:
    registry = ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)
    requirements = [
        CapabilityRequirement(
            capability="document.convert.markdown",
            description="Convert an attached document to Markdown.",
        )
    ]

    selected_tools = select_tools(requirements, registry.enabled_tools())

    assert [tool.tool_id for tool in selected_tools] == ["document.markitdown_convert"]
    assert selected_tools[0].capability == "document.convert.markdown"


def test_disabled_tool_is_not_selected() -> None:
    registry = ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)
    requirements = [
        CapabilityRequirement(
            capability="document.convert.markdown",
            description="Convert an attached document to Markdown.",
        )
    ]

    selected_tools = select_tools(
        requirements,
        registry.enabled_tools(disabled_tool_ids=["document.markitdown_convert"]),
    )

    assert selected_tools == []


def test_missing_capability_checks_temporary_script_feasibility() -> None:
    requirements = [
        CapabilityRequirement(
            capability="file.inspect",
            description="Inspect a bounded local CSV file.",
            temporary_script_candidate=True,
        )
    ]

    gaps = resolve_tool_gaps(requirements, selected_tools=[])

    assert len(gaps) == 1
    assert gaps[0].temporary_script is not None
    assert gaps[0].temporary_script.risk_level == "low"
    assert gaps[0].temporary_script.requires_approval is False


def test_no_tool_and_no_safe_substitute_returns_missing_tool_message() -> None:
    requirements = [
        CapabilityRequirement(
            capability="network.fetch",
            description="Fetch content from the public internet.",
            temporary_script_candidate=False,
        )
    ]

    gaps = resolve_tool_gaps(requirements, selected_tools=[])

    assert len(gaps) == 1
    assert gaps[0].temporary_script is None
    assert gaps[0].user_message is not None
    assert "enabled tool" in gaps[0].user_message


def test_low_risk_temporary_script_node_has_preview_and_no_required_approval() -> None:
    task_plan = analyze_task("Inspect a local CSV file and count the rows.", [])
    task_plan.tool_gaps = resolve_tool_gaps(
        task_plan.requirements,
        selected_tools=[],
    )

    graph = build_task_graph(task_plan)
    script_nodes = [
        node for node in graph["nodes"] if node["nodeType"] == "temporary_script"
    ]

    assert len(script_nodes) == 1
    review = script_nodes[0]["scriptReview"]
    assert review["riskLevel"] == "low"
    assert review["requiresApproval"] is False
    assert "csv" in review["codePreview"].lower()
    assert script_nodes[0]["status"] == "waiting"


def test_high_risk_temporary_script_node_requires_approval() -> None:
    task_plan = analyze_task("Create a script to delete matching files in a folder.", [])
    task_plan.tool_gaps = resolve_tool_gaps(
        task_plan.requirements,
        selected_tools=[],
    )

    graph = build_task_graph(task_plan)
    script_nodes = [
        node for node in graph["nodes"] if node["nodeType"] == "temporary_script"
    ]

    assert len(script_nodes) == 1
    review = script_nodes[0]["scriptReview"]
    assert review["riskLevel"] == "high"
    assert review["requiresApproval"] is True
    assert script_nodes[0]["status"] == "needs_permission"
