from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from agent_service.context_manager import ContextBundle, ToolCapability
from agent_service.goal_spec import GoalSpec
from agent_service.schemas import UserMessage
from agent_service.tool_protocol import normalize_tool_id, provider_tool_id
from agent_service.tool_registry import ToolManifestSpec, ToolRegistry


TOOL_CATALOG_PLANNER_ID = "tool_catalog.planner.v1"


class ToolCatalogPlanningRequest(BaseModel):
    task_id: str
    message: UserMessage
    goal_spec: GoalSpec
    context: ContextBundle


class ToolCatalogPlanningResult(BaseModel):
    planned: bool
    planner: str = TOOL_CATALOG_PLANNER_ID
    graph_payload: dict[str, Any] | None = None
    diagnostics: list[str] = Field(default_factory=list)


class ToolCatalogPlanner:
    def __init__(self, *, tool_registry: ToolRegistry) -> None:
        self.tool_registry = tool_registry

    def plan(self, request: ToolCatalogPlanningRequest) -> ToolCatalogPlanningResult:
        selected = _select_tool(request.message.content, request.context.available_tools)
        if selected is None:
            return ToolCatalogPlanningResult(
                planned=False,
                diagnostics=["no catalog tool matched the task"],
            )

        try:
            manifest = self.tool_registry.get(provider_tool_id(selected.tool_id))
        except KeyError:
            return ToolCatalogPlanningResult(
                planned=False,
                diagnostics=[f"catalog tool is unavailable: {selected.tool_id}"],
            )

        operation = _operation_for_message(manifest, request.message.content)
        if operation is None:
            return ToolCatalogPlanningResult(
                planned=False,
                diagnostics=[f"catalog tool has no matching operation: {manifest.tool_id}"],
            )

        argument_values, diagnostics = _argument_values_for_tool(
            manifest,
            operation=operation,
            message=request.message,
            context=request.context,
        )
        if diagnostics:
            return ToolCatalogPlanningResult(planned=False, diagnostics=diagnostics)

        node_id = _node_id_for_tool(manifest.tool_id)
        graph_payload = {
            "graphId": f"{request.task_id}-graph",
            "nodes": [
                _fixed_tool_node(
                    node_id=node_id,
                    manifest=manifest,
                    operation=operation,
                    argument_values=argument_values,
                ),
                _output_node(dependency=node_id),
            ],
            "edges": [
                {
                    "id": f"{node_id}-task-output",
                    "source": node_id,
                    "target": "task-output",
                }
            ],
            "metadata": {
                "kind": "task",
                "toolCatalogPlanner": {
                    "toolId": normalize_tool_id(manifest.tool_id),
                    "operation": operation,
                },
                "userMessage": request.message.content,
            },
        }
        return ToolCatalogPlanningResult(planned=True, graph_payload=graph_payload)


def _select_tool(
    content: str,
    tools: list[ToolCapability],
) -> ToolCapability | None:
    text_tokens = _signal_tokens(content)
    scored: list[tuple[int, ToolCapability]] = []
    for tool in tools:
        haystack = " ".join(
            [
                tool.tool_id,
                tool.name,
                " ".join(tool.capabilities),
                " ".join(tool.operations),
            ]
        )
        score = len(text_tokens & _signal_tokens(haystack))
        if score >= 2:
            scored.append((score, tool))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1].tool_id))
    return scored[0][1]


def _signal_tokens(value: str) -> set[str]:
    return {
        token
        for token in _tokens(value)
        if len(token) >= 3
        and token
        not in {
            "and",
            "for",
            "the",
            "this",
            "that",
            "tool",
            "tools",
            "use",
            "using",
            "write",
        }
    }


def _tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-zA-Z0-9]+", value.lower()) if token]


def _operation_for_message(manifest: ToolManifestSpec, content: str) -> str | None:
    if len(manifest.operations) == 1:
        return manifest.operations[0].name
    operation_values = (
        manifest.input_schema.get("properties", {})
        .get("operation", {})
        .get("enum", [])
    )
    if len(operation_values) == 1:
        return str(operation_values[0])
    text_tokens = _signal_tokens(content)
    scored: list[tuple[int, str]] = []
    for operation in manifest.operations:
        haystack = f"{operation.name} {operation.description}"
        score = len(text_tokens & _signal_tokens(haystack))
        if score > 0:
            scored.append((score, operation.name))
    if scored:
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][1]
    return None


