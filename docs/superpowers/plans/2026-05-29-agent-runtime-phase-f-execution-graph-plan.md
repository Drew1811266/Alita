# Agent Runtime Phase F ExecutionGraph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce an internal `ExecutionGraph` model that normalizes runtime bindings before node execution while preserving the public `RunGraph` event/API shape.

**Architecture:** Add `execution_graph.py` as a compiler from public `RunGraphRequest.graph` to a private execution model. `run_graph_events()` should compile and validate this private graph before execution, then pass it into `PlannedTaskExecutor` for binding lookup while continuing to emit public node IDs, node records, and current event payloads. This phase does not add ReAct, dynamic model tool calls, sandbox execution, durable checkpoints, memory, or frontend state changes.

**Tech Stack:** Python 3.12, Pydantic v2, existing `RunGraphRequest`/`GraphNode` schemas, existing `HarnessError`, existing `UnifiedToolGateway`, pytest.

---

## Current Baseline

Phase E is complete on branch `codex/agent-runtime-phase-a-security-hygiene`:

- `python/agent_service/planner_chain.py` produces validated `RunGraph` payloads with safe `metadata.plannerChain`.
- `python/agent_service/graph.py` routes task graph creation through `PlannerChain`.
- `python/agent_service/execution.py` still executes directly from public `GraphNode` fields such as `node.toolRef`, `node.modelRef`, `node.permissionsRequired`, and `node.scriptReview`.
- `PlannedTaskExecutor` has fixed branches for document tools, model nodes, temporary scripts, and output nodes.
- `run_graph_events()` validates tool availability through `_validate_graph_tools()` and then selects `DocumentFlowExecutor`, `ResearchFlowExecutor`, or `PlannedTaskExecutor`.

The current gap is runtime binding normalization: execution logic still reads public UI graph fields directly, so unsupported bindings are discovered inside node execution rather than through one internal execution contract.

## Non-Goals

- Do not change `RunGraph`, `GraphNode`, endpoint schemas, or frontend event payloads.
- Do not remove `DocumentFlowExecutor` or `ResearchFlowExecutor`.
- Do not implement model-driven tool calls, ReAct, MCP dynamic planning, or sandbox execution.
- Do not make temporary scripts actually execute; keep current preview/approval behavior.
- Do not change run journal record shape except for existing error messages caused by earlier binding validation.
- Do not add a frontend dependency on `ExecutionGraph`; it is Python-side internal only.

## Files

### Create

- `python/agent_service/execution_graph.py`
  - Defines `ExecutionToolBinding`, `ExecutionModelBinding`, `ExecutionNode`, and `ExecutionGraph`.
  - Compiles public `RunGraphRequest` into an internal execution graph.
  - Validates missing/unsupported runtime bindings before node execution.
  - Provides lookup helpers keyed by public `nodeId`.
- `python/tests/test_execution_graph.py`
  - Unit tests for compilation, binding extraction, dependency preservation, and validation failures.

### Modify

- `python/agent_service/execution.py`
  - Compile `ExecutionGraph` at the start of `run_graph_events()`.
  - Pass `ExecutionGraph` into `PlannedTaskExecutor`.
  - Use execution bindings for fixed-tool/model binding lookups while still passing the public `GraphNode` to existing event and permission helpers.
  - Surface unsupported binding failures before any node starts.
- `python/tests/test_execution.py`
  - Regression tests proving binding validation happens before node start.
  - Regression tests proving public event shape and existing planned-task graph execution still work.

### Read-Only Regression Targets

- `python/agent_service/schemas.py`
- `python/agent_service/tool_protocol.py`
- `python/agent_service/tool_gateway.py`
- `python/agent_service/permission_gate.py`
- `python/tests/test_execution_gateway_integration.py`
- `src/app/backendEvents.test.ts`

---

## Design Contract

Create `python/agent_service/execution_graph.py` with this public module contract:

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_service.harness_errors import HarnessError
from agent_service.schemas import GraphNode, RunGraphRequest
from agent_service.tool_protocol import provider_tool_id


class ExecutionGraphError(HarnessError):
    pass


class ExecutionToolBinding(BaseModel):
    tool_id: str
    operation: str | None = None
    arguments_template: dict[str, str] = Field(default_factory=dict)


class ExecutionModelBinding(BaseModel):
    model_ref: str
    prompt_template: str | None = None
    output_key: str = "text"


