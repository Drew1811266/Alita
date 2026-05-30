# Agent Runtime V032 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the 0.32.0 optimization audit into a staged implementation that upgrades Alita's default agent runtime, checkpoint controls, authority grants, provider runtime, MCP lifecycle, planner quality, trace observability, sandbox posture, and eval gates.

**Architecture:** Keep Alita's visible graph workbench and existing API contracts stable while adding a thin `AgentRuntimeGraph` orchestration layer above the current graph-run executor. Existing runtime pieces such as `PlannerChain`, `ExecutionGraph`, `UnifiedToolGateway`, `RunJournal`, `RuntimeCheckpoint`, `AuthorityContext`, `ToolRuntimeLoader`, and deterministic evals remain the foundation; each phase exposes one additional durable primitive and verifies it before continuing.

**Tech Stack:** Python 3.10+ FastAPI/Pydantic/pytest, LangGraph, React 19/TypeScript/Vitest, Tauri 2/Rust tests, local JSON run journals, MCP provider abstractions, Windows-first constrained execution.

---

## Execution Rules

- Worktree: `D:\Software Project\Alita\.worktrees\agent-runtime-v032-implementation`.
- Branch: `codex/agent-runtime-v032-implementation`.
- Source audit: `docs/agent-development-optimization-2026-05-30-v032.md`.
- Progress tracker: `docs/superpowers/progress/2026-05-30-agent-runtime-v032-progress.md`.
- Every phase starts with tests that fail for the intended missing behavior, then implementation, then the phase gate.
- A phase is not complete until its gate passes and the progress tracker is updated.
- If a gate fails twice for the same root cause, stop and investigate before entering the next phase.
- Keep public request/response schemas backward-compatible unless the phase explicitly adds optional fields.

## Phase Overview

| Phase | Name | Outcome | Gate |
| --- | --- | --- | --- |
| 0 | Baseline And Documentation Alignment | Worktree baseline verified, README/version docs corrected, progress tracker created | `git diff --check`, doc scans, baseline eval/typecheck |
| 1 | Runtime Trace Primitives | Add trace span model and attach spans to checkpoints, authority decisions, recovery actions, and tool observations | Python runtime event/tool gateway tests |
| 2 | Checkpoint Control API | Support listing checkpoints and resuming from a specific `checkpoint_id` | Run journal and execution resume tests |
| 3 | AgentRuntimeGraph Skeleton | Add default state-machine wrapper for route -> plan -> execute -> final without replacing graph UI | Agent runtime graph tests |
| 4 | Explicit AuthorityGrant | Add request-level authority grants for permissions, tools, roots, domains, and budgets | Authority/gateway/execution/security eval tests |
| 5 | Provider Runtime Normalization | Add runtime enum/loader paths for builtin, python_function, python_script, cli, and migrate document tools where low-risk | Tool execution/gateway tests |
| 6 | MCP Lifecycle Handoff | Add sidecar-facing MCP config models, fake stdio/http client lifecycle, and planner context injection | MCP provider/context/planner tests |
| 7 | Schema-Aware Tool Planner | Replace token-only planning with schema-required argument binding and simple multi-tool DAG support | Tool catalog planner/eval tests |
| 8 | Sandbox Posture Upgrade | Add Windows Job Object capability probe and enforced constrained-runner metadata without claiming OS isolation | Sandbox/security eval tests |
| 9 | Model-In-Loop Eval Harness Skeleton | Add optional model-in-loop eval category and trace summary artifacts while keeping deterministic PR gate | Eval harness tests |
| 10 | Final Gate | Full regression pass and docs update | Python, frontend, Rust, eval, diff check |

## Phase 0: Baseline And Documentation Alignment

**Files:**
- Modify: `README.md`
- Create: `docs/superpowers/progress/2026-05-30-agent-runtime-v032-progress.md`
- Verify: `package.json`, `python/pyproject.toml`, `src-tauri/Cargo.toml`, `src-tauri/tauri.conf.json`

- [x] **Step 0.1: Confirm baseline commands**

