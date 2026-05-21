# Agent Kernel Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first production safety and recovery layer after Phase 2: node permission gating, deterministic failure repair suggestions, and stronger checkpoint resume behavior.

**Architecture:** Phase 3 keeps Phase 2's deterministic planner and sequential executor. It adds a `PermissionGate` before node execution, a `FailureReplanner` that emits graph patch suggestions after known failures, and checkpoint tests that prove partial reruns still verify final outputs using source journal outputs. The implementation intentionally does not add temporary script execution, sandboxing, automatic graph mutation, web research execution, or UI approval controls.

**Tech Stack:** Python 3.12, FastAPI sidecar event models, Pydantic schemas, pytest, React/TypeScript event reducer tests, Vitest.

---

## Scope

Phase 3 includes:

- Backend permission metadata on graph nodes and run requests.
- A deterministic permission gate with safe defaults for the current document workflow.
- Backend `permission.required` events and frontend reducer handling.
- A deterministic `FailureReplanner` that emits `graph.patch_suggested` events for known recoverable failures.
- Resume-mode hardening tests for `failed_only` and `from_node` with final verification.

Phase 3 excludes:

- User-facing approval controls.
- Temporary Python script execution or sandboxing.
- Automatic application of graph patches.
- Network/web research execution.
- Parallel node scheduling.
- Rust project schema changes.

## File Structure

Create:

- `python/agent_service/permission_gate.py`
  - Holds permission policy, permission extraction from graph nodes/tool manifests, and denial errors.
- `python/tests/test_permission_gate.py`
  - Unit tests for safe defaults, approval overrides, and tool manifest fallback permissions.
- `python/agent_service/replan.py`
  - Holds graph patch data structures and deterministic failure-to-patch mapping.
- `python/tests/test_replan.py`
  - Unit tests for failure repair suggestions.

Modify:

- `python/agent_service/schemas.py`
  - Add optional node permission metadata and request approved permission list.
- `python/agent_service/graph_compiler.py`
  - Project `TaskNode.risk_level` and `TaskNode.permissions_required` into UI graph dictionaries.
- `python/agent_service/execution.py`
  - Run permission gate before node execution.
  - Emit permission events and graph patch suggestion events.
  - Preserve existing run journal and failure semantics.
- `python/tests/test_graph_compiler.py`
  - Assert compiled graphs carry permission metadata.
- `python/tests/test_execution.py`
  - Cover permission gate integration, patch suggestion events, and checkpoint resume final verification.
- `src/shared/types.ts`
  - Add optional `riskLevel` and `permissionsRequired` fields to `AgentNode`.
  - Add optional `approvedPermissions` to graph run payload typing if the payload type lives there in the implementation.
- `src/shared/events.ts`
  - Add `graph.patch_suggested` event type and richer `permission.required` payload.
- `src/features/task/useTaskEvents.ts`
  - Allow optional `approvedPermissions` in `RunNodeGraphPayload` and send it as `approved_permissions`.
- `src/features/task/useTaskEvents.test.ts`
  - Assert `approved_permissions` is posted when present and defaults to `[]`.
- `src/app/backendEvents.ts`
  - Handle `permission.required` by marking the node as `needs_permission`.
  - Handle `graph.patch_suggested` as a chat-visible advisory event.
- `src/app/backendEvents.test.ts`
  - Assert permission events update node status and script review permission text.

Read-only reference files:

- `python/agent_service/final_verifier.py`
- `python/agent_service/task_graph.py`
- `python/agent_service/tool_registry.py`
- `python/agent_service/tool_execution.py`
- `src/shared/events.ts`
- `src/shared/types.ts`

---

## Task 0: Baseline Verification

**Files:**
- Read: `python/tests/test_execution.py`
- Read: `src/features/task/useTaskEvents.test.ts`
- Read: `src/app/backendEvents.test.ts`

- [ ] **Step 1: Verify branch and clean status**

Run:

```powershell
git status --short --branch
```

Expected:

```text
## codex/agent-kernel-phase-3-plan
```

No modified files should be listed before implementation starts.

