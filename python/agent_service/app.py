from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent_service.execution import run_graph_events
from agent_service.graph import run_agent, stream_agent_events
from agent_service.run_registry import DEFAULT_RUN_REGISTRY
from agent_service.schemas import (
    AgentEvent,
    CancelRunRequest,
    RunGraphRequest,
    UserMessage,
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


@app.post("/agent/message", response_model=list[AgentEvent])
def agent_message(
    message: UserMessage,
    _auth: None = Depends(require_sidecar_token),
) -> list[AgentEvent]:
    return run_agent(message)


@app.post("/agent/message/stream")
def agent_message_stream(
    message: UserMessage,
    _auth: None = Depends(require_sidecar_token),
) -> StreamingResponse:
    return StreamingResponse(
        _serialize_sse_events(message),
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


def _serialize_sse_events(message: UserMessage):
    for event in stream_agent_events(message):
        yield f"data: {event.model_dump_json()}\n\n"


def _serialize_graph_sse_events(request: RunGraphRequest):
    for event in run_graph_events(request, registry=DEFAULT_RUN_REGISTRY):
        yield f"data: {event.model_dump_json()}\n\n"
