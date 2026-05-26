# Agent Kernel Mainline Phase 0-1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the Workflow-first Agent Kernel foundation by documenting current runtime contracts and introducing internal kernel state, planner chain, and execution graph contracts without changing user-visible behavior.

**Architecture:** Phase 0 records the current Agent contracts as an audit artifact. Phase 1 adds internal Python contracts around the existing sidecar flow: `AgentRunState`, `PlannerChain`, and `ExecutionGraph`. Existing `RunGraph`, public events, node IDs, document flow, research flow, and frontend behavior remain compatible.

**Tech Stack:** Python 3.10+, Pydantic, FastAPI sidecar, existing LangGraph router, existing `GoalSpec` / `ContextBundle` / `TaskGraph` / `PlannerV2`, Pytest, React/Vitest event reducer tests for compatibility checks.

---

## Scope

This plan implements only Phase 0 and Phase 1 from:

`docs/superpowers/specs/2026-05-26-workflow-first-agent-kernel-mainline-design.md`

In scope:

- Add an architecture inventory audit for current Agent events, graph node types, tool paths, model call paths, and run journal paths.
- Add `python/agent_service/kernel_state.py`.
- Add `python/agent_service/planning.py`.
- Add `python/agent_service/execution_graph.py`.
- Wire `run_agent()` and `stream_agent_events()` to build `AgentRunState`.
- Wire document and research graph creation through the planner chain while preserving graph payloads.
- Add focused tests and run existing regressions.

Out of scope:

- Controlled ReAct loop.
- Reflexion automation.
- Automatic graph patch application.
- Unified Tool Gateway migration for every tool path.
- Multi-Agent runtime.
- Frontend UI redesign.
- Rust schema changes.

## File Structure

### Create

- `docs/superpowers/audits/2026-05-26-agent-kernel-mainline-phase-0-inventory.md`
  - Static audit of current Agent contracts before code refactor.
- `python/agent_service/kernel_state.py`
  - Internal `AgentRunState`, `AgentRunBudget`, and builder helpers.
- `python/agent_service/planning.py`
  - Planner protocol, planner request/result models, document/research/generic planners, and planner chain.
- `python/agent_service/execution_graph.py`
  - Internal execution graph projection from public `RunGraph`.
- `python/tests/test_kernel_state.py`
- `python/tests/test_planning_chain.py`
- `python/tests/test_execution_graph.py`

### Modify

- `python/agent_service/graph.py`
  - Build `AgentRunState`; use planner chain for task and research graph payloads.
- `python/tests/test_graph.py`
  - Add behavior-preserving assertions for kernel state creation and planner chain routing.
- `python/tests/test_agent_routing_integration.py`
  - Add integration assertion that graph payloads remain compatible after planner chain routing.

### Read-Only Regression Targets

- `python/tests/test_execution.py`
- `python/tests/test_planner_v2.py`
- `python/tests/test_graph_compiler.py`
- `src/app/backendEvents.test.ts`
- `src/shared/events.ts`
- `src/shared/types.ts`

---

## Task 0: Baseline Verification

**Files:**
- Read: `docs/superpowers/specs/2026-05-26-workflow-first-agent-kernel-mainline-design.md`
- Read: `python/agent_service/graph.py`
- Read: `python/agent_service/execution.py`
- Read: `python/tests/test_graph.py`
- Read: `python/tests/test_execution.py`
- Read: `src/app/backendEvents.test.ts`

- [ ] **Step 1: Confirm branch and worktree state**

Run:

```powershell
git status --short --branch
```

Expected: the branch is the working branch for Agent Kernel mainline work. If unrelated modified files are present, leave them unstaged and do not include them in commits for this plan.

- [ ] **Step 2: Run focused backend baseline tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_graph.py tests/test_agent_routing_integration.py tests/test_planner_v2.py tests/test_graph_compiler.py -q
Pop-Location
```

Expected: all selected tests pass before any code changes. If a test fails before changes, stop and diagnose the baseline failure.

- [ ] **Step 3: Run focused execution baseline tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_execution.py -q
Pop-Location
```

Expected: all execution tests pass before any code changes.

- [ ] **Step 4: Run frontend event baseline tests**

Run:

```powershell
npm run frontend:test -- src/app/backendEvents.test.ts
```

Expected: `backendEvents.test.ts` passes. This plan should not require frontend changes.

---

## Task 1: Phase 0 Architecture Inventory Audit

**Files:**
- Create: `docs/superpowers/audits/2026-05-26-agent-kernel-mainline-phase-0-inventory.md`

- [ ] **Step 1: Create the audit document**

Create `docs/superpowers/audits/2026-05-26-agent-kernel-mainline-phase-0-inventory.md`:

```markdown
# Agent Kernel Mainline Phase 0 Inventory

## Purpose

This audit records the current Agent runtime contracts before Phase 1 kernel contract consolidation.

## Public Agent Message Events

Current message and planning events:

- `message.created`
- `message.started`
- `message.delta`
- `message.completed`
- `input.required`
- `research.choice_required`
- `planning.progress`
- `node_graph.created`
- `graph.replanned`
- `graph.overwrite_confirmation_required`

Current run events:

- `run.started`
- `run.cancelled`
- `node.running`
- `node.completed`
- `node.failed`
- `node.needs_permission`
- `permission.required`
- `node.run_recorded`
- `node.runtime_notice`
- `artifact.created`
- `graph.patch_suggested`
- `research.completed`
- `task.failed`
- `task.completed`

## Graph Node Types

Backend `GraphNode.nodeType` currently accepts:

- `fixed_tool`
- `model`
- `output`
- `temporary_placeholder`
- `planning`
- `temporary_script`

Frontend `AgentNode.nodeType` must remain compatible with these values.

## Message Routing Paths

`python/agent_service/graph.py` routes:

- `chat` -> `answer_with_model`
- `local_inquiry` -> `answer_with_model`
- `web_simple_inquiry` -> `answer_with_web`
- `web_complex_choice` -> `choose_research_mode`
- `web_complex_research_flow` -> `plan_research_graph`
- `missing_input` -> `request_required_inputs`
- `task` -> `plan_task_graph`

## Planning Paths

Current planning is split:

- Document processing uses `GoalSpec`, `ContextBundle`, `PlannerV2`, `TaskGraph`, and `GraphCompiler`.
- General task planning uses `task_planner.analyze_task`, `select_tools`, `resolve_tool_gaps`, and `build_task_graph`.
- Research graph planning uses `web_research.build_research_graph`.
- Graph feedback uses `plan_feedback.apply_graph_feedback`.

## Execution Paths

`python/agent_service/execution.py` currently selects executors as follows:

- Research graphs use `ResearchFlowExecutor`.
- Planned task graphs use `PlannedTaskExecutor`.
- Other document graphs use `DocumentFlowExecutor`.
- Tests can inject a custom `NodeExecutor`.

## Tool Execution Paths

Current tool paths:

- Document conversion and Typst export go through `ToolExecutor` adapters.
- Research search and source reading are executed inside `ResearchFlowExecutor`.
- Weather answers are routed through `tool_router` and `tool_providers.weather`.
- Simple web search uses `tool_providers.web_search` provider chain.
- Internal and MCP tools are represented by `UnifiedToolGateway`, `InternalToolProvider`, and `MCPToolProvider`.
- Model-provider tool schema conversion exists in `model_tool_adapter.py`, but a full ReAct loop is not yet wired.

## Model Call Paths

Current model call paths:

- Chat and local inquiry use `answer_with_model`.
- Streaming chat uses `stream_agent_events`.
- Document model nodes use `ModelRuntime`.
- Planned generic model nodes use `PlannedTaskExecutor`.
- API and local model selection are resolved through model sessions and `create_model_client`.

## Run Journal Paths

Run journals are written by `run_graph_events` through `RunJournal`.

Node records include:

- `nodeRunId`
- `runId`
- `nodeId`
- `status`
- `startedAt`
- `completedAt`
- `artifactRefs`
- `values`
- `error`
- `errorCode`
- `runtimeNotice`

## Phase 1 Compatibility Requirement

Phase 1 must not change public event names, public graph node IDs, current document graph shape, current research graph shape, or frontend reducer expectations.
```

- [ ] **Step 2: Verify the audit has no draft markers**

Run:

```powershell
rg -n "未填写" docs/superpowers/audits/2026-05-26-agent-kernel-mainline-phase-0-inventory.md
```

Expected: no matches and exit code `1`.

- [ ] **Step 3: Commit the audit**

Run:

```powershell
git add docs/superpowers/audits/2026-05-26-agent-kernel-mainline-phase-0-inventory.md
git commit -m "docs: inventory agent kernel contracts"
```

Expected: commit succeeds.

---

## Task 2: AgentRunState Internal Contract

**Files:**
- Create: `python/agent_service/kernel_state.py`
- Create: `python/tests/test_kernel_state.py`

- [ ] **Step 1: Write failing kernel state tests**

Create `python/tests/test_kernel_state.py`:

```python
from __future__ import annotations

from agent_service.kernel_state import AgentRunBudget, build_agent_run_state
from agent_service.schemas import Attachment, RunGraph, UserMessage


def test_build_agent_run_state_captures_message_goal_and_route() -> None:
    message = UserMessage(
        task_id="task-doc",
        content="整理这个文档并导出 PDF",
        attachments=[
            Attachment(
                attachment_id="a1",
                name="input.docx",
                path="workspace/input.docx",
                size_bytes=128,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ],
        model_session_id="model-session-1",
    )

    state = build_agent_run_state(
        message,
        model_session_id=message.model_session_id,
        disabled_tool_ids=["internal:document.typst_compile"],
        approved_permissions=["write_project_artifact"],
    )

    assert state.task_id == "task-doc"
    assert state.message == message
    assert state.goal_spec.task_type == "document_processing"
    assert state.goal_spec.deliverable == "pdf_report"
    assert state.route_decision["intent"]["kind"] == "task"
    assert state.model_session_id == "model-session-1"
    assert state.disabled_tool_ids == ["internal:document.typst_compile"]
    assert state.approved_permissions == ["write_project_artifact"]
    assert state.budget.max_planning_steps == 16
    assert state.events == []


def test_build_agent_run_state_preserves_current_graph_and_run_context() -> None:
    graph = RunGraph(
        graphId="graph-1",
        nodes=[
            {
                "nodeId": "task-analysis",
                "nodeType": "planning",
                "displayName": "Task Analysis",
                "status": "completed",
                "summary": "Existing graph.",
                "createdBy": "agent",
                "position": {"x": 0, "y": 0},
            }
        ],
        edges=[],
    )

    state = build_agent_run_state(
        UserMessage(task_id="task-1", content="hello"),
        run_id="run-1",
        current_graph=graph,
        has_run_history=True,
        artifact_refs=["artifact-1"],
        pending_choice={"id": "confirm_overwrite"},
    )

    assert state.run_id == "run-1"
    assert state.current_graph == graph
    assert state.has_run_history is True
    assert state.artifact_refs == ["artifact-1"]
    assert state.pending_choice == {"id": "confirm_overwrite"}
    assert state.execution_mode == "message"


def test_agent_run_budget_defaults_are_safe() -> None:
    budget = AgentRunBudget()

    assert budget.max_planning_steps == 16
    assert budget.max_react_steps == 0
    assert budget.max_tool_calls == 0
    assert budget.max_runtime_ms == 120_000
```

