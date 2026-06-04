# Execute, Verify, Repair Phase 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute a confirmed `AgentCompiledGraph`, verify the result, and surface bounded repair or final events inside the Deep Agent Runtime.

**Architecture:** Add a narrow Agent execution bridge over the existing `run_graph_events()` executor, then wire it into `deep_agent_runtime_graph.py` after `execution_ready`. Execution remains provenance-gated by `AgentCompiledGraph`; low-level run events are forwarded, while new Agent-level events summarize execution, verification, repair, and final status.

**Tech Stack:** Python 3.12, LangGraph `StateGraph`, Pydantic v2, existing `run_graph_events()` execution runtime, pytest, TypeScript event contracts, Vitest.

---

## Scope

This plan implements the first complete Phase 5 slice:

```text
AgentCompiledGraph(execution_ready)
  -> execute through run_graph_events()
  -> deterministic Agent-level verification
  -> final / failed / interrupted / repair proposed
```

It does not add model-adjudicated quality review or full plan regeneration.

## File Structure

Create:

- `python/agent_service/agent_execution_runtime.py`
  Agent-level execution models, provenance validation, `RunGraphRequest` bridge,
  event summarization, and deterministic execution review.

- `python/tests/test_agent_execution_runtime.py`
  Unit tests for bridge validation, event summarization, review, and legacy graph
  rejection.

Modify:

- `python/agent_service/deep_agent_runtime_graph.py`
  Add execution nodes after `execution_ready`.

- `python/agent_service/deep_agent_runtime_models.py`
  Add persisted execution result/review models if aliases are needed for API
  summaries.

- `python/tests/test_deep_agent_runtime_resume.py`
  Add confirmation-to-execution tests with injected fake executor events.

- `src/shared/events.ts`
  Add Agent execution event contracts.

- `src/app/backendEvents.ts`
  Reduce Agent execution events into visible messages and run state.

- `src/app/backendEvents.test.ts`
  Add reducer tests for started, completed, failed, repair, and final events.

## Task 1: Agent Execution Runtime Models And Bridge

**Files:**

- Create: `python/agent_service/agent_execution_runtime.py`
- Create: `python/tests/test_agent_execution_runtime.py`

- [ ] **Step 1: Write failing bridge tests**

Create `python/tests/test_agent_execution_runtime.py` with tests covering:

```python
def test_execution_bridge_rejects_non_execution_ready_compiled_graph() -> None:
    ...


def test_execution_bridge_rejects_legacy_generated_graph() -> None:
    ...


def test_execution_bridge_builds_run_graph_request_from_agent_compiled_graph() -> None:
    ...
```

Use helpers from `python/tests/test_agent_plan_compile.py` where possible, but do
not import private test-only state from unrelated modules if it makes the tests
hard to read.

- [ ] **Step 2: Run failing tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_agent_execution_runtime.py -q
Pop-Location
```

Expected: fail because `agent_service.agent_execution_runtime` does not exist.

- [ ] **Step 3: Implement models and request bridge**

Add `agent_execution_runtime.py` with:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_service.agent_plan_compile import AgentCompiledGraph
from agent_service.harness_errors import HarnessError
from agent_service.schemas import AgentEvent, RunGraph, RunGraphRequest


class AgentExecutionIssue(BaseModel):
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    node_id: str | None = None


class AgentExecutionRunResult(BaseModel):
    status: Literal["completed", "failed", "interrupted"]
    task_id: str
    run_id: str
    thread_id: str
    compile_id: str
    graph_id: str
    completed_node_ids: list[str] = Field(default_factory=list)
    failed_node_id: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    checkpoint_ids: list[str] = Field(default_factory=list)
    recovery_actions: list[dict[str, Any]] = Field(default_factory=list)
    final_message: str | None = None
    raw_events: list[AgentEvent] = Field(default_factory=list)


class AgentExecutionReview(BaseModel):
    status: Literal["approved", "failed", "needs_repair"]
    is_valid: bool
    issues: list[AgentExecutionIssue] = Field(default_factory=list)
    final_artifacts: list[str] = Field(default_factory=list)
    repair_required: bool = False


def run_graph_request_from_agent_compiled_graph(
    compiled_graph: AgentCompiledGraph,
    *,
    project_path: str,
) -> RunGraphRequest:
    if compiled_graph.status != "execution_ready":
        raise HarnessError(
            "agent_compiled_graph_not_execution_ready",
            "Agent compiled graph is not execution_ready.",
        )
    if compiled_graph.metadata.get("generatedBy") != "deep_agent_runtime":
        raise HarnessError(
            "invalid_agent_execution_provenance",
            "Agent execution requires a deep_agent_runtime compiled graph.",
        )
    for node in compiled_graph.nodes:
        if not node.source_plan_step_id:
            raise HarnessError(
                "missing_agent_execution_provenance",
                f"compiled node lacks source plan step: {node.node_id}",
            )
    return RunGraphRequest(
        task_id=compiled_graph.task_id,
        project_path=project_path,
        graph=_run_graph_from_compiled_graph(compiled_graph),
        run_id=compiled_graph.run_id,
    )
```

