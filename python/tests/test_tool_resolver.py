from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_service.tool_registry import ToolRegistry
from agent_service.tool_resolver import (
    ToolResolutionError,
    resolve_tool_binding,
)


def write_manifest(
    root: Path,
    tool_id: str = "document.markitdown_convert",
    *,
    capabilities: list[str] | None = None,
    operation: str = "convert_local_file",
    permissions: list[str] | None = None,
) -> Path:
    package_root = root / tool_id
    package_root.mkdir()
    manifest_path = package_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "tool_id": tool_id,
                "name": "MarkItDown Convert",
                "description": "Convert a local document into Markdown.",
                "version": "1.0.0",
                "source_type": "local_package",
                "license": "MIT",
                "runtime": "python_sidecar",
                "entrypoint": "tools.markitdown_tool:convert",
                "capabilities": capabilities or ["document_conversion"],
                "operations": [
                    {
                        "name": operation,
                        "description": "Convert a local file.",
                    }
                ],
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "permissions": permissions or ["read_project_files"],
                "examples": [{"input": {"path": "sample.pdf"}}],
                "error_codes": ["conversion_failed"],
                "timeout_policy": {"seconds": 60},
                "artifact_policy": {"writes_artifacts": True},
                "security_policy": {"network": False, "plugins": False},
                "node_templates": [],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_resolves_markitdown_by_capability_and_operation(tmp_path: Path) -> None:
    write_manifest(tmp_path)
    registry = ToolRegistry.from_packages_root(tmp_path)

    binding = resolve_tool_binding(
        registry=registry,
        required_capability="document_conversion",
        operation="convert_local_file",
    )

    assert binding.tool_id == "document.markitdown_convert"
    assert binding.operation == "convert_local_file"
    assert binding.arguments_template == {}
    assert binding.required_permissions == ["read_project_files"]
    assert "document_conversion" in binding.binding_reason
    assert "document.markitdown_convert" in binding.binding_reason


def test_resolver_rejects_disabled_tool(tmp_path: Path) -> None:
    write_manifest(tmp_path)
    registry = ToolRegistry.from_packages_root(tmp_path)

    with pytest.raises(
        ToolResolutionError,
        match="document_conversion.*convert_local_file",
    ):
        resolve_tool_binding(
            registry=registry,
            required_capability="document_conversion",
            operation="convert_local_file",
            disabled_tool_ids=["document.markitdown_convert"],
        )


def test_resolver_rejects_missing_capability(tmp_path: Path) -> None:
    write_manifest(tmp_path, capabilities=["document_conversion"])
    registry = ToolRegistry.from_packages_root(tmp_path)

    with pytest.raises(
        ToolResolutionError,
        match="image_generation.*convert_local_file",
    ):
        resolve_tool_binding(
            registry=registry,
            required_capability="image_generation",
            operation="convert_local_file",
        )
