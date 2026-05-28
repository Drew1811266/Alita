from __future__ import annotations

from pathlib import Path

from agent_service.tool_protocol import (
    ToolResultContent,
    ToolSafetyPolicy,
    UnifiedToolDefinition,
    UnifiedToolError,
    UnifiedToolResult,
)


class RecordingGateway:
    provider_id = "recording"

    def __init__(self, *, fail_code: str | None = None) -> None:
        self.calls = []
        self.fail_code = fail_code

    def list_tools(self):
        return [
            _tool_definition(
                "internal:document.markitdown_convert",
                required=[
                    "operation",
                    "input_path",
                    "output_path",
                ],
                permissions=[
                    "read_project_files",
                    "write_project_outputs",
                    "run_python_plugin",
                ],
            ),
            _tool_definition(
                "internal:document.typst_compile",
                required=[
                    "operation",
                    "title",
                    "outline",
                    "report",
                    "source_output_path",
                    "pdf_output_path",
                ],
                permissions=["write_project_outputs", "run_local_cli"],
            ),
            _tool_definition(
                "internal:document.receive_attachment",
                required=["operation"],
                permissions=["read_project_files"],
            ),
        ]

    def call_tool(self, invocation):
        self.calls.append(invocation)
        if self.fail_code is not None:
            return UnifiedToolResult(
                ok=False,
                content=[],
                structured_content=None,
                artifacts=[],
                metadata={},
                error=UnifiedToolError(
                    code=self.fail_code,
                    message=f"gateway failed: {self.fail_code}",
                    recoverable=False,
                ),
            )

        if invocation.tool_id == "internal:document.markitdown_convert":
            output_path = Path(invocation.arguments["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("# Markdown\n\nparsed text", encoding="utf-8")
            return UnifiedToolResult(
                ok=True,
                content=[
                    ToolResultContent(type="json", value={"text": "parsed text"}),
                    ToolResultContent(type="artifact", path=str(output_path)),
                ],
                structured_content={"text": "parsed text"},
                artifacts=[str(output_path)],
                metadata={"gateway": "recording"},
            )

        if invocation.tool_id == "internal:document.typst_compile":
            source_path = Path(invocation.arguments["source_output_path"])
            pdf_path = Path(invocation.arguments["pdf_output_path"])
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text("typst source", encoding="utf-8")
            pdf_path.write_bytes(b"%PDF-1.7\n")
            return UnifiedToolResult(
                ok=True,
                content=[
                    ToolResultContent(type="json", value={"artifact": str(pdf_path)}),
                    ToolResultContent(type="artifact", path=str(source_path)),
                    ToolResultContent(type="artifact", path=str(pdf_path)),
                ],
                structured_content={
                    "source": str(source_path),
                    "artifact": str(pdf_path),
                },
                artifacts=[str(source_path), str(pdf_path)],
                metadata={"gateway": "recording"},
            )

        if invocation.tool_id == "internal:document.receive_attachment":
            return UnifiedToolResult(
                ok=True,
                content=[],
                structured_content={"paths": ""},
                artifacts=[],
                metadata={},
            )

        raise AssertionError(f"unexpected tool id: {invocation.tool_id}")


def _tool_definition(
    tool_id: str,
    *,
    required: list[str],
    permissions: list[str],
) -> UnifiedToolDefinition:
    return UnifiedToolDefinition(
        id=tool_id,
        source="internal",
        provider_id="internal",
        provider_tool_name=tool_id.removeprefix("internal:"),
        display_name=tool_id,
        description=f"Test definition for {tool_id}",
        capabilities=[],
        input_schema={
            "type": "object",
            "required": required,
            "properties": {key: {"type": "string"} for key in required},
        },
        output_schema={"type": "object"},
        permissions=permissions,
        safety_policy=ToolSafetyPolicy(
            filesystem="project_write",
            network="none",
            user_approval="high_risk_only",
            secrets="none",
            sandbox="not_required",
            max_runtime_ms=60000,
        ),
        timeout_ms=60000,
    )
