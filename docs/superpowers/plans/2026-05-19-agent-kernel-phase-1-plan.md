# Agent Kernel Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Agent Kernel foundation without changing the current user-visible document workflow.

**Architecture:** Phase 1 is split into three safe slices. Phase 1A adds `GoalSpec`, `ContextBundle`, internal `TaskGraph`, and a compiler that emits the existing frontend `NodeGraph` shape. Phase 1B replaces inline tool dispatch with explicit manifest-informed adapters. Phase 1C introduces data-driven schema/artifact verification while preserving current failure codes and event behavior.

**Tech Stack:** Python 3.10+, FastAPI sidecar, Pydantic, existing LangGraph router, existing Python tool manifests, Pytest, existing React/Tauri graph schema kept unchanged for this phase.

---

## Current Constraints

- The active branch is `codex/agent-algorithm-refactor`.
- The worktree already has unrelated dirty frontend artifact-preview changes. Do not revert or include those files in Agent Kernel commits.
- `/agent/message` and `/agent/message/stream` do not receive `disabled_tool_ids`. Disabled tool enforcement remains in `/agent/graph/run/stream` for Phase 1.
- The frontend-facing `NodeGraph` schema must remain compatible with `src/shared/types.ts`.
- The current document flow node IDs must remain stable:
  - `document-input`
  - `document-parse`
  - `content-organize`
  - `report-generate`
  - `typst-export`
  - `file-export`

## File Structure

### Create

- `python/agent_service/goal_spec.py`
  - Parses a `UserMessage` into a deterministic `GoalSpec`.
- `python/agent_service/context_manager.py`
  - Builds a small planning context without reading attachment contents.
- `python/agent_service/task_graph.py`
  - Defines internal `TaskGraph`, `TaskNode`, bindings, validation helpers, and the first document graph builder.
- `python/agent_service/graph_compiler.py`
  - Compiles internal `TaskGraph` into the existing UI `NodeGraph` dictionary shape.
- `python/agent_service/tool_resolver.py`
  - Resolves manifest capabilities and operations into a concrete `ToolBinding`.
- `python/agent_service/verifier_v2.py`
  - Provides data-driven required value and artifact checks.
- `python/tests/test_goal_spec.py`
- `python/tests/test_context_manager.py`
- `python/tests/test_task_graph.py`
- `python/tests/test_graph_compiler.py`
- `python/tests/test_tool_resolver.py`
- `python/tests/test_verifier_v2.py`

### Modify

- `python/agent_service/graph.py`
  - Use `GoalSpec` for routing and use `TaskGraph -> GraphCompiler` for document graph generation.
- `python/agent_service/tool_execution.py`
  - Replace inline tool ID dispatch with explicit adapter mapping.
- `python/agent_service/result_verifier.py`
  - Wrap `VerifierV2` so existing callers keep working.
- `python/tests/test_graph.py`
  - Add assertions that document graph generation still produces the same frontend graph shape.
- `python/tests/test_tool_execution.py`
  - Add adapter-map tests while preserving existing MarkItDown and Typst tests.
- `python/tests/test_result_verifier.py`
  - Keep current behavior tests and add coverage for the `VerifierV2` wrapper path.
- `docs/superpowers/specs/2026-05-19-agent-kernel-refactor-design.md`
  - Already updated to reflect Phase 1A/1B/1C scope.

---

## Task 0: Baseline Verification

**Files:**
- Read only: `python/tests/test_graph.py`
- Read only: `python/tests/test_execution.py`
- Read only: `python/tests/test_tool_execution.py`
- Read only: `python/tests/test_result_verifier.py`

- [ ] **Step 1: Record current branch and dirty files**

Run:

```powershell
git status --short --branch
```

Expected: branch is `codex/agent-algorithm-refactor`; unrelated dirty frontend artifact-preview files may appear.

- [ ] **Step 2: Run focused existing Python tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_graph.py tests/test_execution.py tests/test_tool_execution.py tests/test_result_verifier.py
Pop-Location
```

Expected: selected tests pass. If they fail before code changes, stop and investigate the baseline failure before starting Task 1.

---

## Task 1: Phase 1A GoalSpec Parser

**Files:**
- Create: `python/tests/test_goal_spec.py`
- Create: `python/agent_service/goal_spec.py`
- Modify: `python/agent_service/graph.py`
- Test: `python/tests/test_goal_spec.py`
- Test: `python/tests/test_graph.py`

- [ ] **Step 1: Write the failing GoalSpec tests**

Create `python/tests/test_goal_spec.py`:

```python
from __future__ import annotations

from agent_service.goal_spec import GoalSpec, parse_goal_spec
from agent_service.schemas import Attachment, UserMessage