Run:

```powershell
npm run agent:eval
Push-Location python; python -m pytest tests/test_authority.py tests/test_tool_gateway.py tests/test_execution.py -q; Pop-Location
npm run frontend:typecheck
```

Expected:

```text
Agent eval summary: 63/63 passed, 0 failed.
99 passed
frontend:typecheck exits 0
```

- [x] **Step 0.2: Update README version**

Edit `README.md` so the current version line says:

```markdown
当前仓库版本为 `0.32.0`。
```

Also update the limitations section so checkpoint resume is no longer described as entirely future work. The accurate wording is:

```markdown
- run checkpoint、低风险自动继续和 latest checkpoint resume 已经存在；指定 checkpoint resume、rollback、后台多 run 队列和 memory 管理 UI 仍属于后续增强项。
```

- [x] **Step 0.3: Create progress tracker**

Create `docs/superpowers/progress/2026-05-30-agent-runtime-v032-progress.md` with this table:

```markdown
# Agent Runtime V032 Implementation Progress

Started: 2026-05-30
Worktree: `D:\Software Project\Alita\.worktrees\agent-runtime-v032-implementation`
Branch: `codex/agent-runtime-v032-implementation`
Baseline: `f329991`

| Phase | Status | Evidence | Next Action |
| --- | --- | --- | --- |
| 0 Baseline And Documentation Alignment | in_progress | Baseline commands started | Complete Phase 0 gate |
| 1 Runtime Trace Primitives | pending | | Wait for Phase 0 |
| 2 Checkpoint Control API | pending | | Wait for Phase 1 |
| 3 AgentRuntimeGraph Skeleton | pending | | Wait for Phase 2 |
| 4 Explicit AuthorityGrant | pending | | Wait for Phase 3 |
| 5 Provider Runtime Normalization | pending | | Wait for Phase 4 |
| 6 MCP Lifecycle Handoff | pending | | Wait for Phase 5 |
| 7 Schema-Aware Tool Planner | pending | | Wait for Phase 6 |
| 8 Sandbox Posture Upgrade | pending | | Wait for Phase 7 |
| 9 Model-In-Loop Eval Harness Skeleton | pending | | Wait for Phase 8 |
| 10 Final Gate | pending | | Wait for Phase 9 |

## Phase Notes
```

- [x] **Step 0.4: Run Phase 0 gate**

Run:

```powershell
git diff --check
$patterns = @("当前仓库版本为 ``0\." + "31\.0``", "TB" + "D", "待" + "补", "place" + "holder", "fill" + " in")
foreach ($pattern in $patterns) { rg -n $pattern README.md docs/superpowers/plans/2026-05-30-agent-runtime-v032-implementation-plan.md docs/superpowers/progress/2026-05-30-agent-runtime-v032-progress.md }
npm run agent:eval
```

Expected:

```text
git diff --check exits 0
rg exits 1 with no matches
Agent eval summary: 63/63 passed, 0 failed.
```

Update the progress row to `complete` only after all three commands match expectations.

## Phase 1: Runtime Trace Primitives

**Files:**
- Create: `python/agent_service/runtime_trace.py`
- Modify: `python/agent_service/runtime_events.py`
- Modify: `python/agent_service/tool_observation.py`
- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/agent_service/execution.py`
- Test: `python/tests/test_runtime_trace.py`
- Test: `python/tests/test_tool_gateway.py`
- Test: `python/tests/test_execution.py`

- [x] **Step 1.1: Write failing trace model tests**

Create `python/tests/test_runtime_trace.py`:

```python
from agent_service.runtime_trace import RuntimeSpan, next_span_id, trace_id_for_run


def test_trace_id_is_stable_for_run():
    assert trace_id_for_run("run-123") == "trace-run-123"


