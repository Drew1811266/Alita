# Agent Kernel Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic Planner V2, first-class model runtime contracts, plan validation, and final verification while preserving the existing document workflow and UI graph shape.

**Architecture:** Phase 2 builds directly on the completed Phase 1 kernel. It keeps deterministic document templates as the production path, moves model nodes behind a runtime adapter, validates internal task graphs before UI compilation, and adds final run verification after node-level verification. It does not add replan, network research, script execution, memory, MCP, parallel scheduling, or frontend schema changes.

**Tech Stack:** Python 3.10+, Pydantic, existing LangGraph router, existing `LlamaCppModelClient`, pytest, current `TaskGraph -> GraphCompiler -> RunGraph` contract.

---

## Current Baseline

Phase 1 is expected to be present on the implementation branch:

- `python/agent_service/goal_spec.py`
- `python/agent_service/context_manager.py`
- `python/agent_service/task_graph.py`
- `python/agent_service/graph_compiler.py`
- `python/agent_service/tool_resolver.py`
- `python/agent_service/verifier_v2.py`
- `python/agent_service/tool_execution.py` uses adapter-map dispatch
- full Python suite passes with `120 passed`

Phase 2 must preserve these current behaviors:

- Document messages with attachments still create the same frontend `NodeGraph`.
- Missing document attachments still emit `input.required`.
- Chat still goes through `answer_with_model` and streaming remains unchanged.
- `/agent/graph/run/stream` still executes the existing document graph sequentially.
- Disabled tool enforcement stays in graph execution, not message planning.
- Frontend and Rust schemas are not changed in this phase.

## Scope

### In Scope

- Extend `ModelBinding` into a real runtime contract with prompt template, output key, temperature, and max token defaults.
- Add prompt template lookup for known document model nodes.
- Add `ModelRuntime` for local model node execution.
- Make `DocumentFlowExecutor` call `ModelRuntime` for `content-organize` and `report-generate`.
- Add `PlanValidator` for internal `TaskGraph` correctness beyond cycle checks.
- Add `PlannerV2` deterministic template planner for document tasks.
- Route document graph planning through `PlannerV2`.
- Add `FinalVerifier` and integrate it into `run_graph_events` before `task.completed`.
- Add focused and full Python regression tests.

### Out Of Scope

- LLM planner generation for arbitrary tasks.
- Web research.
- Replanner / graph patch engine.
- Permission gate UI.
- Temporary script execution.
- Memory and skill library.
- MCP runtime.
- Parallel graph scheduling.
- Python/TypeScript/Rust schema generation.
- Frontend `App.tsx` decomposition.

## File Structure

### Create

- `python/agent_service/prompt_templates.py`
  - Stores known prompt templates for model bindings and renders model messages.
- `python/agent_service/model_runtime.py`
  - Executes model bindings through a local model client and returns `NodeOutput`.
- `python/agent_service/plan_validator.py`
  - Validates `TaskGraph` tool/model bindings, dependencies, operation availability, and permissions.
- `python/agent_service/planner_v2.py`
  - Produces deterministic `TaskGraph` objects from `GoalSpec` and optional context.
- `python/agent_service/final_verifier.py`
  - Verifies final graph-level outputs after all node outputs are produced.
- `python/tests/test_prompt_templates.py`
- `python/tests/test_model_runtime.py`
- `python/tests/test_plan_validator.py`
- `python/tests/test_planner_v2.py`
- `python/tests/test_final_verifier.py`

### Modify

- `python/agent_service/task_graph.py`
  - Extend `ModelBinding`; keep existing document node IDs and graph output stable.
- `python/agent_service/graph.py`
  - Use `PlannerV2` for document task graph creation.
- `python/agent_service/execution.py`
  - Inject/use `ModelRuntime` in `DocumentFlowExecutor`; call `FinalVerifier` before successful completion.
- `python/tests/test_task_graph.py`
  - Assert extended model binding fields for document model nodes.
- `python/tests/test_graph.py`
  - Assert UI graph shape remains unchanged after `PlannerV2` integration.
- `python/tests/test_execution.py`
  - Assert model runtime usage and final verifier failure path.

---

## Task 0: Baseline Verification

**Files:**
- Read only: `python/tests/test_goal_spec.py`
- Read only: `python/tests/test_context_manager.py`
- Read only: `python/tests/test_task_graph.py`
- Read only: `python/tests/test_graph_compiler.py`
- Read only: `python/tests/test_tool_resolver.py`
- Read only: `python/tests/test_graph.py`
- Read only: `python/tests/test_execution.py`
- Read only: `python/tests/test_tool_execution.py`
- Read only: `python/tests/test_result_verifier.py`
- Read only: `python/tests/test_verifier_v2.py`

- [ ] **Step 1: Confirm the implementation branch**

Run:

```powershell
git status --short --branch
```

Expected:

```text
## codex/agent-kernel-phase-2-plan
```

If the branch is different, stop and switch to the Phase 2 implementation branch that is based on Phase 1.

