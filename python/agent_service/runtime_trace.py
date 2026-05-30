from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def trace_id_for_run(run_id: str) -> str:
    return f"trace-{run_id}"


def next_span_id(counter: int) -> str:
    return f"span-{counter:06d}"


@dataclass(frozen=True)
class RuntimeSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    run_id: str
    node_id: str | None
    kind: str
    name: str
    status: str
    started_at: str
    ended_at: str | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_span_id,
            "runId": self.run_id,
            "nodeId": self.node_id,
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "durationMs": self.duration_ms,
            "metadata": dict(self.metadata),
        }
