# Agent Runtime Phase E Planner Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Router V2-aware Planner Chain that consumes structured route metadata and produces validated task graph payloads through a single planning protocol.

**Architecture:** Add `planner_chain.py` as the orchestration layer between Router V2 routing and graph payload creation. The first version keeps behavior deterministic: document tasks delegate to `PlannerV2`, non-document task graphs delegate to the existing `task_planner`, and all outputs are validated as `RunGraph` payloads before graph events are emitted. This phase does not add LLM-generated DAGs, ReAct, dynamic tool execution, MCP planning, memory, or sandbox execution.

**Tech Stack:** Python 3.12, Pydantic v2, existing `RouterV2Decision` payloads, existing `AgentRunState`, existing `PlannerV2`, existing `task_planner`, existing `RunGraph` schema, pytest.

---

## Current Baseline

Phase D is complete on branch `codex/agent-runtime-phase-a-security-hygiene`:

- `python/agent_service/router_v2.py` emits safe structured route payloads with `taskType`, `toolCandidates`, `requiredPermissions`, confidence, source, and clarification state.
- `python/agent_service/agent_run_state.py` stores `structured_route_decision`.
- `python/agent_service/graph.py` dispatches by Router V2 while preserving old `AgentIntent` values and old event types.
- Task and research graph payloads include `metadata.routeDecision`.
- `ALITA_STRUCTURED_ROUTER` is off by default.
- `.\scripts\verify-mvp.ps1` passes with `599 passed` Python tests plus frontend typecheck and Rust tests.

The current gap is planning: `_graph_payload_for_task()` still chooses between `_create_document_graph()` and `_build_task_graph_payload()` directly. `PlannerV2` only plans `document_processing`; generic tasks still bypass a unified planner protocol.

## Non-Goals

- Do not implement model-generated plans.
- Do not add ReAct, observation loops, tool calls, MCP tool selection, or execution sandbox behavior.
- Do not change public FastAPI endpoint schemas.
- Do not change frontend event type names.
- Do not change the visible graph node/edge schema.
- Do not remove `PlannerV2`; wrap it as one strategy in Planner Chain.
- Do not remove the existing `task_planner`; wrap it as the compatibility strategy.
- Do not make Phase E depend on `ALITA_STRUCTURED_ROUTER=1`.

## Files

### Create

- `python/agent_service/planner_chain.py`
  - Parses Phase D structured route payloads.
  - Defines the Planner Chain request/result contract.
  - Selects deterministic planning strategies.
  - Delegates document tasks to `PlannerV2`.
  - Delegates non-document task graph generation to `task_planner`.
  - Adds planner-chain metadata and validates output through `RunGraph.model_validate()`.
- `python/tests/test_planner_chain.py`
  - Route payload parsing tests.
  - Strategy selection tests.
  - Document strategy tests.
  - Legacy task planner strategy tests.
  - Metadata and validation tests.

### Modify

- `python/agent_service/graph.py`
  - Route task graph creation through `PlannerChain`.
  - Pass `AgentRunState.structured_route_decision` into planning.
  - Preserve `metadata.routeDecision`, `metadata.modelPolicy`, event types, and graph shape.
- `python/tests/test_graph.py`
  - Assert task graph creation uses Planner Chain metadata.
  - Assert document graph still uses `PlannerV2` through Planner Chain.
  - Assert route metadata remains present.
- `python/tests/test_agent_routing_integration.py`
  - Assert endpoint task graph shape remains stable with Planner Chain metadata.

### Read-Only Regression Targets

- `python/agent_service/planner_v2.py`
- `python/agent_service/task_planner.py`
- `python/agent_service/task_graph.py`
- `python/agent_service/plan_validator.py`
- `python/agent_service/graph_compiler.py`
- `python/agent_service/router_v2.py`
- `python/tests/test_planner_v2.py`
- `python/tests/test_task_planner.py`
- `python/tests/test_graph_compiler.py`
- `src/app/backendEvents.test.ts`

---

## Design Contracts

### Structured Route Context

Planner Chain consumes the existing Phase D payload shape. It should not import private helpers from `router_v2.py`.

```python
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_service.goal_spec import GoalSpec, TaskType
from agent_service.router_v2 import AgentRouteIntent, RouteSource


PlannerStrategy = Literal["document_template", "legacy_task_planner"]
PLANNER_CHAIN_VERSION = "planner_chain.v1"

LOCAL_PATH_PATTERN = re.compile(
    r"(?ix)"
    r"(?:"
    r"\b[a-z]:[\\/](?:[^\\/:\r\n,;<>\"|?*]+[\\/])+[^\\/\s:\r\n,;<>\"|?*]+"
    r"|"
    r"/(?:[^/\r\n,;<>\"|?*]+/){2,}[^/\s\r\n,;<>\"|?*]+"
    r")"
)


class PlannerChainError(ValueError):
    pass


class StructuredRouteContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    intent: AgentRouteIntent
    confidence: float = Field(ge=0.0, le=1.0)
    task_type: TaskType = Field(alias="taskType")
    missing_inputs: list[str] = Field(default_factory=list, alias="missingInputs")
    required_permissions: list[str] = Field(
        default_factory=list,
        alias="requiredPermissions",
    )
    tool_candidates: list[str] = Field(default_factory=list, alias="toolCandidates")
    reason: str
    source: RouteSource
    should_clarify: bool = Field(default=False, alias="shouldClarify")
    clarification_prompt: str | None = Field(
        default=None,
        alias="clarificationPrompt",
    )

    def safe_payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "taskType": self.task_type,
            "missingInputs": _scrub_payload(list(self.missing_inputs)),
            "requiredPermissions": _scrub_payload(list(self.required_permissions)),
            "toolCandidates": _scrub_payload(list(self.tool_candidates)),
            "reason": _safe_text(self.reason),
            "source": self.source,
            "shouldClarify": self.should_clarify,
            "clarificationPrompt": (
                _safe_text(self.clarification_prompt)
                if self.clarification_prompt is not None
                else None
            ),
        }
```

