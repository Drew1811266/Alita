# Agent Runtime Closed Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the 0.30.0 optimization document into a staged implementation program that strengthens Alita's Agent Runtime from routed graph execution into a safer, more recoverable act/observe/verify/replan loop.

**Architecture:** Work in `D:\Software Project\Alita\.worktrees\agent-runtime-closed-loop` on branch `codex/agent-runtime-closed-loop`. The implementation proceeds in gates: baseline, authority hardening, generic provider runtime, document binding cleanup, runtime loop checkpointing, planner/ReAct/memory integration, MCP provider activation, research claim evidence, frontend/runtime observability, and final verification. Each phase must pass its local gate and update the progress document before the next phase starts.

**Tech Stack:** Python 3.10+, Pydantic, LangGraph, pytest, JSONL eval harness, React 19, TypeScript, Vitest, Tauri 2, Rust tests, PowerShell verification scripts.

---

## Source Documents

- `docs/agent-development-optimization-2026-05-30.md`
- `docs/superpowers/plans/2026-05-30-agent-runtime-goal-implementation-plan.md`
- `docs/superpowers/progress/2026-05-30-agent-runtime-goal-progress.md`

The older goal plan records the 0.30.0 implementation already completed. This plan starts from that codebase and targets the next closed-loop runtime iteration.

## Operating Loop

For every phase:

1. Confirm entry conditions with the listed commands.
2. Write or update tests before behavior changes.
3. Run the red test and verify the expected failure.
4. Implement the smallest coherent code change for the phase.
5. Run the phase gate.
6. Inspect `git diff --check`, `git diff --stat`, and the relevant source/test diff.
7. Update `docs/superpowers/progress/2026-05-30-agent-runtime-closed-loop-progress.md`.
8. Move to the next phase only if the gate passes.

If the same blocker repeats for three consecutive goal turns and no meaningful progress is possible, mark the Codex goal blocked and record the blocker in the progress document.

## Shared Commands

Run commands from `D:\Software Project\Alita\.worktrees\agent-runtime-closed-loop`.

```powershell
git status --short --branch
git diff --check
npm run agent:eval
Push-Location python; python -m pytest -q; Pop-Location
npm run frontend:lint
npm run frontend:test
cargo test --manifest-path src-tauri/Cargo.toml
powershell -ExecutionPolicy Bypass -File scripts/verify-mvp.ps1
```

Use targeted tests inside each phase first. Run broader gates when a phase touches shared contracts.

## Phase Map

| Phase | Name | Purpose | Gate |
| --- | --- | --- | --- |
| 0 | Baseline And Plan Gate | Persist plan/progress docs and verify clean starting behavior | docs created, diff check clean, baseline targeted tests pass |
| 1 | Authority V2 | Remove legacy auto approval and make authority grants explicit | authority/gateway/permission/security tests and eval pass |
| 2 | Provider Runtime Loader | Replace hard-coded internal tool adapters with manifest-driven provider runtimes | a manifest entrypoint tool runs without adding adapter dict entries |
| 3 | Binding-Driven Document Flow | Execute document fixed-tool nodes through `ExecutionToolBinding` instead of document node id branches | document flow and execution graph tests pass without document runtime bindings table dependence |
| 4 | Runtime Checkpoints And Continue | Add checkpoint records and a controlled low-risk replan/continue loop | run journal/checkpoint/recovery tests pass |
| 5 | Planner ReAct And Memory Defaults | Planner emits bounded ReAct policy and planning reads/writes project memory by default | planner/react/memory tests and eval pass |
| 6 | MCP Provider Activation | Load configured MCP providers into the default tool gateway with authority constraints | MCP provider tests and Rust preference refresh tests pass |
| 7 | Claim Evidence Graph | Upgrade research synthesis to structured claims with evidence refs before rendering | research evidence tests and research eval pass |
| 8 | Frontend Runtime Observability | Surface checkpoints, authority decisions, and recovery actions in existing controllers | frontend controller tests pass |
| 9 | Final Gate | Run full verification, update docs, record residual risks | all required gates pass or failures are explicitly documented |

## Phase 0: Baseline And Plan Gate

**Files:**

- Create: `docs/superpowers/plans/2026-05-30-agent-runtime-closed-loop-plan.md`
- Create: `docs/superpowers/progress/2026-05-30-agent-runtime-closed-loop-progress.md`
- Modify: `docs/agent-development-optimization-2026-05-30.md`

