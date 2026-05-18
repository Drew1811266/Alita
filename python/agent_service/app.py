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
    RunGraphRequest,
)


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
