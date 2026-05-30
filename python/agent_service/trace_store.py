from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_service.runtime_trace import RuntimeSpan


class TraceStore:
    def __init__(self, *, project_path: str, run_id: str) -> None:
        self.base_dir = Path(project_path).parent / "node-runs" / run_id
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.trace_path = self.base_dir / "trace.jsonl"

    def append_span(self, span: RuntimeSpan) -> None:
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(span.to_record(), ensure_ascii=False) + "\n")

    def list_spans(self) -> list[dict[str, Any]]:
        if not self.trace_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.trace_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
