from __future__ import annotations

import pytest

from agent_service.harness_errors import HarnessError
from agent_service.permission_gate import PermissionGate
from agent_service.schemas import GraphNode
from agent_service.tool_registry import ToolManifestSpec, ToolOperationSpec, ToolRegistry


def test_allows_default_document_permissions() -> None:
    node = _node(
        "typst-export",
        tool_ref="document.typst_compile",
        permissions=["write_project_artifact"],
    )

    PermissionGate().ensure_node_allowed(node, tool_registry=_registry())


def test_explicit_empty_default_allowlist_blocks_document_permissions() -> None:
    node = _node(
        "typst-export",
        tool_ref="document.typst_compile",
        permissions=["write_project_artifact"],
    )

    with pytest.raises(HarnessError) as exc_info:
        PermissionGate(default_allowed_permissions=[]).ensure_node_allowed(
            node,
            tool_registry=_registry(),
        )

    assert exc_info.value.code == "permission_required"
    assert "write_project_artifact" in exc_info.value.message


def test_rejects_network_permission_without_approval() -> None:
    node = _node("web-search", permissions=["network"])

    with pytest.raises(HarnessError) as exc_info:
        PermissionGate().ensure_node_allowed(node, tool_registry=_registry())

    assert exc_info.value.code == "permission_required"
    assert "network" in exc_info.value.message


def test_allows_permission_when_request_approves_it() -> None:
    node = _node("web-search", permissions=["network"])

    PermissionGate(approved_permissions=["network"]).ensure_node_allowed(
        node,
        tool_registry=_registry(),
    )


def test_uses_tool_manifest_permissions_when_node_permissions_are_empty() -> None:
    node = _node("custom-tool", tool_ref="custom.network_tool", permissions=[])

    with pytest.raises(HarnessError) as exc_info:
        PermissionGate().ensure_node_allowed(node, tool_registry=_registry())

    assert exc_info.value.code == "permission_required"
    assert "network" in exc_info.value.message


def _node(
    node_id: str,
    *,
    tool_ref: str | None = None,
    permissions: list[str],
) -> GraphNode:
    return GraphNode(
        nodeId=node_id,
        nodeType="fixed_tool" if tool_ref else "model",
        displayName=node_id,
        status="waiting",
        toolRef=tool_ref,
        summary="test node",
        createdBy="agent",
        position={"x": 0, "y": 0},
        permissionsRequired=permissions,
    )


def _registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolManifestSpec(
                tool_id="document.typst_compile",
                name="Typst",
                description="Compile local report artifacts.",
                version="1.0.0",
                source_type="local",
                license="internal",
                runtime="python_sidecar",
                entrypoint=None,
                capabilities=["document.export.pdf"],
                operations=[
                    ToolOperationSpec(
                        name="compile_report_pdf",
                        description="Compile a report PDF.",
                    )
                ],
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                permissions=["write_project_outputs"],
                error_codes=[],
                timeout_policy={},
                artifact_policy={},
                security_policy={},
                examples=[],
                node_templates=[],
            ),
            ToolManifestSpec(
                tool_id="custom.network_tool",
                name="Network Tool",
                description="Uses network.",
                version="1.0.0",
                source_type="local",
                license="internal",
                runtime="python_sidecar",
                entrypoint=None,
                capabilities=["web.search"],
                operations=[
                    ToolOperationSpec(name="search", description="Search web.")
                ],
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                permissions=["network"],
                error_codes=[],
                timeout_policy={},
                artifact_policy={},
                security_policy={},
                examples=[],
                node_templates=[],
            ),
        ]
    )
