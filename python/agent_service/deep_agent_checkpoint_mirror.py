from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_service.deep_agent_runtime_models import PlanningCheckpointSummary
from agent_service.schemas import AgentEvent


def planning_checkpoint_summary_from_state(
    values: dict[str, Any],
    checkpoint_id: str,
    node: str | None,
) -> PlanningCheckpointSummary:
    return PlanningCheckpointSummary(
        runId=str(values.get("run_id") or ""),
        threadId=str(values.get("thread_id") or ""),
        checkpointId=checkpoint_id,
        stage=_stage_from_values(values, node),
        node=node,
        revisionCount=int(values.get("revision_count", 0) or 0),
        hasPlanDraft=values.get("plan_draft") is not None,
        hasCompiledGraph=values.get("compiled_graph") is not None,
        hasAgentCompiledGraph=values.get("agent_compiled_graph") is not None,
        executionReady=bool(values.get("execution_ready", False)),
        createdAt=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def planning_checkpoint_recorded_event(summary: PlanningCheckpointSummary) -> AgentEvent:
    return AgentEvent(
        type="planning.checkpoint_recorded",
        payload={"checkpoint": summary.model_dump(by_alias=True)},
    )


def _stage_from_values(values: dict[str, Any], node: str | None) -> str:
    terminal_status = values.get("terminal_status")
    if isinstance(terminal_status, str) and terminal_status:
        return terminal_status
    if node:
        return node
    return "planning"