- [ ] **Step 2: Run Phase 1 focused regression**

Run:

```powershell
Push-Location python
python -m pytest tests/test_goal_spec.py tests/test_context_manager.py tests/test_task_graph.py tests/test_graph_compiler.py tests/test_tool_resolver.py tests/test_graph.py tests/test_execution.py tests/test_tool_execution.py tests/test_result_verifier.py tests/test_verifier_v2.py
Pop-Location
```

Expected: PASS. If this fails before Phase 2 changes, fix the baseline first or stop.

- [ ] **Step 3: Run full Python suite**

Run:

```powershell
Push-Location python
python -m pytest
Pop-Location
```

Expected: PASS.

---

## Task 1: Extend Model Binding And Prompt Templates

**Files:**
- Create: `python/agent_service/prompt_templates.py`
- Create: `python/tests/test_prompt_templates.py`
- Modify: `python/agent_service/task_graph.py`
- Modify: `python/tests/test_task_graph.py`
- Test: `python/tests/test_prompt_templates.py`
- Test: `python/tests/test_task_graph.py`

- [ ] **Step 1: Write failing prompt template tests**

Create `python/tests/test_prompt_templates.py`:

```python
from __future__ import annotations

import pytest

from agent_service.model_client import ChatMessage
from agent_service.prompt_templates import PromptTemplateError, render_prompt_template


def test_render_content_organizer_prompt_includes_document_text() -> None:
    messages = render_prompt_template(
        "document.content_organizer.zh.v1",
        {"text": "document body"},
    )

    assert messages[0].role == "system"
    assert "document body" in messages[1].content
    assert messages[1] == ChatMessage(role="user", content="document body")


def test_render_report_writer_prompt_prefers_text_input() -> None:
    messages = render_prompt_template(
        "document.report_writer.zh.v1",
        {"text": "document body", "outline": "outline"},
    )

    assert messages[0].role == "system"
    assert messages[1].content == "document body"


def test_render_prompt_template_rejects_unknown_template() -> None:
    with pytest.raises(PromptTemplateError, match="unknown prompt template"):
        render_prompt_template("missing.template", {"text": "body"})
```

- [ ] **Step 2: Add failing TaskGraph binding assertions**

Append to `test_build_document_task_graph_preserves_existing_node_ids` in `python/tests/test_task_graph.py`:

```python
    content_binding = graph.node_by_id("content-organize").model_binding
    assert content_binding is not None
    assert content_binding.prompt_template == "document.content_organizer.zh.v1"
    assert content_binding.output_key == "outline"
    assert content_binding.temperature == 0.2
    assert content_binding.max_tokens == 1024

    report_binding = graph.node_by_id("report-generate").model_binding
    assert report_binding is not None
    assert report_binding.prompt_template == "document.report_writer.zh.v1"
    assert report_binding.output_key == "report"
    assert report_binding.temperature == 0.2
    assert report_binding.max_tokens == 1536
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_prompt_templates.py tests/test_task_graph.py -v
Pop-Location
```

Expected: FAIL because `agent_service.prompt_templates` does not exist and `ModelBinding` lacks new fields.

- [ ] **Step 4: Implement prompt templates**

Create `python/agent_service/prompt_templates.py`:

```python
from __future__ import annotations

from agent_service.model_client import ChatMessage


class PromptTemplateError(ValueError):
    pass


_SYSTEM_PROMPTS = {
    "document.content_organizer.zh.v1": (
        "Organize the user document into concise structured Chinese key points."
    ),
    "document.report_writer.zh.v1": (
        "Write a concise Chinese report from the user document. "
        "Do not claim actions that were not executed."
    ),
}


def render_prompt_template(
    template_id: str,
    values: dict[str, str],
) -> list[ChatMessage]:
    try:
        system_prompt = _SYSTEM_PROMPTS[template_id]
    except KeyError as exc:
        raise PromptTemplateError(f"unknown prompt template: {template_id}") from exc

    user_content = values.get("text", "").strip()
    if not user_content:
        user_content = values.get("report", "").strip() or values.get("outline", "").strip()

    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_content),
    ]
```

- [ ] **Step 5: Extend `ModelBinding`**

Modify `python/agent_service/task_graph.py`:

```python
class ModelBinding(BaseModel):
    model_ref: str
    purpose: str
    runtime: str = "llm"
    prompt_template: str
    output_key: str
    temperature: float = 0.2
    max_tokens: int = 1024
```

Update `content-organize` model binding:

```python
                model_binding=ModelBinding(
                    model_ref="local.content_organizer",
                    purpose="organize_document_content",
                    prompt_template="document.content_organizer.zh.v1",
                    output_key="outline",
                    temperature=0.2,
                    max_tokens=1024,
                ),
```

Update `report-generate` model binding:

```python
                model_binding=ModelBinding(
                    model_ref="local.report_writer",
                    purpose="write_document_report",
                    prompt_template="document.report_writer.zh.v1",
                    output_key="report",
                    temperature=0.2,
                    max_tokens=1536,
                ),
```

