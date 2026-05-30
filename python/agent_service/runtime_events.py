from __future__ import annotations

from datetime import datetime, timezone

from agent_service.authority import AuthorityDecision
from agent_service.replan import ReplanSuggestion
from agent_service.runtime_loop import RuntimeCheckpoint
from agent_service.runtime_trace import RuntimeSpan
from agent_service.schemas import AgentEvent
from agent_service.tool_protocol import UnifiedToolDefinition, UnifiedToolInvocation


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def checkpoint_recorded_event(checkpoint: RuntimeCheckpoint) -> AgentEvent:
    return AgentEvent(
        type="runtime.checkpoint_recorded",
        payload={"checkpoint": checkpoint.to_record()},
    )


def runtime_span_recorded_event(span: RuntimeSpan) -> AgentEvent:
    return AgentEvent(
        type="runtime.span_recorded",
        payload={"span": span.to_record()},
    )


def authority_decision_recorded_event(
    *,
    invocation: UnifiedToolInvocation,
    tool: UnifiedToolDefinition,
    decision: AuthorityDecision,
    created_at: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type="authority.decision_recorded",
        payload={
            "decision": {
                "runId": invocation.run_id,
                "nodeId": invocation.node_id,
                "toolId": invocation.tool_id,
                "providerId": tool.provider_id,
                "allowed": decision.allowed,
                "code": decision.code,
                "message": decision.message,
                "permissions": list(decision.metadata.get("permissions", [])),
                "createdAt": created_at or utc_now_iso(),
            }
        },
    )


def recovery_action_event(
    *,
    event_type: str,
    run_id: str,
    node_id: str,
    suggestion: ReplanSuggestion,
    recovery_count: int = 0,
    created_at: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=event_type,
        payload={
            "action": {
                "runId": run_id,
                "nodeId": node_id,
                "action": "applied" if event_type.endswith("_applied") else "proposed",
                "reason": suggestion.reason,
                "operations": [
                    operation.model_dump() for operation in suggestion.operations
                ],
                "requiresUserApproval": suggestion.requires_user_approval,
                "createdAt": created_at or utc_now_iso(),
                "recoveryCount": recovery_count,
            }
        },
    )
