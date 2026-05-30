# Alita Agent Runtime Goal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the verified Alita Agent optimization document into a staged implementation program with review gates, then execute each phase only after its verification gate passes.

**Architecture:** Keep the root `main` worktree as the synchronized baseline and perform implementation in `D:\Software Project\Alita\.worktrees\reapply-local-root-changes` on `codex/reapply-local-root-changes`. The work proceeds from low-risk evaluation and contracts into execution bindings, permission enforcement, sandbox hardening, dynamic planning, tool-calling loops, recovery, memory, research evidence, and frontend runtime decomposition.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, LangGraph, pytest, JSONL eval fixtures, React 19, TypeScript, Vitest, Tauri 2, Rust tests, PowerShell verification scripts.

---

## Source Of Truth

This plan is derived from:

- `docs/agent-development-optimization-2026-05-30.md`
- `docs/superpowers/plans/2026-05-27-agent-runtime-optimization-plan.md`
- Existing 0.29.0 phase plans from `docs/superpowers/plans/2026-05-28-*` and `docs/superpowers/plans/2026-05-29-*`

The root repository has already been synchronized to `origin/main` at commit `0d058f9`. New work happens on `codex/reapply-local-root-changes` in the isolated worktree.

## Goal Mode Operating Rules

The agent must follow this loop for every phase:

1. Confirm the phase entry conditions with commands.
2. Implement the smallest coherent set of changes for that phase.
3. Run the phase-specific verification commands.
4. Inspect `git diff --stat` and relevant source/test diffs.
5. Record phase status in `docs/superpowers/progress/2026-05-30-agent-runtime-goal-progress.md`.
6. Proceed to the next phase only if the phase gate passes.

If a phase fails verification, fix the phase before proceeding. If the same blocker repeats for three consecutive goal turns and no meaningful progress is possible, mark the goal blocked with the exact blocker.

## Phase Map

| Phase | Name | Purpose | Primary Gate |
| --- | --- | --- | --- |
| 0 | Plan Suite And Baseline | Persist the strategy, create progress tracking, verify synced baseline | Plan docs exist, no placeholders, baseline smoke passes |
| 1 | Eval Gate Expansion | Turn evals into a deterministic quality gate | Router/planner/tool/research/security evals run from one command |
| 2 | Execution Binding V2 | Make `ExecutionGraph` carry real runtime bindings | Binding tests prove operation, args, mappings, artifacts, permissions |
| 3 | Generic Fixed Tool Execution | Remove tool-id branching from planned fixed-tool execution | New manifest fixed tool executes without editing `execution.py` |
| 4 | Authority And Gateway Enforcement | Enforce action-time permissions before provider calls | Permission tests cover paths, writes, network, CLI/script denial |
| 5 | Sandbox Hardening | Reduce temporary script risk inside the local runner contract | Sandbox escape evals and pytest cases pass |
| 6 | Dynamic Planning | Add tool-catalog planning and plan validation repair diagnostics | Planner can produce executable bindings from tool definitions |
| 7 | Tool-Calling Agent Loop | Add API native tool calls and robust local JSON fallback | Tool-call tests execute through `UnifiedToolGateway` |
| 8 | Recovery, Evidence, Memory | Close verifier/replanner loop and improve research/memory | Recovery and claim/evidence evals pass |
| 9 | Frontend Runtime Decomposition | Prepare UI state for multi-run runtime behavior | App controller tests pass and `App.tsx` shrinks materially |
| 10 | Final Release Gate | Run full verification, update docs, summarize residual risk | Python, frontend, Rust, eval, and script gates pass or documented |

## Shared Verification Commands

Run from `D:\Software Project\Alita\.worktrees\reapply-local-root-changes` unless a step says otherwise.

```powershell
git status --short --branch
python -m pytest -q
npm run frontend:lint
npm run frontend:test
cargo test --manifest-path src-tauri/Cargo.toml
powershell -ExecutionPolicy Bypass -File scripts/verify-mvp.ps1
```

For targeted phase gates, run the narrower commands listed in each phase first, then broaden when the phase touches shared runtime behavior.

## Phase 0: Plan Suite And Baseline

**Files:**

- Create: `docs/superpowers/plans/2026-05-30-agent-runtime-goal-implementation-plan.md`
- Create: `docs/superpowers/progress/2026-05-30-agent-runtime-goal-progress.md`
- Keep: `docs/agent-development-optimization-2026-05-30.md`

### Tasks

- [ ] **Step 0.1: Verify worktree baseline**

