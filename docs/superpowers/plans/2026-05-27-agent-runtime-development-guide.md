# Agent Runtime Development Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a concrete engineering guide for implementing the Agent runtime optimization roadmap in small, testable, reviewable phases.

**Architecture:** Keep Alita's user-visible node graph as the control plane while strengthening the Python sidecar into a single-agent runtime. The runtime grows through explicit contracts: `AgentRunState`, structured routing, planner chain, execution graph, Unified Tool Gateway, bounded ReAct, sandboxed temporary scripts, memory, and evals.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, LangGraph, pytest, React 19, Vitest, Tauri 2, Rust, MCP, llama.cpp/OpenAI-compatible model APIs.

---

## 1. How To Use This Document

This document is the development manual for the optimization roadmap in:

`docs/superpowers/plans/2026-05-27-agent-runtime-optimization-plan.md`

Use it as the parent plan. Each phase should be implemented as a separate branch or worktree and should end with tests and a small commit. Do not implement multiple high-risk phases in one unreviewed batch.

Recommended implementation order:

1. Phase A: release/security hygiene.
2. Phase B: `AgentRunState`.
3. Phase C: Unified Tool Gateway execution path.
4. Phase D: structured router.
5. Phase E: planner chain.
6. Phase F: execution graph.
7. Phase G: bounded ReAct.
8. Phase H: temporary script sandbox.
9. Phase I: evidence-driven research.
10. Phase J: eval harness.
11. Phase K: memory/context.
12. Phase L: frontend state decomposition.

Phase B to Phase F are kernel foundation. Phase G and Phase H should not start until Phase C is passing, because model tool calls and temporary scripts must not bypass the gateway and permission checks.

## 2. Non-Negotiable Engineering Rules

Preserve these existing product behaviors unless a phase explicitly changes them:

- Public sidecar endpoints in `python/agent_service/app.py`.
- Frontend event names in `src/shared/events.ts`.
- Current `RunGraph` shape in `src/shared/types.ts` and `python/agent_service/schemas.py`.
- Document workflow node IDs: `document-input`, `document-parse`, `content-organize`, `report-generate`, `typst-export`, `file-export`.
- Research workflow node IDs unless Phase I updates them with compatibility mapping.
- Project file schema compatibility in `src-tauri/src/project.rs`.
- Tauri-managed sidecar lifecycle in `src-tauri/src/sidecar.rs`.

Enforce these runtime rules:

- No internal tool, MCP tool, model-requested tool, web call, script, or external provider call may bypass `UnifiedToolGateway`.
- A model may propose an action, but the kernel owns permission, execution, observation, verification, and journal writes.
- ReAct is per-node and bounded. It is not a global infinite loop.
- Temporary scripts run only after review, policy checks, path checks, timeouts, and artifact constraints.
- Every new behavior gets deterministic tests with fake model/tool/search providers.

## 3. Baseline Commands

Run these before starting each phase:

```powershell
git status --short --branch
python -m pytest -q python/tests/test_agent_routing_integration.py python/tests/test_execution.py python/tests/test_tool_gateway.py python/tests/test_model_tool_adapter.py python/tests/test_planner_v2.py
npm run frontend:typecheck
npm run frontend:test -- --run src/app/backendEvents.test.ts src/features/task/useTaskEvents.test.ts
cargo test --manifest-path src-tauri/Cargo.toml
```

Expected:

- `git status` shows only known local work.
- Python selected tests pass.
- Frontend typecheck and focused event tests pass.
- Rust tests pass.

If a baseline fails before changes, record the failure and fix or isolate it before implementing the phase.

## 4. Contract Map

### Public API Contracts

These are stable inputs and outputs:

- `AgentMessageRequest` in `python/agent_service/schemas.py`.
- `RunGraphRequest` in `python/agent_service/schemas.py`.
- `AgentEvent` in `python/agent_service/schemas.py`.
- `BackendEvent` in `src/shared/events.ts`.
- `NodeGraph` and `AgentNode` in `src/shared/types.ts`.

Do not change these in early kernel phases. Add internal objects that compile to or from these public shapes.

### Internal Kernel Contracts

The new runtime should converge on these internal contracts:

```text
AgentRunState
  -> RouterV2Decision
  -> GoalSpec
  -> ContextBundle
  -> PlanningRequest
  -> PlanningResult
  -> RunGraph
  -> ExecutionGraph
  -> NodeOutput
  -> ReflectionRecord
```

The frontend sees `RunGraph`, events, artifacts, and run history. It does not need to know about `ExecutionGraph`, ReAct internals, provider adapters, or sandbox internals.

## 5. Phase A: Release And Security Hygiene

**Purpose:** remove known correctness and default-security problems before adding more autonomy.

**Files:**

- Modify: `python/pyproject.toml`
- Modify: `python/agent_service/intent.py`
- Modify: `python/agent_service/app.py`
- Modify: `src-tauri/tauri.conf.json`
- Test: `python/tests/test_intent.py`
- Test: `python/tests/test_app.py`

**Development Steps:**

- [ ] Step A1: Add a failing test proving the sidecar rejects authenticated endpoints without token unless explicit dev bypass is enabled.

Add tests to `python/tests/test_app.py`:

```python
from fastapi.testclient import TestClient

from agent_service.app import app


def test_agent_message_requires_token_when_auth_is_configured(monkeypatch):
    monkeypatch.setenv("ALITA_SIDECAR_TOKEN", "expected-token")
    response = TestClient(app).post(
        "/agent/message",
        json={"task_id": "task-1", "content": "hello", "attachments": []},
    )
    assert response.status_code == 401


def test_agent_message_accepts_matching_sidecar_token(monkeypatch):
    monkeypatch.setenv("ALITA_SIDECAR_TOKEN", "expected-token")
    response = TestClient(app).post(
        "/agent/message",
        headers={"X-Alita-Sidecar-Token": "expected-token"},
        json={"task_id": "task-1", "content": "", "attachments": []},
    )
    assert response.status_code == 200
```

Run:

```powershell
python -m pytest -q python/tests/test_app.py
```

Expected before implementation: the second test passes; the first test may already pass only when token is set. Add the explicit dev-bypass behavior in the next step and keep both tests green.

- [ ] Step A2: Add explicit unauthenticated dev bypass.

Implementation rule in `python/agent_service/app.py`:

```python
SIDECAR_DEV_BYPASS_ENV = "ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV"


def _unauthenticated_dev_bypass_enabled() -> bool:
    return os.getenv(SIDECAR_DEV_BYPASS_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
```

`require_sidecar_token()` should allow missing `ALITA_SIDECAR_TOKEN` only when `_unauthenticated_dev_bypass_enabled()` is true.

- [ ] Step A3: Remove mojibake document keywords from `python/agent_service/intent.py`.

Keep valid Chinese entries such as `处理`, `整理`, `总结`, `摘要`, `提取`, `分析`, `改写`, `翻译`, `文档`, `文件`, `附件`, `资料`, `报告`, `图片`, `音频`, `视频`, `表格`.

Add regression tests to `python/tests/test_intent.py`:

```python
from agent_service.intent import IntentKind, classify_route
from agent_service.schemas import UserMessage


def test_chinese_document_request_without_attachment_needs_document_file():
    decision = classify_route(
        UserMessage(task_id="task-1", content="请总结这个文档", attachments=[])
    )
    assert decision.intent.kind == IntentKind.NEED_INPUT
    assert decision.missing_inputs == ["document_file"]


def test_plain_chinese_chat_is_not_document_task():
    decision = classify_route(
        UserMessage(task_id="task-1", content="我们聊一下今天的计划", attachments=[])
    )
    assert decision.intent.kind in {IntentKind.CHAT, IntentKind.INQUIRY}
```

- [ ] Step A4: Align sidecar version.

Change `python/pyproject.toml`:

```toml
version = "0.28.0"
```

- [ ] Step A5: Set a production CSP in `src-tauri/tauri.conf.json`.

Start with a restrictive local app policy:

```json
"csp": "default-src 'self'; img-src 'self' asset: http://asset.localhost data: blob:; media-src 'self' asset: http://asset.localhost data: blob:; connect-src 'self' http://127.0.0.1:8765 http://localhost:8765; style-src 'self' 'unsafe-inline'"
```