- [ ] **Step 6: Run tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_prompt_templates.py tests/test_task_graph.py tests/test_graph_compiler.py -v
Pop-Location
```

Expected: PASS. `tests/test_graph_compiler.py` must continue to pass because `model_ref` did not change.

- [ ] **Step 7: Commit**

Run:

```powershell
git add python/agent_service/prompt_templates.py python/agent_service/task_graph.py python/tests/test_prompt_templates.py python/tests/test_task_graph.py
git commit -m "feat: add model prompt binding contract"
```

Expected: commit succeeds.

---

## Task 2: Model Runtime

**Files:**
- Create: `python/agent_service/model_runtime.py`
- Create: `python/tests/test_model_runtime.py`
- Test: `python/tests/test_model_runtime.py`

- [ ] **Step 1: Write failing model runtime tests**

Create `python/tests/test_model_runtime.py`:

```python
from __future__ import annotations

import pytest

from agent_service.model_client import ChatMessage
from agent_service.model_runtime import (
    ModelRuntime,
    ModelRuntimeError,
    SupportedModelRegistry,
)
from agent_service.node_output import NodeOutput
from agent_service.task_graph import ModelBinding


class FakeModelClient:
    def __init__(self, reply: str = "model output") -> None:
        self.reply = reply
        self.calls: list[dict] = []

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.reply


def test_model_runtime_runs_content_organizer_binding() -> None:
    client = FakeModelClient("outline text")
    runtime = ModelRuntime(model_client=client)
    binding = ModelBinding(
        model_ref="local.content_organizer",
        purpose="organize_document_content",
        prompt_template="document.content_organizer.zh.v1",
        output_key="outline",
        max_tokens=1024,
    )

    output = runtime.run(
        binding,
        inputs={"document-parse": NodeOutput(values={"text": "document body"})},
    )

    assert output == NodeOutput(values={"outline": "outline text"})
    assert client.calls[0]["messages"][1].content == "document body"
    assert client.calls[0]["temperature"] == 0.2
    assert client.calls[0]["max_tokens"] == 1024


def test_model_runtime_runs_report_writer_with_custom_token_limit() -> None:
    client = FakeModelClient("report text")
    runtime = ModelRuntime(model_client=client)
    binding = ModelBinding(
        model_ref="local.report_writer",
        purpose="write_document_report",
        prompt_template="document.report_writer.zh.v1",
        output_key="report",
        max_tokens=1536,
    )

    output = runtime.run(
        binding,
        inputs={"document-parse": NodeOutput(values={"text": "document body"})},
    )

    assert output.values == {"report": "report text"}
    assert client.calls[0]["max_tokens"] == 1536


def test_model_runtime_rejects_unsupported_model_ref() -> None:
    runtime = ModelRuntime(model_client=FakeModelClient())
    binding = ModelBinding(
        model_ref="remote.unknown",
        purpose="unknown",
        prompt_template="document.report_writer.zh.v1",
        output_key="report",
    )

    with pytest.raises(ModelRuntimeError, match="unsupported model ref"):
        runtime.run(binding, inputs={})


def test_supported_model_registry_knows_document_models() -> None:
    registry = SupportedModelRegistry.default()

    assert registry.supports("local.content_organizer")
    assert registry.supports("local.report_writer")
    assert not registry.supports("remote.unknown")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_model_runtime.py -v
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.model_runtime'`.

- [ ] **Step 3: Implement model runtime**

Create `python/agent_service/model_runtime.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_service.model_client import ChatMessage, LlamaCppModelClient
from agent_service.node_output import NodeOutput
from agent_service.prompt_templates import render_prompt_template
from agent_service.task_graph import ModelBinding


class ModelClient(Protocol):
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        ...


class ModelRuntimeError(ValueError):
    pass


@dataclass(frozen=True)
class SupportedModelRegistry:
    model_refs: frozenset[str]

    @classmethod
    def default(cls) -> "SupportedModelRegistry":
        return cls(
            model_refs=frozenset(
                {
                    "local.content_organizer",
                    "local.report_writer",
                }
            )
        )

    def supports(self, model_ref: str) -> bool:
        return model_ref in self.model_refs


class ModelRuntime:
    def __init__(
        self,
        *,
        model_client: ModelClient | None = None,
        supported_models: SupportedModelRegistry | None = None,
    ) -> None:
        self.model_client = model_client or LlamaCppModelClient()
        self.supported_models = supported_models or SupportedModelRegistry.default()

    def run(
        self,
        binding: ModelBinding,
        *,
        inputs: dict[str, NodeOutput],
    ) -> NodeOutput:
        if not self.supported_models.supports(binding.model_ref):
            raise ModelRuntimeError(f"unsupported model ref: {binding.model_ref}")

        values = _flatten_input_values(inputs)
        messages = render_prompt_template(binding.prompt_template, values)
        content = self.model_client.chat(
            messages,
            temperature=binding.temperature,
            max_tokens=binding.max_tokens,
        )
        return NodeOutput(values={binding.output_key: content})


def _flatten_input_values(inputs: dict[str, NodeOutput]) -> dict[str, str]:
    values: dict[str, str] = {}
    for output in inputs.values():
        for key, value in output.values.items():
            values.setdefault(key, value)
    return values
```

