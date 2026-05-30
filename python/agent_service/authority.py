from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from agent_service.tool_protocol import (
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    equivalent_tool_ids,
)


PathUse = Literal["read", "write"]


@dataclass(frozen=True)
class InvocationPath:
    name: str
    path: str
    kind: PathUse


@dataclass(frozen=True)
class AuthorityDecision:
    allowed: bool
    code: str
    message: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthorityContext:
    approved_tool_ids: list[str] = field(default_factory=list)
    approved_permissions: list[str] = field(default_factory=list)
    read_roots: list[str] = field(default_factory=list)
    write_roots: list[str] = field(default_factory=list)
    network_domains: list[str] = field(default_factory=list)
    runtime_budget_ms: int | None = None

    @classmethod
    def from_invocation(cls, invocation: UnifiedToolInvocation) -> "AuthorityContext":
        return cls(
            approved_permissions=list(invocation.requested_permissions),
            read_roots=list(invocation.allowed_roots),
            write_roots=list(invocation.allowed_roots),
            runtime_budget_ms=None,
        )


def extract_invocation_paths(arguments: dict, *, project_path: str | None = None) -> list[InvocationPath]:
    paths: list[InvocationPath] = []
    for name in ("input_path", "input_paths"):
        value = arguments.get(name)
        paths.extend(_paths_from_value(name, value, "read", project_path=project_path))
    for name in ("output_path", "source_output_path", "pdf_output_path"):
        value = arguments.get(name)
        paths.extend(_paths_from_value(name, value, "write", project_path=project_path))
    paths.extend(
        _paths_from_value("paths", arguments.get("paths"), "read", project_path=project_path)
    )
    return paths


def authorize_tool_invocation(
    invocation: UnifiedToolInvocation,
    tool: UnifiedToolDefinition,
    context: AuthorityContext,
) -> AuthorityDecision:
    tool_decision = _authorize_tool_id(invocation, context)
    if tool_decision is not None:
        return tool_decision

    permissions = _dedupe([*tool.permissions, *invocation.requested_permissions])
    permission_decision = _authorize_permissions(permissions, context)
    if permission_decision is not None:
        return permission_decision

    paths = extract_invocation_paths(
        invocation.arguments,
        project_path=invocation.project_path,
    )
    path_decision = _authorize_paths(paths, context)
    if path_decision is not None:
        return path_decision

    return AuthorityDecision(
        allowed=True,
        code="allowed",
        message="tool invocation allowed",
        metadata={
            "permissions": permissions,
            "paths": [path.__dict__ for path in paths],
        },
    )


def _authorize_tool_id(
    invocation: UnifiedToolInvocation,
    context: AuthorityContext,
) -> AuthorityDecision | None:
    if not context.approved_tool_ids:
        return None
    approved: set[str] = set()
    for tool_id in context.approved_tool_ids:
        approved.update(equivalent_tool_ids(tool_id))
    if equivalent_tool_ids(invocation.tool_id) & approved:
        return None
    return AuthorityDecision(
        allowed=False,
        code="tool_denied",
        message=f"tool is not approved for this authority context: {invocation.tool_id}",
        metadata={"toolId": invocation.tool_id},
    )


def _authorize_permissions(
    permissions: list[str],
    context: AuthorityContext,
) -> AuthorityDecision | None:
    approved = set(context.approved_permissions)
    sensitive = [
        permission
        for permission in permissions
        if permission in SENSITIVE_PERMISSIONS and permission not in approved
    ]
    if not sensitive:
        return None
    return AuthorityDecision(
        allowed=False,
        code="permission_denied",
        message=f"permission is not approved: {', '.join(sensitive)}",
        metadata={"permissions": sensitive},
    )


def _authorize_paths(
    paths: list[InvocationPath],
    context: AuthorityContext,
) -> AuthorityDecision | None:
    for path in paths:
        roots = context.read_roots if path.kind == "read" else context.write_roots
        if _path_within_roots(path.path, roots):
            continue
        return AuthorityDecision(
            allowed=False,
            code="path_denied",
            message=f"{path.kind} path is outside approved roots: {path.path}",
            metadata={"path": path.path, "kind": path.kind, "argument": path.name},
        )
    return None


def _paths_from_value(
    name: str,
    value: object,
    kind: PathUse,
    *,
    project_path: str | None,
) -> list[InvocationPath]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_paths = [part.strip() for part in value.splitlines() if part.strip()]
    elif isinstance(value, list):
        raw_paths = [str(part).strip() for part in value if str(part).strip()]
    else:
        raw_paths = [str(value).strip()]
    return [
        InvocationPath(name=name, path=_normalize_invocation_path(path, project_path), kind=kind)
        for path in raw_paths
    ]


def _normalize_invocation_path(path: str, project_path: str | None) -> str:
    candidate = Path(path)
    if not candidate.is_absolute() and project_path:
        candidate = Path(project_path).parent / candidate
    return str(candidate)


def _path_within_roots(path: str, roots: list[str]) -> bool:
    if not roots:
        return False
    candidate = Path(path).resolve(strict=False)
    for root in roots:
        root_path = Path(root).resolve(strict=False)
        try:
            candidate.relative_to(root_path)
            return True
        except ValueError:
            continue
    return False


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


SENSITIVE_PERMISSIONS = frozenset({"network", "run_local_cli", "run_python_plugin"})
