from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from time import monotonic
from uuid import uuid4

from agent_service.schemas import AgentModelConfig


DEFAULT_MODEL_SESSION_TTL_SECONDS = 300.0


class ModelSessionRegistry:
    def __init__(
        self,
        ttl_seconds: float = DEFAULT_MODEL_SESSION_TTL_SECONDS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._lock = Lock()
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._configs: dict[str, tuple[AgentModelConfig, float]] = {}

    def register(self, config: AgentModelConfig) -> str:
        session_id = f"model-session-{uuid4()}"
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            self._configs[session_id] = (config, now + self._ttl_seconds)
        return session_id

    def consume(self, session_id: str) -> AgentModelConfig | None:
        if not session_id.strip():
            raise ValueError("model session id is required")
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            entry = self._configs.pop(session_id, None)
        if entry is None:
            return None
        return entry[0]

    def _purge_expired(self, now: float) -> None:
        expired_session_ids = [
            session_id
            for session_id, (_, expires_at) in self._configs.items()
            if expires_at <= now
        ]
        for session_id in expired_session_ids:
            del self._configs[session_id]


DEFAULT_MODEL_SESSION_REGISTRY = ModelSessionRegistry()
