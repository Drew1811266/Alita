from __future__ import annotations

from collections.abc import Callable
import re
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_service.context_manager import ContextBundle, ToolCapability
from agent_service.graph_compiler import compile_task_graph_to_node_graph
from agent_service.goal_spec import GoalSpec, TaskType
from agent_service.model_runtime import SupportedModelRegistry
from agent_service.planner_v2 import PlannerV2, PlannerV2Error
from agent_service.runtime_events import utc_now_iso
from agent_service.runtime_trace import RuntimeSpan, next_span_id, trace_id_for_run
from agent_service.tool_catalog_planner import (
    ToolCatalogPlanner,
    ToolCatalogPlanningRequest,
)
from agent_service.router_v2 import AgentRouteIntent, RouteSource
from agent_service.schemas import RunGraph, UserMessage
from agent_service.task_planner import (
    analyze_task,
    build_task_graph,
    resolve_tool_gaps,
    select_tools,
)
from agent_service.tool_protocol import normalize_tool_id, provider_tool_id
from agent_service.tool_registry import ToolRegistry

try:
    from agent_service.model_runtime import DEFAULT_SUPPORTED_MODEL_REGISTRY
except ImportError:
    DEFAULT_SUPPORTED_MODEL_REGISTRY = SupportedModelRegistry.default()


PlannerStrategy = Literal["document_template", "tool_catalog", "legacy_task_planner"]
PLANNER_CHAIN_VERSION = "planner_chain.v1"
LOW_RISK_REACT_PERMISSIONS = {"read_attachment", "read_project_files"}
TraceSpanSink = Callable[[RuntimeSpan], None]
LOCAL_PATH_PATTERN = re.compile(
    r"(?ix)"
    r"(?:"
    r"\b[a-z]:[\\/](?:[^\\/:\r\n,;<>\"|?*]+[\\/])*[^\\/\s:\r\n,;<>\"|?*]+"
    r"|"
    r"/(?:[^/\s\r\n,;<>\"|?*]+/)+[^/\s\r\n,;<>\"|?*]+"
    r")"
)


class PlannerChainError(ValueError):
    pass


class StructuredRouteContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    intent: AgentRouteIntent
    confidence: float = Field(ge=0.0, le=1.0)
    task_type: TaskType = Field(alias="taskType")
    missing_inputs: list[str] = Field(default_factory=list, alias="missingInputs")
    required_permissions: list[str] = Field(default_factory=list, alias="requiredPermissions")
    tool_candidates: list[str] = Field(default_factory=list, alias="toolCandidates")
    reason: str
    source: RouteSource
    should_clarify: bool = Field(default=False, alias="shouldClarify")
    clarification_prompt: str | None = Field(default=None, alias="clarificationPrompt")

    def safe_payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "taskType": self.task_type,
            "missingInputs": _scrub_payload(list(self.missing_inputs)),
            "requiredPermissions": _scrub_payload(list(self.required_permissions)),
            "toolCandidates": _scrub_payload(list(self.tool_candidates)),
            "reason": _safe_text(self.reason),
            "source": self.source,
            "shouldClarify": self.should_clarify,
            "clarificationPrompt": (
                _safe_text(self.clarification_prompt)
                if self.clarification_prompt is not None
                else None
            ),
        }


class PlannerChainRequest(BaseModel):
    task_id: str
    message: UserMessage
    goal_spec: GoalSpec
    route: StructuredRouteContext
    context: ContextBundle


class PlannerChainResult(BaseModel):
    planner: str
    strategy: PlannerStrategy
    graph_payload: dict[str, Any]
    validation_warnings: list[str] = Field(default_factory=list)