- [ ] **Step 0.1: Confirm isolated worktree**

Run:

```powershell
git rev-parse --show-toplevel
git rev-parse --git-dir
git rev-parse --git-common-dir
git branch --show-current
git status --short --branch
```

Expected:

```text
D:/Software Project/Alita/.worktrees/agent-runtime-closed-loop
...
codex/agent-runtime-closed-loop
## codex/agent-runtime-closed-loop
```

- [ ] **Step 0.2: Create progress tracker**

Create `docs/superpowers/progress/2026-05-30-agent-runtime-closed-loop-progress.md` with every phase marked `pending` except Phase 0 `in_progress`.

- [ ] **Step 0.3: Run plan hygiene gate**

Run:

```powershell
git diff --check
Select-String -Path docs/superpowers/plans/2026-05-30-agent-runtime-closed-loop-plan.md -Pattern 'T[B]D|TO[D]O|implement\s+later|fill\s+in\s+details'
```

Expected:

```text
git diff --check exits 0
Select-String returns no matches
```

- [ ] **Step 0.4: Run baseline smoke**

Run:

```powershell
npm run agent:eval
Push-Location python; python -m pytest tests/test_authority.py tests/test_tool_gateway.py tests/test_execution_graph.py -q; Pop-Location
```

Expected:

```text
Agent eval reports all cases passed
pytest exits 0
```

## Phase 1: Authority V2

**Files:**

- Modify: `python/agent_service/authority.py`
- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/agent_service/permission_gate.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/model_tool_adapter.py`
- Modify: `python/evals/security_cases.jsonl`
- Test: `python/tests/test_authority.py`
- Test: `python/tests/test_tool_gateway.py`
- Test: `python/tests/test_permission_gate.py`
- Test: `python/tests/test_execution_gateway_integration.py`
- Test: `python/tests/test_eval_harness.py`

- [ ] **Step 1.1: Write failing gateway authority tests**

Add tests proving that a gateway without explicit authority context denies sensitive permissions and does not auto-approve `tool.permissions`.

Run:

```powershell
Push-Location python; python -m pytest tests/test_tool_gateway.py::test_gateway_denies_sensitive_tool_permission_without_explicit_authority -q; Pop-Location
```

Expected before implementation:

```text
FAIL because the test is missing or gateway currently allows the call
```

- [ ] **Step 1.2: Write read/write root separation tests**

Add tests proving a path in `read_roots` is not automatically writable and a path in `write_roots` is not automatically readable.

Run:

```powershell
Push-Location python; python -m pytest tests/test_authority.py::test_authority_separates_read_and_write_roots -q; Pop-Location
```

Expected before implementation:

```text
FAIL because `allowed_roots` currently becomes both read and write roots
```

- [ ] **Step 1.3: Implement explicit authority grant model**

Change `AuthorityContext.from_invocation()` so it no longer turns every `allowed_roots` item into both read and write roots. Add a helper that derives an explicit context only from approved permissions plus scoped read/write roots supplied by execution.

- [ ] **Step 1.4: Remove legacy auto approval**

Change `UnifiedToolGateway.call_tool()` so missing `authority_context` uses a deny-by-default context instead of `_legacy_authority_context()`. Delete `_legacy_authority_context()` after tests are updated.

- [ ] **Step 1.5: Tighten default permissions**

Change `DEFAULT_ALLOWED_PERMISSIONS` so high-risk capabilities are not default allowed. Keep only low-risk read/controlled artifact capabilities. Ensure execution still passes approved permissions from `RunGraphRequest`.

- [ ] **Step 1.6: Update execution authority wiring**

When `DocumentFlowExecutor` and `PlannedTaskExecutor` invoke tools, pass read roots and write roots through a gateway authority context instead of relying on `allowed_roots` as a broad fallback.

- [ ] **Step 1.7: Expand security eval**

Add security cases for denied CLI, denied Python plugin, denied project write, and read/write root separation.

- [ ] **Step 1.8: Phase gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_authority.py tests/test_tool_gateway.py tests/test_permission_gate.py tests/test_execution_gateway_integration.py tests/test_eval_harness.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected:

```text
pytest exits 0
agent eval exits 0
git diff --check exits 0
```

## Phase 2: Provider Runtime Loader

**Files:**

- Create: `python/agent_service/tool_runtime.py`
- Modify: `python/agent_service/tool_execution.py`
- Modify: `python/agent_service/tool_providers/internal.py`
- Modify: `python/agent_service/tool_registry.py`
- Modify: `tool-packages/test_echo/manifest.json`
- Test: `python/tests/test_tool_execution.py`
- Test: `python/tests/test_tool_gateway.py`
- Test: `python/tests/test_tool_registry.py`

- [ ] **Step 2.1: Write failing manifest entrypoint runtime test**

Add a test that defines a temporary manifest with a Python function entrypoint and asserts the internal provider executes it without adding an adapter dict entry.

Run:

```powershell
Push-Location python; python -m pytest tests/test_tool_execution.py::test_tool_executor_loads_python_function_entrypoint_from_manifest -q; Pop-Location
```

Expected before implementation:

```text
FAIL with unsupported tool operation
```

- [ ] **Step 2.2: Add runtime loader module**

Create `tool_runtime.py` with a small `ToolRuntimeLoader` that supports:

- `virtual_system_tool` for built-in no-op/receive-attachment behavior.
- Python function entrypoints in the form `module.path:function_name`.
- Existing legacy adapter fallback for backward compatibility during this phase only.

- [ ] **Step 2.3: Refactor ToolExecutor**

Move adapter dict usage behind `ToolRuntimeLoader`. `ToolExecutor.run()` should resolve manifest, validate operation/schema, then call a runtime loaded from manifest metadata.

- [ ] **Step 2.4: Convert test echo to manifest entrypoint**

Provide a real entrypoint for `test.echo_values` so generic execution is no longer test-only adapter injection.

- [ ] **Step 2.5: Phase gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_tool_execution.py tests/test_tool_gateway.py tests/test_tool_registry.py tests/test_execution.py::test_generic_fixed_tool_node_executes_from_binding -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected all commands exit 0.

## Phase 3: Binding-Driven Document Flow

**Files:**

- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/execution_graph.py`
- Modify: `python/agent_service/task_graph.py`
- Test: `python/tests/test_execution.py`
- Test: `python/tests/test_execution_graph.py`
- Test: `python/tests/test_execution_gateway_integration.py`