def make_attachment(name: str = "input.docx") -> Attachment:
    return Attachment(
        attachment_id="a1",
        name=name,
        path=f"workspace/inputs/{name}",
        size_bytes=100,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def test_plain_chat_goal_spec_is_chat() -> None:
    spec = parse_goal_spec(
        UserMessage(task_id="task-chat", content="你好，请介绍一下你自己")
    )

    assert isinstance(spec, GoalSpec)
    assert spec.task_type == "chat"
    assert spec.deliverable == "chat_answer"
    assert spec.missing_inputs == []
    assert spec.needs_web is False
    assert spec.risk_level == "read_only"


def test_document_task_with_attachment_goal_spec_is_document_processing() -> None:
    spec = parse_goal_spec(
        UserMessage(
            task_id="task-doc",
            content="整理成一份中文报告并导出 PDF",
            attachments=[make_attachment()],
        )
    )

    assert spec.task_type == "document_processing"
    assert spec.deliverable == "pdf_report"
    assert spec.missing_inputs == []
    assert "read_attachment" in spec.permissions_required
    assert "write_project_artifact" in spec.permissions_required
    assert "生成可打开的本地 artifact" in spec.success_criteria


def test_document_task_without_attachment_requests_document_input() -> None:
    spec = parse_goal_spec(
        UserMessage(task_id="task-missing", content="帮我处理这个文档")
    )

    assert spec.task_type == "document_processing"
    assert spec.deliverable == "markdown_report"
    assert spec.missing_inputs == ["document_file"]
    assert spec.needs_user_confirmation is False


def test_explicit_network_request_is_marked_but_not_executed() -> None:
    spec = parse_goal_spec(
        UserMessage(task_id="task-web", content="联网搜索最新的 Tauri 发布版本")
    )

    assert spec.task_type == "research"
    assert spec.needs_web is True
    assert spec.needs_user_confirmation is True
    assert spec.risk_level == "network"
    assert "network" in spec.permissions_required
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
Push-Location python
python -m pytest tests/test_goal_spec.py -v
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.goal_spec'`.

- [ ] **Step 3: Implement the deterministic GoalSpec parser**

Create `python/agent_service/goal_spec.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent_service.schemas import UserMessage


TaskType = Literal[
    "chat",
    "document_processing",
    "research",
    "local_file",
    "content_creation",
    "code_task",
    "automation",
    "unknown",
]

RiskLevel = Literal[
    "read_only",
    "local_write",
    "local_modify",
    "destructive",
    "network",
    "external_comm",
    "system",
]


class GoalSpec(BaseModel):
    goal: str
    task_type: TaskType
    deliverable: str | None = None
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    required_context: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "read_only"
    permissions_required: list[str] = Field(default_factory=list)
    needs_web: bool = False
    needs_user_confirmation: bool = False
    confidence: float = 0.7


DOCUMENT_ACTION_KEYWORDS = [
    "处理",
    "整理",
    "总结",
    "摘要",
    "提取",
    "分析",
    "改写",
    "翻译",
    "生成",
    "导出",
    "转换",
    "报告",
    "report",
    "summarize",
    "summary",
    "convert",
    "export",
]

DOCUMENT_REFERENCE_KEYWORDS = [
    "文档",
    "文件",
    "附件",
    "资料",
    "报告",
    "pdf",
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
]

WEB_KEYWORDS = [
    "联网",
    "搜索",
    "查一下",
    "最新",
    "release",
    "version",
    "github",
    "search",
    "latest",
]


def parse_goal_spec(message: UserMessage) -> GoalSpec:
    content = message.content.strip()
    normalized = content.lower()
    has_attachments = bool(message.attachments)
    has_document_action = _contains_any(normalized, DOCUMENT_ACTION_KEYWORDS)
    has_document_reference = _contains_any(normalized, DOCUMENT_REFERENCE_KEYWORDS)

    if _contains_any(normalized, WEB_KEYWORDS):
        return GoalSpec(
            goal=content or "联网查询",
            task_type="research",
            deliverable="chat_answer",
            constraints=[],
            success_criteria=["只在获得网络权限后使用外部信息"],
            required_context=["user_request"],
            risk_level="network",
            permissions_required=["network"],
            needs_web=True,
            needs_user_confirmation=True,
            confidence=0.78,
        )

    if has_attachments and (not content or has_document_action or has_document_reference):
        deliverable = "pdf_report" if "pdf" in normalized else "markdown_report"
        return GoalSpec(
            goal=content or "处理用户提供的附件",
            task_type="document_processing",
            deliverable=deliverable,
            constraints=_document_constraints(normalized),
            success_criteria=[
                "覆盖附件核心信息",
                "生成可打开的本地 artifact",
            ],
            required_context=["attachments", "available_tools"],
            risk_level="local_write",
            permissions_required=["read_attachment", "write_project_artifact"],
            confidence=0.86,
        )

    if not has_attachments and has_document_action and has_document_reference:
        return GoalSpec(
            goal=content,
            task_type="document_processing",
            deliverable="markdown_report",
            constraints=_document_constraints(normalized),
            success_criteria=["等待用户提供待处理文档"],
            required_context=["attachments"],
            missing_inputs=["document_file"],
            risk_level="read_only",
            permissions_required=["read_attachment"],
            confidence=0.82,
        )

    return GoalSpec(
        goal=content or "继续当前对话",
        task_type="chat",
        deliverable="chat_answer",
        success_criteria=["直接回答用户当前问题"],
        required_context=["conversation"],
        risk_level="read_only",
        permissions_required=[],
        confidence=0.7,
    )


def _contains_any(content: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in content for keyword in keywords)


def _document_constraints(content: str) -> list[str]:
    constraints: list[str] = []
    if "中文" in content:
        constraints.append("中文")
    if "pdf" in content:
        constraints.append("导出 PDF")
    if "markdown" in content or "md" in content:
        constraints.append("导出 Markdown")
    return constraints
```

- [ ] **Step 4: Run GoalSpec tests and verify they pass**

Run:

```powershell
Push-Location python
python -m pytest tests/test_goal_spec.py -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Integrate GoalSpec into `graph.py` routing**

Modify `python/agent_service/graph.py`:

```python
from agent_service.goal_spec import GoalSpec, parse_goal_spec
```

Extend `AgentState`:

```python
class AgentState(TypedDict, total=False):
    message: UserMessage
    events: list[AgentEvent]
    intent: AgentIntent
    goal_spec: GoalSpec
```

Replace `classify_intent()`:

```python
def classify_intent(state: AgentState) -> AgentState:
    goal_spec = parse_goal_spec(state["message"])
    return {
        **state,
        "goal_spec": goal_spec,
        "intent": _intent_from_goal_spec(goal_spec),
    }
```

Add:

```python
def _intent_from_goal_spec(goal_spec: GoalSpec) -> AgentIntent:
    if goal_spec.task_type == "document_processing":
        return "missing_input" if goal_spec.missing_inputs else "document_task"
    return "chat"
```

Keep `_classify_message()` temporarily as a compatibility wrapper for tests or internal callers:

```python
def _classify_message(message: UserMessage) -> AgentIntent:
    return _intent_from_goal_spec(parse_goal_spec(message))
```

- [ ] **Step 6: Run routing regression tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_goal_spec.py tests/test_graph.py -v
Pop-Location
```

Expected: PASS. Existing `test_missing_attachment_requests_input_for_document_task` and `test_attachment_generates_node_graph_for_document_task` must still pass.

- [ ] **Step 7: Commit Phase 1A GoalSpec changes**

Run:

```powershell
git add python/agent_service/goal_spec.py python/agent_service/graph.py python/tests/test_goal_spec.py python/tests/test_graph.py
git commit -m "feat: add agent goal spec parser"
```

Expected: commit succeeds and unrelated frontend artifact-preview files remain unstaged.

---

## Task 2: Phase 1A ContextBundle

**Files:**
- Create: `python/tests/test_context_manager.py`
- Create: `python/agent_service/context_manager.py`
- Test: `python/tests/test_context_manager.py`

- [ ] **Step 1: Write failing ContextBundle tests**

Create `python/tests/test_context_manager.py`:

```python
from __future__ import annotations

from pathlib import Path

from agent_service.context_manager import build_context_bundle
from agent_service.goal_spec import parse_goal_spec
from agent_service.schemas import Attachment, UserMessage
from agent_service.tool_registry import ToolRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_PACKAGES_ROOT = PROJECT_ROOT / "tool-packages"


def test_context_bundle_includes_attachments_and_tools_without_reading_file_contents(
    tmp_path: Path,
) -> None:
    attachment_path = tmp_path / "input.md"
    attachment_path.write_text("private attachment body", encoding="utf-8")
    message = UserMessage(
        task_id="task-context",
        content="整理这份文档",
        attachments=[
            Attachment(
                attachment_id="a1",
                name="input.md",
                path=str(attachment_path),
                size_bytes=attachment_path.stat().st_size,
                mime_type="text/markdown",
            )
        ],
    )
    goal_spec = parse_goal_spec(message)
    registry = ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)

    bundle = build_context_bundle(
        message=message,
        goal_spec=goal_spec,
        project_path=str(tmp_path / "project.alita"),
        tool_registry=registry,
    )

    assert bundle.project_path == str(tmp_path / "project.alita")
    assert bundle.artifact_dir == str(tmp_path / "artifacts")
    assert bundle.attachments[0].path == str(attachment_path)
    assert any(tool.tool_id == "document.markitdown_convert" for tool in bundle.available_tools)
    assert "private attachment body" not in bundle.model_dump_json()
```

- [ ] **Step 2: Run the new ContextBundle test and verify it fails**

Run:

```powershell
Push-Location python
python -m pytest tests/test_context_manager.py -v
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.context_manager'`.

- [ ] **Step 3: Implement ContextBundle**

Create `python/agent_service/context_manager.py`:

```python
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from agent_service.goal_spec import GoalSpec
from agent_service.schemas import Attachment, UserMessage
from agent_service.tool_registry import ToolRegistry, ToolManifestSpec


class AttachmentContext(BaseModel):
    attachment_id: str
    name: str
    path: str
    size_bytes: int
    mime_type: str


class ToolCapability(BaseModel):
    tool_id: str
    name: str
    capabilities: list[str] = Field(default_factory=list)
    operations: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    runtime: str | None = None


class ContextBundle(BaseModel):
    project_path: str
    artifact_dir: str
    goal: str
    task_type: str
    attachments: list[AttachmentContext] = Field(default_factory=list)
    available_tools: list[ToolCapability] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


def build_context_bundle(
    *,
    message: UserMessage,
    goal_spec: GoalSpec,
    project_path: str,
    tool_registry: ToolRegistry,
) -> ContextBundle:
    project_file = Path(project_path)
    artifact_dir = project_file.parent / "artifacts"
    return ContextBundle(
        project_path=project_path,
        artifact_dir=str(artifact_dir),
        goal=goal_spec.goal,
        task_type=goal_spec.task_type,
        attachments=[_attachment_context(attachment) for attachment in message.attachments],
        available_tools=[
            _tool_capability(tool)
            for tool in tool_registry.enabled_tools()
        ],
        constraints=goal_spec.constraints,
    )


def _attachment_context(attachment: Attachment) -> AttachmentContext:
    return AttachmentContext(
        attachment_id=attachment.attachment_id,
        name=attachment.name,
        path=attachment.path,
        size_bytes=attachment.size_bytes,
        mime_type=attachment.mime_type,
    )


def _tool_capability(tool: ToolManifestSpec) -> ToolCapability:
    return ToolCapability(
        tool_id=tool.tool_id,
        name=tool.name,
        capabilities=tool.capabilities,
        operations=[operation.name for operation in tool.operations],
        permissions=tool.permissions,
        runtime=tool.runtime,
    )
```

- [ ] **Step 4: Run ContextBundle tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_context_manager.py -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Commit ContextBundle**

Run:

```powershell
git add python/agent_service/context_manager.py python/tests/test_context_manager.py
git commit -m "feat: add agent context bundle"
```

Expected: commit succeeds.

---

## Task 3: Phase 1A Internal TaskGraph

**Files:**
- Create: `python/tests/test_task_graph.py`
- Create: `python/agent_service/task_graph.py`
- Test: `python/tests/test_task_graph.py`

- [ ] **Step 1: Write failing TaskGraph tests**

Create `python/tests/test_task_graph.py`:

```python
from __future__ import annotations

import pytest

from agent_service.goal_spec import parse_goal_spec
from agent_service.schemas import Attachment, UserMessage
from agent_service.task_graph import (
    TaskGraphValidationError,
    build_document_task_graph,
    validate_task_graph,
)


def document_message() -> UserMessage:
    return UserMessage(
        task_id="task-doc",
        content="整理成一份中文报告并导出 PDF",
        attachments=[
            Attachment(
                attachment_id="a1",
                name="input.docx",
                path="workspace/inputs/input.docx",
                size_bytes=100,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ],
    )


def test_build_document_task_graph_preserves_existing_node_ids() -> None:
    message = document_message()
    goal_spec = parse_goal_spec(message)

    task_graph = build_document_task_graph(task_id=message.task_id, goal_spec=goal_spec)

    assert task_graph.graph_id == "task-doc-graph"
    assert [node.node_id for node in task_graph.nodes] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]
    assert task_graph.node_by_id("document-parse").tool_binding.tool_id == (
        "document.markitdown_convert"
    )
    assert task_graph.node_by_id("typst-export").tool_binding.operation == (
        "compile_report_pdf"
    )
    assert task_graph.node_by_id("content-organize").model_binding.model_ref == (
        "local.content_organizer"
    )


def test_validate_task_graph_rejects_missing_dependency() -> None:
    task_graph = build_document_task_graph(
        task_id="task-doc",
        goal_spec=parse_goal_spec(document_message()),
    )
    task_graph.nodes[1].dependencies = ["missing-node"]

    with pytest.raises(TaskGraphValidationError) as exc_info:
        validate_task_graph(task_graph)

    assert "missing-node" in str(exc_info.value)


def test_validate_task_graph_rejects_cycles() -> None:
    task_graph = build_document_task_graph(
        task_id="task-doc",
        goal_spec=parse_goal_spec(document_message()),
    )
    task_graph.node_by_id("document-input").dependencies = ["file-export"]

    with pytest.raises(TaskGraphValidationError) as exc_info:
        validate_task_graph(task_graph)

    assert "cycle" in str(exc_info.value)
```

- [ ] **Step 2: Run TaskGraph tests and verify they fail**

Run:

```powershell
Push-Location python
python -m pytest tests/test_task_graph.py -v
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.task_graph'`.

- [ ] **Step 3: Implement TaskGraph models and document builder**

Create `python/agent_service/task_graph.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent_service.goal_spec import GoalSpec, RiskLevel


class TaskGraphValidationError(ValueError):
    pass


class RetryPolicy(BaseModel):
    max_retries: int = 0


class ToolBinding(BaseModel):
    tool_id: str
    operation: str
    arguments_template: dict[str, str] = Field(default_factory=dict)
    binding_reason: str
    required_permissions: list[str] = Field(default_factory=list)


class ModelBinding(BaseModel):
    model_ref: str
    runtime: str = "llm"
    prompt_template: str
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    temperature: float = 0.2
    max_tokens: int = 1024
    binding_reason: str


class TaskNodeUi(BaseModel):
    display_name: str
    summary: str
    position: dict[str, float]
    input_ports: list[dict] = Field(default_factory=list)
    output_ports: list[dict] = Field(default_factory=list)


class TaskNode(BaseModel):
    node_id: str
    kind: Literal["input", "tool", "model", "output", "planning"]
    objective: str
    dependencies: list[str] = Field(default_factory=list)
    outputs: dict[str, str] = Field(default_factory=dict)
    success_criteria: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "read_only"
    permissions_required: list[str] = Field(default_factory=list)
    tool_binding: ToolBinding | None = None
    model_binding: ModelBinding | None = None
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    ui: TaskNodeUi


class TaskEdge(BaseModel):
    id: str
    source: str
    target: str


class TaskGraph(BaseModel):
    graph_id: str
    goal_spec: GoalSpec
    nodes: list[TaskNode]
    edges: list[TaskEdge]

    def node_by_id(self, node_id: str) -> TaskNode:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(node_id)


def build_document_task_graph(*, task_id: str, goal_spec: GoalSpec) -> TaskGraph:
    nodes = [
        _document_input_node(),
        _document_parse_node(),
        _content_organize_node(),
        _report_generate_node(),
        _typst_export_node(),
        _file_export_node(),
    ]
    graph = TaskGraph(
        graph_id=f"{task_id}-graph",
        goal_spec=goal_spec,
        nodes=nodes,
        edges=[
            TaskEdge(id=f"{dependency}-{node.node_id}", source=dependency, target=node.node_id)
            for node in nodes
            for dependency in node.dependencies
        ],
    )
    validate_task_graph(graph)
    return graph


def validate_task_graph(task_graph: TaskGraph) -> None:
    node_ids = {node.node_id for node in task_graph.nodes}
    for node in task_graph.nodes:
        for dependency in node.dependencies:
            if dependency not in node_ids:
                raise TaskGraphValidationError(
                    f"node {node.node_id} depends on missing node {dependency}"
                )

    completed: set[str] = set()
    while len(completed) < len(task_graph.nodes):
        ready = [
            node
            for node in task_graph.nodes
            if node.node_id not in completed
            and all(dependency in completed for dependency in node.dependencies)
        ]
        if not ready:
            raise TaskGraphValidationError("task graph contains a dependency cycle")
        for node in ready:
            completed.add(node.node_id)


def _document_input_node() -> TaskNode:
    return TaskNode(
        node_id="document-input",
        kind="input",
        objective="Receive the user-provided document attachments.",
        outputs={"paths": "document"},
        success_criteria=["At least one attachment path is available."],
        risk_level="read_only",
        permissions_required=["read_attachment"],
        tool_binding=ToolBinding(
            tool_id="document.receive_attachment",
            operation="receive_attachment",
            binding_reason="The user attachment is the source document input.",
            required_permissions=["read_attachment"],
        ),
        ui=TaskNodeUi(
            display_name="文档输入",
            summary="接收用户在聊天区提供的文档附件。",
            position={"x": 260, "y": 20},
            output_ports=[_port("document-output", "文档", "document")],
        ),
    )


def _document_parse_node() -> TaskNode:
    return TaskNode(
        node_id="document-parse",
        kind="tool",
        objective="Convert the document attachment to Markdown text.",
        dependencies=["document-input"],
        outputs={"text": "text"},
        success_criteria=["Markdown text is non-empty."],
        risk_level="local_write",
        permissions_required=["read_attachment", "write_project_artifact"],
        tool_binding=ToolBinding(
            tool_id="document.markitdown_convert",
            operation="convert_local_file",
            arguments_template={
                "input_path": "{{attachment.path}}",
                "output_path": "{{artifact_dir}}/converted/{{attachment.index}}-{{attachment.stem}}.md",
            },
            binding_reason="MarkItDown converts local office and PDF files to Markdown.",
            required_permissions=["read_attachment", "write_project_artifact"],
        ),
        ui=TaskNodeUi(
            display_name="文档转 Markdown",
            summary="把用户提供的本地文档转换为适合模型读取的 Markdown 正文。",
            position={"x": 260, "y": 190},
            input_ports=[_port("document-input", "文档", "document")],
            output_ports=[_port("markdown-output", "Markdown", "text")],
        ),
    )


def _content_organize_node() -> TaskNode:
    return TaskNode(
        node_id="content-organize",
        kind="model",
        objective="Extract structured key points from the Markdown text.",
        dependencies=["document-parse"],
        outputs={"outline": "json"},
        success_criteria=["Outline is non-empty."],
        model_binding=ModelBinding(
            model_ref="local.content_organizer",
            prompt_template="document.content_organizer.zh.v1",
            output_schema={"type": "object", "required": ["outline"]},
            binding_reason="A local LLM can organize document content into key points.",
        ),
        ui=TaskNodeUi(
            display_name="整理内容",
            summary="提炼文档要点，形成结构化提纲。",
            position={"x": 90, "y": 370},
            input_ports=[_port("text-input", "正文", "text")],
            output_ports=[_port("outline-output", "提纲", "json")],
        ),
    )


def _report_generate_node() -> TaskNode:
    return TaskNode(
        node_id="report-generate",
        kind="model",
        objective="Generate a concise report from the Markdown text.",
        dependencies=["document-parse"],
        outputs={"report": "text"},
        success_criteria=["Report body is non-empty."],
        model_binding=ModelBinding(
            model_ref="local.report_writer",
            prompt_template="document.report_writer.zh.v1",
            max_tokens=1536,
            output_schema={"type": "object", "required": ["report"]},
            binding_reason="A local LLM can write the requested report.",
        ),
        ui=TaskNodeUi(
            display_name="生成报告",
            summary="根据提取的正文生成报告初稿。",
            position={"x": 430, "y": 370},
            input_ports=[_port("text-input", "正文", "text")],
            output_ports=[_port("report-output", "报告", "text")],
        ),
    )


def _typst_export_node() -> TaskNode:
    return TaskNode(
        node_id="typst-export",
        kind="tool",
        objective="Compile the report into Typst source and PDF artifacts.",
        dependencies=["content-organize", "report-generate"],
        outputs={"source": "artifact", "artifact": "artifact"},
        success_criteria=["Typst source and PDF artifacts exist."],
        risk_level="local_write",
        permissions_required=["write_project_artifact"],
        tool_binding=ToolBinding(
            tool_id="document.typst_compile",
            operation="compile_report_pdf",
            binding_reason="Typst exports the organized report into a local PDF artifact.",
            required_permissions=["write_project_artifact"],
        ),
        ui=TaskNodeUi(
            display_name="Typst PDF 导出",
            summary="把整理结果和报告正文排版为 Typst 源文件，并编译为 PDF。",
            position={"x": 260, "y": 560},
            input_ports=[
                _port("outline-input", "提纲", "json"),
                _port("report-input", "报告", "text"),
            ],
            output_ports=[
                _port("typst-output", "Typst 源文件", "artifact"),
                _port("pdf-output", "PDF 文件", "artifact"),
            ],
        ),
    )


def _file_export_node() -> TaskNode:
    return TaskNode(
        node_id="file-export",
        kind="output",
        objective="Expose the final generated artifacts to the user.",
        dependencies=["typst-export"],
        outputs={"artifact": "artifact"},
        success_criteria=["At least one final artifact exists."],
        risk_level="local_write",
        permissions_required=["write_project_artifact"],
        ui=TaskNodeUi(
            display_name="导出文件",
            summary="汇总 Typst 源文件和 PDF，输出最终文件。",
            position={"x": 260, "y": 750},
            input_ports=[_port("artifact-input", "PDF 文件", "artifact")],
            output_ports=[_port("artifact-output", "产物", "artifact")],
        ),
    )


def _port(port_id: str, label: str, data_type: str) -> dict:
    return {"id": port_id, "label": label, "dataType": data_type}
```

- [ ] **Step 4: Run TaskGraph tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_task_graph.py -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Commit TaskGraph**

Run:

```powershell
git add python/agent_service/task_graph.py python/tests/test_task_graph.py
git commit -m "feat: add internal agent task graph"
```

Expected: commit succeeds.

---

## Task 4: Phase 1A Graph Compiler And Document Graph Integration

**Files:**
- Create: `python/tests/test_graph_compiler.py`
- Create: `python/agent_service/graph_compiler.py`
- Modify: `python/agent_service/graph.py`
- Modify: `python/tests/test_graph.py`
- Test: `python/tests/test_graph_compiler.py`
- Test: `python/tests/test_graph.py`

- [ ] **Step 1: Write failing GraphCompiler tests**

Create `python/tests/test_graph_compiler.py`:

```python
from __future__ import annotations

from agent_service.goal_spec import parse_goal_spec
from agent_service.graph_compiler import compile_task_graph_to_node_graph
from agent_service.schemas import Attachment, UserMessage
from agent_service.task_graph import build_document_task_graph


def test_compile_document_task_graph_to_existing_node_graph_shape() -> None:
    message = UserMessage(
        task_id="task-doc",
        content="整理成报告",
        attachments=[
            Attachment(
                attachment_id="a1",
                name="input.docx",
                path="workspace/inputs/input.docx",
                size_bytes=100,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ],
    )
    task_graph = build_document_task_graph(
        task_id=message.task_id,
        goal_spec=parse_goal_spec(message),
    )

    node_graph = compile_task_graph_to_node_graph(task_graph)

    assert node_graph["graphId"] == "task-doc-graph"
    assert [node["nodeId"] for node in node_graph["nodes"]] == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "typst-export",
        "file-export",
    ]
    assert node_graph["nodes"][1]["toolRef"] == "document.markitdown_convert"
    assert node_graph["nodes"][2]["modelRef"] == "local-content-organizer"
    assert node_graph["nodes"][4]["toolRef"] == "document.typst_compile"
    assert {
        "id": "typst-export-file-export",
        "source": "typst-export",
        "target": "file-export",
    } in node_graph["edges"]
```

- [ ] **Step 2: Run GraphCompiler tests and verify they fail**

Run:

```powershell
Push-Location python
python -m pytest tests/test_graph_compiler.py -v
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.graph_compiler'`.

- [ ] **Step 3: Implement GraphCompiler**

Create `python/agent_service/graph_compiler.py`:

```python
from __future__ import annotations

from agent_service.task_graph import TaskGraph, TaskNode


MODEL_REF_TO_UI_MODEL_REF = {
    "local.content_organizer": "local-content-organizer",
    "local.report_writer": "local-report-writer",
}


def compile_task_graph_to_node_graph(task_graph: TaskGraph) -> dict:
    return {
        "graphId": task_graph.graph_id,
        "nodes": [_compile_node(node) for node in task_graph.nodes],
        "edges": [
            {"id": edge.id, "source": edge.source, "target": edge.target}
            for edge in task_graph.edges
        ],
    }


def _compile_node(node: TaskNode) -> dict:
    compiled = {
        "nodeId": node.node_id,
        "nodeType": _node_type(node),
        "displayName": node.ui.display_name,
        "status": "completed" if node.kind == "input" else "waiting",
        "inputPorts": node.ui.input_ports,
        "outputPorts": node.ui.output_ports,
        "dependencies": node.dependencies,
        "summary": node.ui.summary,
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "position": node.ui.position,
    }
    if node.tool_binding is not None:
        compiled["toolRef"] = node.tool_binding.tool_id
    if node.model_binding is not None:
        compiled["modelRef"] = MODEL_REF_TO_UI_MODEL_REF.get(
            node.model_binding.model_ref,
            node.model_binding.model_ref,
        )
    return compiled


def _node_type(node: TaskNode) -> str:
    if node.kind in {"input", "tool"}:
        return "fixed_tool"
    if node.kind == "model":
        return "model"
    if node.kind == "output":
        return "output"
    return "temporary_placeholder"
```

- [ ] **Step 4: Run GraphCompiler tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_graph_compiler.py -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Replace document graph creation in `graph.py`**

Modify imports in `python/agent_service/graph.py`:

```python
from agent_service.graph_compiler import compile_task_graph_to_node_graph
from agent_service.task_graph import build_document_task_graph
```

Replace `_create_document_graph(task_id: str) -> dict` with:

```python
def _create_document_graph(task_id: str, goal_spec: GoalSpec | None = None) -> dict:
    if goal_spec is None:
        goal_spec = parse_goal_spec(UserMessage(task_id=task_id, content="", attachments=[]))
    return compile_task_graph_to_node_graph(
        build_document_task_graph(task_id=task_id, goal_spec=goal_spec)
    )
```

Modify `plan_node_graph()` to pass the parsed goal:

```python
def plan_node_graph(state: AgentState) -> AgentState:
    goal_spec = state.get("goal_spec") or parse_goal_spec(state["message"])
    return {
        **state,
        "events": [
            AgentEvent(
                type="node_graph.created",
                payload={
                    "graph": _create_document_graph(
                        state["message"].task_id,
                        goal_spec=goal_spec,
                    ),
                },
            )
        ],
    }
```

- [ ] **Step 6: Run graph regression tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_goal_spec.py tests/test_task_graph.py tests/test_graph_compiler.py tests/test_graph.py -v
Pop-Location
```

Expected: PASS. The existing document graph assertions in `tests/test_graph.py` must still pass without frontend changes.

- [ ] **Step 7: Commit graph compiler integration**

Run:

```powershell
git add python/agent_service/graph_compiler.py python/agent_service/graph.py python/tests/test_graph_compiler.py python/tests/test_graph.py
git commit -m "feat: compile document task graph for UI"
```

Expected: commit succeeds.

---

## Task 5: Phase 1B Tool Resolver

**Files:**
- Create: `python/tests/test_tool_resolver.py`
- Create: `python/agent_service/tool_resolver.py`
- Test: `python/tests/test_tool_resolver.py`

- [ ] **Step 1: Write failing ToolResolver tests**

Create `python/tests/test_tool_resolver.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.tool_resolver import ToolResolutionError, resolve_tool_binding
from agent_service.tool_registry import ToolRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_PACKAGES_ROOT = PROJECT_ROOT / "tool-packages"


def test_resolves_markitdown_by_capability_and_operation() -> None:
    registry = ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)

    binding = resolve_tool_binding(
        registry=registry,
        required_capability="document.convert.markdown",
        operation="convert_local_file",
    )

    assert binding.tool_id == "document.markitdown_convert"
    assert binding.operation == "convert_local_file"
    assert "document.convert.markdown" in binding.binding_reason


