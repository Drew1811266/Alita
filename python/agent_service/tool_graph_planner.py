from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from agent_service.tool_ports import compatible_port_types, port_type_for_schema


class PlannedToolNode(BaseModel):
    node_id: str
    tool_id: str
    operation: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    required_arguments: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


class ToolActionGraph(BaseModel):
    nodes: list[PlannedToolNode]


def validate_tool_action_graph(graph: ToolActionGraph) -> list[str]:
    diagnostics: list[str] = []
    known = {node.node_id: node for node in graph.nodes}
    for node in graph.nodes:
        for dependency in node.dependencies:
            if dependency not in known:
                diagnostics.append(
                    f"node {node.node_id} depends on missing node: {dependency}"
                )
        for argument in node.required_arguments:
            value = node.arguments.get(argument)
            if value is None or value == "":
                diagnostics.append(
                    f"node {node.node_id} missing required argument: {argument}"
                )
        for argument, argument_value in node.arguments.items():
            for dependency, output_key in _argument_output_refs(argument_value):
                if dependency not in known:
                    diagnostics.append(
                        f"node {node.node_id} maps missing dependency {dependency}"
                    )
                    continue
                if dependency not in node.dependencies:
                    diagnostics.append(
                        f"node {node.node_id} maps undeclared dependency {dependency}"
                    )
                dependency_node = known[dependency]
                if not _output_schema_has_key(
                    dependency_node.output_schema,
                    output_key,
                ):
                    diagnostics.append(
                        f"node {node.node_id} maps missing output {dependency}.{output_key}"
                    )
                    continue
                if not _mapped_ports_are_compatible(
                    output_schema=dependency_node.output_schema,
                    output_key=output_key,
                    input_schema=node.input_schema,
                    argument=argument,
                ):
                    diagnostics.append(
                        "node "
                        f"{node.node_id} maps incompatible port "
                        f"{dependency}.{output_key} -> {argument}"
                    )
    return diagnostics


def _argument_output_refs(arguments: Any) -> list[tuple[str, str]]:
    if isinstance(arguments, str):
        return [
            (match.group(1), match.group(2).split(".", maxsplit=1)[0])
            for match in re.finditer(r"\{([a-zA-Z0-9_-]+)\.([a-zA-Z0-9_.-]+)\}", arguments)
        ]
    if isinstance(arguments, list):
        refs: list[tuple[str, str]] = []
        for item in arguments:
            refs.extend(_argument_output_refs(item))
        return refs
    if isinstance(arguments, dict):
        refs: list[tuple[str, str]] = []
        for item in arguments.values():
            refs.extend(_argument_output_refs(item))
        return refs
    return []


def _output_schema_has_key(output_schema: dict[str, Any], key: str) -> bool:
    properties = output_schema.get("properties", {})
    return isinstance(properties, dict) and key in properties


def _mapped_ports_are_compatible(
    *,
    output_schema: dict[str, Any],
    output_key: str,
    input_schema: dict[str, Any],
    argument: str,
) -> bool:
    input_properties = input_schema.get("properties", {})
    output_properties = output_schema.get("properties", {})
    if not isinstance(input_properties, dict) or argument not in input_properties:
        return True
    if not isinstance(output_properties, dict) or output_key not in output_properties:
        return True
    output_type = port_type_for_schema(
        output_key,
        dict(output_properties.get(output_key) or {}),
    )
    input_type = port_type_for_schema(
        argument,
        dict(input_properties.get(argument) or {}),
    )
    return compatible_port_types(output_type, input_type)
