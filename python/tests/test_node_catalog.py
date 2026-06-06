from __future__ import annotations

from pathlib import Path

from fastapi.encoders import jsonable_encoder

from agent_service.node_catalog import (
    NodeAvailability,
    NodeCatalogBuilder,
    NodeDefinition,
    NodeExecutionBinding,
    NodePermissionProfile,
)
from agent_service.tool_registry import ToolRegistry


def _registry() -> ToolRegistry:
    return ToolRegistry.from_packages_root(
        Path(__file__).resolve().parents[2] / "tool-packages"
    )


def test_builder_converts_tool_manifest_to_node_definition() -> None:
    snapshot = NodeCatalogBuilder(tool_registry=_registry()).build()

    node = snapshot.node_by_id("document.convert.markdown")

    assert node.node_id == "document.convert.markdown"
    assert node.kind == "tool"
    assert node.category == "document"
    assert node.source == "internal_tool"
    assert node.capabilities == [
        "document.convert",
        "document.convert.markdown",
        "document.markitdown_convert",
    ]
    assert node.execution == NodeExecutionBinding(
        type="tool",
        tool_id="document.markitdown_convert",
        operation="convert_local_file",
    )
    assert node.permissions.permissions == [
        "read_project_files",
        "write_project_outputs",
        "run_python_plugin",
    ]
    assert node.permissions.risk_level == "high"
    assert node.availability == NodeAvailability(status="available")
    assert node.input_ports[0].data_type == "document"
    assert node.output_ports[0].data_type == "markdown"


def test_builder_registers_document_read_write_and_render_tool_nodes() -> None:
    snapshot = NodeCatalogBuilder(tool_registry=_registry()).build()

    read_node = snapshot.node_by_id("document.read")
    assert read_node.capabilities == ["document.read", "document.read_write"]
    assert read_node.execution == NodeExecutionBinding(
        type="tool",
        tool_id="document.read_write",
        operation="read",
    )

    markdown_node = snapshot.node_by_id("document.write_markdown")
    assert markdown_node.capabilities == [
        "document.write",
        "document.write_markdown",
    ]
    assert markdown_node.execution == NodeExecutionBinding(
        type="tool",
        tool_id="document.read_write",
        operation="write_markdown",
    )

    docx_node = snapshot.node_by_id("document.write_docx")
    assert docx_node.capabilities == ["document.write", "document.write_docx"]
    assert docx_node.execution == NodeExecutionBinding(
        type="tool",
        tool_id="document.read_write",
        operation="write_docx",
    )

    render_node = snapshot.node_by_id("document.render.typst_pdf")
    assert render_node.capabilities == [
        "document.render",
        "document.render_pdf",
        "document.render.typst_pdf",
        "document.typst_compile",
    ]
    assert render_node.execution == NodeExecutionBinding(
        type="tool",
        tool_id="document.typst_compile",
        operation="compile_report_pdf",
    )


def test_builder_registers_system_model_human_verifier_and_output_nodes() -> None:
    snapshot = NodeCatalogBuilder(tool_registry=_registry()).build()

    node_ids = {node.node_id for node in snapshot.nodes}

    assert "model.reasoning" in node_ids
    assert "document.summarize" in node_ids
    assert "research.synthesize" in node_ids
    assert "human.clarify" in node_ids
    assert "verify.artifact_exists" in node_ids
    assert "output.final_response" in node_ids
    assert snapshot.node_by_id("model.reasoning").execution.type == "model"
    assert snapshot.node_by_id("document.summarize").execution.type == "model"
    assert snapshot.node_by_id("research.synthesize").execution.type == "model"
    assert snapshot.node_by_id("human.clarify").execution.type == "human"
    assert snapshot.node_by_id("verify.artifact_exists").execution.type == "verifier"
    assert snapshot.node_by_id("output.final_response").execution.type == "output"
    assert snapshot.node_by_id("human.clarify").availability.status == "unavailable"
    assert (
        snapshot.node_by_id("human.clarify").availability.reason_code
        == "runtime_not_supported"
    )
    assert (
        snapshot.node_by_id("verify.artifact_exists").availability.status
        == "unavailable"
    )
    assert (
        snapshot.node_by_id("verify.artifact_exists").availability.reason_code
        == "runtime_not_supported"
    )
    assert snapshot.node_by_id("output.final_response").availability.status == (
        "available"
    )


def test_snapshot_records_duplicate_node_diagnostics() -> None:
    first = NodeDefinition(
        node_id="duplicate.node",
        kind="model",
        display_name="Duplicate",
        description="First duplicate node.",
        category="reasoning",
        capabilities=["duplicate.capability"],
        input_ports=[],
        output_ports=[],
        execution=NodeExecutionBinding(type="model", model_policy="node_reasoning"),
        permissions=NodePermissionProfile(),
        examples=[],
        source="system",
        version="1.0.0",
    )
    second = first.model_copy(update={"description": "Second duplicate node."})

    snapshot = NodeCatalogBuilder(tool_registry=ToolRegistry([])).build(
        additional_system_nodes=[first, second]
    )

    assert any(
        diagnostic.code == "duplicate_node_id"
        and diagnostic.node_id == "duplicate.node"
        for diagnostic in snapshot.diagnostics
    )
    assert snapshot.node_by_id("duplicate.node").description == "First duplicate node."


def test_snapshot_json_encoding_uses_sidecar_snake_case_fields() -> None:
    snapshot = NodeCatalogBuilder(tool_registry=_registry()).build()

    payload = jsonable_encoder(snapshot)
    node = next(
        node
        for node in payload["nodes"]
        if node["node_id"] == "document.convert.markdown"
    )

    assert "schema_version" in payload
    assert "generated_at" in payload
    assert "source_summary" in payload
    assert "schemaVersion" not in payload
    assert "generatedAt" not in payload
    assert "sourceSummary" not in payload
    assert "internal_tool_count" in payload["source_summary"]
    assert "internalToolCount" not in payload["source_summary"]

    assert "node_id" in node
    assert "display_name" in node
    assert "input_ports" in node
    assert "output_ports" in node
    assert "nodeId" not in node
    assert "displayName" not in node
    assert "inputPorts" not in node
    assert "outputPorts" not in node
    assert node["input_ports"][0]["data_type"] == "document"
    assert "dataType" not in node["input_ports"][0]
    assert node["execution"]["tool_id"] == "document.markitdown_convert"
    assert "toolId" not in node["execution"]
    assert node["permissions"]["risk_level"] == "high"
    assert node["permissions"]["requires_approval"] is True
    assert "riskLevel" not in node["permissions"]
    assert "requiresApproval" not in node["permissions"]