class ExecutionNode(BaseModel):
    node_id: str
    node_type: str
    dependencies: list[str] = Field(default_factory=list)
    tool_binding: ExecutionToolBinding | None = None
    model_binding: ExecutionModelBinding | None = None
    verifier_id: str | None = None
    permissions_required: list[str] = Field(default_factory=list)
    artifact_policy: dict[str, str] = Field(default_factory=dict)


class ExecutionGraph(BaseModel):
    graph_id: str
    task_id: str
    nodes: list[ExecutionNode]
    metadata: dict[str, Any] = Field(default_factory=dict)

    def node_by_id(self, node_id: str) -> ExecutionNode:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise ExecutionGraphError(
            "missing_execution_node",
            f"execution node not found: {node_id}",
        )
```

Compiler behavior:

- `compile_execution_graph(request: RunGraphRequest) -> ExecutionGraph`
  - Copies `request.graph.graphId` into `graph_id`.
  - Copies `request.task_id` into `task_id`.
  - Copies `request.graph.metadata` into `metadata`.
  - Converts each public `GraphNode` into an `ExecutionNode`.
  - Preserves public `nodeId` as `node_id`.
  - Preserves public `nodeType` as `node_type`.
  - Preserves `dependencies`.
  - For `fixed_tool` nodes with `toolRef`, creates `ExecutionToolBinding(tool_id=provider_tool_id(node.toolRef), operation=None)`.
  - For `model` nodes with `modelRef`, creates `ExecutionModelBinding(model_ref=node.modelRef)`.
  - Copies `permissionsRequired`.
  - For output nodes, does not create tool/model binding.
  - For temporary script nodes, does not create tool/model binding in Phase F.

Validation behavior:

- `validate_execution_graph_bindings(execution_graph: ExecutionGraph) -> None`
  - Raises `ExecutionGraphError("unsupported_binding", "fixed_tool node <node-id> has no tool binding")` when a `fixed_tool` node lacks a tool binding.
  - Raises `ExecutionGraphError("unsupported_binding", "model node <node-id> has no model binding")` when a `model` node lacks a model binding.
  - Allows planning, output, and temporary_script nodes without bindings.
  - Does not check tool catalog availability; `_validate_graph_tools()` keeps that responsibility.

---

## Task 0: Baseline Verification

**Files:**
- Read: `python/agent_service/execution.py`
- Read: `python/tests/test_execution.py`
- Read: `python/tests/test_execution_gateway_integration.py`

- [ ] **Step 1: Confirm branch and clean worktree**

Run:

```powershell
git status --short --branch
```

Expected:

```text
## codex/agent-runtime-phase-a-security-hygiene
```

- [ ] **Step 2: Run focused execution baseline**

Run:

```powershell
python -m pytest -q python\tests\test_execution.py python\tests\test_execution_gateway_integration.py
```

Expected:

```text
... passed
```

- [ ] **Step 3: Run Phase E planner/graph baseline**

Run:

```powershell
python -m pytest -q python\tests\test_planner_chain.py python\tests\test_graph.py python\tests\test_agent_routing_integration.py
```

Expected:

```text
... passed
```

---

## Task 1: ExecutionGraph Contract And Compiler

**Files:**
- Create: `python/agent_service/execution_graph.py`
- Create: `python/tests/test_execution_graph.py`

- [ ] **Step 1: Write failing compiler tests**

Create `python/tests/test_execution_graph.py` with:

```python
from __future__ import annotations

import pytest

from agent_service.execution_graph import (
    ExecutionGraphError,
    compile_execution_graph,
    validate_execution_graph_bindings,
)
from agent_service.schemas import GraphEdge, GraphNode, RunGraph, RunGraphRequest


def _node(
    node_id: str,
    node_type: str,
    *,
    dependencies: list[str] | None = None,
    tool_ref: str | None = None,
    model_ref: str | None = None,
    permissions: list[str] | None = None,
) -> GraphNode:
    return GraphNode(
        nodeId=node_id,
        nodeType=node_type,
        displayName=node_id,
        status="waiting",
        summary=f"{node_id} summary",
        createdBy="test",
        inputPorts=[],
        outputPorts=[],
        dependencies=list(dependencies or []),
        toolRef=tool_ref,
        modelRef=model_ref,
        permissionsRequired=list(permissions or []),
        position={"x": 0, "y": 0},
    )


