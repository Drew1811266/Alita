# Replace Legacy Task Product Path Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the implicit legacy task graph fallback from the Agent Runtime product path while preserving temporary response-only handling for simple requests.

**Architecture:** Add an explicit Deep Agent product-path classifier in `AgentRuntimeEngine`, guard any temporary legacy response delegation from emitting graph events, and block manual plan-stage legacy graph creation by default. The Deep Agent LangGraph remains the source of truth for graph-task planning, confirmation, compile, interrupts, and failures.

**Tech Stack:** Python 3.12, LangGraph `StateGraph`, Pydantic v2, FastAPI SSE event contracts, React/TypeScript event reducers, pytest, Vitest.

---

## Official Guidance To Keep In Scope

Review these official LangGraph docs before implementation:

- Graph API and `StateGraph`: `https://docs.langchain.com/oss/python/langgraph/graph-api`
- Persistence: `https://docs.langchain.com/oss/python/langgraph/persistence`
- Interrupts: `https://docs.langchain.com/oss/python/langgraph/interrupts`
- Streaming: `https://docs.langchain.com/oss/python/langgraph/streaming`

Implementation constraints:

- Do not replace LangGraph runtime state with UI-invented status.
- Do not synthesize a graph after a Deep Agent failure.
- Do not use legacy task planner as a hidden fallback when Deep Agent planning
  fails or emits an incomplete graph-task event stream.

## File Structure

Modify:

- `python/agent_service/agent_runtime_engine.py`
  Add product-path classification, graph-blocking guard, blocked event helpers,
  and default-disabled legacy plan stepping.

- `python/tests/test_agent_runtime_engine_deep_agent.py`
  Add Deep Agent product-path regression tests.

- `python/tests/test_agent_runtime_engine.py`
  Update existing legacy step tests to use explicit migration opt-in, and add a
  default blocked-path test.

- `src/shared/events.ts`
  Add `runtime.legacy_graph_blocked` to the typed backend event union.

- `src/app/backendEvents.ts`
  Surface a concise message for blocked legacy graph fallback and clear graph
  execution state as failed.

- `src/app/backendEvents.test.ts`
  Add reducer coverage for the new blocked event.

Do not modify:

- `python/agent_service/task_planner.py`
- `python/agent_service/planner_chain.py`
- `python/agent_service/graph.py`
- `python/agent_service/execution.py`

These modules can remain for migration helpers, old tests, and Phase 5 execution
composition, but Phase 4 must remove their implicit product fallback for graph
creation.

## Task 1: Add Failing Product Path Tests

**Files:**

- Modify: `python/tests/test_agent_runtime_engine_deep_agent.py`

- [ ] **Step 1: Add tests for blocked legacy graph fallback**

Append these tests to `python/tests/test_agent_runtime_engine_deep_agent.py`:

```python
def test_deep_agent_incomplete_graph_task_stream_does_not_fall_back_to_legacy_graph() -> None:
    legacy_calls: list[AgentRunState] = []

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        return [
            AgentEvent(
                type="node_graph.created",
                payload={
                    "graph": {
                        "graphId": "legacy-graph",
                        "nodes": [],
                        "edges": [],
                        "metadata": {"plannerChain": {"strategy": "legacy_task_planner"}},
                    }
                },
            )
        ]

    def incomplete_deep_runtime(message: UserMessage, **kwargs):
        del message, kwargs
        return [
            AgentEvent(
                type="reasoning.decision_created",
                payload={
                    "decision": {
                        "next_action": "deep_planning",
                        "complexity": "graph_task",
                    }
                },
            )
        ]

    engine = AgentRuntimeEngine(
        route_runner=legacy_runner,
        deep_runtime_runner=incomplete_deep_runtime,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-incomplete-deep-agent",
            content="Create a multi-step project analysis graph.",
        )
    ).model_copy(update={"project_path": "D:/Project/demo.alita", "run_id": "run-incomplete"})

    result = engine.run_from_state(run_state)

    assert legacy_calls == []
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "reasoning.decision_created",
        "runtime.deep_agent_product_path_blocked",
        "task.failed",
    ]
    failed = result.events[-1]
    assert failed.payload["errorCode"] == "deep_agent_product_path_incomplete"


def test_simple_answer_legacy_response_path_blocks_legacy_graph_events() -> None:
    legacy_calls: list[AgentRunState] = []

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        return [
            AgentEvent(
                type="node_graph.created",
                payload={
                    "graph": {
                        "graphId": "legacy-simple-graph",
                        "nodes": [],
                        "edges": [],
                        "metadata": {"plannerChain": {"strategy": "legacy_task_planner"}},
                    }
                },
            )
        ]

    model = FakeDeepModel([_reasoning_payload("simple_answer")])
    engine = AgentRuntimeEngine(route_runner=legacy_runner)
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="task-simple-block-graph", content="Say hello.")
    ).model_copy(update={"project_path": "D:/Project/demo.alita", "run_id": "run-simple-block"})

    result = engine.run_from_state(run_state, model_client=model)

    assert len(legacy_calls) == 1
    assert all(event.type != "node_graph.created" for event in result.events)
    assert result.events[-2].type == "runtime.legacy_graph_blocked"
    assert result.events[-1].type == "task.failed"
    assert result.events[-1].payload["errorCode"] == "legacy_graph_blocked"


def test_deep_agent_planning_failure_does_not_call_legacy_route_runner() -> None:
    legacy_calls: list[AgentRunState] = []

    def legacy_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        raise AssertionError("legacy route runner must not run after planning failure")

    def failing_deep_runtime(message: UserMessage, **kwargs):
        del kwargs
        return [
            AgentEvent(
                type="planning.failed",
                payload={
                    "taskId": message.task_id,
                    "runId": "run-planning-failed",
                    "threadId": "thread-planning-failed",
                    "errorCode": "deep_planning_unavailable",
                    "error": "model unavailable",
                },
            )
        ]

    engine = AgentRuntimeEngine(
        route_runner=legacy_runner,
        deep_runtime_runner=failing_deep_runtime,
    )
    run_state = AgentRunState.from_user_message(
        UserMessage(
            task_id="task-planning-failed",
            content="Build a detailed execution graph.",
        )
    ).model_copy(
        update={
            "project_path": "D:/Project/demo.alita",
            "run_id": "run-planning-failed",
            "thread_id": "thread-planning-failed",
        }
    )

    result = engine.run_from_state(run_state)

    assert legacy_calls == []
    assert result.events[-1].type == "planning.failed"
```

- [ ] **Step 2: Run the new tests and verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_agent_runtime_engine_deep_agent.py -q
Pop-Location
```

Expected before implementation:

- `test_deep_agent_incomplete_graph_task_stream_does_not_fall_back_to_legacy_graph`
  fails because legacy fallback currently runs.
- `test_simple_answer_legacy_response_path_blocks_legacy_graph_events` fails
  because legacy graph events are currently passed through.

## Task 2: Classify Deep Agent Product Path Outcomes

**Files:**

- Modify: `python/agent_service/agent_runtime_engine.py`
- Test: `python/tests/test_agent_runtime_engine_deep_agent.py`

- [ ] **Step 1: Add product-path decision types**

In `python/agent_service/agent_runtime_engine.py`, extend the imports:

```python
from typing import Any, Literal
```

Add this dataclass after the runner type aliases:

```python
@dataclass(frozen=True)
class DeepAgentProductPathDecision:
    kind: Literal["handled", "allow_legacy_response", "blocked"]
    reason: str
