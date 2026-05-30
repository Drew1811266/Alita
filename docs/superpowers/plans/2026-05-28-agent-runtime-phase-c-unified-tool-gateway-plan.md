# Agent Runtime Phase C Unified Tool Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move executable fixed-tool nodes onto `UnifiedToolGateway` so internal document tools use the same invocation/result path as future MCP tools, while preserving public endpoint schemas and event payloads.

**Architecture:** Keep `ToolExecutor` as the low-level implementation used by `InternalToolProvider`, but remove direct `ToolExecutor.run()` calls from graph execution. `run_graph_events()` should construct or accept a `UnifiedToolGateway`, pass the Phase B `AgentRunState` into executors, and let fixed-tool nodes build `UnifiedToolInvocation` records with run, task, node, project, permission, and allowed-root context. Phase C does not add model-driven tool choice, ReAct loops, external script execution, or MCP dynamic planning; it only makes the current fixed-tool runtime path uniform.

**Tech Stack:** Python 3.12, FastAPI sidecar, Pydantic schemas, pytest, `UnifiedToolGateway`, `InternalToolProvider`, `ToolExecutor`, `AgentRunState`, existing graph execution events.

---

## Current Baseline

Phase B is already complete on branch `codex/agent-runtime-phase-a-security-hygiene`:

- `python/agent_service/agent_run_state.py` defines `AgentRunState`.
- `python/agent_service/app.py` builds `AgentRunState` for message and graph stream endpoints.
- `python/agent_service/execution.py` accepts `run_graph_events(..., run_state: AgentRunState | None = None)`.
- `python/agent_service/tool_gateway.py` defines `UnifiedToolGateway`.
- `python/agent_service/tool_providers/internal.py` adapts internal manifests to unified tool definitions and calls `ToolExecutor`.
- `python/agent_service/execution.py` still passes `tool_executor` into `DocumentFlowExecutor`, and `DocumentFlowExecutor` still calls `ToolExecutor.run()` directly for `document.markitdown_convert` and `document.typst_compile`.
- `PlannedTaskExecutor` still raises `unsupported_runtime` for non-document fixed-tool nodes, even when the tool exists in the internal provider catalog.

## Non-Goals

- Do not change frontend event shapes.
- Do not change FastAPI request or response schemas.
- Do not implement dynamic LLM tool calling.
- Do not execute temporary scripts.
- Do not convert research pseudo-tools (`web.search.parallel`, `web.fetch.sources`) into unified providers yet.
- Do not make MCP tools dynamically selectable by the planner yet.
- Do not remove `ToolExecutor`; after Phase C it remains the internal provider implementation detail.

## Files

- Modify: `python/agent_service/tool_gateway.py`
  - Add the default internal gateway factory.
- Modify: `python/agent_service/execution.py`
  - Accept and pass `UnifiedToolGateway`.
  - Convert fixed-tool node calls into `UnifiedToolInvocation`.
  - Convert `UnifiedToolResult` into `NodeOutput` or `HarnessError`.
- Modify: `python/agent_service/permission_gate.py`
  - Resolve `internal:` tool ids before manifest permission lookup.
- Create: `python/tests/helpers/__init__.py`
  - Make shared test helpers importable.
- Create: `python/tests/helpers/tool_gateway.py`
  - Shared recording gateway for execution tests.
- Create: `python/tests/test_execution_gateway_integration.py`
  - Gateway-level graph execution integration tests.
- Modify: `python/tests/test_tool_gateway.py`
  - Default factory tests.
- Modify: `python/tests/test_execution.py`
  - Compatibility/regression updates for existing `tool_executor` injection.
- Modify: `python/tests/test_permission_gate.py`
  - Prefixed internal tool reference permission coverage.

## Design Contracts

### Default Gateway Factory

`tool_gateway.py` should expose:

```python
def default_unified_tool_gateway(
    *,
    packages_root: Path | None = None,
    internal_executor: ToolExecutor | None = None,
) -> UnifiedToolGateway:
    registry = ToolRegistry.from_packages_root(
        packages_root or default_tool_packages_root()
    )
    return UnifiedToolGateway(
        providers=[
            InternalToolProvider(
                registry=registry,
                executor=internal_executor,
            )
        ]
    )
```

The optional `internal_executor` is only a compatibility injection point. Production graph execution should pass a gateway, not a raw executor.

### Unified Invocation Shape

Every execution-time tool call created by `execution.py` should include:

```python
UnifiedToolInvocation(
    invocation_id=f"{run_state.run_id or request.run_id}-{node.nodeId}-{operation}",
    run_id=run_state.run_id or request.run_id,
    task_id=run_state.task_id,
    node_id=node.nodeId,
    tool_id=normalize_tool_id(node.toolRef or tool_id),
    arguments={"operation": operation, **arguments},
    project_path=run_state.project_path or request.project_path,
    allowed_roots=allowed_roots,
    requested_permissions=required_permissions,
    model_session_id=run_state.message.model_session_id,
)
```

### Result Conversion Rule

Convert gateway results into node outputs with one helper:

```python
def _node_output_from_unified_result(result: UnifiedToolResult) -> NodeOutput:
    if not result.ok:
        error = result.error
        raise HarnessError(
            error.code if error is not None else "tool_failed",
            error.message if error is not None else "tool failed",
        )
    return NodeOutput(
        values=dict(result.structured_content or {}),
        artifacts=list(result.artifacts),
    )
```

### Tool Id Rules

- Graph nodes may contain `document.markitdown_convert` or `internal:document.markitdown_convert`.
- Gateway calls must use normalized ids such as `internal:document.markitdown_convert`.
- Registry lookups must use provider ids such as `document.markitdown_convert`.
- Disabled-tool checks must continue to use `equivalent_tool_ids()`.
- Permission checks must look up manifest permissions with `provider_tool_id()`.

---

## Task 0: Baseline Verification

**Files:**
- Read: `python/agent_service/execution.py`
- Read: `python/agent_service/tool_gateway.py`
- Read: `python/agent_service/tool_providers/internal.py`
- Read: `python/tests/test_execution.py`

