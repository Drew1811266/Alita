# Agent Runtime Phase G Bounded ReAct Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded ReAct controller for selected model nodes so model-requested tools can run through the Unified Tool Gateway with explicit budgets, allowlists, and safe observations.

**Architecture:** Create `react_controller.py` as a small deterministic loop around the existing `ModelClient`, `model_tool_adapter.py`, `UnifiedToolGateway`, and Phase F `ExecutionGraph` bindings. The first version accepts a local JSON action protocol and does not require provider-native tool-calling support; provider-native tool schemas can be exposed through `model_tool_adapter.py` but all execution still enters the gateway. This phase does not execute temporary scripts, add memory, or change public endpoint schemas.

**Tech Stack:** Python 3.12, Pydantic v2, existing `ModelClient` protocol, existing `UnifiedToolGateway`, existing `UnifiedToolInvocation`, existing `model_tool_adapter.py`, pytest.

---

## Current Baseline

Phase F must be complete before Phase G starts:

- `ExecutionGraph` exists as the private runtime model.
- `run_graph_events()` validates normalized bindings before node execution.
- All fixed-tool execution already goes through `UnifiedToolGateway`.
- `model_tool_adapter.py` can convert `UnifiedToolDefinition` to OpenAI-style tool schema and map model-safe tool names back to internal tool IDs.
- `PlannedTaskExecutor` still executes model nodes with one `model_client.chat()` call and no observe-act loop.

The current gap is controlled model-initiated action: model nodes cannot request tools, and there is no budgeted loop that records observations.

## Non-Goals

- Do not add temporary script execution; scripts remain Phase H.
- Do not add OpenAI-only provider behavior as the only path; keep local JSON action protocol working.
- Do not add MCP dynamic planning beyond tools already exposed through `UnifiedToolGateway`.
- Do not change frontend event schemas.
- Do not introduce unbounded loops, background tasks, or durable checkpointing.
- Do not let model-selected tools bypass permission, disabled-tool, project-root, or gateway checks.

## Files

### Create

- `python/agent_service/react_controller.py`
  - Defines `ReActPolicy`, `ReActAction`, `ReActObservation`, and `ReActResult`.
  - Parses local-model JSON actions.
  - Enforces step, tool-call, runtime, tool ID, and permission budgets.
  - Executes allowed tools through `UnifiedToolGateway`.
  - Builds safe observations for the next model turn.
- `python/tests/test_react_controller.py`
  - Unit tests for final answer, one tool call, budget failures, disallowed tools, malformed actions, and safe observations.

### Modify

- `python/agent_service/model_tool_adapter.py`
  - Add helpers to build a base `UnifiedToolInvocation` for model node calls.
  - Add safe observation conversion from `UnifiedToolResult`.
- `python/agent_service/execution.py`
  - Add a narrow integration path for model nodes whose graph metadata or node metadata enables ReAct.
  - Return `NodeOutput` with `values.text`, `values.react.toolCallCount`, and safe observations.
- `python/tests/test_model_tool_adapter.py`
  - Add tests for safe observation payloads and base invocation mapping.
- `python/tests/test_execution.py`
  - Add integration tests proving selected model nodes can run ReAct through a fake gateway and that ordinary model nodes still use one-shot execution.

---

## Design Contract

Create `python/agent_service/react_controller.py` with:

```python
from __future__ import annotations

from collections.abc import Callable
from time import monotonic
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from agent_service.model_client import ChatMessage
from agent_service.model_policy import ModelCallPolicy
from agent_service.tool_gateway import UnifiedToolGateway
from agent_service.tool_protocol import UnifiedToolDefinition, UnifiedToolInvocation


class ReActPolicy(BaseModel):
    enabled: bool = False
    max_steps: int = 4
    max_tool_calls: int = 3
    max_runtime_ms: int = 30000
    allowed_tool_ids: list[str] = Field(default_factory=list)
    allowed_permissions: list[str] = Field(default_factory=list)
    stop_on_first_success: bool = True


class ReActAction(BaseModel):
    kind: Literal["final", "tool"]
    text: str | None = None
    tool_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


class ReActObservation(BaseModel):
    tool_id: str
    ok: bool
    values: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    error_code: str | None = None


class ReActResult(BaseModel):
    ok: bool
    text: str
    tool_call_count: int
    observations: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None
```

Controller behavior:

- `ReActController.run(messages, tools, base_invocation, policy, model_policy=None) -> ReActResult`
  - Returns `ReActResult(ok=False, error_code="react_disabled")` if `policy.enabled` is false.
  - Calls the model at most `policy.max_steps` times.
  - Parses model output as JSON object:
    - final answer: `{"kind": "final", "text": "Document converted and saved."}`
    - tool action: `{"kind": "tool", "tool_id": "document.markitdown_convert", "arguments": {"input_path": "D:\\Project\\input.docx"}}`
  - Rejects malformed JSON as `error_code="malformed_action"`.
  - Rejects a tool ID not in `policy.allowed_tool_ids` as `error_code="tool_not_allowed"`.
  - Rejects tool calls after `max_tool_calls` as `error_code="tool_budget_exceeded"`.
  - Rejects elapsed runtime over `max_runtime_ms` as `error_code="runtime_budget_exceeded"`.
  - Calls `gateway.call_tool()` with `UnifiedToolInvocation` derived from `base_invocation`.
  - Adds safe observations to subsequent model messages.
  - If `stop_on_first_success` is true and the tool succeeds, asks the model for a final answer on the next step.

Observation safety:

- Do not include secret values.
- Do not include raw stderr.
- Do not include local absolute paths except artifact basenames.
- Keep values shallow and JSON-serializable.

---

## Task 0: Baseline Verification

**Files:**
- Read: `python/agent_service/model_tool_adapter.py`
- Read: `python/agent_service/execution.py`
- Read: `python/tests/test_model_tool_adapter.py`
- Read: `python/tests/test_execution.py`

- [ ] **Step 1: Confirm Phase F baseline**

Run:

```powershell
python -m pytest -q python\tests\test_execution_graph.py python\tests\test_execution.py python\tests\test_execution_gateway_integration.py
```

Expected:

```text
... passed
```

---

## Task 1: ReAct Controller Contract

**Files:**
- Create: `python/agent_service/react_controller.py`
- Create: `python/tests/test_react_controller.py`

- [ ] **Step 1: Write failing controller tests**

Create `python/tests/test_react_controller.py` with:

```python
from __future__ import annotations

from agent_service.model_client import ChatMessage
from agent_service.react_controller import ReActController, ReActPolicy
from agent_service.tool_protocol import (
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)


class SequencedModel:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[list[ChatMessage]] = []

    def chat(self, messages, *, temperature=None, max_tokens=None, policy=None):
        self.calls.append(messages)
        return self.replies.pop(0)


class RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[UnifiedToolInvocation] = []

    def call_tool(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        self.calls.append(invocation)
        return UnifiedToolResult(
            invocation_id=invocation.invocation_id,
            tool_id=invocation.tool_id,
            ok=True,
            values={"text": "tool observation", "secret": "sk-test"},
            artifacts=["D:\\Project\\artifacts\\result.md"],
        )


def _tool(tool_id: str = "internal:file.inspect") -> UnifiedToolDefinition:
    return UnifiedToolDefinition(
        id=tool_id,
        name="Inspect file",
        description="Inspect a local project file.",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
    )


def _base_invocation() -> UnifiedToolInvocation:
    return UnifiedToolInvocation(
        invocation_id="react-base",
        run_id="run-react",
        task_id="task-react",
        node_id="model-node",
        tool_id="internal:file.inspect",
        arguments={},
        project_path="D:\\Project\\demo.alita",
        allowed_roots=["D:\\Project"],
        requested_permissions=["read_project_files"],
    )


def test_react_controller_runs_one_tool_call_then_final_answer() -> None:
    model = SequencedModel(
        [
            '{"kind":"tool","tool_id":"internal:file.inspect","arguments":{"path":"README.md"}}',
            '{"kind":"final","text":"The file has 10 rows."}',
        ]
    )
    gateway = RecordingGateway()
    result = ReActController(model_client=model, gateway=gateway).run(
        messages=[ChatMessage(role="user", content="Inspect the file.")],
        tools=[_tool()],
        base_invocation=_base_invocation(),
        policy=ReActPolicy(
            enabled=True,
            max_steps=3,
            max_tool_calls=2,
            allowed_tool_ids=["internal:file.inspect"],
            allowed_permissions=["read_project_files"],
        ),
    )

    assert result.ok is True
    assert result.text == "The file has 10 rows."
    assert result.tool_call_count == 1
    assert gateway.calls[0].tool_id == "internal:file.inspect"
    assert result.observations[0]["values"]["text"] == "tool observation"
    assert "secret" not in result.observations[0]["values"]
    assert result.observations[0]["artifacts"] == ["result.md"]


def test_react_controller_rejects_disallowed_tool_id() -> None:
    model = SequencedModel(
        ['{"kind":"tool","tool_id":"internal:forbidden","arguments":{}}']
    )
    result = ReActController(model_client=model, gateway=RecordingGateway()).run(
        messages=[ChatMessage(role="user", content="Use a tool.")],
        tools=[_tool("internal:forbidden")],
        base_invocation=_base_invocation(),
        policy=ReActPolicy(enabled=True, allowed_tool_ids=["internal:file.inspect"]),
    )

    assert result.ok is False
    assert result.error_code == "tool_not_allowed"
    assert result.tool_call_count == 0


def test_react_controller_rejects_malformed_action() -> None:
    model = SequencedModel(["not json"])
    result = ReActController(model_client=model, gateway=RecordingGateway()).run(
        messages=[ChatMessage(role="user", content="Use a tool.")],
        tools=[_tool()],
        base_invocation=_base_invocation(),
        policy=ReActPolicy(enabled=True, allowed_tool_ids=["internal:file.inspect"]),
    )

    assert result.ok is False
    assert result.error_code == "malformed_action"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_react_controller.py
```