Verify Tauri asset URLs still work with artifact previews.

**Phase A Verification:**

```powershell
python -m pytest -q python/tests/test_app.py python/tests/test_intent.py
npm run frontend:test -- --run src/features/artifacts/artifactApi.test.ts src/features/task/useTaskEvents.test.ts
cargo test --manifest-path src-tauri/Cargo.toml
```

**Acceptance:**

- Sidecar auth has no silent unauthenticated production mode.
- Dev bypass is explicit.
- Chinese document routing is clean.
- Versions are aligned.
- CSP is no longer null.

## 6. Phase B: AgentRunState

**Purpose:** introduce one internal state object shared by routing, planning, execution, and event emission.

**Files:**

- Create: `python/agent_service/agent_run_state.py`
- Modify: `python/agent_service/app.py`
- Modify: `python/agent_service/graph.py`
- Test: `python/tests/test_agent_run_state.py`
- Test: `python/tests/test_agent_routing_integration.py`

**Target Contract:**

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_service.goal_spec import GoalSpec
from agent_service.schemas import AgentEvent, AgentMessageRequest, RunGraph, RunGraphRequest, UserMessage


class AgentRunState(BaseModel):
    task_id: str
    message: UserMessage
    run_id: str | None = None
    goal_spec: GoalSpec | None = None
    current_graph: RunGraph | None = None
    has_run_history: bool = False
    artifact_refs: list[str] = Field(default_factory=list)
    pending_choice: dict[str, Any] | None = None
    model_session_id: str | None = None
    disabled_tool_ids: list[str] = Field(default_factory=list)
    approved_permissions: list[str] = Field(default_factory=list)
    events: list[AgentEvent] = Field(default_factory=list)

    @classmethod
    def from_message_request(cls, request: AgentMessageRequest) -> "AgentRunState":
        user_message = request.to_user_message()
        return cls(
            task_id=request.task_id,
            message=user_message,
            current_graph=request.currentGraph,
            has_run_history=bool(request.hasRunHistory),
            artifact_refs=list(request.artifactRefs or []),
            pending_choice=request.pendingChoice,
            model_session_id=request.model_session_id,
        )

    @classmethod
    def from_run_graph_request(cls, request: RunGraphRequest) -> "AgentRunState":
        return cls(
            task_id=request.task_id,
            run_id=request.run_id,
            message=UserMessage(
                task_id=request.task_id,
                content=str(request.graph.metadata.get("question", "")),
                attachments=list(request.attachments),
                model_session_id=request.model_session_id,
            ),
            current_graph=request.graph,
            model_session_id=request.model_session_id,
            disabled_tool_ids=list(request.disabled_tool_ids),
            approved_permissions=list(request.approved_permissions),
        )
```

**Development Steps:**

- [ ] Step B1: Write tests for `from_message_request()` and `from_run_graph_request()`.
- [ ] Step B2: Create `agent_run_state.py` with the contract above.
- [ ] Step B3: In `app.py`, convert request objects to `AgentRunState` before calling orchestration helpers.
- [ ] Step B4: In `graph.py`, keep public `run_agent()` signature but immediately build or accept `AgentRunState` internally.
- [ ] Step B5: Verify no event payload changes.

**Phase B Verification:**

```powershell
python -m pytest -q python/tests/test_agent_run_state.py python/tests/test_agent_routing_integration.py python/tests/test_graph.py
```

**Acceptance:**

- Existing endpoints remain compatible.
- Graph feedback, research choice, chat, local inquiry, and task graph tests pass.
- New internal state reduces parameter passing but does not change behavior.

## 7. Phase C: Unified Tool Gateway Execution Path

**Purpose:** make `UnifiedToolGateway` the single runtime path for internal fixed tools and future MCP tools.

**Files:**

- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/agent_service/tool_providers/internal.py`
- Modify: `python/agent_service/execution.py`
- Create: `python/tests/test_execution_gateway_integration.py`
- Modify: `python/tests/test_tool_gateway.py`
- Modify: `python/tests/test_execution.py`

**Gateway Factory:**

Create a helper in `tool_gateway.py` or a small adjacent module:

```python
from pathlib import Path

from agent_service.tool_execution import default_tool_packages_root
from agent_service.tool_providers.internal import InternalToolProvider
from agent_service.tool_registry import ToolRegistry


def default_unified_tool_gateway(packages_root: Path | None = None) -> UnifiedToolGateway:
    registry = ToolRegistry.from_packages_root(packages_root or default_tool_packages_root())
    return UnifiedToolGateway(providers=[InternalToolProvider(registry=registry)])
```

**Development Steps:**

- [ ] Step C1: Add a test proving `DocumentFlowExecutor` calls `UnifiedToolGateway.call_tool()` for `document.markitdown_convert`.
- [ ] Step C2: Add a test proving `typst-export` calls `UnifiedToolGateway.call_tool()` for `document.typst_compile`.
- [ ] Step C3: Add a test proving `PlannedTaskExecutor` executes an internal fixed tool through the gateway instead of raising `unsupported_runtime`.
- [ ] Step C4: Add `default_unified_tool_gateway()`.
- [ ] Step C5: Change `DocumentFlowExecutor.__init__()` to accept `tool_gateway: UnifiedToolGateway | None`.
- [ ] Step C6: Translate old `ToolInvocation` arguments into `UnifiedToolInvocation` with `operation` included in `arguments`.
- [ ] Step C7: Convert `UnifiedToolResult` to `NodeOutput`.
- [ ] Step C8: Preserve current artifact paths and values from MarkItDown and Typst.
- [ ] Step C9: Add gateway error conversion to `HarnessError`.

**Result Conversion Rule:**

```python
def _node_output_from_unified_result(result: UnifiedToolResult) -> NodeOutput:
    if not result.ok:
        error = result.error
        raise HarnessError(
            error.code if error else "tool_failed",
            error.message if error else "tool failed",
        )
    values = dict(result.structured_content or {})
    return NodeOutput(values=values, artifacts=list(result.artifacts))
```

**Phase C Verification:**

```powershell
python -m pytest -q python/tests/test_tool_gateway.py python/tests/test_execution_gateway_integration.py python/tests/test_execution.py
```

**Acceptance:**

- Document tools execute through gateway.
- Generic internal fixed tools selected by the planner no longer fail with `unsupported_runtime` when a provider exists.
- Gateway errors remain safe and structured.

## 8. Phase D: Structured Router V2

**Purpose:** reduce brittle keyword routing while keeping deterministic fast paths.

**Files:**

- Create: `python/agent_service/router_v2.py`
- Modify: `python/agent_service/graph.py`
- Modify: `python/agent_service/intent.py`
- Test: `python/tests/test_router_v2.py`
- Test: `python/tests/test_agent_routing_integration.py`

**Target Contract:**

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


AgentRouteIntent = Literal[
    "chat",
    "local_inquiry",
    "web_simple_inquiry",
    "web_complex_choice",
    "web_complex_research_flow",
    "task",
    "missing_input",
]


class RouterV2Decision(BaseModel):
    intent: AgentRouteIntent
    confidence: float = Field(ge=0.0, le=1.0)
    task_type: str
    missing_inputs: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    tool_candidates: list[str] = Field(default_factory=list)
    reason: str
    source: Literal["deterministic", "model", "fallback"] = "deterministic"