- [ ] **Step 1: Confirm branch and clean worktree**

Run:

```powershell
git status --short --branch
```

Expected:

```text
## codex/agent-runtime-phase-a-security-hygiene
```

- [ ] **Step 2: Run the focused Phase B baseline**

Run:

```powershell
python -m pytest -q python\tests\test_agent_run_state.py python\tests\test_tool_gateway.py python\tests\test_execution.py python\tests\test_permission_gate.py
```

Expected:

```text
... passed
```

- [ ] **Step 3: Commit status**

No commit is expected for Task 0.

---

## Task 1: Default Unified Gateway Factory

**Files:**
- Modify: `python/agent_service/tool_gateway.py`
- Modify: `python/tests/test_tool_gateway.py`

- [ ] **Step 1: Add failing tests for the default factory**

Append these tests to `python/tests/test_tool_gateway.py`:

```python
def test_default_unified_tool_gateway_lists_internal_tools() -> None:
    from agent_service.tool_gateway import default_unified_tool_gateway

    gateway = default_unified_tool_gateway(packages_root=_packages_root())

    tool_ids = {tool.id for tool in gateway.list_tools()}
    assert "internal:document.markitdown_convert" in tool_ids
    assert "internal:document.typst_compile" in tool_ids


def test_default_unified_tool_gateway_uses_injected_internal_executor() -> None:
    from agent_service.tool_gateway import default_unified_tool_gateway
    from agent_service.tool_protocol import UnifiedToolInvocation

    class RecordingExecutor:
        def __init__(self) -> None:
            self.calls = []

        def run(self, invocation):
            self.calls.append(invocation)
            return ToolResult(
                values={"text": "converted through factory"},
                artifacts=["artifacts/converted/source.md"],
                metadata={"executor": "recording"},
            )

    executor = RecordingExecutor()
    gateway = default_unified_tool_gateway(
        packages_root=_packages_root(),
        internal_executor=executor,
    )

    result = gateway.call_tool(
        UnifiedToolInvocation(
            invocation_id="inv-factory",
            run_id="run-factory",
            task_id="task-factory",
            tool_id="internal:document.markitdown_convert",
            arguments={
                "operation": "convert_local_file",
                "input_path": "inputs/source.docx",
                "output_path": "artifacts/converted/source.md",
            },
            project_path="D:\\Project\\demo.alita",
            allowed_roots=["D:\\Project"],
            requested_permissions=["read_project_files", "write_project_outputs"],
        )
    )

    assert result.ok is True
    assert result.structured_content == {"text": "converted through factory"}
    assert executor.calls
    assert executor.calls[0].tool_id == "document.markitdown_convert"
    assert executor.calls[0].operation == "convert_local_file"
```

- [ ] **Step 2: Run the new tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_tool_gateway.py::test_default_unified_tool_gateway_lists_internal_tools python\tests\test_tool_gateway.py::test_default_unified_tool_gateway_uses_injected_internal_executor
```

Expected:

```text
FAILED ... ImportError: cannot import name 'default_unified_tool_gateway'
```

- [ ] **Step 3: Add the factory implementation**

In `python/agent_service/tool_gateway.py`, add imports:

```python
from pathlib import Path

from agent_service.tool_execution import ToolExecutor, default_tool_packages_root
from agent_service.tool_providers.internal import InternalToolProvider
from agent_service.tool_registry import ToolRegistry
```

Then add this function below `UnifiedToolGateway.call_tool()` and above `_error()`:

```python
def default_unified_tool_gateway(
    *,
    packages_root: Path | None = None,
    internal_executor: ToolExecutor | None = None,
) -> UnifiedToolGateway:
    registry = ToolRegistry.from_packages_root(
        packages_root or default_tool_packages_root()
    )
    return UnifiedToolGateway(
        providers=[
            InternalToolProvider(
                registry=registry,
                executor=internal_executor,
            )
        ]
    )
```

- [ ] **Step 4: Run gateway tests**

Run:

```powershell
python -m pytest -q python\tests\test_tool_gateway.py
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/agent_service/tool_gateway.py python/tests/test_tool_gateway.py
git commit -m "feat: add default unified tool gateway"
```

Expected: one commit containing only the gateway factory and tests.

---

## Task 2: Document Flow Uses UnifiedToolGateway

**Files:**
- Modify: `python/agent_service/execution.py`
- Create: `python/tests/helpers/__init__.py`
- Create: `python/tests/helpers/tool_gateway.py`
- Create: `python/tests/test_execution_gateway_integration.py`
- Modify: `python/tests/test_execution.py`

- [ ] **Step 1: Create gateway integration test helpers**

Create `python/tests/helpers/__init__.py` with this content:

```python
# Shared pytest helpers.
```

Create `python/tests/helpers/tool_gateway.py` with this content:

```python
from __future__ import annotations

from pathlib import Path

from agent_service.tool_protocol import (
    ToolResultContent,
    ToolSafetyPolicy,
    UnifiedToolDefinition,
    UnifiedToolError,
    UnifiedToolResult,
)


