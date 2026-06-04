from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_service.agent_plan_compile import AgentCompiledGraph
from agent_service.harness_errors import HarnessError
from agent_service.schemas import AgentEvent, RunGraph, RunGraphRequest


class AgentExecutionIssue(BaseModel):
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    node_id: str | None = None


class AgentExecutionRunResult(BaseModel):
    status: Literal["completed", "failed", "interrupted"]
    task_id: str
    run_id: str
    thread_id: str
    compile_id: str
    graph_id: str
    completed_node_ids: list[str] = Field(default_factory=list)
    failed_node_id: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    checkpoint_ids: list[str] = Field(default_factory=list)
    recovery_actions: list[dict[str, Any]] = Field(default_factory=list)
    final_message: str | None = None
    raw_events: list[AgentEvent] = Field(default_factory=list)


class AgentExecutionReview(BaseModel):
    status: Literal["approved", "failed", "needs_repair"]
    is_valid: bool
    issues: list[AgentExecutionIssue] = Field(default_factory=list)
    final_artifacts: list[str] = Field(default_factory=list)
    repair_required: bool = False


def run_graph_request_from_agent_compiled_graph(
    compiled_graph: AgentCompiledGraph,
    *,
    project_path: str,
) -> RunGraphRequest:
    if compiled_graph.status != "execution_ready":
        raise HarnessError(
            "agent_compiled_graph_not_execution_ready",
            "Agent compiled graph is not execution_ready.",
        )
    if compiled_graph.metadata.get("generatedBy") != "deep_agent_runtime":
        raise HarnessError(
            "invalid_agent_execution_provenance",
            "Agent execution requires a deep_agent_runtime compiled graph.",
        )
    for node in compiled_graph.nodes:
        if not node.source_plan_step_id:
            raise HarnessError(
                "missing_agent_execution_provenance",
                f"compiled node lacks source plan step: {node.node_id}",
            )

    return RunGraphRequest(
        task_id=compiled_graph.task_id,
        project_path=project_path,
        graph=_run_graph_from_compiled_graph(compiled_graph),
        run_id=compiled_graph.run_id,
    )


def summarize_agent_execution_events(
    compiled_graph: AgentCompiledGraph,
    events: list[AgentEvent],
) -> AgentExecutionRunResult:
    completed_node_ids: list[str] = []
    failed_node_id: str | None = None
    artifact_refs: list[str] = []
    checkpoint_ids: list[str] = []
    recovery_actions: list[dict[str, Any]] = []
    final_message: str | None = None
    saw_completed = False
    saw_failed = False
    saw_interrupted = False

    for event in events:
        payload = event.payload
        if event.type == "node.completed":
            _append_string(completed_node_ids, payload.get("nodeId"))
            for artifact_ref in _string_list(payload.get("artifactRefs")):
                _append_string(artifact_refs, artifact_ref)
        elif event.type == "node.failed":
            failed_node_id = _string_or_none(payload.get("nodeId")) or failed_node_id
            saw_failed = True
        elif event.type in {"node.needs_permission", "permission.required"}:
            failed_node_id = _string_or_none(payload.get("nodeId")) or failed_node_id
            saw_interrupted = True
        elif event.type == "runtime.interrupted":
            saw_interrupted = True
        elif event.type == "artifact.created":
            _append_string(artifact_refs, payload.get("path"))
        elif event.type in {"runtime.checkpoint_recorded", "checkpoint_recorded"}:
            _append_string(checkpoint_ids, _checkpoint_id(payload))
        elif event.type == "recovery.action_proposed":
            action = payload.get("action")
            recovery_actions.append(
                dict(action) if isinstance(action, dict) else dict(payload)
            )
        elif event.type == "task.failed":
            failed_node_id = _string_or_none(payload.get("nodeId")) or failed_node_id
            if payload.get("errorCode") == "permission_required":
                saw_interrupted = True
            else:
                saw_failed = True
        elif event.type == "task.completed":
            saw_completed = True
            final_message = (
                _string_or_none(payload.get("message"))
                or _string_or_none(payload.get("summary"))
                or final_message
            )

    status: Literal["completed", "failed", "interrupted"]
    if saw_interrupted:
        status = "interrupted"
    elif saw_failed:
        status = "failed"
    elif saw_completed:
        status = "completed"
    else:
        status = "failed"

    return AgentExecutionRunResult(
        status=status,
        task_id=compiled_graph.task_id,
        run_id=compiled_graph.run_id,
        thread_id=compiled_graph.thread_id,
        compile_id=compiled_graph.compile_id,
        graph_id=compiled_graph.source_graph_id,
        completed_node_ids=completed_node_ids,
        failed_node_id=failed_node_id,
        artifact_refs=artifact_refs,
        checkpoint_ids=checkpoint_ids,
        recovery_actions=recovery_actions,
        final_message=final_message if status == "completed" else None,
        raw_events=list(events),
    )