Run:

```powershell
git status --short --branch
git rev-list --left-right --count main...origin/main
git log --oneline --decorate -1 HEAD
```

Expected:

```text
## codex/reapply-local-root-changes
0 0
0d058f9 ... Merge pull request #3 ...
```

The branch name may include untracked docs. Runtime files must not be modified before this phase starts.

- [ ] **Step 0.2: Persist progress tracker**

Create `docs/superpowers/progress/2026-05-30-agent-runtime-goal-progress.md` with:

```markdown
# Agent Runtime Goal Progress

Started: 2026-05-30
Worktree: `D:\Software Project\Alita\.worktrees\reapply-local-root-changes`
Branch: `codex/reapply-local-root-changes`
Baseline: `0d058f9`

| Phase | Status | Evidence | Next Action |
| --- | --- | --- | --- |
| 0 Plan Suite And Baseline | in_progress | Plan file created | Run placeholder scan and baseline smoke |
| 1 Eval Gate Expansion | pending | | Wait for Phase 0 gate |
| 2 Execution Binding V2 | pending | | Wait for Phase 1 gate |
| 3 Generic Fixed Tool Execution | pending | | Wait for Phase 2 gate |
| 4 Authority And Gateway Enforcement | pending | | Wait for Phase 3 gate |
| 5 Sandbox Hardening | pending | | Wait for Phase 4 gate |
| 6 Dynamic Planning | pending | | Wait for Phase 5 gate |
| 7 Tool-Calling Agent Loop | pending | | Wait for Phase 6 gate |
| 8 Recovery, Evidence, Memory | pending | | Wait for Phase 7 gate |
| 9 Frontend Runtime Decomposition | pending | | Wait for Phase 8 gate |
| 10 Final Release Gate | pending | | Wait for Phase 9 gate |
```

- [ ] **Step 0.3: Scan docs for plan placeholders**

Run:

```powershell
$patterns = @('T' + 'BD', 'TO' + 'DO', 'FIX' + 'ME', '待补', '占位')
Select-String -LiteralPath docs\agent-development-optimization-2026-05-30.md,docs\superpowers\plans\2026-05-30-agent-runtime-goal-implementation-plan.md,docs\superpowers\progress\2026-05-30-agent-runtime-goal-progress.md -Pattern $patterns
```

Expected: no matches.

- [ ] **Step 0.4: Run baseline deterministic smoke**

Run:

```powershell
Push-Location python
python -m agent_service.eval_harness --cases evals/router_cases.jsonl --output ..\.codex-run\evals\phase-0-router
Pop-Location
python -m pytest -q python\tests\test_package_metadata.py python\tests\test_router_v2.py python\tests\test_execution_graph.py python\tests\test_tool_gateway.py
```

Expected:

```text
Agent eval summary: 1/1 passed, 0 failed.
...
passed
```

- [ ] **Step 0.5: Mark Phase 0 complete**

Update the progress tracker row:

```markdown
| 0 Plan Suite And Baseline | complete | Placeholder scan clean; router eval passed; targeted pytest passed | Enter Phase 1 |
```

## Phase 1: Eval Gate Expansion

**Files:**

- Modify: `python/agent_service/eval_harness.py`
- Modify: `python/evals/router_cases.jsonl`
- Modify: `python/evals/planner_cases.jsonl`
- Modify: `python/evals/tool_cases.jsonl`
- Modify: `python/evals/research_cases.jsonl`
- Create: `python/evals/security_cases.jsonl`
- Modify: `python/tests/test_eval_harness.py`
- Modify: `scripts/verify-mvp.ps1`
- Modify: `package.json`

### Design

Add enough deterministic eval coverage to make runtime refactors measurable. Phase 1 does not call external model APIs and does not require network. It adds security eval categories using local sandbox/permission fixtures and lets the harness run one file or a directory of JSONL cases.

### Tasks

- [ ] Add `security` to `EvalCase.category`.
- [ ] Add `--cases-dir` CLI support that loads every `*.jsonl` file in deterministic order.
- [ ] Add summary metrics by category in `EvalRunSummary`.
- [ ] Add security case handling for permission and sandbox expectations.
- [ ] Expand each existing JSONL file to at least 10 cases.
- [ ] Add `python/evals/security_cases.jsonl` with at least 10 cases.
- [ ] Add `npm` script `"agent:eval": "cd python && python -m agent_service.eval_harness --cases-dir evals --output ..\\.codex-run\\evals\\all"`.
- [ ] Update `scripts/verify-mvp.ps1` to run all deterministic eval cases, not only router smoke.

