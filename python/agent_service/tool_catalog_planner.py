from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from pydantic import BaseModel, Field

from agent_service.context_manager import ContextBundle, ToolCapability
from agent_service.goal_spec import GoalSpec
from agent_service.schemas import UserMessage
from agent_service.tool_graph_planner import (
    PlannedToolNode,
    ToolActionGraph,
    validate_tool_action_graph,
)
from agent_service.tool_ports import compatible_port_types, port_type_for_schema
from agent_service.tool_protocol import normalize_tool_id, provider_tool_id
from agent_service.tool_registry import ToolManifestSpec, ToolRegistry


TOOL_CATALOG_PLANNER_ID = "tool_catalog.planner.v1"
MAX_TOOL_GRAPH_NODES = 5
CHAIN_TEXT_ARGUMENTS = {"content", "outline", "report", "source_text", "text", "input"}
OUTPUT_KEY_PRIORITY = [
    "text",
    "source_text",
    "report",
    "outline",
    "echo",
    "artifact",
    "artifacts",
    "source",
]


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


@dataclass(frozen=True)
class _CatalogToolPlan:
    selected: ToolCapability
    manifest: ToolManifestSpec
    operation: str
    argument_values: dict[str, Any]
    node_id: str
    missing_arguments: list[str]


@dataclass(frozen=True)
class _GraphStep:
    plan: _CatalogToolPlan
    dependencies: list[str]
    argument_values: dict[str, Any]


@dataclass(frozen=True)
class _DependencyBinding:
    dependencies: list[str]
    argument_values: dict[str, Any]


class ToolCatalogPlanner:
    def __init__(self, *, tool_registry: ToolRegistry) -> None:
        self.tool_registry = tool_registry

    def plan(self, request: ToolCatalogPlanningRequest) -> ToolCatalogPlanningResult:
        selected_tools = _select_tools(
            request.message.content,
            request.context.available_tools,
        )
        if not selected_tools:
            return ToolCatalogPlanningResult(
                planned=False,
                diagnostics=["no catalog tool matched the task"],
            )

        tool_plans: list[_CatalogToolPlan] = []
        diagnostics: list[str] = []
        for selected_tool in selected_tools[:MAX_TOOL_GRAPH_NODES]:
            plan, plan_diagnostics = self._plan_selected_tool(selected_tool, request)
            if plan is None:
                diagnostics.extend(plan_diagnostics)
                continue
            tool_plans.append(plan)
            diagnostics.extend(plan_diagnostics)

        if not tool_plans:
            return ToolCatalogPlanningResult(planned=False, diagnostics=diagnostics)

        graph_steps = _best_tool_graph(tool_plans)
        if not graph_steps:
            return ToolCatalogPlanningResult(
                planned=False,
                diagnostics=diagnostics or _missing_argument_diagnostics(tool_plans[0]),
            )

        action_graph = ToolActionGraph(
            nodes=[
                _planned_tool_node(
                    step.plan,
                    dependencies=step.dependencies,
                    argument_values=step.argument_values,
                )
                for step in graph_steps
            ]
        )
        diagnostics = validate_tool_action_graph(action_graph)
        if diagnostics:
            return ToolCatalogPlanningResult(planned=False, diagnostics=diagnostics)

        fixed_nodes = [
            _fixed_tool_node(
                node_id=step.plan.node_id,
                manifest=step.plan.manifest,
                operation=step.plan.operation,
                argument_values=step.argument_values,
                dependencies=step.dependencies,
                position={"x": 260 + (index * 300), "y": 180},
            )
            for index, step in enumerate(graph_steps)
        ]
        last_node_id = graph_steps[-1].plan.node_id
        first_plan = graph_steps[0].plan
        graph_payload = {
            "graphId": f"{request.task_id}-graph",
            "nodes": [
                *fixed_nodes,
                _output_node(dependency=last_node_id),
            ],
            "edges": [
                *[
                    {
                        "id": f"{dependency}-{step.plan.node_id}",
                        "source": dependency,
                        "target": step.plan.node_id,
                    }
                    for step in graph_steps
                    for dependency in step.dependencies
                ],
                {
                    "id": f"{last_node_id}-task-output",
                    "source": last_node_id,
                    "target": "task-output",
                },
            ],
            "metadata": {
                "kind": "task",
                "toolCatalogPlanner": {
                    "toolId": normalize_tool_id(first_plan.manifest.tool_id),
                    "operation": first_plan.operation,
                    "toolIds": [
                        normalize_tool_id(step.plan.manifest.tool_id)
                        for step in graph_steps
                    ],
                    "operations": [
                        step.plan.operation for step in graph_steps
                    ],
                },
                "userMessage": request.message.content,
            },
        }
        return ToolCatalogPlanningResult(planned=True, graph_payload=graph_payload)

    def _plan_selected_tool(
        self,
        selected: ToolCapability,
        request: ToolCatalogPlanningRequest,
    ) -> tuple[_CatalogToolPlan | None, list[str]]:
        try:
            manifest = self.tool_registry.get(provider_tool_id(selected.tool_id))
        except KeyError:
            return None, [f"catalog tool is unavailable: {selected.tool_id}"]

        operation = _operation_for_message(manifest, request.message.content)
        if operation is None:
            return None, [f"catalog tool has no matching operation: {manifest.tool_id}"]

        argument_values, diagnostics = _argument_values_for_tool(
            manifest,
            operation=operation,
            message=request.message,
            context=request.context,
        )

        return (
            _CatalogToolPlan(
                selected=selected,
                manifest=manifest,
                operation=operation,
                argument_values=argument_values,
                node_id=_node_id_for_tool(manifest.tool_id),
                missing_arguments=_missing_arguments_from_diagnostics(diagnostics),
            ),
            diagnostics,
        )


