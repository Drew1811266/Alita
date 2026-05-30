from __future__ import annotations

from agent_service.tool_execution import ToolResult


def echo_values(invocation) -> ToolResult:
    return ToolResult(
        values={
            "echo": str(invocation.arguments["message"]),
            "source_text": str(invocation.arguments["source_text"]),
            "metadata_value": str(invocation.arguments["metadata_value"]),
        },
        metadata={"runtime": "python_function"},
    )