def _request(nodes: list[GraphNode]) -> RunGraphRequest:
    return RunGraphRequest(
        task_id="task-execution-graph",
        run_id="run-execution-graph",
        project_path="D:\\Project\\demo.alita",
        attachments=[],
        graph=RunGraph(
            graphId="graph-execution",
            nodes=nodes,
            edges=[
                GraphEdge(id=f"{source.nodeId}-{target.nodeId}", source=source.nodeId, target=target.nodeId)
                for source in nodes
                for target in nodes
                if source.nodeId in target.dependencies
            ],
            metadata={"kind": "task", "plannerChain": {"strategy": "legacy_task_planner"}},
        ),
    )


def test_compile_execution_graph_maps_tool_and_model_bindings() -> None:
    request = _request(
        [
            _node("inspect", "fixed_tool", tool_ref="internal:document.markitdown_convert", permissions=["read_attachment"]),
            _node("reason", "model", dependencies=["inspect"], model_ref="local-task-reasoner"),
            _node("output", "output", dependencies=["reason"]),
        ]
    )

    graph = compile_execution_graph(request)

    assert graph.graph_id == "graph-execution"
    assert graph.task_id == "task-execution-graph"
    assert graph.metadata["plannerChain"]["strategy"] == "legacy_task_planner"
    inspect = graph.node_by_id("inspect")
    reason = graph.node_by_id("reason")
    output = graph.node_by_id("output")
    assert inspect.tool_binding is not None
    assert inspect.tool_binding.tool_id == "document.markitdown_convert"
    assert inspect.permissions_required == ["read_attachment"]
    assert reason.model_binding is not None
    assert reason.model_binding.model_ref == "local-task-reasoner"
    assert reason.dependencies == ["inspect"]
    assert output.tool_binding is None
    assert output.model_binding is None


def test_validate_execution_graph_rejects_fixed_tool_without_binding() -> None:
    graph = compile_execution_graph(_request([_node("broken-tool", "fixed_tool")]))

    with pytest.raises(ExecutionGraphError, match="fixed_tool node broken-tool has no tool binding"):
        validate_execution_graph_bindings(graph)


def test_validate_execution_graph_rejects_model_without_binding() -> None:
    graph = compile_execution_graph(_request([_node("broken-model", "model")]))

    with pytest.raises(ExecutionGraphError, match="model node broken-model has no model binding"):
        validate_execution_graph_bindings(graph)


def test_execution_graph_node_by_id_reports_missing_node() -> None:
    graph = compile_execution_graph(_request([_node("output", "output")]))

    with pytest.raises(ExecutionGraphError, match="execution node not found: missing"):
        graph.node_by_id("missing")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_execution_graph.py
```

Expected:

```text
ModuleNotFoundError: No module named 'agent_service.execution_graph'
```

- [ ] **Step 3: Implement the compiler contract**

Create `python/agent_service/execution_graph.py` with:

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_service.harness_errors import HarnessError
from agent_service.schemas import GraphNode, RunGraphRequest
from agent_service.tool_protocol import provider_tool_id


class ExecutionGraphError(HarnessError):
    pass


class ExecutionToolBinding(BaseModel):
    tool_id: str
    operation: str | None = None
    arguments_template: dict[str, str] = Field(default_factory=dict)


class ExecutionModelBinding(BaseModel):
    model_ref: str
    prompt_template: str | None = None
    output_key: str = "text"


class ExecutionNode(BaseModel):
    node_id: str
    node_type: str
    dependencies: list[str] = Field(default_factory=list)
    tool_binding: ExecutionToolBinding | None = None
    model_binding: ExecutionModelBinding | None = None
    verifier_id: str | None = None
    permissions_required: list[str] = Field(default_factory=list)
    artifact_policy: dict[str, str] = Field(default_factory=dict)


class ExecutionGraph(BaseModel):
    graph_id: str
    task_id: str
    nodes: list[ExecutionNode]
    metadata: dict[str, Any] = Field(default_factory=dict)

    def node_by_id(self, node_id: str) -> ExecutionNode:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise ExecutionGraphError(
            "missing_execution_node",
            f"execution node not found: {node_id}",
        )


def compile_execution_graph(request: RunGraphRequest) -> ExecutionGraph:
    return ExecutionGraph(
        graph_id=request.graph.graphId,
        task_id=request.task_id,
        nodes=[_compile_node(node) for node in request.graph.nodes],
        metadata=dict(request.graph.metadata),
    )


def validate_execution_graph_bindings(execution_graph: ExecutionGraph) -> None:
    for node in execution_graph.nodes:
        if node.node_type == "fixed_tool" and node.tool_binding is None:
            raise ExecutionGraphError(
                "unsupported_binding",
                f"fixed_tool node {node.node_id} has no tool binding",
            )
        if node.node_type == "model" and node.model_binding is None:
            raise ExecutionGraphError(
                "unsupported_binding",
                f"model node {node.node_id} has no model binding",
            )


def _compile_node(node: GraphNode) -> ExecutionNode:
    return ExecutionNode(
        node_id=node.nodeId,
        node_type=node.nodeType,
        dependencies=list(node.dependencies),
        tool_binding=_tool_binding_for_node(node),
        model_binding=_model_binding_for_node(node),
        permissions_required=list(node.permissionsRequired),
    )


def _tool_binding_for_node(node: GraphNode) -> ExecutionToolBinding | None:
    if node.nodeType != "fixed_tool" or not node.toolRef:
        return None
    return ExecutionToolBinding(tool_id=provider_tool_id(node.toolRef))


def _model_binding_for_node(node: GraphNode) -> ExecutionModelBinding | None:
    if node.nodeType != "model" or not node.modelRef:
        return None
    return ExecutionModelBinding(model_ref=node.modelRef)
```

