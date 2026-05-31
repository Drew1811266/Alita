from __future__ import annotations

from agent_service.run_journal import RunJournal
from agent_service.runtime_loop import RuntimeCheckpoint
from agent_service.runtime_state import RuntimeState, RuntimeStateDelta


class RuntimeStore:
    def __init__(self, *, project_path: str, run_id: str) -> None:
        self.journal = RunJournal(project_path=project_path, run_id=run_id)

    def write_state(self, state: RuntimeState) -> None:
        self.journal.write_runtime_state(state)

    def read_state(self) -> RuntimeState | None:
        payload = self.journal.read_runtime_state()
        if payload is None:
            return None
        return RuntimeState.model_validate(payload)

    def write_delta(self, delta: RuntimeStateDelta) -> None:
        self.journal.write_runtime_delta(delta)

    def read_deltas(self) -> list[RuntimeStateDelta]:
        return [
            RuntimeStateDelta.model_validate(payload)
            for payload in self.journal.read_runtime_deltas()
        ]

    def write_checkpoint(self, checkpoint: RuntimeCheckpoint) -> None:
        self.journal.write_checkpoint(checkpoint)

    def restore_state(self, checkpoint_id: str | None = None) -> RuntimeState | None:
        checkpoint = self.read_checkpoint_record(checkpoint_id)
        if checkpoint is None:
            return None
        runtime_state = checkpoint.get("runtimeState")
        if not isinstance(runtime_state, dict) or not runtime_state:
            return None
        return RuntimeState.model_validate(runtime_state)

    def read_checkpoint_record(self, checkpoint_id: str | None = None) -> dict | None:
        return (
            self.journal.read_checkpoint(checkpoint_id)
            if checkpoint_id
            else self.journal.read_latest_checkpoint()
        )