- [ ] **Step 3.1: Write failing test for document flow without node-id tool branches**

Add a test that builds the document graph with full `toolBinding` and verifies fixed-tool nodes execute through `PlannedTaskExecutor._run_fixed_tool_node()`.

Run:

```powershell
Push-Location python; python -m pytest tests/test_execution.py::test_document_fixed_tools_execute_from_bindings_without_document_executor_branch -q; Pop-Location
```

Expected before implementation:

```text
FAIL because document node ids still route through DocumentFlowExecutor
```

- [ ] **Step 3.2: Move document model nodes behind execution graph bindings**

Keep document model steps supported, but make the decision based on node type and binding, not `DOCUMENT_FLOW_NODE_IDS`.

- [ ] **Step 3.3: Remove runtime binding table dependence**

Remove or retire `DOCUMENT_FLOW_RUNTIME_TOOL_BINDINGS` from validation. Validation should rely on `GraphNode.toolBinding` and compiled `ExecutionToolBinding`.

- [ ] **Step 3.4: Phase gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_execution.py tests/test_execution_graph.py tests/test_execution_gateway_integration.py tests/test_task_graph.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected all commands exit 0.

## Phase 4: Runtime Checkpoints And Continue

**Files:**

- Create: `python/agent_service/runtime_loop.py`
- Modify: `python/agent_service/run_journal.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/replan.py`
- Test: `python/tests/test_run_journal.py`
- Test: `python/tests/test_execution.py`
- Test: `python/tests/test_replan.py`

- [ ] **Step 4.1: Write failing checkpoint persistence test**

Add a test that records checkpoint state before and after a node run and can load the latest checkpoint for a run id.

Run:

```powershell
Push-Location python; python -m pytest tests/test_run_journal.py::test_run_journal_persists_latest_checkpoint -q; Pop-Location
```

Expected before implementation:

```text
FAIL because checkpoint APIs do not exist
```

- [ ] **Step 4.2: Add checkpoint model**

Add a checkpoint record with run id, node id, status, completed outputs, pending nodes, created time, and recovery count.

- [ ] **Step 4.3: Add low-risk continue loop**

