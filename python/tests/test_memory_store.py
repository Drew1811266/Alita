from __future__ import annotations

from pathlib import Path

from agent_service.context_policy import budget_for_mode, select_memory_for_context
from agent_service.memory_store import (
    MemoryRecord,
    MemoryStore,
    memory_dir_for_project,
    sanitize_memory_summary,
)


def test_memory_dir_is_project_sibling(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.alita"

    assert memory_dir_for_project(str(project_path)) == tmp_path / "demo.alita-memory"


def test_memory_store_appends_and_lists_records(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path / "demo.alita"))
    record = MemoryRecord(
        memory_id="m1",
        kind="graph_summary",
        summary="Generated a report.",
        source_ref="run-1",
        created_at="2026-05-29T00:00:00Z",
        tags=["report"],
    )

    store.append(record)

    assert store.list() == [record]
    assert store.list(tags=["report"]) == [record]
    assert store.list(tags=["missing"]) == []


def test_memory_store_sanitizes_summary_before_persisting(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path / "demo.alita"))
    record = MemoryRecord(
        memory_id="m-secret",
        kind="tool_outcome",
        summary="api_key=sk-secret D:\\Project\\secret.docx",
        source_ref="run-1",
        created_at="2026-05-29T00:00:00Z",
    )

    store.append(record)

    stored_summary = store.list()[0].summary
    assert "sk-secret" not in stored_summary
    assert "secret.docx" not in stored_summary


def test_sanitize_memory_summary_removes_secrets_paths_and_large_content() -> None:
    text = "api_key=sk-secret D:\\Project\\secret.docx " + ("x" * 2000)

    sanitized = sanitize_memory_summary(text, max_chars=120)

    assert "sk-secret" not in sanitized
    assert "D:\\Project" not in sanitized
    assert "secret.docx" not in sanitized
    assert len(sanitized) <= 120


def test_context_policy_selects_recent_allowed_memory_records() -> None:
    records = [
        MemoryRecord(
            memory_id="old",
            kind="tool_outcome",
            summary="old",
            source_ref="r1",
            created_at="2026-05-28T00:00:00Z",
        ),
        MemoryRecord(
            memory_id="new",
            kind="graph_summary",
            summary="new",
            source_ref="r2",
            created_at="2026-05-29T00:00:00Z",
        ),
        MemoryRecord(
            memory_id="pref",
            kind="preference",
            summary="pref",
            source_ref="user",
            created_at="2026-05-27T00:00:00Z",
        ),
    ]
    budget = budget_for_mode("planning")

    selected = select_memory_for_context(records, budget)

    assert [record.memory_id for record in selected] == ["new", "pref"]
    assert budget.max_chars > 0