- [ ] **Step 4: Run model runtime tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_model_runtime.py tests/test_prompt_templates.py -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/model_runtime.py python/tests/test_model_runtime.py
git commit -m "feat: add model runtime adapter"
```

Expected: commit succeeds.

---

## Task 3: Wire DocumentFlowExecutor To ModelRuntime

**Files:**
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_execution.py`
- Test: `python/tests/test_execution.py`

- [ ] **Step 1: Add failing execution tests for runtime usage**

Append to `python/tests/test_execution.py`:

```python
from agent_service.execution import DocumentFlowExecutor, NodeOutput, run_graph_events


class RecordingModelRuntime:
    def __init__(self) -> None:
        self.calls = []

    def run(self, binding, *, inputs):
        self.calls.append((binding, inputs))
        if binding.model_ref == "local.content_organizer":
            return NodeOutput(values={"outline": "runtime outline"})
        if binding.model_ref == "local.report_writer":
            return NodeOutput(values={"report": "runtime report"})
        raise AssertionError(binding.model_ref)


def test_document_flow_model_nodes_use_model_runtime(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("document text", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)
    runtime = RecordingModelRuntime()
    executor = DocumentFlowExecutor(request, model_runtime=runtime)

    parse_output = NodeOutput(values={"text": "document text"})

    outline_output = executor.run(
        "content-organize",
        {"document-parse": parse_output},
    )
    report_output = executor.run(
        "report-generate",
        {"document-parse": parse_output},
    )

    assert outline_output.values == {"outline": "runtime outline"}
    assert report_output.values == {"report": "runtime report"}
    assert [call[0].model_ref for call in runtime.calls] == [
        "local.content_organizer",
        "local.report_writer",
    ]
```

