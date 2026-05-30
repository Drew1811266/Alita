from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


class PlannedToolNode(BaseModel):
    node_id: str
    tool_id: str
    operation: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    required_arguments: list[str] = Field(default_factory=list)
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
        for dependency, output_key in _argument_output_refs(node.arguments):
            if dependency not in known:
                diagnostics.append(
                    f"node {node.node_id} maps missing dependency {dependency}"
                )
                continue
            if dependency not in node.dependencies:
                diagnostics.append(
                    f"node {node.node_id} maps undeclared dependency {dependency}"
                )
            if not _output_schema_has_key(known[dependency].output_schema, output_key):
                diagnostics.append(
                    f"node {node.node_id} maps missing output {dependency}.{output_key}"
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