def _best_tool_graph(plans: list[_CatalogToolPlan]) -> list[_GraphStep]:
    best: list[_GraphStep] = []
    root_plans = [plan for plan in plans if not plan.missing_arguments]
    for root_plan in root_plans:
        root_step = _GraphStep(
            plan=root_plan,
            dependencies=[],
            argument_values=dict(root_plan.argument_values),
        )
        best = _extend_tool_graph(
            steps=[root_step],
            remaining=[plan for plan in plans if plan is not root_plan],
            best=best,
        )
    return best


def _extend_tool_graph(
    *,
    steps: list[_GraphStep],
    remaining: list[_CatalogToolPlan],
    best: list[_GraphStep],
) -> list[_GraphStep]:
    if len(steps) > len(best):
        best = list(steps)
    if len(steps) >= MAX_TOOL_GRAPH_NODES:
        return best

    for plan in remaining:
        binding = _dependency_binding_for_plan(plan, steps)
        if binding is None:
            continue
        step = _GraphStep(
            plan=plan,
            dependencies=binding.dependencies,
            argument_values={**plan.argument_values, **binding.argument_values},
        )
        best = _extend_tool_graph(
            steps=[*steps, step],
            remaining=[candidate for candidate in remaining if candidate is not plan],
            best=best,
        )
    return best


def _dependency_binding_for_plan(
    plan: _CatalogToolPlan,
    previous_steps: list[_GraphStep],
) -> _DependencyBinding | None:
    dependencies: list[str] = []
    argument_values: dict[str, Any] = {}
    required_arguments = _required_arguments(plan.manifest)
    candidate_arguments = [
        argument
        for argument in required_arguments
        if argument != "operation"
        and (argument in plan.missing_arguments or argument in CHAIN_TEXT_ARGUMENTS)
    ]
    for argument in candidate_arguments:
        source = _compatible_source_for_argument(
            argument=argument,
            plan=plan,
            previous_steps=previous_steps,
        )
        if source is None:
            if argument in plan.missing_arguments:
                return None
            continue
        dependency, output_key = source
        argument_values[argument] = f"{{{dependency}.{output_key}}}"
        if dependency not in dependencies:
            dependencies.append(dependency)

    if plan.missing_arguments and not all(
        argument in argument_values for argument in plan.missing_arguments
    ):
        return None
    if not dependencies:
        return None
    return _DependencyBinding(
        dependencies=dependencies,
        argument_values=argument_values,
    )


def _compatible_source_for_argument(
    *,
    argument: str,
    plan: _CatalogToolPlan,
    previous_steps: list[_GraphStep],
) -> tuple[str, str] | None:
    argument_schema = _schema_property(plan.manifest.input_schema, argument)
    argument_type = port_type_for_schema(argument, argument_schema)
    for step in reversed(previous_steps):
        output_properties = _schema_properties(step.plan.manifest.output_schema)
        for output_key in _ordered_output_keys(output_properties):
            output_type = port_type_for_schema(output_key, output_properties[output_key])
            if compatible_port_types(output_type, argument_type):
                return step.plan.node_id, output_key
    return None