def _argument_values_for_tool(
    manifest: ToolManifestSpec,
    *,
    operation: str,
    message: UserMessage,
    context: ContextBundle,
) -> tuple[dict[str, Any], list[str]]:
    values: dict[str, Any] = {"operation": operation}
    diagnostics: list[str] = []
    for argument in _required_arguments(manifest):
        if argument == "operation":
            continue
        if argument in {"message", "query"}:
            values[argument] = message.content
        elif argument in {"source_text", "text", "input"}:
            values[argument] = message.content
        elif argument == "input_path":
            if message.attachments:
                values[argument] = message.attachments[0].path
            else:
                diagnostics.append(
                    f"missing binding value for required argument: {argument}"
                )
        elif argument == "input_paths":
            if message.attachments:
                values[argument] = [
                    attachment.path for attachment in message.attachments
                ]
            else:
                values[argument] = []
        elif argument == "output_path":
            values[argument] = _artifact_path(
                task_id=message.task_id,
                tool_id=manifest.tool_id,
                suffix=".md",
            )
        elif argument == "source_output_path":
            values[argument] = _artifact_path(
                task_id=message.task_id,
                tool_id=manifest.tool_id,
                suffix=".typ",
            )
        elif argument == "pdf_output_path":
            values[argument] = _artifact_path(
                task_id=message.task_id,
                tool_id=manifest.tool_id,
                suffix=".pdf",
            )
        elif argument == "metadata_value":
            values[argument] = "tool_catalog"
        else:
            diagnostics.append(
                f"missing binding value for required argument: {argument}"
            )
    return values, diagnostics


def _artifact_path(*, task_id: str, tool_id: str, suffix: str) -> str:
    return f"artifacts/{_safe_name(task_id)}-{_safe_name(tool_id)}{suffix}"


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _required_arguments(manifest: ToolManifestSpec) -> list[str]:
    return [str(value) for value in manifest.input_schema.get("required", [])]


def _fixed_tool_node(
    *,
    node_id: str,
    manifest: ToolManifestSpec,
    operation: str,
    argument_values: dict[str, Any],
) -> dict[str, Any]:
    template = manifest.node_templates[0] if manifest.node_templates else {}
    return {
        "nodeId": node_id,
        "nodeType": "fixed_tool",
        "displayName": template.get("displayName") or manifest.name,
        "status": "waiting",
        "inputPorts": list(template.get("inputPorts") or []),
        "outputPorts": list(template.get("outputPorts") or []),
        "dependencies": [],
        "toolRef": normalize_tool_id(manifest.tool_id),
        "toolBinding": {
            "providerId": "internal",
            "operation": operation,
            "argumentsTemplate": {
                "values": argument_values,
                "required": _required_arguments(manifest),
            },
            "outputSchema": dict(manifest.output_schema),
            "permissionScope": {
                "permissions": list(manifest.permissions),
                "timeoutMs": int(manifest.timeout_policy.get("seconds", 60)) * 1000,
            },
        },
        "summary": manifest.description,
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "permissionsRequired": list(manifest.permissions),
        "position": {"x": 260, "y": 180},
    }


def _output_node(*, dependency: str) -> dict[str, Any]:
    return {
        "nodeId": "task-output",
        "nodeType": "output",
        "displayName": "输出结果",
        "status": "waiting",
        "inputPorts": [{"id": "result-input", "label": "结果", "dataType": "json"}],
        "outputPorts": [{"id": "result-output", "label": "结果", "dataType": "json"}],
        "dependencies": [dependency],
        "summary": "汇总工具执行结果。",
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "permissionsRequired": [],
        "position": {"x": 260, "y": 360},
    }


def _node_id_for_tool(tool_id: str) -> str:
    safe = re.sub(r"[^a-z0-9]+", "-", tool_id.lower()).strip("-")
    return f"tool-{safe}"
