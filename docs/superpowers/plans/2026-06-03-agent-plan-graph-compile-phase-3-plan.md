# Agent Plan Graph Compile Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this plan.

**Goal:** After the user confirms a Phase 2 Agent Plan Graph, compile that exact confirmed graph into a durable execution-ready agent contract without starting execution.

**Architecture:** Add an Agent Plan Graph Compile layer inside the deep agent LangGraph runtime. This layer validates deep-planning provenance, composes with the existing execution graph compiler, preserves verification and permission contracts, emits compile lifecycle events, and stores compile state in the LangGraph checkpoint and runtime history.

**Tech Stack:** Python, Pydantic, LangGraph, existing `agent_service` runtime modules, TypeScript shared event types, existing frontend planning event reducer/tests.

---

## Constraints

- Work in the Phase 2 worktree: `D:\Software Project\Alita\.worktrees\deep-agent-reasoning-runtime-phase-1`.
- Do not replace Phase 2 planning logic.
- Do not add a second user-facing mode.
- Do not execute the compiled graph in Phase 3.
- Do not silently fall back to legacy templates or generic workflows.
- Keep compile state checkpointed through the existing LangGraph planning runtime.
- Follow official LangGraph graph state, conditional routing, interrupt, persistence, and streaming guidance:
  - https://docs.langchain.com/oss/python/langgraph/graph-api
  - https://docs.langchain.com/oss/python/langgraph/persistence
  - https://docs.langchain.com/oss/python/langgraph/interrupts
  - https://docs.langchain.com/oss/python/langgraph/streaming
  - https://docs.langchain.com/oss/python/langgraph/use-subgraphs
  - https://reference.langchain.com/python/langgraph/graph/

## Implementation Tasks

### 1. Add Agent Compile Contract Models

Create `python/agent_service/agent_plan_compile.py`.

Define Pydantic models for the Phase 3 compile contract:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_service.action_graph import RuntimeActionGraph
from agent_service.execution_graph import ExecutionGraph
from agent_service.schemas import GraphEdge


class ExpectedArtifact(BaseModel):
    label: str
    produced_by_node_id: str
    artifact_type: str | None = None


class AgentCompiledToolContract(BaseModel):
    tool_id: str
    operation: str
    input_template: dict[str, Any] = Field(default_factory=dict)
    output_contract: dict[str, Any] = Field(default_factory=dict)


class AgentCompiledModelContract(BaseModel):
    model_ref: str
    input_contract: dict[str, Any] = Field(default_factory=dict)
    output_contract: dict[str, Any] = Field(default_factory=dict)


class AgentCompiledNode(BaseModel):
    node_id: str
    node_type: Literal["fixed_tool", "model", "output", "control"]
    source_plan_step_id: str
    dependencies: list[str] = Field(default_factory=list)
    binding_kind: Literal["tool", "model", "output", "control"]
    tool_contract: AgentCompiledToolContract | None = None
    model_contract: AgentCompiledModelContract | None = None
    expected_output: str
    verification_criteria: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    permissions_required: list[str] = Field(default_factory=list)
    risk_level: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentCompileIssue(BaseModel):
    code: str
    message: str
    node_id: str | None = None
    severity: Literal["error", "warning"] = "error"


class AgentCompileReview(BaseModel):
    is_valid: bool
    issues: list[AgentCompileIssue] = Field(default_factory=list)
    unsupported_capabilities: list[str] = Field(default_factory=list)
    missing_bindings: list[str] = Field(default_factory=list)
    execution_ready: bool = False


