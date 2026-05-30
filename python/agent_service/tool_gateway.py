from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agent_service.authority import (
    AuthorityContext,
    authorize_tool_invocation,
)
from agent_service.schema_validation import validate_json_schema_subset
from agent_service.tool_execution import ToolExecutor, default_tool_packages_root
from agent_service.tool_protocol import (
    ToolProvider,
    UnifiedToolError,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from agent_service.tool_providers.internal import InternalToolProvider
from agent_service.tool_registry import ToolRegistry


class UnifiedToolGateway:
    def __init__(
        self,
        *,
        providers: list[ToolProvider],
        authority_context: AuthorityContext | None = None,
    ) -> None:
        self.providers = providers
        self.authority_context = authority_context

    def list_tools(self):
        tools = []
        for provider in self.providers:
            tools.extend(provider.list_tools())
        return tools

    def call_tool(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        tool = next(
            (candidate for candidate in self.list_tools() if candidate.id == invocation.tool_id),
            None,
        )
        if tool is None:
            return _error("unsupported_tool", f"unsupported tool: {invocation.tool_id}")
        if not tool.enabled:
            return _error("tool_disabled", f"tool disabled: {invocation.tool_id}")

        try:
            validate_json_schema_subset(tool.input_schema, invocation.arguments)
        except ValueError as error:
            return _error("invalid_tool_input", str(error), recoverable=True)

        authority_context = self.authority_context or _legacy_authority_context(
            invocation,
            tool,
        )
        decision = authorize_tool_invocation(invocation, tool, authority_context)
        if not decision.allowed:
            return _error(
                "authority_denied",
                decision.message,
                recoverable=True,
                safe_details={
                    "authorityCode": decision.code,
                    **decision.metadata,
                },
            )

        provider = next(
            provider for provider in self.providers if provider.provider_id == tool.provider_id
        )
        result = provider.call_tool(invocation)
        if not result.ok:
            return result
        return replace(
            result,
            metadata={
                **result.metadata,
                "authority": "allowed",
                "authorityCode": decision.code,
            },
        )


def _legacy_authority_context(
    invocation: UnifiedToolInvocation,
    tool,
) -> AuthorityContext:
    context = AuthorityContext.from_invocation(invocation)
    return AuthorityContext(
        approved_permissions=[
            *context.approved_permissions,
            *tool.permissions,
        ],
        read_roots=list(context.read_roots),
        write_roots=list(context.write_roots),
        runtime_budget_ms=context.runtime_budget_ms,
    )


def default_unified_tool_gateway(
    *,
    packages_root: Path | None = None,
    registry: ToolRegistry | None = None,
    internal_executor: ToolExecutor | None = None,
) -> UnifiedToolGateway:
    effective_registry = registry or ToolRegistry.from_packages_root(
        packages_root or default_tool_packages_root()
    )
    return UnifiedToolGateway(
        providers=[
            InternalToolProvider(
                registry=effective_registry,
                executor=internal_executor,
            )
        ]
    )


def _error(
    code: str,
    message: str,
    *,
    recoverable: bool = False,
    safe_details: dict | None = None,
) -> UnifiedToolResult:
    return UnifiedToolResult(
        ok=False,
        content=[],
        structured_content=None,
        artifacts=[],
        metadata={},
        error=UnifiedToolError(
            code=code,
            message=message,
            recoverable=recoverable,
            safe_details=safe_details,
        ),
    )