- [ ] **Step 2: Run the new tests and verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_kernel_state.py -v
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.kernel_state'`.

- [ ] **Step 3: Implement `kernel_state.py`**

Create `python/agent_service/kernel_state.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_service.goal_spec import GoalSpec, parse_goal_spec
from agent_service.intent import classify_route
from agent_service.schemas import AgentEvent, RunGraph, UserMessage


ExecutionMode = Literal["message", "stream", "graph_run"]


class AgentRunBudget(BaseModel):
    max_planning_steps: int = 16
    max_react_steps: int = 0
    max_tool_calls: int = 0
    max_runtime_ms: int = 120_000


class AgentRunState(BaseModel):
    task_id: str
    run_id: str | None = None
    message: UserMessage
    goal_spec: GoalSpec
    route_decision: dict[str, Any]
    current_graph: RunGraph | None = None
    execution_mode: ExecutionMode = "message"
    model_session_id: str | None = None
    disabled_tool_ids: list[str] = Field(default_factory=list)
    approved_permissions: list[str] = Field(default_factory=list)
    has_run_history: bool = False
    artifact_refs: list[str] = Field(default_factory=list)
    pending_choice: dict[str, Any] | None = None
    budget: AgentRunBudget = Field(default_factory=AgentRunBudget)
    events: list[AgentEvent] = Field(default_factory=list)
    journal_ref: str | None = None


def build_agent_run_state(
    message: UserMessage,
    *,
    run_id: str | None = None,
    current_graph: RunGraph | None = None,
    execution_mode: ExecutionMode = "message",
    model_session_id: str | None = None,
    disabled_tool_ids: list[str] | None = None,
    approved_permissions: list[str] | None = None,
    has_run_history: bool = False,
    artifact_refs: list[str] | None = None,
    pending_choice: dict[str, Any] | None = None,
    budget: AgentRunBudget | None = None,
    journal_ref: str | None = None,
) -> AgentRunState:
    goal_spec = parse_goal_spec(message)
    route_decision = classify_route(message).to_payload()
    return AgentRunState(
        task_id=message.task_id,
        run_id=run_id,
        message=message,
        goal_spec=goal_spec,
        route_decision=route_decision,
        current_graph=current_graph,
        execution_mode=execution_mode,
        model_session_id=model_session_id or message.model_session_id,
        disabled_tool_ids=list(disabled_tool_ids or []),
        approved_permissions=list(approved_permissions or []),
        has_run_history=has_run_history,
        artifact_refs=list(artifact_refs or []),
        pending_choice=pending_choice,
        budget=budget or AgentRunBudget(),
        journal_ref=journal_ref,
    )
```

- [ ] **Step 4: Run kernel state tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_kernel_state.py -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Commit kernel state**

Run:

```powershell
git add python/agent_service/kernel_state.py python/tests/test_kernel_state.py
git commit -m "feat: add agent run state contract"
```

Expected: commit succeeds.

---

## Task 3: Planner Chain Contract

**Files:**
- Create: `python/agent_service/planning.py`
- Create: `python/tests/test_planning_chain.py`

- [ ] **Step 1: Write failing planner chain tests**

