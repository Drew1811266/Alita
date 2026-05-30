from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent_service.memory_store import MemoryRecord


class ContextBudget(BaseModel):
    mode: Literal["chat", "planning", "execution", "research"]
    max_memory_records: int
    max_chars: int
    allowed_kinds: list[str] = Field(default_factory=list)


def budget_for_mode(mode: str) -> ContextBudget:
    if mode == "chat":
        return ContextBudget(
            mode="chat",
            max_memory_records=3,
            max_chars=1600,
            allowed_kinds=["preference", "graph_summary"],
        )
    if mode == "planning":
        return ContextBudget(
            mode="planning",
            max_memory_records=2,
            max_chars=2400,
            allowed_kinds=["preference", "graph_summary", "tool_outcome"],
        )
    if mode == "execution":
        return ContextBudget(
            mode="execution",
            max_memory_records=3,
            max_chars=1200,
            allowed_kinds=["tool_outcome", "graph_summary"],
        )
    if mode == "research":
        return ContextBudget(
            mode="research",
            max_memory_records=4,
            max_chars=2000,
            allowed_kinds=["graph_summary", "artifact_summary"],
        )
    raise ValueError(f"unsupported context mode: {mode}")


def select_memory_for_context(
    records: list[MemoryRecord],
    budget: ContextBudget,
) -> list[MemoryRecord]:
    allowed_kinds = set(budget.allowed_kinds)
    eligible = [
        record
        for record in records
        if not allowed_kinds or record.kind in allowed_kinds
    ]
    ordered = sorted(
        eligible,
        key=lambda record: (record.created_at, record.memory_id),
        reverse=True,
    )
    selected = ordered[: budget.max_memory_records]
    selected_ids = {record.memory_id for record in selected}

    preferences = [
        record
        for record in ordered
        if record.kind == "preference" and record.memory_id not in selected_ids
    ]
    if preferences and len(selected) == budget.max_memory_records:
        replace_index = _oldest_non_preference_index(selected)
        if replace_index is not None:
            selected[replace_index] = preferences[0]

    selected = sorted(
        selected,
        key=lambda record: (record.created_at, record.memory_id),
        reverse=True,
    )
    return _within_char_budget(selected, budget.max_chars)


def _oldest_non_preference_index(records: list[MemoryRecord]) -> int | None:
    for index in range(len(records) - 1, -1, -1):
        if records[index].kind != "preference":
            return index
    return None


def _within_char_budget(
    records: list[MemoryRecord],
    max_chars: int,
) -> list[MemoryRecord]:
    selected: list[MemoryRecord] = []
    used_chars = 0
    for record in records:
        next_chars = len(record.summary)
        if selected and used_chars + next_chars > max_chars:
            continue
        if not selected and next_chars > max_chars:
            continue
        selected.append(record)
        used_chars += next_chars
    return selected