### Verification

Run:

```powershell
python -m pytest -q python\tests\test_eval_harness.py python\tests\test_sandbox.py python\tests\test_permission_gate.py
npm run agent:eval
powershell -ExecutionPolicy Bypass -File scripts/verify-mvp.ps1
```

Gate:

- All eval categories report pass.
- `summary.json` includes category totals.
- `verify-mvp.ps1` fails if any deterministic eval fails.

## Phase 2: Execution Binding V2

**Files:**

- Modify: `python/agent_service/execution_graph.py`
- Modify: `python/agent_service/schemas.py`
- Modify: `python/agent_service/tool_protocol.py`
- Modify: `python/tests/test_execution_graph.py`
- Modify: `python/tests/test_graph_compiler.py`

### Design

Move runtime binding information out of implicit Python branches and into typed execution graph contracts. The compiler must represent operation, argument template, input mappings, output schema, expected artifacts, and permission scope.

### Tasks

- [ ] Add `ExecutionArgumentTemplate`, `ExecutionInputMapping`, `ExpectedArtifact`, and `ExecutionPermissionScope` models.
- [ ] Extend `ExecutionToolBinding` with `provider_id`, `operation`, `arguments_template`, `input_mappings`, `output_schema`, `expected_artifacts`, and `permission_scope`.
- [ ] Compile document tool operations from tool manifests where possible.
- [ ] Preserve compatibility for existing graph payloads by deriving default operations from known manifest operation names.
- [ ] Validate duplicate node ids, missing dependencies, and unsupported fixed-tool bindings.
- [ ] Add tests that assert `document.markitdown_convert` compiles to `convert_local_file`.
- [ ] Add tests that assert `document.typst_compile` compiles to `compile_report_pdf`.

### Verification

Run:

```powershell
python -m pytest -q python\tests\test_execution_graph.py python\tests\test_graph_compiler.py python\tests\test_execution_gateway_integration.py
```

Gate:

- Binding models are typed and covered.
- Existing document and planned task graphs still compile.
- No public `RunGraph` schema compatibility is broken.

## Phase 3: Generic Fixed Tool Execution

**Files:**

- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/tests/test_execution.py`
- Modify: `python/tests/test_execution_gateway_integration.py`
- Create: `tool-packages/test_echo/manifest.json`

### Design

Replace hard-coded fixed-tool execution with a generic binding renderer. A fixed-tool node should execute if its binding is valid and its arguments can be rendered from attachments, graph metadata, constants, or upstream `NodeOutput` values.

### Tasks

- [ ] Add a small test-only manifest tool with operation `echo_values`.
- [ ] Add a test graph containing a `fixed_tool` node bound to the test tool.
- [ ] Implement argument rendering from binding templates and input mappings.
- [ ] Route the rendered invocation through `UnifiedToolGateway.call_tool()`.
- [ ] Keep document flow compatibility by producing the same output values/artifacts as before.
- [ ] Remove document tool id branching from `PlannedTaskExecutor._run_fixed_tool_node()`.

### Verification

Run:

```powershell
python -m pytest -q python\tests\test_execution.py python\tests\test_execution_gateway_integration.py python\tests\test_tool_execution.py
```

Gate:

- A new manifest fixed tool executes without adding a new `if tool_id == ...` branch.
- Existing document conversion and Typst export tests pass.

## Phase 4: Authority And Gateway Enforcement

**Files:**

- Create: `python/agent_service/authority.py`
- Modify: `python/agent_service/permission_gate.py`
- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/agent_service/tool_protocol.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_permission_gate.py`
- Modify: `python/tests/test_tool_gateway.py`
- Create: `python/tests/test_authority.py`

### Design

Convert permission checks from static permission strings into action-time authorization. The gateway checks actual invocation arguments before provider execution.

### Tasks

- [ ] Add `AuthorityContext` with approved tools, permissions, read roots, write roots, network domains, and runtime budget.
- [ ] Add path extraction helpers for common argument names: `input_path`, `output_path`, `source_output_path`, `pdf_output_path`, `paths`.
- [ ] Default deny `read_project_files`, `run_local_cli`, `run_python_plugin`, network, and project writes.
- [ ] Allow `read_attachment` and artifact writes only when paths are inside approved roots.
- [ ] Add gateway enforcement before provider dispatch.
- [ ] Add audit metadata for allow/deny decisions.