Create `python/tests/test_planning_chain.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.context_manager import build_context_bundle
from agent_service.goal_spec import parse_goal_spec
from agent_service.planning import (
    DocumentTemplatePlanner,
    GenericTaskPlanner,
    PlannerChain,
    PlanningError,
    PlanningRequest,
    ResearchTemplatePlanner,
    default_planner_chain,
)
from agent_service.schemas import Attachment, UserMessage
from agent_service.tool_registry import ToolRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_PACKAGES_ROOT = PROJECT_ROOT / "tool-packages"


def _registry() -> ToolRegistry:
    return ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)


def _request(message: UserMessage) -> PlanningRequest:
    registry = _registry()
    goal_spec = parse_goal_spec(message)
    context = build_context_bundle(
        message,
        goal_spec,
        str(PROJECT_ROOT / "project.alita"),
        registry,
    )
    return PlanningRequest(
        task_id=message.task_id,
        message=message,
        goal_spec=goal_spec,
        context=context,
        route_decision={},
        tool_registry=registry,
    )


def test_document_template_planner_returns_existing_document_graph_shape() -> None:
    request = _request(
        UserMessage(
            task_id="task-doc",
            content="summarize this document as PDF",
            attachments=[
                Attachment(
                    attachment_id="a1",
                    name="input.pdf",
                    path=str(PROJECT_ROOT / "input.pdf"),
                    size_bytes=128,
                    mime_type="application/pdf",
                )
            ],
        )
    )

    result = DocumentTemplatePlanner().plan(request)

    assert result.planner == "template.document.v1"
    assert result.graph_payload["graphId"] == "task-doc-graph"
    assert [node["nodeId"] for node in result.graph_payload["nodes"]] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]
    assert result.task_graph is not None
    assert result.confidence >= 0.8


def test_research_template_planner_returns_existing_research_graph_shape() -> None:
    request = _request(
        UserMessage(
            task_id="task-research",
            content="Research and compare current Python packaging tools",
        )
    )

    result = ResearchTemplatePlanner().plan(request)

    assert result.planner == "template.research.v1"
    assert result.task_graph is None
    assert result.graph_payload["metadata"]["kind"] == "research"
    assert [node["nodeId"] for node in result.graph_payload["nodes"]] == [
        "research-intent-analysis",
        "research-privacy-guard",
        "research-query-plan",
        "research-parallel-search",
        "research-source-review",
        "research-source-reading",
        "research-report-synthesis",
        "research-report-quality-check",
        "research-markdown-output",
    ]


def test_generic_task_planner_preserves_existing_planning_nodes() -> None:
    request = _request(
        UserMessage(
            task_id="task-general",
            content="Can you create a Python script that counts rows in a CSV file?",
        )
    )

    result = GenericTaskPlanner().plan(request)

    assert result.planner == "heuristic.task.v1"
    assert result.task_graph is None
    assert result.graph_payload["metadata"]["planningMode"] == "deep"
    assert [
        node["nodeId"]
        for node in result.graph_payload["nodes"]
        if node["nodeType"] == "planning"
    ] == [
        "task-analysis",
        "context-gathering",
        "evidence-summary",
        "plan-draft",
        "capability-analysis",
        "tool-selection",
        "plan-review",
        "execution-order-planning",
    ]


def test_default_planner_chain_selects_document_before_generic_task() -> None:
    request = _request(
        UserMessage(
            task_id="task-doc",
            content="整理成报告",
            attachments=[
                Attachment(
                    attachment_id="a1",
                    name="input.docx",
                    path=str(PROJECT_ROOT / "input.docx"),
                    size_bytes=128,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        )
    )

    result = default_planner_chain(_registry()).plan(request)

    assert result.planner == "template.document.v1"
    assert result.graph_payload["nodes"][0]["nodeId"] == "document-input"


def test_planner_chain_raises_when_no_planner_can_handle_request() -> None:
    request = _request(UserMessage(task_id="task-chat", content="hello"))

    with pytest.raises(PlanningError, match="no planner can handle task type: chat"):
        PlannerChain([]).plan(request)
```

- [ ] **Step 2: Run planner tests and verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_planning_chain.py -v
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.planning'`.

- [ ] **Step 3: Implement planner chain**

Create `python/agent_service/planning.py`:

```python
from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_service.context_manager import ContextBundle
from agent_service.goal_spec import GoalSpec
from agent_service.graph_compiler import compile_task_graph_to_node_graph
from agent_service.planner_v2 import PlannerV2
from agent_service.schemas import UserMessage
from agent_service.task_graph import TaskGraph
from agent_service.task_planner import (
    analyze_task,
    build_task_graph,
    resolve_tool_gaps,
    select_tools,
)
from agent_service.tool_registry import ToolRegistry
from agent_service.web_research import build_research_graph


class PlanningError(ValueError):
    pass


class PlanningRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_id: str
    message: UserMessage
    goal_spec: GoalSpec
    context: ContextBundle
    route_decision: dict[str, Any] = Field(default_factory=dict)
    tool_registry: ToolRegistry
    disabled_tool_ids: list[str] = Field(default_factory=list)
    approved_permissions: list[str] = Field(default_factory=list)


class PlanningResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    planner: str
    graph_payload: dict[str, Any]
    task_graph: TaskGraph | None = None
    confidence: float = 0.7
    metadata: dict[str, Any] = Field(default_factory=dict)


class Planner(Protocol):
    name: str

    def can_plan(self, request: PlanningRequest) -> bool:
        ...

    def plan(self, request: PlanningRequest) -> PlanningResult:
        ...


class PlannerChain:
    def __init__(self, planners: list[Planner]) -> None:
        self.planners = planners

    def plan(self, request: PlanningRequest) -> PlanningResult:
        for planner in self.planners:
            if planner.can_plan(request):
                return planner.plan(request)
        raise PlanningError(
            f"no planner can handle task type: {request.goal_spec.task_type}"
        )


class DocumentTemplatePlanner:
    name = "template.document.v1"

    def can_plan(self, request: PlanningRequest) -> bool:
        return (
            request.goal_spec.task_type == "document_processing"
            and not request.goal_spec.missing_inputs
            and not _is_markdown_conversion_only(request.message.content)
        )

    def plan(self, request: PlanningRequest) -> PlanningResult:
        result = PlannerV2(tool_registry=request.tool_registry).plan(
            task_id=request.task_id,
            goal_spec=request.goal_spec,
            context=request.context,
        )
        graph_payload = compile_task_graph_to_node_graph(result.task_graph)
        return PlanningResult(
            planner=result.planner,
            graph_payload=graph_payload,
            task_graph=result.task_graph,
            confidence=request.goal_spec.confidence,
            metadata={"validationWarnings": result.validation_warnings},
        )


class ResearchTemplatePlanner:
    name = "template.research.v1"

    def can_plan(self, request: PlanningRequest) -> bool:
        return request.goal_spec.task_type == "research"

    def plan(self, request: PlanningRequest) -> PlanningResult:
        return PlanningResult(
            planner=self.name,
            graph_payload=build_research_graph(
                request.message,
                request.route_decision,
            ),
            confidence=request.goal_spec.confidence,
            metadata={"kind": "research"},
        )


class GenericTaskPlanner:
    name = "heuristic.task.v1"

    def can_plan(self, request: PlanningRequest) -> bool:
        return request.goal_spec.task_type != "chat"

    def plan(self, request: PlanningRequest) -> PlanningResult:
        task_plan = analyze_task(request.message.content, request.message.attachments)
        task_plan.task_id = request.task_id
        task_plan.selected_tools = select_tools(
            task_plan.requirements,
            request.tool_registry.enabled_tools(
                disabled_tool_ids=request.disabled_tool_ids
            ),
        )
        task_plan.tool_gaps = resolve_tool_gaps(
            task_plan.requirements,
            task_plan.selected_tools,
        )
        return PlanningResult(
            planner=self.name,
            graph_payload=build_task_graph(task_plan),
            confidence=request.goal_spec.confidence,
            metadata={"taskKind": task_plan.kind.value},
        )


def default_planner_chain(tool_registry: ToolRegistry) -> PlannerChain:
    del tool_registry
    return PlannerChain(
        [
            DocumentTemplatePlanner(),
            ResearchTemplatePlanner(),
            GenericTaskPlanner(),
        ]
    )


def _is_markdown_conversion_only(content: str) -> bool:
    normalized = content.lower()
    wants_markdown = "markdown" in normalized or "md" in normalized
    wants_conversion = "convert" in normalized or "转换" in content or "转" in content
    wants_report = "report" in normalized or "pdf" in normalized or "报告" in content
    return wants_markdown and wants_conversion and not wants_report
```