### Planner Chain Request And Result

```python
from agent_service.context_manager import ContextBundle
from agent_service.schemas import UserMessage


class PlannerChainRequest(BaseModel):
    task_id: str
    message: UserMessage
    goal_spec: GoalSpec
    route: StructuredRouteContext
    context: ContextBundle


class PlannerChainResult(BaseModel):
    planner: str
    strategy: PlannerStrategy
    graph_payload: dict[str, Any]
    validation_warnings: list[str] = Field(default_factory=list)
```

### Strategy Rules

- If `route.intent != "task"`, Planner Chain raises `PlannerChainError`.
- If `route.missing_inputs` or `goal_spec.missing_inputs` is non-empty, Planner Chain raises `PlannerChainError`.
- If `route.task_type == "document_processing"` and the user is not asking only for document-to-Markdown conversion, use `PlannerV2` and compile its `TaskGraph`.
- If `route.task_type == "document_processing"` but the user is asking only for document-to-Markdown conversion, use the existing `task_planner` compatibility strategy. This preserves the current parse/export graph shape and avoids turning a simple conversion into the six-node PDF/report template.
- For `code_task`, `local_file`, `content_creation`, `automation`, `chat`, `research`, or `unknown` task types routed as `task`, use the existing `task_planner` compatibility strategy.
- Every graph payload produced by Planner Chain must pass `RunGraph.model_validate(graph_payload)`.
- Planner Chain metadata is stored under `graph.metadata.plannerChain`; route metadata stays under `graph.metadata.routeDecision` in `graph.py`.

### Planner Chain Metadata

Planner Chain should add only safe metadata:

```python
metadata["plannerChain"] = {
    "version": "planner_chain.v1",
    "planner": result.planner,
    "strategy": result.strategy,
    "routeIntent": request.route.intent,
    "taskType": request.route.task_type,
    "routeSource": request.route.source,
    "routeConfidence": request.route.confidence,
    "toolCandidates": _scrub_payload(list(request.route.tool_candidates)),
    "requiredPermissions": _scrub_payload(list(request.route.required_permissions)),
}
```

Do not put attachment paths, local file paths, raw prompt text, or model output text in Planner Chain metadata.

---

## Task 0: Baseline Verification

**Files:**
- Read: `python/agent_service/graph.py`
- Read: `python/agent_service/planner_v2.py`
- Read: `python/agent_service/task_planner.py`
- Read: `python/tests/test_graph.py`
- Read: `python/tests/test_planner_v2.py`

- [ ] **Step 1: Confirm branch and clean worktree**

Run:

```powershell
git status --short --branch
```

Expected:

```text
## codex/agent-runtime-phase-a-security-hygiene
```

- [ ] **Step 2: Run focused planning baseline**

Run:

```powershell
python -m pytest -q python\tests\test_planner_v2.py python\tests\test_task_planner.py python\tests\test_graph.py python\tests\test_agent_routing_integration.py
```

Expected:

```text
... passed
```

- [ ] **Step 3: Run frontend graph event baseline**

Run:

```powershell
npm run frontend:test -- src\app\backendEvents.test.ts
```

Expected:

```text
Test Files  1 passed
```

- [ ] **Step 4: Commit status**

Do not commit in Task 0. Continue only if the worktree is clean.

---

## Task 1: Planner Chain Contract And Route Context

**Files:**
- Create: `python/agent_service/planner_chain.py`
- Create: `python/tests/test_planner_chain.py`

- [ ] **Step 1: Add failing route context tests**

Create `python/tests/test_planner_chain.py` with:

```python
from __future__ import annotations

import pytest

from agent_service.planner_chain import (
    PlannerChainError,
    StructuredRouteContext,
    route_context_from_payload,
)


def _route_payload(**overrides):
    payload = {
        "intent": "task",
        "confidence": 0.88,
        "taskType": "code_task",
        "missingInputs": [],
        "requiredPermissions": ["read_project_files"],
        "toolCandidates": ["internal:file.inspect"],
        "reason": "User asks for a coding task.",
        "source": "deterministic",
        "shouldClarify": False,
        "clarificationPrompt": None,
    }
    payload.update(overrides)
    return payload


def test_route_context_parses_phase_d_payload_keys() -> None:
    route = route_context_from_payload(_route_payload())

    assert route.intent == "task"
    assert route.task_type == "code_task"
    assert route.required_permissions == ["read_project_files"]
    assert route.tool_candidates == ["internal:file.inspect"]


def test_route_context_safe_payload_scrubs_path_values() -> None:
    local_path = r"D:\Software Project\Alita\python\agent_service\graph.py"
    route = route_context_from_payload(
        _route_payload(
            missingInputs=[local_path],
            toolCandidates=[local_path],
            reason=f"Need {local_path}",
        )
    )

    payload_dump = repr(route.safe_payload())

    assert local_path not in payload_dump
    assert "Software Project" not in payload_dump
    assert "agent_service" not in payload_dump


def test_route_context_rejects_invalid_payload() -> None:
    with pytest.raises(PlannerChainError, match="invalid structured route payload"):
        route_context_from_payload({"intent": "task"})
```

