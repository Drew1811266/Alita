import json
from pathlib import Path

from agent_service.runtime_state import RuntimeStateDelta, initial_runtime_state
from agent_service.runtime_loop import RuntimeCheckpoint
from agent_service.runtime_store import RuntimeStore
from agent_service.schemas import UserMessage


def test_runtime_store_persists_state_and_deltas(tmp_path: Path) -> None:
    store = RuntimeStore(project_path=str(tmp_path / "demo.alita"), run_id="run-store")
    state = initial_runtime_state(
        message=UserMessage(task_id="task-store", content="Create a report."),
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-store",
    )
    delta = RuntimeStateDelta(
        previous_checkpoint_id=None,
        checkpoint_id="ckpt-run-store-000001-abc",
        stage_before="route",
        stage_after="plan",
        decision={"kind": "legacy_route_and_plan"},
        writes=[{"kind": "action_graph"}],
    )

    store.write_state(state)
    store.write_delta(delta)

    restored_state = store.read_state()
    restored_deltas = store.read_deltas()

    assert restored_state is not None
    assert restored_state.run_id == "run-store"
    assert restored_state.task_id == "task-store"
    assert restored_state.stage == "route"
    assert [item.checkpoint_id for item in restored_deltas] == [
        "ckpt-run-store-000001-abc"
    ]
    assert restored_deltas[0].decision == {"kind": "legacy_route_and_plan"}


def test_runtime_store_restores_state_from_latest_or_requested_checkpoint(
    tmp_path: Path,
) -> None:
    store = RuntimeStore(project_path=str(tmp_path / "demo.alita"), run_id="run-restore")
    route_state = initial_runtime_state(
        message=UserMessage(task_id="task-restore", content="Create a report."),
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-restore",
    )
    plan_state = route_state.model_copy(update={"stage": "plan"})

    store.write_checkpoint(
        RuntimeCheckpoint(
            run_id="run-restore",
            node_id="route",
            status="after_node",
            completed_outputs={},
            pending_node_ids=[],
            created_at="2026-05-31T00:00:00Z",
            sequence=1,
            runtime_state=route_state.model_dump(),
        )
    )
    store.write_checkpoint(
        RuntimeCheckpoint(
            run_id="run-restore",
            node_id="plan",
            status="after_node",
            completed_outputs={},
            pending_node_ids=[],
            created_at="2026-05-31T00:00:01Z",
            sequence=2,
            runtime_state=plan_state.model_dump(),
        )
    )

    latest = store.restore_state()
    requested = store.restore_state("route:after_node:0")

    assert latest is not None
    assert latest.stage == "plan"
    assert requested is not None
    assert requested.stage == "route"


def test_runtime_store_writes_and_reads_planning_checkpoint_summary_sanitizing_extras(
    tmp_path: Path,
) -> None:
    store = RuntimeStore(project_path=str(tmp_path / "demo.alita"), run_id="run-planning")

    store.write_planning_checkpoint_summary(
        {
            "runId": "run-planning",
            "threadId": "thread-1",
            "checkpointId": "checkpoint-1",
            "stage": "planning",
            "node": "deep_plan",
            "revisionCount": 3,
            "hasPlanDraft": True,
            "hasCompiledGraph": False,
            "hasAgentCompiledGraph": True,
            "executionReady": True,
            "createdAt": "2026-06-02T00:00:00Z",
            "rawReasoning": "should be removed",
            "projectPath": "/tmp/project",
            "planDraft": {"steps": [1]},
        }
    )

    summaries = store.read_planning_checkpoint_summaries()
    stored_payload = json.loads(
        (
            tmp_path
            / "node-runs"
            / "run-planning"
            / "planning_checkpoints.json"
        ).read_text(encoding="utf-8")
    )

    assert summaries == [
        {
            "runId": "run-planning",
            "threadId": "thread-1",
            "checkpointId": "checkpoint-1",
            "stage": "planning",
            "node": "deep_plan",
            "revisionCount": 3,
            "hasPlanDraft": True,
            "hasCompiledGraph": False,
            "hasAgentCompiledGraph": True,
            "executionReady": True,
            "createdAt": "2026-06-02T00:00:00Z",
        }
    ]
    assert list(stored_payload) == ["checkpoints"]


def test_runtime_store_reads_latest_planning_checkpoint_summary(tmp_path: Path) -> None:
    store = RuntimeStore(project_path=str(tmp_path / "demo.alita"), run_id="run-latest")

    assert store.read_latest_planning_checkpoint_summary() is None

    store.write_planning_checkpoint_summary(
        {
            "runId": "run-latest",
            "threadId": "thread-1",
            "checkpointId": "checkpoint-1",
            "stage": "planning",
            "revisionCount": 0,
            "hasPlanDraft": False,
            "hasCompiledGraph": False,
            "hasAgentCompiledGraph": False,
            "executionReady": False,
            "createdAt": "2026-06-02T00:00:01Z",
        }
    )
    store.write_planning_checkpoint_summary(
        {
            "runId": "run-latest",
            "threadId": "thread-1",
            "checkpointId": "checkpoint-2",
            "stage": "graph",
            "revisionCount": 1,
            "hasPlanDraft": True,
            "hasCompiledGraph": True,
            "hasAgentCompiledGraph": True,
            "executionReady": True,
            "createdAt": "2026-06-02T00:00:02Z",
        }
    )

    latest = store.read_latest_planning_checkpoint_summary()

    assert latest is not None
    assert latest["checkpointId"] == "checkpoint-2"
    assert latest["revisionCount"] == 1
    assert latest["hasAgentCompiledGraph"] is True
    assert latest["executionReady"] is True


def test_runtime_store_read_nodes_still_ignores_control_files(tmp_path: Path) -> None:
    from agent_service.run_journal import RunJournal

    journal = RunJournal(project_path=str(tmp_path / "demo.alita"), run_id="run-read-nodes")
    journal.write_node("step", {"nodeId": "step", "status": "completed"})
    journal._write_json(journal.base_dir / "runtime_state.json", {"state": {}})
    journal._write_json(journal.base_dir / "runtime_deltas.json", {"deltas": []})
    journal._write_json(
        journal.base_dir / "planning_checkpoints.json",
        {"checkpoints": []},
    )

    records = journal.read_nodes()

    assert records == [{"nodeId": "step", "status": "completed"}]
