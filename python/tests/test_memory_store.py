from __future__ import annotations

from pathlib import Path

from agent_service.context_policy import budget_for_mode, select_memory_for_context
from agent_service.memory_store import (
    MemoryRecord,
    MemoryStore,
    memory_id_for_source,
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
        source_refs=["run-1", "file-export"],
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


def test_memory_store_upsert_replaces_existing_record_by_id(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path / "demo.alita"))
    store.append(
        MemoryRecord(
            memory_id="same",
            kind="graph_summary",
            summary="Old summary.",
            source_ref="run-old",
            created_at="2026-05-29T00:00:00Z",
        )
    )

    store.upsert(
        MemoryRecord(
            memory_id="same",
            kind="graph_summary",
            summary="New summary.",
            source_ref="run-new",
            created_at="2026-05-30T00:00:00Z",
            updated_at="2026-05-30T00:00:00Z",
        )
    )

    records = store.list()
    assert len(records) == 1
    assert records[0].summary == "New summary."
    assert records[0].source_ref == "run-new"


def test_memory_store_filters_expired_records_and_marks_used(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path / "demo.alita"))
    store.append(
        MemoryRecord(
            memory_id="expired",
            kind="graph_summary",
            summary="Expired.",
            source_ref="run-old",
            created_at="2026-05-29T00:00:00Z",
            expires_at="2026-05-30T00:00:00Z",
        )
    )
    store.append(
        MemoryRecord(
            memory_id="active",
            kind="graph_summary",
            summary="Active.",
            source_ref="run-new",
            created_at="2026-05-30T00:00:00Z",
        )
    )

    assert [record.memory_id for record in store.list(now="2026-05-31T00:00:00Z")] == [
        "active"
    ]

    store.mark_used(["active"], used_at="2026-05-31T01:00:00Z")

    assert store.list()[1].last_used_at == "2026-05-31T01:00:00Z"


def test_memory_record_v2_defaults_are_backward_compatible() -> None:
    record = MemoryRecord(
        memory_id="memory-1",
        kind="preference",
        summary="Prefer concise reports.",
        source_ref="user",
        created_at="2026-05-30T00:00:00Z",
    )

    assert record.schema_version == 2
    assert record.importance == 0.5
    assert record.confidence == 0.8
    assert record.visibility == "project"


def test_memory_selection_prefers_relevant_high_importance_records() -> None:
    records = [
        MemoryRecord(
            memory_id="old",
            kind="graph_summary",
            summary="Unrelated weather research.",
            source_ref="run-old",
            created_at="2026-05-29T00:00:00Z",
            importance=0.4,
        ),
        MemoryRecord(
            memory_id="new",
            kind="tool_outcome",
            summary="CSV parser failed on quoted rows.",
            source_ref="run-new",
            created_at="2026-05-30T00:00:00Z",
            importance=0.9,
            tags=["csv"],
        ),
    ]

    selected = select_memory_for_context(
        records,
        budget_for_mode("planning"),
        query="Fix CSV parser quoted rows",
    )

    assert selected[0].memory_id == "new"


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


def test_memory_id_for_source_is_stable_and_path_safe() -> None:
    first = memory_id_for_source(
        "artifact_summary",
        r"D:\Project\secret\report.md",
    )
    second = memory_id_for_source(
        "artifact_summary",
        r"D:\Project\secret\report.md",
    )

    assert first == second
    assert first.startswith("artifact_summary-")
    assert "Project" not in first
    assert "report.md" not in first