class AgentCompiledGraph(BaseModel):
    compile_id: str
    compile_fingerprint: str
    task_id: str
    run_id: str
    thread_id: str
    confirmation_id: str
    source_graph_id: str
    source_plan_draft_id: str
    source_planning_trace_id: str | None = None
    status: Literal["compiled", "reviewed", "execution_ready", "failed"] = "compiled"
    nodes: list[AgentCompiledNode]
    edges: list[GraphEdge]
    execution_graph: ExecutionGraph
    action_graph: RuntimeActionGraph
    success_criteria: list[str] = Field(default_factory=list)
    verification_plan: list[str] = Field(default_factory=list)
    permissions_required: list[str] = Field(default_factory=list)
    expected_artifacts: list[ExpectedArtifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

Expected result:

- `agent_plan_compile.py` imports cleanly.
- Model names are stable and exported through direct imports in tests.
- No compile code is added to `execution.py`.

### 2. Implement Provenance And Fingerprint Guards

In `agent_plan_compile.py`, implement private helpers:

```python
def _require_deep_planning_graph(graph: RunGraph) -> tuple[str, str | None, list[str], list[str]]:
    metadata = graph.metadata or {}
    if metadata.get("generatedBy") != "deep_agent_runtime":
        raise AgentPlanCompileError("Graph was not generated by the deep agent runtime.")
    if metadata.get("modelPolicy") != "deep_reasoning":
        raise AgentPlanCompileError("Graph was not produced under the deep reasoning model policy.")
    source_plan_draft_id = metadata.get("sourcePlanDraftId")
    if not source_plan_draft_id:
        raise AgentPlanCompileError("Graph is missing source plan draft provenance.")
    return (
        source_plan_draft_id,
        metadata.get("planningTraceId"),
        list(metadata.get("successCriteria") or []),
        list(metadata.get("verificationPlan") or []),
    )
```

Implement a deterministic fingerprint over:

- graph ID,
- graph metadata relevant to plan provenance,
- node IDs,
- node types,
- node metadata,
- tool bindings,
- model bindings,
- edges,
- verification criteria.

Use JSON with sorted keys and compact separators before hashing:

```python
def _fingerprint_graph(graph: RunGraph) -> str:
    payload = {
        "id": graph.id,
        "metadata": graph.metadata,
        "nodes": [node.model_dump(mode="json", exclude_none=True) for node in graph.nodes],
        "edges": [edge.model_dump(mode="json", exclude_none=True) for edge in graph.edges],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
```

Expected result:

- Legacy/template graphs fail before execution graph compilation.
- Identical confirmed graphs produce identical fingerprints.
- Fingerprints change when verification criteria or bindings change.

### 3. Implement Confirmed Plan Graph Compiler

Add:

```python
def compile_confirmed_agent_plan_graph(
    graph: RunGraph,
    *,
    task_id: str,
    run_id: str,
    thread_id: str,
    confirmation_id: str,
    tool_registry: ToolRegistry | None = None,
) -> AgentCompiledGraph:
    ...
```

Implementation requirements:

- call `_require_deep_planning_graph(graph)` first;
- call existing `compile_execution_graph(...)`;
- extract `action_graph` from `execution_graph.metadata["actionGraph"]` or from the compiled execution graph contract already produced by `compile_execution_graph`;
- convert each visible graph node into `AgentCompiledNode`;
- preserve `sourcePlanStepId`, `expectedOutput`, `verificationCriteria`, and `requiredCapabilities`;
- collect permissions from node permissions and execution/tool binding metadata;
- collect expected artifact labels from outputs or metadata;
- reject fixed tool nodes with missing binding or operation;
- reject model nodes with missing model reference;
- generate a stable `compile_id` from graph ID, run ID, confirmation ID, and fingerprint.

Node conversion rules:

```python
def _compile_node_contract(node: GraphNode, execution_graph: ExecutionGraph) -> AgentCompiledNode:
    source_step_id = (node.metadata or {}).get("sourcePlanStepId")
    if not source_step_id:
        raise AgentPlanCompileError(f"Node {node.id} is missing source plan step provenance.")

    expected_output = (node.metadata or {}).get("expectedOutput")
    if not expected_output:
        raise AgentPlanCompileError(f"Node {node.id} is missing expected output metadata.")

    verification_criteria = list((node.metadata or {}).get("verificationCriteria") or [])
    required_capabilities = list((node.metadata or {}).get("requiredCapabilities") or [])

    if node.nodeType == "fixed_tool":
        tool_contract = _compile_tool_contract(node, execution_graph)
        binding_kind = "tool"
    elif node.nodeType == "model":
        model_contract = _compile_model_contract(node)
        binding_kind = "model"
    elif node.nodeType == "output":
        binding_kind = "output"
    else:
        binding_kind = "control"

    ...
```

Expected result:

- A confirmed Phase 2 graph compiles into a typed `AgentCompiledGraph`.
- Compile failures are represented as domain errors and can become runtime events.
- Existing `execution_graph.py` remains the source of truth for low-level execution graph validation.

### 4. Implement Compile Review

Add:

```python
def review_agent_compiled_graph(compiled_graph: AgentCompiledGraph) -> AgentCompileReview:
    ...
```

Review rules:

- all nodes have source plan step IDs;
- all fixed tool nodes have tool contracts;
- all model nodes have model contracts;
- every node preserves non-empty verification criteria;
- graph-level verification plan is non-empty when the original plan had success criteria;
- every dependency references an existing node;
- every edge references existing nodes;
- `execution_graph` and `action_graph` node/action counts are consistent with executable nodes;
- unsupported capabilities and missing bindings are reported as explicit issues.

Expected result:

- Review passes for valid Phase 2 graphs.
- Review fails with structured issues for incomplete compile contracts.
- Review does not mutate the source graph.

### 5. Add Unit Tests For Compile Contract

Create `python/tests/test_agent_plan_compile.py` or the matching local test path.

Cover these cases:

```python
def test_compile_confirmed_agent_plan_graph_preserves_provenance() -> None:
    graph = make_deep_agent_run_graph()
    compiled = compile_confirmed_agent_plan_graph(
        graph,
        task_id="task-1",
        run_id="run-1",
        thread_id="thread-1",
        confirmation_id="confirm-1",
    )

    assert compiled.source_graph_id == graph.id
    assert compiled.source_plan_draft_id == graph.metadata["sourcePlanDraftId"]
    assert compiled.nodes[0].source_plan_step_id
    assert compiled.nodes[0].verification_criteria
```

```python
def test_compile_rejects_legacy_graph_without_deep_planning_metadata() -> None:
    graph = make_legacy_run_graph()

    with pytest.raises(AgentPlanCompileError):
        compile_confirmed_agent_plan_graph(
            graph,
            task_id="task-1",
            run_id="run-1",
            thread_id="thread-1",
            confirmation_id="confirm-1",
        )
```

```python
def test_compile_rejects_fixed_tool_node_without_binding() -> None:
    graph = make_deep_agent_run_graph_with_missing_tool_binding()

    with pytest.raises(AgentPlanCompileError):
        compile_confirmed_agent_plan_graph(
            graph,
            task_id="task-1",
            run_id="run-1",
            thread_id="thread-1",
            confirmation_id="confirm-1",
        )
```

```python
def test_compile_fingerprint_changes_when_verification_changes() -> None:
    graph_a = make_deep_agent_run_graph()
    graph_b = make_deep_agent_run_graph()
    graph_b.nodes[0].metadata["verificationCriteria"] = ["different criterion"]

    compiled_a = compile_confirmed_agent_plan_graph(...)
    compiled_b = compile_confirmed_agent_plan_graph(...)

    assert compiled_a.compile_fingerprint != compiled_b.compile_fingerprint
```

Run:

```bash
cd "D:\Software Project\Alita\.worktrees\deep-agent-reasoning-runtime-phase-1"
python -m pytest python/tests/test_agent_plan_compile.py
```

Expected result:

- All compile contract tests pass.
- Failures expose missing contract fields instead of being hidden by fallback behavior.

### 6. Extend Deep Agent Runtime State

Edit `python/agent_service/deep_agent_runtime_graph.py`.

Extend `DeepAgentRuntimeState` with:

```python
agent_compiled_graph: AgentCompiledGraph | None
agent_compile_review: AgentCompileReview | None
execution_ready: bool
compile_failure: dict[str, Any] | None
```

Set defaults in any state initialization helper:

```python
"agent_compiled_graph": None,
"agent_compile_review": None,
"execution_ready": False,
"compile_failure": None,
```

Expected result:

- Existing Phase 2 graph state still serializes.
- New fields survive checkpoint/resume.
- State defaults do not break old tests.

### 7. Add Runtime Nodes For Compile And Review

In `deep_agent_runtime_graph.py`, add node functions:

```python
def compile_confirmed_plan_graph_node(state: DeepAgentRuntimeState) -> dict[str, Any]:
    graph = state.get("compiled_graph")
    if graph is None:
        return _compile_failure_update(state, "No confirmed graph is available to compile.")

    _append_event(
        state,
        "agent_plan_graph.compile_started",
        {"taskId": ..., "runId": ..., "threadId": ..., "graphId": graph.id},
    )

    try:
        compiled = compile_confirmed_agent_plan_graph(
            graph,
            task_id=...,
            run_id=...,
            thread_id=...,
            confirmation_id=...,
        )
    except AgentPlanCompileError as exc:
        return _compile_failure_update(state, str(exc))

    return {
        "agent_compiled_graph": compiled,
        "events": [
            _runtime_event(
                "agent_plan_graph.compiled",
                _compile_event_payload(state, graph, compiled),
            )
        ],
    }
```

Add:

```python
def review_agent_compiled_graph_node(state: DeepAgentRuntimeState) -> dict[str, Any]:
    compiled = state.get("agent_compiled_graph")
    if compiled is None:
        return _compile_failure_update(state, "No compiled agent graph is available to review.")

    review = review_agent_compiled_graph(compiled)
    payload = _compile_review_payload(state, compiled, review)

    if not review.is_valid:
        return {
            "agent_compile_review": review,
            "compile_failure": payload,
            "events": [_runtime_event("agent_plan_graph.compile_failed", payload)],
        }

    ready_graph = compiled.model_copy(update={"status": "execution_ready"})
    return {
        "agent_compiled_graph": ready_graph,
        "agent_compile_review": review,
        "execution_ready": True,
        "events": [
            _runtime_event("agent_plan_graph.compile_review_completed", payload),
            _runtime_event("agent_plan_graph.execution_ready", _execution_ready_payload(ready_graph)),
        ],
    }
```

Expected result:

- Compile and review are real runtime nodes.
- Compile failure is a terminal planning/runtime state for Phase 3.
- No executor is invoked.

### 8. Wire LangGraph Edges After Confirmation

Edit the graph builder in `deep_agent_runtime_graph.py`.

Add nodes:

```python
builder.add_node("compile_confirmed_plan_graph", compile_confirmed_plan_graph_node)
builder.add_node("review_agent_compiled_graph", review_agent_compiled_graph_node)
builder.add_node("execution_ready", execution_ready_node)
builder.add_node("compile_failed", compile_failed_node)
```

Wire:

```python
builder.add_edge("planning_confirmed", "compile_confirmed_plan_graph")
builder.add_edge("compile_confirmed_plan_graph", "review_agent_compiled_graph")
builder.add_conditional_edges(
    "review_agent_compiled_graph",
    route_after_agent_compile_review,
    {
        "execution_ready": "execution_ready",
        "compile_failed": "compile_failed",
    },
)
builder.add_edge("execution_ready", END)
builder.add_edge("compile_failed", END)
```

Routing:

```python
def route_after_agent_compile_review(state: DeepAgentRuntimeState) -> str:
    if state.get("execution_ready"):
        return "execution_ready"
    return "compile_failed"
```

Expected result:

- Approving a plan no longer ends at `planning_confirmed`; it continues into compile.
- Cancel and revise paths remain unchanged.
- The runtime ends at `execution_ready` or `compile_failed`.

### 9. Add Shared Event Types

Edit `src/shared/events.ts`.

Add variants:

```ts
export type AgentPlanGraphEventType =
  | "agent_plan_graph.compile_started"
  | "agent_plan_graph.compiled"
  | "agent_plan_graph.compile_review_completed"
  | "agent_plan_graph.execution_ready"
  | "agent_plan_graph.compile_failed";
```

If the file uses a single union, merge these into the existing event union.

Add payload types:

```ts
export interface AgentPlanGraphCompilePayload {
  taskId: string;
  runId: string;
  threadId: string;
  graphId: string;
  compileId?: string;
}

export interface AgentPlanGraphExecutionReadyPayload extends AgentPlanGraphCompilePayload {
  compileId: string;
  nodeCount: number;
  edgeCount: number;
  toolNodeCount: number;
  modelNodeCount: number;
  permissionsRequired: string[];
  expectedArtifacts: string[];
}

export interface AgentPlanGraphCompileFailedPayload extends AgentPlanGraphCompilePayload {
  reason: string;
  issues: Array<{ code: string; message: string; nodeId?: string; severity: "error" | "warning" }>;
  unsupportedCapabilities: string[];
  missingBindings: string[];
}
```

Expected result:

- TypeScript accepts the new event variants.
- Event payloads are typed without leaking private reasoning.

### 10. Update Frontend Runtime State

Edit the frontend reducer/store that currently handles `planning.confirmed` and `node_graph.created`.

Add compile state:

```ts
type AgentCompileStatus =
  | "idle"
  | "compiling"
  | "compiled"
  | "reviewed"
  | "execution_ready"
  | "failed";
```

Handle events:

```ts
case "agent_plan_graph.compile_started":
  return { ...state, agentCompileStatus: "compiling", agentCompileFailure: null };

case "agent_plan_graph.compiled":
  return { ...state, agentCompileStatus: "compiled" };

case "agent_plan_graph.compile_review_completed":
  return { ...state, agentCompileStatus: "reviewed" };

case "agent_plan_graph.execution_ready":
  return {
    ...state,
    agentCompileStatus: "execution_ready",
    agentExecutionReadySummary: event.payload,
  };

case "agent_plan_graph.compile_failed":
  return {
    ...state,
    agentCompileStatus: "failed",
    agentCompileFailure: event.payload,
  };
```

Expected result:

- After confirmation, UI shows that the confirmed graph is compiling.
- Successful compile shows execution-ready status.
- Compile failure is visible as a blocker.
- The UI does not say the task is executing.

### 11. Persist Compile Summary

Edit the runtime store or run journal integration used by `deep_agent_runtime_graph.py`.

Persist compact summaries for:

- compile started,
- compile failed,
- execution ready.

Recommended summary shape:

```python
{
    "kind": "agent_plan_compile",
    "taskId": task_id,
    "runId": run_id,
    "threadId": thread_id,
    "graphId": graph_id,
    "compileId": compile_id,
    "compileFingerprint": compile_fingerprint,
    "status": status,
    "nodeCount": node_count,
    "issueCount": issue_count,
    "permissionsRequired": permissions_required,
    "expectedArtifacts": expected_artifact_labels,
}
```

Expected result:

- Product history can show whether the confirmed plan became execution-ready.
- Runtime resume still relies on LangGraph checkpoint state.
- Summaries do not include private prompts or hidden reasoning traces.

### 12. Add Runtime Tests

Extend the deep agent runtime tests.

Cases:

```python
def test_approved_confirmation_compiles_confirmed_graph() -> None:
    runtime = build_deep_agent_runtime_graph(checkpointer=...)
    result = resume_after_confirmation(runtime, decision="approve")

    event_types = [event["type"] for event in result["events"]]
    assert "planning.confirmed" in event_types
    assert "agent_plan_graph.compile_started" in event_types
    assert "agent_plan_graph.compiled" in event_types
    assert "agent_plan_graph.execution_ready" in event_types
    assert result["execution_ready"] is True
```

```python
def test_cancelled_confirmation_does_not_compile() -> None:
    result = resume_after_confirmation(runtime, decision="cancel")

    event_types = [event["type"] for event in result["events"]]
    assert "planning.cancelled" in event_types
    assert "agent_plan_graph.compile_started" not in event_types
```

```python
def test_revision_confirmation_does_not_compile_until_reapproved() -> None:
    result = resume_after_confirmation(runtime, decision="revise", instructions="Make it safer.")

    event_types = [event["type"] for event in result["events"]]
    assert "agent_plan_graph.compile_started" not in event_types
    assert result["execution_ready"] is False
```

```python
def test_compile_failure_does_not_execute_graph() -> None:
    result = resume_after_confirmation_with_uncompilable_graph(runtime)

    event_types = [event["type"] for event in result["events"]]
    assert "agent_plan_graph.compile_failed" in event_types
    assert not any(event_type.startswith("execution.") for event_type in event_types)
```

Run:

```bash
cd "D:\Software Project\Alita\.worktrees\deep-agent-reasoning-runtime-phase-1"
python -m pytest python/tests/test_deep_agent_runtime_graph.py
```

Expected result:

- Approval routes through compile.
- Cancel and revise skip compile.
- Compile failure is terminal for Phase 3.
- No execution starts.

### 13. Add Frontend Event Tests

Update the relevant TypeScript tests for runtime event state.

Cases:

```ts
it("marks the confirmed graph as compiling", () => {
  const state = reduceRuntimeEvent(initialState, {
    type: "agent_plan_graph.compile_started",
    payload: { taskId: "task-1", runId: "run-1", threadId: "thread-1", graphId: "graph-1" },
  });

  expect(state.agentCompileStatus).toBe("compiling");
});
```

```ts
it("stores execution-ready summary without marking execution active", () => {
  const state = reduceRuntimeEvent(initialState, {
    type: "agent_plan_graph.execution_ready",
    payload: {
      taskId: "task-1",
      runId: "run-1",
      threadId: "thread-1",
      graphId: "graph-1",
      compileId: "compile-1",
      nodeCount: 3,
      edgeCount: 2,
      toolNodeCount: 1,
      modelNodeCount: 2,
      permissionsRequired: [],
      expectedArtifacts: ["report"],
    },
  });

  expect(state.agentCompileStatus).toBe("execution_ready");
  expect(state.isExecuting).toBe(false);
});
```

Run the local frontend test command from `package.json`, for example:

```bash
cd "D:\Software Project\Alita\.worktrees\deep-agent-reasoning-runtime-phase-1"
npm test -- --run
```

Expected result:

- New event types pass TypeScript checks.
- Reducer state reflects compile status honestly.

### 14. Add Regression Gate For No Template Fallback

Add or extend tests to prove:

- graphs with `metadata.generatedBy != "deep_agent_runtime"` cannot compile as Phase 3 agent graphs;
- graphs missing `sourcePlanDraftId` cannot compile;
- fixed tool nodes missing operation cannot compile;
- compiler never changes a failed fixed tool node into a model node.

Expected result:

- Any attempt to reintroduce template fallback fails tests.

### 15. Verification Commands

Run targeted backend tests:

```bash
cd "D:\Software Project\Alita\.worktrees\deep-agent-reasoning-runtime-phase-1"
python -m pytest python/tests/test_agent_plan_compile.py python/tests/test_deep_agent_runtime_graph.py
```

Run frontend tests/type checks using the existing project commands discovered from `package.json`, for example:

```bash
cd "D:\Software Project\Alita\.worktrees\deep-agent-reasoning-runtime-phase-1"
npm test -- --run
npm run typecheck
```

Run formatting or linting if configured:

```bash
cd "D:\Software Project\Alita\.worktrees\deep-agent-reasoning-runtime-phase-1"
npm run lint
```

Expected result:

- Backend compile/runtime tests pass.
- Frontend event tests pass.
- TypeScript accepts the new event payloads.
- Lint passes or only reports pre-existing unrelated issues.

### 16. Documentation Sync

Update Phase 2 or product docs only if needed to reflect the new terminal state:

- Phase 2 terminal state: confirmed plan.
- Phase 3 terminal states: execution-ready compiled graph or compile failure.
- Phase 4 starting point: consume `AgentCompiledGraph`, execute steps, verify outputs, and repair failures.

Expected result:

- The docs do not imply Phase 3 executes user tasks.
- Phase boundaries remain clear.

## Definition Of Done

- `AgentCompiledGraph` and `AgentCompileReview` models exist.
- Confirmed Phase 2 graphs compile into typed Phase 3 contracts.
- Legacy/template graphs are rejected by provenance checks.
- Tool/model binding failures are explicit compile failures.
- LangGraph runtime routes approval through compile and review nodes.
- Runtime emits `agent_plan_graph.*` compile lifecycle events.
- Frontend records compile status and execution-ready summary.
- Runtime persistence stores compact compile summaries.
- Tests cover success, failure, cancel, revise, event handling, and no execution.
- No Phase 3 path starts the executor.

## Commit Guidance

Do not commit automatically. After implementation and verification, ask the user whether to commit this phase in the Phase 2 worktree.