- [ ] **Step 4: Run planner chain tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_planning_chain.py -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Commit planner chain**

Run:

```powershell
git add python/agent_service/planning.py python/tests/test_planning_chain.py
git commit -m "feat: add agent planner chain contract"
```

Expected: commit succeeds.

---

## Task 4: ExecutionGraph Internal Projection

**Files:**
- Create: `python/agent_service/execution_graph.py`
- Create: `python/tests/test_execution_graph.py`

- [ ] **Step 1: Write failing execution graph tests**

Create `python/tests/test_execution_graph.py`:

```python
from __future__ import annotations

import pytest

from agent_service.execution_graph import ExecutionGraph, ExecutionGraphError
from agent_service.schemas import RunGraph


def test_execution_graph_projects_run_graph_nodes() -> None:
    graph = RunGraph(
        graphId="graph-1",
        nodes=[
            {
                "nodeId": "document-parse",
                "nodeType": "fixed_tool",
                "displayName": "Document parse",
                "status": "waiting",
                "dependencies": [],
                "toolRef": "internal:document.markitdown_convert",
                "summary": "Convert document.",
                "createdBy": "agent",
                "permissionsRequired": ["read_attachment"],
                "riskLevel": "read_only",
                "position": {"x": 0, "y": 0},
            },
            {
                "nodeId": "file-export",
                "nodeType": "output",
                "displayName": "Export",
                "status": "waiting",
                "dependencies": ["document-parse"],
                "summary": "Export artifact.",
                "createdBy": "agent",
                "position": {"x": 180, "y": 0},
            },
        ],
        edges=[
            {
                "id": "document-parse-file-export",
                "source": "document-parse",
                "target": "file-export",
            }
        ],
    )

    execution_graph = ExecutionGraph.from_run_graph(graph)

    assert execution_graph.graph_id == "graph-1"
    assert [node.node_id for node in execution_graph.ordered_nodes()] == [
        "document-parse",
        "file-export",
    ]
    parse_node = execution_graph.node_by_id("document-parse")
    assert parse_node.node_type == "fixed_tool"
    assert parse_node.tool_id == "internal:document.markitdown_convert"
    assert parse_node.permissions_required == ["read_attachment"]
    assert parse_node.risk_level == "read_only"


def test_execution_graph_rejects_duplicate_node_ids() -> None:
    graph = RunGraph(
        graphId="graph-dup",
        nodes=[
            _node("same"),
            _node("same"),
        ],
        edges=[],
    )

    with pytest.raises(ExecutionGraphError, match="duplicate node id: same"):
        ExecutionGraph.from_run_graph(graph)


def test_execution_graph_rejects_missing_dependency() -> None:
    graph = RunGraph(
        graphId="graph-missing-dep",
        nodes=[
            _node("child", dependencies=["missing-parent"]),
        ],
        edges=[],
    )

    with pytest.raises(ExecutionGraphError, match="missing dependency"):
        ExecutionGraph.from_run_graph(graph)


def _node(node_id: str, dependencies: list[str] | None = None) -> dict:
    return {
        "nodeId": node_id,
        "nodeType": "model",
        "displayName": node_id,
        "status": "waiting",
        "dependencies": dependencies or [],
        "summary": "Test node.",
        "createdBy": "agent",
        "position": {"x": 0, "y": 0},
    }
```

- [ ] **Step 2: Run execution graph tests and verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_execution_graph.py -v
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.execution_graph'`.

- [ ] **Step 3: Implement execution graph projection**