def test_resolver_rejects_disabled_tool() -> None:
    registry = ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)

    with pytest.raises(ToolResolutionError) as exc_info:
        resolve_tool_binding(
            registry=registry,
            required_capability="document.convert.markdown",
            operation="convert_local_file",
            disabled_tool_ids=["document.markitdown_convert"],
        )

    assert "document.convert.markdown" in str(exc_info.value)


def test_resolver_rejects_missing_capability() -> None:
    registry = ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)

    with pytest.raises(ToolResolutionError) as exc_info:
        resolve_tool_binding(
            registry=registry,
            required_capability="document.ocr.unavailable",
            operation="run",
        )

    assert "document.ocr.unavailable" in str(exc_info.value)
```

- [ ] **Step 2: Run ToolResolver tests and verify they fail**

Run:

```powershell
Push-Location python
python -m pytest tests/test_tool_resolver.py -v
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.tool_resolver'`.

- [ ] **Step 3: Implement ToolResolver**

Create `python/agent_service/tool_resolver.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field

from agent_service.tool_registry import ToolRegistry


class ToolResolutionError(ValueError):
    pass


class ResolvedToolBinding(BaseModel):
    tool_id: str
    operation: str
    arguments_template: dict[str, str] = Field(default_factory=dict)
    binding_reason: str
    required_permissions: list[str] = Field(default_factory=list)


def resolve_tool_binding(
    *,
    registry: ToolRegistry,
    required_capability: str,
    operation: str,
    disabled_tool_ids: list[str] | None = None,
) -> ResolvedToolBinding:
    disabled = set(disabled_tool_ids or [])
    for tool in registry.enabled_tools(disabled_tool_ids=disabled):
        if required_capability not in tool.capabilities:
            continue
        if not registry.has_operation(tool.tool_id, operation):
            continue
        return ResolvedToolBinding(
            tool_id=tool.tool_id,
            operation=operation,
            binding_reason=(
                f"Tool capability {required_capability} is provided by {tool.tool_id}."
            ),
            required_permissions=tool.permissions,
        )

    raise ToolResolutionError(
        f"no enabled tool provides capability {required_capability} with operation {operation}"
    )
```