- [ ] **Step 4: Run compiler tests**

Run:

```powershell
python -m pytest -q python\tests\test_execution_graph.py
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/execution_graph.py python/tests/test_execution_graph.py
git commit -m "feat: add execution graph compiler"
```

---

## Task 2: PlannedTaskExecutor Binding Lookup

**Files:**
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_execution.py`

- [ ] **Step 1: Add failing executor binding lookup test**

Append to `python/tests/test_execution.py`:

```python
from agent_service.execution_graph import compile_execution_graph


def test_planned_executor_uses_execution_graph_tool_binding(tmp_path: Path) -> None:
    request = RunGraphRequest(
        task_id="task-binding-runtime",
        run_id="run-binding-runtime",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph=RunGraph(
            graphId="binding-graph",
            nodes=[
                _graph_node(
                    "tool-node",
                    "fixed_tool",
                    tool_ref="internal:document.markitdown_convert",
                )
            ],
            edges=[],
            metadata={"plannerChain": {"strategy": "legacy_task_planner"}},
        ),
    )
    execution_graph = compile_execution_graph(request)
    request.graph.nodes[0].toolRef = "internal:missing.after.compile"
    executor = PlannedTaskExecutor(
        request,
        tool_registry=_tool_registry_with_document_tools(),
        tool_gateway=RecordingGateway(),
        execution_graph=execution_graph,
    )

    with pytest.raises(HarnessError, match="document.markitdown_convert"):
        executor.run("tool-node", {})
```

If `test_execution.py` does not already expose `_graph_node()` or `_tool_registry_with_document_tools()`, create local helpers in the test file with this shape:

```python
def _graph_node(node_id: str, node_type: str, *, tool_ref: str | None = None, model_ref: str | None = None) -> GraphNode:
    return GraphNode(
        nodeId=node_id,
        nodeType=node_type,
        displayName=node_id,
        status="waiting",
        summary=node_id,
        createdBy="test",
        inputPorts=[],
        outputPorts=[],
        dependencies=[],
        toolRef=tool_ref,
        modelRef=model_ref,
        position={"x": 0, "y": 0},
    )
```

- [ ] **Step 2: Run the targeted test and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_execution.py::test_planned_executor_uses_execution_graph_tool_binding
```

Expected:

```text
TypeError: PlannedTaskExecutor.__init__() got an unexpected keyword argument 'execution_graph'
```

- [ ] **Step 3: Add execution graph to PlannedTaskExecutor**

In `python/agent_service/execution.py`, add imports:

```python
from agent_service.execution_graph import (
    ExecutionGraph,
    compile_execution_graph,
    validate_execution_graph_bindings,
)
```

Change `PlannedTaskExecutor.__init__()` to accept and store the compiled graph:

```python
        execution_graph: ExecutionGraph | None = None,
```

Inside `__init__()` after `self.nodes_by_id`:

```python
        self.execution_graph = execution_graph or compile_execution_graph(request)
```

Change `_run_fixed_tool_node()` to read the normalized binding:

```python
        execution_node = self.execution_graph.node_by_id(node.nodeId)
        if execution_node.tool_binding is None:
            raise HarnessError(
                "unsupported_binding",
                f"fixed_tool node {node.nodeId} has no tool binding",
            )
        tool_id = execution_node.tool_binding.tool_id
```