Create `python/agent_service/execution_graph.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field

from agent_service.risk_levels import RiskLevel
from agent_service.schemas import RunGraph


class ExecutionGraphError(ValueError):
    pass


class ExecutionNode(BaseModel):
    node_id: str
    node_type: str
    dependencies: list[str] = Field(default_factory=list)
    tool_id: str | None = None
    model_ref: str | None = None
    verifier_id: str | None = None
    permissions_required: list[str] = Field(default_factory=list)
    risk_level: RiskLevel | None = None


class ExecutionGraph(BaseModel):
    graph_id: str
    nodes: list[ExecutionNode]

    @classmethod
    def from_run_graph(cls, graph: RunGraph) -> "ExecutionGraph":
        node_ids = [node.nodeId for node in graph.nodes]
        duplicate_ids = sorted(
            node_id for node_id in set(node_ids) if node_ids.count(node_id) > 1
        )
        if duplicate_ids:
            raise ExecutionGraphError(f"duplicate node id: {duplicate_ids[0]}")

        known_node_ids = set(node_ids)
        execution_nodes: list[ExecutionNode] = []
        for node in graph.nodes:
            for dependency in node.dependencies:
                if dependency not in known_node_ids:
                    raise ExecutionGraphError(
                        f"missing dependency for {node.nodeId}: {dependency}"
                    )
            execution_nodes.append(
                ExecutionNode(
                    node_id=node.nodeId,
                    node_type=node.nodeType,
                    dependencies=list(node.dependencies),
                    tool_id=node.toolRef,
                    model_ref=node.modelRef,
                    permissions_required=list(node.permissionsRequired),
                    risk_level=node.riskLevel,
                )
            )
        return cls(graph_id=graph.graphId, nodes=execution_nodes)

    def node_by_id(self, node_id: str) -> ExecutionNode:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise ExecutionGraphError(f"node not found: {node_id}")

    def ordered_nodes(self) -> list[ExecutionNode]:
        ordered: list[ExecutionNode] = []
        completed: set[str] = set()
        while len(ordered) < len(self.nodes):
            ready = [
                node
                for node in self.nodes
                if node.node_id not in completed
                and all(dependency in completed for dependency in node.dependencies)
            ]
            if not ready:
                raise ExecutionGraphError("cycle detected or dependency not satisfiable")
            for node in ready:
                ordered.append(node)
                completed.add(node.node_id)
        return ordered
```

- [ ] **Step 4: Run execution graph tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_execution_graph.py -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Commit execution graph**

Run:

```powershell
git add python/agent_service/execution_graph.py python/tests/test_execution_graph.py
git commit -m "feat: add internal execution graph contract"
```

Expected: commit succeeds.

---

## Task 5: Wire AgentRunState Into Message Entry Points

**Files:**
- Modify: `python/agent_service/graph.py`
- Modify: `python/tests/test_graph.py`

- [ ] **Step 1: Add failing tests for kernel state construction**

Append to `python/tests/test_graph.py`:

```python
def test_run_agent_builds_agent_run_state(monkeypatch) -> None:
    captured = []

    def recording_builder(message, **kwargs):
        from agent_service.kernel_state import build_agent_run_state

        state = build_agent_run_state(message, **kwargs)
        captured.append(state)
        return state

    monkeypatch.setattr(graph_module, "build_agent_run_state", recording_builder)

    events = run_agent(
        UserMessage(task_id="task-chat", content="hello"),
        model_client=FakeModelClient("hi"),
    )

    assert [event.type for event in events] == ["message.created"]
    assert captured
    assert captured[0].task_id == "task-chat"
    assert captured[0].execution_mode == "message"
    assert captured[0].goal_spec.task_type == "chat"


def test_stream_agent_events_builds_stream_agent_run_state(monkeypatch) -> None:
    captured = []

    def recording_builder(message, **kwargs):
        from agent_service.kernel_state import build_agent_run_state

        state = build_agent_run_state(message, **kwargs)
        captured.append(state)
        return state

    monkeypatch.setattr(graph_module, "build_agent_run_state", recording_builder)

    events = list(
        stream_agent_events(
            UserMessage(task_id="task-chat", content="hello"),
            model_client=FakeModelClient(),
        )
    )

    assert events[0].type == "message.started"
    assert captured
    assert captured[0].task_id == "task-chat"
    assert captured[0].execution_mode == "stream"
```

- [ ] **Step 2: Run the new tests and verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_graph.py::test_run_agent_builds_agent_run_state tests/test_graph.py::test_stream_agent_events_builds_stream_agent_run_state -v
Pop-Location
```

Expected: FAIL because `graph_module` does not expose `build_agent_run_state`.

- [ ] **Step 3: Import and call the kernel state builder**

Modify `python/agent_service/graph.py` imports:

```python
from agent_service.kernel_state import build_agent_run_state
```

At the start of `run_agent()`, after the feedback short-circuit check and before `build_graph(...)`, add:

```python
    kernel_state = build_agent_run_state(
        message,
        current_graph=current_graph,
        execution_mode="message",
        model_session_id=message.model_session_id,
        has_run_history=has_run_history,
        artifact_refs=artifact_refs,
        pending_choice=pending_choice,
    )
```

Update the `app.invoke(...)` call to preserve the state:

```python
    result = app.invoke(
        {
            "message": message,
            "events": [],
            "inquiry_choice": inquiry_choice,
            "kernel_state": kernel_state,
        }
    )
```

Extend `AgentState` in the same file:

```python
    kernel_state: object
```

At the start of `stream_agent_events()`, after the feedback short-circuit check, add:

```python
    kernel_state = build_agent_run_state(
        message,
        current_graph=current_graph,
        execution_mode="stream",
        model_session_id=message.model_session_id,
        has_run_history=has_run_history,
        artifact_refs=artifact_refs,
        pending_choice=pending_choice,
    )
