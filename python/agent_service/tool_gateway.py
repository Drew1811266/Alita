from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from agent_service.authority import (
    AuthorityContext,
    AuthorityDecision,
    authorize_tool_invocation,
)
from agent_service.runtime_events import utc_now_iso
from agent_service.runtime_trace import RuntimeSpan, next_span_id, trace_id_for_run
from agent_service.schema_validation import validate_json_schema_subset
from agent_service.tool_execution import ToolExecutor, default_tool_packages_root
from agent_service.tool_observation import ObservationTimer, observation_metadata
from agent_service.tool_protocol import (
    ToolProvider,
    UnifiedToolDefinition,
    UnifiedToolError,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from agent_service.mcp_client_factory import create_mcp_client
from agent_service.tool_providers.internal import InternalToolProvider
from agent_service.tool_providers.mcp import McpClient, McpProviderConfig, McpToolProvider
from agent_service.tool_registry import ToolRegistry


AuthorityEventSink = Callable[
    [UnifiedToolInvocation, UnifiedToolDefinition, AuthorityDecision],
    None,
]
TraceSpanSink = Callable[[RuntimeSpan], None]


class UnifiedToolGateway:
    def __init__(
        self,
        *,
        providers: list[ToolProvider],
        authority_context: AuthorityContext | None = None,
        authority_event_sink: AuthorityEventSink | None = None,
        trace_span_sink: TraceSpanSink | None = None,
    ) -> None:
        self.providers = providers
        self.authority_context = authority_context
        self.authority_event_sink = authority_event_sink
        self.trace_span_sink = trace_span_sink
        self._span_counter = 0

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
        timer = ObservationTimer()
        authority_context = _authority_context_for_invocation(
            self.authority_context,
            invocation,
        )
        runtime_budget_ms = _effective_runtime_budget_ms(authority_context, tool)

        try:
            validate_json_schema_subset(tool.input_schema, invocation.arguments)
        except ValueError as error:
            return _with_observation(
                _error("invalid_tool_input", str(error), recoverable=True),
                invocation=invocation,
                tool=tool,
                ok=False,
                duration_ms=timer.elapsed_ms(),
                error_code="invalid_tool_input",
                runtime_budget_ms=runtime_budget_ms,
            )

        decision = authorize_tool_invocation(invocation, tool, authority_context)
        if self.authority_event_sink is not None:
            self.authority_event_sink(invocation, tool, decision)
        if not decision.allowed:
            return _with_observation(
                _error(
                    "authority_denied",
                    decision.message,
                    recoverable=True,
                    safe_details={
                        "authorityCode": decision.code,
                        **decision.metadata,
                    },
                ),
                invocation=invocation,
                tool=tool,
                ok=False,
                duration_ms=timer.elapsed_ms(),
                authority_code=decision.code,
                error_code="authority_denied",
                runtime_budget_ms=runtime_budget_ms,
            )

        provider = next(
            provider for provider in self.providers if provider.provider_id == tool.provider_id
        )
        span_started_at = utc_now_iso()
        result = provider.call_tool(invocation, timeout_ms=runtime_budget_ms)
        duration_ms = timer.elapsed_ms()
        if not result.ok:
            error_code = result.error.code if result.error is not None else "tool_failed"
            self._record_tool_span(
                invocation=invocation,
                tool=tool,
                status="error",
                started_at=span_started_at,
                duration_ms=duration_ms,
                authority_code=decision.code,
                error_code=error_code,
                runtime_budget_ms=runtime_budget_ms,
            )
            return _with_observation(
                result,
                invocation=invocation,
                tool=tool,
                ok=False,
                duration_ms=duration_ms,
                authority_code=decision.code,
                error_code=error_code,
                runtime_budget_ms=runtime_budget_ms,
            )
        self._record_tool_span(
            invocation=invocation,
            tool=tool,
            status="ok",
            started_at=span_started_at,
            duration_ms=duration_ms,
            authority_code=decision.code,
            error_code=None,
            runtime_budget_ms=runtime_budget_ms,
        )
        return replace(
            result,
            metadata={
                **result.metadata,
                "authority": "allowed",
                "authorityCode": decision.code,
                **observation_metadata(
                    tool_id=invocation.tool_id,
                    provider_id=tool.provider_id,
                    ok=True,
                    duration_ms=duration_ms,
                    authority_code=decision.code,
                    error_code=None,
                    runtime_budget_ms=runtime_budget_ms,
                ),
            },
        )

    def _record_tool_span(
        self,
        *,
        invocation: UnifiedToolInvocation,
        tool: UnifiedToolDefinition,
        status: str,
        started_at: str,
        duration_ms: int,
        authority_code: str | None,
        error_code: str | None,
        runtime_budget_ms: int | None,
    ) -> None:
        if self.trace_span_sink is None:
            return
        self._span_counter += 1
        self.trace_span_sink(
            RuntimeSpan(
                trace_id=trace_id_for_run(invocation.run_id),
                span_id=next_span_id(self._span_counter),
                parent_span_id=None,
                run_id=invocation.run_id,
                node_id=invocation.node_id,
                kind="tool.call",
                name=invocation.tool_id,
                status=status,
                started_at=started_at,
                ended_at=utc_now_iso(),
                duration_ms=duration_ms,
                metadata={
                    "toolId": invocation.tool_id,
                    "providerId": tool.provider_id,
                    "authorityCode": authority_code,
                    "errorCode": error_code,
                    "runtimeBudgetMs": runtime_budget_ms,
                },
            )
        )


def _authority_context_for_invocation(
    authority_context: AuthorityContext | None,
    invocation: UnifiedToolInvocation,
) -> AuthorityContext:
    if authority_context is None:
        return AuthorityContext.from_invocation(invocation)
    return authority_context.with_invocation_scope(invocation)


def _effective_runtime_budget_ms(
    authority_context: AuthorityContext,
    tool: UnifiedToolDefinition,
) -> int | None:
    candidates = [
        value
        for value in (authority_context.runtime_budget_ms, tool.timeout_ms)
        if value is not None
    ]
    return min(candidates) if candidates else None


def default_unified_tool_gateway(
    *,
    packages_root: Path | None = None,
    registry: ToolRegistry | None = None,
    internal_executor: ToolExecutor | None = None,
    authority_context: AuthorityContext | None = None,
    authority_event_sink: AuthorityEventSink | None = None,
    trace_span_sink: TraceSpanSink | None = None,
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
        authority_event_sink=authority_event_sink,
        trace_span_sink=trace_span_sink,
    )


def _mcp_providers_from_config(
    *,
    configs: list[McpProviderConfig],
    client_factory: Callable[[McpProviderConfig], McpClient] | None,
) -> list[McpToolProvider]:
    effective_client_factory = client_factory or create_mcp_client
    providers: list[McpToolProvider] = []
    for config in configs:
        if not config.enabled:
            continue
        providers.append(
            McpToolProvider(
                provider_id=config.provider_id,
                display_name=config.display_name,
                client=effective_client_factory(config),
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


def _with_observation(
    result: UnifiedToolResult,
    *,
    invocation: UnifiedToolInvocation,
    tool: UnifiedToolDefinition,
    ok: bool,
    duration_ms: int,
    authority_code: str | None = None,
    error_code: str | None = None,
    runtime_budget_ms: int | None = None,
) -> UnifiedToolResult:
    return replace(
        result,
        metadata={
            **result.metadata,
            **observation_metadata(
                tool_id=invocation.tool_id,
                provider_id=tool.provider_id,
                ok=ok,
                duration_ms=duration_ms,
                authority_code=authority_code,
                error_code=error_code,
                runtime_budget_ms=runtime_budget_ms,
            ),
        },
    )
