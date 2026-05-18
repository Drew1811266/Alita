from __future__ import annotations

from pathlib import Path

from agent_service.schemas import Attachment
from agent_service.task_planner import (
    CapabilityRequirement,
    TaskPlan,
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


def test_mixed_network_csv_task_is_unsupported_not_low_risk_script() -> None:
    task_plan = analyze_task("Download a CSV from the network and count rows.", [])
    task_plan.tool_gaps = resolve_tool_gaps(task_plan.requirements, selected_tools=[])

    assert task_plan.kind == TaskKind.UNSUPPORTED
    assert [requirement.capability for requirement in task_plan.requirements] == [
        "network.fetch"
    ]
    assert task_plan.tool_gaps[0].temporary_script is None
    assert task_plan.tool_gaps[0].user_message is not None


def test_shell_process_credential_and_broad_filesystem_tasks_are_unsupported() -> None:
    cases = [
        ("Run a shell command to count rows in a CSV.", "shell.execute"),
        ("Kill the stuck process after inspecting the log.", "process.control"),
        ("Use my password to open the local CSV.", "credential.handle"),
        ("Scan my whole filesystem and summarize every CSV.", "filesystem.broad_access"),
    ]

    for prompt, capability in cases:
        task_plan = analyze_task(prompt, [])
        task_plan.tool_gaps = resolve_tool_gaps(task_plan.requirements, selected_tools=[])

        assert task_plan.kind == TaskKind.UNSUPPORTED
        assert [requirement.capability for requirement in task_plan.requirements] == [
            capability
        ]
        assert task_plan.tool_gaps[0].temporary_script is None


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


def test_document_task_graph_preserves_workflow_with_planner_nodes_and_estimates() -> None:
    task_plan = analyze_task("Please organize this document into a report PDF.", [_docx_attachment()])
    task_plan.task_id = "doc-plan"

    graph = build_task_graph(task_plan)

    assert graph["metadata"]["taskKind"] == "document"
    assert [node["nodeId"] for node in graph["nodes"][:6]] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]
    planning_nodes = [node for node in graph["nodes"] if node["nodeType"] == "planning"]
    assert [node["nodeId"] for node in planning_nodes] == [
        "task-analysis",
        "capability-analysis",
        "tool-selection",
        "execution-order-planning",
    ]
    document_nodes = [
        node
        for node in graph["nodes"]
        if node["nodeId"]
        in {
            "document-input",
            "document-parse",
            "content-organize",
            "report-generate",
            "typst-export",
            "file-export",
        }
    ]
    assert [node["nodeId"] for node in document_nodes] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]
    executable_nodes = [
        node
        for node in document_nodes
        if node["nodeType"] in {"fixed_tool", "model", "temporary_script"}
    ]
    document_input = next(
        node for node in graph["nodes"] if node["nodeId"] == "document-input"
    )
    assert executable_nodes
    assert all(node.get("estimate") for node in executable_nodes)
    assert all(node.get("resourceUsage") for node in executable_nodes)
    assert document_input["dependencies"] == ["execution-order-planning"]
    assert {
        (edge["source"], edge["target"]) for edge in graph["edges"]
    } >= {("execution-order-planning", "document-input")}


def test_markdown_document_conversion_graph_only_parses_and_outputs() -> None:
    task_plan = analyze_task("Please convert this document to Markdown.", [_docx_attachment()])
    task_plan.task_id = "doc-markdown"

    graph = build_task_graph(task_plan)

    assert [node["nodeId"] for node in graph["nodes"]] == [
        "document-input",
        "document-parse",
        "file-export",
        "task-analysis",
        "capability-analysis",
        "tool-selection",
        "execution-order-planning",
    ]
    assert [
        node["nodeId"] for node in graph["nodes"] if node["nodeType"] == "model"
    ] == []
    assert "typst-export" not in {node["nodeId"] for node in graph["nodes"]}
    assert next(
        node for node in graph["nodes"] if node["nodeId"] == "document-input"
    )["dependencies"] == ["execution-order-planning"]
    executable_nodes = [
        node
        for node in graph["nodes"]
        if node["nodeType"] in {"fixed_tool", "model", "temporary_script"}
    ]
    assert executable_nodes
    assert all(node.get("estimate") for node in executable_nodes)
    assert all(node.get("resourceUsage") for node in executable_nodes)


def test_unsupported_mixed_plan_stops_before_executable_nodes() -> None:
    task_plan = TaskPlan(
        kind=TaskKind.CONTENT,
        summary="Plan a mixed task with one blocked network capability.",
        requirements=[
            CapabilityRequirement(
                capability="model.reasoning",
                description="Draft a summary.",
                can_use_model=True,
            ),
            CapabilityRequirement(
                capability="network.fetch",
                description="Fetch content from the public internet.",
            ),
        ],
    )
    task_plan.tool_gaps = resolve_tool_gaps(task_plan.requirements, selected_tools=[])

    graph = build_task_graph(task_plan)

    assert graph["nodes"][-1]["nodeId"] == "missing-tool-response"
    assert graph["nodes"][-1]["nodeType"] == "output"
    assert [
        node["nodeId"]
        for node in graph["nodes"]
        if node["nodeType"] in {"fixed_tool", "model", "temporary_script"}
    ] == []


def test_unsupported_document_plan_stops_before_document_executable_nodes() -> None:
    task_plan = TaskPlan(
        kind=TaskKind.DOCUMENT,
        summary="Plan a document task with a missing renderer.",
        requirements=[
            CapabilityRequirement(
                capability="document_input",
                description="Receive the user-provided attachment.",
            ),
            CapabilityRequirement(
                capability="document.render.unavailable",
                description="Render the document with an unavailable renderer.",
            ),
        ],
    )
    task_plan.tool_gaps = resolve_tool_gaps(task_plan.requirements, selected_tools=[])

    graph = build_task_graph(task_plan)
    planning_nodes = [node for node in graph["nodes"] if node["nodeType"] == "planning"]

    assert [node["nodeId"] for node in planning_nodes] == [
        "task-analysis",
        "capability-analysis",
        "tool-selection",
        "execution-order-planning",
    ]
    assert graph["nodes"][-1]["nodeId"] == "missing-tool-response"
    assert graph["nodes"][-1]["nodeType"] == "output"
    assert [
        node["nodeId"]
        for node in graph["nodes"]
        if node["nodeType"] in {"fixed_tool", "model", "temporary_script"}
    ] == []
