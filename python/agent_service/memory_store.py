from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agent_service.privacy import sanitize_for_web_search


class MemoryRecord(BaseModel):
    memory_id: str
    scope: Literal["project", "global"] = "project"
    kind: Literal["preference", "graph_summary", "artifact_summary", "tool_outcome"]
    summary: str
    source_ref: str
    created_at: str
    tags: list[str] = Field(default_factory=list)


def memory_dir_for_project(project_path: str) -> Path:
    path = Path(project_path)
    return path.with_name(f"{path.name}-memory")


def sanitize_memory_summary(text: str, max_chars: int = 1200) -> str:
    sanitized = sanitize_for_web_search(text).sanitizedText
    sanitized = _SECRET_ASSIGNMENT_RE.sub("[SECRET]", sanitized)
    sanitized = _WINDOWS_PATH_RE.sub("[LOCAL_PATH]", sanitized)
    sanitized = _POSIX_PATH_RE.sub("[LOCAL_PATH]", sanitized)
    sanitized = " ".join(sanitized.split())
    if len(sanitized) <= max_chars:
        return sanitized
    return sanitized[: max_chars - 3].rstrip() + "..."


class MemoryStore:
    def __init__(self, project_path: str) -> None:
        self.project_path = project_path
        self.memory_dir = memory_dir_for_project(project_path)
        self.memory_path = self.memory_dir / "memory.jsonl"

    def append(self, record: MemoryRecord) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        safe_record = record.model_copy(
            update={"summary": sanitize_memory_summary(record.summary)}
        )
        with self.memory_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe_record.model_dump(), ensure_ascii=False) + "\n")

    def list(
        self,
        scope: str = "project",
        tags: list[str] | None = None,
    ) -> list[MemoryRecord]:
        if not self.memory_path.exists():
            return []
        required_tags = set(tags or [])
        records: list[MemoryRecord] = []
        for raw_line in self.memory_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            record = MemoryRecord.model_validate(json.loads(line))
            if record.scope != scope:
                continue
            if required_tags and not required_tags.issubset(set(record.tags)):
                continue
            records.append(record)
        return records


_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^\s'\"]+",
    re.IGNORECASE,
)
_WINDOWS_PATH_RE = re.compile(r"(?<![\w])(?:[A-Za-z]:\\[^\s]+)")
_POSIX_PATH_RE = re.compile(r"(?<![\w:/])/(?:[^\s/]+/)+[^\s]+")
