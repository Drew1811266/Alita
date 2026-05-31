from __future__ import annotations

from pathlib import Path

from agent_service.context_manager import build_context_bundle
from agent_service.goal_spec import parse_goal_spec
from agent_service.schemas import Attachment, RunGraph, UserMessage
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


def test_tool_catalog_planner_binds_attachment_paths_and_output_path() -> None:
    attachment = Attachment(
        attachment_id="att-1",
        name="source.md",
        path=str(PROJECT_ROOT / "inputs" / "source.md"),
        size_bytes=12,
        mime_type="text/markdown",
    )
    message = UserMessage(
        task_id="task-document-read",
        content="Use the document read write tool to read this attachment.",
        attachments=[attachment],
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
    tool_node = result.graph_payload["nodes"][0]
    values = tool_node["toolBinding"]["argumentsTemplate"]["values"]
    assert values["operation"] == "read"
    assert values["input_paths"] == [attachment.path]
    assert values["output_path"] == "artifacts/task-document-read-document-read-write.md"


def test_tool_catalog_planner_chains_schema_compatible_tools() -> None:
    attachment = Attachment(
        attachment_id="att-chain",
        name="source.md",
        path=str(PROJECT_ROOT / "inputs" / "source.md"),
        size_bytes=12,
        mime_type="text/markdown",
    )
    message = UserMessage(
        task_id="task-document-echo-chain",
        content=(
            "Use the document read write tool and echo values tool to read "
            "this attachment then echo the extracted text."
        ),
        attachments=[attachment],
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
    assert [node["nodeId"] for node in result.graph_payload["nodes"]] == [
        "tool-document-read-write",
        "tool-test-echo-values",
        "task-output",
    ]
    document_node = result.graph_payload["nodes"][0]
    echo_node = result.graph_payload["nodes"][1]
    assert document_node["toolBinding"]["argumentsTemplate"]["values"][
        "input_paths"
    ] == [attachment.path]
    assert echo_node["dependencies"] == ["tool-document-read-write"]
    assert echo_node["toolBinding"]["argumentsTemplate"]["values"][
        "source_text"
    ] == "{tool-document-read-write.text}"
    assert result.graph_payload["edges"] == [
        {
            "id": "tool-document-read-write-tool-test-echo-values",
            "source": "tool-document-read-write",
            "target": "tool-test-echo-values",
        },
        {
            "id": "tool-test-echo-values-task-output",
            "source": "tool-test-echo-values",
            "target": "task-output",
        },
    ]


def test_tool_catalog_planner_builds_three_step_schema_compatible_dag() -> None:
    attachment = Attachment(
        attachment_id="att-dag",
        name="source.docx",
        path=str(PROJECT_ROOT / "inputs" / "source.docx"),
        size_bytes=12,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    message = UserMessage(
        task_id="task-convert-echo-typst",
        content=(
            "Use markitdown convert, echo values, and typst compile to convert "
            "this attachment, echo the extracted text, then compile a PDF."
        ),
        attachments=[attachment],
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
    assert [node["nodeId"] for node in result.graph_payload["nodes"]] == [
        "tool-document-markitdown-convert",
        "tool-test-echo-values",
        "tool-document-typst-compile",
        "task-output",
    ]
    echo_node = result.graph_payload["nodes"][1]
    typst_node = result.graph_payload["nodes"][2]
    assert echo_node["dependencies"] == ["tool-document-markitdown-convert"]
    assert echo_node["toolBinding"]["argumentsTemplate"]["values"]["source_text"] == (
        "{tool-document-markitdown-convert.text}"
    )
    assert typst_node["dependencies"] == ["tool-test-echo-values"]
    typst_values = typst_node["toolBinding"]["argumentsTemplate"]["values"]
    assert typst_values["outline"] == "{tool-test-echo-values.source_text}"
    assert typst_values["report"] == "{tool-test-echo-values.source_text}"
    assert result.graph_payload["metadata"]["toolCatalogPlanner"]["toolIds"] == [
        "internal:document.markitdown_convert",
        "internal:test.echo_values",
        "internal:document.typst_compile",
    ]


def test_tool_catalog_planner_reports_unbound_required_argument(tmp_path: Path) -> None:
    package_root = tmp_path / "tool-packages"
    tool_root = package_root / "strict"
    tool_root.mkdir(parents=True)
    (tool_root / "manifest.json").write_text(
        """
{
  "tool_id": "strict.requires_owner",
  "name": "Strict Owner Tool",
  "description": "Requires an owner field.",
  "version": "0.1.0",
  "source_type": "test",
  "license": "internal",
  "runtime": "python_function",
  "entrypoint": "strict_tool:run",
  "capabilities": ["strict", "owner"],
  "operations": [
    {
      "name": "run",
      "description": "Run strict owner tool."
    }
  ],
  "input_schema": {
    "type": "object",
    "required": ["operation", "owner"],
    "properties": {
      "operation": {"type": "string", "enum": ["run"]},
      "owner": {"type": "string"}
    }
  },
  "output_schema": {"type": "object"},
  "permissions": [],
  "error_codes": [],
  "timeout_policy": {},
  "artifact_policy": {},
  "security_policy": {},
  "examples": [],
  "node_templates": []
}
""",
        encoding="utf-8",
    )
    message = UserMessage(
        task_id="task-strict-owner",
        content="Use the strict owner tool.",
    )
    registry = ToolRegistry.from_packages_root(package_root)
    goal_spec = parse_goal_spec(message)
    context = build_context_bundle(
        message,
        goal_spec,
        str(tmp_path / "project.alita"),
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
    assert result.diagnostics == ["missing binding value for required argument: owner"]