```

**Development Steps:**

- [ ] Step D1: Implement `deterministic_route(message, current_graph, pending_choice, inquiry_choice)`.
- [ ] Step D2: Keep weather, empty input, document attachment, explicit graph feedback, and explicit research choice deterministic.
- [ ] Step D3: Add `model_route()` using model JSON output behind a feature flag such as `ALITA_STRUCTURED_ROUTER=1`.
- [ ] Step D4: Add confidence thresholds: `>=0.75` proceed, `0.45-0.74` ask clarification, `<0.45` fallback.
- [ ] Step D5: Include `routeDecision` metadata on graph payloads and optionally on debug events.
- [ ] Step D6: Add tests with fake model router output.

**Test Cases:**

- Empty message without attachment returns `missing_input`.
- Empty message with attachment returns `task`.
- Weather question routes to `web_simple_inquiry` with `weather.current` or `weather.forecast` candidate.
- "Can you explain how to convert markdown?" remains inquiry, not task.
- Mixed Chinese/English task with attachment routes to document task.
- Existing graph feedback routes to graph feedback handler, not a new task.

**Phase D Verification:**

```powershell
python -m pytest -q python/tests/test_router_v2.py python/tests/test_agent_routing_integration.py python/tests/test_intent.py
```

**Acceptance:**

- Existing route tests remain stable.
- Ambiguous prompts have inspectable structured decisions.
- Model router can be disabled without breaking the deterministic product path.

## 9. Phase E: Planner Chain

**Purpose:** replace isolated template planning with a common planner protocol.

**Files:**

- Create: `python/agent_service/planner_protocol.py`
- Create: `python/agent_service/planners/__init__.py`
- Create: `python/agent_service/planners/document_template.py`
- Create: `python/agent_service/planners/research_template.py`
- Create: `python/agent_service/planners/tool_capability.py`
- Modify: `python/agent_service/planner_v2.py`
- Modify: `python/agent_service/graph.py`
- Modify: `python/agent_service/plan_validator.py`
- Test: `python/tests/test_planner_chain.py`
- Test: `python/tests/test_plan_validator.py`

**Target Contract:**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_service.context_manager import ContextBundle
from agent_service.goal_spec import GoalSpec
from agent_service.schemas import UserMessage


@dataclass(frozen=True)
class PlanningRequest:
    task_id: str
    message: UserMessage
    goal_spec: GoalSpec
    context: ContextBundle
    route_reason: str = ""


@dataclass(frozen=True)
class PlanningResult:
    planner_name: str
    graph_payload: dict
    warnings: list[str]


class Planner(Protocol):
    name: str

    def can_plan(self, request: PlanningRequest) -> bool:
        raise NotImplementedError

    def plan(self, request: PlanningRequest) -> PlanningResult:
        raise NotImplementedError
```

**Development Steps:**

- [ ] Step E1: Wrap current `PlannerV2` behavior in `DocumentTemplatePlanner`.
- [ ] Step E2: Wrap current `build_research_graph()` in `ResearchTemplatePlanner`.
- [ ] Step E3: Add `ToolCapabilityPlanner` that builds graph nodes from `UnifiedToolDefinition.node_template`.
- [ ] Step E4: Add `PlannerChain` with ordered planners: document, research, tool capability, heuristic fallback.
- [ ] Step E5: Ensure `PlannerChain.plan()` returns one graph payload and planner metadata.
- [ ] Step E6: Preserve current document graph and research graph shape in regression tests.
- [ ] Step E7: Add plan validator checks for output node, acyclic graph, tool bindings, and permission declarations.

**Phase E Verification:**

```powershell
python -m pytest -q python/tests/test_planner_chain.py python/tests/test_planner_v2.py python/tests/test_graph_compiler.py python/tests/test_agent_routing_integration.py
```

**Acceptance:**

- Current document and research graph payloads remain frontend-compatible.
- Planner selection is explicit and testable.
- Tool-catalog planning has a first implementation path without replacing templates.

## 10. Phase F: ExecutionGraph

**Purpose:** create an internal execution model with normalized bindings and policies.

**Files:**

- Create: `python/agent_service/execution_graph.py`
- Modify: `python/agent_service/execution.py`
- Test: `python/tests/test_execution_graph.py`
- Test: `python/tests/test_execution.py`

**Target Contract:**

```python
from __future__ import annotations

from pydantic import BaseModel, Field


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
    metadata: dict = Field(default_factory=dict)
```

**Development Steps:**

- [ ] Step F1: Write compiler tests from `RunGraph` to `ExecutionGraph`.
- [ ] Step F2: Map `fixed_tool.toolRef` to `ExecutionToolBinding`.
- [ ] Step F3: Map `model.modelRef` to `ExecutionModelBinding`.
- [ ] Step F4: Preserve output nodes and dependencies.
- [ ] Step F5: Use `ExecutionGraph` inside `run_graph_events()` for binding lookup while continuing to emit public node IDs.
- [ ] Step F6: Add unsupported binding errors before node execution starts.

**Phase F Verification:**

```powershell
python -m pytest -q python/tests/test_execution_graph.py python/tests/test_execution.py
```