Leave the existing `self._call_tool(node, operation=operation, arguments=arguments)` call shape unchanged for this task. It still receives the public node and current event behavior stays stable.

Change model-node lookup in `run()` to read the normalized binding:

```python
            execution_node = self.execution_graph.node_by_id(node_id)
            model_binding = execution_node.model_binding
            if model_binding is None or model_binding.model_ref not in SUPPORTED_PLANNED_MODEL_REFS:
                raise HarnessError(
                    "unsupported_runtime",
                    f"model node {node_id} has no bound runtime: "
                    f"{model_binding.model_ref if model_binding is not None else '<missing>'}",
                )
```

Keep the public `GraphNode` as the input to `_planned_model_prompt()` and `policy_for_graph_node()` in Phase F.

- [ ] **Step 4: Run targeted executor test**

Run:

```powershell
python -m pytest -q python\tests\test_execution.py::test_planned_executor_uses_execution_graph_tool_binding
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Run execution regressions**

Run:

```powershell
python -m pytest -q python\tests\test_execution.py python\tests\test_execution_gateway_integration.py
```

Expected:

```text
... passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add python/agent_service/execution.py python/tests/test_execution.py
git commit -m "refactor: use execution graph bindings in planned executor"
```

---

## Task 3: Validate Bindings Before Node Execution

**Files:**
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_execution.py`

- [ ] **Step 1: Add failing early validation test**

Append to `python/tests/test_execution.py`:

```python
def test_missing_fixed_tool_binding_fails_before_run_started(tmp_path: Path) -> None:
    request = RunGraphRequest(
        task_id="task-missing-binding",
        run_id="run-missing-binding",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph=RunGraph(
            graphId="missing-binding-graph",
            nodes=[
                _graph_node("missing-tool", "fixed_tool"),
                _graph_node("task-output", "output"),
            ],
            edges=[],
            metadata={"plannerChain": {"strategy": "legacy_task_planner"}},
        ),
    )

    events = list(run_graph_events(request))

    assert [event.type for event in events] == ["task.failed"]
    assert events[0].payload["errorCode"] == "unsupported_binding"
    assert "missing-tool" in events[0].payload["error"]
```

- [ ] **Step 2: Run the targeted test and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_execution.py::test_missing_fixed_tool_binding_fails_before_run_started
```

Expected:

```text
AssertionError
```

The old behavior may emit `run.started` or `unsupported_tool`; Phase F should produce the precise binding validation error before node execution starts.

- [ ] **Step 3: Compile and validate ExecutionGraph in `run_graph_events()`**

In `run_graph_events()`, inside the existing initial `try` block after `ordered_nodes = _topological_nodes(request)`, add:

```python
        execution_graph = compile_execution_graph(request)
        validate_execution_graph_bindings(execution_graph)
```

Then pass `execution_graph` into `PlannedTaskExecutor`:

```python
            execution_graph=execution_graph,
```

For non-planned graphs, the compiled graph is still harmless. Validation allows output/planning/temporary_script nodes without bindings.

- [ ] **Step 4: Run targeted validation test**

Run:

```powershell
python -m pytest -q python\tests\test_execution.py::test_missing_fixed_tool_binding_fails_before_run_started
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Run execution regression tests**

Run:

```powershell
python -m pytest -q python\tests\test_execution_graph.py python\tests\test_execution.py python\tests\test_execution_gateway_integration.py
```

Expected:

```text
... passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add python/agent_service/execution.py python/tests/test_execution.py
git commit -m "feat: validate execution graph bindings before run"
```

---

## Task 4: Preserve Public Event And Journal Compatibility

**Files:**
- Modify: `python/tests/test_execution.py`
- Modify: `python/tests/test_agent_routing_integration.py`

- [ ] **Step 1: Add public shape regression test**

Append to `python/tests/test_execution.py`:

```python
def test_execution_graph_does_not_change_run_event_shape(tmp_path: Path) -> None:
    graph_event = run_agent(
        UserMessage(
            task_id="execution-graph-event-shape",
            content="Create a Python script that counts rows in a CSV file.",
        )
    )[0]
    graph = graph_event.payload["graph"]
    request = RunGraphRequest(
        task_id="execution-graph-event-shape",
        run_id="execution-graph-run",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph=RunGraph.model_validate(graph),
    )

    events = list(run_graph_events(request))

    assert events[0].type == "run.started"
    assert set(events[0].payload.keys()) == {"runId", "taskId", "startedAt"}
    assert all("executionGraph" not in event.payload for event in events)
```