- [ ] **Step 2: Run the failing tests**

Run:

```powershell
python -m pytest -q python\tests\test_planner_chain.py
```

Expected:

```text
ModuleNotFoundError: No module named 'agent_service.planner_chain'
```

- [ ] **Step 3: Create planner chain contract module**

Create `python/agent_service/planner_chain.py` with:

```python
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_service.context_manager import ContextBundle
from agent_service.goal_spec import GoalSpec, TaskType
from agent_service.router_v2 import AgentRouteIntent, RouteSource
from agent_service.schemas import UserMessage


PlannerStrategy = Literal["document_template", "legacy_task_planner"]
PLANNER_CHAIN_VERSION = "planner_chain.v1"
LOCAL_PATH_PATTERN = re.compile(
    r"(?ix)"
    r"(?:"
    r"\b[a-z]:[\\/](?:[^\\/:\r\n,;<>\"|?*]+[\\/])+[^\\/\s:\r\n,;<>\"|?*]+"
    r"|"
    r"/(?:[^/\r\n,;<>\"|?*]+/){2,}[^/\s\r\n,;<>\"|?*]+"
    r")"
)


class PlannerChainError(ValueError):
    pass


class StructuredRouteContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    intent: AgentRouteIntent
    confidence: float = Field(ge=0.0, le=1.0)
    task_type: TaskType = Field(alias="taskType")
    missing_inputs: list[str] = Field(default_factory=list, alias="missingInputs")
    required_permissions: list[str] = Field(
        default_factory=list,
        alias="requiredPermissions",
    )
    tool_candidates: list[str] = Field(default_factory=list, alias="toolCandidates")
    reason: str
    source: RouteSource
    should_clarify: bool = Field(default=False, alias="shouldClarify")
    clarification_prompt: str | None = Field(
        default=None,
        alias="clarificationPrompt",
    )

    def safe_payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "taskType": self.task_type,
            "missingInputs": _scrub_payload(list(self.missing_inputs)),
            "requiredPermissions": _scrub_payload(list(self.required_permissions)),
            "toolCandidates": _scrub_payload(list(self.tool_candidates)),
            "reason": _safe_text(self.reason),
            "source": self.source,
            "shouldClarify": self.should_clarify,
            "clarificationPrompt": (
                _safe_text(self.clarification_prompt)
                if self.clarification_prompt is not None
                else None
            ),
        }


class PlannerChainRequest(BaseModel):
    task_id: str
    message: UserMessage
    goal_spec: GoalSpec
    route: StructuredRouteContext
    context: ContextBundle


class PlannerChainResult(BaseModel):
    planner: str
    strategy: PlannerStrategy
    graph_payload: dict[str, Any]
    validation_warnings: list[str] = Field(default_factory=list)


def route_context_from_payload(payload: dict[str, Any]) -> StructuredRouteContext:
    try:
        return StructuredRouteContext.model_validate(payload)
    except ValidationError as exc:
        raise PlannerChainError(f"invalid structured route payload: {exc}") from exc


def _safe_text(value: str) -> str:
    return LOCAL_PATH_PATTERN.sub("[local_path]", value)


def _scrub_payload(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, list):
        return [_scrub_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _scrub_payload(item) for key, item in value.items()}
    return value
```

- [ ] **Step 4: Run planner chain contract tests**

Run:

```powershell
python -m pytest -q python\tests\test_planner_chain.py
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/planner_chain.py python/tests/test_planner_chain.py
git commit -m "feat: add planner chain contract"
```

---

## Task 2: Document Strategy Through PlannerV2

**Files:**
- Modify: `python/agent_service/planner_chain.py`
- Modify: `python/tests/test_planner_chain.py`

- [ ] **Step 1: Add failing document strategy tests**

Append to `python/tests/test_planner_chain.py`:

```python
from pathlib import Path

from agent_service.context_manager import build_context_bundle
from agent_service.goal_spec import parse_goal_spec
from agent_service.planner_chain import PlannerChain, PlannerChainRequest
from agent_service.schemas import Attachment, RunGraph, UserMessage
from agent_service.tool_registry import ToolRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_PACKAGES_ROOT = PROJECT_ROOT / "tool-packages"


def _tool_registry() -> ToolRegistry:
    return ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)


def _document_message() -> UserMessage:
    return UserMessage(
        task_id="task-document-chain",
        content="summarize this document as a PDF report",
        attachments=[
            Attachment(
                attachment_id="a1",
                name="source.docx",
                path=str(PROJECT_ROOT / "fixtures" / "source.docx"),
                size_bytes=128,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ],
    )


def _request_for(message: UserMessage, route_payload: dict) -> PlannerChainRequest:
    goal_spec = parse_goal_spec(message)
    registry = _tool_registry()
    context = build_context_bundle(
        message,
        goal_spec,
        str(PROJECT_ROOT),
        registry,
    )
    return PlannerChainRequest(
        task_id=message.task_id,
        message=message,
        goal_spec=goal_spec,
        route=route_context_from_payload(route_payload),
        context=context,
    )


def test_planner_chain_uses_planner_v2_for_document_processing() -> None:
    message = _document_message()
    request = _request_for(
        message,
        _route_payload(taskType="document_processing"),
    )

    result = PlannerChain(tool_registry=_tool_registry()).plan(request)

    assert result.planner == "template.document.v1"
    assert result.strategy == "document_template"
    RunGraph.model_validate(result.graph_payload)
    assert [node["nodeId"] for node in result.graph_payload["nodes"]] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]
    metadata = result.graph_payload["metadata"]["plannerChain"]
    assert metadata["version"] == "planner_chain.v1"
    assert metadata["strategy"] == "document_template"
    assert metadata["taskType"] == "document_processing"


def test_planner_chain_rejects_missing_inputs_before_planning() -> None:
    message = UserMessage(task_id="missing-doc", content="summarize this document")
    request = _request_for(
        message,
        _route_payload(taskType="document_processing", missingInputs=["document_file"]),
    )

    with pytest.raises(PlannerChainError, match="missing inputs: document_file"):
        PlannerChain(tool_registry=_tool_registry()).plan(request)


def test_planner_chain_rejects_non_task_routes() -> None:
    message = UserMessage(task_id="not-task", content="hello")
    request = _request_for(
        message,
        _route_payload(intent="chat", taskType="chat"),
    )

    with pytest.raises(PlannerChainError, match="cannot plan non-task route"):
        PlannerChain(tool_registry=_tool_registry()).plan(request)
```

- [ ] **Step 2: Run the new tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_planner_chain.py::test_planner_chain_uses_planner_v2_for_document_processing python\tests\test_planner_chain.py::test_planner_chain_rejects_missing_inputs_before_planning python\tests\test_planner_chain.py::test_planner_chain_rejects_non_task_routes
```

Expected:

```text
ImportError: cannot import name 'PlannerChain'
```

- [ ] **Step 3: Implement PlannerChain document strategy**

Add these imports near the existing imports in `python/agent_service/planner_chain.py`, then add `PlannerChain` below `route_context_from_payload()`:

```python
from agent_service.graph_compiler import compile_task_graph_to_node_graph
from agent_service.model_runtime import SupportedModelRegistry
from agent_service.planner_v2 import PlannerV2, PlannerV2Error
from agent_service.schemas import RunGraph
from agent_service.tool_registry import ToolRegistry

try:
    from agent_service.model_runtime import DEFAULT_SUPPORTED_MODEL_REGISTRY
except ImportError:
    DEFAULT_SUPPORTED_MODEL_REGISTRY = SupportedModelRegistry.default()


class PlannerChain:
    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        model_registry: SupportedModelRegistry | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.model_registry = model_registry or DEFAULT_SUPPORTED_MODEL_REGISTRY

    def plan(self, request: PlannerChainRequest) -> PlannerChainResult:
        self._validate_request(request)
        if request.route.task_type == "document_processing" and not _is_markdown_conversion_only(
            request.message.content
        ):
            return self._plan_document_template(request)
        raise PlannerChainError(f"unsupported planner chain task type: {request.route.task_type}")

    def _validate_request(self, request: PlannerChainRequest) -> None:
        if request.route.intent != "task":
            raise PlannerChainError(f"cannot plan non-task route: {request.route.intent}")
        missing_inputs = [
            *request.route.missing_inputs,
            *request.goal_spec.missing_inputs,
        ]
        if missing_inputs:
            raise PlannerChainError(f"missing inputs: {', '.join(missing_inputs)}")

    def _plan_document_template(
        self,
        request: PlannerChainRequest,
    ) -> PlannerChainResult:
        try:
            plan = PlannerV2(
                tool_registry=self.tool_registry,
                model_registry=self.model_registry,
            ).plan(
                task_id=request.task_id,
                goal_spec=request.goal_spec,
                context=request.context,
            )
        except PlannerV2Error as exc:
            raise PlannerChainError(str(exc)) from exc

        graph_payload = compile_task_graph_to_node_graph(plan.task_graph)
        graph_payload = _with_planner_chain_metadata(
            graph_payload,
            request=request,
            planner=plan.planner,
            strategy="document_template",
        )
        _validate_graph_payload(graph_payload)
        return PlannerChainResult(
            planner=plan.planner,
            strategy="document_template",
            graph_payload=graph_payload,
            validation_warnings=list(plan.validation_warnings),
        )
```

Append these helper functions after `PlannerChain`:

```python
def _with_planner_chain_metadata(
    graph_payload: dict[str, Any],
    *,
    request: PlannerChainRequest,
    planner: str,
    strategy: PlannerStrategy,
) -> dict[str, Any]:
    metadata = dict(graph_payload.get("metadata") or {})
    metadata["plannerChain"] = {
        "version": PLANNER_CHAIN_VERSION,
        "planner": planner,
        "strategy": strategy,
        "routeIntent": request.route.intent,
        "taskType": request.route.task_type,
        "routeSource": request.route.source,
        "routeConfidence": request.route.confidence,
        "toolCandidates": _scrub_payload(list(request.route.tool_candidates)),
        "requiredPermissions": _scrub_payload(list(request.route.required_permissions)),
    }
    return {**graph_payload, "metadata": metadata}