- [ ] **Step 2: Run backend baseline tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_execution.py tests/test_graph_compiler.py tests/test_final_verifier.py -v
Pop-Location
```

Expected: all selected tests pass.

- [ ] **Step 3: Run frontend event baseline tests**

Run:

```powershell
npm run frontend:test -- src/app/backendEvents.test.ts src/features/task/useTaskEvents.test.ts
```

Expected: all selected Vitest tests pass.

---

## Task 1: Permission Schema And Compiler Projection

**Files:**
- Modify: `python/agent_service/schemas.py`
- Modify: `python/agent_service/graph_compiler.py`
- Modify: `python/tests/test_graph_compiler.py`
- Modify: `src/shared/types.ts`

- [ ] **Step 1: Add failing backend compiler test**

In `python/tests/test_graph_compiler.py`, add:

```python
def test_compiled_graph_includes_permission_metadata() -> None:
    graph = build_document_task_graph("task-permissions", _goal_spec())

    compiled = compile_task_graph_to_node_graph(graph)

    nodes_by_id = {node["nodeId"]: node for node in compiled["nodes"]}
    assert nodes_by_id["document-input"]["riskLevel"] == "read_only"
    assert nodes_by_id["document-input"]["permissionsRequired"] == [
        "read_attachment"
    ]
    assert nodes_by_id["typst-export"]["riskLevel"] == "local_write"
    assert nodes_by_id["typst-export"]["permissionsRequired"] == [
        "write_project_artifact"
    ]
```

- [ ] **Step 2: Run the failing backend compiler test**

Run:

```powershell
Push-Location python
python -m pytest tests/test_graph_compiler.py::test_compiled_graph_includes_permission_metadata -v
Pop-Location
```

Expected: FAIL with `KeyError: 'riskLevel'`.

- [ ] **Step 3: Extend backend schemas**

In `python/agent_service/schemas.py`, add this alias near `ScriptReviewState`.
Do not import `RiskLevel` from `goal_spec.py`; `goal_spec.py` already imports
`UserMessage` from `schemas.py`, so importing back would create a circular import.

```python
GraphRiskLevel = Literal[
    "read_only",
    "local_write",
    "local_modify",
    "destructive",
    "network",
    "external_comm",
    "system",
]
```

Add fields to `GraphNode`:

```python
    riskLevel: GraphRiskLevel | None = None
    permissionsRequired: list[str] = Field(default_factory=list)
```

Add this field to `RunGraphRequest`:

```python
    approved_permissions: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Project metadata in graph compiler**

In `python/agent_service/graph_compiler.py`, add these keys to `compiled_node` inside `_compile_node`:

```python
        "riskLevel": node.risk_level,
        "permissionsRequired": list(node.permissions_required),
```

- [ ] **Step 5: Update frontend node type**

In `src/shared/types.ts`, add:

```ts
export type RiskLevel =
  | "read_only"
  | "local_write"
  | "local_modify"
  | "destructive"
  | "network"
  | "external_comm"
  | "system";
```

Add optional fields to `AgentNode`:

```ts
  riskLevel?: RiskLevel;
  permissionsRequired?: string[];
```

- [ ] **Step 6: Run compiler and type checks**

Run:

```powershell
Push-Location python
python -m pytest tests/test_graph_compiler.py -v
Pop-Location
npm run frontend:lint
```

Expected: all tests and TypeScript checks pass.

- [ ] **Step 7: Commit**

Run:

```powershell
git add python/agent_service/schemas.py python/agent_service/graph_compiler.py python/tests/test_graph_compiler.py src/shared/types.ts
git commit -m "feat: project graph permission metadata"
```

Expected: commit succeeds.

---

## Task 2: Permission Gate Unit

**Files:**
- Create: `python/agent_service/permission_gate.py`
- Create: `python/tests/test_permission_gate.py`

- [ ] **Step 1: Add failing permission gate tests**

Create `python/tests/test_permission_gate.py`:

```python
from __future__ import annotations

import pytest

from agent_service.harness_errors import HarnessError
from agent_service.permission_gate import PermissionGate
from agent_service.schemas import GraphNode
from agent_service.tool_registry import ToolManifestSpec, ToolOperationSpec, ToolRegistry


def test_allows_default_document_permissions() -> None:
    node = _node(
        "typst-export",
        tool_ref="document.typst_compile",
        permissions=["write_project_artifact"],
    )

    PermissionGate().ensure_node_allowed(node, tool_registry=_registry())


def test_rejects_network_permission_without_approval() -> None:
    node = _node("web-search", permissions=["network"])

    with pytest.raises(HarnessError) as exc_info:
        PermissionGate().ensure_node_allowed(node, tool_registry=_registry())

    assert exc_info.value.code == "permission_required"
    assert "network" in exc_info.value.message


def test_allows_permission_when_request_approves_it() -> None:
    node = _node("web-search", permissions=["network"])

    PermissionGate(approved_permissions=["network"]).ensure_node_allowed(
        node,
        tool_registry=_registry(),
    )


def test_uses_tool_manifest_permissions_when_node_permissions_are_empty() -> None:
    node = _node("custom-tool", tool_ref="custom.network_tool", permissions=[])

    with pytest.raises(HarnessError) as exc_info:
        PermissionGate().ensure_node_allowed(node, tool_registry=_registry())

    assert exc_info.value.code == "permission_required"
    assert "network" in exc_info.value.message


def _node(
    node_id: str,
    *,
    tool_ref: str | None = None,
    permissions: list[str],
) -> GraphNode:
    return GraphNode(
        nodeId=node_id,
        nodeType="fixed_tool" if tool_ref else "model",
        displayName=node_id,
        status="waiting",
        toolRef=tool_ref,
        summary="test node",
        createdBy="agent",
        position={"x": 0, "y": 0},
        permissionsRequired=permissions,
    )


def _registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolManifestSpec(
                tool_id="document.typst_compile",
                name="Typst",
                description="Compile local report artifacts.",
                version="1.0.0",
                source_type="local",
                license="internal",
                runtime="python_sidecar",
                entrypoint=None,
                capabilities=["document.export.pdf"],
                operations=[
                    ToolOperationSpec(
                        name="compile_report_pdf",
                        description="Compile a report PDF.",
                    )
                ],
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                permissions=["write_project_outputs"],
                error_codes=[],
                timeout_policy={},
                artifact_policy={},
                security_policy={},
                examples=[],
                node_templates=[],
            ),
            ToolManifestSpec(
                tool_id="custom.network_tool",
                name="Network Tool",
                description="Uses network.",
                version="1.0.0",
                source_type="local",
                license="internal",
                runtime="python_sidecar",
                entrypoint=None,
                capabilities=["web.search"],
                operations=[
                    ToolOperationSpec(name="search", description="Search web.")
                ],
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                permissions=["network"],
                error_codes=[],
                timeout_policy={},
                artifact_policy={},
                security_policy={},
                examples=[],
                node_templates=[],
            ),
        ]
    )
```

- [ ] **Step 2: Run the failing permission gate tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_permission_gate.py -v
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.permission_gate'`.

- [ ] **Step 3: Implement permission gate**

Create `python/agent_service/permission_gate.py`:

```python
from __future__ import annotations

from collections.abc import Iterable

from agent_service.harness_errors import HarnessError
from agent_service.schemas import GraphNode
from agent_service.tool_registry import ToolRegistry


DEFAULT_ALLOWED_PERMISSIONS = frozenset(
    {
        "read_attachment",
        "read_project_files",
        "write_project_artifact",
        "write_project_outputs",
    }
)


class PermissionGate:
    def __init__(
        self,
        *,
        approved_permissions: Iterable[str] | None = None,
        default_allowed_permissions: Iterable[str] | None = None,
    ) -> None:
        self.approved_permissions = set(approved_permissions or [])
        self.default_allowed_permissions = set(
            default_allowed_permissions or DEFAULT_ALLOWED_PERMISSIONS
        )

    def required_permissions(
        self,
        node: GraphNode,
        *,
        tool_registry: ToolRegistry,
    ) -> list[str]:
        permissions = list(node.permissionsRequired)
        if not permissions and node.toolRef:
            try:
                permissions = list(tool_registry.get(node.toolRef).permissions)
            except KeyError:
                permissions = []
        if node.scriptReview is not None:
            permissions.extend(node.scriptReview.permissions)
        return _dedupe(permissions)

    def denied_permissions(
        self,
        node: GraphNode,
        *,
        tool_registry: ToolRegistry,
    ) -> list[str]:
        allowed = self.default_allowed_permissions | self.approved_permissions
        return [
            permission
            for permission in self.required_permissions(node, tool_registry=tool_registry)
            if permission not in allowed
        ]

    def ensure_node_allowed(
        self,
        node: GraphNode,
        *,
        tool_registry: ToolRegistry,
    ) -> None:
        denied = self.denied_permissions(node, tool_registry=tool_registry)
        if denied:
            raise HarnessError(
                "permission_required",
                (
                    f"node {node.nodeId} requires permission approval: "
                    f"{', '.join(denied)}"
                ),
            )


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
```

- [ ] **Step 4: Run permission gate tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_permission_gate.py -v
Pop-Location
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/permission_gate.py python/tests/test_permission_gate.py
git commit -m "feat: add execution permission gate"
```

Expected: commit succeeds.

---

## Task 3: Permission Gate Execution Integration

**Files:**
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_execution.py`

