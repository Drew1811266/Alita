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
