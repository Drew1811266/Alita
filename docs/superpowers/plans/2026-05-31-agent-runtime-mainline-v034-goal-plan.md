# Agent Runtime Mainline v0.34 Goal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Alita 0.34.0 from a runtime facade around the legacy router/DAG runner into a staged Agent Runtime mainline with durable state, stronger traceability, schema-aware tool planning, real MCP execution, safer sandboxing, governed memory, and model-loop eval gates.

**Architecture:** Move `/agent/message` onto `AgentRuntimeEngine` first while preserving current behavior, then incrementally make `RuntimeState`/`RuntimeStateDelta` the persisted control plane. Keep document/research behavior compatible while compiling business flows into generic runtime actions. Every phase has a verification gate; failed gates block the next phase until fixed.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest, LangGraph legacy router, Tauri/React frontend, TypeScript/Vitest, JSONL journal/trace files, Windows-oriented sandbox constraints.

---

## Goal-Mode Execution Protocol

This is the active Codex goal plan. Work proceeds phase by phase in order.

Rules:

1. Before editing a phase, read the phase objective, files, and gate.
2. Write or update the targeted failing tests first.
3. Run the targeted tests and confirm they fail for the expected reason.
4. Implement the smallest code change that satisfies the phase.
5. Run the phase gate commands.
6. Inspect `git diff --name-status` and the key diff hunks.
7. If all gate commands pass and the diff matches the phase scope, mark the phase complete and continue to the next phase.
8. If a gate fails, debug and fix within the same phase before moving on.
9. Do not mark the overall Codex goal complete until Phase 10 passes and the final full verification gate passes.

Phase gate baseline:

```powershell
python -m pytest python/tests/test_agent_runtime_engine.py -q
python -m pytest python/tests/test_app.py -q
python -m pytest python/tests/test_run_journal.py python/tests/test_trace_store.py python/tests/test_memory_store.py -q
npm run frontend:typecheck
npm run frontend:test
npm run agent:eval
```

The full baseline can be expensive. Each phase lists a narrower gate. Run the full baseline at the end and whenever a phase changes shared contracts used by multiple subsystems.

---

## Phase 1: RuntimeEngine Owns Message Entry

**Outcome:** `/agent/message`, `/agent/research/choose`, and `/agent/message/stream` route through `AgentRuntimeEngine`, while external events remain backward compatible.

**Files:**

- Modify: `python/agent_service/agent_runtime_engine.py`
- Modify: `python/agent_service/app.py`
- Modify: `python/tests/test_agent_runtime_engine.py`
- Modify: `python/tests/test_app.py`

### Task 1.1: Add RuntimeEngine request-level orchestration

- [x] **Step 1: Write tests for request-level engine methods**

Add tests to `python/tests/test_agent_runtime_engine.py`:

```python
from agent_service.agent_run_state import AgentRunState
from agent_service.schemas import AgentEvent, UserMessage


def test_engine_run_from_agent_state_wraps_legacy_events_with_runtime_events():
    captured: list[AgentRunState] = []

    def fake_runner(run_state: AgentRunState, **kwargs):
        del kwargs
        captured.append(run_state)
        return [AgentEvent(type="message.created", payload={"message": {"content": "ok"}})]

    engine = AgentRuntimeEngine(route_runner=fake_runner)
    run_state = AgentRunState.from_user_message(
        UserMessage(task_id="task-runtime-entry", content="hello")
    ).model_copy(update={"project_path": "D:/Project/demo.alita", "run_id": "run-entry"})

    result = engine.run_from_state(run_state)

    assert captured[0].task_id == "task-runtime-entry"
    assert [event.type for event in result.events] == [
        "runtime.run_started",
        "runtime.state_delta",
        "message.created",
    ]
    assert result.state.stage == "plan"
    assert result.events[1].payload["delta"]["decision"]["kind"] == "legacy_route_and_plan"
```

- [x] **Step 2: Run the new engine test and confirm it fails**

Run:

```powershell
python -m pytest python/tests/test_agent_runtime_engine.py::test_engine_run_from_agent_state_wraps_legacy_events_with_runtime_events -q
```

Expected: fail because `AgentRuntimeEngine` has no `route_runner` injection and no `run_from_state()`.

- [x] **Step 3: Implement engine injection and `run_from_state()`**

In `python/agent_service/agent_runtime_engine.py`, change the constructor and add `run_from_state()`:

```python
class AgentRuntimeEngine:
    def __init__(self, *, route_runner=run_agent_from_state) -> None:
        self.route_runner = route_runner

    def run_from_state(
        self,
        run_state: AgentRunState,
        *,
        model_client=None,
        search_provider=None,
        weather_provider=None,
    ) -> RuntimeEngineResult:
        started = self.start_run(
            message=run_state.message,
            project_path=run_state.project_path or "project.alita",
            run_id=run_state.run_id,
        )
        events, next_state = self._legacy_route_and_plan(
            started.state,
            run_state,
            model_client=model_client,
            search_provider=search_provider,
            weather_provider=weather_provider,
        )
        return RuntimeEngineResult(state=next_state, events=[*started.events, *events])
```

Add `_legacy_route_and_plan()` so `step()` and `run_from_state()` share one path:

```python
def _legacy_route_and_plan(...):
    routed_events = self.route_runner(...)
    next_state = state.model_copy(update={"stage": "plan"})
    delta = RuntimeStateDelta(
        previous_checkpoint_id=None,
        checkpoint_id=f"{state.run_id}:route:0",
        stage_before=state.stage,
        stage_after=next_state.stage,
        decision={"kind": "legacy_route_and_plan"},
        emitted_events=[event.model_dump() for event in routed_events],
    )
    return [
        AgentEvent(type="runtime.state_delta", payload={"delta": delta.model_dump()}),
        *routed_events,
    ], next_state
```

Keep backward compatibility: `step(state)` still returns a list of events and should still include `node_graph.created` for task planning.

- [x] **Step 4: Run engine tests**

Run:

```powershell
python -m pytest python/tests/test_agent_runtime_engine.py -q
```

Expected: all tests pass.

### Task 1.2: Route app message endpoints through RuntimeEngine

- [x] **Step 1: Replace app endpoint tests with engine-centric assertions**

Update `python/tests/test_app.py` so the first message endpoint test monkeypatches `agent_service.app.AgentRuntimeEngine` or a helper factory and verifies `run_from_state()` receives the original `AgentRunState`. Keep assertions for `current_graph`, `has_run_history`, `artifact_refs`, `pending_choice`, and `inquiry_choice`.

For stream, verify the stream path also uses `AgentRuntimeEngine.stream_from_state()` or the shared helper rather than direct `stream_agent_events_from_state()`.

- [x] **Step 2: Run targeted app tests and confirm failures**

Run:

```powershell
python -m pytest python/tests/test_app.py::test_agent_message_endpoint_passes_agent_run_state_to_orchestrator python/tests/test_app.py::test_agent_message_stream_endpoint_passes_agent_run_state_to_streamer -q
```

Expected: fail because app still imports and calls `run_agent_from_state()` and `stream_agent_events_from_state()` directly.

- [x] **Step 3: Implement app routing helpers**

In `python/agent_service/app.py`:

```python
from agent_service.agent_runtime_engine import AgentRuntimeEngine
```

Add helpers:

```python
def _runtime_engine() -> AgentRuntimeEngine:
    return AgentRuntimeEngine()


def _run_message_with_runtime(request: AgentMessageRequest, *, model_client) -> list[AgentEvent]:
    run_state = AgentRunState.from_message_request(request)
    return _runtime_engine().run_from_state(run_state, model_client=model_client).events
```

Change `/agent/message` and `/agent/research/choose` to call `_run_message_with_runtime()`.

For stream, add `AgentRuntimeEngine.stream_from_state()` or use `run_from_state()` and serialize its events. Preserve existing SSE response shape.

- [x] **Step 4: Run Phase 1 app tests**

Run:

```powershell
python -m pytest python/tests/test_app.py -q
python -m pytest python/tests/test_agent_runtime_engine.py -q
```

Expected: all pass.

### Phase 1 Gate

Run:

```powershell
python -m pytest python/tests/test_agent_runtime_engine.py python/tests/test_app.py -q
rg -n "run_agent_from_state\\(" python/agent_service/app.py
```

Pass criteria:

- Tests pass.
- `app.py` no longer directly calls `run_agent_from_state()` inside endpoint handlers.
- Current response event payloads remain backward compatible.

---

## Phase 2: Durable Runtime Store and Checkpoint Identity

**Outcome:** Runtime state, deltas, and checkpoints are persisted through one store. Checkpoint identity becomes stable and unique.

**Files:**

- Create: `python/agent_service/runtime_store.py`
- Modify: `python/agent_service/runtime_loop.py`
- Modify: `python/agent_service/run_journal.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_run_journal.py`
- Create: `python/tests/test_runtime_store.py`

### Task 2.1: Add stable checkpoint IDs

