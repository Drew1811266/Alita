from __future__ import annotations

from time import perf_counter
from typing import Any


class ObservationTimer:
    def __init__(self) -> None:
        self.started = perf_counter()

    def elapsed_ms(self) -> int:
        return int((perf_counter() - self.started) * 1000)


def observation_metadata(
    *,
    tool_id: str,
    provider_id: str,
    ok: bool,
    duration_ms: int,
    authority_code: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    return {
        "observation": {
            "toolId": tool_id,
            "providerId": provider_id,
            "ok": ok,
            "durationMs": duration_ms,
            "authorityCode": authority_code,
            "errorCode": error_code,
        }
    }