```

When `stream_agent_events()` delegates to `run_agent(...)`, no extra argument is required because `run_agent()` builds its own message-mode state for that branch. Keep public behavior unchanged.

- [ ] **Step 4: Run graph tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_graph.py::test_run_agent_builds_agent_run_state tests/test_graph.py::test_stream_agent_events_builds_stream_agent_run_state tests/test_graph.py::test_plain_chat_returns_local_model_message tests/test_graph.py::test_plain_chat_streams_local_model_message_deltas -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Commit graph entry state wiring**

Run:

```powershell
git add python/agent_service/graph.py python/tests/test_graph.py
git commit -m "refactor: build agent run state at message entrypoints"
```

Expected: commit succeeds.

---

## Task 6: Route Graph Planning Through PlannerChain

**Files:**
- Modify: `python/agent_service/graph.py`
- Modify: `python/tests/test_graph.py`
- Modify: `python/tests/test_agent_routing_integration.py`

- [ ] **Step 1: Add planner chain integration tests**

Append to `python/tests/test_graph.py`:

```python
def test_task_graph_planning_uses_default_planner_chain(monkeypatch) -> None:
    from agent_service.planning import PlanningResult

    captured = []

    class RecordingPlannerChain:
        def plan(self, request):
            captured.append(request)
            return PlanningResult(
                planner="recording.planner",
                graph_payload={
                    "graphId": f"{request.task_id}-graph",
                    "nodes": [
                        {
                            "nodeId": "task-output",
                            "nodeType": "output",
                            "displayName": "Task output",
                            "status": "waiting",
                            "inputPorts": [],
                            "outputPorts": [],
                            "dependencies": [],
                            "summary": "Recorded output.",
                            "createdBy": "agent",
                            "artifactRefs": [],
                            "retryCount": 0,
                            "position": {"x": 0, "y": 0},
                        }
                    ],
                    "edges": [],
                    "metadata": {},
                },
                confidence=0.9,
            )

    monkeypatch.setattr(
        graph_module,
        "default_planner_chain",
        lambda tool_registry: RecordingPlannerChain(),
    )

    events = run_agent(
        UserMessage(
            task_id="task-general",
            content="Can you create a Python script that counts rows in a CSV file?",
        )
    )

    assert captured
    assert captured[0].task_id == "task-general"
    assert captured[0].goal_spec.goal.startswith("Can you create")
    assert events[0].type == "node_graph.created"
    assert events[0].payload["graph"]["metadata"]["modelPolicy"] == "deep_reasoning"


def test_research_graph_planning_uses_default_planner_chain(monkeypatch) -> None:
    from agent_service.planning import PlanningResult

    captured = []

    class RecordingPlannerChain:
        def plan(self, request):
            captured.append(request)
            return PlanningResult(
                planner="recording.research",
                graph_payload={
                    "graphId": f"{request.task_id}-research-graph",
                    "nodes": [
                        {
                            "nodeId": "research-markdown-output",
                            "nodeType": "output",
                            "displayName": "Markdown output",
                            "status": "waiting",
                            "inputPorts": [],
                            "outputPorts": [],
                            "dependencies": [],
                            "summary": "Recorded research output.",
                            "createdBy": "agent",
                            "artifactRefs": [],
                            "retryCount": 0,
                            "position": {"x": 0, "y": 0},
                        }
                    ],
                    "edges": [],
                    "metadata": {"kind": "research"},
                },
                confidence=0.9,
            )

    monkeypatch.setattr(
        graph_module,
        "default_planner_chain",
        lambda tool_registry: RecordingPlannerChain(),
    )

    events = run_agent(
        UserMessage(
            task_id="complex-web",
            content="Research and compare current Python packaging tools",
        ),
        inquiry_choice="research_flow",
    )

    assert captured
    assert captured[0].goal_spec.task_type == "research"
    assert events[0].type == "node_graph.created"
    assert events[0].payload["graph"]["metadata"]["modelPolicy"] == "deep_reasoning"
```

Append to `python/tests/test_agent_routing_integration.py`:

```python
def test_planner_chain_preserves_document_and_research_graph_payloads() -> None:
    document_events = run_agent(
        UserMessage(
            task_id="doc-chain",
            content="整理成报告",
            attachments=[
                {
                    "attachment_id": "a1",
                    "name": "input.docx",
                    "path": "workspace/input.docx",
                    "size_bytes": 100,
                    "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                }
            ],
        )
    )
    document_graph = document_events[0].payload["graph"]
    assert [node["nodeId"] for node in document_graph["nodes"][:6]] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]

    research_events = run_agent(
        UserMessage(
            task_id="research-chain",
            content="Research and compare current Python packaging tools",
        ),
        inquiry_choice="research_flow",
    )
    research_graph = research_events[0].payload["graph"]
    assert research_graph["metadata"]["kind"] == "research"
    assert research_graph["nodes"][0]["nodeId"] == "research-intent-analysis"
```

- [ ] **Step 2: Run integration tests and verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_graph.py::test_task_graph_planning_uses_default_planner_chain tests/test_graph.py::test_research_graph_planning_uses_default_planner_chain tests/test_agent_routing_integration.py::test_planner_chain_preserves_document_and_research_graph_payloads -v
Pop-Location
```

Expected: first two tests FAIL because `graph.py` still calls planning code directly instead of `default_planner_chain`.

- [ ] **Step 3: Import planner chain types in graph**

Modify `python/agent_service/graph.py` imports:

```python
from agent_service.planning import PlanningRequest, default_planner_chain
```

