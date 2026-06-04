from pathlib import Path
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from agent_service.deep_agent_checkpointer import (
    create_deep_planning_checkpointer,
    deep_planning_thread_config,
    planning_checkpoint_db_path,
)


def test_thread_config_uses_langgraph_configurable_thread_id() -> None:
    assert deep_planning_thread_config("thread-123") == {
        "configurable": {"thread_id": "thread-123"}
    }


def test_planning_checkpoint_db_path_uses_node_runs_under_project_parent(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "workspace" / "project"

    assert planning_checkpoint_db_path(str(project_path), "run-123") == (
        tmp_path
        / "workspace"
        / "node-runs"
        / "run-123"
        / "deep-planning.sqlite"
    )


@pytest.mark.parametrize("run_id", ["../escape", "run/escape", r"run\escape"])
def test_planning_checkpoint_db_path_rejects_unsafe_run_id(
    tmp_path: Path,
    run_id: str,
) -> None:
    with pytest.raises(ValueError, match="invalid run_id"):
        planning_checkpoint_db_path(str(tmp_path / "project"), run_id)


def test_factory_rejects_unsafe_run_id_before_creating_directory(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="invalid run_id"):
        create_deep_planning_checkpointer(str(tmp_path / "project"), "../escape")

    assert not (tmp_path / "node-runs").exists()


def test_factory_can_create_memory_checkpointer_for_tests(tmp_path: Path) -> None:
    bundle = create_deep_planning_checkpointer(
        str(tmp_path / "project"),
        "run-memory",
        mode="memory",
    )

    assert isinstance(bundle.checkpointer, InMemorySaver)
    assert bundle.mode == "memory"
    assert bundle.path is None
    assert bundle.degraded is False
    assert bundle.degradation_reason is None


def test_factory_can_create_sqlite_checkpointer_and_close(tmp_path: Path) -> None:
    project_path = tmp_path / "project"
    expected_path = tmp_path / "node-runs" / "run-sqlite" / "deep-planning.sqlite"

    bundle = create_deep_planning_checkpointer(str(project_path), "run-sqlite")

    try:
        assert expected_path.exists()
        assert bundle.mode == "sqlite"
        assert bundle.path == expected_path
        assert bundle.degraded is False
        assert bundle.degradation_reason is None
        assert bundle._connection is not None
    finally:
        bundle.close()

    bundle.close()


def test_sqlite_checkpointer_persists_state_history_for_tiny_graph(
    tmp_path: Path,
) -> None:
    class SmokeState(TypedDict):
        value: int

    def write_value(state: SmokeState) -> SmokeState:
        return {"value": 42}

    bundle = create_deep_planning_checkpointer(str(tmp_path / "project"), "run-smoke")

    try:
        graph = StateGraph(SmokeState)
        graph.add_node("write_value", write_value)
        graph.set_entry_point("write_value")
        graph.add_edge("write_value", END)
        app = graph.compile(checkpointer=bundle.checkpointer)

        config = deep_planning_thread_config("thread-sqlite-smoke")
        output = app.invoke({"value": 0}, config)

        assert output["value"] == 42
        assert list(app.get_state_history(config))
    finally:
        bundle.close()
