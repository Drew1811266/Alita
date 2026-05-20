from __future__ import annotations

from collections.abc import Iterable

from agent_service.harness_errors import HarnessError
from agent_service.schemas import GraphNode
from agent_service.tool_registry import ToolRegistry


DEFAULT_ALLOWED_PERMISSIONS = frozenset(
    {
        "read_attachment",
        "read_project_files",
        "run_local_cli",
        "run_python_plugin",
        "write_project_artifact",
        "write_project_outputs",
    }
)


class PermissionGate:
    def __init__(
        self,
        *,
        approved_permissions: Iterable[str] | None = None,
        default_allowed_permissions: Iterable[str] | None = None,
    ) -> None:
        self.approved_permissions = set(approved_permissions or [])
        if default_allowed_permissions is None:
            default_allowed_permissions = DEFAULT_ALLOWED_PERMISSIONS
        self.default_allowed_permissions = set(default_allowed_permissions)

    def required_permissions(
        self,
        node: GraphNode,
        *,
        tool_registry: ToolRegistry,
    ) -> list[str]:
        permissions = list(node.permissionsRequired)
        if node.toolRef:
            try:
                permissions.extend(tool_registry.get(node.toolRef).permissions)
            except KeyError:
                pass
        if node.scriptReview is not None:
            permissions.extend(node.scriptReview.permissions)
        return _dedupe(permissions)

    def denied_permissions(
        self,
        node: GraphNode,
        *,
        tool_registry: ToolRegistry,
    ) -> list[str]:
        allowed = self.default_allowed_permissions | self.approved_permissions
        return [
            permission
            for permission in self.required_permissions(node, tool_registry=tool_registry)
            if permission not in allowed
        ]

    def ensure_node_allowed(
        self,
        node: GraphNode,
        *,
        tool_registry: ToolRegistry,
    ) -> None:
        denied = self.denied_permissions(node, tool_registry=tool_registry)
        if denied:
            raise HarnessError(
                "permission_required",
                (
                    f"node {node.nodeId} requires permission approval: "
                    f"{', '.join(denied)}"
                ),
            )


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