Keep existing imports used by feedback logic and compatibility helpers.

- [ ] **Step 4: Add a graph planning helper in `graph.py`**

Add this helper near `_graph_payload_for_task`:

```python
def _planning_request_for_message(
    message: UserMessage,
    *,
    goal_spec: GoalSpec,
    route_decision: dict,
) -> PlanningRequest:
    tool_registry = ToolRegistry.from_packages_root(default_tool_packages_root())
    context = build_context_bundle(
        message=message,
        goal_spec=goal_spec,
        project_path="project.alita",
        tool_registry=tool_registry,
    )
    return PlanningRequest(
        task_id=message.task_id,
        message=message,
        goal_spec=goal_spec,
        context=context,
        route_decision=route_decision,
        tool_registry=tool_registry,
    )
```

If `build_context_bundle` in the current codebase uses positional parameters, call it with the existing accepted signature:

```python
    context = build_context_bundle(
        message,
        goal_spec,
        "project.alita",
        tool_registry,
    )
```

Use the form accepted by the current function definition.

- [ ] **Step 5: Route task graph payloads through the planner chain**

Replace `_graph_payload_for_task(...)` in `python/agent_service/graph.py` with:

```python
def _graph_payload_for_task(
    message: UserMessage,
    *,
    goal_spec: GoalSpec | None = None,
) -> dict:
    spec = goal_spec or parse_goal_spec(message)
    request = _planning_request_for_message(
        message,
        goal_spec=spec,
        route_decision={},
    )
    graph_payload = default_planner_chain(request.tool_registry).plan(
        request
    ).graph_payload
    return _with_model_policy_metadata(
        graph_payload,
        DEEP_REASONING_POLICY.profile.value,
    )
```

- [ ] **Step 6: Route research graph payloads through the planner chain**

Replace `_research_graph_payload(...)` in `python/agent_service/graph.py` with:

```python
def _research_graph_payload(state: AgentState) -> dict:
    message = state["message"]
    goal_spec = state.get("goal_spec") or parse_goal_spec(message)
    request = _planning_request_for_message(
        message,
        goal_spec=goal_spec,
        route_decision=state.get("route_decision", {}),
    )
    graph_payload = default_planner_chain(request.tool_registry).plan(
        request
    ).graph_payload
    return _with_model_policy_metadata(
        graph_payload,
        DEEP_REASONING_POLICY.profile.value,
    )
```

- [ ] **Step 7: Keep compatibility helpers temporarily**

Leave these functions in `graph.py` if other tests still import them:

- `_build_task_graph_payload`
- `_create_document_graph`
- `_is_markdown_conversion_only`

If `_create_document_graph` becomes unused, do not delete it in this task. Removing compatibility helpers should be a later cleanup after all tests and downstream imports are checked.

- [ ] **Step 8: Run graph and planning tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_planning_chain.py tests/test_graph.py tests/test_agent_routing_integration.py -q
Pop-Location
```

Expected: PASS.

- [ ] **Step 9: Commit planner chain routing**

Run:

```powershell
git add python/agent_service/graph.py python/tests/test_graph.py python/tests/test_agent_routing_integration.py
git commit -m "refactor: route graph planning through planner chain"
```

Expected: commit succeeds.

---

## Task 7: Phase 0-1 Regression

**Files:**
- Read: `python/tests/test_kernel_state.py`
- Read: `python/tests/test_planning_chain.py`
- Read: `python/tests/test_execution_graph.py`
- Read: `python/tests/test_graph.py`
- Read: `python/tests/test_agent_routing_integration.py`
- Read: `python/tests/test_execution.py`
- Read: `src/app/backendEvents.test.ts`

- [ ] **Step 1: Run Phase 0-1 focused Python tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_kernel_state.py tests/test_planning_chain.py tests/test_execution_graph.py tests/test_graph.py tests/test_agent_routing_integration.py tests/test_planner_v2.py tests/test_graph_compiler.py tests/test_execution.py -q
Pop-Location
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full Python suite**

Run:

```powershell
Push-Location python
python -m pytest -q
Pop-Location
```

Expected: full Python suite passes. If optional local model or ASR dependencies are absent, existing tests should still use fakes/mocks and not require real models.

- [ ] **Step 3: Run frontend event reducer regression**

Run:

```powershell
npm run frontend:test -- src/app/backendEvents.test.ts
```

Expected: frontend event reducer tests pass without any source changes.

- [ ] **Step 4: Check final worktree state**

Run:

```powershell
git status --short --branch
```

Expected: only intentional Phase 0-1 files are committed. If unrelated files remain dirty, leave them untouched.

---

## Self-Review Checklist

- Phase 0 audit is covered by Task 1.
- `AgentRunState` is covered by Tasks 2 and 5.
- Planner chain interfaces and behavior-preserving routing are covered by Tasks 3 and 6.
- Internal `ExecutionGraph` is covered by Task 4.
- Existing public event names are unchanged.
- Existing document graph node IDs are unchanged.
- Existing research graph node IDs are unchanged.
- No controlled ReAct loop is implemented in this plan.
- No Reflexion automation is implemented in this plan.
- No Multi-Agent runtime is implemented in this plan.
- Full Python regression is required before completion.
- Frontend reducer regression is required even though frontend files should not change.

## Execution Handoff

Plan execution should proceed task-by-task with tests after each task and commits after each self-contained slice. Use `superpowers:subagent-driven-development` for the recommended execution path, or `superpowers:executing-plans` for inline execution in this session.