Expected:

```text
ModuleNotFoundError: No module named 'agent_service.react_controller'
```

- [ ] **Step 3: Implement minimal controller**

Create `python/agent_service/react_controller.py` implementing the design contract. Use this parsing helper:

```python
def _parse_action(raw: str) -> ReActAction | None:
    try:
        return ReActAction.model_validate_json(raw)
    except ValidationError:
        return None
```

Use this observation helper:

```python
def _safe_observation(result) -> ReActObservation:
    values = {
        key: value
        for key, value in dict(result.values).items()
        if "secret" not in key.lower() and "key" not in key.lower()
    }
    artifacts = [Path(path).name for path in result.artifacts]
    return ReActObservation(
        tool_id=result.tool_id,
        ok=bool(result.ok),
        values=values,
        artifacts=artifacts,
        error_code=result.error_code,
    )
```

When building tool invocations, copy `base_invocation` fields and replace `invocation_id`, `tool_id`, and `arguments`.

- [ ] **Step 4: Run controller tests**

Run:

```powershell
python -m pytest -q python\tests\test_react_controller.py
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/react_controller.py python/tests/test_react_controller.py
git commit -m "feat: add bounded react controller"
```

---

## Task 2: Budget And Allowlist Coverage

**Files:**
- Modify: `python/agent_service/react_controller.py`
- Modify: `python/tests/test_react_controller.py`

- [ ] **Step 1: Add budget tests**

Append to `python/tests/test_react_controller.py`:

```python
def test_react_controller_stops_when_tool_budget_is_exceeded() -> None:
    model = SequencedModel(
        [
            '{"kind":"tool","tool_id":"internal:file.inspect","arguments":{}}',
            '{"kind":"tool","tool_id":"internal:file.inspect","arguments":{}}',
        ]
    )
    result = ReActController(model_client=model, gateway=RecordingGateway()).run(
        messages=[ChatMessage(role="user", content="Use tools.")],
        tools=[_tool()],
        base_invocation=_base_invocation(),
        policy=ReActPolicy(
            enabled=True,
            max_steps=3,
            max_tool_calls=1,
            allowed_tool_ids=["internal:file.inspect"],
        ),
    )

    assert result.ok is False
    assert result.error_code == "tool_budget_exceeded"
    assert result.tool_call_count == 1


def test_react_controller_stops_when_step_budget_is_exceeded() -> None:
    model = SequencedModel(
        [
            '{"kind":"tool","tool_id":"internal:file.inspect","arguments":{}}',
            '{"kind":"tool","tool_id":"internal:file.inspect","arguments":{}}',
        ]
    )
    result = ReActController(model_client=model, gateway=RecordingGateway()).run(
        messages=[ChatMessage(role="user", content="Use tools.")],
        tools=[_tool()],
        base_invocation=_base_invocation(),
        policy=ReActPolicy(
            enabled=True,
            max_steps=1,
            max_tool_calls=3,
            allowed_tool_ids=["internal:file.inspect"],
        ),
    )

    assert result.ok is False
    assert result.error_code == "step_budget_exceeded"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_react_controller.py::test_react_controller_stops_when_tool_budget_is_exceeded python\tests\test_react_controller.py::test_react_controller_stops_when_step_budget_is_exceeded
```

Expected:

```text
FAILED
```

- [ ] **Step 3: Implement explicit budget exits**

Inside `ReActController.run()`, return these error codes:

```python
serialized_observations = [observation.model_dump(mode="json") for observation in observations]
if step_index >= policy.max_steps:
    return ReActResult(ok=False, text="", tool_call_count=tool_call_count, observations=serialized_observations, error_code="step_budget_exceeded")
if tool_call_count >= policy.max_tool_calls:
    return ReActResult(ok=False, text="", tool_call_count=tool_call_count, observations=serialized_observations, error_code="tool_budget_exceeded")
```