- [x] Write a failing test proving two checkpoints with the same node/status/recovery count but different sequence produce different `checkpointId` values.
- [x] Add `checkpoint_id: str | None = None` and `state_hash: str | None = None` to `RuntimeCheckpoint`.
- [x] Generate `checkpointId` as explicit `checkpoint_id` when present, otherwise `ckpt-{run_id}-{sequence}-{short_hash}` when `sequence` exists, otherwise preserve the old label for old tests that construct legacy checkpoints.
- [x] Preserve `nodeId`, `status`, and `recoveryCount` as readable fields.
- [x] Update execution checkpoint enrichment to set `checkpoint_id` and `state_hash`.

Gate:

```powershell
python -m pytest python/tests/test_run_journal.py python/tests/test_execution.py::test_resume_checkpoint_uses_requested_checkpoint_id -q
```

### Task 2.2: Persist RuntimeStateDelta

- [x] Add `RunJournal.write_runtime_state(state)` and `RunJournal.write_runtime_delta(delta)`.
- [x] Add `RunJournal.read_runtime_state()` and `RunJournal.read_runtime_deltas()`.
- [x] Add `RuntimeStore` wrapper that uses `RunJournal`.
- [x] Make `AgentRuntimeEngine.run_from_state()` write initial state and delta when a `RuntimeStore` is configured.
- [x] Keep store optional so unit tests can run without filesystem setup.

Gate:

```powershell
python -m pytest python/tests/test_runtime_store.py python/tests/test_agent_runtime_engine.py -q
```

### Task 2.3: Restore RuntimeState from checkpoint

- [x] Save full `RuntimeState.model_dump()` under checkpoint `runtimeState` for runtime-engine checkpoints.
- [x] Add `RuntimeStore.restore_state(checkpoint_id=None)`.
- [x] Make `AgentRuntimeEngine.resume()` return a restored state when store is present.
- [x] Keep old graph resume behavior in `run_graph_events()` until Phase 3/4 migrates action execution.

Gate:

```powershell
python -m pytest python/tests/test_runtime_store.py python/tests/test_run_journal.py -q
```

---

## Phase 3: Runtime Step Dispatch and RuntimeActionGraph Bridge

**Outcome:** `AgentRuntimeEngine.step()` dispatches by `RuntimeState.stage` and produces explicit route/context/plan/action deltas. Legacy router becomes a compatibility action, not the owner of the control flow.

**Files:**

- Modify: `python/agent_service/agent_runtime_engine.py`
- Modify: `python/agent_service/runtime_state.py`
- Modify: `python/agent_service/action_graph.py`
- Modify: `python/agent_service/graph.py`
- Modify: `python/tests/test_agent_runtime_engine.py`
- Modify: `python/tests/test_action_graph.py`

Tasks:

- [x] Add explicit stage handling for `route`, `context`, `plan`, `act`, `observe`, `verify`, and terminal stages in `AgentRuntimeEngine`.
- [x] Make `step(state)` dispatch according to `state.stage`.
- [x] Move the current legacy call into the plan-stage compatibility path.
- [x] Convert `RunGraph` output from legacy planning into `RuntimeActionGraph` with `action_graph_from_run_graph()`.
- [x] Store action graph writes when legacy planner emits `node_graph.created`.
- [x] Add tests for route and plan transitions and for no direct `run_agent_from_state()` call from `step(route)`.

Gate:

```powershell
python -m pytest python/tests/test_agent_runtime_engine.py python/tests/test_action_graph.py python/tests/test_graph.py -q
```

---

## Phase 4: Flow Templates Replace Runtime Business Privileges

**Outcome:** document and research flow definitions move out of `execution.py` into template/compiler modules. Runtime execution knows generic graph/action categories, not hard-coded business node IDs.

**Files:**

- Create: `python/agent_service/flow_templates/__init__.py`
- Create: `python/agent_service/flow_templates/document.py`
- Create: `python/agent_service/flow_templates/research.py`
- Modify: `python/agent_service/task_planner.py`
- Modify: `python/agent_service/web_research.py`
- Modify: `python/agent_service/execution.py`
- Create: `python/tests/test_flow_templates.py`
- Modify: `python/tests/test_execution.py`
- Modify: `python/tests/test_web_research.py`

Tasks:

- [x] Extract document node ID definitions into `flow_templates/document.py`.
- [x] Extract research node ID definitions into `flow_templates/research.py`.
- [x] Keep `execution.py` compatibility adapters during this phase, but make node-id constants import from templates.
- [x] Add template metadata functions that convert each template into generic runtime metadata.
- [x] Add tests proving document/research template metadata is stable.
- [x] Reduce direct business node-id string checks in `execution.py` to template constants.