**Acceptance:**

- Runtime has a normalized execution model.
- Public graph shape remains unchanged.
- Unsupported runtime errors become precise binding validation errors.

## 11. Phase G: Bounded ReAct Controller

**Purpose:** allow selected model nodes to request tools in a controlled observe-act loop.

**Files:**

- Create: `python/agent_service/react_controller.py`
- Modify: `python/agent_service/model_client.py`
- Modify: `python/agent_service/model_tool_adapter.py`
- Modify: `python/agent_service/execution.py`
- Test: `python/tests/test_react_controller.py`
- Test: `python/tests/test_model_tool_adapter.py`

**Target Contract:**

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class ReActPolicy(BaseModel):
    enabled: bool = False
    max_steps: int = 4
    max_tool_calls: int = 3
    max_runtime_ms: int = 30000
    allowed_tool_ids: list[str] = Field(default_factory=list)
    allowed_permissions: list[str] = Field(default_factory=list)
    stop_on_first_success: bool = True


class ReActResult(BaseModel):
    ok: bool
    text: str
    tool_call_count: int
    observations: list[dict] = Field(default_factory=list)
    error_code: str | None = None
```

**Development Steps:**

- [ ] Step G1: Add fake model client tests for one tool call followed by final answer.
- [ ] Step G2: Add tests for max tool calls exceeded.
- [ ] Step G3: Add tests for disallowed tool ID.
- [ ] Step G4: Add tests for malformed local-model JSON action.
- [ ] Step G5: Add `ReActController.run()` with explicit budget counters.
- [ ] Step G6: Convert tool catalog to model tool schema with `model_tool_adapter.py`.
- [ ] Step G7: Execute requested tools through `UnifiedToolGateway`.
- [ ] Step G8: Append safe observations to model context.
- [ ] Step G9: Return `NodeOutput` with text and observation metadata.

**Phase G Verification:**

```powershell
python -m pytest -q python/tests/test_react_controller.py python/tests/test_model_tool_adapter.py python/tests/test_execution.py
```

**Acceptance:**

- ReAct loops are bounded and testable.
- Every tool call uses the gateway.
- Observations are recorded without exposing secrets.

## 12. Phase H: Temporary Script Sandbox

**Purpose:** make low-risk temporary script nodes executable under strict local controls.

**Files:**

- Create: `python/agent_service/sandbox.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/task_planner.py`
- Modify: `python/agent_service/permission_gate.py`
- Test: `python/tests/test_sandbox.py`
- Test: `python/tests/test_execution.py`

**Target Contract:**

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SandboxRequest(BaseModel):
    script: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    project_path: str
    allowed_roots: list[str]
    network_allowed: bool = False
    timeout_seconds: float = 10.0
    artifact_dir: str


class SandboxResult(BaseModel):
    ok: bool
    stdout: str = ""
    stderr: str = ""
    values: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    error_code: str | None = None
```

**Development Steps:**

- [ ] Step H1: Add tests for allowed CSV read inside project root.
- [ ] Step H2: Add tests for path escape attempt using `..`.
- [ ] Step H3: Add tests for timeout.
- [ ] Step H4: Add tests for denied network imports such as `socket`, `requests`, and `urllib`.
- [ ] Step H5: Add tests for high-risk approval requirement.
- [ ] Step H6: Implement script preflight checks.
- [ ] Step H7: Implement subprocess runner with `cwd` under artifact temp dir.
- [ ] Step H8: Pass script input as JSON through stdin.
- [ ] Step H9: Require script output JSON on stdout with `values` and `artifacts`.
- [ ] Step H10: Validate returned artifact paths are inside the artifact directory.

**Phase H Verification:**

```powershell
python -m pytest -q python/tests/test_sandbox.py python/tests/test_execution.py python/tests/test_agent_routing_integration.py
```

**Acceptance:**

- Low-risk temporary scripts run in supported bounded cases.
- High-risk scripts remain blocked until approved.
- Path and artifact constraints are enforced by tests.

## 13. Phase I: Evidence-Driven Research

**Purpose:** upgrade research from snippet stitching to source-grounded synthesis.

**Files:**