```

- [ ] **Step 2: Replace the old terminal helper with classifier**

Replace `_deep_agent_finished_without_legacy()` with:

```python
def _deep_agent_product_path_decision(
    events: list[AgentEvent],
) -> DeepAgentProductPathDecision:
    handled_event_types = {
        "node_graph.created",
        "planning.clarification_required",
        "planning.confirmation_required",
        "planning.interrupted",
        "planning.confirmed",
        "planning.cancelled",
        "planning.failed",
        "agent_plan_graph.compile_failed",
        "agent_plan_graph.execution_ready",
    }
    if any(event.type in handled_event_types for event in events):
        return DeepAgentProductPathDecision(
            kind="handled",
            reason="deep_agent_runtime_emitted_terminal_event",
        )

    for event in reversed(events):
        if event.type == "reasoning.completed":
            next_action = _event_next_action(event)
            if next_action in {"simple_answer", "tool_action", "bounded_tool"}:
                return DeepAgentProductPathDecision(
                    kind="allow_legacy_response",
                    reason=f"deep_agent_runtime_allowed_response_path:{next_action}",
                )
            return DeepAgentProductPathDecision(
                kind="blocked",
                reason=f"deep_agent_runtime_incomplete_for:{next_action or 'unknown'}",
            )
        if event.type == "reasoning.decision_created":
            next_action = _event_next_action(event)
            if next_action in {"deep_planning", "clarification"}:
                return DeepAgentProductPathDecision(
                    kind="blocked",
                    reason=f"deep_agent_runtime_missing_terminal_event:{next_action}",
                )

    return DeepAgentProductPathDecision(
        kind="blocked",
        reason="deep_agent_runtime_emitted_no_product_path_decision",
    )


def _event_next_action(event: AgentEvent) -> str:
    payload = event.payload if isinstance(event.payload, dict) else {}
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else payload
    return str(
        decision.get("nextAction")
        or decision.get("next_action")
        or decision.get("next_action".replace("_", ""))
        or ""
    )
```

- [ ] **Step 3: Add blocked product-path events**

Add these helpers below the classifier:

```python
def _deep_agent_product_path_blocked_events(
    state: RuntimeState,
    *,
    reason: str,
) -> list[AgentEvent]:
    payload = {
        "runId": state.run_id,
        "threadId": state.thread_id,
        "taskId": state.task_id,
        "reason": reason,
    }
    return [
        AgentEvent(
            type="runtime.deep_agent_product_path_blocked",
            payload=payload,
        ),
        AgentEvent(
            type="task.failed",
            payload={
                "taskId": state.task_id,
                "runId": state.run_id,
                "errorCode": "deep_agent_product_path_incomplete",
                "error": (
                    "Deep Agent runtime did not emit a terminal product-path event; "
                    "legacy graph fallback is blocked."
                ),
                "reason": reason,
            },
        ),
    ]
```

- [ ] **Step 4: Update `run_from_state()`**

Replace:

```python
if _deep_agent_finished_without_legacy(deep_events):
    next_state = started.state.model_copy(update={"stage": "plan"})
    self._write_state(next_state)
    return RuntimeEngineResult(
        state=next_state,
        events=[*started.events, *deep_events],
    )
