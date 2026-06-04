# Deep Planning LangGraph Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Alita's Deep Agent planning path a LangGraph-native, checkpointed, interruptible, resumable, bounded-revision planning runtime.

**Architecture:** Keep Phase 1's model-backed reasoning and plan-to-graph compiler, but replace the one-shot `invoke()` path with a checkpointed LangGraph runtime. LangGraph checkpoint state is the source of truth for planning; Alita's `RuntimeStore` mirrors safe checkpoint summaries for UI/run-history compatibility. Clarification and confirmation use LangGraph `interrupt()` and `Command(resume=payload)`, while invalid plans use a bounded model-backed `revise_plan` loop.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, LangGraph 1.1.10, `langgraph-checkpoint-sqlite`, pytest, React 19, TypeScript 6, Vitest, existing Tauri sidecar APIs.

---

## Source Spec

Implement from:

- `docs/superpowers/specs/2026-06-02-deep-planning-langgraph-phase-2-design.md`

LangGraph sources used by the spec:

- https://docs.langchain.com/oss/python/langgraph/overview
- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://docs.langchain.com/oss/python/langgraph/streaming
- https://docs.langchain.com/oss/python/langgraph/fault-tolerance
- https://reference.langchain.com/python/langgraph/graph/

## Current Baseline

Phase 1 code already exists:

- `python/agent_service/deep_agent_runtime_graph.py`
- `python/agent_service/deep_agent_planner.py`
- `python/agent_service/deep_agent_models.py`
- `python/agent_service/deep_agent_graph_compile.py`
- `python/agent_service/agent_runtime_engine.py`
- `python/tests/test_deep_agent_runtime_graph.py`
- `python/tests/test_agent_runtime_engine_deep_agent.py`
- `src/shared/events.ts`
- `src/app/backendEvents.ts`

Do not reintroduce legacy planner fallback. Existing tests that monkeypatch `task_planner.analyze_task` and `planner_chain.analyze_task` must keep passing.

## File Structure

Create:

- `python/agent_service/deep_agent_checkpointer.py` - factory for LangGraph checkpointers and thread config.
- `python/agent_service/deep_agent_runtime_models.py` - runtime-only Pydantic models for resume commands, checkpoint summaries, and run results.
- `python/agent_service/deep_agent_checkpoint_mirror.py` - converts LangGraph snapshots into safe Alita planning checkpoint summaries.
- `python/tests/test_deep_agent_checkpointer.py` - checkpointer dependency/factory tests.
- `python/tests/test_deep_agent_runtime_resume.py` - interrupt/resume and revision tests.
- `python/tests/test_deep_agent_runtime_streaming.py` - LangGraph stream bridge tests.

Modify:

- `python/pyproject.toml` - add official SQLite checkpointer package.
- `python/agent_service/deep_agent_runtime_graph.py` - reducer state, checkpointer config, interrupts, resume, revision, confirmation, streaming.
- `python/agent_service/deep_agent_planner.py` - ensure revision instructions are always passed through prompts.
- `python/agent_service/run_journal.py` - persist planning checkpoint summaries.
- `python/agent_service/runtime_store.py` - expose planning checkpoint read/write helpers.
- `python/agent_service/agent_runtime_engine.py` - pass run/thread ids and resume commands to deep runtime.
- `python/agent_service/agent_run_state.py` - preserve planning resume payload from `pendingChoice` if not already exposed.
- `python/agent_service/app.py` - keep public events stable and support planning resume through the existing message endpoint.
- `src/shared/events.ts` - add Phase 2 planning event types.
- `src/app/backendEvents.ts` - reduce planning stage, checkpoint, confirmation, resumed events.
- `src/app/backendEvents.test.ts` - cover new reducer behavior.
- `src/features/task/useTaskEvents.ts` - add typed helper for planning confirmation resume payload.
- `src/features/task/useTaskEvents.test.ts` - ensure pending choice serializes to `pending_choice`.
- `src/app/App.tsx` and `src/app/App.test.tsx` - route planning confirmation choices through the existing pending-choice submission path.
- `src/features/chat/ChatPanel.tsx` and tests if a new planning confirmation button group is required.

---

## Task 1: Checkpointer Dependency And Factory

**Files:**

- Modify: `python/pyproject.toml`
- Create: `python/agent_service/deep_agent_checkpointer.py`
- Create: `python/tests/test_deep_agent_checkpointer.py`

- [ ] **Step 1: Write failing tests for the checkpointer factory**

Create `python/tests/test_deep_agent_checkpointer.py`:

```python
from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from agent_service.deep_agent_checkpointer import (
    DeepPlanningCheckpointerBundle,
    create_deep_planning_checkpointer,
    deep_planning_thread_config,
    planning_checkpoint_db_path,
)


def test_thread_config_uses_langgraph_configurable_thread_id() -> None:
    assert deep_planning_thread_config("thread-task-1") == {
        "configurable": {"thread_id": "thread-task-1"}
    }


def test_planning_checkpoint_db_path_lives_under_node_runs(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.alita"

    path = planning_checkpoint_db_path(
        project_path=str(project_path),
        run_id="run-abc",
    )

    assert path == tmp_path / "node-runs" / "run-abc" / "deep-planning.sqlite"


def test_factory_can_create_memory_checkpointer_for_tests(tmp_path: Path) -> None:
    bundle = create_deep_planning_checkpointer(
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-memory",
        mode="memory",
    )

    assert isinstance(bundle, DeepPlanningCheckpointerBundle)
    assert isinstance(bundle.checkpointer, InMemorySaver)
    assert bundle.mode == "memory"
    assert bundle.degraded is False


def test_sqlite_factory_creates_database_path(tmp_path: Path) -> None:
    bundle = create_deep_planning_checkpointer(
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-sqlite",
        mode="sqlite",
    )

    assert bundle.mode == "sqlite"
    assert bundle.degraded is False
    assert bundle.path == tmp_path / "node-runs" / "run-sqlite" / "deep-planning.sqlite"
    assert bundle.path.exists()
    bundle.close()
```

- [ ] **Step 2: Run failing checkpointer tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_checkpointer.py -q
Pop-Location
```

Expected: fail because `deep_agent_checkpointer.py` does not exist and the SQLite dependency is not declared.

- [ ] **Step 3: Add the SQLite checkpointer dependency**

Modify `python/pyproject.toml` dependencies:

```toml
dependencies = [
  "fastapi",
  "langgraph",
  "langgraph-checkpoint-sqlite>=3.1.0,<4",
  "markitdown[pdf,docx,pptx,xlsx]==0.1.5",
  "pydantic",
  "python-docx",
  "uvicorn",
]
```

Then install for the active local environment:

```powershell
Push-Location python
python -m pip install -e .[test]
Pop-Location
```

Expected: package install succeeds and `python -c "import langgraph.checkpoint.sqlite"` succeeds.

- [ ] **Step 4: Implement the checkpointer factory**

Create `python/agent_service/deep_agent_checkpointer.py`:

```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.memory import InMemorySaver


CheckpointerMode = Literal["sqlite", "memory"]


@dataclass
class DeepPlanningCheckpointerBundle:
    checkpointer: Any
    mode: CheckpointerMode
    path: Path | None = None
    degraded: bool = False
    degradation_reason: str | None = None
    _connection: sqlite3.Connection | None = None

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def deep_planning_thread_config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def planning_checkpoint_db_path(*, project_path: str, run_id: str) -> Path:
    project = Path(project_path)
    return project.parent / "node-runs" / run_id / "deep-planning.sqlite"