def test_span_record_uses_camel_case_payload():
    span = RuntimeSpan(
        trace_id="trace-run-1",
        span_id="span-000001",
        parent_span_id=None,
        run_id="run-1",
        node_id="node-a",
        kind="tool_call",
        name="internal:test.echo_values",
        status="ok",
        started_at="2026-05-30T00:00:00Z",
        ended_at="2026-05-30T00:00:01Z",
        duration_ms=1000,
        metadata={"ok": True},
    )

    assert span.to_record() == {
        "traceId": "trace-run-1",
        "spanId": "span-000001",
        "parentSpanId": None,
        "runId": "run-1",
        "nodeId": "node-a",
        "kind": "tool_call",
        "name": "internal:test.echo_values",
        "status": "ok",
        "startedAt": "2026-05-30T00:00:00Z",
        "endedAt": "2026-05-30T00:00:01Z",
        "durationMs": 1000,
        "metadata": {"ok": True},
    }


def test_next_span_id_is_deterministic_for_counter():
    assert next_span_id(1) == "span-000001"
    assert next_span_id(42) == "span-000042"
```

- [x] **Step 1.2: Run trace tests to verify RED**

Run:

```powershell
Push-Location python; python -m pytest tests/test_runtime_trace.py -q; Pop-Location
```

Expected: fails with `ModuleNotFoundError: No module named 'agent_service.runtime_trace'`.

- [x] **Step 1.3: Implement runtime trace model**

Create `python/agent_service/runtime_trace.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def trace_id_for_run(run_id: str) -> str:
    return f"trace-{run_id}"


def next_span_id(counter: int) -> str:
    return f"span-{counter:06d}"


@dataclass(frozen=True)
class RuntimeSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    run_id: str
    node_id: str | None
    kind: str
    name: str
    status: str
    started_at: str
    ended_at: str | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_span_id,
            "runId": self.run_id,
            "nodeId": self.node_id,
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "durationMs": self.duration_ms,
            "metadata": dict(self.metadata),
        }
```

- [x] **Step 1.4: Add runtime trace event helper**

Modify `python/agent_service/runtime_events.py` to import `RuntimeSpan` and add:

```python
def runtime_span_recorded_event(span: RuntimeSpan) -> AgentEvent:
    return AgentEvent(
        type="runtime.span_recorded",
        payload={"span": span.to_record()},
    )
```

- [x] **Step 1.5: Attach trace metadata to tool observations**

Modify `python/agent_service/tool_observation.py` so `observation_metadata(...)` accepts optional `trace_id` and `span_id`, then includes them in the `observation` object when provided:

```python
if trace_id is not None:
    observation["traceId"] = trace_id
if span_id is not None:
    observation["spanId"] = span_id
```

Update `tool_gateway.py` calls to pass no trace values yet so existing behavior remains compatible.

- [x] **Step 1.6: Emit node execution spans**

In `python/agent_service/execution.py`, during each node execution:

1. Maintain `span_counter`.
2. Before executing a node, create a span with kind `node_execution`, name `node.nodeId`, status `running`.
3. After success, emit `runtime.span_recorded` with status `ok`.
4. After failure, emit `runtime.span_recorded` with status `error` and metadata `{"errorCode": payload.get("errorCode")}`.

Use existing `_now_iso()` and `perf_counter()` utilities.

- [x] **Step 1.7: Run Phase 1 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_runtime_trace.py tests/test_tool_gateway.py tests/test_execution.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected:

```text
runtime trace tests pass
existing tool gateway/execution tests pass
Agent eval summary: 63/63 passed, 0 failed.
git diff --check exits 0
```

Update progress before Phase 2.

## Phase 2: Checkpoint Control API

**Files:**
- Modify: `python/agent_service/run_journal.py`
- Modify: `python/agent_service/runtime_loop.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/schemas.py`
- Test: `python/tests/test_run_journal.py`
- Test: `python/tests/test_execution.py`

- [x] **Step 2.1: Write failing checkpoint-id tests**

Add tests asserting:

```python
def test_read_checkpoint_by_id_returns_matching_record(tmp_path):
    journal = RunJournal(project_path=str(tmp_path / "demo.alita"), run_id="run-1")
    journal.write_checkpoint(RuntimeCheckpoint(... node_id="a", status="after_node", ...))
    journal.write_checkpoint(RuntimeCheckpoint(... node_id="b", status="before_node", ...))

    assert journal.read_checkpoint("a:after_node:0")["nodeId"] == "a"