- [ ] **Step 1: Add failing execution tests**

In `python/tests/test_execution.py`, add:

```python
def test_execution_emits_permission_required_before_running_blocked_node(
    tmp_path: Path,
) -> None:
    request = build_request(
        tmp_path,
        nodes=[
            build_node(
                "network-node",
                "model",
                [],
                permissions=["network"],
            )
        ],
    )

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert "node.running" not in [event.type for event in events]
    assert events[0].type == "run.started"
    assert events[1].type == "permission.required"
    assert events[1].payload["nodeId"] == "network-node"
    assert events[1].payload["permissions"] == ["network"]
    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "permission_required"


def test_execution_runs_blocked_permission_when_approved(tmp_path: Path) -> None:
    request = build_request(
        tmp_path,
        nodes=[
            build_node(
                "network-node",
                "model",
                [],
                permissions=["network"],
            )
        ],
    )
    request.approved_permissions = ["network"]

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert "node.running" in [event.type for event in events]
    assert events[-1].type == "task.completed"
```

Modify `build_node` test helper in the same file to accept permissions:

```python
def build_node(
    node_id: str,
    node_type: str,
    dependencies: list[str],
    *,
    tool_ref: str | None = None,
    model_ref: str | None = None,
    permissions: list[str] | None = None,
) -> dict:
    node = {
        "nodeId": node_id,
        "nodeType": node_type,
        "displayName": node_id,
        "status": "waiting",
        "inputPorts": [],
        "outputPorts": [],
        "dependencies": dependencies,
        "summary": "测试节点",
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "position": {"x": 0, "y": 0},
        "permissionsRequired": permissions or [],
    }
```

- [ ] **Step 2: Run the failing execution tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_execution.py::test_execution_emits_permission_required_before_running_blocked_node tests/test_execution.py::test_execution_runs_blocked_permission_when_approved -v
Pop-Location
```

Expected: FAIL because `permission.required` is not emitted.

- [ ] **Step 3: Integrate permission gate in execution**

In `python/agent_service/execution.py`, import:

```python
from agent_service.permission_gate import PermissionGate
```

Add parameter to `run_graph_events`:

```python
    permission_gate: PermissionGate | None = None,
```

After `_validate_graph_tools`, keep the concrete registry in a local variable:

```python
        effective_tool_registry = tool_registry or _default_tool_registry()
        _validate_graph_tools(request, effective_tool_registry)
```

Create the gate after `disabled_tool_ids`:

```python
    gate = permission_gate or PermissionGate(
        approved_permissions=request.approved_permissions
    )
```

Before `if cancel_token.cancelled:` and before writing a node running record, add:

```python
            denied_permissions = gate.denied_permissions(
                node,
                tool_registry=effective_tool_registry,
            )
            if denied_permissions:
                completed_at = _now_iso()
                error = HarnessError(
                    "permission_required",
                    (
                        f"node {node.nodeId} requires permission approval: "
                        f"{', '.join(denied_permissions)}"
                    ),
                )
                payload = harness_error_payload(error)
                record = {
                    "nodeRunId": f"{request.run_id}-{node.nodeId}",
                    "runId": request.run_id,
                    "nodeId": node.nodeId,
                    "status": "needs_permission",
                    "startedAt": completed_at,
                    "completedAt": completed_at,
                    "artifactRefs": [],
                    "error": str(error),
                    "values": {},
                }
                journal.write_node(node.nodeId, record)
                journal.write_run(
                    {
                        "runId": request.run_id,
                        "taskId": request.task_id,
                        "status": "failed",
                        "startedAt": started_at,
                        "completedAt": completed_at,
                        "mode": request.mode.model_dump(),
                    }
                )
                yield AgentEvent(
                    type="permission.required",
                    payload={
                        "nodeId": node.nodeId,
                        "taskId": request.task_id,
                        "runId": request.run_id,
                        "permissions": denied_permissions,
                    },
                )
                yield AgentEvent(
                    type="node.run_recorded",
                    payload={"record": _event_record(record)},
                )
                yield AgentEvent(
                    type="task.failed",
                    payload={
                        "taskId": request.task_id,
                        "runId": request.run_id,
                        **payload,
                    },
                )
                return
```

- [ ] **Step 4: Run execution tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_permission_gate.py tests/test_execution.py -v
Pop-Location
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/execution.py python/tests/test_execution.py
git commit -m "feat: gate graph execution by permissions"
```

Expected: commit succeeds.