def create_deep_planning_checkpointer(
    *,
    project_path: str,
    run_id: str,
    mode: CheckpointerMode = "sqlite",
    allow_memory_fallback: bool = False,
) -> DeepPlanningCheckpointerBundle:
    if mode == "memory":
        return DeepPlanningCheckpointerBundle(
            checkpointer=InMemorySaver(),
            mode="memory",
        )

    path = planning_checkpoint_db_path(project_path=project_path, run_id=run_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except Exception as error:
        if allow_memory_fallback:
            return DeepPlanningCheckpointerBundle(
                checkpointer=InMemorySaver(),
                mode="memory",
                degraded=True,
                degradation_reason=f"sqlite_checkpointer_unavailable:{type(error).__name__}",
            )
        raise

    connection = sqlite3.connect(path, check_same_thread=False)
    return DeepPlanningCheckpointerBundle(
        checkpointer=SqliteSaver(connection),
        mode="sqlite",
        path=path,
        _connection=connection,
    )
```

- [ ] **Step 5: Run checkpointer tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_checkpointer.py -q
Pop-Location
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add python/pyproject.toml python/agent_service/deep_agent_checkpointer.py python/tests/test_deep_agent_checkpointer.py
git commit -m "feat: add deep planning checkpointer factory"
```

---

## Task 2: Runtime Models, State Reducers, And Safe Resume Payloads

**Files:**

- Create: `python/agent_service/deep_agent_runtime_models.py`
- Modify: `python/agent_service/deep_agent_runtime_graph.py`
- Modify: `python/tests/test_deep_agent_runtime_graph.py`

- [ ] **Step 1: Add failing tests for reducer-safe event accumulation**

Append to `python/tests/test_deep_agent_runtime_graph.py`:

```python
from langgraph.checkpoint.memory import InMemorySaver


def test_deep_agent_runtime_uses_reducer_events_without_duplicates() -> None:
    model = FakeModel([_reasoning_payload(), _plan_payload(["one", "two"])])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-reducer", content="Create a two step plan."),
        project_path="D:/Project/demo.alita",
        run_id="run-reducer",
        thread_id="thread-reducer",
        model_client=model,
        checkpointer=InMemorySaver(),
    )

    event_types = [event.type for event in events]
    assert event_types.count("reasoning.decision_created") == 1
    assert event_types.count("planning.draft_created") == 1
    assert event_types.count("node_graph.created") == 1
```

Expected: fail because `run_deep_agent_runtime()` does not yet accept `run_id`, `thread_id`, or `checkpointer`.

- [ ] **Step 2: Add runtime model file**

Create `python/agent_service/deep_agent_runtime_models.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_service.schemas import AgentEvent


PlanningResumeKind = Literal[
    "clarification_answer",
    "confirmation",
]

PlanningConfirmationDecision = Literal["approve", "revise", "cancel"]


class PlanningResumeCommand(BaseModel):
    kind: PlanningResumeKind
    thread_id: str = Field(alias="threadId")
    run_id: str | None = Field(default=None, alias="runId")
    answer: str | None = None
    decision: PlanningConfirmationDecision | None = None
    revision_instructions: list[str] = Field(default_factory=list, alias="revisionInstructions")


class DeepAgentRunResult(BaseModel):
    events: list[AgentEvent]
    run_id: str = Field(alias="runId")
    thread_id: str = Field(alias="threadId")
    latest_checkpoint_id: str | None = Field(default=None, alias="latestCheckpointId")
    interrupted: bool = False
    interrupt_payload: dict[str, Any] | None = Field(default=None, alias="interruptPayload")


class PlanningCheckpointSummary(BaseModel):
    run_id: str = Field(alias="runId")
    thread_id: str = Field(alias="threadId")
    checkpoint_id: str = Field(alias="checkpointId")
    stage: str
    node: str | None = None
    revision_count: int = Field(default=0, alias="revisionCount")
    has_plan_draft: bool = Field(default=False, alias="hasPlanDraft")
    has_compiled_graph: bool = Field(default=False, alias="hasCompiledGraph")
    created_at: str = Field(alias="createdAt")
```

- [ ] **Step 3: Refactor graph state to reducer-safe collections**

Modify imports in `python/agent_service/deep_agent_runtime_graph.py`:

```python
import operator
from typing import Annotated
```

Change `DeepAgentRuntimeState` collection fields:

```python
class DeepAgentRuntimeState(TypedDict, total=False):
    message: UserMessage
    project_path: str
    run_id: str
    thread_id: str
    model_client: Any
    reasoning_decision: ReasoningDecision
    context_bundle: dict[str, Any]
    available_capabilities: set[str]
    plan_draft: PlanDraft
    thinking_status: ThinkingStatus
    plan_review: PlanReview
    revision_count: int
    revision_instructions: Annotated[list[str], operator.add]
    compiled_graph: dict[str, Any]
    graph_review: GraphReview
    confirmation: dict[str, Any]
    terminal_status: str
    events: Annotated[list[AgentEvent], operator.add]
```

- [ ] **Step 4: Stop returning accumulated events from nodes**

Change each node update from this pattern:

```python
"events": [
    *state.get("events", []),
    AgentEvent(
        type="planning.started",
        payload={"taskId": state["message"].task_id},
    ),
]
```

to this pattern:

```python
"events": [
    AgentEvent(
        type="planning.started",
        payload={"taskId": state["message"].task_id},
    ),
]
```

Apply to:

- `reasoning_gate`
- `deep_plan`
- `review_plan_node`
- `compile_agent_plan_graph_node`
- `review_graph_node`
- `present_plan`
- `clarify_required`
- `simple_reasoning_final`

Do not remove event ordering tests; update expected order only if new Phase 2 events are added in later tasks.

- [ ] **Step 5: Run reducer-focused tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_runtime_graph.py::test_deep_agent_runtime_uses_reducer_events_without_duplicates tests/test_deep_agent_runtime_graph.py::test_deep_agent_runtime_calls_model_and_emits_graph_from_plan -q
Pop-Location
```

Expected: both pass.

- [ ] **Step 6: Commit**

```powershell
git add python/agent_service/deep_agent_runtime_models.py python/agent_service/deep_agent_runtime_graph.py python/tests/test_deep_agent_runtime_graph.py
git commit -m "refactor: make deep planning state reducer-safe"
```

---

## Task 3: Checkpointed Graph Invocation And RuntimeStore Mirror

**Files:**

- Create: `python/agent_service/deep_agent_checkpoint_mirror.py`
- Modify: `python/agent_service/deep_agent_runtime_graph.py`
- Modify: `python/agent_service/run_journal.py`
- Modify: `python/agent_service/runtime_store.py`
- Create: `python/tests/test_deep_agent_runtime_resume.py`
- Modify: `python/tests/test_runtime_store.py`

- [ ] **Step 1: Write failing tests for checkpoint history and mirror storage**

Create `python/tests/test_deep_agent_runtime_resume.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from agent_service.deep_agent_runtime_graph import (
    build_deep_agent_runtime_graph,
    run_deep_agent_runtime,
)
from agent_service.deep_agent_checkpointer import deep_planning_thread_config
from agent_service.runtime_store import RuntimeStore
from agent_service.schemas import UserMessage
from tests.test_deep_agent_runtime_graph import FakeModel, _plan_payload, _reasoning_payload


def test_checkpointed_deep_agent_runtime_has_state_history(tmp_path: Path) -> None:
    checkpointer = InMemorySaver()
    model = FakeModel([_reasoning_payload(), _plan_payload(["plan", "write"])])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-history", content="Create a report."),
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-history",
        thread_id="thread-history",
        model_client=model,
        checkpointer=checkpointer,
    )

    assert events[-1].type == "node_graph.created"
    app = build_deep_agent_runtime_graph(checkpointer=checkpointer)
    history = list(app.get_state_history(deep_planning_thread_config("thread-history")))
    assert len(history) >= 4
    assert any("plan_draft" in snapshot.values for snapshot in history)


