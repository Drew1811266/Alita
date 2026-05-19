from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent_service.asr import (
    ASRError,
    ASRStatus,
    DEFAULT_ASR_SERVICE,
    TranscriptionRequest,
    TranscriptionResponse,
    get_asr_status,
)
from agent_service.execution import run_graph_events
from agent_service.graph import run_agent, stream_agent_events
from agent_service.run_registry import DEFAULT_RUN_REGISTRY
from agent_service.schemas import (
    AgentEvent,
    AgentMessageRequest,
    CancelRunRequest,
    GraphNode,
    ResearchChoiceRequest,
    RunGraphRequest,
    ScriptApprovalRequest,
    ScriptRejectionRequest,
)
from agent_service.script_review import script_review_fingerprint


app = FastAPI(title="Alita Agent Sidecar")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SIDECAR_TOKEN_ENV = "ALITA_SIDECAR_TOKEN"
SIDECAR_TOKEN_HEADER = "X-Alita-Sidecar-Token"


def require_sidecar_token(
    sidecar_token: str | None = Header(default=None, alias=SIDECAR_TOKEN_HEADER),
) -> None:
    expected_token = os.getenv(SIDECAR_TOKEN_ENV)
    if not expected_token:
        return
    if sidecar_token != expected_token:
        raise HTTPException(status_code=401, detail="invalid sidecar token")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/asr/status", response_model=ASRStatus)
def asr_status(
    modelPath: str | None = None,
    _auth: None = Depends(require_sidecar_token),
) -> ASRStatus:
    path = Path(modelPath).expanduser() if modelPath is not None else None
    return get_asr_status(model_path=path)


@app.post("/asr/transcribe", response_model=TranscriptionResponse)
def asr_transcribe(
    request: TranscriptionRequest,
    _auth: None = Depends(require_sidecar_token),
) -> TranscriptionResponse:
    try:
        return DEFAULT_ASR_SERVICE.transcribe(request)
    except ASRError as error:
        raise HTTPException(
            status_code=409 if error.code == "asr_busy" else 400,
            detail={"errorCode": error.code, "error": error.message},
        ) from error


@app.post("/agent/message", response_model=list[AgentEvent])
def agent_message(
    request: AgentMessageRequest,
    _auth: None = Depends(require_sidecar_token),
) -> list[AgentEvent]:
    return run_agent(
        request.to_user_message(),
        inquiry_choice=request.inquiry_choice,
        current_graph=request.currentGraph,
        has_run_history=bool(request.hasRunHistory),
        artifact_refs=request.artifactRefs,
        pending_choice=request.pendingChoice,
    )


@app.post("/agent/research/choose", response_model=list[AgentEvent])
def research_choose(
    request: ResearchChoiceRequest,
    _auth: None = Depends(require_sidecar_token),
) -> list[AgentEvent]:
    return run_agent(
        request.to_user_message(),
        inquiry_choice=request.inquiry_choice,
        current_graph=request.currentGraph,
        has_run_history=bool(request.hasRunHistory),
        artifact_refs=request.artifactRefs,
        pending_choice=request.pendingChoice,
    )


@app.post("/agent/message/stream")
def agent_message_stream(
    request: AgentMessageRequest,
    _auth: None = Depends(require_sidecar_token),
) -> StreamingResponse:
    return StreamingResponse(
        _serialize_sse_events(request),
        media_type="text/event-stream",
    )


@app.post("/agent/graph/run/stream")
def graph_run_stream(
    request: RunGraphRequest,
    _auth: None = Depends(require_sidecar_token),
) -> StreamingResponse:
    return StreamingResponse(
        _serialize_graph_sse_events(request),
        media_type="text/event-stream",
    )


@app.post("/agent/graph/run/cancel")
def cancel_graph_run(
    request: CancelRunRequest,
    _auth: None = Depends(require_sidecar_token),
) -> dict[str, bool]:
    return {"cancelled": DEFAULT_RUN_REGISTRY.cancel(request.run_id)}


@app.post("/agent/scripts/approve", response_model=list[AgentEvent])
def approve_temporary_script(
    request: ScriptApprovalRequest,
    _auth: None = Depends(require_sidecar_token),
) -> list[AgentEvent]:
    graph = request.currentGraph.model_copy(deep=True)
    node = _script_node_for_request(graph.nodes, request.node_id)
    review = node.scriptReview
    if review is None:
        raise HTTPException(status_code=400, detail="temporary script has no review state")

    expected_fingerprint = script_review_fingerprint(review)
    if request.approvalFingerprint != expected_fingerprint:
        raise HTTPException(
            status_code=409,
            detail="approval fingerprint does not match script review state",
        )

    review.status = "approved"
    review.approvalFingerprint = expected_fingerprint
    node.status = _status_after_permission_approval(node, graph.nodes)
    return [_graph_snapshot_event(graph, "Temporary script approved.")]


@app.post("/agent/scripts/reject", response_model=list[AgentEvent])
def reject_temporary_script(
    request: ScriptRejectionRequest,
    _auth: None = Depends(require_sidecar_token),
) -> list[AgentEvent]:
    graph = request.currentGraph.model_copy(deep=True)
    node = _script_node_for_request(graph.nodes, request.node_id)
    review = node.scriptReview
    if review is None:
        raise HTTPException(status_code=400, detail="temporary script has no review state")

    review.status = "rejected"
    review.approvalFingerprint = None
    node.status = "needs_permission"
    return [_graph_snapshot_event(graph, "Temporary script rejected.")]


def _serialize_sse_events(request: AgentMessageRequest):
    for event in stream_agent_events(
        request.to_user_message(),
        inquiry_choice=request.inquiry_choice,
        current_graph=request.currentGraph,
        has_run_history=bool(request.hasRunHistory),
        artifact_refs=request.artifactRefs,
        pending_choice=request.pendingChoice,
    ):
        yield f"data: {event.model_dump_json()}\n\n"


def _serialize_graph_sse_events(request: RunGraphRequest):
    for event in run_graph_events(request, registry=DEFAULT_RUN_REGISTRY):
        yield f"data: {event.model_dump_json()}\n\n"


def _script_node_for_request(nodes: list[GraphNode], node_id: str) -> GraphNode:
    for node in nodes:
        if node.nodeId == node_id:
            if node.nodeType != "temporary_script":
                raise HTTPException(
                    status_code=400,
                    detail="node is not a temporary script",
                )
            return node
    raise HTTPException(status_code=404, detail="temporary script node not found")


def _status_after_permission_approval(
    node: GraphNode,
    nodes: list[GraphNode],
) -> str:
    completed = {candidate.nodeId for candidate in nodes if candidate.status == "completed"}
    if all(dependency in completed for dependency in node.dependencies):
        return "ready"
    return "waiting"


def _graph_snapshot_event(graph, summary: str) -> AgentEvent:
    return AgentEvent(
        type="graph.replanned",
        payload={
            "graph": graph.model_dump(),
            "previousGraphId": graph.graphId,
            "summary": summary,
        },
    )