class PlannerChain:
    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        model_registry: SupportedModelRegistry | None = None,
        trace_span_sink: TraceSpanSink | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.model_registry = model_registry or DEFAULT_SUPPORTED_MODEL_REGISTRY
        self.trace_span_sink = trace_span_sink
        self._span_counter = 0

    def plan(self, request: PlannerChainRequest) -> PlannerChainResult:
        started_at = utc_now_iso()
        start = perf_counter()
        try:
            self._validate_request(request)
            if request.route.task_type == "document_processing":
                catalog_result = (
                    self._plan_tool_catalog(request)
                    if _explicit_tool_catalog_request(request)
                    else None
                )
                if catalog_result is not None:
                    result = catalog_result
                elif not _is_markdown_conversion_only(request.message.content):
                    result = self._plan_document_template(request)
                else:
                    result = self._plan_legacy_task(request)
            elif request.route.task_type != "document_processing":
                catalog_result = self._plan_tool_catalog(request)
                result = (
                    catalog_result
                    if catalog_result is not None
                    else self._plan_legacy_task(request)
                )
            else:
                result = self._plan_legacy_task(request)
        except Exception as error:
            self._record_planner_span(
                request=request,
                result=None,
                status="error",
                started_at=started_at,
                duration_ms=int((perf_counter() - start) * 1000),
                error_code=type(error).__name__,
            )
            raise
        self._record_planner_span(
            request=request,
            result=result,
            status="ok",
            started_at=started_at,
            duration_ms=int((perf_counter() - start) * 1000),
            error_code=None,
        )
        return result

    def _validate_request(self, request: PlannerChainRequest) -> None:
        if request.route.intent != "task":
            raise PlannerChainError(f"cannot plan non-task route: {request.route.intent}")
        missing_inputs = _scrub_payload(
            [
                *request.route.missing_inputs,
                *request.goal_spec.missing_inputs,
            ]
        )
        if missing_inputs:
            raise PlannerChainError(
                f"missing inputs: {', '.join(str(item) for item in missing_inputs)}"
            )

    def _plan_document_template(self, request: PlannerChainRequest) -> PlannerChainResult:
        try:
            plan = PlannerV2(
                tool_registry=self.tool_registry,
                model_registry=self.model_registry,
            ).plan(
                task_id=request.task_id,
                goal_spec=request.goal_spec,
                context=request.context,
            )
        except PlannerV2Error as exc:
            raise PlannerChainError(_safe_text(str(exc))) from None

        graph_payload = compile_task_graph_to_node_graph(plan.task_graph)
        graph_payload = _with_planner_chain_metadata(
            graph_payload,
            request=request,
            planner=plan.planner,
            strategy="document_template",
        )
        _validate_graph_payload(graph_payload)
        return PlannerChainResult(
            planner=plan.planner,
            strategy="document_template",
            graph_payload=graph_payload,
            validation_warnings=list(plan.validation_warnings),
        )

    def _plan_tool_catalog(
        self,
        request: PlannerChainRequest,
    ) -> PlannerChainResult | None:
        result = ToolCatalogPlanner(tool_registry=self.tool_registry).plan(
            ToolCatalogPlanningRequest(
                task_id=request.task_id,
                message=request.message,
                goal_spec=request.goal_spec,
                context=request.context,
            )
        )
        if not result.planned or result.graph_payload is None:
            return None

        graph_payload = _with_planner_chain_metadata(
            result.graph_payload,
            request=request,
            planner=result.planner,
            strategy="tool_catalog",
        )
        _validate_graph_payload(graph_payload)
        return PlannerChainResult(
            planner=result.planner,
            strategy="tool_catalog",
            graph_payload=graph_payload,
            validation_warnings=list(result.diagnostics),
        )

    def _plan_legacy_task(self, request: PlannerChainRequest) -> PlannerChainResult:
        task_plan = analyze_task(request.message.content, request.message.attachments)
        task_plan.task_id = request.task_id
        task_plan.selected_tools = select_tools(
            task_plan.requirements,
            self.tool_registry.enabled_tools(),
        )
        task_plan.tool_gaps = resolve_tool_gaps(
            task_plan.requirements,
            task_plan.selected_tools,
        )
        graph_payload = build_task_graph(task_plan)
        graph_payload = _with_planner_chain_metadata(
            graph_payload,
            request=request,
            planner="legacy.task_planner.v1",
            strategy="legacy_task_planner",
        )
        _validate_graph_payload(graph_payload)
        return PlannerChainResult(
            planner="legacy.task_planner.v1",
            strategy="legacy_task_planner",
            graph_payload=graph_payload,
            validation_warnings=[],
        )

    def _record_planner_span(
        self,
        *,
        request: PlannerChainRequest,
        result: PlannerChainResult | None,
        status: str,
        started_at: str,
        duration_ms: int,
        error_code: str | None,
    ) -> None:
        if self.trace_span_sink is None:
            return
        self._span_counter += 1
        graph_payload = result.graph_payload if result is not None else {}
        self.trace_span_sink(
            RuntimeSpan(
                trace_id=trace_id_for_run(request.task_id),
                span_id=next_span_id(self._span_counter),
                parent_span_id=None,
                run_id=request.task_id,
                node_id="planner-chain",
                kind="planner.call",
                name=result.planner if result is not None else PLANNER_CHAIN_VERSION,
                status=status,
                started_at=started_at,
                ended_at=utc_now_iso(),
                duration_ms=duration_ms,
                metadata={
                    "plannerChainVersion": PLANNER_CHAIN_VERSION,
                    "planner": result.planner if result is not None else None,
                    "strategy": result.strategy if result is not None else None,
                    "taskType": _enum_value(request.route.task_type),
                    "routeIntent": _enum_value(request.route.intent),
                    "routeSource": _enum_value(request.route.source),
                    "routeConfidence": request.route.confidence,
                    "graphNodeCount": len(graph_payload.get("nodes") or []),
                    "validationWarningCount": (
                        len(result.validation_warnings) if result is not None else 0
                    ),
                    "errorCode": error_code,
                },
            )
        )


