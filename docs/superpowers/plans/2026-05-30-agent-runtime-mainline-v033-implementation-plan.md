# Agent Runtime Mainline V033 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the 0.33.0 optimization audit into a gated implementation program that makes Alita's Agent Runtime the default control plane for task execution, durability, safety, tool planning, MCP, observability, memory, and eval.

**Architecture:** Keep the current graph workbench and sidecar APIs backward-compatible while introducing a new runtime mainline in layers: first state/action/delta models, then an engine facade, then checkpoint v2, eval/CI, capability grants, planner DAG validation, MCP client path, trace store, and memory v2. Each phase produces testable software and must pass its gate before the next phase starts.

**Tech Stack:** Python 3.10+ FastAPI/Pydantic/pytest, local JSON run journals, existing LangGraph route graph, React 19/TypeScript/Vitest, Tauri 2/Rust tests, MCP provider abstractions, Windows-first constrained execution.

---

## Source Documents

- Audit: `docs/agent-development-optimization-2026-05-30-v033.md`
- Plan: `docs/superpowers/plans/2026-05-30-agent-runtime-mainline-v033-implementation-plan.md`
- Progress tracker: `docs/superpowers/progress/2026-05-30-agent-runtime-mainline-v033-progress.md`

## Goal-Mode Operating Rules

For every phase:

1. Confirm entry conditions.
2. Write or update tests before behavior changes.
3. Run the targeted test and record the expected failure when the behavior is missing.
4. Implement the smallest coherent change that satisfies the phase.
5. Run the phase gate exactly as written.
6. Inspect `git diff --check`, targeted source diffs, and relevant event/schema changes.
7. Update the progress tracker with command evidence.
8. Enter the next phase only after the phase gate passes.

If the same blocker repeats for three consecutive goal turns and no meaningful progress is possible, mark the Codex goal blocked and write the blocker into the progress tracker.

## Shared Verification Commands

Use targeted gates inside each phase first. Use these broader gates when a phase touches shared contracts:

```powershell
git diff --check
npm run agent:eval
Push-Location python; python -m pytest -q; Pop-Location
npm run frontend:typecheck
npm run frontend:test
cargo test --manifest-path src-tauri/Cargo.toml
```

## Phase Map

| Phase | Name | Outcome | Gate |
| --- | --- | --- | --- |
| 0 | Worktree, Baseline, Progress Tracker | Isolated branch/workspace ready, progress tracker created, baseline verified | status, diff check, eval, targeted runtime tests |
| 1 | Runtime State And Action Models | Add first-class runtime state/action/delta schemas without changing public behavior | runtime model tests and existing graph tests |
| 2 | AgentRuntimeEngine Facade | Add engine `start_run/step/resume/interrupt` over current planner/executor seams | engine tests and graph compatibility tests |
| 3 | Checkpoint V2 And Atomic Journal | Add thread/sequence/parent/hash/state-version checkpoints and atomic journal writes | journal/resume tests and execution tests |
| 4 | Eval And CI Gate | Add mock model-loop runner and GitHub Actions gate for frontend/python/eval | eval harness tests and workflow lint-by-inspection |
| 5 | Capability-First Safety | Introduce capability request/grant schema and enforce domain/budget/tool grants in gateway | authority/gateway/security eval tests |
| 6 | Schema DAG Tool Planner | Add deterministic schema verifier and limited multi-tool action graph planning | planner/tool catalog/eval tests |
| 7 | Runtime ActionGraph Bridge | Compile document/research templates into action graphs while preserving legacy graph UI | execution graph and document/research tests |
| 8 | MCP End-To-End Minimal Path | Implement testable stdio/http MCP client factory and sidecar config handoff | MCP provider/gateway/Rust preference tests |
| 9 | Trace Store And Span Taxonomy | Persist trace spans, add model/tool/checkpoint span taxonomy, bind eval summaries | runtime trace/execution/frontend tests |
| 10 | Memory V2 Retrieval | Add memory schema v2, migration-safe parsing, deterministic scorer, and context selection | memory/context/graph tests |
| 11 | Final Docs And Full Gate | Update docs, record residual risks, run full regression | all shared verification commands |

## Phase 0: Worktree, Baseline, Progress Tracker

**Files:**
- Create: `docs/superpowers/progress/2026-05-30-agent-runtime-mainline-v033-progress.md`
- Verify: `docs/agent-development-optimization-2026-05-30-v033.md`
- Verify: `package.json`
- Verify: `python/pyproject.toml`

- [ ] **Step 0.1: Confirm workspace isolation**

Run:

```powershell
git rev-parse --show-toplevel
git rev-parse --git-dir
git rev-parse --git-common-dir
git rev-parse --show-superproject-working-tree
git branch --show-current
git status --short --branch
```

Expected:

```text
Repository root is the implementation workspace.
If on main, stop before code changes and create an isolated worktree or branch.
There is no superproject path.
Status output does not include unrelated modified source files.
```

- [ ] **Step 0.2: Create progress tracker**

Create `docs/superpowers/progress/2026-05-30-agent-runtime-mainline-v033-progress.md` with this content:

```markdown
# Agent Runtime Mainline V033 Progress

Started: 2026-05-30
Source audit: `docs/agent-development-optimization-2026-05-30-v033.md`
Plan: `docs/superpowers/plans/2026-05-30-agent-runtime-mainline-v033-implementation-plan.md`

| Phase | Status | Evidence | Next Action |
| --- | --- | --- | --- |
| 0 Worktree, Baseline, Progress Tracker | in_progress | Plan created | Run Phase 0 gate |
| 1 Runtime State And Action Models | pending | | Wait for Phase 0 |
| 2 AgentRuntimeEngine Facade | pending | | Wait for Phase 1 |
| 3 Checkpoint V2 And Atomic Journal | pending | | Wait for Phase 2 |
| 4 Eval And CI Gate | pending | | Wait for Phase 3 |
| 5 Capability-First Safety | pending | | Wait for Phase 4 |
| 6 Schema DAG Tool Planner | pending | | Wait for Phase 5 |
| 7 Runtime ActionGraph Bridge | pending | | Wait for Phase 6 |
| 8 MCP End-To-End Minimal Path | pending | | Wait for Phase 7 |
| 9 Trace Store And Span Taxonomy | pending | | Wait for Phase 8 |
| 10 Memory V2 Retrieval | pending | | Wait for Phase 9 |
| 11 Final Docs And Full Gate | pending | | Wait for Phase 10 |

## Phase Evidence
```

- [ ] **Step 0.3: Run baseline gate**

Run:

```powershell
git diff --check
npm run agent:eval
Push-Location python; python -m pytest tests/test_agent_runtime_graph.py tests/test_run_journal.py tests/test_runtime_trace.py tests/test_tool_catalog_planner.py tests/test_authority.py tests/test_mcp_tool_provider.py tests/test_memory_store.py -q; Pop-Location
```

Expected:

```text
git diff --check exits 0
Agent eval summary: 64/64 passed, 0 failed.
targeted pytest exits 0
```

- [ ] **Step 0.4: Update progress tracker**

Set Phase 0 row to:

```markdown
| 0 Worktree, Baseline, Progress Tracker | complete | `git diff --check`; `npm run agent:eval` -> 64/64; targeted pytest passed | Enter Phase 1 |
```

Set Phase 1 row to `in_progress`.

## Phase 1: Runtime State And Action Models

**Files:**
- Create: `python/agent_service/runtime_state.py`
- Modify: `python/agent_service/agent_runtime_graph.py`
- Test: `python/tests/test_runtime_state.py`
- Test: `python/tests/test_agent_runtime_graph.py`

- [ ] **Step 1.1: Write runtime state model tests**

Create `python/tests/test_runtime_state.py`:

```python
from agent_service.runtime_state import (
    RuntimeAction,
    RuntimeState,
    RuntimeStateDelta,
    initial_runtime_state,
)
from agent_service.schemas import UserMessage


def test_initial_runtime_state_uses_route_stage_and_thread_id():
    message = UserMessage(task_id="task-1", content="Create a report.")

    state = initial_runtime_state(
        message=message,
        project_path="D:/Project/demo.alita",
        run_id="run-1",
    )

    assert state.thread_id == "thread-task-1"
    assert state.run_id == "run-1"
    assert state.task_id == "task-1"
    assert state.stage == "route"
    assert state.messages[0]["role"] == "user"
    assert state.messages[0]["content"] == "Create a report."
    assert state.project_path == "D:/Project/demo.alita"


def test_runtime_action_records_model_tool_human_and_control_shape():
    action = RuntimeAction(
        action_id="act-1",
        action_type="tool",
        name="internal:test.echo_values",
        inputs={"message": "hello"},
        expected_outputs={"text": "string"},
        dependencies=["act-0"],
    )

    assert action.action_id == "act-1"
    assert action.action_type == "tool"
    assert action.permissions == []
    assert action.timeout_ms is None


def test_runtime_delta_records_stage_transition_and_writes():
    delta = RuntimeStateDelta(
        previous_checkpoint_id="ckpt-1",
        checkpoint_id="ckpt-2",
        stage_before="plan",
        stage_after="act",
        decision={"actionId": "act-1"},
        writes=[{"kind": "selected_action", "actionId": "act-1"}],
        emitted_events=[{"type": "runtime.state_delta"}],
    )

    assert delta.stage_before == "plan"
    assert delta.stage_after == "act"
    assert delta.writes[0]["kind"] == "selected_action"
```

- [ ] **Step 1.2: Run model tests to verify RED**

Run:

```powershell
Push-Location python; python -m pytest tests/test_runtime_state.py -q; Pop-Location
```

Expected:

```text
FAIL with ModuleNotFoundError for agent_service.runtime_state
```

- [ ] **Step 1.3: Implement runtime state models**

Create `python/agent_service/runtime_state.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_service.schemas import UserMessage


RuntimeStage = Literal[
    "route",
    "context",
    "plan",
    "approve",
    "act",
    "observe",
    "verify",
    "replan",
    "final",
    "failed",
    "interrupted",
]

RuntimeActionType = Literal["model", "tool", "human", "control"]


class RuntimeAction(BaseModel):
    action_id: str
    action_type: RuntimeActionType
    name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected_outputs: dict[str, Any] = Field(default_factory=dict)
    permissions: list[dict[str, Any]] = Field(default_factory=list)
    timeout_ms: int | None = None
    retry_policy: dict[str, Any] | None = None
    dependencies: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeState(BaseModel):
    thread_id: str
    run_id: str
    task_id: str
    project_path: str
    stage: RuntimeStage = "route"
    messages: list[dict[str, Any]] = Field(default_factory=list)
    goal_spec: dict[str, Any] | None = None
    context_bundle: dict[str, Any] | None = None
    action_graph: dict[str, Any] | None = None
    selected_action: RuntimeAction | None = None
    observations: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] | None = None
    pending_approvals: list[dict[str, Any]] = Field(default_factory=list)
    memory_writes: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeStateDelta(BaseModel):
    previous_checkpoint_id: str | None = None
    checkpoint_id: str
    stage_before: RuntimeStage | str
    stage_after: RuntimeStage | str
    decision: dict[str, Any] = Field(default_factory=dict)
    writes: list[dict[str, Any]] = Field(default_factory=list)
    emitted_events: list[dict[str, Any]] = Field(default_factory=list)


def initial_runtime_state(
    *,
    message: UserMessage,
    project_path: str,
    run_id: str,
    thread_id: str | None = None,
) -> RuntimeState:
    return RuntimeState(
        thread_id=thread_id or f"thread-{message.task_id}",
        run_id=run_id,
        task_id=message.task_id,
        project_path=project_path,
        stage="route",
        messages=[
            {
                "role": "user",
                "content": message.content,
                "attachments": [attachment.model_dump() for attachment in message.attachments],
            }
        ],
    )
```

- [ ] **Step 1.4: Align AgentRuntimeGraph stages with runtime state**

Modify `python/agent_service/agent_runtime_graph.py` so `AgentRuntimeStage` includes `context`, `approve`, `act`, and `interrupted`. Keep existing stages and public helpers backward-compatible:

```python
AgentRuntimeStage = Literal[
    "route",
    "context",
    "plan",
    "approve",
    "execute",
    "act",
    "observe",
    "verify",
    "replan",
    "final",
    "failed",
    "interrupted",
]
```

Do not remove `execute` in this phase because existing metadata uses it.

- [ ] **Step 1.5: Run Phase 1 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_runtime_state.py tests/test_agent_runtime_graph.py tests/test_graph.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected:

```text
runtime state tests pass
agent runtime graph and graph tests pass
Agent eval summary: 64/64 passed, 0 failed.
git diff --check exits 0
```

- [ ] **Step 1.6: Update progress tracker**

Set Phase 1 to complete with the gate evidence. Set Phase 2 to `in_progress`.

## Phase 2: AgentRuntimeEngine Facade

**Files:**
- Create: `python/agent_service/agent_runtime_engine.py`
- Modify: `python/agent_service/graph.py`
- Modify: `python/agent_service/runtime_events.py`
- Test: `python/tests/test_agent_runtime_engine.py`
- Test: `python/tests/test_graph.py`

