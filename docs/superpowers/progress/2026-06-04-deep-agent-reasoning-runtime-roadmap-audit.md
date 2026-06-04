# Deep Agent Reasoning Runtime Roadmap Audit

Date: 2026-06-04

This audit maps `docs/superpowers/specs/2026-06-01-deep-agent-reasoning-runtime-design.md`
to the current Phase 2 worktree state after the Phase 5 execution-runtime slice.

## Source Of Truth

The original design defines this invariant:

```text
User Message
  -> Reasoning Gate
  -> Context Build
  -> Deep Planning when an execution graph is needed
  -> Plan Review
  -> Agent Plan Graph Compile
  -> Graph Review
  -> Present Plan Graph
  -> Execute
  -> Verify Result
  -> Repair or Final
```

The implementation phases in that document are:

1. Phase 1: Reasoning Gate
2. Phase 2: Deep Planning LangGraph
3. Phase 3: Agent Plan Graph Compile
4. Phase 4: Replace Legacy Task Product Path
5. Phase 5: Execute, Verify, Repair

## Current Worktree

Worktree:

```text
D:\Software Project\Alita\.worktrees\deep-agent-reasoning-runtime-phase-1
```

Branch:

```text
codex/deep-agent-reasoning-runtime-phase-1
```

Important note: this worktree already contains uncommitted Phase 2, Phase 3,
Phase 4, and Phase 5 changes. They were preserved as the baseline for the
current roadmap audit.

## Phase Status

| Phase | Original Name | Current Status | Evidence | Remaining Gap |
| --- | --- | --- | --- | --- |
| 1 | Reasoning Gate | Implemented in worktree | `deep_agent_models.py`, `deep_agent_planner.py`, `deep_agent_runtime_graph.py`, `test_agent_runtime_engine_deep_agent.py` | Keep regression tests green through branch integration. |
| 2 | Deep Planning LangGraph | Implemented in worktree | `deep_agent_checkpointer.py`, `deep_agent_checkpoint_mirror.py`, resume/streaming tests, Phase 2 docs | Needs branch integration/commit. |
| 3 | Agent Plan Graph Compile | Implemented in worktree | `agent_plan_compile.py`, `agent_plan_graph.*` events, execution-ready state, Phase 3 docs | Needs branch integration/commit. |
| 4 | Replace Legacy Task Product Path | Implemented in worktree | `agent_runtime_engine.py` classifies Deep Agent outcomes, blocks incomplete graph-task fallbacks, blocks legacy graph events, and exposes frontend blocked-path events | Needs branch integration/commit. |
| 5 | Execute, Verify, Repair | Implemented in worktree | `agent_execution_runtime.py`, `deep_agent_runtime_graph.py`, `agent_execution.*` events, frontend event reducer/controller tests | Needs branch integration/commit. |

## Key Finding

The previous Phase 4 discussion drifted toward Phase 5 execution runtime design.
That was premature relative to the original roadmap.

Correct sequencing:

```text
Phase 4: remove legacy task graph product fallback
Phase 5: execute, verify, repair the confirmed AgentCompiledGraph
```

## Phase 4 Problem That Was Fixed

Before Phase 4, `python/agent_service/agent_runtime_engine.py` first invoked the
Deep Agent runtime. If `_deep_agent_finished_without_legacy()` did not see a
terminal event, it fell back to legacy routing:

```text
run_from_state()
  -> deep_runtime_runner(...)
  -> if not terminal:
       _legacy_route_and_plan(...)
```

The same pattern exists in streaming:

```text
stream_from_state()
  -> deep_runtime_stream_runner(...)
  -> if not terminal:
       stream_runner(...)
```

There was also a manual runtime step path:

```text
step(stage="plan")
  -> _plan_legacy_action_graph(...)
```

Those paths were acceptable migration scaffolding in Phase 1. Phase 4 now guards
them:

- incomplete Deep Agent graph-task paths emit
  `runtime.deep_agent_product_path_blocked` and `task.failed`;
- temporary simple-answer legacy delegation is response-only and blocks graph
  events with `runtime.legacy_graph_blocked`;
- `step(stage="plan")` blocks legacy graph planning by default and only permits
  it through explicit `allow_legacy_task_product_path=True` migration opt-in.

## Phase 4 Acceptance Result

After the Phase 4 implementation:

1. A user task request that needs a graph must never get a legacy template graph
   from the product path.
2. If Deep Agent planning fails, the product shows that failure.
3. If Deep Agent planning interrupts for clarification or confirmation, the
   product waits for resume.
4. If Deep Agent planning confirms and compiles, the product reaches
   `agent_plan_graph.execution_ready`.
5. Simple answer requests may still delegate to legacy answer code temporarily,
   but that delegated path is graph-blocked.
6. Legacy planner/template modules may remain available for old tests,
   migration helpers, and execution fixtures, but not as an implicit product
   fallback from Agent Runtime graph creation.

## Phase 5 Acceptance Result

After the Phase 5 implementation:

1. `AgentCompiledGraph(status="execution_ready")` is the only entry into the
   Deep Agent execution bridge.
2. Legacy/template graphs and compiled graphs without Deep Agent provenance are
   rejected before execution.
3. `deep_agent_runtime_graph.py` conditionally continues from
   `agent_plan_graph.execution_ready` into execution, verification, final,
   interrupted, failed, or repair-proposed terminal states.
4. Low-level `run_graph_events()` events are forwarded while Agent-level
   `agent_execution.*` events summarize start, completion, interruption,
   failure, verification, repair, and final success.
5. Runner/bridge exceptions are converted into `agent_execution.failed` and
   `terminal_status="execution_failed"` instead of escaping the LangGraph run.
6. The frontend accepts all `agent_execution.*` events, preserves compile state
   after execution starts, suppresses duplicate generic task terminal messages
   inside Agent execution streams, and keeps ordinary task terminal messages
   unchanged outside Agent execution.

## Verification

The Phase 4 target regression passed:

```powershell
Push-Location python
python -m pytest tests/test_agent_runtime_engine.py tests/test_agent_runtime_engine_deep_agent.py tests/test_deep_agent_runtime_graph.py tests/test_deep_agent_runtime_resume.py tests/test_agent_plan_compile.py -q
Pop-Location
# 68 passed

npm run frontend:test -- src/app/backendEvents.test.ts src/features/task/useTaskEvents.test.ts src/features/task/useGraphRunController.test.ts
# 72 passed

npm run frontend:typecheck
# passed

git diff --check
# no whitespace errors; CRLF warnings only
```

The Phase 5 target regression passed:

```powershell
Push-Location python
python -m pytest tests/test_agent_execution_runtime.py tests/test_agent_runtime_engine.py tests/test_agent_runtime_engine_deep_agent.py tests/test_deep_agent_runtime_graph.py tests/test_deep_agent_runtime_resume.py tests/test_agent_plan_compile.py -q
Pop-Location
# 89 passed

npm run frontend:test -- src/app/backendEvents.test.ts src/features/task/useTaskEvents.test.ts src/features/task/useGraphRunController.test.ts
# 88 passed

npm run frontend:typecheck
# passed

git diff --check
# no whitespace errors; CRLF warnings only
```

## Remaining Work Order

1. Preserve and commit Phase 2/3/4/5 work when the branch is ready.
2. Run a final whole-branch review before integration.
3. Decide whether to add model-adjudicated execution quality review and
   automatic plan regeneration as a later Phase 6, beyond the deterministic
   Phase 5 repair proposal slice.
