from pathlib import Path

import pytest

from agent_service.run_journal import RunJournal
from agent_service.runtime_loop import RuntimeCheckpoint


def test_writes_run_and_node_records(tmp_path: Path) -> None:
    journal = RunJournal(project_path=str(tmp_path / "demo.alita"), run_id="run-1")

    journal.write_run({"runId": "run-1", "status": "running"})
    journal.write_node(
        "document-parse",
        {"nodeId": "document-parse", "status": "completed"},
    )

    assert (tmp_path / "node-runs" / "run-1" / "run.json").exists()
    assert (tmp_path / "node-runs" / "run-1" / "document-parse.json").exists()
    assert journal.read_node("document-parse")["status"] == "completed"


def test_rejects_unsafe_run_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run_id"):
        RunJournal(project_path=str(tmp_path / "demo.alita"), run_id="../escape")

    assert not (tmp_path / "escape").exists()


def test_rejects_unsafe_node_id(tmp_path: Path) -> None:
    journal = RunJournal(project_path=str(tmp_path / "demo.alita"), run_id="run-1")

    with pytest.raises(ValueError, match="node_id"):
        journal.write_node("../escape", {"status": "failed"})

    assert not (tmp_path / "node-runs" / "escape.json").exists()


def test_run_journal_persists_latest_checkpoint(tmp_path: Path) -> None:
    journal = RunJournal(project_path=str(tmp_path / "demo.alita"), run_id="run-1")

    journal.write_checkpoint(
        RuntimeCheckpoint(
            run_id="run-1",
            node_id="document-input",
            status="before_node",
            completed_outputs={},
            pending_node_ids=["document-input", "document-parse"],
            created_at="2026-05-30T00:00:00Z",
            recovery_count=0,
        )
    )
    journal.write_checkpoint(
        RuntimeCheckpoint(
            run_id="run-1",
            node_id="document-input",
            status="after_node",
            completed_outputs={"document-input": {"values": {"paths": "input.md"}}},
            pending_node_ids=["document-parse"],
            created_at="2026-05-30T00:00:01Z",
            recovery_count=0,
        )
    )

    latest = journal.read_latest_checkpoint()

    assert latest is not None
    assert latest["nodeId"] == "document-input"
    assert latest["status"] == "after_node"
    assert latest["pendingNodeIds"] == ["document-parse"]


def test_run_journal_reads_checkpoint_by_id(tmp_path: Path) -> None:
    journal = RunJournal(project_path=str(tmp_path / "demo.alita"), run_id="run-1")

    journal.write_checkpoint(
        RuntimeCheckpoint(
            run_id="run-1",
            node_id="first",
            status="before_node",
            completed_outputs={},
            pending_node_ids=["first", "task-output"],
            created_at="2026-05-30T00:00:00Z",
            recovery_count=0,
        )
    )
    journal.write_checkpoint(
        RuntimeCheckpoint(
            run_id="run-1",
            node_id="task-output",
            status="after_node",
            completed_outputs={"first": {"values": {"text": "done"}}},
            pending_node_ids=[],
            created_at="2026-05-30T00:00:01Z",
            recovery_count=0,
        )
    )

    checkpoint = journal.read_checkpoint("first:before_node:0")

    assert checkpoint is not None
    assert checkpoint["checkpointId"] == "first:before_node:0"
    assert checkpoint["nodeId"] == "first"