- [ ] **Step 4: Run ToolResolver tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_tool_resolver.py -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Commit ToolResolver**

Run:

```powershell
git add python/agent_service/tool_resolver.py python/tests/test_tool_resolver.py
git commit -m "feat: add manifest tool resolver"
```

Expected: commit succeeds.

---

## Task 6: Phase 1B ToolExecutor Adapter Map

**Files:**
- Modify: `python/agent_service/tool_execution.py`
- Modify: `python/tests/test_tool_execution.py`
- Test: `python/tests/test_tool_execution.py`

- [ ] **Step 1: Add failing adapter-map tests**

Append to `python/tests/test_tool_execution.py`:

```python
def test_tool_executor_uses_registered_adapter_for_manifest_operation(tmp_path):
    registry = ToolRegistry.from_packages_root(TOOL_PACKAGES_ROOT)
    invocation = ToolInvocation(
        tool_id="document.markitdown_convert",
        operation="convert_local_file",
        arguments={
            "input_path": str(tmp_path / "source.docx"),
            "output_path": str(tmp_path / "converted.md"),
        },
        project_path=str(tmp_path / "project.alita"),
        allowed_roots=[str(tmp_path)],
    )
    calls = []

    def adapter(invocation):
        calls.append(invocation)
        return ToolResult(values={"text": "adapter text"}, artifacts=[])

    executor = ToolExecutor(
        registry=registry,
        adapters={("document.markitdown_convert", "convert_local_file"): adapter},
    )

    result = executor.run(invocation)

    assert result.values == {"text": "adapter text"}
    assert calls == [invocation]


def test_tool_executor_rejects_known_tool_without_adapter(tmp_path):
    packages_root = tmp_path / "tool-packages"
    custom_tool_root = packages_root / "custom"
    custom_tool_root.mkdir(parents=True)
    (custom_tool_root / "manifest.json").write_text(
        """
{
  "tool_id": "document.custom",
  "name": "Custom Tool",
  "description": "Known manifest without an executor adapter.",
  "version": "1.0.0",
  "source_type": "test",
  "license": "internal",
  "runtime": "python_sidecar",
  "entrypoint": "python/tools/custom.py",
  "capabilities": ["document.custom"],
  "operations": [{"name": "run", "description": "Run custom tool."}],
  "input_schema": {"type": "object", "required": ["operation"], "properties": {"operation": {"type": "string", "enum": ["run"]}}},
  "output_schema": {"type": "object"},
  "permissions": ["read_project_files"],
  "examples": [{"title": "Run", "input": {"operation": "run"}}],
  "error_codes": ["unsupported_tool"],
  "timeout_policy": {"seconds": 10},
  "artifact_policy": {},
  "security_policy": {"network": false}
}
""".strip(),
        encoding="utf-8",
    )
    registry = ToolRegistry.from_packages_root(packages_root)
    executor = ToolExecutor(registry=registry, adapters={})

    with pytest.raises(HarnessError) as exc_info:
        executor.run(
            ToolInvocation(
                tool_id="document.custom",
                operation="run",
                arguments={},
                project_path=str(tmp_path / "project.alita"),
            )
        )

    assert exc_info.value.code == "unsupported_tool"
    assert "document.custom" in exc_info.value.message
```