- [ ] **Step 2: Run targeted test and verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_execution.py::test_document_flow_model_nodes_use_model_runtime -v
Pop-Location
```

Expected: FAIL because `DocumentFlowExecutor.__init__()` does not accept `model_runtime`.

- [ ] **Step 3: Modify `DocumentFlowExecutor` constructor**

Modify `python/agent_service/execution.py` imports:

```python
from agent_service.model_runtime import ModelRuntime
from agent_service.task_graph import build_document_task_graph
from agent_service.goal_spec import GoalSpec
```

Modify constructor:

```python
    def __init__(
        self,
        request: RunGraphRequest,
        *,
        model_client: ModelClient | None = None,
        model_runtime: ModelRuntime | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self.request = request
        self.model_client = model_client or LlamaCppModelClient()
        self.model_runtime = model_runtime or ModelRuntime(model_client=self.model_client)
        self.tool_executor = tool_executor or ToolExecutor()
        self.project_dir = Path(request.project_path).parent
        self.artifact_dir = self.project_dir / "artifacts"
        self.task_graph = build_document_task_graph(
            request.task_id,
            GoalSpec(
                goal="Run document graph",
                task_type="document_processing",
                deliverable="pdf_report",
                risk_level="local_write",
                permissions_required=["read_attachment", "write_project_artifact"],
            ),
        )
```

- [ ] **Step 4: Replace direct model calls**

Replace `content-organize` branch:

```python
        if node_id == "content-organize":
            node = self.task_graph.node_by_id("content-organize")
            if node.model_binding is None:
                raise ValueError("content-organize is missing model binding")
            return self.model_runtime.run(node.model_binding, inputs=inputs)
```

Replace `report-generate` branch:

```python
        if node_id == "report-generate":
            node = self.task_graph.node_by_id("report-generate")
            if node.model_binding is None:
                raise ValueError("report-generate is missing model binding")
            return self.model_runtime.run(node.model_binding, inputs=inputs)
```

- [ ] **Step 5: Run execution tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_execution.py tests/test_model_runtime.py -v
Pop-Location
```

Expected: PASS. Existing fake `model_client` tests must still pass because default `ModelRuntime` uses the provided `model_client`.

- [ ] **Step 6: Commit**

Run:

```powershell
git add python/agent_service/execution.py python/tests/test_execution.py
git commit -m "refactor: execute model nodes through model runtime"
```

Expected: commit succeeds.

---

## Task 4: Plan Validator

**Files:**
- Create: `python/agent_service/plan_validator.py`
- Create: `python/tests/test_plan_validator.py`
- Test: `python/tests/test_plan_validator.py`

- [ ] **Step 1: Write failing validator tests**

Create `python/tests/test_plan_validator.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.goal_spec import GoalSpec
from agent_service.model_runtime import SupportedModelRegistry
from agent_service.plan_validator import PlanValidationError, validate_plan
from agent_service.task_graph import ToolBinding, build_document_task_graph
from agent_service.tool_registry import ToolRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_PACKAGES_ROOT = PROJECT_ROOT / "tool-packages"


def _goal_spec() -> GoalSpec:
    return GoalSpec(
        goal="summarize document",
        task_type="document_processing",
        deliverable="pdf_report",
        risk_level="local_write",
        permissions_required=["read_attachment", "write_project_artifact"],
    )


def test_validate_plan_accepts_document_task_graph() -> None:
    graph = build_document_task_graph("task-doc", _goal_spec())

    validate_plan(
        graph,
        tool_registry=ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT),
        model_registry=SupportedModelRegistry.default(),
    )


def test_validate_plan_rejects_unknown_tool_binding() -> None:
    graph = build_document_task_graph("task-doc", _goal_spec())
    graph.node_by_id("document-parse").tool_binding = ToolBinding(
        tool_id="document.missing",
        operation="run",
    )

    with pytest.raises(PlanValidationError, match="document.missing"):
        validate_plan(
            graph,
            tool_registry=ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT),
            model_registry=SupportedModelRegistry.default(),
        )


def test_validate_plan_rejects_unsupported_model_binding() -> None:
    graph = build_document_task_graph("task-doc", _goal_spec())
    model_binding = graph.node_by_id("content-organize").model_binding
    assert model_binding is not None
    model_binding.model_ref = "remote.unknown"

    with pytest.raises(PlanValidationError, match="remote.unknown"):
        validate_plan(
            graph,
            tool_registry=ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT),
            model_registry=SupportedModelRegistry.default(),
        )


def test_validate_plan_rejects_missing_required_binding() -> None:
    graph = build_document_task_graph("task-doc", _goal_spec())
    graph.node_by_id("document-parse").tool_binding = None

    with pytest.raises(PlanValidationError, match="document-parse.*tool_binding"):
        validate_plan(
            graph,
            tool_registry=ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT),
            model_registry=SupportedModelRegistry.default(),
        )
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_plan_validator.py -v
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.plan_validator'`.

- [ ] **Step 3: Implement plan validator**

Create `python/agent_service/plan_validator.py`:

```python
from __future__ import annotations

from agent_service.model_runtime import SupportedModelRegistry
from agent_service.task_graph import TaskGraph, validate_task_graph
from agent_service.tool_registry import ToolRegistry


class PlanValidationError(ValueError):
    pass


def validate_plan(
    task_graph: TaskGraph,
    *,
    tool_registry: ToolRegistry,
    model_registry: SupportedModelRegistry,
) -> None:
    try:
        validate_task_graph(task_graph)
        _validate_bindings(
            task_graph,
            tool_registry=tool_registry,
            model_registry=model_registry,
        )
    except Exception as exc:
        if isinstance(exc, PlanValidationError):
            raise
        raise PlanValidationError(str(exc)) from exc


def _validate_bindings(
    task_graph: TaskGraph,
    *,
    tool_registry: ToolRegistry,
    model_registry: SupportedModelRegistry,
) -> None:
    for node in task_graph.nodes:
        if node.kind in {"input", "fixed_tool"}:
            if node.tool_binding is None:
                raise PlanValidationError(f"{node.node_id} is missing tool_binding")
            try:
                tool_registry.get(node.tool_binding.tool_id)
            except KeyError as exc:
                raise PlanValidationError(str(exc)) from exc
            if not tool_registry.has_operation(
                node.tool_binding.tool_id,
                node.tool_binding.operation,
            ):
                raise PlanValidationError(
                    f"{node.node_id} uses unsupported operation "
                    f"{node.tool_binding.tool_id}:{node.tool_binding.operation}"
                )

        if node.kind == "model":
            if node.model_binding is None:
                raise PlanValidationError(f"{node.node_id} is missing model_binding")
            if not model_registry.supports(node.model_binding.model_ref):
                raise PlanValidationError(
                    f"{node.node_id} uses unsupported model ref "
                    f"{node.model_binding.model_ref}"
                )
```

- [ ] **Step 4: Run validator tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_plan_validator.py tests/test_task_graph.py -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/plan_validator.py python/tests/test_plan_validator.py
git commit -m "feat: add task graph plan validator"
```

Expected: commit succeeds.

---

## Task 5: Planner V2 Deterministic Template Planner

**Files:**
- Create: `python/agent_service/planner_v2.py`
- Create: `python/tests/test_planner_v2.py`
- Test: `python/tests/test_planner_v2.py`

- [ ] **Step 1: Write failing planner tests**

Create `python/tests/test_planner_v2.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.context_manager import build_context_bundle
from agent_service.goal_spec import parse_goal_spec
from agent_service.planner_v2 import PlannerV2, PlannerV2Error
from agent_service.schemas import Attachment, UserMessage
from agent_service.tool_registry import ToolRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_PACKAGES_ROOT = PROJECT_ROOT / "tool-packages"


def _document_message() -> UserMessage:
    return UserMessage(
        task_id="task-doc",
        content="summarize as a PDF report",
        attachments=[
            Attachment(
                attachment_id="a1",
                name="input.md",
                path="workspace/inputs/input.md",
                size_bytes=100,
                mime_type="text/markdown",
            )
        ],
    )


def test_planner_v2_builds_valid_document_task_graph() -> None:
    message = _document_message()
    goal_spec = parse_goal_spec(message)
    registry = ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)
    context = build_context_bundle(
        message=message,
        goal_spec=goal_spec,
        project_path="workspace/project.alita",
        tool_registry=registry,
    )

    result = PlannerV2(tool_registry=registry).plan(
        task_id=message.task_id,
        goal_spec=goal_spec,
        context=context,
    )

    assert result.planner == "template.document.v1"
    assert result.task_graph.graph_id == "task-doc-graph"
    assert result.task_graph.node_by_id("document-parse").tool_binding is not None
    assert result.validation_warnings == []


