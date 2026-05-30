# Agent Runtime V0.31 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the 0.31.0 optimization audit into a staged implementation that upgrades Alita's runtime observability, checkpoint recovery, authority grants, provider runtime, MCP discovery, planner policy, safe memory writes, sandbox posture, and eval coverage.

**Architecture:** Keep the existing `graph.py` router and `run_graph_events()` executor stable while extracting explicit runtime support modules around them. Each phase adds one runtime contract, verifies it with focused tests, then runs a phase gate before moving to the next phase.

**Tech Stack:** Python 3.10, Pydantic, FastAPI sidecar, LangGraph, pytest, React 19, TypeScript, Vitest, Tauri/Rust command layer, JSONL deterministic eval harness.

---

## Execution Rules

This plan is executed in Codex goal mode on branch `codex/agent-runtime-v031-implementation`.

After every phase:

1. Run the phase-specific Python/TypeScript/Rust tests listed in the phase.
2. Run `npm run agent:eval` when the phase touches runtime, authority, planner, tool, research, sandbox, memory, or eval behavior.
3. Run `git diff --check`.
4. Review the phase acceptance checklist.
5. Only proceed to the next phase when all commands exit `0` and all acceptance checks are satisfied.

Final verification:

```powershell
npm run agent:eval
cd python; python -m pytest
cd ..; npm run frontend:typecheck
npm run frontend:test
cd src-tauri; cargo test
cd ..; git diff --check
```

Expected final result: all available tests pass, no whitespace errors, implementation documents reflect the completed phases, and no known phase acceptance item remains unmet.

## Phase Map

| Phase | Purpose | Primary Gate |
| --- | --- | --- |
| 0 | Baseline and plan | Plan exists and baseline eval passes |
| 1 | Runtime observability events | Backend emits checkpoint/recovery/authority events consumed by frontend |
| 2 | Checkpoint resume | Failed/interrupted graph runs can resume from latest checkpoint |
| 3 | Explicit authority grants | Requested permissions no longer self-approve sensitive access |
| 4 | Provider observation contract | Tool calls return consistent observation metadata |
| 5 | MCP provider discovery path | Configured MCP tools can enter gateway/planner through a typed handoff |
| 6 | Planner/ReAct/memory/eval improvements | Planner policy and safe memory defaults are measurable |
| 7 | Sandbox posture hardening | Constrained runner is explicitly documented and tested for escape patterns |
| 8 | Final review | Full suite and goal completion audit |

---

## Execution Result

Status: completed in Codex goal mode on `codex/agent-runtime-v031-implementation`.

Final verification evidence:

| Command | Result |
| --- | --- |
| `npm run agent:eval` | `63/63 passed, 0 failed` |
| `cd python; python -m pytest` | `734 passed` |
| `npm run frontend:typecheck` | exit `0` |
| `npm run frontend:test` | `32` test files, `210` tests passed |
| `cd src-tauri; cargo test` | exit `0`; Rust/Tauri unit and integration suites passed |
| `git diff --check` | exit `0`; CRLF conversion warnings only |

Residual long-term work remains intentionally out of scope for this goal: full `AgentRuntimeGraph` replacement, real MCP stdio/http lifecycle, OS-level sandbox isolation, model-in-loop benchmarks, and cost tracing.

---

## Phase 0: Baseline And Plan

**Files:**
- Create: `docs/superpowers/plans/2026-05-30-agent-runtime-v031-implementation-plan.md`
- Read: `docs/agent-development-optimization-2026-05-30-v031.md`

- [x] **Step 1: Confirm baseline branch and dirty state**

Run:

```powershell
git branch --show-current
git status --short
```

Expected:

```text
codex/agent-runtime-v031-implementation
?? docs/agent-development-optimization-2026-05-30-v031.md
?? docs/superpowers/plans/2026-05-30-agent-runtime-v031-implementation-plan.md
```

- [x] **Step 2: Run baseline deterministic eval**

Run:

```powershell
npm run agent:eval
```

Expected:

```text
Agent eval summary: 59/59 passed, 0 failed.
```

- [x] **Step 3: Phase 0 acceptance review**

Acceptance:

- The implementation plan exists.
- The plan explicitly lists stage gates.
- Baseline deterministic eval passes before code changes.

---

## Phase 1: Runtime Observability Events