### Verification

Run:

```powershell
python -m pytest -q python\tests\test_authority.py python\tests\test_permission_gate.py python\tests\test_tool_gateway.py python\tests\test_execution.py
```

Gate:

- Tool calls with path traversal are denied before provider execution.
- Existing approved document flow can run with the correct authority context.
- Default permission set is least privilege.

## Phase 5: Sandbox Hardening

**Files:**

- Modify: `python/agent_service/sandbox.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_sandbox.py`
- Modify: `python/evals/security_cases.jsonl`

### Design

Keep the local subprocess runner contract but reduce easy escapes and resource abuse. This phase does not claim to create a production-grade OS sandbox.

### Tasks

- [ ] Add max script bytes.
- [ ] Add max stdout/stderr bytes.
- [ ] Add max artifact count.
- [ ] Add max artifact size.
- [ ] Reject scripts containing direct file reads outside brokered input paths when detected by AST calls to `open`, `Path.open`, and `read_text`.
- [ ] Deny environment access for secret-looking keys.
- [ ] Add structured error codes for output too large, artifact too large, too many artifacts, and forbidden file API.
- [ ] Add security eval cases for network import, dynamic import, path escape, env access, process launch, oversized output, and artifact escape.

### Verification

Run:

```powershell
python -m pytest -q python\tests\test_sandbox.py python\tests\test_execution.py::test_temporary_script_node_runs_low_risk_script_in_sandbox
npm run agent:eval
```

Gate:

- Known sandbox escape attempts fail with explicit error codes.
- Low-risk approved script execution still works.

## Phase 6: Dynamic Planning

**Files:**

- Create: `python/agent_service/tool_catalog_planner.py`
- Modify: `python/agent_service/planner_chain.py`
- Modify: `python/agent_service/plan_validator.py`
- Modify: `python/agent_service/context_manager.py`
- Modify: `python/tests/test_planner_chain.py`
- Create: `python/tests/test_tool_catalog_planner.py`
- Modify: `python/evals/planner_cases.jsonl`

### Design

Add a planner that can create executable fixed-tool graph nodes from `UnifiedToolDefinition` entries, not from hard-coded task templates.

### Tasks

- [ ] Define `ToolCatalogPlanningRequest` and `ToolCatalogPlanningResult`.
- [ ] Select candidate tools from `ContextBundle.available_tools`.
- [ ] Create node payloads with `toolRef`, input ports, output ports, permissions, and execution binding metadata.
- [ ] Emit diagnostics for missing inputs, missing permissions, and schema mismatch.
- [ ] Insert the tool-catalog planner between document template and legacy fallback.
- [ ] Add planner eval cases for supported and unsupported tool tasks.

### Verification

Run:

```powershell
python -m pytest -q python\tests\test_tool_catalog_planner.py python\tests\test_planner_chain.py python\tests\test_plan_validator.py
npm run agent:eval
```

Gate:

- At least one non-document tool plan is created from tool catalog definitions.
- Unsupported plans fail before execution with actionable diagnostics.

## Phase 7: Tool-Calling Agent Loop

**Files:**

- Modify: `python/agent_service/model_client.py`
- Modify: `python/agent_service/model_tool_adapter.py`
- Modify: `python/agent_service/react_controller.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_model_client.py`
- Modify: `python/tests/test_model_tool_adapter.py`
- Modify: `python/tests/test_react_controller.py`
- Modify: `python/tests/test_execution.py`

### Design

Support provider-native tool calls for API models and a tolerant strict-JSON fallback for local models. All tool execution remains gateway-mediated.

### Tasks

- [ ] Add `chat_with_tools()` protocol and return type for tool calls.
- [ ] Add OpenAI-compatible payload fields `tools` and `tool_choice`.
- [ ] Parse `choices[0].message.tool_calls`.
- [ ] Convert tool call names using `ModelToolNameMap`.
- [ ] Route tool calls through `execute_model_tool_calls()`.
- [ ] Add JSON object extraction fallback to `ReActController._parse_action()`.
- [ ] Preserve current plain chat behavior.

### Verification

Run:

```powershell
python -m pytest -q python\tests\test_model_client.py python\tests\test_model_tool_adapter.py python\tests\test_react_controller.py python\tests\test_execution.py::test_react_enabled_model_node_records_observations
```

Gate:

- API tool call payloads and parser are tested without live network.
- Local JSON fallback accepts wrapped JSON and rejects ambiguous output.
- Every tool call enters `UnifiedToolGateway`.