Add the narrow converter in this file:

```python
def _run_graph_from_compiled_graph(compiled_graph: AgentCompiledGraph) -> RunGraph:
    public_nodes = [
        execution_node.public_node
        for execution_node in compiled_graph.execution_graph.nodes
    ]
    return RunGraph(
        graphId=compiled_graph.source_graph_id,
        nodes=public_nodes,
        edges=list(compiled_graph.edges),
        metadata=dict(compiled_graph.metadata),
    )
```

`RuntimeActionGraph` is not reversible by itself; do not call a nonexistent
`to_run_graph()` API.

- [ ] **Step 4: Implement event summarization**

Add:

```python
def summarize_agent_execution_events(
    compiled_graph: AgentCompiledGraph,
    events: list[AgentEvent],
) -> AgentExecutionRunResult:
    ...
```

Rules:

- `task.completed` -> status `completed`
- `task.failed` -> status `failed`
- `node.needs_permission`, `runtime.interrupted`, or permission failure code ->
  status `interrupted`
- collect `node.completed` node IDs
- collect `checkpoint_recorded` checkpoint IDs
- collect `recovery.action_proposed` payloads
- collect artifact refs from `task.completed`

- [ ] **Step 5: Run bridge tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_agent_execution_runtime.py -q
Pop-Location
```

Expected: tests pass.

## Task 2: Agent-Level Execution Verification

**Files:**

- Modify: `python/agent_service/agent_execution_runtime.py`
- Modify: `python/tests/test_agent_execution_runtime.py`

- [ ] **Step 1: Add failing review tests**

Add tests:

```python
def test_execution_review_approves_completed_result_with_expected_artifact() -> None:
    ...


def test_execution_review_requires_repair_for_recovery_suggestion() -> None:
    ...


def test_execution_review_fails_when_expected_artifact_missing() -> None:
    ...
```

- [ ] **Step 2: Implement deterministic review**

Add:

```python
def review_agent_execution_result(
    compiled_graph: AgentCompiledGraph,
    result: AgentExecutionRunResult,
) -> AgentExecutionReview:
    ...
```

Rules:

- failed result with recovery actions -> `needs_repair`
- failed result without recovery actions -> `failed`
- completed result missing expected artifact paths -> `failed`
- completed result with required artifacts -> `approved`

- [ ] **Step 3: Run review tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_agent_execution_runtime.py -q
Pop-Location
```

Expected: tests pass.

## Task 3: Wire Execution Into Deep Agent Runtime Graph

**Files:**

- Modify: `python/agent_service/deep_agent_runtime_graph.py`
- Modify: `python/tests/test_deep_agent_runtime_resume.py`

- [ ] **Step 1: Add failing graph tests**

Add tests proving:

```python
def test_confirmed_execution_ready_graph_runs_agent_execution_node() -> None:
    ...


def test_agent_execution_failure_records_failed_terminal_state() -> None:
    ...
```

Use injected fake execution event runner so tests do not execute real tools.

- [ ] **Step 2: Add runtime state fields**

Extend `DeepAgentRuntimeState` and `_runtime_invoke_input()` with:

