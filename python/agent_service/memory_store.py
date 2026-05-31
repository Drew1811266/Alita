from __future__ import annotations

import json
import re
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agent_service.privacy import sanitize_for_web_search


class MemoryRecord(BaseModel):
    memory_id: str
    schema_version: int = 2
    scope: Literal["project", "global"] = "project"
    kind: Literal["preference", "graph_summary", "artifact_summary", "tool_outcome"]
    summary: str
    source_type: str = "run"
    source_ref: str
    source_refs: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str | None = None
    last_used_at: str | None = None
    expires_at: str | None = None
    importance: float = 0.5
    confidence: float = 0.8
    visibility: Literal["private", "project", "global"] = "project"
    tags: list[str] = Field(default_factory=list)


def memory_dir_for_project(project_path: str) -> Path:
    path = Path(project_path)
    return path.with_name(f"{path.name}-memory")


def memory_id_for_source(kind: str, source_ref: str) -> str:
    digest = hashlib.sha256(source_ref.encode("utf-8")).hexdigest()[:16]
    safe_kind = re.sub(r"[^a-z0-9_]+", "_", kind.lower()).strip("_")
    return f"{safe_kind}-{digest}"


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

    def upsert(self, record: MemoryRecord) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        safe_record = record.model_copy(
            update={"summary": sanitize_memory_summary(record.summary)}
        )
        records = self._read_all()
        replaced = False
        updated_records: list[MemoryRecord] = []
        for existing in records:
            if existing.memory_id == safe_record.memory_id:
                updated_records.append(safe_record)
                replaced = True
            else:
                updated_records.append(existing)
        if not replaced:
            updated_records.append(safe_record)
        self._write_all(updated_records)

    def mark_used(self, memory_ids: list[str], *, used_at: str) -> None:
        ids = set(memory_ids)
        if not ids:
            return
        records = [
            record.model_copy(update={"last_used_at": used_at})
            if record.memory_id in ids
            else record
            for record in self._read_all()
        ]
        self._write_all(records)

    def list(
        self,
        scope: str = "project",
        tags: list[str] | None = None,
        now: str | None = None,
    ) -> list[MemoryRecord]:
        required_tags = set(tags or [])
        records: list[MemoryRecord] = []
        for record in self._read_all():
            if record.scope != scope:
                continue
            if required_tags and not required_tags.issubset(set(record.tags)):
                continue
            if now is not None and record.expires_at is not None and record.expires_at <= now:
                continue
            records.append(record)
        return records

    def _read_all(self) -> list[MemoryRecord]:
        if not self.memory_path.exists():
            return []
        records: list[MemoryRecord] = []
        for raw_line in self.memory_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            records.append(MemoryRecord.model_validate(json.loads(line)))
        return records

    def _write_all(self, records: list[MemoryRecord]) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(
            json.dumps(record.model_dump(), ensure_ascii=False)
            for record in records
        )
        if payload:
            payload += "\n"
        self.memory_path.write_text(payload, encoding="utf-8")


_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^\s'\"]+",
    re.IGNORECASE,
)
_WINDOWS_PATH_RE = re.compile(r"(?<![\w])(?:[A-Za-z]:\\[^\s]+)")
_POSIX_PATH_RE = re.compile(r"(?<![\w:/])/(?:[^\s/]+/)+[^\s]+")