route_events, next_state = self._legacy_route_and_plan(
```

with:

```python
decision = _deep_agent_product_path_decision(deep_events)
if decision.kind == "handled":
    next_state = started.state.model_copy(update={"stage": "plan"})
    self._write_state(next_state)
    return RuntimeEngineResult(
        state=next_state,
        events=[*started.events, *deep_events],
    )
if decision.kind == "blocked":
    next_state = started.state.model_copy(update={"stage": "failed"})
    self._write_state(next_state)
    blocked_events = _deep_agent_product_path_blocked_events(
        next_state,
        reason=decision.reason,
    )
    return RuntimeEngineResult(
        state=next_state,
        events=[*started.events, *deep_events, *blocked_events],
    )

route_events, next_state = self._legacy_response_only(
```

- [ ] **Step 5: Update `stream_from_state()`**

Replace:

```python
if _deep_agent_finished_without_legacy(deep_events):
    next_state = started.state.model_copy(update={"stage": "plan"})
    self._write_state(next_state)
    return
```

with:

```python
decision = _deep_agent_product_path_decision(deep_events)
if decision.kind == "handled":
    next_state = started.state.model_copy(update={"stage": "plan"})
    self._write_state(next_state)
    return
if decision.kind == "blocked":
    next_state = started.state.model_copy(update={"stage": "failed"})
    self._write_state(next_state)
    for event in _deep_agent_product_path_blocked_events(
        next_state,
        reason=decision.reason,
    ):
        yield event
    return
```

Then replace the later fallback call with `_legacy_response_only`.

- [ ] **Step 6: Run targeted tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_agent_runtime_engine_deep_agent.py -q
Pop-Location
```

Expected now:

- Product-path incomplete and planning-failure tests pass.
- Legacy simple graph blocking still fails until Task 3 adds the guard.

## Task 3: Guard Temporary Legacy Response Delegation

**Files:**

- Modify: `python/agent_service/agent_runtime_engine.py`
- Test: `python/tests/test_agent_runtime_engine_deep_agent.py`

- [ ] **Step 1: Rename `_legacy_route_and_plan` to response-only**

Rename:

```python
def _legacy_route_and_plan(
```

to:

```python
def _legacy_response_only(
```

Keep the signature unchanged.

- [ ] **Step 2: Add graph event detection helpers**

Add:

```python
_LEGACY_GRAPH_EVENT_TYPES = {
    "node_graph.created",
    "planning.graph_compiled",
    "planning.graph_review_completed",
    "agent_plan_graph.compile_started",
    "agent_plan_graph.compiled",
    "agent_plan_graph.compile_review_completed",
    "agent_plan_graph.execution_ready",
}


def _legacy_graph_event_types(events: list[AgentEvent]) -> list[str]:
    return [
        event.type
        for event in events
        if event.type in _LEGACY_GRAPH_EVENT_TYPES
    ]
```

- [ ] **Step 3: Add blocked legacy graph events**

Add:

```python
def _legacy_graph_blocked_events(
    state: RuntimeState,
    *,
    blocked_event_types: list[str],
) -> list[AgentEvent]:
    reason = "legacy graph event emitted from response-only fallback"
    payload = {
        "runId": state.run_id,
        "threadId": state.thread_id,
        "taskId": state.task_id,
        "reason": reason,
        "blockedEventTypes": blocked_event_types,
    }
    return [
        AgentEvent(
            type="runtime.legacy_graph_blocked",
            payload=payload,
        ),
        AgentEvent(
            type="task.failed",
            payload={
                "taskId": state.task_id,
                "runId": state.run_id,
                "errorCode": "legacy_graph_blocked",
                "error": (
                    "Legacy graph creation is blocked from the Agent Runtime "
                    "product path."
                ),
                "blockedEventTypes": blocked_event_types,
            },
        ),
    ]
```

- [ ] **Step 4: Guard `_legacy_response_only()`**

Inside `_legacy_response_only()`, after:

```python
routed_events = self.route_runner(
```

add:

```python
blocked_event_types = _legacy_graph_event_types(routed_events)
if blocked_event_types:
    blocked_events = _legacy_graph_blocked_events(
        state,
        blocked_event_types=blocked_event_types,
    )
    next_state = state.model_copy(update={"stage": "failed"})
    delta = RuntimeStateDelta(
        previous_checkpoint_id=None,
        checkpoint_id=f"{state.run_id}:legacy-response-blocked:0",
        stage_before=state.stage,
        stage_after=next_state.stage,
        decision={
            "kind": "legacy_graph_blocked",
            "blockedEventTypes": blocked_event_types,
        },
        emitted_events=[event.model_dump() for event in blocked_events],
    )
    self._write_delta(delta)
    self._write_state(next_state)
    return [
        AgentEvent(
            type="runtime.state_delta",
            payload={"delta": delta.model_dump()},
        ),
        *blocked_events,
    ], next_state
```

Keep the existing success path for non-graph message events.

- [ ] **Step 5: Update stream fallback guard**

In `stream_from_state()`, collect events from `self.stream_runner(...)` before
yielding graph events to the user. Replace the direct streaming loop with:

```python
emitted_events: list[AgentEvent] = []
for event in self.stream_runner(
    run_state,
    model_client=model_client,
    search_provider=search_provider,
    weather_provider=weather_provider,
):
    emitted_events.append(event)
    blocked_event_types = _legacy_graph_event_types(emitted_events)
    if blocked_event_types:
        next_state = started.state.model_copy(update={"stage": "failed"})
        blocked_events = _legacy_graph_blocked_events(
            next_state,
            blocked_event_types=blocked_event_types,
        )
        for blocked_event in blocked_events:
            yield blocked_event
        self._write_state(next_state)
        return
    yield event
```

- [ ] **Step 6: Run targeted tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_agent_runtime_engine_deep_agent.py -q
Pop-Location
```

Expected: all tests in `test_agent_runtime_engine_deep_agent.py` pass.

## Task 4: Block Manual Legacy Plan Step By Default

**Files:**

- Modify: `python/agent_service/agent_runtime_engine.py`
- Modify: `python/tests/test_agent_runtime_engine.py`

- [ ] **Step 1: Add explicit migration opt-in**

In `AgentRuntimeEngine.__init__()`, add:

```python
allow_legacy_task_product_path: bool = False,
```

Store it:

```python
self.allow_legacy_task_product_path = allow_legacy_task_product_path
```

- [ ] **Step 2: Guard `step(stage="plan")`**

Replace:

```python
if state.stage == "plan":
    return self._plan_legacy_action_graph(state)
```

with:

```python
if state.stage == "plan":
    if self.allow_legacy_task_product_path:
        return self._plan_legacy_action_graph(state)
    blocked_events = _legacy_graph_blocked_events(
        state,
        blocked_event_types=["legacy_plan_action_graph"],
    )
    next_state = state.model_copy(update={"stage": "failed"})
    delta = RuntimeStateDelta(
        previous_checkpoint_id=None,
        checkpoint_id=f"{state.run_id}:legacy-plan-blocked:0",
        stage_before=state.stage,
        stage_after=next_state.stage,
        decision={
            "kind": "legacy_graph_blocked",
            "blockedEventTypes": ["legacy_plan_action_graph"],
        },
        emitted_events=[event.model_dump() for event in blocked_events],
    )
    self._write_delta(delta)
    self._write_state(next_state)
    return [
        AgentEvent(type="runtime.state_delta", payload={"delta": delta.model_dump()}),
        *blocked_events,
    ]
```

- [ ] **Step 3: Update existing legacy step test**

In `python/tests/test_agent_runtime_engine.py`, find the test that expects
`stage="plan"` to use the legacy planner. Change engine creation from:

```python
engine = AgentRuntimeEngine(
    route_runner=fake_runner,
    runtime_store=store,
)
```

to:

```python
engine = AgentRuntimeEngine(
    route_runner=fake_runner,
    runtime_store=store,
    allow_legacy_task_product_path=True,
)
```

- [ ] **Step 4: Add default blocked step test**

Add this test to `python/tests/test_agent_runtime_engine.py`:

```python
def test_engine_step_plan_blocks_legacy_planner_by_default():
    legacy_calls: list[AgentRunState] = []

    def fake_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        legacy_calls.append(run_state)
        return [
            AgentEvent(
                type="node_graph.created",
                payload={"graph": {"graphId": "legacy", "nodes": [], "edges": []}},
            )
        ]

    engine = AgentRuntimeEngine(route_runner=fake_runner)
    state = initial_runtime_state(
        message=UserMessage(task_id="task-block-step", content="Make a graph."),
        project_path="project.alita",
        run_id="run-block-step",
    ).model_copy(update={"stage": "plan"})

    events = engine.step(state)

    assert legacy_calls == []
    assert [event.type for event in events] == [
        "runtime.state_delta",
        "runtime.legacy_graph_blocked",
        "task.failed",
    ]
    assert events[-1].payload["errorCode"] == "legacy_graph_blocked"
```

- [ ] **Step 5: Run runtime engine tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_agent_runtime_engine.py tests/test_agent_runtime_engine_deep_agent.py -q
Pop-Location
```

Expected: both files pass.

## Task 5: Add Frontend Event Contract Coverage

**Files:**

- Modify: `src/shared/events.ts`
- Modify: `src/app/backendEvents.ts`
- Modify: `src/app/backendEvents.test.ts`

- [ ] **Step 1: Extend shared event types**

In `src/shared/events.ts`, add this union member near other runtime events:

```ts
  | {
      type: "runtime.legacy_graph_blocked";
      payload: {
        runId: string;
        threadId: string;
        taskId: string;
        reason: string;
        blockedEventTypes: string[];
      };
    }
  | {
      type: "runtime.deep_agent_product_path_blocked";
      payload: {
        runId: string;
        threadId: string;
        taskId: string;
        reason: string;
      };
    }
```

- [ ] **Step 2: Handle blocked events in reducer**

In `src/app/backendEvents.ts`, before the generic `task.failed` branch, add:

```ts
    if (event.type === "runtime.legacy_graph_blocked") {
      return {
        ...current,
        activeRunId: event.payload.runId,
        activeTaskId: event.payload.taskId,
        agentCompileStatus: "failed",
        taskStatus: "failed",
        messages: [
          ...current.messages,
          {
            role: "assistant",
            content:
              "Legacy graph fallback was blocked. The Agent must produce the task graph through deep planning.",
          },
        ],
      };
    }

    if (event.type === "runtime.deep_agent_product_path_blocked") {
      return {
        ...current,
        activeRunId: event.payload.runId,
        activeTaskId: event.payload.taskId,
        agentCompileStatus: "failed",
        taskStatus: "failed",
        messages: [
          ...current.messages,
          {
            role: "assistant",
            content:
              "Deep Agent planning did not reach a valid terminal state, and legacy graph fallback is blocked.",
          },
        ],
      };
    }
```

Adjust field names to match the existing reducer's local state shape if it uses
different names.

- [ ] **Step 3: Add reducer tests**

Append to `src/app/backendEvents.test.ts`:

```ts
  it("surfaces blocked legacy graph fallback", () => {
    const result = applyBackendEvent(initialBackendState(), {
      type: "runtime.legacy_graph_blocked",
      payload: {
        runId: "run-block",
        threadId: "thread-block",
        taskId: "task-block",
        reason: "legacy graph event emitted from response-only fallback",
        blockedEventTypes: ["node_graph.created"],
      },
    });

    expect(result.taskStatus).toBe("failed");
    expect(result.agentCompileStatus).toBe("failed");
    expect(result.messages.at(-1)?.content).toContain("Legacy graph fallback");
  });

  it("surfaces blocked incomplete deep agent product path", () => {
    const result = applyBackendEvent(initialBackendState(), {
      type: "runtime.deep_agent_product_path_blocked",
      payload: {
        runId: "run-incomplete",
        threadId: "thread-incomplete",
        taskId: "task-incomplete",
        reason: "deep_agent_runtime_missing_terminal_event:deep_planning",
      },
    });

    expect(result.taskStatus).toBe("failed");
    expect(result.agentCompileStatus).toBe("failed");
    expect(result.messages.at(-1)?.content).toContain("Deep Agent planning");
  });
```

- [ ] **Step 4: Run frontend tests**

Run:

```powershell
npm test -- --run src/app/backendEvents.test.ts
```

Expected: backend event reducer tests pass.

## Task 6: Regression Gates

**Files:**

- No source edits expected unless tests reveal a real regression.

- [ ] **Step 1: Run Python target tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_agent_runtime_engine.py tests/test_agent_runtime_engine_deep_agent.py tests/test_deep_agent_runtime_graph.py tests/test_deep_agent_runtime_resume.py tests/test_agent_plan_compile.py -q
Pop-Location
```

Expected: all selected Python tests pass.

- [ ] **Step 2: Run frontend target tests**

Run:

```powershell
npm test -- --run src/app/backendEvents.test.ts src/features/task/useTaskEvents.test.ts src/features/task/useGraphRunController.test.ts
```

Expected: all selected frontend tests pass.

- [ ] **Step 3: Run type check**

Run:

```powershell
npm run typecheck
```

Expected: no TypeScript errors.

- [ ] **Step 4: Check whitespace**

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.

## Definition Of Done

Phase 4 is complete only when:

- User graph-task product flow is handled by Deep Agent runtime terminal events.
- Legacy task graph planning is not called after Deep Agent failure or incomplete
  graph-task output.
- Temporary simple-answer legacy delegation cannot emit graph events.
- Manual `step(stage="plan")` blocks legacy graph planning unless migration
  opt-in is explicit.
- Backend and frontend event contracts expose blocked fallback clearly.
- Target backend and frontend tests pass.

## Handoff To Phase 5

After Phase 4 passes, write Phase 5 docs under:

- `docs/superpowers/specs/2026-06-04-execute-verify-repair-phase-5-design.md`
- `docs/superpowers/plans/2026-06-04-execute-verify-repair-phase-5-plan.md`

Phase 5 must consume `AgentCompiledGraph` from
`agent_plan_graph.execution_ready` and attach execution, result verification,
bounded repair, and checkpoint-aware resume. It must not execute legacy template
graphs as the Agent product path.