**Goal:** Make backend runtime events match the frontend observability contract.

**Files:**
- Create: `python/agent_service/runtime_events.py`
- Modify: `python/agent_service/execution.py`
- Modify: `src/shared/events.ts`
- Modify: `src/features/task/useGraphRuntimeController.ts`
- Modify: `src/features/permissions/usePermissionController.ts`
- Test: `python/tests/test_execution.py`
- Test: `src/features/task/useGraphRuntimeController.test.ts`
- Test: `src/features/permissions/usePermissionController.test.ts`

- [x] **Step 1: Add backend event builders**

Create `python/agent_service/runtime_events.py` with focused builders:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_service.authority import AuthorityDecision
from agent_service.replan import ReplanSuggestion
from agent_service.runtime_loop import RuntimeCheckpoint
from agent_service.schemas import AgentEvent
from agent_service.tool_protocol import UnifiedToolDefinition, UnifiedToolInvocation


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def checkpoint_recorded_event(checkpoint: RuntimeCheckpoint) -> AgentEvent:
    return AgentEvent(
        type="runtime.checkpoint_recorded",
        payload={"checkpoint": checkpoint.to_record()},
    )


def authority_decision_recorded_event(
    *,
    invocation: UnifiedToolInvocation,
    tool: UnifiedToolDefinition,
    decision: AuthorityDecision,
    created_at: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type="authority.decision_recorded",
        payload={
            "decision": {
                "runId": invocation.run_id,
                "nodeId": invocation.node_id,
                "toolId": invocation.tool_id,
                "providerId": tool.provider_id,
                "allowed": decision.allowed,
                "code": decision.code,
                "message": decision.message,
                "permissions": list(decision.metadata.get("permissions", [])),
                "createdAt": created_at or utc_now_iso(),
            }
        },
    )


def recovery_action_event(
    *,
    event_type: str,
    run_id: str,
    node_id: str,
    suggestion: ReplanSuggestion,
    recovery_count: int = 0,
    created_at: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=event_type,
        payload={
            "action": {
                "runId": run_id,
                "nodeId": node_id,
                "action": "applied" if event_type.endswith("_applied") else "proposed",
                "reason": suggestion.reason,
                "operations": [
                    operation.model_dump() for operation in suggestion.operations
                ],
                "requiresUserApproval": suggestion.requires_user_approval,
                "createdAt": created_at or utc_now_iso(),
                "recoveryCount": recovery_count,
            }
        },
    )
```

- [x] **Step 2: Record authority decisions in the gateway**

Update `UnifiedToolGateway` so it can accept an optional event sink:

```python
AuthorityEventSink = Callable[
    [UnifiedToolInvocation, UnifiedToolDefinition, AuthorityDecision], None
]
```

Constructor:

```python
def __init__(
    self,
    *,
    providers: list[ToolProvider],
    authority_context: AuthorityContext | None = None,
    authority_event_sink: AuthorityEventSink | None = None,
) -> None:
    self.providers = providers
    self.authority_context = authority_context
    self.authority_event_sink = authority_event_sink
```

After `decision = authorize_tool_invocation(...)`:

```python
if self.authority_event_sink is not None:
    self.authority_event_sink(invocation, tool, decision)
```

- [x] **Step 3: Wire observability events into `run_graph_events()`**

In `python/agent_service/execution.py`:

- Import event builders from `runtime_events.py`.
- Keep a local `pending_observability_events: list[AgentEvent]`.
- Build the default gateway with an authority sink that appends `authority_decision_recorded_event(...)`.
- Replace direct `journal.write_checkpoint(checkpoint)` blocks with:

```python
journal.write_checkpoint(checkpoint)
yield checkpoint_recorded_event(checkpoint)
```

- After authority-sensitive node execution attempts, drain pending authority events:

```python
while pending_observability_events:
    yield pending_observability_events.pop(0)
```

- When a suggestion is created and not auto-applied, emit `recovery.action_proposed`.
- When `_can_auto_continue(...)` is true, emit `recovery.action_applied` instead of only `recovery.continued`; keep `recovery.continued` as a compatibility event for existing tests.

- [x] **Step 4: Align frontend event contract**

In `src/shared/events.ts`, add:

```ts
| {
    type: "recovery.continued";
    payload: {
      runId: string;
      taskId: string;
      nodeId: string;
      reason: string;
      recoveryCount: number;
      suggestion?: unknown;
      createdAt: string;
    };
  }
