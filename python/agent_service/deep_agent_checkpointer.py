from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.memory import InMemorySaver

from agent_service.run_journal import _safe_storage_id

CheckpointerMode = Literal["sqlite", "memory"]


@dataclass
class DeepPlanningCheckpointerBundle:
    checkpointer: Any
    mode: CheckpointerMode
    path: Path | None
    degraded: bool
    degradation_reason: str | None
    _connection: sqlite3.Connection | None

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def deep_planning_thread_config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def planning_checkpoint_db_path(project_path: str, run_id: str) -> Path:
    safe_run_id = _safe_storage_id("run_id", run_id)
    return Path(project_path).parent / "node-runs" / safe_run_id / "deep-planning.sqlite"


def create_deep_planning_checkpointer(
    project_path: str,
    run_id: str,
    mode: CheckpointerMode = "sqlite",
    allow_memory_fallback: bool = False,
) -> DeepPlanningCheckpointerBundle:
    if mode == "memory":
        return DeepPlanningCheckpointerBundle(
            checkpointer=InMemorySaver(),
            mode="memory",
            path=None,
            degraded=False,
            degradation_reason=None,
            _connection=None,
        )

    db_path = planning_checkpoint_db_path(project_path, run_id)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as error:
        if not allow_memory_fallback:
            raise
        return DeepPlanningCheckpointerBundle(
            checkpointer=InMemorySaver(),
            mode="memory",
            path=None,
            degraded=True,
            degradation_reason=(
                f"sqlite_checkpointer_unavailable:{type(error).__name__}"
            ),
            _connection=None,
        )

    connection = sqlite3.connect(db_path, check_same_thread=False)
    return DeepPlanningCheckpointerBundle(
        checkpointer=SqliteSaver(connection),
        mode="sqlite",
        path=db_path,
        degraded=False,
        degradation_reason=None,
        _connection=connection,
    )