- Create: `python/agent_service/research_evidence.py`
- Modify: `python/agent_service/web_research.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/web_search.py`
- Test: `python/tests/test_research_evidence.py`
- Test: `python/tests/test_web_research.py`

**Target Evidence Shape:**

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class EvidenceSource(BaseModel):
    source_id: str
    title: str
    url: str
    source_type: str
    accepted: bool
    score: float
    snippet: str = ""
    content_excerpt: str = ""
    content_hash: str | None = None
    observed_date: str | None = None
    rejection_reason: str | None = None


class ResearchEvidenceSet(BaseModel):
    question: str
    accepted_sources: list[EvidenceSource] = Field(default_factory=list)
    rejected_sources: list[EvidenceSource] = Field(default_factory=list)
    duplicate_sources: list[EvidenceSource] = Field(default_factory=list)
    failed_reads: list[dict[str, str]] = Field(default_factory=list)
```

**Development Steps:**

- [ ] Step I1: Add tests for URL/content deduplication.
- [ ] Step I2: Add tests for accepted/rejected scoring.
- [ ] Step I3: Add tests for citation coverage in Markdown.
- [ ] Step I4: Add bounded concurrent search with deterministic fake provider tests.
- [ ] Step I5: Store source content hash and excerpt spans.
- [ ] Step I6: Update report synthesis prompt to require source IDs in claims.
- [ ] Step I7: Add deterministic fallback quality checks for no citations and no accepted sources.
- [ ] Step I8: Preserve `research.completed` event payload compatibility.

**Phase I Verification:**

```powershell
python -m pytest -q python/tests/test_research_evidence.py python/tests/test_web_research.py python/tests/test_agent_routing_integration.py
```

**Acceptance:**

- Research reports cite accepted sources.
- Duplicate and failed-read sources are visible.
- Quality check catches missing citations.

## 14. Phase J: Agent Eval Harness

**Purpose:** create task-level regression signals for the Agent runtime.

**Files:**

- Create: `python/agent_service/eval_harness.py`
- Create: `python/evals/router_cases.jsonl`
- Create: `python/evals/planner_cases.jsonl`
- Create: `python/evals/tool_cases.jsonl`
- Create: `python/evals/research_cases.jsonl`
- Test: `python/tests/test_eval_harness.py`
- Modify: `scripts/verify-mvp.ps1`

**Eval Case Shape:**

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    case_id: str
    category: Literal["router", "planner", "tool", "research", "recovery"]
    input: dict[str, Any]
    expected: dict[str, Any]
    tags: list[str] = Field(default_factory=list)
```

**Development Steps:**

- [ ] Step J1: Add JSONL loader tests.
- [ ] Step J2: Add router eval runner with deterministic classifier.
- [ ] Step J3: Add planner eval runner checking graph validity and expected node IDs.
- [ ] Step J4: Add tool eval runner with fake gateway.
- [ ] Step J5: Add research eval runner with fake search/source providers.
- [ ] Step J6: Emit JSON and Markdown summary files under `.codex-run/evals`.
- [ ] Step J7: Add `scripts/verify-mvp.ps1` smoke invocation.

**Phase J Verification:**

```powershell
python -m pytest -q python/tests/test_eval_harness.py
powershell -ExecutionPolicy Bypass -File scripts/verify-mvp.ps1
```

**Acceptance:**

- Eval harness runs without network.
- Router/planner/tool/research regressions can fail deterministically.
- Summary output is readable by humans and automation.

## 15. Phase K: Memory And Context Management

**Purpose:** add project-scoped memory without leaking sensitive local data.

**Files:**

- Create: `python/agent_service/memory_store.py`
- Create: `python/agent_service/context_policy.py`
- Modify: `python/agent_service/context_manager.py`
- Modify: `src-tauri/src/project.rs`
- Modify: `src/shared/types.ts`
- Test: `python/tests/test_memory_store.py`
- Test: `python/tests/test_context_manager.py`
- Test: `src-tauri/tests/project_tests.rs`

**Memory Record Shape:**

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    memory_id: str
    scope: Literal["project", "global"] = "project"
    kind: Literal["preference", "graph_summary", "artifact_summary", "tool_outcome"]
    summary: str
    source_ref: str
    created_at: str
    tags: list[str] = Field(default_factory=list)