```

In `useGraphRuntimeController.ts`, map `recovery.continued` into an applied recovery action when the backend emits the compatibility event.

- [x] **Step 5: Add Python event tests**

Add tests in `python/tests/test_execution.py`:

```python
def test_run_graph_events_emits_checkpoint_events_for_completed_nodes(tmp_path: Path) -> None:
    ...
    event_types = [event.type for event in events]
    assert "runtime.checkpoint_recorded" in event_types
    checkpoints = [
        event.payload["checkpoint"]
        for event in events
        if event.type == "runtime.checkpoint_recorded"
    ]
    assert any(checkpoint["status"] == "before_node" for checkpoint in checkpoints)
    assert any(checkpoint["status"] == "after_node" for checkpoint in checkpoints)
```

```python
def test_run_graph_events_emits_authority_decision_for_tool_call(tmp_path: Path) -> None:
    ...
    authority_events = [
        event for event in events if event.type == "authority.decision_recorded"
    ]
    assert authority_events
    assert authority_events[0].payload["decision"]["allowed"] is True
```

```python
def test_run_graph_events_emits_recovery_action_applied_for_auto_retry(tmp_path: Path) -> None:
    ...
    assert "recovery.action_applied" in [event.type for event in events]
```

- [x] **Step 6: Run Phase 1 verification**

Run:

```powershell
cd python; python -m pytest tests/test_execution.py tests/test_tool_gateway.py -q
cd ..; npm run frontend:test -- useGraphRuntimeController usePermissionController
npm run agent:eval
git diff --check
```

Acceptance:

- Backend emits checkpoint events for checkpoint writes.
- Backend emits authority decision events for allowed and denied tool calls.
- Backend emits proposed/applied recovery action events.
- Frontend reducers retain checkpoint, authority, and recovery state.

---

## Phase 2: Checkpoint Resume

**Goal:** Allow a graph run to resume from the latest checkpoint without rerunning completed nodes.

**Files:**
- Modify: `python/agent_service/runtime_loop.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/schemas.py`
- Test: `python/tests/test_run_journal.py`
- Test: `python/tests/test_execution.py`

- [x] **Step 1: Extend run mode**

In `RunMode`, add:

```python
type: Literal["full", "failed_only", "from_node", "resume_checkpoint"] = "full"
checkpoint_id: str | None = None
```

The default remains `full`.

- [x] **Step 2: Restore checkpoint outputs**

In `runtime_loop.py`, add:

```python
def outputs_from_checkpoint_record(record: dict[str, Any]) -> dict[str, NodeOutput]:
    restored: dict[str, NodeOutput] = {}
    for node_id, payload in dict(record.get("completedOutputs") or {}).items():
        restored[node_id] = NodeOutput(
            values=dict(payload.get("values") or {}),
            artifacts=list(payload.get("artifactRefs") or []),
        )
    return restored
```

Also add:

```python
def pending_node_ids_from_checkpoint_record(record: dict[str, Any]) -> list[str]:
    return [str(value) for value in record.get("pendingNodeIds") or []]
```

- [x] **Step 3: Select nodes from checkpoint**

In `execution.py`, when `request.mode.type == "resume_checkpoint"`:

- Read `RunJournal(...).read_latest_checkpoint()` unless `checkpoint_id` is later implemented.
- Restore `outputs` from checkpoint.
- Reduce `selected_nodes` to nodes whose ids are in `pendingNodeIds`.
- Emit `runtime.resume_started` with checkpoint status and pending count.

Use this shape:

```python
if request.mode.type == "resume_checkpoint":
    latest_checkpoint = journal.read_latest_checkpoint()
    if latest_checkpoint is None:
        raise HarnessError("missing_checkpoint", "no checkpoint exists for resume")
    outputs.update(outputs_from_checkpoint_record(latest_checkpoint))
    pending_ids = set(pending_node_ids_from_checkpoint_record(latest_checkpoint))
    selected_nodes = [node for node in selected_nodes if node.nodeId in pending_ids]
    yield AgentEvent(
        type="runtime.resume_started",
        payload={
            "runId": request.run_id,
            "taskId": request.task_id,
            "checkpoint": latest_checkpoint,
            "pendingNodeIds": list(pending_ids),
        },
    )