---

## Task 4: Frontend Permission Event Handling

**Files:**
- Modify: `src/shared/events.ts`
- Modify: `src/features/task/useTaskEvents.ts`
- Modify: `src/features/task/useTaskEvents.test.ts`
- Modify: `src/app/backendEvents.ts`
- Modify: `src/app/backendEvents.test.ts`

- [ ] **Step 1: Add failing frontend tests**

In `src/features/task/useTaskEvents.test.ts`, add:

```ts
it("posts approved permissions with graph run requests", async () => {
  const graph: NodeGraph = { graphId: "graph-1", nodes: [], edges: [] };
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(
      new Response(
        'data: {"type":"run.started","payload":{"runId":"run-1","taskId":"task-1","startedAt":"2026-05-10T00:00:00.000Z"}}\n\n',
      ),
    );

  await runNodeGraphStream(
    {
      runId: "run-1",
      taskId: "task-1",
      projectPath: "D:\\Project\\demo.alita",
      graph,
      attachments: [],
      approvedPermissions: ["network"],
      mode: { type: "full" },
    },
    () => undefined,
  );

  expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
    approved_permissions: ["network"],
  });
});
```

In `src/app/backendEvents.test.ts`, add:

```ts
it("marks a node as needing permission when permission.required is received", () => {
  const result = reduceBackendEvents(
    {
      messages: [],
      graph: graphWithNode,
      dirty: false,
      activeRunId: "run-1",
    },
    [
      {
        type: "permission.required",
        payload: {
          nodeId: "document-parse",
          taskId: "task-1",
          runId: "run-1",
          permissions: ["network"],
        },
      },
    ],
    createAssistantMessage,
  );

  expect(result.graph?.nodes[0].status).toBe("needs_permission");
  expect(result.graph?.nodes[0].scriptReview).toEqual({
    status: "reviewing",
    summary: "节点需要授权后才能继续执行。",
    permissions: ["network"],
  });
});
```

- [ ] **Step 2: Run failing frontend tests**

Run:

```powershell
npm run frontend:test -- src/features/task/useTaskEvents.test.ts src/app/backendEvents.test.ts
```

Expected: FAIL because `approvedPermissions` and reducer handling are absent.

- [ ] **Step 3: Update frontend event types**

In `src/shared/events.ts`, change `permission.required` payload to:

```ts
      payload: {
        nodeId: string;
        taskId?: string;
        runId?: string;
        permissions: string[];
      };
```

- [ ] **Step 4: Send approved permissions to sidecar**

In `src/features/task/useTaskEvents.ts`, add to `RunNodeGraphPayload`:

```ts
  approvedPermissions?: string[];
```

Add this key to the graph run request body:

```ts
      approved_permissions: payload.approvedPermissions ?? [],
```

- [ ] **Step 5: Handle permission event in reducer**

In `src/app/backendEvents.ts`, before the `artifact.created` block, add:

```ts
    if (event.type === "permission.required") {
      return updateNode(current, event.payload.nodeId, {
        status: "needs_permission",
        scriptReview: {
          status: "reviewing",
          summary: "节点需要授权后才能继续执行。",
          permissions: event.payload.permissions,
        },
      });
    }
```

- [ ] **Step 6: Run frontend tests and lint**

Run:

```powershell
npm run frontend:test -- src/features/task/useTaskEvents.test.ts src/app/backendEvents.test.ts
npm run frontend:lint
```

Expected: tests and TypeScript checks pass.

- [ ] **Step 7: Commit**

Run:

```powershell
git add src/shared/events.ts src/features/task/useTaskEvents.ts src/features/task/useTaskEvents.test.ts src/app/backendEvents.ts src/app/backendEvents.test.ts
git commit -m "feat: surface graph permission requirements"
```

Expected: commit succeeds.

---

## Task 5: Failure Replanner Unit

**Files:**
- Create: `python/agent_service/replan.py`
- Create: `python/tests/test_replan.py`

- [ ] **Step 1: Add failing replanner tests**

Create `python/tests/test_replan.py`:

```python
from __future__ import annotations

from agent_service.harness_errors import HarnessError
from agent_service.replan import FailureReplanner
from agent_service.schemas import RunGraphRequest


def test_replanner_suggests_retry_for_empty_node_output(tmp_path) -> None:
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = _request(tmp_path)
    node = request.graph.nodes[2]

    suggestion = FailureReplanner().propose(
        request=request,
        failed_node=node,
        error=HarnessError("empty_node_output", "node content-organize returned empty value"),
    )

    assert suggestion is not None
    assert suggestion.reason == "node content-organize returned empty value"
    assert suggestion.operations[0].op == "retry_node"
    assert suggestion.operations[0].node_id == "content-organize"


def test_replanner_suggests_rerun_missing_artifact_node(tmp_path) -> None:
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = _request(tmp_path)
    node = request.graph.nodes[-1]

    suggestion = FailureReplanner().propose(
        request=request,
        failed_node=node,
        error=HarnessError("missing_artifact", "artifact does not exist"),
    )

    assert suggestion is not None
    assert suggestion.operations[0].op == "rerun_node"
    assert suggestion.operations[0].node_id == "file-export"


def test_replanner_returns_none_for_permission_required(tmp_path) -> None:
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = _request(tmp_path)

    suggestion = FailureReplanner().propose(
        request=request,
        failed_node=request.graph.nodes[0],
        error=HarnessError("permission_required", "approval required"),
    )

    assert suggestion is None


def _request(tmp_path) -> RunGraphRequest:
    return RunGraphRequest(
        task_id="task-replan",
        project_path=str(tmp_path / "project.alita"),
        graph={
            "graphId": "graph-replan",
            "nodes": [
                _node("document-input", "fixed_tool", []),
                _node("document-parse", "fixed_tool", ["document-input"]),
                _node("content-organize", "model", ["document-parse"]),
                _node("file-export", "output", ["content-organize"]),
            ],
            "edges": [],
        },
    )


def _node(node_id: str, node_type: str, dependencies: list[str]) -> dict:
    return {
        "nodeId": node_id,
        "nodeType": node_type,
        "displayName": node_id,
        "status": "waiting",
        "inputPorts": [],
        "outputPorts": [],
        "dependencies": dependencies,
        "summary": "test node",
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "position": {"x": 0, "y": 0},
    }
```

- [ ] **Step 2: Run failing replanner tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_replan.py -v
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.replan'`.

- [ ] **Step 3: Implement deterministic replanner**

Create `python/agent_service/replan.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent_service.harness_errors import HarnessError
from agent_service.schemas import GraphNode, RunGraphRequest


GraphPatchOpName = Literal[
    "retry_node",
    "rerun_node",
    "rerun_from_node",
    "request_tool_enablement",
]


class GraphPatchOperation(BaseModel):
    op: GraphPatchOpName
    node_id: str
    reason: str


class ReplanSuggestion(BaseModel):
    reason: str
    operations: list[GraphPatchOperation] = Field(default_factory=list)
    requires_user_approval: bool = False


class FailureReplanner:
    def propose(
        self,
        *,
        request: RunGraphRequest,
        failed_node: GraphNode | None,
        error: Exception,
    ) -> ReplanSuggestion | None:
        if failed_node is None:
            return None

        code = error.code if isinstance(error, HarnessError) else "execution_failed"
        reason = str(error)

        if code == "empty_node_output":
            return _suggestion(reason, "retry_node", failed_node.nodeId)

        if code == "missing_artifact":
            return _suggestion(reason, "rerun_node", failed_node.nodeId)

        if code == "missing_dependency_output":
            return _suggestion(reason, "rerun_from_node", failed_node.nodeId)

        if code in {"tool_disabled", "unsupported_tool"}:
            return ReplanSuggestion(
                reason=reason,
                operations=[
                    GraphPatchOperation(
                        op="request_tool_enablement",
                        node_id=failed_node.nodeId,
                        reason=reason,
                    )
                ],
                requires_user_approval=True,
            )

        return None


def _suggestion(
    reason: str,
    op: GraphPatchOpName,
    node_id: str,
) -> ReplanSuggestion:
    return ReplanSuggestion(
        reason=reason,
        operations=[
            GraphPatchOperation(
                op=op,
                node_id=node_id,
                reason=reason,
            )
        ],
    )
```

- [ ] **Step 4: Run replanner tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_replan.py -v
Pop-Location
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/replan.py python/tests/test_replan.py
git commit -m "feat: add deterministic failure replanner"
```

Expected: commit succeeds.

---

## Task 6: Emit Replan Suggestions From Execution

**Files:**
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_execution.py`
- Modify: `src/shared/events.ts`
- Modify: `src/app/backendEvents.ts`
- Modify: `src/app/backendEvents.test.ts`

- [ ] **Step 1: Add failing execution event test**

In `python/tests/test_execution.py`, add:

```python
def test_execution_emits_replan_suggestion_for_empty_node_output(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.md"
    source.write_text("正文", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)

    class EmptyContentExecutor(FakeNodeExecutor):
        def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
            if node_id == "content-organize":
                return NodeOutput(values={"outline": ""})
            return super().run(node_id, inputs)

    events = list(run_graph_events(request, executor=EmptyContentExecutor()))

    suggestion_event = next(
        event for event in events if event.type == "graph.patch_suggested"
    )
    assert suggestion_event.payload["operations"][0]["op"] == "retry_node"
    assert suggestion_event.payload["operations"][0]["node_id"] == "content-organize"
    assert events[-1].type == "task.failed"
```

- [ ] **Step 2: Run failing execution event test**

Run:

```powershell
Push-Location python
python -m pytest tests/test_execution.py::test_execution_emits_replan_suggestion_for_empty_node_output -v
Pop-Location
```

Expected: FAIL because no `graph.patch_suggested` event exists.

- [ ] **Step 3: Add frontend event type**

In `src/shared/events.ts`, add this union member:

```ts
  | {
      type: "graph.patch_suggested";
      payload: {
        reason: string;
        operations: Array<{
          op:
            | "retry_node"
            | "rerun_node"
            | "rerun_from_node"
            | "request_tool_enablement";
          node_id: string;
          reason: string;
        }>;
        requires_user_approval: boolean;
      };
    }
```

- [ ] **Step 4: Wire replanner into execution**

In `python/agent_service/execution.py`, import:

```python
from agent_service.replan import FailureReplanner
```

Add parameter to `run_graph_events`:

```python
    failure_replanner: FailureReplanner | None = None,
```

Create the replanner after the final verifier:

```python
    replanner = failure_replanner or FailureReplanner()
```

Inside the node exception block, after `node.run_recorded` and before `task.failed`, add:

```python
                suggestion = replanner.propose(
                    request=request,
                    failed_node=node,
                    error=error,
                )
                if suggestion is not None:
                    yield AgentEvent(
                        type="graph.patch_suggested",
                        payload=suggestion.model_dump(),
                    )
```

Inside the final verifier exception block, pass the output node when possible:

```python
            output_node = next(
                (node for node in request.graph.nodes if node.nodeType == "output"),
                None,
            )
            suggestion = replanner.propose(
                request=request,
                failed_node=output_node,
                error=error,
            )
            if suggestion is not None:
                yield AgentEvent(
                    type="graph.patch_suggested",
                    payload=suggestion.model_dump(),
                )
```

- [ ] **Step 5: Add frontend reducer handling for graph patch suggestions**

In `src/app/backendEvents.test.ts`, add:

```ts
it("adds a chat notice when a graph patch is suggested", () => {
  const result = reduceBackendEvents(
    {
      messages: [],
      graph: graphWithNode,
      dirty: false,
    },
    [
      {
        type: "graph.patch_suggested",
        payload: {
          reason: "node content-organize returned empty value",
          operations: [
            {
              op: "retry_node",
              node_id: "content-organize",
              reason: "node content-organize returned empty value",
            },
          ],
          requires_user_approval: false,
        },
      },
    ],
    createAssistantMessage,
  );

  expect(result.messages[0].content).toContain("建议修复");
  expect(result.messages[0].content).toContain("retry_node");
});
```

In `src/app/backendEvents.ts`, before `task.completed`, add:

```ts
    if (event.type === "graph.patch_suggested") {
      const operations = event.payload.operations
        .map((operation) => `${operation.op}:${operation.node_id}`)
        .join("、");
      return {
        ...current,
        messages: [
          ...current.messages,
          createAssistantMessage(
            `建议修复：${event.payload.reason}（${operations}）`,
          ),
        ],
        dirty: true,
      };
    }
```

- [ ] **Step 6: Run execution and type tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_replan.py tests/test_execution.py -v
Pop-Location
npm run frontend:test -- src/app/backendEvents.test.ts
npm run frontend:lint
```

Expected: all tests and TypeScript checks pass.

- [ ] **Step 7: Commit**

Run:

```powershell
git add python/agent_service/execution.py python/tests/test_execution.py src/shared/events.ts src/app/backendEvents.ts src/app/backendEvents.test.ts
git commit -m "feat: emit graph repair suggestions"
```

Expected: commit succeeds.

---

## Task 7: Checkpoint Resume Hardening

**Files:**
- Modify: `python/tests/test_execution.py`
- Modify: `python/agent_service/execution.py` only if the new tests expose a bug.

- [ ] **Step 1: Add completed-source failed-only test**

In `python/tests/test_execution.py`, add:

```python
def test_failed_only_with_no_failed_nodes_verifies_source_final_output(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "report.md"
    artifact.write_text("report", encoding="utf-8")
    source_run = "run-all-completed"
    journal = RunJournal(project_path=str(tmp_path / "project.alita"), run_id=source_run)
    journal.write_node(
        "file-export",
        {
            "nodeId": "file-export",
            "status": "completed",
            "values": {"artifact": str(artifact)},
            "artifactRefs": [str(artifact)],
        },
    )
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source, run_id="run-no-failed")
    request.mode.type = "failed_only"
    request.mode.source_run_id = source_run

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert [event.type for event in events] == [
        "run.started",
        "task.completed",
    ]