## Phase 8: Recovery, Evidence, Memory

**Files:**

- Modify: `python/agent_service/replan.py`
- Modify: `python/agent_service/result_verifier.py`
- Modify: `python/agent_service/final_verifier.py`
- Modify: `python/agent_service/research_evidence.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/memory_store.py`
- Modify: `python/agent_service/context_manager.py`
- Modify: `python/tests/test_replan.py`
- Modify: `python/tests/test_result_verifier.py`
- Modify: `python/tests/test_research_evidence.py`
- Modify: `python/tests/test_memory_store.py`
- Modify: `python/evals/research_cases.jsonl`

### Design

Make observation, verification, recovery, claim evidence, and memory records feed each other without making the agent opaque. Recovery stays conservative and auditable.

### Tasks

- [ ] Add `RecoveryAction` for retry, replace tool, fix arguments, and ask user.
- [ ] Record verifier diagnostics in `RunJournal`.
- [ ] Add low-risk automatic retry for empty model output and missing expected artifact.
- [ ] Add `ResearchClaim`, `EvidenceRef`, and claim-level citation diagnostics.
- [ ] Add memory auto-write for run summaries, artifact summaries, and tool outcomes.
- [ ] Add memory source refs and deletion-safe record ids.

### Verification

Run:

```powershell
python -m pytest -q python\tests\test_replan.py python\tests\test_result_verifier.py python\tests\test_research_evidence.py python\tests\test_memory_store.py python\tests\test_execution.py
npm run agent:eval
```

Gate:

- Recovery actions are explicit and journaled.
- Research reports fail diagnostics when key claims lack evidence.
- Memory records are sanitized and retrievable by relevant context.

## Phase 9: Frontend Runtime Decomposition

**Files:**

- Modify: `src/app/App.tsx`
- Create: `src/features/project/useProjectController.ts`
- Create: `src/features/project/useProjectController.test.ts`
- Create: `src/features/chat/useChatSessionController.ts`
- Create: `src/features/chat/useChatSessionController.test.ts`
- Create: `src/features/task/useGraphRuntimeController.ts`
- Create: `src/features/task/useGraphRuntimeController.test.ts`
- Create: `src/features/permissions/usePermissionController.ts`
- Create: `src/features/permissions/usePermissionController.test.ts`
- Modify: `src/app/App.test.tsx`

### Design

Keep UI behavior stable while moving domain workflows out of `App.tsx`. This phase prepares for multiple active/background runs.

### Tasks

- [ ] Extract project open/create/save/recent state into `useProjectController`.
- [ ] Extract chat draft, pending attachments, and context attachments into `useChatSessionController`.
- [ ] Extract graph running/cancelling/run id refs into `useGraphRuntimeController`.
- [ ] Add `usePermissionController` for future approval prompts and current pending choice coordination.
- [ ] Keep `App.tsx` as composition and wiring.
- [ ] Add tests for each controller's reducer/action behavior.

### Verification

Run:

```powershell
npm run frontend:lint
npm run frontend:test -- --run src/features/project/useProjectController.test.ts src/features/chat/useChatSessionController.test.ts src/features/task/useGraphRuntimeController.test.ts src/features/permissions/usePermissionController.test.ts src/app/App.test.tsx
```

Gate:

- Controller tests pass.
- Existing app smoke render passes.
- `App.tsx` line count is lower than the pre-phase count.

## Phase 10: Final Release Gate

**Files:**

- Modify: `docs/agent-development-optimization-2026-05-30.md`
- Modify: `docs/superpowers/progress/2026-05-30-agent-runtime-goal-progress.md`
- Modify: `docs/mvp-verification.md`
- Modify: `README.md`

### Tasks

- [ ] Update the optimization document with implementation status per phase.
- [ ] Update progress tracker with final evidence.
- [ ] Update README current limitations and verification section.
- [ ] Update MVP verification docs with eval gate commands.
- [ ] Run broad verification.
- [ ] Summarize residual risk and next recommended PRs.

### Verification

Run:

```powershell
python -m pytest -q
npm run frontend:lint
npm run frontend:test
npm run agent:eval
cargo test --manifest-path src-tauri/Cargo.toml
powershell -ExecutionPolicy Bypass -File scripts/verify-mvp.ps1
git status --short --branch
git diff --stat
```

Gate:

- All required verification commands pass, or any failure is documented with exact command output and a follow-up phase.
- Progress tracker marks all phases complete.
- The worktree contains only intentional changes.