Allow one controlled continue when `FailureReplanner` proposes a patch marked low risk. Record the patch and retry decision in the journal.

- [ ] **Step 4.4: Phase gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_run_journal.py tests/test_execution.py tests/test_replan.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected all commands exit 0.

## Phase 5: Planner ReAct And Memory Defaults

**Files:**

- Modify: `python/agent_service/planner_chain.py`
- Modify: `python/agent_service/tool_catalog_planner.py`
- Modify: `python/agent_service/context_manager.py`
- Modify: `python/agent_service/graph.py`
- Modify: `python/agent_service/execution.py`
- Test: `python/tests/test_planner_chain.py`
- Test: `python/tests/test_tool_catalog_planner.py`
- Test: `python/tests/test_graph.py`
- Test: `python/tests/test_memory_store.py`
- Test: `python/tests/test_react_controller.py`

- [ ] **Step 5.1: Write failing planner ReAct policy test**

Add a planner test asserting tool-exploration model nodes receive bounded `metadata.react` with allowed tool ids and permissions.

Run:

```powershell
Push-Location python; python -m pytest tests/test_planner_chain.py::test_planner_chain_emits_bounded_react_policy_for_tool_exploration -q; Pop-Location
```

Expected before implementation:

```text
FAIL because planner output lacks react metadata
```

- [ ] **Step 5.2: Write failing memory planning test**

Add a graph test asserting `MemoryStore.list()` records are passed to `build_context_bundle()` during task planning.

Run:

```powershell
Push-Location python; python -m pytest tests/test_graph.py::test_task_planning_loads_project_memory_by_default -q; Pop-Location
```

Expected before implementation:

```text
FAIL because graph planning does not read MemoryStore
```

- [ ] **Step 5.3: Implement bounded ReAct policy generation**

PlannerChain should attach ReAct metadata only for model nodes that need tool exploration. Use candidate tool ids and approved low-risk permissions.

- [ ] **Step 5.4: Load memory into planning context**

`_graph_payload_for_task()` should read project memory from the real project path when available and pass records into `build_context_bundle()`.

- [ ] **Step 5.5: Write tool outcome memory on success and failure**

Extend execution memory writes so successful and failed tool outcomes become memory records with safe summaries and source refs.

- [ ] **Step 5.6: Phase gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_planner_chain.py tests/test_tool_catalog_planner.py tests/test_graph.py tests/test_memory_store.py tests/test_react_controller.py tests/test_execution.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected all commands exit 0.

## Phase 6: MCP Provider Activation

**Files:**

- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/agent_service/tool_providers/mcp.py`
- Modify: `python/agent_service/app.py`
- Modify: `src-tauri/src/commands.rs`
- Modify: `src-tauri/src/preferences.rs`
- Test: `python/tests/test_mcp_tool_provider.py`
- Test: `python/tests/test_tool_gateway.py`
- Test: `src-tauri/tests/preferences_tests.rs`
- Test: `src-tauri/tests/tool_provider_commands_tests.rs`

- [ ] **Step 6.1: Write failing gateway MCP provider loading test**

Add a Python test asserting default gateway construction can include enabled MCP providers supplied by config.

Run:

```powershell
Push-Location python; python -m pytest tests/test_tool_gateway.py::test_default_gateway_loads_enabled_mcp_providers_from_config -q; Pop-Location
```

Expected before implementation:

```text
FAIL because default gateway only has internal provider
```

- [ ] **Step 6.2: Write failing Rust refresh test**

Update Rust command tests so enabled MCP provider refresh returns discovered tools from a test connector rather than `Vec::new()`.

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml refresh_mcp_tool_provider_tools --test tool_provider_commands_tests
```

Expected before implementation:

```text
FAIL because refresh returns an empty vector
```

- [ ] **Step 6.3: Add MCP provider config handoff**

Wire non-secret provider config into sidecar requests where the current architecture already sends model/tool config. Keep credentials out of project files and logs.

- [ ] **Step 6.4: Enforce MCP authority**

Require `call_external_mcp_tool` plus provider/tool allow-list authority before MCP calls.