def test_runtime_store_persists_safe_planning_checkpoint_summary(tmp_path: Path) -> None:
    store = RuntimeStore(project_path=str(tmp_path / "demo.alita"), run_id="run-store")

    store.write_planning_checkpoint_summary(
        {
            "runId": "run-store",
            "threadId": "thread-store",
            "checkpointId": "checkpoint-1",
            "stage": "deep_plan",
            "node": "deep_plan",
            "revisionCount": 0,
            "hasPlanDraft": True,
            "hasCompiledGraph": False,
            "createdAt": "2026-06-02T00:00:00+00:00",
            "rawReasoning": "must not be stored",
        }
    )

    summaries = store.read_planning_checkpoint_summaries()
    assert summaries == [
        {
            "runId": "run-store",
            "threadId": "thread-store",
            "checkpointId": "checkpoint-1",
            "stage": "deep_plan",
            "node": "deep_plan",
            "revisionCount": 0,
            "hasPlanDraft": True,
            "hasCompiledGraph": False,
            "createdAt": "2026-06-02T00:00:00+00:00",
        }
    ]
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_runtime_resume.py tests/test_runtime_store.py -q
Pop-Location
```

Expected: fail because checkpoint-aware runtime parameters and planning summary persistence do not exist.

- [ ] **Step 3: Add planning checkpoint persistence to RunJournal**

Modify `python/agent_service/run_journal.py`:

```python
    def write_planning_checkpoint_summary(self, payload: dict[str, Any]) -> None:
        summaries = self.read_planning_checkpoint_summaries()
        sanitized = {
            "runId": payload["runId"],
            "threadId": payload["threadId"],
            "checkpointId": payload["checkpointId"],
            "stage": payload["stage"],
            "node": payload.get("node"),
            "revisionCount": int(payload.get("revisionCount") or 0),
            "hasPlanDraft": bool(payload.get("hasPlanDraft")),
            "hasCompiledGraph": bool(payload.get("hasCompiledGraph")),
            "createdAt": payload["createdAt"],
        }
        summaries.append(sanitized)
        self._write_json(
            self.base_dir / "planning_checkpoints.json",
            {"checkpoints": summaries},
        )

    def read_planning_checkpoint_summaries(self) -> list[dict[str, Any]]:
        path = self.base_dir / "planning_checkpoints.json"
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        return list(payload.get("checkpoints", []))
```

Also update `read_nodes()` exclusion:

```python
if path.name not in {
    "run.json",
    "audit.json",
    "checkpoints.json",
    "runtime_state.json",
    "runtime_deltas.json",
    "planning_checkpoints.json",
}
```

- [ ] **Step 4: Add RuntimeStore helpers**

Modify `python/agent_service/runtime_store.py`:

```python
    def write_planning_checkpoint_summary(self, payload: dict) -> None:
        self.journal.write_planning_checkpoint_summary(payload)

    def read_planning_checkpoint_summaries(self) -> list[dict]:
        return self.journal.read_planning_checkpoint_summaries()

    def read_latest_planning_checkpoint_summary(self) -> dict | None:
        summaries = self.read_planning_checkpoint_summaries()
        return summaries[-1] if summaries else None
```

- [ ] **Step 5: Add checkpoint mirror helpers**

Create `python/agent_service/deep_agent_checkpoint_mirror.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_service.deep_agent_runtime_models import PlanningCheckpointSummary
from agent_service.schemas import AgentEvent


def planning_checkpoint_summary_from_state(
    *,
    values: dict[str, Any],
    checkpoint_id: str,
    node: str | None,
) -> PlanningCheckpointSummary:
    return PlanningCheckpointSummary(
        runId=str(values.get("run_id") or ""),
        threadId=str(values.get("thread_id") or ""),
        checkpointId=checkpoint_id,
        stage=_stage_from_values(values, node),
        node=node,
        revisionCount=int(values.get("revision_count") or 0),
        hasPlanDraft=bool(values.get("plan_draft")),
        hasCompiledGraph=bool(values.get("compiled_graph")),
        createdAt=datetime.now(timezone.utc).isoformat(),
    )


def planning_checkpoint_recorded_event(
    summary: PlanningCheckpointSummary,
) -> AgentEvent:
    return AgentEvent(
        type="planning.checkpoint_recorded",
        payload={"checkpoint": summary.model_dump(by_alias=True)},
    )


def _stage_from_values(values: dict[str, Any], node: str | None) -> str:
    terminal_status = values.get("terminal_status")
    if isinstance(terminal_status, str) and terminal_status:
        return terminal_status
    if node:
        return node
    return "planning"
```

- [ ] **Step 6: Compile and invoke with checkpointer config**

Modify `python/agent_service/deep_agent_runtime_graph.py` imports:

```python
from langgraph.types import Command

from agent_service.deep_agent_checkpointer import (
    create_deep_planning_checkpointer,
    deep_planning_thread_config,
)
```

Change build and run signatures:

```python
def run_deep_agent_runtime(
    message: UserMessage,
    *,
    project_path: str,
    run_id: str | None = None,
    thread_id: str | None = None,
    model_client: Any | None = None,
    checkpointer: Any | None = None,
) -> list[AgentEvent]:
    effective_run_id = run_id or message.task_id
    effective_thread_id = thread_id or f"thread-{message.task_id}"
    bundle = None
    if checkpointer is None:
        bundle = create_deep_planning_checkpointer(
            project_path=project_path,
            run_id=effective_run_id,
            mode="sqlite",
            allow_memory_fallback=False,
        )
        checkpointer = bundle.checkpointer

    try:
        app = build_deep_agent_runtime_graph(checkpointer=checkpointer)
        result = app.invoke(
            {
                "message": message,
                "project_path": project_path,
                "run_id": effective_run_id,
                "thread_id": effective_thread_id,
                "model_client": model_client or LlamaCppModelClient(),
                "revision_count": 0,
                "revision_instructions": [],
                "events": [],
            },
            config=deep_planning_thread_config(effective_thread_id),
            version="v2",
        )
        output = result.value if hasattr(result, "value") else result
        return list(output.get("events") or [])
    finally:
        if bundle is not None:
            bundle.close()


def build_deep_agent_runtime_graph(*, checkpointer: Any | None = None):
    graph = StateGraph(DeepAgentRuntimeState)
    graph.add_node("reasoning_gate", reasoning_gate)
    graph.add_node("build_context", build_context)
    graph.add_node("deep_plan", deep_plan)
    graph.add_node("review_plan", review_plan_node)
    graph.add_node("compile_agent_plan_graph", compile_agent_plan_graph_node)
    graph.add_node("review_graph", review_graph_node)
    graph.add_node("present_plan", present_plan)
    graph.add_node("clarify_required", clarify_required)
    graph.add_node("simple_reasoning_final", simple_reasoning_final)
    graph.add_node("deep_agent_failed", deep_agent_failed)
    graph.set_entry_point("reasoning_gate")
    graph.add_edge("build_context", "deep_plan")
    graph.add_edge("compile_agent_plan_graph", "review_graph")
    graph.add_edge("present_plan", END)
    graph.add_edge("clarify_required", END)
    graph.add_edge("simple_reasoning_final", END)
    graph.add_edge("deep_agent_failed", END)
    return graph.compile(checkpointer=checkpointer)
```

- [ ] **Step 7: Run checkpoint tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_runtime_resume.py tests/test_runtime_store.py tests/test_deep_agent_runtime_graph.py -q
Pop-Location
```

Expected: tests pass.

- [ ] **Step 8: Commit**

```powershell
git add python/agent_service/deep_agent_checkpoint_mirror.py python/agent_service/deep_agent_runtime_graph.py python/agent_service/run_journal.py python/agent_service/runtime_store.py python/tests/test_deep_agent_runtime_resume.py python/tests/test_runtime_store.py
git commit -m "feat: checkpoint deep planning runtime"
```

---

## Task 4: Clarification Interrupt And Resume

**Files:**

- Modify: `python/agent_service/deep_agent_runtime_graph.py`
- Modify: `python/agent_service/deep_agent_runtime_models.py`
- Modify: `python/agent_service/agent_run_state.py`
- Modify: `python/agent_service/agent_runtime_engine.py`
- Modify: `python/tests/test_deep_agent_runtime_resume.py`
- Modify: `python/tests/test_agent_runtime_engine_deep_agent.py`

- [ ] **Step 1: Add failing clarification interrupt/resume tests**

Append to `python/tests/test_deep_agent_runtime_resume.py`:

```python
from agent_service.deep_agent_runtime_models import PlanningResumeCommand


def test_clarification_interrupts_before_graph_creation(tmp_path: Path) -> None:
    checkpointer = InMemorySaver()
    payload = _plan_payload(["clarify"])
    payload["missing_information"] = ["target audience"]
    model = FakeModel([_reasoning_payload(), payload])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-clarify-interrupt", content="Make a report."),
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-clarify-interrupt",
        thread_id="thread-clarify-interrupt",
        model_client=model,
        checkpointer=checkpointer,
    )

    assert "planning.clarification_required" in [event.type for event in events]
    assert "planning.interrupted" in [event.type for event in events]
    assert all(event.type != "node_graph.created" for event in events)


def test_clarification_resume_continues_same_thread(tmp_path: Path) -> None:
    checkpointer = InMemorySaver()
    first_payload = _plan_payload(["clarify"])
    first_payload["missing_information"] = ["target audience"]
    model = FakeModel([
        _reasoning_payload(),
        first_payload,
        _plan_payload(["understand", "write"]),
    ])

    first_events = run_deep_agent_runtime(
        UserMessage(task_id="task-clarify-resume", content="Make a report."),
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-clarify-resume",
        thread_id="thread-clarify-resume",
        model_client=model,
        checkpointer=checkpointer,
    )
    assert "planning.interrupted" in [event.type for event in first_events]

    resumed_events = run_deep_agent_runtime(
        UserMessage(task_id="task-clarify-resume", content="Make a report."),
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-clarify-resume",
        thread_id="thread-clarify-resume",
        model_client=model,
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="clarification_answer",
            threadId="thread-clarify-resume",
            runId="run-clarify-resume",
            answer="The report is for executives.",
        ),
    )

    assert "planning.resumed" in [event.type for event in resumed_events]
    assert resumed_events[-1].type == "node_graph.created"
    assert model.calls == 3
```