```

Use a generated `checkpointId` field in the expected record. The first run should fail because checkpoints do not have stable IDs.

- [x] **Step 2.2: Add checkpoint IDs**

Update `RuntimeCheckpoint.to_record()` to include:

```python
"checkpointId": f"{self.node_id}:{self.status}:{self.recovery_count}"
```

Add `RunJournal.read_checkpoint(checkpoint_id: str) -> dict[str, Any] | None`.

- [x] **Step 2.3: Use `RunMode.checkpoint_id`**

In `run_graph_events()`, when `request.mode.type == "resume_checkpoint"`:

```python
checkpoint = (
    journal.read_checkpoint(request.mode.checkpoint_id)
    if request.mode.checkpoint_id
    else journal.read_latest_checkpoint()
)
```

If the requested checkpoint is missing, return `missing_checkpoint`.

- [x] **Step 2.4: Run Phase 2 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_run_journal.py tests/test_execution.py tests/test_agent_run_state.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected: tests pass, eval 63/63, diff check clean.

Update progress before Phase 3.

## Phase 3: AgentRuntimeGraph Skeleton

**Files:**
- Create: `python/agent_service/agent_runtime_graph.py`
- Modify: `python/agent_service/graph.py`
- Test: `python/tests/test_agent_runtime_graph.py`
- Test: `python/tests/test_graph.py`

- [x] **Step 3.1: Write failing runtime graph tests**

Create tests for a minimal API:

```python
from agent_service.agent_runtime_graph import AgentRuntimeGraph, AgentRuntimeGraphState


def test_runtime_graph_routes_task_to_planning_state():
    graph = AgentRuntimeGraph()
    state = AgentRuntimeGraphState(task_id="task-1", message="summarize this", project_path="demo.alita")

    result = graph.route(state)

    assert result.stage == "plan"
    assert result.task_id == "task-1"
```

Expected RED: module missing.

- [x] **Step 3.2: Implement skeleton state machine**

Create `agent_runtime_graph.py` with:

- `AgentRuntimeStage = Literal["route", "plan", "execute", "observe", "verify", "replan", "final", "failed"]`
- `AgentRuntimeGraphState` Pydantic model.
- `AgentRuntimeGraph.route()`, `plan_ready()`, `execution_ready()`, `final()` helpers.

Do not replace existing FastAPI endpoints in this phase.

- [x] **Step 3.3: Wire task planning metadata**

In `graph.py`, when task planning creates a graph, add metadata:

```python
"agentRuntime": {"version": "agent_runtime_graph.v1", "stage": "plan"}
```

Keep existing event payloads intact.

- [x] **Step 3.4: Run Phase 3 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_agent_runtime_graph.py tests/test_graph.py tests/test_planner_chain.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected: tests pass, eval 63/63, diff check clean.

Update progress before Phase 4.

## Phase 4: Explicit AuthorityGrant

**Files:**
- Modify: `python/agent_service/authority.py`
- Modify: `python/agent_service/schemas.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/agent_service/eval_harness.py`
- Modify: `python/evals/security_cases.jsonl`
- Test: `python/tests/test_authority.py`
- Test: `python/tests/test_tool_gateway.py`
- Test: `python/tests/test_execution_gateway_integration.py`

- [x] **Step 4.1: Write failing grant tests**

Add tests proving:

- Requested sensitive permission is denied without grant.
- Tool id is denied when `approved_tool_ids` is non-empty and does not include invocation tool.
- Network domain in invocation metadata is denied if absent from grant.
- Runtime budget is copied into observation metadata.

- [x] **Step 4.2: Add API grant schema**

Add `AuthorityGrantPayload` to `schemas.py`:

```python
class AuthorityGrantPayload(BaseModel):
    approved_tool_ids: list[str] = Field(default_factory=list)
    approved_permissions: list[str] = Field(default_factory=list)
    read_roots: list[str] = Field(default_factory=list)
    write_roots: list[str] = Field(default_factory=list)
    network_domains: list[str] = Field(default_factory=list)
    runtime_budget_ms: int | None = None
