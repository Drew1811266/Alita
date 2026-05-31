from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, Field

from agent_service.context_policy import budget_for_mode, select_memory_for_context
from agent_service.goal_spec import GoalSpec, TaskType
from agent_service.memory_store import MemoryRecord, MemoryStore, sanitize_memory_summary
from agent_service.runtime_events import utc_now_iso
from agent_service.runtime_trace import RuntimeSpan, next_span_id, trace_id_for_run
from agent_service.schemas import UserMessage
from agent_service.tool_gateway import UnifiedToolGateway
from agent_service.tool_protocol import UnifiedToolDefinition
from agent_service.tool_registry import ToolRegistry
from agent_service.tool_resolver import resolve_tools_for_task


TraceSpanSink = Callable[[RuntimeSpan], None]
_context_span_counter = 0


class AttachmentContext(BaseModel):
    attachment_id: str
    name: str
    path: str
    size_bytes: int
    mime_type: str


class ToolCapability(BaseModel):
    tool_id: str
    name: str
    source: str = "internal"
    provider_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    operations: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    runtime: str | None = None


class ContextBundle(BaseModel):
    project_path: str
    artifact_dir: str
    goal: str
    task_type: TaskType
    attachments: list[AttachmentContext] = Field(default_factory=list)
    available_tools: list[ToolCapability] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    memory_summaries: list[str] = Field(default_factory=list)


def build_context_bundle(
    message: UserMessage,
    goal_spec: GoalSpec,
    project_path: str,
    tool_registry: ToolRegistry,
    tool_gateway: UnifiedToolGateway | None = None,
    disabled_tool_ids: list[str] | None = None,
    external_tools: list[ToolCapability] | None = None,
    memory_records: list[MemoryRecord] | None = None,
    memory_store: MemoryStore | None = None,
    context_mode: str = "planning",
    trace_span_sink: TraceSpanSink | None = None,
) -> ContextBundle:
    project_file = Path(project_path)
    budget = budget_for_mode(context_mode)
    memory_candidates = memory_records or []
    memory_started_at = utc_now_iso()
    memory_start = perf_counter()
    try:
        selected_memory = select_memory_for_context(
            memory_candidates,
            budget,
            query=message.content,
        )
    except Exception as error:
        _record_memory_search_span(
            trace_span_sink,
            message=message,
            context_mode=context_mode,
            candidate_record_count=len(memory_candidates),
            selected_record_count=0,
            selected_memory_ids=[],
            status="error",
            started_at=memory_started_at,
            duration_ms=int((perf_counter() - memory_start) * 1000),
            error_code=type(error).__name__,
        )
        raise
    _record_memory_search_span(
        trace_span_sink,
        message=message,
        context_mode=context_mode,
        candidate_record_count=len(memory_candidates),
        selected_record_count=len(selected_memory),
        selected_memory_ids=[record.memory_id for record in selected_memory],
        status="ok",
        started_at=memory_started_at,
        duration_ms=int((perf_counter() - memory_start) * 1000),
        error_code=None,
    )
    if memory_store is not None and selected_memory:
        memory_store.mark_used(
            [record.memory_id for record in selected_memory],
            used_at=utc_now_iso(),
        )
    available_tools = (
        _tool_capabilities_from_unified_catalog(
            resolve_tools_for_task(
                tool_gateway.list_tools(),
                task_text=message.content,
                disabled_tool_ids=disabled_tool_ids or [],
                approved_permissions=[],
            )
        )
        if tool_gateway is not None
        else _tool_capabilities_from_registry(tool_registry)
    )
    available_tools = _merge_tool_capabilities(
        available_tools,
        external_tools or [],
        disabled_tool_ids or [],
    )
    return ContextBundle(
        project_path=project_path,
        artifact_dir=str(project_file.parent / "artifacts"),
        goal=goal_spec.goal,
        task_type=goal_spec.task_type,
        attachments=[
            AttachmentContext(
                attachment_id=attachment.attachment_id,
                name=attachment.name,
                path=attachment.path,
                size_bytes=attachment.size_bytes,
                mime_type=attachment.mime_type,
            )
            for attachment in message.attachments
        ],
        available_tools=available_tools,
        constraints=list(goal_spec.constraints),
        memory_summaries=[
            sanitize_memory_summary(record.summary, max_chars=budget.max_chars)
            for record in selected_memory
        ],
    )


def _tool_capabilities_from_registry(tool_registry: ToolRegistry) -> list[ToolCapability]:
    return [
        ToolCapability(
            tool_id=tool.tool_id,
            name=tool.name,
            capabilities=list(tool.capabilities),
            operations=[operation.name for operation in tool.operations],
            permissions=list(tool.permissions),
            runtime=tool.runtime,
        )
        for tool in tool_registry.enabled_tools()
    ]


def _tool_capabilities_from_unified_catalog(
    tools: list[UnifiedToolDefinition],
) -> list[ToolCapability]:
    return [
        ToolCapability(
            tool_id=tool.id,
            name=tool.display_name,
            source=tool.source,
            provider_id=tool.provider_id,
            capabilities=list(tool.capabilities),
            operations=_operation_names_from_schema(tool.input_schema),
            permissions=list(tool.permissions),
            runtime=tool.source,
        )
        for tool in tools
    ]


def _merge_tool_capabilities(
    base_tools: list[ToolCapability],
    external_tools: list[ToolCapability],
    disabled_tool_ids: list[str],
) -> list[ToolCapability]:
    disabled = set(disabled_tool_ids)
    merged: list[ToolCapability] = []
    seen: set[str] = set()
    for tool in [*base_tools, *external_tools]:
        if tool.tool_id in disabled:
            continue
        if tool.tool_id in seen:
            continue
        seen.add(tool.tool_id)
        merged.append(tool)
    return merged


def _operation_names_from_schema(schema: dict) -> list[str]:
    operation = schema.get("properties", {}).get("operation", {})
    enum_values = operation.get("enum", [])
    return [str(value) for value in enum_values]


def _record_memory_search_span(
    trace_span_sink: TraceSpanSink | None,
    *,
    message: UserMessage,
    context_mode: str,
    candidate_record_count: int,
    selected_record_count: int,
    selected_memory_ids: list[str],
    status: str,
    started_at: str,
    duration_ms: int,
    error_code: str | None,
) -> None:
    if trace_span_sink is None:
        return
    global _context_span_counter
    _context_span_counter += 1
    trace_span_sink(
        RuntimeSpan(
            trace_id=trace_id_for_run(message.task_id),
            span_id=next_span_id(_context_span_counter),
            parent_span_id=None,
            run_id=message.task_id,
            node_id="context-manager",
            kind="memory.search",
            name="context.memory.select",
            status=status,
            started_at=started_at,
            ended_at=utc_now_iso(),
            duration_ms=duration_ms,
            metadata={
                "contextMode": context_mode,
                "candidateRecordCount": candidate_record_count,
                "selectedRecordCount": selected_record_count,
                "selectedMemoryIds": list(selected_memory_ids),
                "errorCode": error_code,
            },
        )
    )