- [ ] **Step 2.1: Write engine facade tests**

Create `python/tests/test_agent_runtime_engine.py`:

```python
from agent_service.agent_runtime_engine import AgentRuntimeEngine
from agent_service.schemas import UserMessage


def test_engine_start_run_creates_runtime_state_and_started_event():
    engine = AgentRuntimeEngine()
    message = UserMessage(task_id="task-engine", content="Create a Python script.")

    result = engine.start_run(
        message=message,
        project_path="D:/Project/demo.alita",
        run_id="run-engine",
    )

    assert result.state.stage == "route"
    assert result.state.run_id == "run-engine"
    assert [event.type for event in result.events] == ["runtime.run_started"]
    assert result.events[0].payload["runId"] == "run-engine"


def test_engine_step_routes_and_plans_task_with_existing_planner():
    engine = AgentRuntimeEngine()
    message = UserMessage(task_id="task-engine-plan", content="Create a Python script that counts CSV rows.")

    started = engine.start_run(
        message=message,
        project_path="D:/Project/demo.alita",
        run_id="run-engine-plan",
    )
    events = engine.step(started.state)

    event_types = [event.type for event in events]
    assert "runtime.state_delta" in event_types
    assert "node_graph.created" in event_types


def test_engine_interrupt_marks_state_interrupted():
    engine = AgentRuntimeEngine()
    message = UserMessage(task_id="task-interrupt", content="Create a report.")
    started = engine.start_run(
        message=message,
        project_path="D:/Project/demo.alita",
        run_id="run-interrupt",
    )

    result = engine.interrupt(started.state, reason="user_cancelled")

    assert result.state.stage == "interrupted"
    assert result.events[0].type == "runtime.interrupted"
```

- [ ] **Step 2.2: Run engine tests to verify RED**

Run:

```powershell
Push-Location python; python -m pytest tests/test_agent_runtime_engine.py -q; Pop-Location
```

Expected:

```text
FAIL with ModuleNotFoundError for agent_service.agent_runtime_engine
```

- [ ] **Step 2.3: Implement engine facade**

Create `python/agent_service/agent_runtime_engine.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from agent_service.graph import run_agent_from_state
from agent_service.agent_run_state import AgentRunState
from agent_service.runtime_state import RuntimeState, RuntimeStateDelta, initial_runtime_state
from agent_service.schemas import AgentEvent, UserMessage


@dataclass(frozen=True)
class RuntimeEngineResult:
    state: RuntimeState
    events: list[AgentEvent]


class AgentRuntimeEngine:
    def start_run(
        self,
        *,
        message: UserMessage,
        project_path: str,
        run_id: str | None = None,
        thread_id: str | None = None,
    ) -> RuntimeEngineResult:
        state = initial_runtime_state(
            message=message,
            project_path=project_path,
            run_id=run_id or f"run-{uuid4()}",
            thread_id=thread_id,
        )
        return RuntimeEngineResult(
            state=state,
            events=[
                AgentEvent(
                    type="runtime.run_started",
                    payload={
                        "runId": state.run_id,
                        "threadId": state.thread_id,
                        "taskId": state.task_id,
                        "stage": state.stage,
                    },
                )
            ],
        )

    def step(self, state: RuntimeState) -> list[AgentEvent]:
        message = UserMessage(
            task_id=state.task_id,
            content=str(state.messages[0].get("content") or ""),
        )
        run_state = AgentRunState.from_user_message(message).model_copy(
            update={
                "project_path": state.project_path,
                "run_id": state.run_id,
            }
        )
        routed_events = run_agent_from_state(run_state)
        delta = RuntimeStateDelta(
            previous_checkpoint_id=None,
            checkpoint_id=f"{state.run_id}:route:0",
            stage_before=state.stage,
            stage_after="plan",
            decision={"kind": "route_and_plan"},
            emitted_events=[event.model_dump() for event in routed_events],
        )
        return [
            AgentEvent(type="runtime.state_delta", payload={"delta": delta.model_dump()}),
            *routed_events,
        ]

    def resume(self, state: RuntimeState, checkpoint_id: str | None = None) -> list[AgentEvent]:
        return [
            AgentEvent(
                type="runtime.resume_requested",
                payload={
                    "runId": state.run_id,
                    "threadId": state.thread_id,
                    "checkpointId": checkpoint_id,
                },
            )
        ]

    def interrupt(self, state: RuntimeState, *, reason: str) -> RuntimeEngineResult:
        interrupted = state.model_copy(update={"stage": "interrupted"})
        return RuntimeEngineResult(
            state=interrupted,
            events=[
                AgentEvent(
                    type="runtime.interrupted",
                    payload={
                        "runId": state.run_id,
                        "threadId": state.thread_id,
                        "reason": reason,
                    },
                )
            ],
        )
```

- [ ] **Step 2.4: Add runtime event type helper**

Modify `python/agent_service/runtime_events.py` only if a shared helper reduces duplication. Add:

```python
def runtime_state_delta_event(delta: RuntimeStateDelta) -> AgentEvent:
    return AgentEvent(type="runtime.state_delta", payload={"delta": delta.model_dump()})
```

Keep direct event construction if adding the helper creates an import cycle.

- [ ] **Step 2.5: Keep public graph behavior unchanged**

Do not route `/agent/message` through the engine by default in this phase. Add a graph test assertion that existing task requests still return only `node_graph.created`, not `runtime.run_started`.

- [ ] **Step 2.6: Run Phase 2 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_agent_runtime_engine.py tests/test_graph.py tests/test_agent_run_state.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected:

```text
engine tests pass
existing graph tests pass
Agent eval summary: 64/64 passed, 0 failed.
git diff --check exits 0
```

- [ ] **Step 2.7: Update progress tracker**

Set Phase 2 to complete. Set Phase 3 to `in_progress`.

## Phase 3: Checkpoint V2 And Atomic Journal

**Files:**
- Modify: `python/agent_service/runtime_loop.py`
- Modify: `python/agent_service/run_journal.py`
- Modify: `python/agent_service/execution.py`
- Test: `python/tests/test_run_journal.py`
- Test: `python/tests/test_execution.py`

- [ ] **Step 3.1: Write checkpoint v2 tests**

Add to `python/tests/test_run_journal.py`:

```python
from agent_service.runtime_loop import RuntimeCheckpoint
from agent_service.run_journal import RunJournal


def test_checkpoint_v2_records_sequence_parent_hash_and_state(tmp_path):
    checkpoint = RuntimeCheckpoint(
        run_id="run-1",
        node_id="node-a",
        status="after_node",
        completed_outputs={},
        pending_node_ids=[],
        created_at="2026-05-30T00:00:00Z",
        thread_id="thread-1",
        sequence=7,
        parent_checkpoint_id="ckpt-parent",
        graph_hash="sha256:abc",
        state_version=2,
        writes=[{"kind": "node_output"}],
        pending_approvals=[{"kind": "tool"}],
        runtime_state={"stage": "observe"},
    )

    record = checkpoint.to_record()

    assert record["threadId"] == "thread-1"
    assert record["sequence"] == 7
    assert record["parentCheckpointId"] == "ckpt-parent"
    assert record["graphHash"] == "sha256:abc"
    assert record["stateVersion"] == 2
    assert record["writes"] == [{"kind": "node_output"}]
    assert record["runtimeState"] == {"stage": "observe"}


def test_run_journal_atomic_write_leaves_no_tmp_file(tmp_path):
    journal = RunJournal(project_path=str(tmp_path / "demo.alita"), run_id="run-1")
    journal.write_run({"runId": "run-1", "status": "running"})

    assert journal.read_run()["status"] == "running"
    assert list(journal.base_dir.glob("*.tmp")) == []
```

- [ ] **Step 3.2: Run checkpoint tests to verify RED**

Run:

```powershell
Push-Location python; python -m pytest tests/test_run_journal.py::test_checkpoint_v2_records_sequence_parent_hash_and_state tests/test_run_journal.py::test_run_journal_atomic_write_leaves_no_tmp_file -q; Pop-Location
```

Expected:

```text
FAIL because RuntimeCheckpoint lacks v2 fields and RunJournal lacks read_run or atomic writes
```

- [ ] **Step 3.3: Extend RuntimeCheckpoint backward-compatibly**

Modify `RuntimeCheckpoint` in `python/agent_service/runtime_loop.py`:

```python
thread_id: str | None = None
sequence: int | None = None
parent_checkpoint_id: str | None = None
graph_hash: str | None = None
state_version: int = 1
writes: list[dict[str, Any]] = Field(default_factory=list)
pending_approvals: list[dict[str, Any]] = Field(default_factory=list)
runtime_state: dict[str, Any] = Field(default_factory=dict)
```

Add camelCase fields to `to_record()`. Keep existing `checkpointId`, `completedOutputs`, and `pendingNodeIds`.

- [ ] **Step 3.4: Add atomic journal writes and read_run**

Modify `RunJournal._write_json()`:

```python
tmp_path = path.with_suffix(path.suffix + ".tmp")
tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp_path.replace(path)
```

Add:

```python
def read_run(self) -> dict[str, Any]:
    return json.loads((self.base_dir / "run.json").read_text(encoding="utf-8"))
```

- [ ] **Step 3.5: Add sequence assignment in execution**

In `run_graph_events()`, maintain `checkpoint_sequence = 0`. Before each checkpoint write, increment sequence and pass `sequence=checkpoint_sequence`, `thread_id=f"thread-{request.task_id}"`, `state_version=2`, and `runtime_state={"nodeId": node.nodeId, "status": checkpoint.status}`.

- [ ] **Step 3.6: Run Phase 3 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_run_journal.py tests/test_execution.py tests/test_agent_runtime_engine.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected:

```text
run journal and execution tests pass
Agent eval summary: 64/64 passed, 0 failed.
git diff --check exits 0
```

- [ ] **Step 3.7: Update progress tracker**

Set Phase 3 to complete. Set Phase 4 to `in_progress`.

## Phase 4: Eval And CI Gate

**Files:**
- Modify: `python/agent_service/eval_harness.py`
- Modify: `python/evals/model_loop_cases.jsonl`
- Create: `.github/workflows/ci.yml`
- Test: `python/tests/test_eval_harness.py`

- [ ] **Step 4.1: Write mock model-loop eval test**

Add to `python/tests/test_eval_harness.py`:

```python
from agent_service.eval_harness import EvalCase, run_eval_cases


def test_model_loop_eval_runs_mock_runner_when_enabled(monkeypatch):
    monkeypatch.setenv("ALITA_MODEL_LOOP_EVAL", "mock")
    summary = run_eval_cases(
        [
            EvalCase(
                case_id="model-loop-mock",
                category="model_loop",
                input={"kind": "planner_binding", "content": "Use echo tool"},
                expected={"skipped": False, "runner": "mock", "ok": True},
            )
        ]
    )

    assert summary.failed == 0
    assert summary.results[0].details["runner"] == "mock"
```

- [ ] **Step 4.2: Run model-loop test to verify RED**

Run:

```powershell
Push-Location python; python -m pytest tests/test_eval_harness.py::test_model_loop_eval_runs_mock_runner_when_enabled -q; Pop-Location
```

Expected:

```text
FAIL because enabled model_loop returns "runner is not configured"
```

- [ ] **Step 4.3: Implement mock model-loop runner**

Modify `_run_model_loop_case()`:

```python
mode = os.getenv("ALITA_MODEL_LOOP_EVAL", "").strip().lower()
if mode not in {"1", "true", "yes", "on", "mock"}:
    details = {"skipped": True, "reason": "model loop eval disabled"}
    ...
if mode == "mock":
    details = {"skipped": False, "runner": "mock", "ok": True}
    return EvalCaseResult(..., passed=_expected_subset_matches(details, case.expected), details=details)
```

Keep non-mock enabled mode failing until a real runner is implemented.

- [ ] **Step 4.4: Add CI workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: ci

on:
  pull_request:
  push:
    branches: [main]

jobs:
  frontend:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
      - run: npm ci
      - run: npm run frontend:typecheck
      - run: npm run frontend:test

  python:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install --upgrade pip
      - run: python -m pip install -e "python[test]"
      - run: python -m pytest python/tests -q
      - run: npm ci
      - run: npm run agent:eval
```

- [ ] **Step 4.5: Run Phase 4 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_eval_harness.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected:

```text
eval harness tests pass
Agent eval summary: 64/64 passed, 0 failed.
git diff --check exits 0
```

- [ ] **Step 4.6: Update progress tracker**

Set Phase 4 to complete. Set Phase 5 to `in_progress`.

## Phase 5: Capability-First Safety

**Files:**
- Create: `python/agent_service/capability_grants.py`
- Modify: `python/agent_service/authority.py`
- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/agent_service/eval_harness.py`
- Modify: `python/evals/security_cases.jsonl`
- Test: `python/tests/test_authority.py`
- Test: `python/tests/test_tool_gateway.py`
- Test: `python/tests/test_eval_harness.py`