- [ ] **Step 2: Run failing clarification tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_runtime_resume.py::test_clarification_interrupts_before_graph_creation tests/test_deep_agent_runtime_resume.py::test_clarification_resume_continues_same_thread -q
Pop-Location
```

Expected: fail because `resume_command` and `interrupt()` are not implemented.

- [ ] **Step 3: Add resume command parameter to runtime invocation**

Modify `run_deep_agent_runtime()`:

```python
from langgraph.types import Command
from agent_service.deep_agent_runtime_models import PlanningResumeCommand


def run_deep_agent_runtime(
    message: UserMessage,
    *,
    project_path: str,
    run_id: str | None = None,
    thread_id: str | None = None,
    model_client: Any | None = None,
    checkpointer: Any | None = None,
    resume_command: PlanningResumeCommand | None = None,
) -> list[AgentEvent]:
    effective_run_id = run_id or message.task_id
    effective_thread_id = thread_id or f"thread-{message.task_id}"
    input_payload: dict[str, Any] | Command
    if resume_command is not None:
        input_payload = Command(resume=resume_command.model_dump(by_alias=True))
    else:
        input_payload = {
            "message": message,
            "project_path": project_path,
            "run_id": effective_run_id,
            "thread_id": effective_thread_id,
            "model_client": model_client or LlamaCppModelClient(),
            "revision_count": 0,
            "revision_instructions": [],
            "events": [],
        }
    result = app.invoke(
        input_payload,
        config=deep_planning_thread_config(effective_thread_id),
        version="v2",
    )
```

- [ ] **Step 4: Implement `clarify_required` as a LangGraph interrupt**

Modify imports:

```python
from langgraph.types import Command, interrupt
```

Modify `clarify_required()`:

```python
def clarify_required(state: DeepAgentRuntimeState) -> dict[str, Any]:
    review = state.get("plan_review")
    decision = state.get("reasoning_decision")
    prompt = "请补充任务目标或输入信息后我再生成执行图。"
    missing_inputs: list[str] = []
    if review is not None:
        missing_inputs = list(review.missing_inputs)
        if review.suggested_clarifying_question:
            prompt = review.suggested_clarifying_question
    elif decision is not None and decision.next_action == "clarification":
        prompt = decision.why_this_path

    payload = {
        "kind": "planning.clarification",
        "taskId": state["message"].task_id,
        "runId": state["run_id"],
        "threadId": state["thread_id"],
        "question": prompt,
        "missingInputs": missing_inputs,
    }
    resume_payload = interrupt(payload)
    answer = str(
        resume_payload.get("answer")
        if isinstance(resume_payload, dict)
        else resume_payload
    ).strip()

    return {
        "revision_instructions": [
            f"Use this user clarification while revising the plan: {answer}"
        ],
        "events": [
            AgentEvent(
                type="planning.interrupted",
                payload=payload,
            ),
            AgentEvent(
                type="planning.resumed",
                payload={
                    "taskId": state["message"].task_id,
                    "runId": state["run_id"],
                    "threadId": state["thread_id"],
                    "kind": "planning.clarification",
                },
            ),
        ],
    }
```

Keep `planning.clarification_required` emitted by the node that routes to `clarify_required`, so the UI receives the prompt before the interrupt.

- [ ] **Step 5: Add `resume_after_clarification` node**

Add node:

```python
def resume_after_clarification(state: DeepAgentRuntimeState) -> dict[str, Any]:
    return {
        "plan_draft": None,
        "plan_review": None,
        "compiled_graph": None,
        "graph_review": None,
        "events": [
            AgentEvent(
                type="planning.stage_changed",
                payload={
                    "taskId": state["message"].task_id,
                    "stage": "build_context",
                    "label": "构建上下文",
                },
            )
        ],
    }
```

Wire graph:

```python
graph.add_node("resume_after_clarification", resume_after_clarification)
graph.add_edge("clarify_required", "resume_after_clarification")
graph.add_edge("resume_after_clarification", "build_context")
```

- [ ] **Step 6: Parse planning resume payload from `AgentRunState.pending_choice`**

`AgentRunState` already stores `pending_choice`. Keep that field and add this helper in `python/agent_service/agent_runtime_engine.py`:

```python
def planning_resume_command_from_pending_choice(
    pending_choice: dict[str, Any] | None,
) -> PlanningResumeCommand | None:
    if not pending_choice:
        return None
    kind = str(pending_choice.get("kind") or "")
    if kind == "planning.clarification":
        return PlanningResumeCommand.model_validate(
            {
                "kind": "clarification_answer",
                "threadId": pending_choice["threadId"],
                "runId": pending_choice.get("runId"),
                "answer": pending_choice.get("answer", ""),
            }
        )
    return None
```

- [ ] **Step 7: Pass resume command through AgentRuntimeEngine**

Modify `python/agent_service/agent_runtime_engine.py`:

```python
from agent_service.deep_agent_runtime_models import PlanningResumeCommand


def _planning_resume_command_from_pending_choice(
    pending_choice: dict[str, Any] | None,
) -> PlanningResumeCommand | None:
    if not pending_choice:
        return None
    kind = str(pending_choice.get("kind") or "")
    if kind == "planning.clarification":
        return PlanningResumeCommand.model_validate(
            {
                "kind": "clarification_answer",
                "threadId": pending_choice["threadId"],
                "runId": pending_choice.get("runId"),
                "answer": pending_choice.get("answer", ""),
            }
        )
    return None
```

When calling `self.deep_runtime_runner`, pass the planning resume command:

```python
deep_events = self.deep_runtime_runner(
    run_state.message,
    project_path=run_state.project_path or "project.alita",
    run_id=run_state.run_id,
    thread_id=run_state.thread_id,
    model_client=model_client,
    resume_command=_planning_resume_command_from_pending_choice(run_state.pending_choice),
)
```

Use the actual `AgentRunState` thread field if it exists; otherwise derive `thread_id=f"thread-{run_state.message.task_id}"`.

- [ ] **Step 8: Run clarification tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_runtime_resume.py tests/test_agent_runtime_engine_deep_agent.py -q
Pop-Location
```

Expected: pass.

- [ ] **Step 9: Commit**

```powershell
git add python/agent_service/deep_agent_runtime_graph.py python/agent_service/deep_agent_runtime_models.py python/agent_service/agent_run_state.py python/agent_service/agent_runtime_engine.py python/tests/test_deep_agent_runtime_resume.py python/tests/test_agent_runtime_engine_deep_agent.py
git commit -m "feat: add deep planning clarification resume"
```

---

## Task 5: Bounded Model-Backed Plan Revision

**Files:**

- Modify: `python/agent_service/deep_agent_runtime_graph.py`
- Modify: `python/agent_service/deep_agent_planner.py`
- Modify: `python/tests/test_deep_agent_planner.py`
- Modify: `python/tests/test_deep_agent_runtime_resume.py`

- [ ] **Step 1: Add failing planner prompt test for revision instructions**

Append to `python/tests/test_deep_agent_planner.py`:

```python
def test_deep_planning_prompt_includes_revision_instructions() -> None:
    from agent_service.deep_agent_planner import _planning_prompt

    prompt = _planning_prompt(
        UserMessage(task_id="task-revise-prompt", content="Create a report."),
        context_bundle={"available_tools": []},
        revision_instructions=[
            "Add verification criteria for every step.",
            "Use only model.reasoning capability.",
        ],
    )

    assert "Add verification criteria for every step." in prompt
    assert "Use only model.reasoning capability." in prompt
```

Expected: pass if Phase 1 already includes revision instructions; keep this as a regression test.

- [ ] **Step 2: Add failing bounded revision runtime tests**

Append to `python/tests/test_deep_agent_runtime_resume.py`:

```python
def test_invalid_plan_revises_once_and_then_creates_graph(tmp_path: Path) -> None:
    invalid = _plan_payload(["draft"])
    invalid["steps"][0]["verification_criteria"] = []
    revised = _plan_payload(["draft"])
    model = FakeModel([_reasoning_payload(), invalid, revised])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-revise-success", content="Create a report."),
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-revise-success",
        thread_id="thread-revise-success",
        model_client=model,
        checkpointer=InMemorySaver(),
        revision_budget=2,
    )

    event_types = [event.type for event in events]
    assert "planning.revision_requested" in event_types
    assert "planning.revision_completed" in event_types
    assert events[-1].type == "node_graph.created"
    assert model.calls == 3


def test_revision_budget_exhaustion_fails_without_graph(tmp_path: Path) -> None:
    invalid_a = _plan_payload(["draft"])
    invalid_a["steps"][0]["verification_criteria"] = []
    invalid_b = _plan_payload(["draft"])
    invalid_b["steps"][0]["verification_criteria"] = []
    model = FakeModel([_reasoning_payload(), invalid_a, invalid_b])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-revise-fail", content="Create a report."),
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-revise-fail",
        thread_id="thread-revise-fail",
        model_client=model,
        checkpointer=InMemorySaver(),
        revision_budget=1,
    )

    event_types = [event.type for event in events]
    assert "planning.revision_exhausted" in event_types
    assert events[-1].type == "planning.failed"
    assert all(event.type != "node_graph.created" for event in events)
```

- [ ] **Step 3: Add revision budget to runtime state and invocation**

Modify `DeepAgentRuntimeState`:

```python
revision_budget: int
```

Modify `run_deep_agent_runtime()`:

```python
def run_deep_agent_runtime(
    message: UserMessage,
    *,
    project_path: str,
    run_id: str | None = None,
    thread_id: str | None = None,
    model_client: Any | None = None,
    checkpointer: Any | None = None,
    resume_command: PlanningResumeCommand | None = None,
    revision_budget: int = 2,
) -> list[AgentEvent]:
    input_payload = {
        "message": message,
        "project_path": project_path,
        "run_id": run_id or message.task_id,
        "thread_id": thread_id or f"thread-{message.task_id}",
        "model_client": model_client or LlamaCppModelClient(),
        "revision_count": 0,
        "revision_budget": revision_budget,
        "revision_instructions": [],
        "events": [],
    }
```

- [ ] **Step 4: Implement `revise_plan` node**

Add:

```python
def revise_plan(
    state: DeepAgentRuntimeState,
) -> Command[Literal["review_plan", "deep_agent_failed"]]:
    revision_count = int(state.get("revision_count") or 0) + 1
    instructions = list(state.get("revision_instructions") or [])
    if state.get("plan_review") is not None:
        instructions.extend(state["plan_review"].revision_instructions)
    if state.get("graph_review") is not None:
        instructions.extend(state["graph_review"].findings)

    events = [
        AgentEvent(
            type="planning.revision_started",
            payload={
                "taskId": state["message"].task_id,
                "revisionCount": revision_count,
                "instructions": instructions,
            },
        )
    ]

    try:
        result = DeepPlanningEngine(model_client=state["model_client"]).plan(
            state["message"],
            context_bundle=state.get("context_bundle") or {},
            revision_instructions=instructions,
        )
    except DeepPlanningError as error:
        return Command(
            update={"events": [*events, _planning_failed_event(error)]},
            goto="deep_agent_failed",
        )

    return Command(
        update={
            "revision_count": revision_count,
            "plan_draft": result.plan_draft,
            "thinking_status": result.thinking_status,
            "events": [
                *events,
                AgentEvent(
                    type="planning.revision_completed",
                    payload={
                        "taskId": state["message"].task_id,
                        "revisionCount": revision_count,
                        "planDraft": result.plan_draft.model_dump(),
                    },
                ),
            ],
        },
        goto="review_plan",
    )
```

- [ ] **Step 5: Route invalid reviews through revision budget**

Modify `review_plan_node()` invalid branch:

```python
    if review.status == "invalid":
        revision_count = int(state.get("revision_count") or 0)
        revision_budget = int(state.get("revision_budget") or 2)
        if revision_count < revision_budget:
            return Command(
                update={
                    "plan_review": review,
                    "revision_instructions": list(review.revision_instructions),
                    "events": [
                        *events,
                        AgentEvent(
                            type="planning.revision_requested",
                            payload={
                                "taskId": state["message"].task_id,
                                "revisionCount": revision_count + 1,
                                "reason": "plan_review_invalid",
                                "instructions": list(review.revision_instructions),
                            },
                        ),
                    ],
                },
                goto="revise_plan",
            )

        return Command(
            update={
                "plan_review": review,
                "events": [
                    *events,
                    AgentEvent(
                        type="planning.revision_exhausted",
                        payload={
                            "taskId": state["message"].task_id,
                            "reason": "plan_review_invalid",
                        },
                    ),
                    AgentEvent(
                        type="planning.failed",
                        payload={"reason": "plan_review_invalid", "review": review.model_dump()},
                    ),
                ],
            },
            goto="deep_agent_failed",
        )
```

Wire graph:

```python
graph.add_node("revise_plan", revise_plan)
```

- [ ] **Step 6: Route graph review failures through revision**

Modify `review_graph_node()` invalid branch with the same budget logic, using:

```python
"reason": "graph_review_invalid"
```

and `revision_instructions` from `review.findings`.

- [ ] **Step 7: Run revision tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_planner.py tests/test_deep_agent_runtime_resume.py -q
Pop-Location
```

Expected: pass.

- [ ] **Step 8: Commit**

```powershell
git add python/agent_service/deep_agent_runtime_graph.py python/agent_service/deep_agent_planner.py python/tests/test_deep_agent_planner.py python/tests/test_deep_agent_runtime_resume.py
git commit -m "feat: add bounded deep plan revision"
```

---

## Task 6: Plan Confirmation Interrupt And Resume

**Files:**

- Modify: `python/agent_service/deep_agent_runtime_graph.py`
- Modify: `python/agent_service/deep_agent_runtime_models.py`
- Modify: `python/agent_service/agent_runtime_engine.py`
- Modify: `python/tests/test_deep_agent_runtime_resume.py`
- Modify: `python/tests/test_agent_runtime_engine_deep_agent.py`

- [ ] **Step 1: Add failing confirmation tests**

Append to `python/tests/test_deep_agent_runtime_resume.py`:

```python
def test_graph_review_approval_interrupts_for_confirmation(tmp_path: Path) -> None:
    checkpointer = InMemorySaver()
    model = FakeModel([_reasoning_payload(), _plan_payload(["draft"])])

    events = run_deep_agent_runtime(
        UserMessage(task_id="task-confirm", content="Create a report."),
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-confirm",
        thread_id="thread-confirm",
        model_client=model,
        checkpointer=checkpointer,
        require_confirmation=True,
    )

    event_types = [event.type for event in events]
    assert events[-2].type == "node_graph.created"
    assert events[-1].type == "planning.confirmation_required"
    assert "planning.confirmed" not in event_types


def test_confirmation_resume_approve_marks_plan_confirmed(tmp_path: Path) -> None:
    checkpointer = InMemorySaver()
    model = FakeModel([_reasoning_payload(), _plan_payload(["draft"])])

    first_events = run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-approve", content="Create a report."),
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-confirm-approve",
        thread_id="thread-confirm-approve",
        model_client=model,
        checkpointer=checkpointer,
        require_confirmation=True,
    )
    assert first_events[-1].type == "planning.confirmation_required"

    resumed = run_deep_agent_runtime(
        UserMessage(task_id="task-confirm-approve", content="Create a report."),
        project_path=str(tmp_path / "demo.alita"),
        run_id="run-confirm-approve",
        thread_id="thread-confirm-approve",
        model_client=model,
        checkpointer=checkpointer,
        resume_command=PlanningResumeCommand(
            kind="confirmation",
            threadId="thread-confirm-approve",
            runId="run-confirm-approve",
            decision="approve",
        ),
        require_confirmation=True,
    )

    assert resumed[-1].type == "planning.confirmed"
```

- [ ] **Step 2: Run failing confirmation tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_runtime_resume.py::test_graph_review_approval_interrupts_for_confirmation tests/test_deep_agent_runtime_resume.py::test_confirmation_resume_approve_marks_plan_confirmed -q
Pop-Location
```

Expected: fail because confirmation interrupt is not implemented.

- [ ] **Step 3: Add confirmation events to `present_plan`**

Modify `present_plan()`:

```python
def present_plan(state: DeepAgentRuntimeState) -> Command[Literal["confirm_plan"]]:
    graph = state["compiled_graph"]
    return Command(
        update={
            "events": [
                AgentEvent(
                    type="node_graph.created",
                    payload={"graph": graph},
                ),
                AgentEvent(
                    type="planning.confirmation_required",
                    payload={
                        "taskId": state["message"].task_id,
                        "runId": state["run_id"],
                        "threadId": state["thread_id"],
                        "graphId": graph["graphId"],
                        "summary": "请确认是否执行这个由 Agent 深度规划生成的计划图。",
                        "pendingChoice": {
                            "kind": "planning.confirmation",
                            "runId": state["run_id"],
                            "threadId": state["thread_id"],
                            "graphId": graph["graphId"],
                        },
                        "choices": [
                            {"id": "approve", "label": "确认执行"},
                            {"id": "revise", "label": "要求修订"},
                            {"id": "cancel", "label": "取消"},
                        ],
                    },
                ),
            ]
        },
        goto="confirm_plan",
    )
```

Change graph edge:

```python
graph.add_node("confirm_plan", confirm_plan)
graph.add_edge("present_plan", "confirm_plan")
```

- [ ] **Step 4: Implement `confirm_plan` interrupt**

Add:

```python
def confirm_plan(
    state: DeepAgentRuntimeState,
) -> Command[Literal["planning_confirmed", "revise_plan", "planning_cancelled"]]:
    graph = state["compiled_graph"]
    payload = {
        "kind": "planning.confirmation",
        "taskId": state["message"].task_id,
        "runId": state["run_id"],
        "threadId": state["thread_id"],
        "graphId": graph["graphId"],
    }
    resume_payload = interrupt(payload)
    decision = (
        resume_payload.get("decision")
        if isinstance(resume_payload, dict)
        else "approve"
    )

    if decision == "revise":
        instructions = []
        if isinstance(resume_payload, dict):
            instructions = [
                str(value)
                for value in resume_payload.get("revisionInstructions", [])
            ]
        return Command(
            update={
                "revision_instructions": instructions or ["Revise the plan per user request."],
                "events": [
                    AgentEvent(
                        type="planning.resumed",
                        payload={**payload, "decision": "revise"},
                    )
                ],
            },
            goto="revise_plan",
        )

    if decision == "cancel":
        return Command(
            update={
                "terminal_status": "cancelled",
                "events": [
                    AgentEvent(
                        type="planning.cancelled",
                        payload=payload,
                    )
                ],
            },
            goto="planning_cancelled",
        )

    return Command(
        update={
            "confirmation": {"decision": "approve"},
            "terminal_status": "planning_confirmed",
            "events": [
                AgentEvent(
                    type="planning.confirmed",
                    payload=payload,
                )
            ],
        },
        goto="planning_confirmed",
    )
```

Add terminal nodes:

```python
def planning_confirmed(state: DeepAgentRuntimeState) -> dict[str, Any]:
    del state
    return {}


def planning_cancelled(state: DeepAgentRuntimeState) -> dict[str, Any]:
    del state
    return {}
```

- [ ] **Step 5: Parse confirmation resume payload**

Update `_planning_resume_command_from_pending_choice()` in `agent_runtime_engine.py`:

```python
    if kind == "planning.confirmation":
        return PlanningResumeCommand.model_validate(
            {
                "kind": "confirmation",
                "threadId": pending_choice["threadId"],
                "runId": pending_choice.get("runId"),
                "decision": pending_choice.get("decision", "approve"),
                "revisionInstructions": pending_choice.get("revisionInstructions", []),
            }
        )
```

- [ ] **Step 6: Run confirmation tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_runtime_resume.py tests/test_agent_runtime_engine_deep_agent.py -q
Pop-Location
```

Expected: pass.

- [ ] **Step 7: Commit**

```powershell
git add python/agent_service/deep_agent_runtime_graph.py python/agent_service/deep_agent_runtime_models.py python/agent_service/agent_runtime_engine.py python/tests/test_deep_agent_runtime_resume.py python/tests/test_agent_runtime_engine_deep_agent.py
git commit -m "feat: require confirmation for deep planning graphs"
```

---

## Task 7: LangGraph Streaming Event Bridge

**Files:**

- Modify: `python/agent_service/deep_agent_runtime_graph.py`
- Modify: `python/agent_service/agent_runtime_engine.py`
- Modify: `python/agent_service/app.py`
- Create: `python/tests/test_deep_agent_runtime_streaming.py`
- Modify: `python/tests/test_app.py`

- [ ] **Step 1: Add failing streaming parity test**

Create `python/tests/test_deep_agent_runtime_streaming.py`:

```python
from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from agent_service.deep_agent_runtime_graph import (
    run_deep_agent_runtime,
    stream_deep_agent_runtime_events,
)
from agent_service.schemas import UserMessage
from tests.test_deep_agent_runtime_graph import FakeModel, _plan_payload, _reasoning_payload


def test_deep_agent_streaming_matches_non_stream_event_order(tmp_path) -> None:
    non_stream_model = FakeModel([_reasoning_payload(), _plan_payload(["draft"])])
    stream_model = FakeModel([_reasoning_payload(), _plan_payload(["draft"])])

    kwargs = {
        "message": UserMessage(task_id="task-stream", content="Create a report."),
        "project_path": str(tmp_path / "demo.alita"),
        "run_id": "run-stream",
        "thread_id": "thread-stream",
        "checkpointer": InMemorySaver(),
        "require_confirmation": False,
    }
    non_stream_events = run_deep_agent_runtime(
        model_client=non_stream_model,
        **kwargs,
    )
    stream_events = list(
        stream_deep_agent_runtime_events(
            model_client=stream_model,
            **{
                **kwargs,
                "thread_id": "thread-stream-2",
                "run_id": "run-stream-2",
                "checkpointer": InMemorySaver(),
            },
        )
    )

    assert [event.type for event in stream_events] == [
        event.type for event in non_stream_events
    ]
```

- [ ] **Step 2: Run failing streaming test**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_runtime_streaming.py -q
Pop-Location
```

Expected: fail because `stream_deep_agent_runtime_events()` does not exist.

- [ ] **Step 3: Implement streaming event bridge**

Add to `python/agent_service/deep_agent_runtime_graph.py`:

```python
def stream_deep_agent_runtime_events(
    message: UserMessage,
    *,
    project_path: str,
    run_id: str | None = None,
    thread_id: str | None = None,
    model_client: Any | None = None,
    checkpointer: Any | None = None,
    resume_command: PlanningResumeCommand | None = None,
    revision_budget: int = 2,
    require_confirmation: bool = True,
):
    effective_run_id = run_id or message.task_id
    effective_thread_id = thread_id or f"thread-{message.task_id}"
    bundle = None
    if checkpointer is None:
        bundle = create_deep_planning_checkpointer(
            project_path=project_path,
            run_id=effective_run_id,
            mode="sqlite",
            allow_memory_fallback=False,
        )
        checkpointer = bundle.checkpointer

    try:
        app = build_deep_agent_runtime_graph(checkpointer=checkpointer)
        input_payload = _deep_runtime_input_or_resume_command(
            message=message,
            project_path=project_path,
            run_id=effective_run_id,
            thread_id=effective_thread_id,
            model_client=model_client or LlamaCppModelClient(),
            resume_command=resume_command,
            revision_budget=revision_budget,
            require_confirmation=require_confirmation,
        )
        seen_event_keys: set[tuple[str, str]] = set()
        for chunk in app.stream(
            input_payload,
            config=deep_planning_thread_config(effective_thread_id),
            stream_mode="updates",
            version="v2",
        ):
            data = chunk.get("data") if isinstance(chunk, dict) and "data" in chunk else chunk
            if not isinstance(data, dict):
                continue
            for update in data.values():
                if not isinstance(update, dict):
                    continue
                for event in update.get("events") or []:
                    parsed = event if isinstance(event, AgentEvent) else AgentEvent.model_validate(event)
                    key = (parsed.type, parsed.model_dump_json())
                    if key in seen_event_keys:
                        continue
                    seen_event_keys.add(key)
                    yield parsed
    finally:
        if bundle is not None:
            bundle.close()
```

Extract shared input building into helper:

```python
def _deep_runtime_input_or_resume_command(
    *,
    message: UserMessage,
    project_path: str,
    run_id: str,
    thread_id: str,
    model_client: Any,
    resume_command: PlanningResumeCommand | None,
    revision_budget: int,
    require_confirmation: bool,
) -> dict[str, Any] | Command:
    if resume_command is not None:
        return Command(resume=resume_command.model_dump(by_alias=True))
    return {
        "message": message,
        "project_path": project_path,
        "run_id": run_id,
        "thread_id": thread_id,
        "model_client": model_client,
        "revision_count": 0,
        "revision_budget": revision_budget,
        "require_confirmation": require_confirmation,
        "revision_instructions": [],
        "events": [],
    }
```

Use it from both stream and non-stream paths.

- [ ] **Step 4: Route AgentRuntimeEngine streaming through deep runtime stream**

Modify `AgentRuntimeEngine.__init__`:

```python
from agent_service.deep_agent_runtime_graph import (
    run_deep_agent_runtime,
    stream_deep_agent_runtime_events,
)

DeepRuntimeStreamRunner = Callable[..., Any]

def __init__(
    self,
    *,
    route_runner: RouteRunner = run_agent_from_state,
    deep_runtime_runner: DeepRuntimeRunner = run_deep_agent_runtime,
    deep_runtime_stream_runner: DeepRuntimeStreamRunner = stream_deep_agent_runtime_events,
    stream_runner: StreamRunner = stream_agent_events_from_state,
    runtime_store: RuntimeStore | None = None,
) -> None:
    self.route_runner = route_runner
    self.deep_runtime_runner = deep_runtime_runner
    self.deep_runtime_stream_runner = deep_runtime_stream_runner
    self.stream_runner = stream_runner
    self.runtime_store = runtime_store
```

Modify `stream_from_state()` to yield deep streaming events first:

```python
deep_events: list[AgentEvent] = []
for event in self.deep_runtime_stream_runner(
    run_state.message,
    project_path=run_state.project_path or "project.alita",
    run_id=run_state.run_id,
    thread_id=getattr(run_state, "thread_id", None) or f"thread-{run_state.message.task_id}",
    model_client=model_client,
    resume_command=_planning_resume_command_from_pending_choice(run_state.pending_choice),
):
    deep_events.append(event)
    yield event
if _deep_agent_finished_without_legacy(deep_events):
    next_state = started.state.model_copy(update={"stage": "plan"})
    self._write_state(next_state)
    return
```

- [ ] **Step 5: Add app streaming regression test**

In `python/tests/test_app.py`, add or update a test that calls `/agent/message/stream` with fake model setup and asserts the SSE contains:

```text
reasoning.decision_created
planning.started
planning.draft_created
node_graph.created
```

Do not include runtime control events in the public SSE output.

- [ ] **Step 6: Run streaming tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_runtime_streaming.py tests/test_agent_runtime_engine_deep_agent.py tests/test_app.py -q
Pop-Location
```

Expected: pass.

- [ ] **Step 7: Commit**

```powershell
git add python/agent_service/deep_agent_runtime_graph.py python/agent_service/agent_runtime_engine.py python/agent_service/app.py python/tests/test_deep_agent_runtime_streaming.py python/tests/test_app.py
git commit -m "feat: stream deep planning graph events"
```

---

## Task 8: Frontend Event And Pending Choice Support

**Files:**

- Modify: `src/shared/events.ts`
- Modify: `src/app/backendEvents.ts`
- Modify: `src/app/backendEvents.test.ts`
- Modify: `src/features/task/useTaskEvents.ts`
- Modify: `src/features/task/useTaskEvents.test.ts`
- Modify: `src/app/App.tsx`
- Modify: `src/app/App.test.tsx`
- Modify: `src/features/chat/ChatPanel.tsx`
- Modify: `src/features/chat/ChatPanel.test.tsx`

- [ ] **Step 1: Add failing reducer tests for Phase 2 events**

Append to `src/app/backendEvents.test.ts`:

```ts
it("stores planning confirmation as a pending choice", () => {
  const result = reduceBackendEvents(
    {
      messages: [],
      graph: null,
      dirty: false,
    },
    [
      {
        type: "planning.confirmation_required",
        payload: {
          taskId: "task-1",
          runId: "run-1",
          threadId: "thread-1",
          graphId: "graph-1",
          summary: "请确认是否执行计划图。",
          pendingChoice: {
            kind: "planning.confirmation",
            runId: "run-1",
            threadId: "thread-1",
            graphId: "graph-1",
          },
          choices: [
            { id: "approve", label: "确认执行" },
            { id: "revise", label: "要求修订" },
            { id: "cancel", label: "取消" },
          ],
        },
      },
    ],
    createAssistantMessage,
  );

  expect(result.pendingPlanningChoice).toMatchObject({
    taskId: "task-1",
    threadId: "thread-1",
  });
  expect(result.messages[0].content).toContain("请确认是否执行计划图。");
});

it("keeps planning checkpoint summaries out of normal chat messages", () => {
  const result = reduceBackendEvents(
    {
      messages: [],
      graph: null,
      dirty: false,
    },
    [
      {
        type: "planning.checkpoint_recorded",
        payload: {
          checkpoint: {
            runId: "run-1",
            threadId: "thread-1",
            checkpointId: "ckpt-1",
            stage: "deep_plan",
            node: "deep_plan",
            revisionCount: 0,
            hasPlanDraft: true,
            hasCompiledGraph: false,
            createdAt: "2026-06-02T00:00:00+00:00",
          },
        },
      },
    ],
    createAssistantMessage,
  );

  expect(result.messages).toEqual([]);
  expect(result.dirty).toBe(true);
});
```

- [ ] **Step 2: Run failing frontend tests**

Run:

```powershell
npm run frontend:test -- src/app/backendEvents.test.ts
```

Expected: fail because types and reducer fields do not exist.

- [ ] **Step 3: Add Phase 2 event types**

Modify `src/shared/events.ts` by adding these union members near existing planning events:

```ts
  | {
      type: "planning.stage_changed";
      payload: {
        taskId: string;
        stage: string;
        label: string;
      };
    }
  | {
      type: "planning.checkpoint_recorded";
      payload: {
        checkpoint: {
          runId: string;
          threadId: string;
          checkpointId: string;
          stage: string;
          node?: string | null;
          revisionCount: number;
          hasPlanDraft: boolean;
          hasCompiledGraph: boolean;
          createdAt: string;
        };
      };
    }
  | {
      type: "planning.confirmation_required";
      payload: {
        taskId: string;
        runId: string;
        threadId: string;
        graphId: string;
        summary: string;
        pendingChoice: Record<string, unknown>;
        choices: Array<{
          id: "approve" | "revise" | "cancel";
          label: string;
          description?: string;
        }>;
      };
    }
  | {
      type: "planning.confirmed";
      payload: {
        taskId: string;
        runId: string;
        threadId: string;
        graphId: string;
      };
    }
  | {
      type: "planning.cancelled";
      payload: {
        taskId: string;
        runId: string;
        threadId: string;
        graphId: string;
      };
    }
  | {
      type: "planning.interrupted" | "planning.resumed";
      payload: Record<string, unknown>;
    }
  | {
      type:
        | "planning.revision_requested"
        | "planning.revision_started"
        | "planning.revision_completed"
        | "planning.revision_exhausted";
      payload: Record<string, unknown>;
    }
```

- [ ] **Step 4: Add planning pending choice reducer state**

Modify `src/app/backendEvents.ts`:

```ts
export type PendingPlanningChoice = Extract<
  BackendEvent,
  { type: "planning.confirmation_required" }
>["payload"];

type PlanningCheckpointRecord = Extract<
  BackendEvent,
  { type: "planning.checkpoint_recorded" }
>["payload"]["checkpoint"];
```

Then add these fields to `BackendEventState`:

```ts
  pendingPlanningChoice?: PendingPlanningChoice | null;
  planningCheckpoints?: PlanningCheckpointRecord[];
```

Add reducer branches:

```ts
    if (event.type === "planning.stage_changed") {
      return {
        ...current,
        dirty: true,
      };
    }

    if (event.type === "planning.checkpoint_recorded") {
      return {
        ...current,
        planningCheckpoints: [
          ...(current.planningCheckpoints ?? []),
          event.payload.checkpoint,
        ],
        dirty: true,
      };
    }

    if (event.type === "planning.confirmation_required") {
      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage(formatPlanningConfirmationPrompt(event.payload)),
        ],
        pendingResearchChoice: null,
        pendingGraphOverwriteChoice: null,
        pendingPlanningChoice: event.payload,
        dirty: true,
      };
    }

    if (event.type === "planning.confirmed") {
      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage("已确认计划图，等待执行。"),
        ],
        pendingPlanningChoice: null,
        dirty: true,
      };
    }

    if (event.type === "planning.cancelled") {
      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage("已取消本次计划。"),
        ],
        pendingPlanningChoice: null,
        dirty: true,
      };
    }
