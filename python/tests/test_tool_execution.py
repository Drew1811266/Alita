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
from tools.typst_tool import TypstCompileResult


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


def test_tool_executor_routes_typst_pdf_compilation(monkeypatch, tmp_path):
    source = tmp_path / "artifacts" / "typst" / "report.typ"
    pdf = tmp_path / "artifacts" / "typst" / "report.pdf"
    calls = []

    def fake_compile_typst_report_pdf(**kwargs):
        calls.append(kwargs)
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("typst source", encoding="utf-8")
        pdf.write_bytes(b"%PDF-1.7\n")
        return TypstCompileResult(
            source_path=str(source),
            pdf_path=str(pdf),
            artifacts=[str(source), str(pdf)],
            metadata={"compiler": "typst"},
        )

    monkeypatch.setattr(
        "agent_service.tool_execution.compile_typst_report_pdf",
        fake_compile_typst_report_pdf,
    )

    result = ToolExecutor().run(
        ToolInvocation(
            tool_id="document.typst_compile",
            operation="compile_report_pdf",
            arguments={
                "title": "Report",
                "outline": "outline",
                "report": "report",
                "source_output_path": str(source),
                "pdf_output_path": str(pdf),
            },
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
        )
    )

    assert result.values["artifact"] == str(pdf)
    assert result.values["source"] == str(source)
    assert result.artifacts == [str(source), str(pdf)]
    assert calls == [
        {
            "title": "Report",
            "outline": "outline",
            "report": "report",
            "source_output_path": str(source),
            "pdf_output_path": str(pdf),
            "project_path": str(tmp_path / "project.alita"),
            "allowed_roots": [str(tmp_path)],
        }
    ]


def test_tool_executor_routes_virtual_receive_attachment(tmp_path):
    result = ToolExecutor().run(
        ToolInvocation(
            tool_id="document.receive_attachment",
            operation="receive_attachment",
            arguments={"paths": "a\nb"},
            project_path=str(tmp_path / "project.alita"),
            allowed_roots=[str(tmp_path)],
        )
    )

    assert result.values == {"paths": "a\nb"}
    assert result.artifacts == []
    assert result.metadata == {}


def test_tool_executor_uses_registered_adapter_for_manifest_operation(tmp_path):
    calls = []

    def fake_adapter(invocation):
        calls.append(invocation)
        return ToolResult(values={"ok": "true"})

    executor = ToolExecutor(
        adapters={
            ("document.markitdown_convert", "convert_local_file"): fake_adapter,
        }
    )
    invocation = ToolInvocation(
        tool_id="document.markitdown_convert",
        operation="convert_local_file",
        arguments={
            "input_path": str(tmp_path / "source.docx"),
            "output_path": str(tmp_path / "converted.md"),
        },
        project_path=str(tmp_path),
    )

    result = executor.run(invocation)

    assert result.values == {"ok": "true"}
    assert calls == [invocation]


def test_tool_executor_rejects_known_tool_without_adapter(tmp_path):
    package_root = tmp_path / "tool-packages"
    tool_root = package_root / "custom"
    tool_root.mkdir(parents=True)
    (tool_root / "manifest.json").write_text(
        """
{
  "tool_id": "custom.echo",
  "name": "Custom Echo",
  "description": "Test-only manifest tool.",
  "version": "0.1.0",
  "source_type": "external_python_package",
  "license": "internal",
  "runtime": "python_sidecar",
  "capabilities": [],
  "operations": [
    {
      "name": "send_message",
      "description": "Send input."
    }
  ],
  "input_schema": {
    "type": "object",
    "required": ["operation", "message"],
    "properties": {
      "operation": {
        "type": "string",
        "enum": ["send_message"]
      },
      "message": {
        "type": "string"
      }
    }
  },
  "output_schema": {
    "type": "object"
  },
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
    executor = ToolExecutor(registry=ToolRegistry.from_packages_root(package_root))

    with pytest.raises(HarnessError) as exc_info:
        executor.run(
            ToolInvocation(
                tool_id="custom.echo",
                operation="send_message",
                arguments={"message": "hello"},
                project_path=str(tmp_path),
            )
        )

    assert exc_info.value.code == "unsupported_tool"
    assert "custom.echo" in exc_info.value.message
    assert "send_message" in exc_info.value.message


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
