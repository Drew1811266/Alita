from __future__ import annotations

from dataclasses import dataclass
import re

from agent_service.tool_gateway import UnifiedToolGateway
from agent_service.tool_protocol import (
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)


@dataclass(frozen=True)
class ModelToolCall:
    id: str
    name: str
    arguments: dict


class ModelToolNameMap:
    def __init__(self, tool_to_model: dict[str, str]) -> None:
        self._tool_to_model = dict(tool_to_model)
        self._model_to_tool = {model: tool for tool, model in tool_to_model.items()}

    @classmethod
    def from_tools(cls, tools: list[UnifiedToolDefinition]) -> "ModelToolNameMap":
        return cls({tool.id: model_safe_tool_name(tool.id) for tool in tools})

    def model_name_for_tool_id(self, tool_id: str) -> str:
        return self._tool_to_model[tool_id]

    def tool_id_for_model_name(self, model_name: str) -> str:
        return self._model_to_tool[model_name]


def to_openai_tool_schema(tool: UnifiedToolDefinition) -> dict:
    return {
        "type": "function",
        "function": {
            "name": model_safe_tool_name(tool.id),
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def model_safe_tool_name(tool_id: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_]", "__", tool_id)
    value = re.sub(r"__+", "__", value).strip("_")
    return value[:64]


def execute_model_tool_calls(
    tool_calls: list[ModelToolCall],
    *,
    name_map: ModelToolNameMap,
    gateway: UnifiedToolGateway,
    base_invocation: UnifiedToolInvocation,
) -> list[UnifiedToolResult]:
    results: list[UnifiedToolResult] = []
    for call in tool_calls:
        tool_id = name_map.tool_id_for_model_name(call.name)
        results.append(
            gateway.call_tool(
                UnifiedToolInvocation(
                    invocation_id=call.id,
                    run_id=base_invocation.run_id,
                    task_id=base_invocation.task_id,
                    node_id=base_invocation.node_id,
                    tool_id=tool_id,
                    arguments=dict(call.arguments),
                    project_path=base_invocation.project_path,
                    allowed_roots=list(base_invocation.allowed_roots),
                    requested_permissions=list(base_invocation.requested_permissions),
                    approval_token=base_invocation.approval_token,
                    model_session_id=base_invocation.model_session_id,
                )
            )
        )
    return results