```

**Development Steps:**

- [ ] Step K1: Add memory persistence tests under a temp project directory.
- [ ] Step K2: Add redaction tests for secrets, raw local paths, and large content.
- [ ] Step K3: Add context budget selection tests for chat, planning, node execution, and research.
- [ ] Step K4: Implement JSONL memory store under project sibling directory such as `alita-memory`.
- [ ] Step K5: Add summarization hooks for completed runs and artifacts.
- [ ] Step K6: Add project schema field only if needed; prefer sidecar-owned project sibling storage for first pass.

**Phase K Verification:**

```powershell
python -m pytest -q python/tests/test_memory_store.py python/tests/test_context_manager.py
cargo test --manifest-path src-tauri/Cargo.toml project
```

**Acceptance:**

- Follow-up tasks can use compact prior summaries.
- Sensitive data is excluded from model context by default.
- Memory is scoped and inspectable.

## 16. Phase L: Frontend State Decomposition

**Purpose:** keep frontend maintainable as Agent runtime events grow.

**Files:**

- Create: `src/features/task/useGraphRunController.ts`
- Create: `src/features/artifacts/useArtifactPreviewController.ts`
- Create: `src/features/preferences/usePreferencesController.ts`
- Create: `src/features/voice/useVoiceInputController.ts`
- Modify: `src/app/App.tsx`
- Test: `src/app/App.test.tsx`
- Test: `src/app/backendEvents.test.ts`
- Test: feature hook tests beside each new hook.

**Development Steps:**

- [ ] Step L1: Extract graph run state from `App.tsx` into `useGraphRunController`.
- [ ] Step L2: Extract artifact preview state into `useArtifactPreviewController`.
- [ ] Step L3: Extract preferences loading/saving helpers into `usePreferencesController`.
- [ ] Step L4: Extract voice recording/transcription lifecycle into `useVoiceInputController`.
- [ ] Step L5: Keep `reduceBackendEvents()` as the canonical event reducer.
- [ ] Step L6: Add hook tests using fake sidecar functions and fake artifact APIs.
- [ ] Step L7: Run full frontend tests.

**Phase L Verification:**

```powershell
npm run frontend:typecheck
npm run frontend:test
```

**Acceptance:**

- `App.tsx` becomes a composition shell.
- Existing UI and event reducer behavior remains stable.
- New runtime events can be added without expanding one component indefinitely.

## 17. Phase Gate Checklist

Every phase must pass this gate before the next phase starts:

- [ ] Public API compatibility checked.
- [ ] New behavior has focused tests.
- [ ] Existing regression tests for touched layer pass.
- [ ] `git diff` only includes phase-related files.
- [ ] User-facing event payloads are documented if changed.
- [ ] Security-sensitive behavior has negative tests.
- [ ] Failure path emits a safe error and does not leak local paths, API keys, or raw provider exceptions.
- [ ] Run journal or event reducer behavior remains inspectable.

## 18. Suggested Commit Sequence

Use small commits with clear scope:

```text
chore: align sidecar version and security defaults
refactor: add agent run state contract
feat: route document tools through unified gateway
feat: add structured agent router
feat: introduce planner chain
feat: compile public graphs to execution graph
feat: add bounded react controller
feat: execute reviewed temporary scripts in sandbox
feat: add evidence model for research reports
test: add agent eval harness
feat: add project-scoped memory store
refactor: split app runtime controllers
```

Do not combine sandbox, ReAct, and gateway migration in one commit. They each change the safety boundary.

## 19. Final Delivery Definition

The Agent runtime optimization line is complete when:

- The visible node graph remains the control plane.
- All tool calls go through `UnifiedToolGateway`.
- Router decisions are structured and testable.
- Planner chain supports template and tool-catalog graph generation.
- Execution uses an internal normalized `ExecutionGraph`.
- ReAct is bounded, per-node, journaled, and permission-gated.
- Temporary scripts can run only inside the sandbox contract.
- Research reports are evidence-grounded and citation-checked.
- Memory is project-scoped and redacted.
- Eval harness catches regressions before users do.
- Frontend state remains maintainable after runtime event growth.