def test_planner_v2_rejects_missing_document_input() -> None:
    message = UserMessage(task_id="task-missing", content="process this document")
    goal_spec = parse_goal_spec(message)
    registry = ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)
    context = build_context_bundle(
        message=message,
        goal_spec=goal_spec,
        project_path="workspace/project.alita",
        tool_registry=registry,
    )

    with pytest.raises(PlannerV2Error, match="missing inputs"):
        PlannerV2(tool_registry=registry).plan(
            task_id=message.task_id,
            goal_spec=goal_spec,
            context=context,
        )


def test_planner_v2_rejects_unsupported_task_type() -> None:
    message = UserMessage(task_id="task-chat", content="hello")
    goal_spec = parse_goal_spec(message)
    registry = ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)
    context = build_context_bundle(
        message=message,
        goal_spec=goal_spec,
        project_path="workspace/project.alita",
        tool_registry=registry,
    )

    with pytest.raises(PlannerV2Error, match="unsupported task type"):
        PlannerV2(tool_registry=registry).plan(
            task_id=message.task_id,
            goal_spec=goal_spec,
            context=context,
        )
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_planner_v2.py -v
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.planner_v2'`.

- [ ] **Step 3: Implement Planner V2**

Create `python/agent_service/planner_v2.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field

from agent_service.context_manager import ContextBundle
from agent_service.goal_spec import GoalSpec
from agent_service.model_runtime import SupportedModelRegistry
from agent_service.plan_validator import validate_plan
from agent_service.task_graph import TaskGraph, build_document_task_graph
from agent_service.tool_registry import ToolRegistry


class PlannerV2Error(ValueError):
    pass


class PlanResult(BaseModel):
    planner: str
    task_graph: TaskGraph
    validation_warnings: list[str] = Field(default_factory=list)


class PlannerV2:
    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        model_registry: SupportedModelRegistry | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.model_registry = model_registry or SupportedModelRegistry.default()

    def plan(
        self,
        *,
        task_id: str,
        goal_spec: GoalSpec,
        context: ContextBundle,
    ) -> PlanResult:
        if goal_spec.missing_inputs:
            missing = ", ".join(goal_spec.missing_inputs)
            raise PlannerV2Error(f"missing inputs: {missing}")

        if goal_spec.task_type != "document_processing":
            raise PlannerV2Error(f"unsupported task type: {goal_spec.task_type}")

        task_graph = build_document_task_graph(task_id, goal_spec)
        validate_plan(
            task_graph,
            tool_registry=self.tool_registry,
            model_registry=self.model_registry,
        )
        return PlanResult(
            planner="template.document.v1",
            task_graph=task_graph,
            validation_warnings=[],
        )
```

- [ ] **Step 4: Run planner tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_planner_v2.py tests/test_plan_validator.py -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/planner_v2.py python/tests/test_planner_v2.py
git commit -m "feat: add deterministic planner v2"
```

Expected: commit succeeds.

---

## Task 6: Route Graph Planning Through Planner V2

**Files:**
- Modify: `python/agent_service/graph.py`
- Modify: `python/tests/test_graph.py`
- Test: `python/tests/test_graph.py`

- [ ] **Step 1: Add graph integration assertions**

In `python/tests/test_graph.py`, extend `test_attachment_generates_node_graph_for_document_task` with:

```python
    assert graph["nodes"][2]["modelRef"] == "local-content-organizer"
    assert graph["nodes"][3]["modelRef"] == "local-report-writer"
    assert set(graph) == {"graphId", "nodes", "edges"}
```

Add this test:

```python
def test_document_graph_planning_still_validates_frontend_shape() -> None:
    events = run_agent(
        UserMessage(
            task_id="task-planner-v2",
            content="summarize as PDF",
            attachments=[
                Attachment(
                    attachment_id="a1",
                    name="input.md",
                    path="workspace/inputs/input.md",
                    size_bytes=100,
                    mime_type="text/markdown",
                )
            ],
        )
    )

    graph = events[0].payload["graph"]

    assert graph["graphId"] == "task-planner-v2-graph"
    assert [edge["id"] for edge in graph["edges"]] == [
        "document-input-document-parse",
        "document-parse-content-organize",
        "document-parse-report-generate",
        "content-organize-typst-export",
        "report-generate-typst-export",
        "typst-export-file-export",
    ]