- [ ] **Step 6.5: Phase gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_mcp_tool_provider.py tests/test_tool_gateway.py tests/test_model_tool_adapter.py -q; Pop-Location
cargo test --manifest-path src-tauri/Cargo.toml --test preferences_tests --test tool_provider_commands_tests
git diff --check
```

Expected all commands exit 0.

## Phase 7: Claim Evidence Graph

**Files:**

- Modify: `python/agent_service/research_evidence.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/eval_harness.py`
- Modify: `python/evals/research_cases.jsonl`
- Test: `python/tests/test_research_evidence.py`
- Test: `python/tests/test_execution.py`
- Test: `python/tests/test_eval_harness.py`

- [ ] **Step 7.1: Write failing structured claim test**

Add a test asserting synthesis produces `ResearchClaim` records with evidence refs, support status, and source excerpt refs before Markdown rendering.

Run:

```powershell
Push-Location python; python -m pytest tests/test_research_evidence.py::test_research_claims_bind_to_source_excerpts -q; Pop-Location
```

Expected before implementation:

```text
FAIL because claims do not track excerpt support
```

- [ ] **Step 7.2: Add claim/evidence models**

Extend `ResearchClaim` and `EvidenceRef` with excerpt, support status, and diagnostics. Keep serialization backward compatible.

- [ ] **Step 7.3: Generate claims before Markdown**

Research synthesis should build claims from accepted evidence, validate them, then render Markdown from claims.

- [ ] **Step 7.4: Add research eval metric**

Eval details should include claim count, unsupported claim count, and citation support pass/fail.

- [ ] **Step 7.5: Phase gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_research_evidence.py tests/test_execution.py::test_research_report_synthesis_includes_source_citations tests/test_eval_harness.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected all commands exit 0.

## Phase 8: Frontend Runtime Observability

**Files:**

- Modify: `src/shared/events.ts`
- Modify: `src/shared/types.ts`
- Modify: `src/features/task/useGraphRunController.ts`
- Modify: `src/features/task/useGraphRuntimeController.ts`
- Modify: `src/features/permissions/usePermissionController.ts`
- Test: `src/features/task/useGraphRunController.test.ts`
- Test: `src/features/task/useGraphRuntimeController.test.ts`
- Test: `src/features/permissions/usePermissionController.test.ts`

- [ ] **Step 8.1: Write failing event handling tests**

Add tests for checkpoint, authority decision, and recovery action events updating the existing runtime state without breaking current graph run events.

Run:

```powershell
npm run frontend:test -- src/features/task/useGraphRunController.test.ts src/features/task/useGraphRuntimeController.test.ts src/features/permissions/usePermissionController.test.ts
```

Expected before implementation:

```text
FAIL because the new events are not represented in frontend state
```

- [ ] **Step 8.2: Add event types**

Add typed event payloads for checkpoint recorded, authority denied/allowed summary, and recovery action proposed/applied.

- [ ] **Step 8.3: Update controllers**

Store the new runtime observability data alongside existing run records. Keep UI rendering changes minimal unless existing components require labels.

- [ ] **Step 8.4: Phase gate**

Run:

```powershell
npm run frontend:lint
npm run frontend:test -- src/features/task/useGraphRunController.test.ts src/features/task/useGraphRuntimeController.test.ts src/features/permissions/usePermissionController.test.ts
git diff --check
```

Expected all commands exit 0.

## Phase 9: Final Gate

**Files:**

- Modify: `README.md`
- Modify: `docs/agent-development-optimization-2026-05-30.md`
- Modify: `docs/superpowers/progress/2026-05-30-agent-runtime-closed-loop-progress.md`

- [ ] **Step 9.1: Update docs**

Update README limitations and the optimization document with the implemented phase status and remaining risks.

- [ ] **Step 9.2: Full verification**

Run:

```powershell
git diff --check
npm run agent:eval
Push-Location python; python -m pytest -q; Pop-Location
npm run frontend:lint
npm run frontend:test
cargo test --manifest-path src-tauri/Cargo.toml
powershell -ExecutionPolicy Bypass -File scripts/verify-mvp.ps1
```

Expected all commands exit 0.

- [ ] **Step 9.3: Final review**

Run:

```powershell
git status --short
git diff --stat
git diff -- docs/agent-development-optimization-2026-05-30.md README.md docs/superpowers/progress/2026-05-30-agent-runtime-closed-loop-progress.md
```

Expected:

```text
Only intended source, test, eval, and documentation files are modified
Progress document marks every phase complete
Residual risks are explicitly recorded
```
