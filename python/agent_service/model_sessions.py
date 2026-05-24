from __future__ import annotations

from threading import Lock
from uuid import uuid4

from agent_service.schemas import AgentModelConfig


class ModelSessionRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._configs: dict[str, AgentModelConfig] = {}

    def register(self, config: AgentModelConfig) -> str:
        session_id = f"model-session-{uuid4()}"
        with self._lock:
            self._configs[session_id] = config
        return session_id

    def consume(self, session_id: str) -> AgentModelConfig | None:
        if not session_id.strip():
            raise ValueError("model session id is required")
        with self._lock:
            return self._configs.pop(session_id, None)


DEFAULT_MODEL_SESSION_REGISTRY = ModelSessionRegistry()