- [ ] **Step 4: Run React tests**

Run:

```powershell
python -m pytest -q python\tests\test_react_controller.py
```

Expected:

```text
5 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/react_controller.py python/tests/test_react_controller.py
git commit -m "test: cover react controller budgets"
```

---

## Task 3: Model Tool Adapter Helpers

**Files:**
- Modify: `python/agent_service/model_tool_adapter.py`
- Modify: `python/tests/test_model_tool_adapter.py`

- [ ] **Step 1: Add adapter tests**

Append to `python/tests/test_model_tool_adapter.py`:

```python
from agent_service.model_tool_adapter import safe_observation_payload
from agent_service.tool_protocol import UnifiedToolResult


def test_safe_observation_payload_omits_secret_values_and_uses_artifact_names() -> None:
    result = UnifiedToolResult(
        invocation_id="inv-1",
        tool_id="internal:file.inspect",
        ok=True,
        values={"text": "ok", "api_key": "sk-secret"},
        artifacts=["D:\\Project\\artifacts\\report.md"],
    )

    payload = safe_observation_payload(result)

    assert payload["toolId"] == "internal:file.inspect"
    assert payload["ok"] is True
    assert payload["values"] == {"text": "ok"}
    assert payload["artifacts"] == ["report.md"]
```

- [ ] **Step 2: Run adapter test and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_model_tool_adapter.py::test_safe_observation_payload_omits_secret_values_and_uses_artifact_names
```

Expected:

```text
ImportError: cannot import name 'safe_observation_payload'
```

- [ ] **Step 3: Implement `safe_observation_payload()`**

Add to `python/agent_service/model_tool_adapter.py`:

```python
from pathlib import Path
from typing import Any


def safe_observation_payload(result: UnifiedToolResult) -> dict[str, Any]:
    return {
        "toolId": result.tool_id,
        "ok": result.ok,
        "values": {
            key: value
            for key, value in dict(result.values).items()
            if "secret" not in key.lower() and "key" not in key.lower()
        },
        "artifacts": [Path(path).name for path in result.artifacts],
        "errorCode": result.error_code,
    }
```

- [ ] **Step 4: Run adapter tests**

Run:

```powershell
python -m pytest -q python\tests\test_model_tool_adapter.py
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/model_tool_adapter.py python/tests/test_model_tool_adapter.py
git commit -m "feat: add safe model tool observations"
```

---

## Task 4: Execution Integration Behind Metadata Flag

**Files:**
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_execution.py`

- [ ] **Step 1: Add execution integration test**

Append to `python/tests/test_execution.py`:

```python
def test_react_enabled_model_node_records_observations(tmp_path: Path) -> None:
    graph_event = run_agent(
        UserMessage(
            task_id="react-execution",
            content="Create a Python script that counts rows in a CSV file.",
        )
    )[0]
    graph = RunGraph.model_validate(graph_event.payload["graph"])
    for node in graph.nodes:
        if node.nodeType == "model":
            graph.metadata["react"] = {
                "enabled": True,
                "allowedToolIds": ["internal:file.inspect"],
                "maxSteps": 2,
                "maxToolCalls": 1,
            }
            node.modelRef = "local-task-reasoner"
            break
    model = FakeModelClient()
    model.replies = [
        '{"kind":"tool","tool_id":"internal:file.inspect","arguments":{"path":"README.md"}}',
        '{"kind":"final","text":"Inspected README."}',
    ]
    gateway = RecordingGateway()
    request = RunGraphRequest(
        task_id="react-execution",
        run_id="react-run",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph=graph,
    )

    events = list(run_graph_events(request, model_client=model, tool_gateway=gateway))

    completed_records = [
        event.payload["record"]
        for event in events
        if event.type == "node.run_recorded"
        and event.payload["record"]["status"] == "completed"
    ]
    model_record = next(record for record in completed_records if record["values"].get("react"))
    assert model_record["values"]["text"] == "Inspected README."
    assert model_record["values"]["react"]["toolCallCount"] == 1
```

Adjust the fake model helper names to match existing `test_execution.py` helpers. If the file already has a different fake model shape, use that local style rather than adding a duplicate class.

