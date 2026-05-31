from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent_service.runtime_loop import RuntimeCheckpoint
from agent_service.runtime_state import RuntimeState, RuntimeStateDelta

SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class RunJournal:
    def __init__(self, *, project_path: str, run_id: str) -> None:
        safe_run_id = _safe_storage_id("run_id", run_id)
        self.base_dir = Path(project_path).parent / "node-runs" / safe_run_id
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def write_run(self, payload: dict[str, Any]) -> None:
        self._write_json(self.base_dir / "run.json", payload)

    def read_run(self) -> dict[str, Any]:
        return json.loads((self.base_dir / "run.json").read_text(encoding="utf-8"))

    def write_node(self, node_id: str, payload: dict[str, Any]) -> None:
        safe_node_id = _safe_storage_id("node_id", node_id)
        self._write_json(self.base_dir / f"{safe_node_id}.json", payload)

    def read_node(self, node_id: str) -> dict[str, Any]:
        safe_node_id = _safe_storage_id("node_id", node_id)
        return json.loads(
            (self.base_dir / f"{safe_node_id}.json").read_text(encoding="utf-8")
        )

    def read_nodes(self) -> list[dict[str, Any]]:
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in self.base_dir.glob("*.json")
            if path.name not in {"run.json", "audit.json", "checkpoints.json"}
        ]

    def write_audit_event(self, payload: dict[str, Any]) -> None:
        events = self.read_audit_events()
        events.append(payload)
        self._write_json(self.base_dir / "audit.json", {"events": events})

    def read_audit_events(self) -> list[dict[str, Any]]:
        path = self.base_dir / "audit.json"
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        return list(payload.get("events", []))

    def write_checkpoint(self, checkpoint: RuntimeCheckpoint) -> None:
        checkpoints = self.read_checkpoints()
        checkpoints.append(checkpoint.to_record())
        self._write_json(self.base_dir / "checkpoints.json", {"checkpoints": checkpoints})

    def read_checkpoints(self) -> list[dict[str, Any]]:
        path = self.base_dir / "checkpoints.json"
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        return list(payload.get("checkpoints", []))

    def read_latest_checkpoint(self) -> dict[str, Any] | None:
        checkpoints = self.read_checkpoints()
        if not checkpoints:
            return None
        return checkpoints[-1]

    def read_checkpoint(self, checkpoint_id: str) -> dict[str, Any] | None:
        for checkpoint in self.read_checkpoints():
            if checkpoint.get("checkpointId") == checkpoint_id:
                return checkpoint
            if checkpoint.get("checkpointLabel") == checkpoint_id:
                return checkpoint
        return None

    def write_runtime_state(self, state: RuntimeState) -> None:
        self._write_json(self.base_dir / "runtime_state.json", {"state": state.model_dump()})

    def read_runtime_state(self) -> dict[str, Any] | None:
        path = self.base_dir / "runtime_state.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        state = payload.get("state")
        return dict(state) if isinstance(state, dict) else None

    def write_runtime_delta(self, delta: RuntimeStateDelta) -> None:
        deltas = self.read_runtime_deltas()
        deltas.append(delta.model_dump())
        self._write_json(self.base_dir / "runtime_deltas.json", {"deltas": deltas})

    def read_runtime_deltas(self) -> list[dict[str, Any]]:
        path = self.base_dir / "runtime_deltas.json"
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        return list(payload.get("deltas", []))

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)


def _safe_storage_id(kind: str, value: str) -> str:
    if not SAFE_ID_PATTERN.fullmatch(value):
        raise ValueError(f"invalid {kind}: {value}")
    return value