def route_context_from_payload(payload: dict[str, Any]) -> StructuredRouteContext:
    try:
        return StructuredRouteContext.model_validate(payload)
    except ValidationError:
        raise PlannerChainError("invalid structured route payload") from None


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _safe_text(value: str) -> str:
    return LOCAL_PATH_PATTERN.sub("[local_path]", value)


def _scrub_payload(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, list):
        return [_scrub_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _scrub_payload(item) for key, item in value.items()}
    return value


def _with_planner_chain_metadata(
    graph_payload: dict[str, Any],
    *,
    request: PlannerChainRequest,
    planner: str,
    strategy: PlannerStrategy,
) -> dict[str, Any]:
    metadata = dict(graph_payload.get("metadata") or {})
    metadata["plannerChain"] = {
        "version": PLANNER_CHAIN_VERSION,
        "planner": planner,
        "strategy": strategy,
        "routeIntent": request.route.intent,
        "taskType": request.route.task_type,
        "routeSource": request.route.source,
        "routeConfidence": request.route.confidence,
        "toolCandidates": _scrub_payload(list(request.route.tool_candidates)),
        "requiredPermissions": _scrub_payload(list(request.route.required_permissions)),
    }
    react_metadata = _react_metadata_for_request(request, strategy=strategy)
    if react_metadata is not None:
        metadata["react"] = react_metadata
    action_policies = _action_policies_for_request(
        graph_payload,
        request=request,
        strategy=strategy,
    )
    if action_policies:
        metadata["actionPolicies"] = action_policies
    return {**graph_payload, "metadata": _scrub_payload(metadata)}


def _react_metadata_for_request(
    request: PlannerChainRequest,
    *,
    strategy: PlannerStrategy,
) -> dict[str, Any] | None:
    if strategy != "legacy_task_planner":
        return None
    tool_ids = _allowed_react_tool_ids(request)
    if not tool_ids:
        return None
    permissions = _allowed_react_permissions(request, tool_ids)
    return {
        "enabled": True,
        "nativeToolCalls": False,
        "maxSteps": 4,
        "maxToolCalls": min(3, max(1, len(tool_ids))),
        "allowedToolIds": tool_ids,
        "allowedPermissions": permissions,
    }


