from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass
class CancelToken:
    run_id: str
    cancelled: bool = False


class RunRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._tokens: dict[str, CancelToken] = {}

    def start(self, run_id: str) -> CancelToken:
        with self._lock:
            token = CancelToken(run_id=run_id)
            self._tokens[run_id] = token
            return token

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            token = self._tokens.get(run_id)
            if token is None:
                return False
            token.cancelled = True
            return True

    def finish(self, run_id: str) -> None:
        with self._lock:
            self._tokens.pop(run_id, None)


DEFAULT_RUN_REGISTRY = RunRegistry()
