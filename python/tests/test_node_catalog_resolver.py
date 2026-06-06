from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.node_catalog import (
    NodeAvailability,
    NodeCatalogBuilder,
    NodeCatalogSnapshot,
    NodeDefinition,
    NodeExecutionBinding,
    NodePermissionProfile,
)
from agent_service.node_catalog_resolver import (
    NodeCatalogResolutionError,
    NodeCatalogResolver,
)
from agent_service.tool_registry import ToolRegistry


def _registry() -> ToolRegistry:
    return ToolRegistry.from_packages_root(
        Path(__file__).resolve().parents[2] / "tool-packages"
    )


def _node(
    node_id: str,
    *,
    capabilities: list[str],
    risk_level: str = "medium",
    availability_status: str = "available",
) -> NodeDefinition:
    return NodeDefinition(
        node_id=node_id,
        kind="tool",
        display_name=f"Display {node_id}",
        description=f"Description for {node_id}.",
        category="document",
        capabilities=capabilities,
        input_ports=[],
        output_ports=[],
        execution=NodeExecutionBinding(
            type="tool",
            tool_id=f"tool.{node_id}",
            operation="run",
        ),
        permissions=NodePermissionProfile(risk_level=risk_level),
        examples=[],
        source="internal_tool",
        availability=NodeAvailability(status=availability_status),
    )


def _resolver(*nodes: NodeDefinition) -> NodeCatalogResolver:
    return NodeCatalogResolver(NodeCatalogSnapshot(nodes=list(nodes)))


def test_resolve_prefers_available_matching_node_id() -> None:
    resolver = _resolver(
        _node("document.write_markdown", capabilities=["document.write"]),
        _node("document.write_docx", capabilities=["document.write"]),
    )

    resolution = resolver.resolve(
        required_capabilities=["document.write"],
        preferred_node_ids=["document.write_docx"],
    )

    assert resolution.node.node_id == "document.write_docx"
    assert resolution.selection_reason == "preferred_node_id:document.write_docx"


def test_resolve_ranks_equal_matches_by_lower_risk() -> None:
    resolver = _resolver(
        _node(
            "document.read.high_risk",
            capabilities=["document.read"],
            risk_level="high",
        ),
        _node(
            "document.read.low_risk",
            capabilities=["document.read"],
            risk_level="low",
        ),
    )

    resolution = resolver.resolve(
        required_capabilities=["document.read"],
        preferred_node_ids=[],
    )

    assert resolution.node.node_id == "document.read.low_risk"
    assert resolution.selection_reason == "ranked_match:document.read"


def test_resolve_exact_node_id_match_beats_lower_risk_generic_match() -> None:
    resolver = _resolver(
        _node(
            "generic.document.converter",
            capabilities=["document.convert.markdown"],
            risk_level="low",
        ),
        _node(
            "document.convert.markdown",
            capabilities=["document.convert.markdown"],
            risk_level="high",
        ),
    )

    resolution = resolver.resolve(
        required_capabilities=["document.convert.markdown"],
        preferred_node_ids=[],
    )

    assert resolution.node.node_id == "document.convert.markdown"
    assert resolution.selection_reason == "matched_node_id:document.convert.markdown"


def test_resolve_excludes_unavailable_nodes() -> None:
    resolver = _resolver(
        _node(
            "document.read.unavailable",
            capabilities=["document.read"],
            risk_level="low",
            availability_status="unavailable",
        ),
        _node(
            "document.read.available",
            capabilities=["document.read"],
            risk_level="high",
        ),
    )

    resolution = resolver.resolve(
        required_capabilities=["document.read"],
        preferred_node_ids=["document.read.unavailable"],
    )

    assert resolution.node.node_id == "document.read.available"


def test_resolve_excludes_unavailable_default_document_read_node() -> None:
    resolver = NodeCatalogResolver(
        NodeCatalogBuilder(tool_registry=_registry()).build()
    )

    with pytest.raises(NodeCatalogResolutionError) as error:
        resolver.resolve(
            required_capabilities=["document.read"],
            preferred_node_ids=[],
        )

    assert error.value.code == "unsupported_capability"
    assert error.value.capabilities == ["document.read"]


def test_resolve_mixed_tool_and_model_capabilities_uses_specific_tool_node() -> None:
    resolver = _resolver(
        _node(
            "model.reasoning",
            capabilities=["model.reasoning"],
            risk_level="low",
        ),
        _node(
            "document.read",
            capabilities=["document.read"],
            risk_level="high",
        ),
    )

    resolution = resolver.resolve(
        required_capabilities=["document.read", "model.reasoning"],
        preferred_node_ids=[],
    )

    assert resolution.node.node_id == "document.read"
    assert resolution.matched_capabilities == ["document.read"]
    assert resolution.selection_reason == "matched_node_id:document.read"


def test_resolve_rejects_partial_specific_capability_matches() -> None:
    resolver = _resolver(
        _node(
            "document.read",
            capabilities=["document.read"],
            risk_level="low",
        ),
        _node(
            "document.render.typst_pdf",
            capabilities=["document.render.typst_pdf"],
            risk_level="medium",
        ),
    )

    with pytest.raises(NodeCatalogResolutionError) as error:
        resolver.resolve(
            required_capabilities=[
                "document.read",
                "document.render.typst_pdf",
            ],
            preferred_node_ids=[],
        )

    assert error.value.code == "unsupported_capability"
    assert error.value.capabilities == [
        "document.read",
        "document.render.typst_pdf",
    ]


def test_resolve_raises_unsupported_capability_error() -> None:
    resolver = _resolver(
        _node("document.read", capabilities=["document.read"]),
    )

    with pytest.raises(NodeCatalogResolutionError) as error:
        resolver.resolve(
            required_capabilities=["document.render.typst_pdf"],
            preferred_node_ids=[],
        )

    assert error.value.code == "unsupported_capability"
    assert error.value.capabilities == ["document.render.typst_pdf"]