```python
agent_execution_result: dict[str, Any] | None
agent_execution_review: dict[str, Any] | None
execution_failure: dict[str, Any] | None
execution_repair_plan: dict[str, Any] | None
execution_repair_count: int
```

- [ ] **Step 3: Add graph nodes**

Add nodes:

```python
execute_agent_compiled_graph
verify_agent_execution_result
agent_execution_final
agent_execution_failed
agent_execution_interrupted
```

Route:

```text
execution_ready -> execute_agent_compiled_graph
execute_agent_compiled_graph -> verify_agent_execution_result
verify_agent_execution_result -> final / failed / interrupted
```

- [ ] **Step 4: Preserve test-only no-execute path if needed**

If existing tests expect `execution_ready` to terminate, add a runtime flag:

```python
execute_after_compile: bool = True
```

Use `False` only in tests that explicitly assert compile-only behavior.

- [ ] **Step 5: Run runtime tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_deep_agent_runtime_resume.py tests/test_deep_agent_runtime_graph.py tests/test_agent_execution_runtime.py -q
Pop-Location
```

Expected: tests pass.

## Task 4: Backend Event Contracts

**Files:**

- Modify: `src/shared/events.ts`
- Modify: `src/app/backendEvents.ts`
- Modify: `src/app/backendEvents.test.ts`

- [ ] **Step 1: Add shared event types**

Add:

```ts
| { type: "agent_execution.started"; payload: { taskId: string; runId: string; threadId: string; compileId: string; graphId: string } }
| { type: "agent_execution.completed"; payload: { taskId: string; runId: string; threadId: string; compileId: string; artifactRefs: string[] } }
| { type: "agent_execution.verify_completed"; payload: { taskId: string; runId: string; threadId: string; status: "approved" | "failed" | "needs_repair"; issues: unknown[] } }
| { type: "agent_execution.repair_proposed"; payload: { taskId: string; runId: string; threadId: string; actions: unknown[] } }
| { type: "agent_execution.interrupted"; payload: { taskId: string; runId: string; threadId: string; reason: string } }
| { type: "agent_execution.failed"; payload: { taskId: string; runId: string; threadId: string; reason: string; errorCode?: string } }
| { type: "agent_execution.final"; payload: { taskId: string; runId: string; threadId: string; message: string; artifactRefs: string[] } }
```

- [ ] **Step 2: Add reducer tests**

Add tests for execution started, final, failed, and repair proposed messages.

- [ ] **Step 3: Add reducer handling**

Show concise Chinese assistant messages and keep compile status unchanged after
execution starts.

- [ ] **Step 4: Run frontend tests**

Run:

```powershell
npm run frontend:test -- src/app/backendEvents.test.ts src/features/task/useTaskEvents.test.ts
npm run frontend:typecheck
```

Expected: tests and typecheck pass.

## Task 5: Regression Gates

**Files:**

- No source edits expected unless tests reveal a real regression.

- [ ] **Step 1: Run Python target tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_agent_execution_runtime.py tests/test_agent_runtime_engine.py tests/test_agent_runtime_engine_deep_agent.py tests/test_deep_agent_runtime_graph.py tests/test_deep_agent_runtime_resume.py tests/test_agent_plan_compile.py -q
Pop-Location
```

Expected: all selected Python tests pass.

- [ ] **Step 2: Run frontend target tests**

Run:

```powershell
npm run frontend:test -- src/app/backendEvents.test.ts src/features/task/useTaskEvents.test.ts src/features/task/useGraphRunController.test.ts
```

Expected: all selected frontend tests pass.

- [ ] **Step 3: Run typecheck**

Run:

```powershell
npm run frontend:typecheck
```

Expected: no TypeScript errors.

- [ ] **Step 4: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected: no whitespace errors. CRLF warnings are acceptable if no whitespace
errors are reported.

## Definition Of Done

Phase 5 is complete only when:

- execution starts from `AgentCompiledGraph` with `status="execution_ready"`;
- legacy/template graphs are rejected by the execution bridge;
- low-level `run_graph_events()` output is streamed and summarized into
  Agent-level execution events;
- result verification emits approved, failed, or repair-required review;
- recoverable failures produce bounded repair suggestions;
- interrupted permission/input paths do not pretend success;
- target backend and frontend tests pass.