def _ordered_output_keys(properties: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(
        properties,
        key=lambda key: (
            OUTPUT_KEY_PRIORITY.index(key)
            if key in OUTPUT_KEY_PRIORITY
            else len(OUTPUT_KEY_PRIORITY),
            key,
        ),
    )


def _schema_properties(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return {}
    return {
        str(name): dict(property_schema or {})
        for name, property_schema in properties.items()
    }


def _schema_property(schema: dict[str, Any], name: str) -> dict[str, Any]:
    return _schema_properties(schema).get(name, {})


def _missing_arguments_from_diagnostics(diagnostics: list[str]) -> list[str]:
    prefix = "missing binding value for required argument: "
    return [
        diagnostic.removeprefix(prefix)
        for diagnostic in diagnostics
        if diagnostic.startswith(prefix)
    ]


def _missing_argument_diagnostics(plan: _CatalogToolPlan) -> list[str]:
    return [
        f"missing binding value for required argument: {argument}"
        for argument in plan.missing_arguments
    ]


def _select_tool(
    content: str,
    tools: list[ToolCapability],
) -> ToolCapability | None:
    selected = _select_tools(content, tools)
    return selected[0] if selected else None


def _select_tools(
    content: str,
    tools: list[ToolCapability],
) -> list[ToolCapability]:
    text_tokens = _signal_tokens(content)
    scored: list[tuple[int, int, ToolCapability]] = []
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
            scored.append((_tool_position(content, tool), score, tool))
    if not scored:
        return []
    scored.sort(key=lambda item: (item[0], -item[1], item[2].tool_id))
    return [tool for _, _, tool in scored]


def _tool_position(content: str, tool: ToolCapability) -> int:
    normalized_content = content.lower()
    haystack = " ".join(
        [
            tool.tool_id,
            tool.name,
            " ".join(tool.capabilities),
            " ".join(tool.operations),
        ]
    )
    positions = [
        normalized_content.find(token)
        for token in _signal_tokens(haystack)
        if normalized_content.find(token) >= 0
    ]
    return min(positions) if positions else len(normalized_content)


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
        elif argument == "title":
            values[argument] = Path(context.project_path).stem or message.task_id
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


def _planned_tool_node(
    plan: _CatalogToolPlan,
    *,
    dependencies: list[str],
    argument_values: dict[str, Any],
) -> PlannedToolNode:
    return PlannedToolNode(
        node_id=plan.node_id,
        tool_id=normalize_tool_id(plan.manifest.tool_id),
        operation=plan.operation,
        arguments=dict(argument_values),
        dependencies=list(dependencies),
        required_arguments=_required_arguments(plan.manifest),
        input_schema=dict(plan.manifest.input_schema),
        output_schema=dict(plan.manifest.output_schema),
    )


def _can_chain_tool_plans(
    first_plan: _CatalogToolPlan,
    second_plan: _CatalogToolPlan,
) -> bool:
    return _has_text_output(first_plan.manifest) and (
        _chain_target_argument(second_plan) is not None
    )


def _has_text_output(manifest: ToolManifestSpec) -> bool:
    properties = manifest.output_schema.get("properties", {})
    return isinstance(properties, dict) and "text" in properties


def _chain_target_argument(plan: _CatalogToolPlan) -> str | None:
    for argument in _required_arguments(plan.manifest):
        if argument in CHAIN_TEXT_ARGUMENTS:
            return argument
    return None


def _fixed_tool_node(
    *,
    node_id: str,
    manifest: ToolManifestSpec,
    operation: str,
    argument_values: dict[str, Any],
    dependencies: list[str] | None = None,
    position: dict[str, float] | None = None,
) -> dict[str, Any]:
    template = manifest.node_templates[0] if manifest.node_templates else {}
    return {
        "nodeId": node_id,
        "nodeType": "fixed_tool",
        "displayName": template.get("displayName") or manifest.name,
        "status": "waiting",
        "inputPorts": list(template.get("inputPorts") or []),
        "outputPorts": list(template.get("outputPorts") or []),
        "dependencies": list(dependencies or []),
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
        "position": position or {"x": 260, "y": 180},
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