```

Add optional `authority_grants: list[AuthorityGrantPayload] = Field(default_factory=list)` to `RunGraphRequest`.

- [x] **Step 4.3: Merge grants into runtime authority**

Update `_runtime_authority_context()` in `execution.py`:

```python
base = AuthorityContext(...)
for grant in request.authority_grants:
    merge approved tools, permissions, roots, domains, and minimum runtime budget
return merged
```

Do not remove `approved_permissions`; keep backward compatibility.

- [x] **Step 4.4: Enforce domain/budget metadata**

Extend `UnifiedToolInvocation` with optional metadata:

```python
metadata: JsonObject = field(default_factory=dict)
```

In `authorize_tool_invocation()`, if `metadata["networkDomain"]` exists and not in `context.network_domains`, return `network_domain_denied`.

In `tool_gateway.py`, include `runtimeBudgetMs` in observation when present.

- [x] **Step 4.5: Add security eval case**

Add one JSONL case where `networkDomain` is denied without grant and allowed with grant.

- [x] **Step 4.6: Run Phase 4 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_authority.py tests/test_tool_gateway.py tests/test_execution_gateway_integration.py tests/test_eval_harness.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected: tests pass, eval 64/64 or higher depending on added cases, diff check clean.

Update progress before Phase 5.

## Phase 5: Provider Runtime Normalization

**Files:**
- Modify: `python/agent_service/tool_runtime.py`
- Modify: `python/agent_service/tool_execution.py`
- Modify: `python/agent_service/tool_registry.py`
- Modify: `tool-packages/document/manifest.json`
- Modify: `tool-packages/markitdown/manifest.json`
- Modify: `tool-packages/typst/manifest.json`
- Test: `python/tests/test_tool_execution.py`
- Test: `python/tests/test_tool_registry.py`

- [x] **Step 5.1: Write failing runtime enum tests**

Add tests proving:

- `python_function` entrypoint still works.
- `python_script` runtime rejects missing script file with `unsupported_runtime`.
- `cli` runtime rejects direct execution until an adapter/provider is registered.
- `document.read_write` has operations parsed from manifest.

- [x] **Step 5.2: Add runtime enum constants**

In `tool_runtime.py`, define:

```python
SUPPORTED_TOOL_RUNTIMES = {
    "python_function",
    "python_script",
    "cli",
    "builtin",
    "mcp",
    "python_sidecar",
}
```

Use the manifest runtime to route:

- `python_function`: load `module:function`.
- `builtin` and `python_sidecar`: adapter fallback.
- `python_script`: return controlled unsupported error until implemented.
- `cli`: return controlled unsupported error until provider implemented.
- `mcp`: never handled by internal runtime.

- [x] **Step 5.3: Repair document manifest**

Update `tool-packages/document/manifest.json`:

```json
"runtime": "python_script",
"operations": [
  {"name": "read", "description": "Read local project documents."},
  {"name": "write_markdown", "description": "Write Markdown output."},
  {"name": "write_docx", "description": "Write Word document output."}
]
```

- [x] **Step 5.4: Preserve MarkItDown/Typst compatibility**

Leave `markitdown` and `typst` as `python_sidecar` in this phase so existing adapters keep working. Add comments in tests that migration to non-adapter runtime is a later compatibility cleanup.

- [x] **Step 5.5: Run Phase 5 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_tool_execution.py tests/test_tool_registry.py tests/test_tool_gateway.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected: tests pass, eval gate passes, diff check clean.

Update progress before Phase 6.

## Phase 6: MCP Lifecycle Handoff

**Files:**
- Modify: `python/agent_service/tool_providers/mcp.py`
- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/agent_service/context_manager.py`
- Modify: `python/agent_service/graph.py`
- Modify: `python/agent_service/schemas.py`
- Test: `python/tests/test_mcp_tool_provider.py`
- Test: `python/tests/test_context_manager.py`
- Test: `python/tests/test_planner_chain.py`