```

- [ ] **Step 2: Add source artifact missing test**

In `python/tests/test_execution.py`, add:

```python
def test_failed_only_with_missing_source_final_artifact_fails_final_verification(
    tmp_path: Path,
) -> None:
    source_run = "run-missing-final-artifact"
    missing_artifact = tmp_path / "missing.md"
    journal = RunJournal(project_path=str(tmp_path / "project.alita"), run_id=source_run)
    journal.write_node(
        "file-export",
        {
            "nodeId": "file-export",
            "status": "completed",
            "values": {"artifact": str(missing_artifact)},
            "artifactRefs": [str(missing_artifact)],
        },
    )
    source = tmp_path / "input.md"
    source.write_text("content", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source, run_id="run-missing-final")
    request.mode.type = "failed_only"
    request.mode.source_run_id = source_run

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "missing_artifact"
    assert any(event.type == "graph.patch_suggested" for event in events)
```

- [ ] **Step 3: Run checkpoint tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_execution.py::test_failed_only_with_no_failed_nodes_verifies_source_final_output tests/test_execution.py::test_failed_only_with_missing_source_final_artifact_fails_final_verification -v
Pop-Location
```

Expected: both tests pass. If either fails, fix only the source-output hydration or final-verifier integration path needed by the failure.

- [ ] **Step 4: Run execution tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_execution.py -v
Pop-Location
```

Expected: all execution tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/tests/test_execution.py python/agent_service/execution.py
git commit -m "test: harden checkpoint final verification"
```

Expected: commit succeeds. If `execution.py` was not modified, do not include it in `git add`.

---

## Task 8: Phase 3 Regression

**Files:**
- Read: `python/tests/test_permission_gate.py`
- Read: `python/tests/test_replan.py`
- Read: `python/tests/test_execution.py`
- Read: `python/tests/test_graph_compiler.py`
- Read: `python/tests/test_final_verifier.py`
- Read: `src/app/backendEvents.test.ts`
- Read: `src/features/task/useTaskEvents.test.ts`

- [ ] **Step 1: Run Phase 3 focused backend tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_permission_gate.py tests/test_replan.py tests/test_execution.py tests/test_graph_compiler.py tests/test_final_verifier.py -v
Pop-Location
```

Expected: all selected backend tests pass.

- [ ] **Step 2: Run Phase 3 focused frontend tests**

Run:

```powershell
npm run frontend:test -- src/app/backendEvents.test.ts src/features/task/useTaskEvents.test.ts
npm run frontend:lint
```

Expected: selected frontend tests and TypeScript checks pass.

- [ ] **Step 3: Run full Python suite**

Run:

```powershell
Push-Location python
python -m pytest
Pop-Location
```

Expected: full Python suite passes.

- [ ] **Step 4: Inspect final branch status**

Run:

```powershell
git status --short --branch
```

Expected:

```text
## codex/agent-kernel-phase-3-plan
```

No modified files should be listed.

---

## Self-Review Checklist

- Phase 3 keeps existing document graph behavior working without approvals.
- Current document tools pass through the default permission allowlist.
- Network, system, destructive, external communication, and local modify permissions are blocked unless explicitly approved.
- Permission denial emits `permission.required`, records the node as `needs_permission`, and ends the run with `task.failed`.
- Permission denial does not emit `node.running`.
- `approved_permissions` is optional and defaults to `[]`.
- Replan suggestions are advisory events only; execution does not mutate the graph automatically.
- Replanner returns no suggestion for `permission_required` because permission flow is handled by `permission.required`.
- Final verifier still runs after selected nodes complete, including rerun modes with source outputs.
- Frontend changes are limited to event/request typing and reducer handling.
- No Rust schema change is required.
- No sandbox or temporary script execution is introduced.