- [ ] **Step 5.1: Write capability request tests**

Add to `python/tests/test_authority.py`:

```python
from agent_service.capability_grants import capability_request_for_tool_invocation
from agent_service.tool_protocol import ToolSafetyPolicy, UnifiedToolDefinition, UnifiedToolInvocation


def test_capability_request_extracts_tool_filesystem_and_network_domain():
    tool = UnifiedToolDefinition(
        id="internal:web.fetch",
        source="internal",
        provider_id="internal",
        provider_tool_name="web.fetch",
        display_name="Fetch",
        description="Fetch URL",
        capabilities=["web_search"],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        permissions=["network"],
        safety_policy=ToolSafetyPolicy(
            filesystem="none",
            network="provider_declared",
            user_approval="high_risk_only",
            secrets="none",
            sandbox="not_required",
            max_runtime_ms=5000,
        ),
        timeout_ms=5000,
    )
    invocation = UnifiedToolInvocation(
        invocation_id="inv-1",
        run_id="run-1",
        task_id="task-1",
        tool_id="internal:web.fetch",
        arguments={"url": "https://docs.example.com/a"},
        allowed_roots=[],
        requested_permissions=["network"],
        metadata={"networkDomain": "docs.example.com"},
    )

    request = capability_request_for_tool_invocation(invocation, tool)

    assert request.capability == "tool"
    assert request.tool_id == "internal:web.fetch"
    assert request.network_domains == ["docs.example.com"]
    assert request.runtime_budget_ms == 5000
```

- [ ] **Step 5.2: Run capability tests to verify RED**

Run:

```powershell
Push-Location python; python -m pytest tests/test_authority.py::test_capability_request_extracts_tool_filesystem_and_network_domain -q; Pop-Location
```

Expected:

```text
FAIL with ModuleNotFoundError for agent_service.capability_grants
```

- [ ] **Step 5.3: Implement capability grant module**

Create `python/agent_service/capability_grants.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field

from agent_service.authority import extract_invocation_paths
from agent_service.tool_protocol import UnifiedToolDefinition, UnifiedToolInvocation


class CapabilityRequest(BaseModel):
    capability: str
    provider_id: str | None = None
    tool_id: str | None = None
    operation: str | None = None
    read_roots: list[str] = Field(default_factory=list)
    write_roots: list[str] = Field(default_factory=list)
    network_domains: list[str] = Field(default_factory=list)
    runtime_budget_ms: int | None = None
    reason: str = ""


def capability_request_for_tool_invocation(
    invocation: UnifiedToolInvocation,
    tool: UnifiedToolDefinition,
) -> CapabilityRequest:
    paths = extract_invocation_paths(invocation.arguments, project_path=invocation.project_path)
    network_domain = invocation.metadata.get("networkDomain")
    return CapabilityRequest(
        capability="tool",
        provider_id=tool.provider_id,
        tool_id=invocation.tool_id,
        operation=str(invocation.arguments.get("operation") or ""),
        read_roots=[path.path for path in paths if path.kind == "read"],
        write_roots=[path.path for path in paths if path.kind == "write"],
        network_domains=[str(network_domain)] if network_domain else [],
        runtime_budget_ms=tool.timeout_ms,
        reason=f"Invoke {invocation.tool_id}",
    )
```

- [ ] **Step 5.4: Enforce network domain presence for network tools**

Modify `authorize_tool_invocation()` so tools with `network` permission or safety policy `network != "none"` must either:

- provide `invocation.metadata["networkDomain"]` and have it approved, or
- return `network_domain_required`.

Keep non-network tools unchanged.

- [ ] **Step 5.5: Apply runtime budget timeout metadata**

Modify `UnifiedToolGateway.call_tool()` so effective budget is:

```python
min(value for value in [authority_context.runtime_budget_ms, tool.timeout_ms] if value is not None)
```

Add it to observation metadata. Do not implement cross-provider cancellation in this phase.

- [ ] **Step 5.6: Add security eval cases**

Append to `python/evals/security_cases.jsonl`:

```json
{"case_id":"security-authority-network-domain-required","category":"security","input":{"kind":"authority","permissions":["network"],"requested_permissions":["network"],"approved_permissions":["network"],"arguments":{"operation":"fetch"}},"expected":{"ok":false,"authorityCode":"network_domain_required"},"tags":["authority","capability"]}
{"case_id":"security-authority-network-domain-approved","category":"security","input":{"kind":"authority","permissions":["network"],"requested_permissions":["network"],"approved_permissions":["network"],"context_network_domains":["docs.example.com"],"metadata":{"networkDomain":"docs.example.com"},"arguments":{"operation":"fetch"}},"expected":{"ok":true,"authorityCode":"allowed"},"tags":["authority","capability"]}
```

Update eval harness authority case to accept `metadata` and `context_network_domains`.

- [ ] **Step 5.7: Run Phase 5 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_authority.py tests/test_tool_gateway.py tests/test_eval_harness.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected:

```text
authority/gateway/eval tests pass
Agent eval passes with the new security cases included
git diff --check exits 0
```

- [ ] **Step 5.8: Update progress tracker**

Set Phase 5 to complete. Set Phase 6 to `in_progress`.

## Phase 6: Schema DAG Tool Planner

**Files:**
- Create: `python/agent_service/tool_graph_planner.py`
- Modify: `python/agent_service/tool_catalog_planner.py`
- Modify: `python/agent_service/planner_chain.py`
- Modify: `python/evals/planner_cases.jsonl`
- Test: `python/tests/test_tool_graph_planner.py`
- Test: `python/tests/test_tool_catalog_planner.py`
- Test: `python/tests/test_planner_chain.py`

- [ ] **Step 6.1: Write graph verifier tests**

Create `python/tests/test_tool_graph_planner.py`:

```python
from agent_service.tool_graph_planner import (
    PlannedToolNode,
    ToolActionGraph,
    validate_tool_action_graph,
)


def test_tool_action_graph_requires_dependency_outputs_for_mappings():
    graph = ToolActionGraph(
        nodes=[
            PlannedToolNode(
                node_id="extract",
                tool_id="internal:document.read",
                operation="read",
                arguments={"input_paths": ["a.docx"], "output_path": "artifacts/a.md"},
                output_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            ),
            PlannedToolNode(
                node_id="report",
                tool_id="internal:test.echo_values",
                operation="echo_values",
                arguments={"source_text": "{extract.text}"},
                dependencies=["extract"],
                required_arguments=["source_text"],
            ),
        ]
    )

    diagnostics = validate_tool_action_graph(graph)

    assert diagnostics == []


def test_tool_action_graph_reports_missing_required_argument():
    graph = ToolActionGraph(
        nodes=[
            PlannedToolNode(
                node_id="report",
                tool_id="internal:test.echo_values",
                operation="echo_values",
                arguments={},
                required_arguments=["source_text"],
            )
        ]
    )

    diagnostics = validate_tool_action_graph(graph)

    assert diagnostics == ["node report missing required argument: source_text"]
```

