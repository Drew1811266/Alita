from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

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
from agent_service.model_sessions import DEFAULT_MODEL_SESSION_REGISTRY
from agent_service.run_registry import DEFAULT_RUN_REGISTRY
from agent_service.schemas import (
    AgentEvent,
    CancelRunRequest,
    RegisterModelSessionRequest,
    RegisterModelSessionResponse,
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
VALIDATION_SECRET_KEYS = {"apiKey", "api_key"}


def require_sidecar_token(
    sidecar_token: str | None = Header(default=None, alias=SIDECAR_TOKEN_HEADER),
) -> None:
    expected_token = os.getenv(SIDECAR_TOKEN_ENV)
    if not expected_token:
        return
    if sidecar_token != expected_token:
        raise HTTPException(status_code=401, detail="invalid sidecar token")


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    _request: Request,
    error: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder(
            {"detail": sanitize_validation_error_detail(error.errors())}
        ),
    )


def sanitize_validation_error_detail(value: Any) -> Any:
    if isinstance(value, list):
        return [sanitize_validation_error_detail(item) for item in value]
    if isinstance(value, dict):
        return {
            key: "<redacted>"
            if key in VALIDATION_SECRET_KEYS
            else sanitize_validation_error_detail(item)
            for key, item in value.items()
            if key != "input"
        }
    return value


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


@app.post("/agent/model/session", response_model=RegisterModelSessionResponse)
def register_model_session(
    request: RegisterModelSessionRequest,
    _auth: None = Depends(require_sidecar_token),
) -> RegisterModelSessionResponse:
    session_id = DEFAULT_MODEL_SESSION_REGISTRY.register(request.model_config_value)
    return RegisterModelSessionResponse(modelSessionId=session_id)


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