- [ ] **Step 2: Run adapter tests and verify they fail**

Run:

```powershell
Push-Location python
python -m pytest tests/test_tool_execution.py::test_tool_executor_uses_registered_adapter_for_manifest_operation tests/test_tool_execution.py::test_tool_executor_rejects_known_tool_without_adapter -v
Pop-Location
```

Expected: first test FAILS because `ToolExecutor.__init__()` does not accept `adapters`.

- [ ] **Step 3: Refactor `ToolExecutor` to use explicit adapters**

Modify `python/agent_service/tool_execution.py`:

```python
from collections.abc import Callable
```

Add after `ToolResult`:

```python
ToolAdapter = Callable[[ToolInvocation], ToolResult]
ToolAdapterKey = tuple[str, str]
```

Replace `ToolExecutor.__init__()` and dispatch:

```python
class ToolExecutor:
    def __init__(
        self,
        *,
        registry: ToolRegistry | None = None,
        adapters: dict[ToolAdapterKey, ToolAdapter] | None = None,
    ) -> None:
        self.registry = registry or ToolRegistry.from_packages_root(
            _default_tool_packages_root()
        )
        self.adapters = _default_adapters()
        if adapters is not None:
            self.adapters.update(adapters)

    def run(self, invocation: ToolInvocation) -> ToolResult:
        try:
            manifest = self.registry.get(invocation.tool_id)
        except KeyError as exc:
            raise HarnessError(
                "unsupported_tool", f"unsupported tool: {invocation.tool_id}"
            ) from exc

        if not self.registry.has_operation(invocation.tool_id, invocation.operation):
            raise HarnessError(
                "unsupported_operation",
                f"unsupported operation for {invocation.tool_id}: {invocation.operation}",
            )

        arguments = {"operation": invocation.operation, **invocation.arguments}
        try:
            validate_json_schema_subset(manifest.input_schema, arguments)
        except ValueError as exc:
            raise HarnessError("invalid_tool_input", str(exc)) from exc

        adapter = self.adapters.get((invocation.tool_id, invocation.operation))
        if adapter is None:
            raise HarnessError(
                "unsupported_tool",
                f"unsupported tool adapter: {invocation.tool_id}:{invocation.operation}",
            )
        return adapter(invocation)
```