- [x] **Step 6.1: Write failing MCP lifecycle tests**

Add a fake client lifecycle test:

```python
class FakeLifecycleClient:
    started = False
    stopped = False
    def start(self): self.started = True
    def health(self): return {"ok": self.started}
    def list_tools(self): ...
    def call_tool(self, name, arguments): ...
    def stop(self): self.stopped = True
```

Assert enabled MCP providers call `start()` before list/call in the test factory path.

- [x] **Step 6.2: Add lifecycle protocol**

In `mcp.py`, extend protocol with optional methods by using `hasattr` calls:

- `start`
- `health`
- `stop`

`McpToolProvider.list_tools()` should call `start()` once lazily before listing.

- [x] **Step 6.3: Add sidecar MCP config payload**

Add optional MCP provider config list to `AgentMessageRequest`:

```python
mcp_provider_configs: list[McpProviderConfigPayload] = Field(default_factory=list)
```

Keep field optional so existing Tauri requests work.

- [x] **Step 6.4: Inject MCP tool capabilities into planning context**

In `graph.py`, when MCP configs are provided with a test client factory, pass discovered tools into `build_context_bundle()` as external tools. In production path without client factory, do not launch external processes yet.

- [x] **Step 6.5: Run Phase 6 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_mcp_tool_provider.py tests/test_context_manager.py tests/test_planner_chain.py tests/test_graph.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected: tests pass, eval gate passes, diff check clean.

Update progress before Phase 7.

## Phase 7: Schema-Aware Tool Planner

**Files:**
- Modify: `python/agent_service/tool_catalog_planner.py`
- Modify: `python/agent_service/planner_chain.py`
- Modify: `python/agent_service/eval_harness.py`
- Modify: `python/evals/planner_cases.jsonl`
- Test: `python/tests/test_tool_catalog_planner.py`
- Test: `python/tests/test_planner_chain.py`

- [x] **Step 7.1: Write failing schema binding tests**

Add tests proving:

- A tool with required `query` binds user message.
- A tool with required `input_paths` and attachments binds attachment paths.
- A tool with required output path binds project artifact path.
- A tool with unmet required field returns diagnostics instead of bad graph.

- [x] **Step 7.2: Implement schema-aware bindings**

Extend `_argument_values_for_tool()`:

- `query/message/text/input/source_text`: user message content.
- `input_path`: first attachment path.
- `input_paths`: all attachment paths.
- `output_path`: `artifacts/{safe_task_id}-{tool_name}.md`.
- `source_output_path`: `artifacts/{safe_task_id}-{tool_name}.typ`.
- `pdf_output_path`: `artifacts/{safe_task_id}-{tool_name}.pdf`.
- `metadata_value`: `tool_catalog`.

Use graph metadata/project path only for relative artifact paths; do not write files during planning.

- [x] **Step 7.3: Add simple multi-tool DAG support**

If two selected tools match and the first tool output schema has `text` while the second requires `source_text` or `report`, create a two-node DAG with dependency and input mapping. Keep this limited to deterministic schema compatibility.

- [x] **Step 7.4: Add eval case**

Add a planner eval where a catalog tool requiring attachment paths produces a graph with a fixed tool node and no missing binding diagnostics.

- [x] **Step 7.5: Run Phase 7 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_tool_catalog_planner.py tests/test_planner_chain.py tests/test_eval_harness.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected: tests pass, eval count increases if a case is added, diff check clean.

Update progress before Phase 8.

## Phase 8: Sandbox Posture Upgrade

**Files:**
- Modify: `python/agent_service/sandbox.py`
- Modify: `python/agent_service/eval_harness.py`
- Modify: `python/evals/security_cases.jsonl`
- Test: `python/tests/test_sandbox.py`
- Test: `python/tests/test_eval_harness.py`