def _validate_graph_payload(graph_payload: dict[str, Any]) -> None:
    try:
        RunGraph.model_validate(graph_payload)
    except Exception as exc:
        raise PlannerChainError(f"invalid node graph payload: {exc}") from exc


def _is_markdown_conversion_only(content: str) -> bool:
    normalized = content.lower()
    wants_markdown = "markdown" in normalized or "md" in normalized
    wants_conversion = "convert" in normalized or "转换" in content or "转" in content
    wants_report = "report" in normalized or "pdf" in normalized or "报告" in content
    return wants_markdown and wants_conversion and not wants_report
```

- [ ] **Step 4: Run planner chain document tests**

Run:

```powershell
python -m pytest -q python\tests\test_planner_chain.py python\tests\test_planner_v2.py python\tests\test_graph_compiler.py
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/planner_chain.py python/tests/test_planner_chain.py
git commit -m "feat: add document planner chain strategy"
```

---

## Task 3: Legacy Task Planner Strategy

**Files:**
- Modify: `python/agent_service/planner_chain.py`
- Modify: `python/tests/test_planner_chain.py`

- [ ] **Step 1: Add failing legacy strategy tests**

Append to `python/tests/test_planner_chain.py`:

```python
def test_planner_chain_uses_legacy_task_planner_for_code_task() -> None:
    message = UserMessage(
        task_id="task-code-chain",
        content="Create a Python script that counts rows in a CSV file.",
    )
    request = _request_for(
        message,
        _route_payload(taskType="code_task", toolCandidates=[]),
    )

    result = PlannerChain(tool_registry=_tool_registry()).plan(request)

    assert result.planner == "legacy.task_planner.v1"
    assert result.strategy == "legacy_task_planner"
    RunGraph.model_validate(result.graph_payload)
    assert result.graph_payload["graphId"] == "task-code-chain-graph"
    assert result.graph_payload["metadata"]["plannerChain"]["strategy"] == (
        "legacy_task_planner"
    )
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


def test_planner_chain_metadata_does_not_include_raw_route_paths() -> None:
    local_path = r"D:\Software Project\Alita\python\agent_service\graph.py"
    message = UserMessage(
        task_id="task-path-chain",
        content="Create a Python script that counts rows in a CSV file.",
    )
    request = _request_for(
        message,
        _route_payload(
            taskType="code_task",
            toolCandidates=[local_path],
            requiredPermissions=[local_path],
        ),
    )

    result = PlannerChain(tool_registry=_tool_registry()).plan(request)
    metadata_dump = repr(result.graph_payload["metadata"]["plannerChain"])

    assert local_path not in metadata_dump
    assert "Software Project" not in metadata_dump
    assert "agent_service" not in metadata_dump