```

Add formatter:

```ts
function formatPlanningConfirmationPrompt(
  payload: PendingPlanningChoice,
): string {
  const choices = payload.choices
    .map((choice, index) => `${index + 1}. ${choice.label}`)
    .join("\n");
  return `${payload.summary}\n\n${choices}`;
}
```

- [ ] **Step 5: Add frontend pending-choice serialization helper**

Modify `src/app/backendEvents.ts`:

```ts
export function toPlanningConfirmationSubmitChoice(
  pendingChoice: PendingPlanningChoice,
  choiceId: "approve" | "revise" | "cancel",
  revisionInstructions: string[] = [],
): Record<string, unknown> {
  return {
    ...pendingChoice.pendingChoice,
    kind: "planning.confirmation",
    decision: choiceId,
    revisionInstructions,
  };
}
```

Add tests:

```ts
it("serializes planning confirmation submit choice", () => {
  const choice: PendingPlanningChoice = {
    taskId: "task-1",
    runId: "run-1",
    threadId: "thread-1",
    graphId: "graph-1",
    summary: "Confirm.",
    pendingChoice: {
      kind: "planning.confirmation",
      runId: "run-1",
      threadId: "thread-1",
      graphId: "graph-1",
    },
    choices: [{ id: "approve", label: "Approve" }],
  };

  expect(toPlanningConfirmationSubmitChoice(choice, "approve")).toMatchObject({
    kind: "planning.confirmation",
    decision: "approve",
    threadId: "thread-1",
  });
});
```

- [ ] **Step 6: Wire App pendingPlanningChoice refs**

Modify `src/app/App.tsx` by mirroring the existing `pendingGraphOverwriteChoice` pattern:

```ts
const pendingPlanningChoiceRef = useRef<PendingPlanningChoice | null>(null);
```

When reducer output is applied:

```ts
pendingPlanningChoiceRef.current = next.pendingPlanningChoice ?? null;
```

When submitting a planning confirmation:

```ts
const pendingPlanningChoice = pendingPlanningChoiceRef.current;
if (pendingPlanningChoice) {
    await submitUserMessageWithStreamFallback({
      payload: {
        taskId: pendingPlanningChoice.taskId,
        content,
        attachments: [],
      pendingChoice: toPlanningConfirmationSubmitChoice(
        pendingPlanningChoice,
        selectedChoice,
      ),
      modelSessionId: await registerAgentModelSessionForSubmit(),
    },
    createSession: createAgentSession,
    submitStream: submitUserMessageStream,
    submitFallback: submitUserMessage,
    onEvent: (event) => applyBackendEvent(event, {
      taskId: pendingPlanningChoice.taskId,
      content,
      attachments: [],
      pendingChoice: toPlanningConfirmationSubmitChoice(
        pendingPlanningChoice,
        selectedChoice,
      ),
    }),
  });
}
```

Use the existing chat submit path for typed revision text. Add planning confirmation buttons to `ChatPanel` next to the existing research choice bar with `className="secondaryButton researchChoiceButton"` so the visual treatment stays consistent.

- [ ] **Step 7: Run frontend tests**

Run:

```powershell
npm run frontend:test -- src/app/backendEvents.test.ts src/features/task/useTaskEvents.test.ts src/app/App.test.tsx src/features/chat/ChatPanel.test.tsx
npm run frontend:typecheck
```

Expected: pass.

- [ ] **Step 8: Commit**

```powershell
git add src/shared/events.ts src/app/backendEvents.ts src/app/backendEvents.test.ts src/features/task/useTaskEvents.ts src/features/task/useTaskEvents.test.ts src/app/App.tsx src/app/App.test.tsx src/features/chat/ChatPanel.tsx src/features/chat/ChatPanel.test.tsx
git commit -m "feat: surface deep planning confirmation state"
```

---

## Task 9: Regression Gates And Documentation Sync

**Files:**

- Modify: `docs/superpowers/specs/2026-06-02-deep-planning-langgraph-phase-2-design.md`
- Modify: `README.md` if runtime behavior docs are stale.
- Modify: focused tests whose assertions change because Phase 2 adds confirmation before execution.

- [ ] **Step 1: Run backend focused suite**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_checkpointer.py tests/test_deep_agent_runtime_graph.py tests/test_deep_agent_runtime_resume.py tests/test_deep_agent_runtime_streaming.py tests/test_deep_agent_planner.py tests/test_agent_runtime_engine_deep_agent.py -q
Pop-Location
```

Expected: all tests pass.

- [ ] **Step 2: Run backend regression suite**

Run:

```powershell
Push-Location python
python -m pytest tests/test_agent_runtime_engine.py tests/test_app.py tests/test_graph.py tests/test_runtime_store.py tests/test_run_journal.py tests/test_model_client.py -q
Pop-Location
```

Expected: all tests pass.

- [ ] **Step 3: Run frontend focused suite**

Run:

```powershell
npm run frontend:test -- src/app/backendEvents.test.ts src/features/task/useTaskEvents.test.ts src/app/App.test.tsx src/features/chat/ChatPanel.test.tsx src/features/canvas/NodePopover.test.tsx
npm run frontend:typecheck
```

Expected: all tests pass.

- [ ] **Step 4: Run full Python quick gate if time allows**

Run:

```powershell
Push-Location python
python -m pytest -q
Pop-Location
```

Expected: pass. If this is too slow during implementation, run it before final handoff.

- [ ] **Step 5: Check whitespace and generated file drift**

Run:

```powershell
git diff --check
git status --short
```

Expected:

- No whitespace errors.
- Only intentional Phase 2 files are modified.
- Pre-existing unrelated `src-tauri/Cargo.toml` changes remain unstaged unless they are part of a separate user-approved task.

- [ ] **Step 6: Update docs with actual implementation notes**

If implementation details differ from the spec, update:

```text
docs/superpowers/specs/2026-06-02-deep-planning-langgraph-phase-2-design.md
```

Use concrete statements only. Do not add aspirational text.

- [ ] **Step 7: Commit final docs/test sync**

```powershell
git add docs/superpowers/specs/2026-06-02-deep-planning-langgraph-phase-2-design.md README.md
git commit -m "docs: sync deep planning phase 2 behavior"
```

Only include `README.md` if it changed.

---

## Final Verification

Run:

```powershell
git diff --check
Push-Location python
python -m pytest tests/test_deep_agent_checkpointer.py tests/test_deep_agent_runtime_graph.py tests/test_deep_agent_runtime_resume.py tests/test_deep_agent_runtime_streaming.py tests/test_deep_agent_planner.py tests/test_agent_runtime_engine_deep_agent.py tests/test_agent_runtime_engine.py tests/test_app.py tests/test_graph.py tests/test_runtime_store.py tests/test_run_journal.py tests/test_model_client.py -q
Pop-Location
npm run frontend:typecheck
npm run frontend:test -- src/app/backendEvents.test.ts src/features/task/useTaskEvents.test.ts src/app/App.test.tsx src/features/chat/ChatPanel.test.tsx src/features/canvas/NodePopover.test.tsx
```

Expected:

- No whitespace errors.
- Deep planning tests prove checkpoint, interrupt, resume, revision, confirmation, and streaming behavior.
- Regression tests prove no legacy template fallback on Deep Agent task graph creation.
- Frontend tests prove planning confirmation and checkpoint events reduce cleanly.
- TypeScript typecheck passes.

## Definition Of Done

Phase 2 is complete only when:

- `build_deep_agent_runtime_graph()` accepts a LangGraph checkpointer.
- Deep planning invocations always use a stable `thread_id`.
- Clarification uses `interrupt()` and resumes on the same thread.
- Confirmation uses `interrupt()` and resumes with approve, revise, or cancel.
- `revise_plan` is bounded and model-backed.
- Planning checkpoint summaries are persisted safely through `RuntimeStore`.
- Streaming events come from LangGraph execution updates.
- Existing Phase 1 graph provenance remains intact.
- No user task graph path silently falls back to legacy templates.
- UI can represent planning confirmation without pretending the graph is already executing.