class RecordingGateway:
    provider_id = "recording"

    def __init__(self, *, fail_code: str | None = None) -> None:
        self.calls = []
        self.fail_code = fail_code

    def list_tools(self):
        return [
            _tool_definition(
                "internal:document.markitdown_convert",
                required=[
                    "operation",
                    "input_path",
                    "output_path",
                ],
                permissions=[
                    "read_project_files",
                    "write_project_outputs",
                    "run_python_plugin",
                ],
            ),
            _tool_definition(
                "internal:document.typst_compile",
                required=[
                    "operation",
                    "title",
                    "outline",
                    "report",
                    "source_output_path",
                    "pdf_output_path",
                ],
                permissions=["write_project_outputs", "run_local_cli"],
            ),
            _tool_definition(
                "internal:document.receive_attachment",
                required=["operation"],
                permissions=["read_project_files"],
            ),
        ]

    def call_tool(self, invocation):
        self.calls.append(invocation)
        if self.fail_code is not None:
            return UnifiedToolResult(
                ok=False,
                content=[],
                structured_content=None,
                artifacts=[],
                metadata={},
                error=UnifiedToolError(
                    code=self.fail_code,
                    message=f"gateway failed: {self.fail_code}",
                    recoverable=False,
                ),
            )

        if invocation.tool_id == "internal:document.markitdown_convert":
            output_path = Path(invocation.arguments["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("# Markdown\n\nparsed text", encoding="utf-8")
            return UnifiedToolResult(
                ok=True,
                content=[
                    ToolResultContent(type="json", value={"text": "parsed text"}),
                    ToolResultContent(type="artifact", path=str(output_path)),
                ],
                structured_content={"text": "parsed text"},
                artifacts=[str(output_path)],
                metadata={"gateway": "recording"},
            )

        if invocation.tool_id == "internal:document.typst_compile":
            source_path = Path(invocation.arguments["source_output_path"])
            pdf_path = Path(invocation.arguments["pdf_output_path"])
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text("typst source", encoding="utf-8")
            pdf_path.write_bytes(b"%PDF-1.7\n")
            return UnifiedToolResult(
                ok=True,
                content=[
                    ToolResultContent(type="json", value={"artifact": str(pdf_path)}),
                    ToolResultContent(type="artifact", path=str(source_path)),
                    ToolResultContent(type="artifact", path=str(pdf_path)),
                ],
                structured_content={
                    "source": str(source_path),
                    "artifact": str(pdf_path),
                },
                artifacts=[str(source_path), str(pdf_path)],
                metadata={"gateway": "recording"},
            )

        if invocation.tool_id == "internal:document.receive_attachment":
            return UnifiedToolResult(
                ok=True,
                content=[],
                structured_content={"paths": ""},
                artifacts=[],
                metadata={},
            )

        raise AssertionError(f"unexpected tool id: {invocation.tool_id}")


def _tool_definition(
    tool_id: str,
    *,
    required: list[str],
    permissions: list[str],
) -> UnifiedToolDefinition:
    return UnifiedToolDefinition(
        id=tool_id,
        source="internal",
        provider_id="internal",
        provider_tool_name=tool_id.removeprefix("internal:"),
        display_name=tool_id,
        description=f"Test definition for {tool_id}",
        capabilities=[],
        input_schema={
            "type": "object",
            "required": required,
            "properties": {
                key: {"type": "string"}
                for key in required
            },
        },
        output_schema={"type": "object"},
        permissions=permissions,
        safety_policy=ToolSafetyPolicy(
            filesystem="project_write",
            network="none",
            user_approval="high_risk_only",
            secrets="none",
            sandbox="not_required",
            max_runtime_ms=60000,
        ),
        timeout_ms=60000,
    )
```

- [ ] **Step 2: Create the gateway integration test module**

Create `python/tests/test_execution_gateway_integration.py` with this initial content:

```python
from __future__ import annotations

from pathlib import Path

from agent_service.agent_run_state import AgentRunState
from agent_service.execution import DocumentFlowExecutor, NodeOutput, run_graph_events
from agent_service.schemas import RunGraphRequest
from tests.helpers.tool_gateway import RecordingGateway
from tests.test_execution import (
    FakeModelClient,
    build_document_flow_request,
    build_document_flow_request_with_typst,
    build_node,
)
```

- [ ] **Step 3: Add failing test for MarkItDown document parse through gateway**

Append this test to `python/tests/test_execution_gateway_integration.py`:

```python
def test_document_flow_parse_calls_unified_tool_gateway(tmp_path: Path) -> None:
    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    request = build_document_flow_request(tmp_path, source)
    run_state = AgentRunState.from_run_graph_request(request)
    gateway = RecordingGateway()
    executor = DocumentFlowExecutor(
        request,
        run_state=run_state,
        model_client=FakeModelClient(),
        tool_gateway=gateway,
    )

    output = executor.run("document-parse", {})

    assert output.values == {"text": "parsed text"}
    assert output.artifacts == [
        str(tmp_path / "artifacts" / "converted" / "01-input.md")
    ]
    assert len(gateway.calls) == 1
    invocation = gateway.calls[0]
    assert invocation.run_id == request.run_id
    assert invocation.task_id == request.task_id
    assert invocation.node_id == "document-parse"
    assert invocation.tool_id == "internal:document.markitdown_convert"
    assert invocation.arguments == {
        "operation": "convert_local_file",
        "input_path": str(source),
        "output_path": str(tmp_path / "artifacts" / "converted" / "01-input.md"),
    }
    assert invocation.project_path == request.project_path
    assert str(tmp_path) in invocation.allowed_roots
    assert "read_project_files" in invocation.requested_permissions
    assert invocation.model_session_id is None
```

- [ ] **Step 4: Add failing test for Typst export through gateway**

Append this test:

```python
def test_document_flow_typst_export_calls_unified_tool_gateway(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("# Title\n\nBody", encoding="utf-8")
    request = build_document_flow_request_with_typst(tmp_path, source)
    gateway = RecordingGateway()
    executor = DocumentFlowExecutor(
        request,
        run_state=AgentRunState.from_run_graph_request(request),
        model_client=FakeModelClient(),
        tool_gateway=gateway,
    )

    output = executor.run(
        "typst-export",
        {
            "content-organize": NodeOutput(values={"outline": "outline"}),
            "report-generate": NodeOutput(values={"report": "report"}),
        },
    )

    assert len(gateway.calls) == 1
    invocation = gateway.calls[0]
    assert invocation.node_id == "typst-export"
    assert invocation.tool_id == "internal:document.typst_compile"
    assert invocation.arguments["operation"] == "compile_report_pdf"
    assert invocation.arguments["title"] == "project"
    assert invocation.arguments["outline"] == "outline"
    assert invocation.arguments["report"] == "report"
    assert invocation.arguments["source_output_path"].endswith(".typ")
    assert invocation.arguments["pdf_output_path"].endswith(".pdf")
    assert output.values["artifact"].endswith(".pdf")
    assert any(Path(path).suffix == ".pdf" for path in output.artifacts)
```

- [ ] **Step 5: Run new tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_execution_gateway_integration.py::test_document_flow_parse_calls_unified_tool_gateway python\tests\test_execution_gateway_integration.py::test_document_flow_typst_export_calls_unified_tool_gateway
```

Expected:

```text
FAILED ... TypeError: DocumentFlowExecutor.__init__() got an unexpected keyword argument 'run_state'
```

- [ ] **Step 6: Update execution imports**

In `python/agent_service/execution.py`, update imports:

```python
from agent_service.tool_gateway import (
    UnifiedToolGateway,
    default_unified_tool_gateway,
)
from agent_service.tool_protocol import (
    UnifiedToolInvocation,
    UnifiedToolResult,
    equivalent_tool_ids,
    normalize_tool_id,
    provider_tool_id,
)
```

Remove `ToolInvocation` from the `tool_execution` import block. Keep `ToolExecutor` and `default_tool_packages_root` for compatibility and registry helpers.

- [ ] **Step 7: Add gateway helpers in `execution.py`**

Add these helpers near `_default_tool_registry()`:

```python
def _default_tool_gateway(
    *,
    tool_executor: ToolExecutor | None = None,
) -> UnifiedToolGateway:
    return default_unified_tool_gateway(internal_executor=tool_executor)


def _node_output_from_unified_result(result: UnifiedToolResult) -> NodeOutput:
    if not result.ok:
        error = result.error
        raise HarnessError(
            error.code if error is not None else "tool_failed",
            error.message if error is not None else "tool failed",
        )
    return NodeOutput(
        values=dict(result.structured_content or {}),
        artifacts=list(result.artifacts),
    )


def _required_permissions_for_tool_node(
    node: GraphNode,
    *,
    tool_registry: ToolRegistry,
) -> list[str]:
    permissions = list(node.permissionsRequired)
    if node.toolRef:
        try:
            permissions.extend(tool_registry.get(provider_tool_id(node.toolRef)).permissions)
        except KeyError:
            pass
    return _dedupe(permissions)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
```

- [ ] **Step 8: Change `DocumentFlowExecutor.__init__()`**

Replace its signature and tool fields with:

```python
class DocumentFlowExecutor:
    def __init__(
        self,
        request: RunGraphRequest,
        *,
        run_state: AgentRunState | None = None,
        model_client: ModelClient | None = None,
        model_runtime: ModelRuntime | None = None,
        tool_gateway: UnifiedToolGateway | None = None,
        tool_executor: ToolExecutor | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.request = request
        self.run_state = run_state or AgentRunState.from_run_graph_request(request)
        self.model_client = model_client or LlamaCppModelClient()
        self.model_runtime = model_runtime or ModelRuntime(model_client=self.model_client)
        self.tool_registry = tool_registry or _default_tool_registry()
        self.tool_gateway = tool_gateway or _default_tool_gateway(
            tool_executor=tool_executor
        )
        self.nodes_by_id = {node.nodeId: node for node in request.graph.nodes}
        self.project_dir = Path(request.project_path).parent
        self.artifact_dir = self.project_dir / "artifacts"
        self.task_graph = build_document_task_graph(
            request.task_id,
            GoalSpec(
                goal="Process attached documents into a report artifact.",
                task_type="document_processing",
                deliverable="markdown_report",
                success_criteria=["Generate a local project artifact."],
                required_context=["attachment"],
                risk_level="local_write",
                permissions_required=["read_attachment", "write_project_artifact"],
                confidence=0.85,
            ),
        )
```

- [ ] **Step 9: Add `DocumentFlowExecutor._call_tool()`**

Add this method inside `DocumentFlowExecutor`, above `_allowed_roots()`:

```python
    def _call_tool(
        self,
        node_id: str,
        *,
        tool_id: str,
        operation: str,
        arguments: dict[str, object],
    ) -> NodeOutput:
        node = self.nodes_by_id.get(node_id)
        permissions = (
            _required_permissions_for_tool_node(
                node,
                tool_registry=self.tool_registry,
            )
            if node is not None
            else []
        )
        result = self.tool_gateway.call_tool(
            UnifiedToolInvocation(
                invocation_id=(
                    f"{self.run_state.run_id or self.request.run_id}-"
                    f"{node_id}-{operation}"
                ),
                run_id=self.run_state.run_id or self.request.run_id,
                task_id=self.run_state.task_id,
                node_id=node_id,
                tool_id=normalize_tool_id(tool_id),
                arguments={"operation": operation, **arguments},
                project_path=self.run_state.project_path or self.request.project_path,
                allowed_roots=self._allowed_roots(),
                requested_permissions=permissions,
                model_session_id=self.run_state.message.model_session_id,
            )
        )
        return _node_output_from_unified_result(result)
```

- [ ] **Step 10: Route document parse through the gateway**

Replace the `document-parse` branch's `self.tool_executor.run(...)` block with:

```python
                output = self._call_tool(
                    "document-parse",
                    tool_id="document.markitdown_convert",
                    operation="convert_local_file",
                    arguments={
                        "input_path": attachment.path,
                        "output_path": str(output_path),
                    },
                )
                text = str(output.values.get("text", ""))
                if text:
                    texts.append(text)
                artifacts.extend(output.artifacts)
```

- [ ] **Step 11: Route Typst export through the gateway**

Replace the `typst-export` branch's `self.tool_executor.run(...)` block with:

```python
            output = self._call_tool(
                "typst-export",
                tool_id="document.typst_compile",
                operation="compile_report_pdf",
                arguments={
                    "title": Path(self.request.project_path).stem or "Alita Report",
                    "outline": outline,
                    "report": report,
                    "source_output_path": str(
                        self.artifact_dir / "typst" / f"{output_stem}.typ"
                    ),
                    "pdf_output_path": str(
                        self.artifact_dir / "typst" / f"{output_stem}.pdf"
                    ),
                },
            )
            return output
```

- [ ] **Step 12: Run document gateway tests**

Run:

```powershell
python -m pytest -q python\tests\test_execution_gateway_integration.py::test_document_flow_parse_calls_unified_tool_gateway python\tests\test_execution_gateway_integration.py::test_document_flow_typst_export_calls_unified_tool_gateway
```

Expected:

```text
2 passed
```

- [ ] **Step 13: Run existing document execution tests**

Run:

```powershell
python -m pytest -q python\tests\test_execution.py::test_document_parse_uses_markitdown_tool_executor python\tests\test_execution.py::test_document_flow_runs_typst_export_and_file_export_passes_pdf_artifact python\tests\test_execution.py::test_generated_markdown_conversion_graph_exports_converted_artifact
```

Expected:

```text
3 passed
```

These existing tests may keep using `tool_executor=...`; after this task that raw executor must be wrapped inside the default internal gateway rather than called directly by `DocumentFlowExecutor`.

- [ ] **Step 14: Commit**

Run:

```powershell
git add python/agent_service/execution.py python/tests/helpers/__init__.py python/tests/helpers/tool_gateway.py python/tests/test_execution_gateway_integration.py python/tests/test_execution.py
git commit -m "refactor: execute document tools through unified gateway"
```

Expected: one commit containing document tool gateway migration and tests.

---

## Task 3: Planned Fixed Tools Use UnifiedToolGateway

**Files:**
- Modify: `python/agent_service/execution.py`
- Modify: `python/tests/test_execution_gateway_integration.py`

- [ ] **Step 1: Add failing test for a planned fixed tool node**

Append this test to `python/tests/test_execution_gateway_integration.py`:

```python
def test_planned_fixed_tool_node_executes_through_unified_gateway(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.docx"
    source.write_bytes(b"fake docx")
    request = RunGraphRequest(
        task_id="task-planned-tool",
        run_id="run-planned-tool",
        project_path=str(tmp_path / "project.alita"),
        attachments=[
            {
                "attachment_id": "a1",
                "name": source.name,
                "path": str(source),
                "size_bytes": source.stat().st_size,
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }
        ],
        graph={
            "graphId": "planned-tool-graph",
            "metadata": {"taskKind": "document_processing"},
            "nodes": [
                build_node(
                    "execution-order-planning",
                    "planning",
                    [],
                ),
                build_node(
                    "tool-document-markitdown-convert",
                    "fixed_tool",
                    ["execution-order-planning"],
                    tool_ref="internal:document.markitdown_convert",
                    permissions=["read_project_files", "write_project_outputs"],
                ),
                build_node(
                    "task-output",
                    "output",
                    ["tool-document-markitdown-convert"],
                ),
            ],
            "edges": [],
        },
    )
    gateway = RecordingGateway()

    events = list(
        run_graph_events(
            request,
            run_state=AgentRunState.from_run_graph_request(request),
            tool_gateway=gateway,
        )
    )

    assert events[-1].type == "task.completed"
    assert len(gateway.calls) == 1
    invocation = gateway.calls[0]
    assert invocation.node_id == "tool-document-markitdown-convert"
    assert invocation.tool_id == "internal:document.markitdown_convert"
    assert invocation.arguments["operation"] == "convert_local_file"
    assert invocation.arguments["input_path"] == str(source)
    assert invocation.arguments["output_path"] == str(
        tmp_path / "artifacts" / "converted" / "01-input.md"
    )
```

- [ ] **Step 2: Add failing test for gateway error conversion**

Append this test:

```python
def test_planned_fixed_tool_gateway_error_becomes_node_failure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.docx"
    source.write_bytes(b"fake docx")
    request = RunGraphRequest(
        task_id="task-planned-tool-error",
        run_id="run-planned-tool-error",
        project_path=str(tmp_path / "project.alita"),
        attachments=[
            {
                "attachment_id": "a1",
                "name": source.name,
                "path": str(source),
                "size_bytes": source.stat().st_size,
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }
        ],
        graph={
            "graphId": "planned-tool-error-graph",
            "metadata": {"taskKind": "document_processing"},
            "nodes": [
                build_node(
                    "tool-document-markitdown-convert",
                    "fixed_tool",
                    [],
                    tool_ref="document.markitdown_convert",
                    permissions=["read_project_files", "write_project_outputs"],
                ),
                build_node(
                    "task-output",
                    "output",
                    ["tool-document-markitdown-convert"],
                ),
            ],
            "edges": [],
        },
    )

    events = list(
        run_graph_events(
            request,
            run_state=AgentRunState.from_run_graph_request(request),
            tool_gateway=RecordingGateway(fail_code="conversion_failed"),
        )
    )

    assert "node.failed" in [event.type for event in events]
    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "conversion_failed"
    assert "gateway failed: conversion_failed" in events[-1].payload["error"]
```

- [ ] **Step 3: Run new planned-tool tests and verify failure**

Run:

```powershell
python -m pytest -q python\tests\test_execution_gateway_integration.py::test_planned_fixed_tool_node_executes_through_unified_gateway python\tests\test_execution_gateway_integration.py::test_planned_fixed_tool_gateway_error_becomes_node_failure
```

Expected:

```text
FAILED ... TypeError: run_graph_events() got an unexpected keyword argument 'tool_gateway'
```

- [ ] **Step 4: Update `PlannedTaskExecutor.__init__()`**

In `python/agent_service/execution.py`, replace the `PlannedTaskExecutor.__init__()` signature/body with:

```python
class PlannedTaskExecutor:
    def __init__(
        self,
        request: RunGraphRequest,
        *,
        run_state: AgentRunState | None = None,
        model_client: ModelClient | None = None,
        tool_gateway: UnifiedToolGateway | None = None,
        tool_executor: ToolExecutor | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.request = request
        self.run_state = run_state or AgentRunState.from_run_graph_request(request)
        self.nodes_by_id = {node.nodeId: node for node in request.graph.nodes}
        self.model_client = model_client or LlamaCppModelClient()
        self.tool_registry = tool_registry or _default_tool_registry()
        self.tool_gateway = tool_gateway or _default_tool_gateway(
            tool_executor=tool_executor
        )
        self.document_executor = DocumentFlowExecutor(
            request,
            run_state=self.run_state,
            model_client=model_client,
            tool_gateway=self.tool_gateway,
            tool_executor=tool_executor,
            tool_registry=self.tool_registry,
        )
```

- [ ] **Step 5: Add `PlannedTaskExecutor._call_tool()`**

Add this method inside `PlannedTaskExecutor`, before `run()`:

```python
    def _call_tool(
        self,
        node: GraphNode,
        *,
        operation: str,
        arguments: dict[str, object],
    ) -> NodeOutput:
        if not node.toolRef:
            raise HarnessError(
                "unsupported_runtime",
                f"tool node {node.nodeId} has no bound runtime: <missing>",
            )
        result = self.tool_gateway.call_tool(
            UnifiedToolInvocation(
                invocation_id=(
                    f"{self.run_state.run_id or self.request.run_id}-"
                    f"{node.nodeId}-{operation}"
                ),
                run_id=self.run_state.run_id or self.request.run_id,
                task_id=self.run_state.task_id,
                node_id=node.nodeId,
                tool_id=normalize_tool_id(node.toolRef),
                arguments={"operation": operation, **arguments},
                project_path=self.run_state.project_path or self.request.project_path,
                allowed_roots=self.document_executor._allowed_roots(),
                requested_permissions=_required_permissions_for_tool_node(
                    node,
                    tool_registry=self.tool_registry,
                ),
                model_session_id=self.run_state.message.model_session_id,
            )
        )
        return _node_output_from_unified_result(result)
```

- [ ] **Step 6: Add fixed-tool argument inference for currently supported internal tools**

Add this method inside `PlannedTaskExecutor`, below `_call_tool()`:

```python
    def _run_fixed_tool_node(
        self,
        node: GraphNode,
        inputs: dict[str, NodeOutput],
    ) -> NodeOutput:
        tool_id = provider_tool_id(node.toolRef or "")

        if tool_id == "document.receive_attachment":
            if not self.request.attachments:
                raise HarnessError(
                    "missing_input",
                    f"tool node {node.nodeId} requires at least one attachment",
                )
            return NodeOutput(
                values={
                    "paths": "\n".join(
                        attachment.path for attachment in self.request.attachments
                    )
                }
            )

        if tool_id == "document.markitdown_convert":
            if not self.request.attachments:
                raise HarnessError(
                    "missing_input",
                    f"tool node {node.nodeId} requires at least one attachment",
                )
            texts: list[str] = []
            artifacts: list[str] = []
            for index, attachment in enumerate(self.request.attachments):
                input_path = Path(attachment.path)
                output_path = self.document_executor._converted_output_path(
                    index,
                    input_path,
                )
                output = self._call_tool(
                    node,
                    operation="convert_local_file",
                    arguments={
                        "input_path": attachment.path,
                        "output_path": str(output_path),
                    },
                )
                text = str(output.values.get("text", ""))
                if text:
                    texts.append(text)
                artifacts.extend(output.artifacts)
            return NodeOutput(
                artifacts=artifacts,
                values={"text": "\n\n".join(texts)},
            )

        if tool_id == "document.typst_compile":
            outline = _first_input_value(inputs, "outline")
            report = _first_input_value(inputs, "report")
            output_stem = f"report-{uuid4().hex[:8]}"
            return self._call_tool(
                node,
                operation="compile_report_pdf",
                arguments={
                    "title": Path(self.request.project_path).stem or "Alita Report",
                    "outline": outline,
                    "report": report,
                    "source_output_path": str(
                        self.document_executor.artifact_dir
                        / "typst"
                        / f"{output_stem}.typ"
                    ),
                    "pdf_output_path": str(
                        self.document_executor.artifact_dir
                        / "typst"
                        / f"{output_stem}.pdf"
                    ),
                },
            )

        raise HarnessError(
            "unsupported_runtime",
            f"tool node {node.nodeId} has no bound runtime: {node.toolRef or '<missing>'}",
        )
```

- [ ] **Step 7: Replace the fixed-tool unsupported branch**

In `PlannedTaskExecutor.run()`, replace:

```python
        if node.nodeType == "fixed_tool":
            raise HarnessError(
                "unsupported_runtime",
                f"tool node {node_id} has no bound runtime: {node.toolRef or '<missing>'}",
            )
```

with:

```python
        if node.nodeType == "fixed_tool":
            return self._run_fixed_tool_node(node, inputs)
```

- [ ] **Step 8: Add `tool_gateway` parameter to `run_graph_events()`**

Update the `run_graph_events()` signature:

```python
def run_graph_events(
    request: RunGraphRequest,
    *,
    run_state: AgentRunState | None = None,
    executor: NodeExecutor | None = None,
    model_client: ModelClient | None = None,
    tool_gateway: UnifiedToolGateway | None = None,
    tool_executor: ToolExecutor | None = None,
    search_provider: SearchProvider | None = None,
    source_fetcher: SourceContentFetcher | None = None,
    registry: RunRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
    permission_gate: PermissionGate | None = None,
    result_verifier: ResultVerifier | None = None,
    final_verifier: FinalVerifier | None = None,
    failure_replanner: FailureReplanner | None = None,
) -> Iterator[AgentEvent]:
```

Then after `effective_tool_registry = tool_registry or _default_tool_registry()`, add:

```python
        effective_tool_gateway = tool_gateway or _default_tool_gateway(
            tool_executor=tool_executor
        )
```

Keep the variable available for executor construction.

- [ ] **Step 9: Pass gateway and run state into executors**

In `run_graph_events()`, update executor construction:

```python
        node_executor = PlannedTaskExecutor(
            request,
            run_state=run_state,
            model_client=model_client,
            tool_gateway=effective_tool_gateway,
            tool_executor=tool_executor,
            tool_registry=effective_tool_registry,
        )
```

and:

```python
        node_executor = DocumentFlowExecutor(
            request,
            run_state=run_state,
            model_client=model_client,
            tool_gateway=effective_tool_gateway,
            tool_executor=tool_executor,
            tool_registry=effective_tool_registry,
        )
```

- [ ] **Step 10: Run planned fixed-tool tests**

Run:

```powershell
python -m pytest -q python\tests\test_execution_gateway_integration.py::test_planned_fixed_tool_node_executes_through_unified_gateway python\tests\test_execution_gateway_integration.py::test_planned_fixed_tool_gateway_error_becomes_node_failure
```

Expected:

```text
2 passed
```

- [ ] **Step 11: Run gateway integration tests**

Run:

```powershell
python -m pytest -q python\tests\test_execution_gateway_integration.py
```

Expected:

```text
4 passed
```

- [ ] **Step 12: Commit**

Run:

```powershell
git add python/agent_service/execution.py python/tests/test_execution_gateway_integration.py
git commit -m "refactor: execute planned fixed tools through unified gateway"
```

Expected: one commit containing planned fixed-tool gateway support and tests.

---

## Task 4: Tool Validation And Permission Lookup Use Unified Tool Ids

**Files:**
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/permission_gate.py`
- Modify: `python/tests/test_execution_gateway_integration.py`
- Modify: `python/tests/test_permission_gate.py`

- [ ] **Step 1: Add permission gate test for prefixed internal tool refs**

Append this test to `python/tests/test_permission_gate.py`:

```python
def test_manifest_permissions_work_with_prefixed_internal_tool_ref() -> None:
    node = _node(
        "custom-tool",
        tool_ref="internal:custom.network_tool",
        permissions=[],
    )

    with pytest.raises(HarnessError) as exc_info:
        PermissionGate().ensure_node_allowed(node, tool_registry=_registry())

    assert exc_info.value.code == "permission_required"
    assert "network" in exc_info.value.message
```

- [ ] **Step 2: Add graph validation test for gateway catalog**

Append this test to `python/tests/test_execution_gateway_integration.py`:

```python
def test_graph_tool_validation_uses_gateway_catalog_for_prefixed_internal_tools(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.docx"
    source.write_bytes(b"fake docx")
    request = RunGraphRequest(
        task_id="task-prefixed-tool",
        run_id="run-prefixed-tool",
        project_path=str(tmp_path / "project.alita"),
        attachments=[
            {
                "attachment_id": "a1",
                "name": source.name,
                "path": str(source),
                "size_bytes": source.stat().st_size,
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }
        ],
        graph={
            "graphId": "prefixed-tool-graph",
            "metadata": {"taskKind": "document_processing"},
            "nodes": [
                build_node(
                    "tool-document-markitdown-convert",
                    "fixed_tool",
                    [],
                    tool_ref="internal:document.markitdown_convert",
                    permissions=["read_project_files", "write_project_outputs"],
                ),
                build_node(
                    "task-output",
                    "output",
                    ["tool-document-markitdown-convert"],
                ),
            ],
            "edges": [],
        },
    )

    events = list(
        run_graph_events(
            request,
            run_state=AgentRunState.from_run_graph_request(request),
            tool_gateway=RecordingGateway(),
        )
    )

    assert events[-1].type == "task.completed"
```

- [ ] **Step 3: Run new tests and verify permission test failure**

Run:

```powershell
python -m pytest -q python\tests\test_permission_gate.py::test_manifest_permissions_work_with_prefixed_internal_tool_ref python\tests\test_execution_gateway_integration.py::test_graph_tool_validation_uses_gateway_catalog_for_prefixed_internal_tools
```

Expected before implementation:

```text
FAILED python/tests/test_permission_gate.py::test_manifest_permissions_work_with_prefixed_internal_tool_ref
```

The graph validation test may already pass because `_validate_graph_tools()` uses `provider_tool_id()`. Keep it as regression coverage for Phase C.

- [ ] **Step 4: Fix permission lookup for prefixed tool refs**

In `python/agent_service/permission_gate.py`, add:

```python
from agent_service.tool_protocol import provider_tool_id
```

Then replace:

```python
permissions.extend(tool_registry.get(node.toolRef).permissions)
```

with:

```python
permissions.extend(tool_registry.get(provider_tool_id(node.toolRef)).permissions)
```

- [ ] **Step 5: Make graph validation use the gateway catalog**

In `python/agent_service/execution.py`, change `_validate_graph_tools()` signature:

```python
def _validate_graph_tools(
    request: RunGraphRequest,
    available_tools: list,
) -> None:
```

Replace its body with:

```python
def _validate_graph_tools(
    request: RunGraphRequest,
    available_tools: list,
) -> None:
    available_tool_ids: set[str] = set()
    for tool in available_tools:
        available_tool_ids.update(equivalent_tool_ids(tool.id))

    for node in request.graph.nodes:
        if node.nodeType != "fixed_tool" or not node.toolRef:
            continue
        if _is_research_graph(request) and node.toolRef in {
            "web.search.parallel",
            "web.fetch.sources",
        }:
            continue
        if not (equivalent_tool_ids(node.toolRef) & available_tool_ids):
            raise HarnessError(
                "unsupported_tool",
                f"unsupported tool: {node.toolRef}",
            )
```

Update the call site in `run_graph_events()`:

```python
        effective_tool_registry = tool_registry or _default_tool_registry()
        effective_tool_gateway = tool_gateway or _default_tool_gateway(
            tool_executor=tool_executor
        )
        _validate_graph_tools(request, effective_tool_gateway.list_tools())
```

- [ ] **Step 6: Run permission and validation tests**

Run:

```powershell
python -m pytest -q python\tests\test_permission_gate.py python\tests\test_execution_gateway_integration.py
```

Expected:

```text
... passed
```

- [ ] **Step 7: Run unsupported tool regression**

Run:

```powershell
python -m pytest -q python\tests\test_execution.py::test_rejects_graph_with_unknown_tool_ref_before_running_nodes
```

Expected:

```text
1 passed
```

- [ ] **Step 8: Commit**

Run:

```powershell
git add python/agent_service/execution.py python/agent_service/permission_gate.py python/tests/test_execution_gateway_integration.py python/tests/test_permission_gate.py
git commit -m "fix: validate graph tools against unified gateway"
```

Expected: one commit containing validation and permission lookup changes.

---

## Task 5: Compatibility Regression For Existing `tool_executor` Injection

**Files:**
- Modify: `python/tests/test_execution.py`
- Read: `python/tests/helpers/tool_gateway.py`
- Read: `python/agent_service/execution.py`

- [ ] **Step 1: Add regression test proving `tool_executor` is only a compatibility adapter**

Append this test near the existing document tool executor tests in `python/tests/test_execution.py`:

```python
def test_tool_executor_injection_is_wrapped_by_unified_gateway(tmp_path: Path) -> None:
    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    request = build_document_flow_request(tmp_path, source)
    tool_executor = FakeToolExecutor()

    events = list(
        run_graph_events(
            request,
            model_client=FakeModelClient(),
            tool_executor=tool_executor,
        )
    )

    assert events[-1].type == "task.completed"
    assert tool_executor.calls
    invocation = tool_executor.calls[0]
    assert invocation.tool_id == "document.markitdown_convert"
    assert invocation.operation == "convert_local_file"
```

This test intentionally still observes the fake raw executor because the default gateway wraps it through `InternalToolProvider`. The production path should still call the gateway first.

- [ ] **Step 2: Add regression test proving explicit gateway wins over raw executor**

Append this test:

```python
def test_explicit_tool_gateway_takes_precedence_over_tool_executor(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    request = build_document_flow_request(tmp_path, source)
    gateway = RecordingGateway()
    tool_executor = FakeToolExecutor()

    events = list(
        run_graph_events(
            request,
            model_client=FakeModelClient(),
            tool_gateway=gateway,
            tool_executor=tool_executor,
        )
    )

    assert events[-1].type == "task.completed"
    assert gateway.calls
    assert tool_executor.calls == []
```

Add the missing import at the top of `python/tests/test_execution.py`:

```python
from tests.helpers.tool_gateway import RecordingGateway
```

- [ ] **Step 3: Run compatibility tests**

Run:

```powershell
python -m pytest -q python\tests\test_execution.py::test_tool_executor_injection_is_wrapped_by_unified_gateway python\tests\test_execution.py::test_explicit_tool_gateway_takes_precedence_over_tool_executor
```

Expected:

```text
2 passed
```

- [ ] **Step 4: Run broader execution tests**

Run:

```powershell
python -m pytest -q python\tests\test_execution.py python\tests\test_execution_gateway_integration.py
```

Expected:

```text
... passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add python/tests/test_execution.py
git commit -m "test: preserve tool executor compatibility through gateway"
```

---

## Task 6: Final Regression And Review

**Files:**
- Read: `python/agent_service/tool_gateway.py`
- Read: `python/agent_service/tool_providers/internal.py`
- Read: `python/agent_service/execution.py`
- Read: `python/agent_service/permission_gate.py`
- Read: `python/agent_service/model_tool_adapter.py`
- Read: `python/tests/test_execution_gateway_integration.py`

- [ ] **Step 1: Run Phase C focused Python tests**

Run:

```powershell
python -m pytest -q python\tests\test_tool_gateway.py python\tests\test_execution_gateway_integration.py python\tests\test_execution.py python\tests\test_permission_gate.py python\tests\test_model_tool_adapter.py python\tests\test_agent_run_state.py
```

Expected:

```text
... passed
```

- [ ] **Step 2: Run public routing and event compatibility tests**

Run:

```powershell
python -m pytest -q python\tests\test_agent_routing_integration.py python\tests\test_app.py python\tests\test_graph.py
```

Expected:

```text
... passed
```

- [ ] **Step 3: Run frontend event regression**

Run:

```powershell
npm run frontend:test -- src/features/task/useTaskEvents.test.ts src/app/backendEvents.test.ts
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

- [ ] **Step 5: Confirm no direct `ToolExecutor.run()` calls remain in graph execution**

Run:

```powershell
rg -n "tool_executor\.run|ToolInvocation\(" python\agent_service\execution.py
```

Expected:

```text
```

No matches should be printed. `ToolExecutor` may still appear in constructor signatures and in `_default_tool_gateway(tool_executor=...)`.

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

Dispatch a final code review over the Phase C commit range. Use this prompt:

```text
Review Phase C UnifiedToolGateway execution migration. Prioritize whether all graph fixed-tool execution now enters through UnifiedToolGateway, whether ToolExecutor is only an InternalToolProvider implementation detail, whether event payloads and endpoint schemas are unchanged, whether permission/disabled-tool behavior is preserved for both bare and internal-prefixed tool ids, and whether the implementation avoids premature dynamic tool-calling or MCP planning scope.
```

Expected: reviewer returns no blocking findings. Fix any critical or important finding before finishing.

---

## Acceptance Criteria

Phase C is complete when all statements are true:

- `default_unified_tool_gateway()` exists and builds a gateway backed by `InternalToolProvider`.
- `DocumentFlowExecutor` does not call `ToolExecutor.run()` directly.
- Document parse calls `UnifiedToolGateway.call_tool()` with `internal:document.markitdown_convert`.
- Typst export calls `UnifiedToolGateway.call_tool()` with `internal:document.typst_compile`.
- `run_graph_events()` accepts optional `tool_gateway` without changing endpoint schemas.
- Existing `tool_executor` test injection still works by wrapping the executor in the internal provider.
- Explicit `tool_gateway` injection takes precedence over `tool_executor`.
- `PlannedTaskExecutor` can execute currently supported internal fixed tools through the gateway instead of always raising `unsupported_runtime`.
- Gateway errors become structured `HarnessError` failures and preserve existing `node.failed` / `task.failed` payload shapes.
- Graph tool validation uses the unified gateway catalog and still skips research pseudo-tools until their provider phase.
- Permission lookup handles both bare ids and `internal:`-prefixed tool refs.
- `ToolExecutor` remains covered by `python/tests/test_tool_execution.py` but is not directly called from graph execution.
- Existing app, routing, graph, frontend event, Python, and Rust regressions pass.
- `.\scripts\verify-mvp.ps1` passes.

## Handoff Notes For Phase D

Phase D can build Router V2 on top of a stronger runtime boundary: `AgentRunState` now carries run context, and fixed-tool execution now has a single gateway surface. Do not add model-selected dynamic tool calls in Phase D unless Router V2 first emits structured `tool_candidates` and confidence metadata; dynamic execution should wait for the bounded ReAct/tool-call phase.