- [ ] **Step 2: Run integration test and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_execution.py::test_react_enabled_model_node_records_observations
```

Expected:

```text
FAILED
```

The current execution path records a one-shot model result and no `values.react`.

- [ ] **Step 3: Add metadata flag parsing**

In `execution.py`, add a helper:

```python
def _react_policy_from_graph_metadata(metadata: dict) -> ReActPolicy:
    react = dict(metadata.get("react") or {})
    return ReActPolicy(
        enabled=bool(react.get("enabled", False)),
        max_steps=int(react.get("maxSteps", 4)),
        max_tool_calls=int(react.get("maxToolCalls", 3)),
        allowed_tool_ids=list(react.get("allowedToolIds") or []),
        allowed_permissions=list(react.get("allowedPermissions") or []),
    )
```

In `PlannedTaskExecutor.run()` model branch:

- Build `react_policy = _react_policy_from_graph_metadata(self.request.graph.metadata)`.
- If disabled, keep current one-shot behavior.
- If enabled, call `ReActController`.
- Build `base_invocation` with run/task/node/project/allowed roots/permissions.
- Return:

```python
NodeOutput(
    values={
        "mode": "planned_task",
        "nodeType": node.nodeType,
        "summary": node.summary,
        "modelRef": model_binding.model_ref,
        "text": result.text,
        "react": {
            "ok": result.ok,
            "toolCallCount": result.tool_call_count,
            "observations": result.observations,
            "errorCode": result.error_code,
        },
    }
)
```

If `result.ok` is false, raise `HarnessError(result.error_code or "react_failed", "react controller failed")`.

- [ ] **Step 4: Run integration regression**

Run:

```powershell
python -m pytest -q python\tests\test_react_controller.py python\tests\test_execution.py::test_react_enabled_model_node_records_observations
```

Expected:

```text
... passed
```

- [ ] **Step 5: Run broader execution tests**

Run:

```powershell
python -m pytest -q python\tests\test_react_controller.py python\tests\test_model_tool_adapter.py python\tests\test_execution.py
```

Expected:

```text
... passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add python/agent_service/execution.py python/tests/test_execution.py
git commit -m "feat: run bounded react for enabled model nodes"
```

---

## Task 5: Final Regression And Review

**Files:**
- Read: `python/agent_service/react_controller.py`
- Read: `python/agent_service/model_tool_adapter.py`
- Read: `python/agent_service/execution.py`
- Read: `python/tests/test_react_controller.py`
- Read: `python/tests/test_execution.py`

- [ ] **Step 1: Run Phase G focused tests**

Run:

```powershell
python -m pytest -q python\tests\test_react_controller.py python\tests\test_model_tool_adapter.py python\tests\test_execution.py
```

Expected:

```text
... passed
```

- [ ] **Step 2: Run gateway and planner regressions**

Run:

```powershell
python -m pytest -q python\tests\test_execution_gateway_integration.py python\tests\test_planner_chain.py python\tests\test_graph.py
```

Expected:

```text
... passed
```

- [ ] **Step 3: Confirm no Phase H sandbox scope leaked in**

Run:

```powershell
rg -n "SandboxRequest|sandbox.py|subprocess|network_allowed|temporary script run" python\agent_service\react_controller.py python\agent_service\execution.py
```

Expected:

```text
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

- [ ] **Step 5: Final code review**

Dispatch a final code review over the Phase G commit range:

```text
Review Phase G Bounded ReAct implementation. Prioritize bounded loop enforcement, malformed action handling, tool allowlist enforcement, gateway-only tool execution, observation privacy, one-shot model node compatibility, event payload compatibility, and whether implementation avoids temporary script sandbox, memory, durable execution, or broad MCP planning scope.
```

Expected: reviewer returns no critical or important findings. Fix any critical or important finding before finishing Phase G.

---

## Acceptance Criteria

Phase G is complete when all statements are true:

- `python/agent_service/react_controller.py` exists and is covered by `python/tests/test_react_controller.py`.
- ReAct loops are disabled by default.
- Enabled ReAct loops enforce step, tool-call, runtime, and allowlist budgets.
- Malformed model actions fail deterministically.
- Every tool action uses `UnifiedToolGateway`.
- Safe observations omit secrets and raw local paths.
- Ordinary one-shot model nodes still work.
- Public endpoint and frontend event shapes remain unchanged.
- No temporary script execution, memory, durable checkpointing, or sandbox behavior is introduced.
- `.\scripts\verify-mvp.ps1` passes.

## Handoff Notes For Phase H

Phase H can add a sandbox runner for low-risk temporary script nodes. It must not bypass Phase C gateway permissions or Phase G tool-call budgets. ReAct must not be allowed to invoke temporary script execution unless Phase H explicitly exposes a reviewed sandbox tool through the gateway.