Gate:

```powershell
python -m pytest python/tests/test_flow_templates.py python/tests/test_execution.py python/tests/test_web_research.py -q
rg -n "DOCUMENT_FLOW_NODE_IDS|research-query-plan|research-parallel-search" python/agent_service/execution.py
```

Pass criteria:

- Tests pass.
- Remaining business node references in `execution.py` are either compatibility comments or imports from template modules.

---

## Phase 5: Trace Spans for Model, Tool, Planner, Memory

**Outcome:** `TraceStore` records more than `runtime.node`. It captures model/tool/planner/memory spans with redacted metadata.

**Files:**

- Reuse unchanged: `python/agent_service/runtime_trace.py`
- Reuse unchanged: `python/agent_service/trace_store.py`
- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/agent_service/model_runtime.py`
- Modify: `python/agent_service/planner_chain.py`
- Modify: `python/agent_service/context_manager.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_tool_gateway.py`
- Modify: `python/tests/test_model_runtime.py`
- Modify: `python/tests/test_planner_chain.py`
- Modify: `python/tests/test_context_manager.py`
- Modify: `python/tests/test_execution.py`

Tasks:

- [x] Add span metadata that records bounded IDs, counts, policy refs, and status without prompt, argument, summary, or artifact payloads.
- [x] Add `tool.call` span around `UnifiedToolGateway.call_tool()`.
- [x] Add `model.call` span wrapper around `ModelRuntime.run()` and planned-task model execution.
- [x] Add `planner.call` span around `PlannerChain.plan()`.
- [x] Add `memory.search` span in context selection and `memory.write` span in automatic memory writes.
- [x] Preserve existing `runtime.span_recorded` event payload contract and persist all run-level spans through `TraceStore`.

Gate:

```powershell
python -m pytest python/tests/test_tool_gateway.py python/tests/test_model_runtime.py python/tests/test_planner_chain.py python/tests/test_context_manager.py -q
python -m pytest python/tests/test_execution.py::test_run_graph_events_persists_runtime_node_spans python/tests/test_execution.py::test_run_graph_events_persists_tool_and_model_call_spans python/tests/test_execution.py::test_run_graph_events_persists_planned_model_call_spans python/tests/test_execution.py::test_run_completion_auto_writes_memory_records python/tests/test_execution.py::test_run_completion_writes_memory_by_default python/tests/test_execution.py::test_run_completion_can_disable_memory_auto_write -q
python -m pytest python/tests/test_trace_store.py python/tests/test_runtime_trace.py -q
```

Status: passed on 2026-05-31. Frontend reducer/typecheck was not run in this phase because no frontend files or event shape changed.

---

## Phase 6: Schema-Constrained Multi-Step Tool DAG Planner

**Outcome:** `ToolCatalogPlanner` supports small schema-compatible DAGs instead of one optional two-step chain.

**Files:**

- Create: `python/agent_service/tool_ports.py`
- Modify: `python/agent_service/tool_graph_planner.py`
- Modify: `python/agent_service/tool_catalog_planner.py`
- Modify: `python/tests/test_tool_catalog_planner.py`
- Modify: `python/tests/test_tool_graph_planner.py`
- Modify: `python/evals/planner_cases.jsonl`

Tasks:

- [x] Define normalized tool port types: `text`, `file_path`, `file_paths`, `json`, `artifact_path`, `url`, `table`, `pdf`.
- [x] Derive input/output port types from JSON schema properties.
- [x] Replace fixed `first_plan`/`second_plan` logic with bounded search up to 5 nodes.
- [x] Validate dependency references, required args, port compatibility, authority hints, and artifact outputs.
- [x] Add deterministic planner eval cases for three-step document conversion/export.

Gate:

```powershell
python -m pytest python/tests/test_tool_catalog_planner.py python/tests/test_tool_graph_planner.py -q
npm run agent:eval
```

Status: passed on 2026-05-31.

---

## Phase 7: Real Stdio MCP Minimum Loop

**Outcome:** A configured stdio MCP server can start, initialize, list tools, call a tool, stop, and produce trace/authority records.

**Files:**

- Modify: `python/agent_service/mcp_client_factory.py`
- Modify: `python/agent_service/tool_providers/mcp.py`
- Modify: `python/agent_service/tool_gateway.py`
- Create: `python/tests/fixtures/mcp_stdio_server.py`
- Modify: `python/tests/test_mcp_client_factory.py`
- Modify: `python/tests/test_mcp_tool_provider.py`
- Modify: `python/tests/test_tool_gateway.py`

Tasks:

- [x] Implement JSON-RPC stdio MCP client lifecycle: `start`, `initialize`, `tools/list`, `tools/call`, `stop`.
- [x] Add timeout support to stdio reads/writes.
- [x] Map MCP tool schemas into `UnifiedToolDefinition`.
- [x] Preserve `UnavailableMcpClient` for invalid config.
- [x] Add fixture stdio server that exposes one echo tool.
- [x] Ensure authority can deny and allow MCP calls.

Gate:

```powershell
python -m pytest python/tests/test_mcp_client_factory.py python/tests/test_mcp_tool_provider.py python/tests/test_tool_gateway.py -q
```

Status: passed on 2026-05-31.

---

## Phase 8: Authority Budget and Sandbox Boundary Upgrade

**Outcome:** Tool runtime budget is enforceable, and sandbox reports process-tree/backend guarantees truthfully.

**Files:**

- Modify: `python/agent_service/tool_protocol.py`
- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/agent_service/tool_providers/internal.py`
- Modify: `python/agent_service/tool_providers/mcp.py`
- Modify: `python/agent_service/sandbox.py`
- Modify: `python/tests/test_tool_gateway.py`
- Modify: `python/tests/test_sandbox.py`

