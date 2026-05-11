from pathlib import Path

import pytest

from agent_service.run_journal import RunJournal


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
