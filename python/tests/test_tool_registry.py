import json
from pathlib import Path

import pytest

from agent_service.tool_registry import ToolRegistry


def write_manifest(
    root: Path, tool_id: str, operation: str = "convert_local_file"
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
                "capabilities": ["document_conversion"],
                "operations": [
                    {
                        "name": operation,
                        "description": "Convert a local file.",
                    }
                ],
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "permissions": ["read_project_files"],
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


def test_loads_manifests_and_virtual_document_input_tool(tmp_path: Path) -> None:
    write_manifest(tmp_path, "document.markitdown_convert")

    registry = ToolRegistry.from_packages_root(tmp_path)

    assert registry.get("document.markitdown_convert").tool_id == (
        "document.markitdown_convert"
    )
    assert registry.get("document.receive_attachment").tool_id == (
        "document.receive_attachment"
    )
    assert registry.has_operation("document.markitdown_convert", "convert_local_file")


def test_filters_disabled_tools(tmp_path: Path) -> None:
    write_manifest(tmp_path, "document.markitdown_convert")
    registry = ToolRegistry.from_packages_root(tmp_path)

    enabled_tool_ids = {
        tool.tool_id
        for tool in registry.enabled_tools(
            disabled_tool_ids=["document.markitdown_convert"]
        )
    }

    assert "document.markitdown_convert" not in enabled_tool_ids
    assert "document.receive_attachment" in enabled_tool_ids


def test_unknown_tool_raises_key_error(tmp_path: Path) -> None:
    registry = ToolRegistry.from_packages_root(tmp_path)

    with pytest.raises(KeyError, match="missing.tool"):
        registry.get("missing.tool")


def test_loads_real_tool_packages_with_legacy_document_manifest() -> None:
    packages_root = Path(__file__).resolve().parents[2] / "tool-packages"
    registry = ToolRegistry.from_packages_root(packages_root)

    markitdown = registry.get("document.markitdown_convert")
    assert "read_project_files" in markitdown.permissions

    typst = registry.get("document.typst_compile")
    assert registry.has_operation("document.typst_compile", "compile_report_pdf")
    assert "write_project_outputs" in typst.permissions

    document_tool = registry.get("document.read_write")
    assert document_tool.runtime is None