- [ ] **Step 6.2: Run graph planner tests to verify RED**

Run:

```powershell
Push-Location python; python -m pytest tests/test_tool_graph_planner.py -q; Pop-Location
```

Expected:

```text
FAIL with ModuleNotFoundError for agent_service.tool_graph_planner
```

- [ ] **Step 6.3: Implement graph planner models and validator**

Create `python/agent_service/tool_graph_planner.py`:

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlannedToolNode(BaseModel):
    node_id: str
    tool_id: str
    operation: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    required_arguments: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(default_factory=dict)


class ToolActionGraph(BaseModel):
    nodes: list[PlannedToolNode]


def validate_tool_action_graph(graph: ToolActionGraph) -> list[str]:
    diagnostics: list[str] = []
    known = {node.node_id for node in graph.nodes}
    for node in graph.nodes:
        for dependency in node.dependencies:
            if dependency not in known:
                diagnostics.append(f"node {node.node_id} depends on missing node: {dependency}")
        for argument in node.required_arguments:
            value = node.arguments.get(argument)
            if value is None or value == "":
                diagnostics.append(f"node {node.node_id} missing required argument: {argument}")
    return diagnostics
```

- [ ] **Step 6.4: Integrate validator into ToolCatalogPlanner**

Before returning graph payload, create a `ToolActionGraph` with the selected fixed tool node. If diagnostics are non-empty, return `ToolCatalogPlanningResult(planned=False, diagnostics=diagnostics)`.

- [ ] **Step 6.5: Add limited two-tool chaining**

In `ToolCatalogPlanner`, if the top two selected tools are schema-compatible:

- first output schema has property `text`;
- second required argument is one of `source_text`, `text`, or `input`;
- both tools are selected by capability retrieval;

then generate two `fixed_tool` nodes with dependency and a rendered argument template of `{first_node_id}.text`.

Keep single-tool behavior unchanged for existing tests.

- [ ] **Step 6.6: Add planner eval case**

Append a planner case that expects a graph containing two fixed tool node ids for a synthetic multi-tool request. Use existing test tools only; do not require real files.

- [ ] **Step 6.7: Run Phase 6 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_tool_graph_planner.py tests/test_tool_catalog_planner.py tests/test_planner_chain.py tests/test_eval_harness.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected:

```text
tool graph planner and existing planner tests pass
Agent eval passes
git diff --check exits 0
```

- [ ] **Step 6.8: Update progress tracker**

Set Phase 6 to complete. Set Phase 7 to `in_progress`.

## Phase 7: Runtime ActionGraph Bridge

**Files:**
- Create: `python/agent_service/action_graph.py`
- Modify: `python/agent_service/execution_graph.py`
- Modify: `python/agent_service/execution.py`
- Test: `python/tests/test_action_graph.py`
- Test: `python/tests/test_execution_graph.py`
- Test: `python/tests/test_execution.py`

- [ ] **Step 7.1: Write action graph compilation tests**

Create `python/tests/test_action_graph.py`:

```python
from agent_service.action_graph import action_graph_from_run_graph
from agent_service.schemas import RunGraph


def test_action_graph_from_run_graph_maps_fixed_tool_model_and_output_nodes():
    graph = RunGraph(
        graphId="graph-1",
        nodes=[
            {
                "nodeId": "tool-a",
                "nodeType": "fixed_tool",
                "displayName": "Tool A",
                "status": "waiting",
                "toolRef": "internal:test.echo_values",
                "summary": "Echo values.",
                "createdBy": "agent",
                "position": {"x": 0, "y": 0},
            },
            {
                "nodeId": "output",
                "nodeType": "output",
                "displayName": "Output",
                "status": "waiting",
                "dependencies": ["tool-a"],
                "summary": "Final output.",
                "createdBy": "agent",
                "position": {"x": 100, "y": 0},
            },
        ],
        edges=[],
    )

    action_graph = action_graph_from_run_graph(graph)

    assert [action.action_id for action in action_graph.actions] == ["tool-a", "output"]
    assert action_graph.actions[0].action_type == "tool"
    assert action_graph.actions[1].action_type == "control"
```

- [ ] **Step 7.2: Run action graph tests to verify RED**

Run:

```powershell
Push-Location python; python -m pytest tests/test_action_graph.py -q; Pop-Location
```

Expected:

```text
FAIL with ModuleNotFoundError for agent_service.action_graph
```

- [ ] **Step 7.3: Implement action graph bridge**

Create `python/agent_service/action_graph.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field

from agent_service.runtime_state import RuntimeAction
from agent_service.schemas import RunGraph


class RuntimeActionGraph(BaseModel):
    graph_id: str
    actions: list[RuntimeAction] = Field(default_factory=list)


def action_graph_from_run_graph(graph: RunGraph) -> RuntimeActionGraph:
    actions: list[RuntimeAction] = []
    for node in graph.nodes:
        if node.nodeType == "fixed_tool":
            action_type = "tool"
            name = node.toolRef or node.nodeId
        elif node.nodeType == "model":
            action_type = "model"
            name = node.modelRef or node.nodeId
        elif node.nodeType == "output":
            action_type = "control"
            name = node.nodeId
        else:
            action_type = "control"
            name = node.nodeId
        actions.append(
            RuntimeAction(
                action_id=node.nodeId,
                action_type=action_type,
                name=name,
                dependencies=list(node.dependencies),
                permissions=[{"permission": permission} for permission in node.permissionsRequired],
            )
        )
    return RuntimeActionGraph(graph_id=graph.graphId, actions=actions)