- [x] **Step 8.1: Write failing posture tests**

Add tests asserting `SandboxResult` exposes:

```python
security_model == "constrained_subprocess_runner"
security_boundary == "preflight_and_runtime_limits_not_os_isolation"
is_os_isolated is False
is_process_tree_limited is False unless a backend enables it
```

- [x] **Step 8.2: Add capability flags**

Extend `SandboxResult` with:

- `is_os_isolated: bool = False`
- `is_process_tree_limited: bool = False`
- `backend: str = "subprocess"`

Ensure result payloads include these fields.

- [x] **Step 8.3: Add Windows Job Object probe function**

Add:

```python
def job_object_backend_available() -> bool:
    return os.name == "nt"
```

Do not claim enforcement yet. The goal is explicit posture metadata and future backend seam.

- [x] **Step 8.4: Add eval case**

Add security eval asserting sandbox posture reports no OS isolation.

- [x] **Step 8.5: Run Phase 8 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_sandbox.py tests/test_eval_harness.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected: tests pass, eval gate passes, diff check clean.

Update progress before Phase 9.

## Phase 9: Model-In-Loop Eval Harness Skeleton

**Files:**
- Modify: `python/agent_service/eval_harness.py`
- Create: `python/evals/model_loop_cases.jsonl`
- Test: `python/tests/test_eval_harness.py`

- [x] **Step 9.1: Write failing model-loop eval tests**

Add tests proving:

- `EvalCase.category` accepts `model_loop`.
- model-loop cases are skipped unless explicitly enabled.
- summary reports skipped count in details without failing deterministic gate.

- [x] **Step 9.2: Implement optional category**

Update eval models:

```python
category: Literal["router", "planner", "tool", "research", "recovery", "security", "model_loop"]
```

Add `_run_model_loop_case()` that returns passed when `ALITA_MODEL_LOOP_EVAL=1` is not set and details include `{"skipped": True}`.

- [x] **Step 9.3: Add skeleton cases**

Create `python/evals/model_loop_cases.jsonl` with one skipped case:

```json
{"case_id":"model-loop-planner-binding-smoke","category":"model_loop","input":{"kind":"planner_binding","content":"Use the echo tool to summarize this text"},"expected":{"skipped":true}}
```

- [x] **Step 9.4: Run Phase 9 gate**

Run:

```powershell
Push-Location python; python -m pytest tests/test_eval_harness.py -q; Pop-Location
npm run agent:eval
git diff --check
```

Expected: deterministic eval includes skipped model-loop case as pass with skipped details, diff check clean.

Update progress before Phase 10.

## Phase 10: Final Gate

**Files:**
- Modify: `README.md`
- Modify: `docs/agent-development-optimization-2026-05-30-v032.md`
- Modify: `docs/superpowers/progress/2026-05-30-agent-runtime-v032-progress.md`

- [x] **Step 10.1: Update docs with implementation results**

Append an implementation result section to `docs/agent-development-optimization-2026-05-30-v032.md` covering:

- Trace primitives.
- Checkpoint id resume.
- AgentRuntimeGraph skeleton.
- AuthorityGrant.
- Provider runtime normalization.
- MCP lifecycle handoff.
- Schema-aware tool planner.
- Sandbox posture metadata.
- Model-loop eval skeleton.
- Residual risks.

- [x] **Step 10.2: Run full gate**

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
agent eval passes
python pytest passes
frontend typecheck exits 0
frontend test passes
Rust cargo test exits 0
```

- [x] **Step 10.3: Final progress update**

Update every progress row to `complete`, including evidence from the full gate. Record any residual limitations exactly; do not claim OS isolation, real production MCP credentials, or full multi-Agent support.

## Residual Work Explicitly Out Of Scope

- Full replacement of `graph.py` with a LangGraph-persisted `AgentRuntimeGraph`.
- Production MCP credential broker and long-running process supervisor.
- Enforced Windows Job Object/AppContainer backend.
- Full model quality benchmark with real remote/local models in CI.
- Multi-Agent team runtime.