- [ ] **Step 2: Run the public shape regression test**

Run:

```powershell
python -m pytest -q python\tests\test_execution.py::test_execution_graph_does_not_change_run_event_shape
```

Expected:

```text
1 passed
```

This test may already pass. Keep it as compatibility coverage.

- [ ] **Step 3: Run frontend event regression**

Run:

```powershell
npm run frontend:test -- src\app\backendEvents.test.ts
```

Expected:

```text
Test Files  1 passed
```

- [ ] **Step 4: Commit**

Run:

```powershell
git add python/tests/test_execution.py
git commit -m "test: preserve execution graph event shape"
```

---

## Task 5: Final Regression And Review

**Files:**
- Read: `python/agent_service/execution_graph.py`
- Read: `python/agent_service/execution.py`
- Read: `python/tests/test_execution_graph.py`
- Read: `python/tests/test_execution.py`

- [ ] **Step 1: Run Phase F focused tests**

Run:

```powershell
python -m pytest -q python\tests\test_execution_graph.py python\tests\test_execution.py python\tests\test_execution_gateway_integration.py
```

Expected:

```text
... passed
```

- [ ] **Step 2: Run planner/execution boundary tests**

Run:

```powershell
python -m pytest -q python\tests\test_planner_chain.py python\tests\test_graph.py python\tests\test_agent_routing_integration.py python\tests\test_execution.py
```

Expected:

```text
... passed
```

- [ ] **Step 3: Run frontend event regression**

Run:

```powershell
npm run frontend:test -- src\features\task\useTaskEvents.test.ts src\app\backendEvents.test.ts
```

Expected:

```text
Test Files  2 passed
```

- [ ] **Step 4: Run full MVP verification**

Run:

```powershell
.\scripts\verify-mvp.ps1
```

Expected:

```text
MVP verification passed.
```

- [ ] **Step 5: Confirm no Phase G/H scope leaked in**

Run:

```powershell
rg -n "ReAct|react_controller|tool_calls|ToolCall|sandbox|subprocess|network_allowed" python\agent_service\execution_graph.py python\agent_service\execution.py
```

Expected:

```text
```

No matches should appear except existing unrelated imports/comments that predate Phase F. Do not implement ReAct or sandbox execution in Phase F.

- [ ] **Step 6: Confirm worktree cleanliness**

Run:

```powershell
git status --short --branch
```

Expected:

```text
## codex/agent-runtime-phase-a-security-hygiene
```

- [ ] **Step 7: Final code review**

Dispatch a final code review over the Phase F commit range. Use this prompt:

```text
Review Phase F ExecutionGraph implementation. Prioritize whether public RunGraph/API/event shapes remain stable, whether fixed-tool and model bindings are normalized before execution, whether unsupported binding errors happen before node execution starts, whether existing gateway/permission/disabled-tool behavior is preserved, whether private ExecutionGraph data leaks into frontend events, and whether the implementation avoids ReAct, sandbox, MCP dynamic planning, durable execution, or memory scope.
```

Expected: reviewer returns no critical or important findings. Fix any critical or important finding before finishing Phase F.

---

## Acceptance Criteria

Phase F is complete when all statements are true:

- `python/agent_service/execution_graph.py` exists and is covered by `python/tests/test_execution_graph.py`.
- Public `RunGraphRequest.graph` compiles to private `ExecutionGraph`.
- Fixed-tool bindings are normalized into `ExecutionToolBinding`.
- Model bindings are normalized into `ExecutionModelBinding`.
- Output, planning, and temporary script nodes preserve dependencies and public node IDs.
- `run_graph_events()` validates execution bindings before run start and before any node execution.
- `PlannedTaskExecutor` can use `ExecutionGraph` for fixed-tool and model binding lookup.
- Public event payloads do not expose `ExecutionGraph`.
- Existing Unified Tool Gateway execution remains intact.
- Existing permission-required behavior for temporary scripts remains intact.
- Existing frontend event reducer tests pass.
- No ReAct, sandbox execution, dynamic MCP planning, durable checkpointing, or memory behavior is introduced.
- `.\scripts\verify-mvp.ps1` passes.

## Handoff Notes For Phase G

Phase G can attach a bounded ReAct controller to selected model nodes after Phase F lands. It should use `ExecutionGraph` to determine model bindings and allowed tools, and all tool calls must enter through `UnifiedToolGateway`. Phase G should not execute temporary scripts; that remains Phase H.