def review_agent_execution_result(
    compiled_graph: AgentCompiledGraph,
    result: AgentExecutionRunResult,
) -> AgentExecutionReview:
    if result.status in {"failed", "interrupted"}:
        if result.recovery_actions:
            return AgentExecutionReview(
                status="needs_repair",
                is_valid=False,
                issues=[
                    AgentExecutionIssue(
                        code="execution_repair_available",
                        message="Execution failed or interrupted with recovery actions.",
                        node_id=result.failed_node_id,
                    )
                ],
                final_artifacts=list(result.artifact_refs),
                repair_required=True,
            )
        return AgentExecutionReview(
            status="failed",
            is_valid=False,
            issues=[
                AgentExecutionIssue(
                    code="execution_failed",
                    message="Execution failed or was interrupted.",
                    node_id=result.failed_node_id,
                )
            ],
            final_artifacts=list(result.artifact_refs),
        )

    missing_issues: list[AgentExecutionIssue] = []
    actual_artifacts = set(result.artifact_refs)
    for node in compiled_graph.nodes:
        for artifact in node.expected_artifacts:
            if not _artifact_matches_expected_template(
                artifact.path_template,
                actual_artifacts,
            ):
                missing_issues.append(
                    AgentExecutionIssue(
                        code="missing_expected_artifact",
                        message=(
                            f"Expected artifact was not produced: "
                            f"{artifact.path_template}"
                        ),
                        node_id=node.node_id,
                    )
                )

    if missing_issues:
        return AgentExecutionReview(
            status="failed",
            is_valid=False,
            issues=missing_issues,
            final_artifacts=list(result.artifact_refs),
        )

    return AgentExecutionReview(
        status="approved",
        is_valid=True,
        final_artifacts=list(result.artifact_refs),
    )


def _run_graph_from_compiled_graph(compiled_graph: AgentCompiledGraph) -> RunGraph:
    return RunGraph(
        graphId=compiled_graph.source_graph_id,
        nodes=[
            execution_node.public_node
            for execution_node in compiled_graph.execution_graph.nodes
        ],
        edges=list(compiled_graph.edges),
        metadata=dict(compiled_graph.metadata),
    )


def _checkpoint_id(payload: dict[str, Any]) -> str | None:
    checkpoint = payload.get("checkpoint")
    if isinstance(checkpoint, dict):
        checkpoint_id = checkpoint.get("checkpointId") or checkpoint.get(
            "checkpoint_id"
        )
        if checkpoint_id is not None:
            return str(checkpoint_id)
    checkpoint_id = payload.get("checkpointId") or payload.get("checkpoint_id")
    if checkpoint_id is None:
        return None
    return str(checkpoint_id)


def _artifact_matches_expected_template(
    path_template: str,
    artifact_refs: set[str],
) -> bool:
    if "{" not in path_template:
        return path_template in artifact_refs

    regex = _path_template_regex(path_template)
    if regex is None:
        return False
    return any(
        regex.fullmatch(artifact_ref) is not None
        for artifact_ref in artifact_refs
    )


def _path_template_regex(path_template: str) -> re.Pattern[str] | None:
    parts = re.split(r"(\{[^{}]+\})", path_template)
    if not any(part and not part.startswith("{") for part in parts):
        return None

    pattern = ""
    for part in parts:
        if not part:
            continue
        if part.startswith("{") and part.endswith("}"):
            pattern += r"[^/\\]+"
        else:
            pattern += re.escape(part)
    return re.compile(pattern)


def _append_string(values: list[str], value: Any) -> None:
    string_value = _string_or_none(value)
    if string_value is None or string_value in values:
        return
    values.append(string_value)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)