Tasks:

- [x] Extend `ToolProvider.call_tool()` protocol with `timeout_ms: int | None = None`.
- [x] Pass effective runtime budget from `UnifiedToolGateway` into providers.
- [x] Make internal tool execution respect timeout where the local executor supports it.
- [x] Make MCP calls use the smaller of authority budget and tool timeout.
- [x] Add Windows Job Object capability detection as a backend flag without claiming isolation when not active.
- [x] Add tests proving subprocess backend still reports no OS isolation and provider timeout is passed.

Gate:

```powershell
python -m pytest python/tests/test_tool_gateway.py python/tests/test_sandbox.py -q
```

Status: passed on 2026-05-31.

---

## Phase 9: Governed Memory v2

**Outcome:** Memory uses upsert/dedupe, expiry filtering, last-used updates, and a policy boundary for automatic writes.

**Files:**

- Modify: `python/agent_service/memory_store.py`
- Modify: `python/agent_service/context_policy.py`
- Modify: `python/agent_service/context_manager.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_memory_store.py`
- Modify: `python/tests/test_context_manager.py`
- Modify: `python/tests/test_execution.py`

Tasks:

- [x] Add `MemoryStore.upsert(record)` keyed by `memory_id`.
- [x] Add `MemoryStore.mark_used(memory_ids, used_at)`.
- [x] Filter expired records during listing or context selection.
- [x] Add automatic write policy that avoids storing low-value repeated summaries.
- [x] Update context selection to mark selected records as used.
- [x] Keep append available for compatibility but migrate internal writes to upsert.

Gate:

```powershell
python -m pytest python/tests/test_memory_store.py python/tests/test_context_manager.py python/tests/test_execution.py -q
```

Status: passed on 2026-05-31.

---

## Phase 10: Scripted Model-Loop Eval Gate

**Outcome:** `model_loop` eval no longer only skips or returns mock success. It runs deterministic scripted model/tool/observation/final cases.

**Files:**

- Modify: `python/agent_service/eval_harness.py`
- Modify: `python/evals/model_loop_cases.jsonl`
- Modify: `python/tests/test_eval_harness.py`
- Optional Modify: `README.md` eval section if behavior is documented there.

Tasks:

- [x] Add a scripted model client that returns configured actions by step.
- [x] Add a recording gateway for scripted tool responses.
- [x] Run `ReActController` or RuntimeEngine model/action path against the scripted sequence.
- [x] Assert final answer, tool call count, observation count, and error code.
- [x] Make default CI run the deterministic scripted model-loop cases without external API keys.
- [x] Keep env-enabled real model loop as a separate nightly/manual mode.

Gate:

```powershell
python -m pytest python/tests/test_eval_harness.py python/tests/test_react_controller.py -q
npm run agent:eval
```

Status: passed on 2026-05-31.

---

## Final Verification Gate

Run:

```powershell
python -m pytest python/tests -q
npm run frontend:typecheck
npm run frontend:test
npm run agent:eval
git diff --check
git status --short
```

Pass criteria:

- Python tests pass.
- Frontend typecheck passes.
- Frontend tests pass.
- Agent eval passes.
- `git diff --check` reports no whitespace errors.
- `git status --short` contains only intentional source, test, and documentation changes.

When this gate passes, update the Codex goal status to complete.