Replace private methods with module-level adapter functions:

```python
def _default_adapters() -> dict[ToolAdapterKey, ToolAdapter]:
    return {
        ("document.markitdown_convert", "convert_local_file"): _run_markitdown,
        ("document.typst_compile", "compile_report_pdf"): _run_typst,
    }


def _run_markitdown(invocation: ToolInvocation) -> ToolResult:
    result = convert_markitdown_local_file(
        input_path=str(invocation.arguments["input_path"]),
        output_path=str(invocation.arguments["output_path"]),
        project_path=invocation.project_path,
        allowed_roots=invocation.allowed_roots,
    )
    return ToolResult(
        values={"text": result.text},
        artifacts=result.artifacts,
        metadata=result.metadata,
    )


def _run_typst(invocation: ToolInvocation) -> ToolResult:
    result = compile_typst_report_pdf(
        title=str(invocation.arguments["title"]),
        outline=str(invocation.arguments["outline"]),
        report=str(invocation.arguments["report"]),
        source_output_path=str(invocation.arguments["source_output_path"]),
        pdf_output_path=str(invocation.arguments["pdf_output_path"]),
        project_path=invocation.project_path,
        allowed_roots=invocation.allowed_roots,
    )
    return ToolResult(
        values={"source": result.source_path, "artifact": result.pdf_path},
        artifacts=result.artifacts,
        metadata=result.metadata,
    )
```

