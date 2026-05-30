from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from agent_service.authority import AuthorityContext, authorize_tool_invocation
from agent_service.schema_validation import validate_json_schema_subset
from agent_service.tool_execution import ToolExecutor, default_tool_packages_root
from agent_service.tool_protocol import (
    ToolProvider,
    UnifiedToolError,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from agent_service.tool_providers.internal import InternalToolProvider
from agent_service.tool_providers.mcp import McpClient, McpProviderConfig, McpToolProvider
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

        authority_context = _authority_context_for_invocation(
            self.authority_context,
            invocation,
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


def _authority_context_for_invocation(
    authority_context: AuthorityContext | None,
    invocation: UnifiedToolInvocation,
) -> AuthorityContext:
    if authority_context is None:
        return AuthorityContext.from_invocation(invocation)
    return authority_context.with_invocation_scope(invocation)


def default_unified_tool_gateway(
    *,
    packages_root: Path | None = None,
    registry: ToolRegistry | None = None,
    internal_executor: ToolExecutor | None = None,
    authority_context: AuthorityContext | None = None,
    mcp_provider_configs: list[McpProviderConfig] | None = None,
    mcp_client_factory: Callable[[McpProviderConfig], McpClient] | None = None,
) -> UnifiedToolGateway:
    effective_registry = registry or ToolRegistry.from_packages_root(
        packages_root or default_tool_packages_root()
    )
    providers = [
        InternalToolProvider(
            registry=effective_registry,
            executor=internal_executor,
        )
    ]
    providers.extend(
        _mcp_providers_from_config(
            configs=mcp_provider_configs or [],
            client_factory=mcp_client_factory,
        )
    )
    return UnifiedToolGateway(
        providers=providers,
        authority_context=authority_context,
    )


def _mcp_providers_from_config(
    *,
    configs: list[McpProviderConfig],
    client_factory: Callable[[McpProviderConfig], McpClient] | None,
) -> list[McpToolProvider]:
    if client_factory is None:
        return []
    providers: list[McpToolProvider] = []
    for config in configs:
        if not config.enabled:
            continue
        providers.append(
            McpToolProvider(
                provider_id=config.provider_id,
                display_name=config.display_name,
                client=client_factory(config),
                enabled=True,
            )
        )
    return providers


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