```

- [ ] **Step 7.4: Attach action graph metadata during execution graph compile**

Modify `compile_execution_graph()` to include metadata:

```python
metadata={**dict(request.graph.metadata), "actionGraphVersion": "runtime_action_graph.v1"}
```

Do not remove legacy `DocumentFlowExecutor` in this phase; use the action graph as an inspectable bridge.

- [ ] **Step 7.5: Run Phase 7 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_action_graph.py tests/test_execution_graph.py tests/test_execution.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected:

```text
action graph, execution graph, and execution tests pass
Agent eval passes
git diff --check exits 0
```

- [ ] **Step 7.6: Update progress tracker**

Set Phase 7 to complete. Set Phase 8 to `in_progress`.

## Phase 8: MCP End-To-End Minimal Path

**Files:**
- Create: `python/agent_service/mcp_client_factory.py`
- Modify: `python/agent_service/tool_providers/mcp.py`
- Modify: `python/agent_service/tool_gateway.py`
- Modify: `src-tauri/src/agent_client.rs`
- Modify: `src-tauri/src/commands.rs`
- Test: `python/tests/test_mcp_client_factory.py`
- Test: `python/tests/test_mcp_tool_provider.py`
- Test: `python/tests/test_tool_gateway.py`
- Test: `src-tauri/tests/tool_provider_commands_tests.rs`

- [ ] **Step 8.1: Write MCP client factory tests**

Create `python/tests/test_mcp_client_factory.py`:

```python
from agent_service.mcp_client_factory import create_mcp_client
from agent_service.tool_providers.mcp import McpProviderConfig


def test_create_mcp_client_rejects_missing_stdio_command():
    config = McpProviderConfig(provider_id="docs", display_name="Docs", transport="stdio")

    client = create_mcp_client(config)

    assert client.health()["ok"] is False
    assert client.health()["errorCode"] == "missing_command"


def test_create_mcp_client_rejects_missing_http_url():
    config = McpProviderConfig(provider_id="docs", display_name="Docs", transport="http")

    client = create_mcp_client(config)

    assert client.health()["ok"] is False
    assert client.health()["errorCode"] == "missing_url"
```

- [ ] **Step 8.2: Run MCP factory tests to verify RED**

Run:

```powershell
Push-Location python; python -m pytest tests/test_mcp_client_factory.py -q; Pop-Location
```

Expected:

```text
FAIL with ModuleNotFoundError for agent_service.mcp_client_factory
```

- [ ] **Step 8.3: Implement safe minimal client factory**

Create `python/agent_service/mcp_client_factory.py`:

```python
from __future__ import annotations

from typing import Any

from agent_service.tool_providers.mcp import McpProviderConfig, McpToolSpec


class UnavailableMcpClient:
    def __init__(self, *, error_code: str, message: str) -> None:
        self.error_code = error_code
        self.message = message

    def list_tools(self) -> list[McpToolSpec]:
        return []

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"isError": True, "content": [{"type": "text", "text": self.message}]}

    def health(self) -> dict[str, Any]:
        return {"ok": False, "errorCode": self.error_code, "message": self.message}


def create_mcp_client(config: McpProviderConfig):
    if config.transport == "stdio" and not config.command:
        return UnavailableMcpClient(error_code="missing_command", message="MCP stdio command is required")
    if config.transport == "http" and not config.url:
        return UnavailableMcpClient(error_code="missing_url", message="MCP HTTP URL is required")
    return UnavailableMcpClient(error_code="unsupported_transport_runtime", message="Real MCP client runtime is not enabled yet")
```

This phase creates the factory seam and explicit health behavior. It does not launch external processes yet.

- [ ] **Step 8.4: Wire factory into default gateway helper**

Add optional use of `create_mcp_client` in testable gateway construction when configs are supplied and no custom factory is provided. Keep production call paths conservative by returning health/status tools only until credentials and process supervision are implemented.

- [ ] **Step 8.5: Improve Rust refresh output**

Modify `refresh_mcp_tool_provider_tools_for_preferences()` so it reports transport-aware status:

```rust
description: format!("Configured MCP {transport} provider connectivity check.")
```

Keep returning the synthetic status tool until Python sidecar MCP discovery is connected to Tauri.

- [ ] **Step 8.6: Run Phase 8 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_mcp_client_factory.py tests/test_mcp_tool_provider.py tests/test_tool_gateway.py -q; Pop-Location
cargo test --manifest-path src-tauri/Cargo.toml --test tool_provider_commands_tests
git diff --check
```

Expected:

```text
MCP Python tests pass
Rust tool provider command tests pass
git diff --check exits 0
```

- [ ] **Step 8.7: Update progress tracker**

Set Phase 8 to complete. Set Phase 9 to `in_progress`.

## Phase 9: Trace Store And Span Taxonomy

**Files:**
- Create: `python/agent_service/trace_store.py`
- Modify: `python/agent_service/runtime_trace.py`
- Modify: `python/agent_service/execution.py`
- Modify: `src/shared/events.ts`
- Modify: `src/features/task/useGraphRuntimeController.ts`
- Test: `python/tests/test_runtime_trace.py`
- Test: `python/tests/test_trace_store.py`
- Test: `python/tests/test_execution.py`
- Test: `src/features/task/useGraphRuntimeController.test.ts`

- [ ] **Step 9.1: Write trace store tests**

Create `python/tests/test_trace_store.py`:

```python
from agent_service.runtime_trace import RuntimeSpan
from agent_service.trace_store import TraceStore


def test_trace_store_appends_and_lists_spans(tmp_path):
    store = TraceStore(project_path=str(tmp_path / "demo.alita"), run_id="run-1")
    span = RuntimeSpan(
        trace_id="trace-run-1",
        span_id="span-000001",
        parent_span_id=None,
        run_id="run-1",
        node_id="node-a",
        kind="tool.call",
        name="internal:test.echo_values",
        status="ok",
        started_at="2026-05-30T00:00:00Z",
        ended_at="2026-05-30T00:00:01Z",
        duration_ms=1000,
    )

    store.append_span(span)

    assert store.list_spans()[0]["kind"] == "tool.call"
    assert store.list_spans()[0]["spanId"] == "span-000001"
```

- [ ] **Step 9.2: Run trace store tests to verify RED**

Run:

```powershell
Push-Location python; python -m pytest tests/test_trace_store.py -q; Pop-Location
```

Expected:

```text
FAIL with ModuleNotFoundError for agent_service.trace_store
```

- [ ] **Step 9.3: Implement trace store**

Create `python/agent_service/trace_store.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_service.runtime_trace import RuntimeSpan


class TraceStore:
    def __init__(self, *, project_path: str, run_id: str) -> None:
        self.base_dir = Path(project_path).parent / "node-runs" / run_id
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.trace_path = self.base_dir / "trace.jsonl"

    def append_span(self, span: RuntimeSpan) -> None:
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(span.to_record(), ensure_ascii=False) + "\n")

    def list_spans(self) -> list[dict[str, Any]]:
        if not self.trace_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.trace_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
```

- [ ] **Step 9.4: Normalize span taxonomy**

Update span kind values in execution:

- node execution success/failure remains `runtime.node`.
- tool gateway observations map to `tool.call` when a span is created later.
- checkpoint write helper can produce `checkpoint.write` in future phases.

Keep existing tests compatible by allowing old kind in assertions where needed.

- [ ] **Step 9.5: Persist node spans**

In `run_graph_events()`, after creating each `RuntimeSpan`, append it to `TraceStore(project_path=request.project_path, run_id=request.run_id)` before emitting the event.

- [ ] **Step 9.6: Run Phase 9 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_runtime_trace.py tests/test_trace_store.py tests/test_execution.py -q; Pop-Location
npm run frontend:test -- src/features/task/useGraphRuntimeController.test.ts
npm run agent:eval
git diff --check
```

Expected:

```text
trace and execution tests pass
frontend runtime controller tests pass
Agent eval passes
git diff --check exits 0
```

- [ ] **Step 9.7: Update progress tracker**

Set Phase 9 to complete. Set Phase 10 to `in_progress`.

## Phase 10: Memory V2 Retrieval

**Files:**
- Modify: `python/agent_service/memory_store.py`
- Modify: `python/agent_service/context_policy.py`
- Modify: `python/agent_service/context_manager.py`
- Test: `python/tests/test_memory_store.py`
- Test: `python/tests/test_context_manager.py`
- Test: `python/tests/test_graph.py`

- [ ] **Step 10.1: Write memory v2 tests**

Add to `python/tests/test_memory_store.py`:

```python
from agent_service.memory_store import MemoryRecord, MemoryStore
from agent_service.context_policy import budget_for_mode, select_memory_for_context


def test_memory_record_v2_defaults_are_backward_compatible():
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


def test_memory_selection_prefers_relevant_high_importance_records():
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
```

- [ ] **Step 10.2: Run memory tests to verify RED**

Run:

```powershell
Push-Location python; python -m pytest tests/test_memory_store.py::test_memory_record_v2_defaults_are_backward_compatible tests/test_memory_store.py::test_memory_selection_prefers_relevant_high_importance_records -q; Pop-Location
```

Expected:

```text
FAIL because MemoryRecord lacks v2 fields and select_memory_for_context lacks query argument
```

- [ ] **Step 10.3: Extend MemoryRecord**

Modify `MemoryRecord`:

```python
schema_version: int = 2
source_type: str = "run"
updated_at: str | None = None
last_used_at: str | None = None
expires_at: str | None = None
importance: float = 0.5
confidence: float = 0.8
visibility: Literal["private", "project", "global"] = "project"
```

Keep existing JSONL records readable by providing defaults.

- [ ] **Step 10.4: Add deterministic retrieval scorer**

Modify `select_memory_for_context()` to accept `query: str = ""`. Score eligible records by:

```text
term overlap * 3 + importance * 2 + confidence + preference boost + recency tie-break
```

Keep existing max record and char budget behavior.

- [ ] **Step 10.5: Pass query from context manager**

In `build_context_bundle()`, call:

```python
selected_memory = select_memory_for_context(memory_records or [], budget, query=message.content)
```

- [ ] **Step 10.6: Run Phase 10 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_memory_store.py tests/test_context_manager.py tests/test_graph.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected:

```text
memory/context/graph tests pass
Agent eval passes
git diff --check exits 0
```

- [ ] **Step 10.7: Update progress tracker**

Set Phase 10 to complete. Set Phase 11 to `in_progress`.

## Phase 11: Final Docs And Full Gate

**Files:**
- Modify: `README.md`
- Modify: `docs/agent-development-optimization-2026-05-30-v033.md`
- Modify: `docs/superpowers/progress/2026-05-30-agent-runtime-mainline-v033-progress.md`

- [ ] **Step 11.1: Update optimization document with implementation results**

Append a section to `docs/agent-development-optimization-2026-05-30-v033.md`:

```markdown
## 19. Agent Runtime Mainline 实施结果

本轮实施完成了 runtime state/action/delta、AgentRuntimeEngine facade、checkpoint v2、mock model-loop eval、CI gate、capability request/grant、schema DAG planner、ActionGraph bridge、MCP client factory seam、TraceStore、Memory v2 retrieval。

仍未宣称完成的能力：

- 生产级 MCP stdio/http supervisor 和 credential broker。
- OS 级 sandbox 隔离。
- 完整多 Agent team runtime。
- 真实模型 benchmark 的 CI 门禁。
```

- [ ] **Step 11.2: Update README limitations**

In `README.md`, add accurate wording:

```markdown
- Agent Runtime Mainline 已具备 state/action/delta、engine facade、checkpoint v2、trace store 和 memory v2 retrieval；默认自治循环仍按阶段接入，生产级 MCP supervisor、强沙箱和多 Agent team 仍是后续路线。
```

- [ ] **Step 11.3: Run full gate**

Run:

```powershell
git diff --check
npm run agent:eval
Push-Location python; python -m pytest -q; Pop-Location
npm run frontend:typecheck
npm run frontend:test
cargo test --manifest-path src-tauri/Cargo.toml
```

Expected:

```text
git diff --check exits 0
Agent eval passes
Python pytest passes
frontend typecheck exits 0
frontend tests pass
Rust tests pass
```

- [ ] **Step 11.4: Final progress update**

Set every phase to `complete` and append the exact command evidence from Step 11.3. Record residual risks exactly:

```markdown
Residual risks:

- MCP client factory has health/error seams; production process supervisor and credential broker are not yet implemented.
- Sandbox remains constrained subprocess runner, not OS isolation.
- Multi-agent team runtime remains out of scope until single-agent runtime mainline is stable.
- Real model benchmark is opt-in and not a blocking PR gate.
```

- [ ] **Step 11.5: Final review**

Run:

```powershell
git status --short
git diff --stat
Select-String -Path docs/superpowers/plans/2026-05-30-agent-runtime-mainline-v033-implementation-plan.md,docs/superpowers/progress/2026-05-30-agent-runtime-mainline-v033-progress.md -Pattern 'T[B]D|TO[D]O|f[i]ll in|implement la[t]er' -CaseSensitive:$false
```

Expected:

```text
Only intended source, test, eval, workflow, and documentation files are modified.
Select-String returns no matches.
```

## Out Of Scope Until A Later Plan

- Replacing the existing graph UI with a new UI-first runtime timeline.
- Production-grade MCP process supervisor with credentials and reconnect.
- OS-level sandbox enforcement through AppContainer, Docker, WSL, or low-privilege worker users.
- Real model benchmark as a required PR gate.
- Multi-Agent teams, role handoff, team memory, and team-level termination protocols.