- [ ] **Step 4: Run tool execution tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_tool_execution.py -v
Pop-Location
```

Expected: PASS. Existing monkeypatch tests for `convert_markitdown_local_file` and `compile_typst_report_pdf` must still pass because default adapters call those module-level names.

- [ ] **Step 5: Run execution tests that use fake tool executors**

Run:

```powershell
Push-Location python
python -m pytest tests/test_execution.py::test_document_parse_uses_markitdown_tool_executor tests/test_execution.py::test_document_flow_runs_typst_export_and_file_export_passes_pdf_artifact -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 6: Commit ToolExecutor adapter map**

Run:

```powershell
git add python/agent_service/tool_execution.py python/tests/test_tool_execution.py
git commit -m "refactor: route tools through explicit adapters"
```

Expected: commit succeeds.

---

## Task 7: Phase 1C Verifier V2

**Files:**
- Create: `python/tests/test_verifier_v2.py`
- Create: `python/agent_service/verifier_v2.py`
- Modify: `python/agent_service/result_verifier.py`
- Modify: `python/tests/test_result_verifier.py`
- Test: `python/tests/test_verifier_v2.py`
- Test: `python/tests/test_result_verifier.py`

- [ ] **Step 1: Write failing Verifier V2 tests**

Create `python/tests/test_verifier_v2.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.harness_errors import HarnessError
from agent_service.node_output import NodeOutput
from agent_service.verifier_v2 import NodeVerificationSpec, VerifierV2


def test_verifier_v2_rejects_empty_required_value() -> None:
    verifier = VerifierV2(
        specs={"node-a": NodeVerificationSpec(required_values=["text"])}
    )

    with pytest.raises(HarnessError) as exc_info:
        verifier.verify("node-a", NodeOutput(values={"text": "   "}))

    assert exc_info.value.code == "empty_node_output"
    assert "node-a" in exc_info.value.message
    assert "text" in exc_info.value.message


def test_verifier_v2_rejects_missing_artifact(tmp_path: Path) -> None:
    verifier = VerifierV2()

    with pytest.raises(HarnessError) as exc_info:
        verifier.verify(
            "node-a",
            NodeOutput(values={"text": "body"}, artifacts=[str(tmp_path / "missing.md")]),
        )

    assert exc_info.value.code == "missing_artifact"


def test_verifier_v2_accepts_existing_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "report.md"
    artifact.write_text("report", encoding="utf-8")
    verifier = VerifierV2(
        specs={"node-a": NodeVerificationSpec(required_values=["artifact"])}
    )

    verifier.verify(
        "node-a",
        NodeOutput(values={"artifact": str(artifact)}, artifacts=[str(artifact)]),
    )
```