```

- [x] **Step 4: Add resume tests**

Add a test where:

1. First run fails after one completed node.
2. Latest checkpoint contains that completed node.
3. Second run uses `RunMode(type="resume_checkpoint")`.
4. The first node is not executed again.
5. The pending node executes and final task completes.

Expected assertions:

```python
assert "runtime.resume_started" in [event.type for event in resumed_events]
assert executor.calls == ["second-node"]
assert "task.completed" in [event.type for event in resumed_events]
```

- [x] **Step 5: Run Phase 2 verification**

Run:

```powershell
cd python; python -m pytest tests/test_run_journal.py tests/test_execution.py -q
cd ..; npm run agent:eval
git diff --check
```

Acceptance:

- Resume mode restores completed outputs from checkpoint.
- Resume mode only executes pending nodes.
- Missing checkpoint fails with a clear `missing_checkpoint` error.
- Existing full/from_node/failed_only modes keep their behavior.

---

## Phase 3: Explicit Authority Grants

**Goal:** Requested permissions are treated as requested scope, not automatically approved authority.

**Files:**
- Modify: `python/agent_service/authority.py`
- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/evals/security_cases.jsonl`
- Test: `python/tests/test_authority.py`
- Test: `python/tests/test_tool_gateway.py`
- Test: `python/tests/test_execution_gateway_integration.py`
- Test: `python/tests/test_eval_harness.py`

- [x] **Step 1: Add explicit grant model**

In `authority.py`, add:

```python
@dataclass(frozen=True)
class AuthorityGrant:
    approved_tool_ids: list[str] = field(default_factory=list)
    approved_permissions: list[str] = field(default_factory=list)
    read_roots: list[str] = field(default_factory=list)
    write_roots: list[str] = field(default_factory=list)
    network_domains: list[str] = field(default_factory=list)
    runtime_budget_ms: int | None = None

    def to_context(self) -> AuthorityContext:
        return AuthorityContext(
            approved_tool_ids=list(self.approved_tool_ids),
            approved_permissions=list(self.approved_permissions),
            read_roots=list(self.read_roots),
            write_roots=list(self.write_roots),
            network_domains=list(self.network_domains),
            runtime_budget_ms=self.runtime_budget_ms,
        )
```

- [x] **Step 2: Make fallback deny sensitive permissions**

Change `AuthorityContext.from_invocation()` to:

```python
return cls(
    approved_permissions=[],
    read_roots=list(invocation.allowed_roots),
    write_roots=[],
    runtime_budget_ms=None,
)
```

Change `with_invocation_scope()` so it does not append `invocation.requested_permissions` to `approved_permissions`.

- [x] **Step 3: Preserve runtime-approved permissions**

Keep `_runtime_authority_context(request)` as the place that converts user-approved run permissions into authority:

```python
AuthorityContext(
    approved_permissions=list(request.approved_permissions),
    read_roots=_request_read_roots(request),
    write_roots=_request_write_roots(request),
)
```

- [x] **Step 4: Add security eval cases**

Add cases proving:

- `context: from_invocation` with `requested_permissions: ["network"]` is denied.
- Explicit `approved_permissions: ["network"]` is allowed.
- Write path outside `write_roots` is denied.

- [x] **Step 5: Run Phase 3 verification**

Run:

```powershell
cd python; python -m pytest tests/test_authority.py tests/test_tool_gateway.py tests/test_execution_gateway_integration.py tests/test_eval_harness.py -q
cd ..; npm run agent:eval
git diff --check
```

Acceptance:

- No sensitive permission is approved only because invocation requested it.
- Runtime-approved permissions still work.
- Security eval count increases and all eval cases pass.

---

## Phase 4: Provider Observation Contract

**Goal:** Normalize tool/provider result metadata and runtime duration so observations can feed journal, memory, and eval consistently.

**Files:**
- Create: `python/agent_service/tool_observation.py`
- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/agent_service/tool_providers/internal.py`
- Modify: `python/agent_service/tool_providers/mcp.py`
- Modify: `python/agent_service/execution.py`
- Test: `python/tests/test_tool_gateway.py`
- Test: `python/tests/test_mcp_tool_provider.py`
- Test: `python/tests/test_tool_execution.py`

- [x] **Step 1: Add observation helper**

Create `tool_observation.py`:

```python
from __future__ import annotations