def _action_policies_for_request(
    graph_payload: dict[str, Any],
    *,
    request: PlannerChainRequest,
    strategy: PlannerStrategy,
) -> dict[str, Any]:
    react_metadata = _react_metadata_for_request(request, strategy=strategy)
    if react_metadata is None:
        return {}
    policies: dict[str, Any] = {}
    for node in graph_payload.get("nodes", []):
        if not isinstance(node, dict) or node.get("nodeType") != "model":
            continue
        node_id = str(node.get("nodeId") or "")
        if not node_id:
            continue
        policies[node_id] = {
            "reactEnabled": react_metadata["enabled"],
            "nativeToolCalls": react_metadata["nativeToolCalls"],
            "maxSteps": react_metadata["maxSteps"],
            "maxToolCalls": react_metadata["maxToolCalls"],
            "allowedToolIds": list(react_metadata["allowedToolIds"]),
            "allowedPermissions": list(react_metadata["allowedPermissions"]),
        }
    return policies


def _allowed_react_tool_ids(request: PlannerChainRequest) -> list[str]:
    available = {
        normalize_tool_id(tool.tool_id) for tool in request.context.available_tools
    }
    available.update(
        provider_tool_id(tool.tool_id) for tool in request.context.available_tools
    )
    selected: list[str] = []
    for tool_id in request.route.tool_candidates:
        normalized = normalize_tool_id(str(tool_id))
        unprefixed = provider_tool_id(normalized)
        if available and normalized not in available and unprefixed not in available:
            continue
        if normalized not in selected:
            selected.append(normalized)
    return selected


def _allowed_react_permissions(
    request: PlannerChainRequest,
    tool_ids: list[str],
) -> list[str]:
    allowed: list[str] = []
    for permission in request.route.required_permissions:
        if permission in LOW_RISK_REACT_PERMISSIONS and permission not in allowed:
            allowed.append(permission)
    for tool in request.context.available_tools:
        if tool.tool_id not in tool_ids:
            continue
        for permission in tool.permissions:
            if permission in LOW_RISK_REACT_PERMISSIONS and permission not in allowed:
                allowed.append(permission)
    return allowed


def _validate_graph_payload(graph_payload: dict[str, Any]) -> None:
    try:
        RunGraph.model_validate(graph_payload)
    except Exception:
        raise PlannerChainError("invalid node graph payload") from None


def _is_markdown_conversion_only(content: str) -> bool:
    normalized = content.lower()
    wants_markdown = bool(
        re.search(
            r"\bmarkdown\b|\.md\b|\b(?:to|as|into)\s+md\b|\bmd\s+(?:file|format|document|output)\b",
            normalized,
        )
    )
    wants_conversion = "convert" in normalized or "转换" in content or "转" in content
    wants_report = "report" in normalized or "pdf" in normalized or "报告" in content
    return wants_markdown and wants_conversion and not wants_report


def _explicit_tool_catalog_request(request: PlannerChainRequest) -> bool:
    content = request.message.content.lower()
    matches = {
        term
        for tool in request.context.available_tools
        for term in _explicit_tool_terms(tool)
        if term in content
    }
    return len(matches) >= 2


def _explicit_tool_terms(tool: ToolCapability) -> set[str]:
    normalized_id = provider_tool_id(normalize_tool_id(tool.tool_id)).lower()
    raw_terms = set(re.split(r"[._:\-\s]+", normalized_id))
    if tool.name.isascii():
        raw_terms.add(tool.name.lower())
    raw_terms.add(normalized_id.replace(".", " ").replace("_", " "))
    if "." in normalized_id:
        raw_terms.add(normalized_id.rsplit(".", maxsplit=1)[-1].replace("_", " "))
    return {
        term
        for term in raw_terms
        if len(term) >= 5 and term not in {"document", "values", "compile"}
    }
