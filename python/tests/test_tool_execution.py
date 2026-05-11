from pathlib import Path

import pytest

from agent_service.harness_errors import HarnessError
from agent_service.tool_execution import (
    ToolExecutor,
    ToolInvocation,
    ToolResult,
    resolve_tool_packages_root,
)
from agent_service.tool_registry import ToolRegistry
from tools.markitdown_tool import MarkItDownResult


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = PROJECT_ROOT / "python"
TOOL_PACKAGES_ROOT = PROJECT_ROOT / "tool-packages"


def test_tool_result_defaults_are_empty_containers():
    result = ToolResult()

    assert result.values == {}
    assert result.artifacts == []
    assert result.metadata == {}

    other = ToolResult()
    assert other.values is not result.values
    assert other.artifacts is not result.artifacts
    assert other.metadata is not result.metadata


def test_tool_executor_routes_markitdown_conversion(monkeypatch, tmp_path):
    output = tmp_path / "converted.md"
    calls = []

    def fake_convert_markitdown_local_file(**kwargs):
        calls.append(kwargs)
        output.write_text("# markdown", encoding="utf-8")
        return MarkItDownResult(
            text="# markdown",
            artifacts=[str(output)],
            metadata={"converter": "markitdown"},
        )

    monkeypatch.setattr(
        "agent_service.tool_execution.convert_markitdown_local_file",
        fake_convert_markitdown_local_file,
    )

    result = ToolExecutor().run(
        ToolInvocation(
            tool_id="document.markitdown_convert",
            operation="convert_local_file",
            arguments={
                "input_path": str(tmp_path / "source.docx"),
                "output_path": str(output),
            },
            project_path=str(tmp_path),
            allowed_roots=[str(tmp_path)],
        )
    )

    assert result.values["text"] == "# markdown"
    assert result.artifacts == [str(output)]
    assert calls == [
        {
            "input_path": str(tmp_path / "source.docx"),
            "output_path": str(output),
            "project_path": str(tmp_path),
            "allowed_roots": [str(tmp_path)],
        }
    ]


def test_tool_executor_default_registry_finds_tools_from_python_cwd(monkeypatch):
    monkeypatch.chdir(PYTHON_ROOT)

    executor = ToolExecutor()

    assert executor.registry.get("document.markitdown_convert").tool_id == (
        "document.markitdown_convert"
    )


def test_resolve_tool_packages_root_prefers_packaged_manifest_root(tmp_path):
    packaged_root = tmp_path / "packaged" / "tool-packages"
    markitdown_root = packaged_root / "markitdown"
    markitdown_root.mkdir(parents=True)
    (markitdown_root / "manifest.json").write_text("{}", encoding="utf-8")
    missing_root = tmp_path / "missing" / "tool-packages"

    selected = resolve_tool_packages_root([missing_root, packaged_root, TOOL_PACKAGES_ROOT])

    assert selected == packaged_root


def test_tool_executor_rejects_unknown_tool():
    invocation = ToolInvocation(
        tool_id="unknown.tool",
        operation="run",
        arguments={},
        project_path=".",
    )

    with pytest.raises(HarnessError) as exc_info:
        ToolExecutor().run(invocation)

    assert exc_info.value.code == "unsupported_tool"
    assert "unknown.tool" in exc_info.value.message


def test_tool_executor_rejects_unsupported_manifest_operation():
    registry = ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)
    executor = ToolExecutor(registry=registry)
    invocation = ToolInvocation(
        tool_id="document.markitdown_convert",
        operation="delete_file",
        arguments={
            "operation": "delete_file",
            "input_path": "a.md",
            "output_path": "b.md",
        },
        project_path=".",
    )

    with pytest.raises(HarnessError) as exc_info:
        executor.run(invocation)

    assert exc_info.value.code == "unsupported_operation"


def test_tool_executor_validates_manifest_input_schema():
    registry = ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)
    executor = ToolExecutor(registry=registry)
    invocation = ToolInvocation(
        tool_id="document.markitdown_convert",
        operation="convert_local_file",
        arguments={
            "operation": "convert_local_file",
            "output_path": "b.md",
        },
        project_path=".",
    )

    with pytest.raises(HarnessError) as exc_info:
        executor.run(invocation)

    assert exc_info.value.code == "invalid_tool_input"
    assert "input_path" in exc_info.value.message