from time import perf_counter
from typing import Any


class ObservationTimer:
    def __init__(self) -> None:
        self.started = perf_counter()

    def elapsed_ms(self) -> int:
        return int((perf_counter() - self.started) * 1000)


def observation_metadata(
    *,
    tool_id: str,
    provider_id: str,
    ok: bool,
    duration_ms: int,
    authority_code: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    return {
        "observation": {
            "toolId": tool_id,
            "providerId": provider_id,
            "ok": ok,
            "durationMs": duration_ms,
            "authorityCode": authority_code,
            "errorCode": error_code,
        }
    }
```

- [x] **Step 2: Add gateway-level observation metadata**

Wrap provider calls in `UnifiedToolGateway.call_tool()` with `ObservationTimer`, then merge `observation_metadata(...)` into the returned result metadata for both success and failure.

- [x] **Step 3: Persist observation in node record**

In `_node_output_from_unified_result()` or `_run_fixed_tool_node()`, include observation metadata in output values:

```python
values = dict(result.structured_content or {})
if "observation" in result.metadata:
    values["observation"] = result.metadata["observation"]
```

- [x] **Step 4: Run Phase 4 verification**

Run:

```powershell
cd python; python -m pytest tests/test_tool_gateway.py tests/test_mcp_tool_provider.py tests/test_tool_execution.py tests/test_execution.py -q
cd ..; npm run agent:eval
git diff --check
```

Acceptance:

- Internal and MCP tool calls include `metadata.observation`.
- Node output values preserve observation metadata.
- Failed tool calls include `ok: false` and an error code.

---

## Phase 5: MCP Provider Discovery Path

**Goal:** Create a typed path for MCP provider configs to enter Python gateway and planner context.

**Files:**
- Modify: `python/agent_service/tool_providers/mcp.py`
- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/agent_service/context_manager.py`
- Modify: `python/agent_service/graph.py`
- Modify: `src-tauri/src/preferences.rs`
- Modify: `src-tauri/src/commands.rs`
- Test: `python/tests/test_mcp_tool_provider.py`
- Test: `python/tests/test_tool_gateway.py`
- Test: `python/tests/test_context_manager.py`
- Test: `src-tauri/tests/preferences_tests.rs`
- Test: `src-tauri/tests/tool_provider_commands_tests.rs`

- [x] **Step 1: Extend MCP provider config**

Add transport fields to Python `McpProviderConfig`:

```python
transport: str = "stdio"
command: str | None = None
url: str | None = None
```

- [x] **Step 2: Add sidecar-safe config serializer**

In Rust command layer, expose enabled MCP configs as JSON-compatible provider config records matching the Python dataclass fields.

- [x] **Step 3: Add context manager hook**

Allow `build_context_bundle(...)` to accept `external_tools: list[ToolCapability] | None`, then append them to registry tools.

- [x] **Step 4: Add graph planning hook**

Do not build real stdio clients in this phase. Add a typed optional parameter to `_graph_payload_for_task(...)` and `run_agent...` call paths so tests can inject MCP-discovered tool capabilities.

- [x] **Step 5: Run Phase 5 verification**

Run:

```powershell
cd python; python -m pytest tests/test_mcp_tool_provider.py tests/test_tool_gateway.py tests/test_context_manager.py tests/test_planner_chain.py -q
cd ..; cd src-tauri; cargo test tool_provider preferences
cd ..; npm run agent:eval
git diff --check
```

Acceptance:

- Enabled MCP configs can become `McpProviderConfig`.
- Injected MCP tools appear in planning context.
- Disabled MCP providers remain invisible.
- No real external MCP process is launched in deterministic tests.

---

## Phase 6: Planner, ReAct, Memory, And Eval

**Goal:** Improve default policy generation and make safe memory/eval behavior measurable.

**Files:**
- Modify: `python/agent_service/planner_chain.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/memory_store.py`
- Modify: `python/agent_service/eval_harness.py`
- Modify: `python/evals/planner_cases.jsonl`
- Modify: `python/evals/tool_cases.jsonl`
- Modify: `python/evals/research_cases.jsonl`
- Test: `python/tests/test_planner_chain.py`
- Test: `python/tests/test_memory_store.py`
- Test: `python/tests/test_eval_harness.py`
- Test: `python/tests/test_react_controller.py`

- [x] **Step 1: Emit node-level action policy metadata**

Add graph metadata:

```json
"actionPolicies": {
  "node-id": {
    "reactEnabled": true,
    "nativeToolCalls": false,
    "allowedToolIds": [],
    "allowedPermissions": [],
    "maxSteps": 4
  }
}
```

Keep graph-level `react` for backward compatibility.

- [x] **Step 2: Use node-level policy during model execution**

In `PlannedTaskExecutor`, prefer `metadata.actionPolicies[node_id]` over graph-level `react` when building `ReActPolicy`.

- [x] **Step 3: Safe default memory auto-write**

Change `_memory_auto_write_enabled()`:

```python
memory_config = request.graph.metadata.get("memory")
if isinstance(memory_config, dict) and memory_config.get("autoWrite") is False:
    return False
return True
```

Keep memory summaries sanitized through `MemoryStore.append()`.

- [x] **Step 4: Expand eval summary metrics**

Add category-level details for:

- `claimCount`
- `unsupportedClaimCount`
- `observationPresent`
- `memoryAutoWriteDefault`

- [x] **Step 5: Run Phase 6 verification**

Run:

```powershell
cd python; python -m pytest tests/test_planner_chain.py tests/test_memory_store.py tests/test_eval_harness.py tests/test_react_controller.py tests/test_execution.py -q
cd ..; npm run agent:eval
git diff --check
```

Acceptance:

- Planner emits node-level policies for model nodes that need tool exploration.
- Execution honors node-level ReAct policy.
- Safe run memory writes by default unless explicitly disabled.
- Eval summary exposes the new deterministic metrics.

---

## Phase 7: Sandbox Posture Hardening

**Goal:** Make the current sandbox posture explicit and add deterministic escape regression tests.

**Files:**
- Modify: `python/agent_service/sandbox.py`
- Modify: `python/evals/security_cases.jsonl`
- Modify: `docs/agent-development-optimization-2026-05-30-v031.md`
- Test: `python/tests/test_sandbox.py`
- Test: `python/tests/test_eval_harness.py`

- [x] **Step 1: Rename user-facing description**

Add constants:

```python
SANDBOX_SECURITY_MODEL = "constrained_subprocess_runner"
SANDBOX_SECURITY_BOUNDARY = "preflight_and_runtime_limits_not_os_isolation"
```

Expose them in `SandboxResult.values` for successful runs and in error metadata where practical.

- [x] **Step 2: Expand forbidden API detection**

Add tests and checks for:

- `os.system`
- `os.popen`
- `subprocess.Popen`
- `socket.socket` when network is not allowed
- `Path.write_text()` outside artifact dir when literal path is used

- [x] **Step 3: Add security eval cases**

Add JSONL cases for dynamic path and process launch patterns that must fail deterministically.

- [x] **Step 4: Update optimization doc residual risk**

In `docs/agent-development-optimization-2026-05-30-v031.md`, mark sandbox work as improved but not OS-level isolation. Keep Job Object/AppContainer as a future task unless implemented.

- [x] **Step 5: Run Phase 7 verification**

Run:

```powershell
cd python; python -m pytest tests/test_sandbox.py tests/test_eval_harness.py -q
cd ..; npm run agent:eval
git diff --check
```

Acceptance:

- Current sandbox is named accurately.
- Escape regression cases fail closed.
- Documentation does not overclaim OS-level isolation.

---

## Phase 8: Final Review And Goal Completion

**Files:**
- Modify: `docs/agent-development-optimization-2026-05-30-v031.md`
- Modify: `docs/superpowers/plans/2026-05-30-agent-runtime-v031-implementation-plan.md`

- [x] **Step 1: Update implementation results**

Append an implementation status section to the audit doc:

```markdown
## 12. Goal Mode Implementation Results

| Phase | Status | Verification |
| --- | --- | --- |
...
```

- [x] **Step 2: Run full verification**

Run:

```powershell
npm run agent:eval
cd python; python -m pytest
cd ..; npm run frontend:typecheck
npm run frontend:test
cd src-tauri; cargo test
cd ..; git diff --check
```

- [x] **Step 3: Inspect final diff**

Run:

```powershell
git status --short
git diff --stat
```

Acceptance:

- Full verification commands exit `0`.
- Phase result table is accurate.
- No unrelated generated files are staged or modified.
- Goal can be marked complete.