- [ ] **Step 2: Run Verifier V2 tests and verify they fail**

Run:

```powershell
Push-Location python
python -m pytest tests/test_verifier_v2.py -v
Pop-Location
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent_service.verifier_v2'`.

- [ ] **Step 3: Implement Verifier V2**

Create `python/agent_service/verifier_v2.py`:

```python
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from agent_service.harness_errors import HarnessError
from agent_service.node_output import NodeOutput


class NodeVerificationSpec(BaseModel):
    required_values: list[str] = Field(default_factory=list)
    require_artifact_value_listed: bool = False


def default_document_verification_specs() -> dict[str, NodeVerificationSpec]:
    return {
        "document-input": NodeVerificationSpec(required_values=["paths"]),
        "document-parse": NodeVerificationSpec(required_values=["text"]),
        "content-organize": NodeVerificationSpec(required_values=["outline"]),
        "report-generate": NodeVerificationSpec(required_values=["report"]),
        "file-export": NodeVerificationSpec(
            required_values=["artifact"],
            require_artifact_value_listed=True,
        ),
    }


class VerifierV2:
    def __init__(
        self,
        *,
        specs: dict[str, NodeVerificationSpec] | None = None,
    ) -> None:
        self.specs = specs or default_document_verification_specs()

    def verify(self, node_id: str, output: NodeOutput) -> None:
        spec = self.specs.get(node_id, NodeVerificationSpec())
        for required_value in spec.required_values:
            value = output.values.get(required_value, "")
            if not value.strip():
                raise HarnessError(
                    "empty_node_output",
                    f"node {node_id} returned empty value: {required_value}",
                )

        if spec.require_artifact_value_listed:
            artifact_value = output.values.get("artifact", "")
            if not output.artifacts:
                raise HarnessError(
                    "missing_artifact",
                    f"{node_id} artifact is missing from artifact list",
                )
            if Path(artifact_value) not in {Path(artifact) for artifact in output.artifacts}:
                raise HarnessError(
                    "missing_artifact",
                    f"{node_id} artifact is not listed: {artifact_value}",
                )

        for artifact in output.artifacts:
            if not Path(artifact).is_file():
                raise HarnessError(
                    "missing_artifact",
                    f"artifact does not exist: {artifact}",
                )
```

- [ ] **Step 4: Run Verifier V2 tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_verifier_v2.py -v
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Wrap Verifier V2 from existing ResultVerifier**

Replace `python/agent_service/result_verifier.py` with:

```python
from __future__ import annotations

from agent_service.node_output import NodeOutput
from agent_service.verifier_v2 import VerifierV2


class ResultVerifier:
    def __init__(self, *, verifier: VerifierV2 | None = None) -> None:
        self.verifier = verifier or VerifierV2()

    def verify(self, node_id: str, output: NodeOutput) -> None:
        self.verifier.verify(node_id, output)
```

- [ ] **Step 6: Run existing ResultVerifier tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_result_verifier.py tests/test_verifier_v2.py -v
Pop-Location
```

Expected: PASS. Existing error codes and messages remain compatible enough for current assertions.

- [ ] **Step 7: Run execution verifier regression**

Run:

```powershell
Push-Location python
python -m pytest tests/test_execution.py::test_execution_fails_when_result_verifier_rejects_empty_output -v
Pop-Location
```

Expected: PASS with `errorCode == "empty_node_output"`.

- [ ] **Step 8: Commit Verifier V2**

Run:

```powershell
git add python/agent_service/verifier_v2.py python/agent_service/result_verifier.py python/tests/test_verifier_v2.py python/tests/test_result_verifier.py python/tests/test_execution.py
git commit -m "refactor: add data-driven result verifier"
```

Expected: commit succeeds.

---

## Task 8: Phase 1 Focused Regression

**Files:**
- Read only: `python/tests/test_goal_spec.py`
- Read only: `python/tests/test_context_manager.py`
- Read only: `python/tests/test_task_graph.py`
- Read only: `python/tests/test_graph_compiler.py`
- Read only: `python/tests/test_graph.py`
- Read only: `python/tests/test_execution.py`
- Read only: `python/tests/test_tool_execution.py`
- Read only: `python/tests/test_result_verifier.py`
- Read only: `python/tests/test_verifier_v2.py`

- [ ] **Step 1: Run all Agent Kernel Phase 1 Python tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_goal_spec.py tests/test_context_manager.py tests/test_task_graph.py tests/test_graph_compiler.py tests/test_tool_resolver.py tests/test_graph.py tests/test_execution.py tests/test_tool_execution.py tests/test_result_verifier.py tests/test_verifier_v2.py
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

Expected: PASS. If optional local ASR dependencies are absent, verify existing ASR tests still use mocks and do not require a real Qwen model.

- [ ] **Step 3: Run frontend typecheck only if frontend files were changed**

Run only if Agent work changed TypeScript or React files:

```powershell
npm run frontend:lint
```

Expected: PASS. Phase 1 is designed to avoid frontend changes.

- [ ] **Step 4: Inspect final git status**

Run:

```powershell
git status --short --branch
```

Expected: Agent Kernel files are committed or intentionally staged according to the execution mode. Existing unrelated artifact-preview files may still be dirty and must not be included in Agent Kernel commits.

---

## Self-Review Checklist

- Phase 1A maps to Tasks 1 through 4.
- Phase 1B maps to Tasks 5 and 6.
- Phase 1C maps to Task 7.
- Focused regression maps to Task 8.
- No Phase 1 task changes frontend or Rust schemas.
- No Phase 1 task implements web research, script execution, memory, MCP, parallel scheduling, or schema generation.
- Disabled tool enforcement remains in `RunGraphRequest` execution, not message planning.
- Existing document flow node IDs are preserved.