```

- [ ] **Step 2: Run tests before integration**

Run:

```powershell
Push-Location python
python -m pytest tests/test_graph.py tests/test_planner_v2.py -v
Pop-Location
```

Expected: PASS before integration because behavior is still equivalent. Continue with integration anyway.

- [ ] **Step 3: Update `graph.py` imports**

Modify `python/agent_service/graph.py`:

```python
from agent_service.context_manager import build_context_bundle
from agent_service.planner_v2 import PlannerV2
from agent_service.tool_execution import default_tool_packages_root
from agent_service.tool_registry import ToolRegistry
```

Remove direct `build_document_task_graph` import if it is no longer used.

- [ ] **Step 4: Replace `_create_document_graph`**

Replace `_create_document_graph`:

```python
def _create_document_graph(task_id: str, goal_spec: GoalSpec, message: UserMessage) -> dict:
    tool_registry = ToolRegistry.from_packages_root(default_tool_packages_root())
    context = build_context_bundle(
        message=message,
        goal_spec=goal_spec,
        project_path="project.alita",
        tool_registry=tool_registry,
    )
    plan = PlannerV2(tool_registry=tool_registry).plan(
        task_id=task_id,
        goal_spec=goal_spec,
        context=context,
    )
    return compile_task_graph_to_node_graph(plan.task_graph)
```

Modify `plan_node_graph`:

```python
def plan_node_graph(state: AgentState) -> AgentState:
    return {
        **state,
        "events": [
            AgentEvent(
                type="node_graph.created",
                payload={
                    "graph": _create_document_graph(
                        state["message"].task_id,
                        state["goal_spec"],
                        state["message"],
                    ),
                },
            )
        ],
    }
```

Note: `project_path="project.alita"` is a temporary planning placeholder because `/agent/message` does not receive the project path today. It only affects context artifact directory metadata, not current graph output. Do not expose this in event payloads.

- [ ] **Step 5: Run graph tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_graph.py tests/test_graph_compiler.py tests/test_planner_v2.py -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```powershell
git add python/agent_service/graph.py python/tests/test_graph.py
git commit -m "refactor: plan document graphs through planner v2"
```

Expected: commit succeeds.

---

## Task 7: Final Verifier And Execution Integration

**Files:**
- Create: `python/agent_service/final_verifier.py`
- Create: `python/tests/test_final_verifier.py`
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_execution.py`
- Test: `python/tests/test_final_verifier.py`
- Test: `python/tests/test_execution.py`

- [ ] **Step 1: Write failing final verifier tests**

Create `python/tests/test_final_verifier.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.final_verifier import FinalVerifier
from agent_service.harness_errors import HarnessError
from agent_service.node_output import NodeOutput
from agent_service.schemas import GraphEdge, GraphNode, RunGraph, RunGraphRequest


def _request(tmp_path: Path) -> RunGraphRequest:
    graph = RunGraph(
        graphId="graph-final",
        nodes=[
            GraphNode(
                nodeId="file-export",
                nodeType="output",
                displayName="Export",
                status="waiting",
                dependencies=[],
                summary="Export final artifact.",
                createdBy="agent",
                position={"x": 0, "y": 0},
            )
        ],
        edges=[],
    )
    return RunGraphRequest(
        task_id="task-final",
        project_path=str(tmp_path / "project.alita"),
        graph=graph,
    )


def test_final_verifier_accepts_existing_output_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "report.pdf"
    artifact.write_bytes(b"%PDF")
    request = _request(tmp_path)

    FinalVerifier().verify(
        request,
        outputs={
            "file-export": NodeOutput(
                artifacts=[str(artifact)],
                values={"artifact": str(artifact)},
            )
        },
    )


def test_final_verifier_rejects_missing_output_node(tmp_path: Path) -> None:
    request = _request(tmp_path)

    with pytest.raises(HarnessError) as exc_info:
        FinalVerifier().verify(request, outputs={})

    assert exc_info.value.code == "missing_final_output"
    assert "file-export" in exc_info.value.message


def test_final_verifier_rejects_missing_output_artifact(tmp_path: Path) -> None:
    request = _request(tmp_path)

    with pytest.raises(HarnessError) as exc_info:
        FinalVerifier().verify(
            request,
            outputs={
                "file-export": NodeOutput(
                    artifacts=[str(tmp_path / "missing.pdf")],
                    values={"artifact": str(tmp_path / "missing.pdf")},
                )
            },
        )

    assert exc_info.value.code == "missing_artifact"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_final_verifier.py -v
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.final_verifier'`.

- [ ] **Step 3: Implement final verifier**

Create `python/agent_service/final_verifier.py`:

```python
from __future__ import annotations

from pathlib import Path

from agent_service.harness_errors import HarnessError
from agent_service.node_output import NodeOutput
from agent_service.schemas import RunGraphRequest


class FinalVerifier:
    def verify(
        self,
        request: RunGraphRequest,
        *,
        outputs: dict[str, NodeOutput],
    ) -> None:
        output_nodes = [
            node for node in request.graph.nodes if node.nodeType == "output"
        ]
        for node in output_nodes:
            output = outputs.get(node.nodeId)
            if output is None:
                raise HarnessError(
                    "missing_final_output",
                    f"missing final output for node: {node.nodeId}",
                )
            artifact_value = output.values.get("artifact", "")
            if artifact_value and Path(artifact_value) not in {
                Path(artifact) for artifact in output.artifacts
            }:
                raise HarnessError(
                    "missing_artifact",
                    f"final artifact is not listed: {artifact_value}",
                )
            for artifact in output.artifacts:
                if not Path(artifact).is_file():
                    raise HarnessError(
                        "missing_artifact",
                        f"artifact does not exist: {artifact}",
                    )
```

- [ ] **Step 4: Add execution integration test**

Add to `python/tests/test_execution.py`:

```python
from agent_service.harness_errors import HarnessError


class RejectingFinalVerifier:
    def verify(self, request, *, outputs):
        raise HarnessError("missing_final_output", "missing final output for node: file-export")


def test_execution_fails_when_final_verifier_rejects_output(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("document text", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)

    events = list(
        run_graph_events(
            request,
            executor=FakeNodeExecutor(),
            final_verifier=RejectingFinalVerifier(),
        )
    )

    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "missing_final_output"
```

- [ ] **Step 5: Wire final verifier into execution**

Modify imports in `python/agent_service/execution.py`:

```python
from agent_service.final_verifier import FinalVerifier
```

Modify `run_graph_events` signature:

```python
    final_verifier: FinalVerifier | None = None,
) -> Iterator[AgentEvent]:
```

After the node execution loop succeeds, before writing completed run status:

```python
        try:
            (final_verifier or FinalVerifier()).verify(request, outputs=outputs)
        except Exception as error:
            completed_at = _now_iso()
            payload = harness_error_payload(error)
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
                type="task.failed",
                payload={
                    "taskId": request.task_id,
                    "runId": request.run_id,
                    **payload,
                },
            )
            return
```

Then keep the existing successful `task.completed` path unchanged.

- [ ] **Step 6: Run final verifier tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_final_verifier.py tests/test_execution.py -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```powershell
git add python/agent_service/final_verifier.py python/agent_service/execution.py python/tests/test_final_verifier.py python/tests/test_execution.py
git commit -m "feat: verify final graph outputs"
```

Expected: commit succeeds.

---

## Task 8: Phase 2 Regression

**Files:**
- Read only: `python/tests/test_prompt_templates.py`
- Read only: `python/tests/test_model_runtime.py`
- Read only: `python/tests/test_plan_validator.py`
- Read only: `python/tests/test_planner_v2.py`
- Read only: `python/tests/test_final_verifier.py`
- Read only: `python/tests/test_goal_spec.py`
- Read only: `python/tests/test_context_manager.py`
- Read only: `python/tests/test_task_graph.py`
- Read only: `python/tests/test_graph_compiler.py`
- Read only: `python/tests/test_tool_resolver.py`
- Read only: `python/tests/test_graph.py`
- Read only: `python/tests/test_execution.py`
- Read only: `python/tests/test_tool_execution.py`
- Read only: `python/tests/test_result_verifier.py`
- Read only: `python/tests/test_verifier_v2.py`

- [ ] **Step 1: Run all Agent Kernel Phase 2 focused tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_prompt_templates.py tests/test_model_runtime.py tests/test_plan_validator.py tests/test_planner_v2.py tests/test_final_verifier.py tests/test_goal_spec.py tests/test_context_manager.py tests/test_task_graph.py tests/test_graph_compiler.py tests/test_tool_resolver.py tests/test_graph.py tests/test_execution.py tests/test_tool_execution.py tests/test_result_verifier.py tests/test_verifier_v2.py
Pop-Location
```

Expected: PASS.

- [ ] **Step 2: Run full Python suite**

Run:

```powershell
Push-Location python
python -m pytest
Pop-Location
```

Expected: PASS.

- [ ] **Step 3: Inspect final status**

Run:

```powershell
git status --short --branch
```

Expected: clean Phase 2 implementation branch. Do not include unrelated frontend artifact-preview changes from the main workspace.

---

## Self-Review Checklist

- Phase 2 does not change frontend or Rust schemas.
- Phase 2 does not add web research, script execution, memory, MCP, replan, permission gates, or parallel scheduling.
- Model nodes execute through `ModelRuntime`.
- Prompt templates are explicit and testable.
- `PlannerV2` is deterministic and template-backed.
- Plan validation runs before UI compilation.
- Final verification runs before `task.completed`.
- Existing document graph node IDs and UI shape remain stable.
- Existing `HarnessError` codes for node verification and tool execution remain stable.
- Full Python suite passes before completion.