def test_planner_chain_preserves_markdown_conversion_legacy_strategy() -> None:
    message = UserMessage(
        task_id="doc-markdown-chain",
        content="Please convert this document to Markdown.",
        attachments=[
            Attachment(
                attachment_id="a-markdown",
                name="markdown-source.docx",
                path=str(PROJECT_ROOT / "fixtures" / "markdown-source.docx"),
                size_bytes=128,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ],
    )
    request = _request_for(
        message,
        _route_payload(taskType="document_processing", toolCandidates=[]),
    )

    result = PlannerChain(tool_registry=_tool_registry()).plan(request)

    assert result.planner == "legacy.task_planner.v1"
    assert result.strategy == "legacy_task_planner"
    assert [node["nodeId"] for node in result.graph_payload["nodes"]] == [
        "document-input",
        "document-parse",
        "file-export",
        "task-analysis",
        "context-gathering",
        "evidence-summary",
        "plan-draft",
        "capability-analysis",
        "tool-selection",
        "plan-review",
        "execution-order-planning",
    ]
    assert "typst-export" not in {node["nodeId"] for node in result.graph_payload["nodes"]}
```

- [ ] **Step 2: Run the new tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_planner_chain.py::test_planner_chain_uses_legacy_task_planner_for_code_task python\tests\test_planner_chain.py::test_planner_chain_metadata_does_not_include_raw_route_paths python\tests\test_planner_chain.py::test_planner_chain_preserves_markdown_conversion_legacy_strategy
```

Expected:

```text
PlannerChainError: unsupported planner chain task type
```

- [ ] **Step 3: Implement legacy task planner strategy**

In `python/agent_service/planner_chain.py`, add imports:

```python
from agent_service.task_planner import (
    analyze_task,
    build_task_graph,
    resolve_tool_gaps,
    select_tools,
)
```

Change `PlannerChain.plan()` to:

```python
    def plan(self, request: PlannerChainRequest) -> PlannerChainResult:
        self._validate_request(request)
        if request.route.task_type == "document_processing" and not _is_markdown_conversion_only(
            request.message.content
        ):
            return self._plan_document_template(request)
        return self._plan_legacy_task(request)
```

Append this method inside `PlannerChain`:

```python
    def _plan_legacy_task(self, request: PlannerChainRequest) -> PlannerChainResult:
        task_plan = analyze_task(request.message.content, request.message.attachments)
        task_plan.task_id = request.task_id
        task_plan.selected_tools = select_tools(
            task_plan.requirements,
            self.tool_registry.enabled_tools(),
        )
        task_plan.tool_gaps = resolve_tool_gaps(
            task_plan.requirements,
            task_plan.selected_tools,
        )
        graph_payload = build_task_graph(task_plan)
        graph_payload = _with_planner_chain_metadata(
            graph_payload,
            request=request,
            planner="legacy.task_planner.v1",
            strategy="legacy_task_planner",
        )
        _validate_graph_payload(graph_payload)
        return PlannerChainResult(
            planner="legacy.task_planner.v1",
            strategy="legacy_task_planner",
            graph_payload=graph_payload,
            validation_warnings=[],
        )
```

- [ ] **Step 4: Run planner chain tests**

Run:

```powershell
python -m pytest -q python\tests\test_planner_chain.py python\tests\test_task_planner.py
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/planner_chain.py python/tests/test_planner_chain.py
git commit -m "feat: add legacy planner chain strategy"
```

---

## Task 4: Integrate Planner Chain Into Graph Task Planning

**Files:**
- Modify: `python/agent_service/graph.py`
- Modify: `python/tests/test_graph.py`
- Modify: `python/tests/test_agent_routing_integration.py`

- [ ] **Step 1: Add failing graph integration tests**

Append to `python/tests/test_graph.py`:

```python
def test_task_graph_records_planner_chain_metadata() -> None:
    events = run_agent(
        UserMessage(
            task_id="planner-chain-code",
            content="Create a Python script that counts rows in a CSV file.",
        )
    )

    graph = events[0].payload["graph"]
    planner_chain = graph["metadata"]["plannerChain"]
    assert planner_chain["version"] == "planner_chain.v1"
    assert planner_chain["planner"] == "legacy.task_planner.v1"
    assert planner_chain["strategy"] == "legacy_task_planner"
    assert planner_chain["routeIntent"] == "task"
    assert planner_chain["taskType"] == "code_task"
    assert graph["metadata"]["routeDecision"]["intent"] == "task"


def test_document_task_graph_records_document_planner_chain_metadata() -> None:
    events = run_agent(
        UserMessage(
            task_id="planner-chain-document",
            content="summarize this document as a PDF report",
            attachments=[
                Attachment(
                    attachment_id="a-planner-chain",
                    name="planner-chain.docx",
                    path="workspace/inputs/planner-chain.docx",
                    size_bytes=100,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        )
    )

    graph = events[0].payload["graph"]
    planner_chain = graph["metadata"]["plannerChain"]
    assert planner_chain["version"] == "planner_chain.v1"
    assert planner_chain["planner"] == "template.document.v1"
    assert planner_chain["strategy"] == "document_template"
    assert planner_chain["taskType"] == "document_processing"
    assert [node["nodeId"] for node in graph["nodes"]] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]
```

In `python/tests/test_agent_routing_integration.py`, add to `test_task_message_creates_graph_with_planning_and_executable_nodes()`:

```python
    planner_chain = graph["metadata"]["plannerChain"]
    assert planner_chain["version"] == "planner_chain.v1"
    assert planner_chain["strategy"] == "legacy_task_planner"
```

- [ ] **Step 2: Run integration tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_graph.py::test_task_graph_records_planner_chain_metadata python\tests\test_graph.py::test_document_task_graph_records_document_planner_chain_metadata python\tests\test_agent_routing_integration.py::test_task_message_creates_graph_with_planning_and_executable_nodes
```

Expected:

```text
KeyError: 'plannerChain'
```

- [ ] **Step 3: Update graph imports**

In `python/agent_service/graph.py`, remove imports that will no longer be needed directly:

```python
from agent_service.graph_compiler import compile_task_graph_to_node_graph
from agent_service.planner_v2 import PlannerV2
from agent_service.task_planner import (
    analyze_task,
    build_task_graph,
    resolve_tool_gaps,
    select_tools,
)
```

Add:

```python
from agent_service.planner_chain import (
    PlannerChain,
    PlannerChainRequest,
    route_context_from_payload,
)
from agent_service.router_v2 import deterministic_route
```

Keep `build_context_bundle`, `ToolRegistry`, and `default_tool_packages_root`.

- [ ] **Step 4: Thread run_state into task graph payload creation**

Change `plan_task_graph()`:

```python
def plan_task_graph(state: AgentState) -> AgentState:
    message = state["message"]
    run_state = state.get("run_state")
    graph_payload = _graph_payload_for_task(
        message,
        goal_spec=state.get("goal_spec"),
        run_state=run_state,
    )
    graph_payload = _with_route_decision_metadata(
        graph_payload,
        run_state,
    )
    return {
        **state,
        "events": [
            AgentEvent(
                type="node_graph.created",
                payload={"graph": graph_payload},
            )
        ],
    }
```

Change `_graph_payload_for_task()` signature and body:

```python
def _graph_payload_for_task(
    message: UserMessage,
    *,
    goal_spec: GoalSpec | None = None,
    run_state: AgentRunState | None = None,
) -> dict:
    spec = goal_spec or parse_goal_spec(message)
    tool_registry = ToolRegistry.from_packages_root(default_tool_packages_root())
    route_payload = _structured_route_payload_for_planning(message, run_state)
    context = build_context_bundle(
        message=message,
        goal_spec=spec,
        project_path="project.alita",
        tool_registry=tool_registry,
    )
    result = PlannerChain(tool_registry=tool_registry).plan(
        PlannerChainRequest(
            task_id=message.task_id,
            message=message,
            goal_spec=spec,
            route=route_context_from_payload(route_payload),
            context=context,
        )
    )
    return _with_model_policy_metadata(
        result.graph_payload,
        DEEP_REASONING_POLICY.profile.value,
    )
```

Add helper:

```python
def _structured_route_payload_for_planning(
    message: UserMessage,
    run_state: AgentRunState | None,
) -> dict:
    if run_state is not None and run_state.structured_route_decision is not None:
        return dict(run_state.structured_route_decision)
    return deterministic_route(message).to_payload()
```

- [ ] **Step 5: Update stream task branch**

In `stream_agent_events_from_state()`, change:

```python
        graph_payload = _graph_payload_for_task(
            message,
            goal_spec=run_state.goal_spec,
        )
```

to:

```python
        graph_payload = _graph_payload_for_task(
            message,
            goal_spec=run_state.goal_spec,
            run_state=run_state,
        )
```

- [ ] **Step 6: Remove graph-local document strategy helpers**

Delete `_build_task_graph_payload()`, `_create_document_graph()`, and `_is_markdown_conversion_only()` from `python/agent_service/graph.py`. Planner Chain now owns the legacy task planner delegation, the `PlannerV2` delegation, and the markdown-only compatibility branch.

- [ ] **Step 7: Update the existing document planner graph test**

In `python/tests/test_graph.py`, update the existing `test_attachment_document_task_graph_uses_planner_v2_shape()` so it no longer patches `graph_module.PlannerV2`. Rename it to `test_attachment_document_task_graph_uses_planner_chain_shape()` and patch `graph_module.PlannerChain` instead:

```python
def test_attachment_document_task_graph_uses_planner_chain_shape(monkeypatch) -> None:
    planner_calls: list[dict[str, object]] = []

    class RecordingPlannerChain:
        def __init__(self, *, tool_registry) -> None:
            self.tool_registry = tool_registry

        def plan(self, request):
            planner_calls.append(
                {
                    "task_id": request.task_id,
                    "goal_spec": request.goal_spec,
                    "context": request.context,
                    "route": request.route,
                    "tool_registry": self.tool_registry,
                }
            )
            graph_payload = compile_task_graph_to_node_graph(
                build_document_task_graph(request.task_id, request.goal_spec)
            )
            graph_payload["metadata"] = {
                "plannerChain": {
                    "version": "planner_chain.v1",
                    "planner": "template.document.v1",
                    "strategy": "document_template",
                    "routeIntent": request.route.intent,
                    "taskType": request.route.task_type,
                    "routeSource": request.route.source,
                    "routeConfidence": request.route.confidence,
                    "toolCandidates": list(request.route.tool_candidates),
                    "requiredPermissions": list(request.route.required_permissions),
                }
            }
            return SimpleNamespace(graph_payload=graph_payload)

    monkeypatch.setattr(graph_module, "PlannerChain", RecordingPlannerChain)

    events = run_agent(
        UserMessage(
            task_id="task-planner-chain",
            content="summarize this document as a PDF report",
            attachments=[
                Attachment(
                    attachment_id="a-planner-chain",
                    name="planner-chain.docx",
                    path="workspace/inputs/planner-chain.docx",
                    size_bytes=100,
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            ],
        )
    )

    assert planner_calls
    assert planner_calls[0]["task_id"] == "task-planner-chain"
    assert planner_calls[0]["route"].task_type == "document_processing"
    assert len(events) == 1
    assert events[0].type == "node_graph.created"
    graph = events[0].payload["graph"]
    assert graph["graphId"] == "task-planner-chain-graph"
    assert graph["metadata"]["plannerChain"]["strategy"] == "document_template"
    assert graph["metadata"]["modelPolicy"] == ModelCallProfile.DEEP_REASONING.value
```

Add this import at the top of `python/tests/test_graph.py` if it is not already present:

```python
from agent_service.graph_compiler import compile_task_graph_to_node_graph
```

- [ ] **Step 8: Run graph integration tests**

Run:

```powershell
python -m pytest -q python\tests\test_graph.py::test_task_graph_records_planner_chain_metadata python\tests\test_graph.py::test_document_task_graph_records_document_planner_chain_metadata python\tests\test_agent_routing_integration.py::test_task_message_creates_graph_with_planning_and_executable_nodes
```

Expected:

```text
... passed
```

- [ ] **Step 9: Run broader planning regressions**

Run:

```powershell
python -m pytest -q python\tests\test_planner_chain.py python\tests\test_graph.py python\tests\test_agent_routing_integration.py python\tests\test_planner_v2.py python\tests\test_task_planner.py
```

Expected:

```text
... passed
```

- [ ] **Step 10: Commit**

Run:

```powershell
git add python/agent_service/graph.py python/tests/test_graph.py python/tests/test_agent_routing_integration.py
git commit -m "refactor: route task graph planning through planner chain"
```

---

## Task 5: Planner Chain Compatibility And Privacy Regression

**Files:**
- Modify: `python/tests/test_planner_chain.py`
- Modify: `python/tests/test_graph.py`
- Read: `src/app/backendEvents.test.ts`

- [ ] **Step 1: Add unsupported and validation regression tests**

Append to `python/tests/test_planner_chain.py`:

```python
def test_planner_chain_rejects_missing_goal_spec_inputs_even_if_route_is_clean() -> None:
    message = UserMessage(task_id="missing-doc-goal", content="summarize this document")
    goal_spec = parse_goal_spec(message)
    registry = _tool_registry()
    context = build_context_bundle(
        message,
        goal_spec,
        str(PROJECT_ROOT),
        registry,
    )
    request = PlannerChainRequest(
        task_id=message.task_id,
        message=message,
        goal_spec=goal_spec,
        route=route_context_from_payload(
            _route_payload(taskType="document_processing", missingInputs=[])
        ),
        context=context,
    )

    with pytest.raises(PlannerChainError, match="missing inputs: document_file"):
        PlannerChain(tool_registry=registry).plan(request)


def test_planner_chain_wraps_invalid_document_plan_errors() -> None:
    message = _document_message()
    request = _request_for(
        message,
        _route_payload(taskType="document_processing"),
    )

    with pytest.raises(PlannerChainError, match="invalid plan: unknown tool binding"):
        PlannerChain(tool_registry=ToolRegistry([])).plan(request)
```

- [ ] **Step 2: Add frontend event compatibility assertion**

Append to `python/tests/test_graph.py`:

```python
def test_planner_chain_metadata_does_not_change_node_graph_event_shape() -> None:
    events = run_agent(
        UserMessage(
            task_id="planner-chain-event-shape",
            content="Create a Python script that counts rows in a CSV file.",
        )
    )

    assert [event.type for event in events] == ["node_graph.created"]
    event = events[0]
    assert set(event.payload.keys()) == {"graph"}
    graph = event.payload["graph"]
    assert "plannerChain" in graph["metadata"]
    assert "routeDecision" in graph["metadata"]
```

- [ ] **Step 3: Run compatibility tests**

Run:

```powershell
python -m pytest -q python\tests\test_planner_chain.py python\tests\test_graph.py python\tests\test_agent_routing_integration.py
npm run frontend:test -- src\app\backendEvents.test.ts
```

Expected:

```text
... passed
Test Files  1 passed
```

- [ ] **Step 4: Commit**

Run:

```powershell
git add python/tests/test_planner_chain.py python/tests/test_graph.py
git commit -m "test: cover planner chain compatibility"
```

---

## Task 6: Final Regression And Review

**Files:**
- Read: `python/agent_service/planner_chain.py`
- Read: `python/agent_service/graph.py`
- Read: `python/agent_service/planner_v2.py`
- Read: `python/agent_service/router_v2.py`
- Read: `python/tests/test_planner_chain.py`
- Read: `python/tests/test_graph.py`

- [ ] **Step 1: Run focused Python tests**

Run:

```powershell
python -m pytest -q python\tests\test_planner_chain.py python\tests\test_planner_v2.py python\tests\test_task_planner.py python\tests\test_graph.py python\tests\test_agent_routing_integration.py
```

Expected:

```text
... passed
```

- [ ] **Step 2: Run graph compiler and validator tests**

Run:

```powershell
python -m pytest -q python\tests\test_graph_compiler.py python\tests\test_plan_validator.py python\tests\test_task_graph.py
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

- [ ] **Step 5: Confirm no Phase F/G scope leaked in**

Run:

```powershell
rg -n "ReAct|react_controller|tool_calls|ToolCall|mcp|durable|checkpoint|sandbox" python\agent_service\planner_chain.py python\agent_service\graph.py
```

Expected:

```text
```

No matches should appear except existing unrelated comments or import paths that predate Phase E. Do not implement ReAct, dynamic MCP planning, durable execution, or sandbox execution in Phase E.

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

Dispatch a final code review over the Phase E commit range. Use this prompt:

```text
Review Phase E Planner Chain implementation. Prioritize Router V2 structured route consumption, planner strategy selection, PlannerV2 compatibility, legacy task_planner compatibility, graph event/API compatibility, route and planner metadata privacy, validation through RunGraph, graph feedback preservation, and whether the implementation avoids ReAct, MCP dynamic planning, tool execution, durable execution, or sandbox scope.
```

Expected: reviewer returns no critical or important findings. Fix any critical or important finding before finishing.

---

## Acceptance Criteria

Phase E is complete when all statements are true:

- `python/agent_service/planner_chain.py` exists and is covered by `python/tests/test_planner_chain.py`.
- Planner Chain consumes Phase D structured route payloads through `StructuredRouteContext`.
- Planner Chain rejects non-task routes and missing inputs before planning.
- Document tasks still use `PlannerV2` and preserve the existing six-node document graph shape.
- Document-to-Markdown conversion requests with attachments still use the legacy `task_planner` parse/export graph instead of the six-node document report template.
- Non-document task routes use the existing `task_planner` compatibility strategy through Planner Chain.
- Planner Chain graph payloads validate with `RunGraph.model_validate()`.
- `graph.py` task graph creation routes through `PlannerChain`.
- `metadata.routeDecision` remains present and safe.
- `metadata.plannerChain` is present on task graphs and does not include raw local paths or attachment paths.
- Existing `node_graph.created`, `input.required`, `message.created`, and research choice event shapes remain compatible.
- No LLM dynamic planner, ReAct loop, MCP tool selection, tool execution, durable checkpointing, or sandbox execution is introduced.
- `.\scripts\verify-mvp.ps1` passes.

## Handoff Notes For Phase F

Phase F can add dynamic DAG proposal behind a feature flag by implementing another Planner Chain strategy. It should consume the same `PlannerChainRequest`, emit a `TaskGraph` or `RunGraph` payload that passes the same validation gates, and keep deterministic document and legacy strategies as fallbacks.
