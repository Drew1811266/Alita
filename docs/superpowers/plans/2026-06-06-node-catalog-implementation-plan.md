# Node Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a shared Node Catalog layer so Deep Agent planning, graph compilation, and the frontend read-only node library all use the same normalized node definitions.

**Architecture:** Add backend catalog models, a builder, and a resolver that normalize internal tool manifests and system nodes into `NodeCatalogSnapshot`. Inject compact catalog summaries into Deep Agent planning, resolve plan steps through `NodeCatalogResolver` during graph compilation, and expose the same snapshot to a lightweight frontend node library and canvas node details.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest, React 19, TypeScript, Vitest, Tauri 2 sidecar HTTP bridge.

---

## Source References

- Spec: `docs/superpowers/specs/2026-06-06-node-catalog-design.md`
- Current tool manifest loader: `python/agent_service/tool_registry.py`
- Current Deep Agent graph compiler: `python/agent_service/deep_agent_graph_compile.py`
- Current Deep Agent context builder: `python/agent_service/context_manager.py`
- Current sidecar API: `python/agent_service/app.py`
- Current task frontend API pattern: `src/features/task/useTaskEvents.ts`
- Current graph node popover: `src/features/canvas/NodePopover.tsx`

## Scope Guardrails

Included:

- Backend `NodeDefinition`, `NodeCatalogSnapshot`, builder, diagnostics, availability, resolver.
- First catalog nodes for documents, web research, data/office, reasoning, human, verifier, and output categories.
- Graph compile through catalog for tool/model/system nodes.
- Planning context catalog summaries and `preferred_node_ids` plan hints.
- FastAPI endpoint for the catalog snapshot.
- Frontend read-only node library with search, category filter, availability, permissions, and details.
- Canvas node catalog provenance in `NodePopover`.

Excluded:

- Drag-and-drop node creation.
- Manual edge wiring.
- Node parameter editing UI.
- User-created custom nodes.
- Saved graph templates.
- Full plugin marketplace.
- Dynamic catalog hot reload.

## Planned File Structure

```text
python/
  agent_service/
    node_catalog.py                  # NodeDefinition models, builder, system node registry
    node_catalog_resolver.py         # Capability and preferred-node resolution
    context_manager.py               # Add available_nodes to ContextBundle
    deep_agent_models.py             # Add preferred_node_ids to PlanStep
    deep_agent_planner.py            # Include preferred_node_ids in prompt contract
    deep_agent_graph_compile.py      # Resolve nodes through NodeCatalogResolver
    deep_agent_runtime_graph.py      # Build and pass NodeCatalogSnapshot
    app.py                           # GET /agent/node-catalog
    schemas.py                       # Broaden port dataType values if needed
  tests/
    test_node_catalog.py
    test_node_catalog_resolver.py
    test_context_manager.py
    test_deep_agent_models.py
    test_deep_agent_planner.py
    test_deep_agent_graph_compile.py
    test_app.py

src/
  shared/
    types.ts                         # Node catalog frontend types
  features/
    nodeCatalog/
      nodeCatalogApi.ts              # Fetch sidecar catalog snapshot
      nodeCatalogApi.test.ts
      useNodeCatalog.ts
      useNodeCatalog.test.ts
      NodeCatalogPanel.tsx
      NodeCatalogPanel.test.tsx
  features/
    canvas/
      NodePopover.tsx                # Show catalog provenance
      NodePopover.test.tsx
  app/
    App.tsx                          # Read-only node library entry
    app.css                          # Node library styles
```

## Task 1: Backend Node Catalog Models And Builder

**Files:**
- Create: `python/agent_service/node_catalog.py`
- Create: `python/tests/test_node_catalog.py`

- [ ] **Step 1: Write failing tests for manifest and system node normalization**

Add `python/tests/test_node_catalog.py`:

```python
from __future__ import annotations

from pathlib import Path

from agent_service.node_catalog import (
    NodeAvailability,
    NodeCatalogBuilder,
    NodeDefinition,
    NodeExecutionBinding,
    NodePermissionProfile,
)
from agent_service.tool_registry import ToolRegistry


def _registry() -> ToolRegistry:
    return ToolRegistry.from_packages_root(
        Path(__file__).resolve().parents[2] / "tool-packages"
    )


def test_builder_converts_tool_manifest_to_node_definition() -> None:
    snapshot = NodeCatalogBuilder(tool_registry=_registry()).build()

    node = snapshot.node_by_id("document.convert.markdown")

    assert node.node_id == "document.convert.markdown"
    assert node.kind == "tool"
    assert node.category == "document"
    assert node.source == "internal_tool"
    assert node.capabilities == ["document.convert.markdown"]
    assert node.execution == NodeExecutionBinding(
        type="tool",
        tool_id="document.markitdown_convert",
        operation="convert_local_file",
    )
    assert node.permissions.permissions == [
        "read_project_files",
        "write_project_outputs",
        "run_python_plugin",
    ]
    assert node.permissions.risk_level == "high"
    assert node.availability == NodeAvailability(status="available")
    assert node.input_ports[0].data_type == "document"
    assert node.output_ports[0].data_type == "markdown"


def test_builder_registers_system_model_human_verifier_and_output_nodes() -> None:
    snapshot = NodeCatalogBuilder(tool_registry=_registry()).build()

    node_ids = {node.node_id for node in snapshot.nodes}

    assert "document.summarize" in node_ids
    assert "research.synthesize" in node_ids
    assert "human.clarify" in node_ids
    assert "verify.artifact_exists" in node_ids
    assert "output.final_response" in node_ids
    assert snapshot.node_by_id("document.summarize").execution.type == "model"
    assert snapshot.node_by_id("human.clarify").execution.type == "human"
    assert snapshot.node_by_id("verify.artifact_exists").execution.type == "verifier"
    assert snapshot.node_by_id("output.final_response").execution.type == "output"


def test_snapshot_records_duplicate_node_diagnostics() -> None:
    first = NodeDefinition(
        node_id="duplicate.node",
        kind="model",
        display_name="Duplicate",
        description="First duplicate node.",
        category="reasoning",
        capabilities=["duplicate.capability"],
        input_ports=[],
        output_ports=[],
        execution=NodeExecutionBinding(type="model", model_policy="node_reasoning"),
        permissions=NodePermissionProfile(),
        examples=[],
        source="system",
        version="1.0.0",
    )
    second = first.model_copy(update={"description": "Second duplicate node."})

    snapshot = NodeCatalogBuilder(tool_registry=ToolRegistry([])).build(
        additional_system_nodes=[first, second]
    )

    assert any(
        diagnostic.code == "duplicate_node_id"
        and diagnostic.node_id == "duplicate.node"
        for diagnostic in snapshot.diagnostics
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
Push-Location python
python -m pytest tests/test_node_catalog.py -q
Pop-Location
```

Expected: fails with `ModuleNotFoundError: No module named 'agent_service.node_catalog'`.

- [ ] **Step 3: Add catalog models and builder**

Create `python/agent_service/node_catalog.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_service.tool_registry import ToolManifestSpec, ToolRegistry


NodeKind = Literal["tool", "model", "human", "verifier", "output"]
NodeCategory = Literal[
    "document",
    "web",
    "data",
    "reasoning",
    "human",
    "verification",
    "output",
]
NodeSource = Literal["internal_tool", "system", "mcp", "plugin"]
AvailabilityStatus = Literal["available", "degraded", "unavailable"]
RiskLevel = Literal["low", "medium", "high"]


class NodeCatalogModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class NodeAvailability(NodeCatalogModel):
    status: AvailabilityStatus
    reason_code: str | None = None
    message: str | None = None


class NodePortDefinition(NodeCatalogModel):
    id: str
    label: str
    data_type: Literal[
        "text",
        "markdown",
        "document",
        "table",
        "json",
        "artifact",
        "url",
        "query",
        "decision",
    ] = Field(alias="dataType")
    required: bool = True
    multiple: bool = False
    description: str = ""


class NodeExecutionBinding(NodeCatalogModel):
    type: Literal["tool", "model", "human", "verifier", "output"]
    tool_id: str | None = None
    operation: str | None = None
    model_policy: Literal[
        "deep_reasoning",
        "node_reasoning",
        "fast_chat",
        "fast_factual",
    ] | None = None
    verifier_type: Literal[
        "artifact_exists",
        "citation_check",
        "schema_check",
        "coverage_check",
    ] | None = None
    output_type: Literal[
        "markdown",
        "docx",
        "pdf",
        "table",
        "checklist",
        "final_response",
    ] | None = None


class NodePermissionProfile(NodeCatalogModel):
    permissions: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "low"
    requires_approval: bool = False
    filesystem: Literal["none", "project_read", "project_write"] = "none"
    network: Literal["none", "external"] = "none"
    sandbox: Literal["none", "sidecar", "external"] = "none"


class NodeExample(NodeCatalogModel):
    title: str
    input: dict = Field(default_factory=dict)


class NodeDefinition(NodeCatalogModel):
    node_id: str
    kind: NodeKind
    display_name: str
    description: str
    category: NodeCategory
    capabilities: list[str] = Field(default_factory=list)
    input_ports: list[NodePortDefinition] = Field(default_factory=list)
    output_ports: list[NodePortDefinition] = Field(default_factory=list)
    execution: NodeExecutionBinding
    permissions: NodePermissionProfile = Field(default_factory=NodePermissionProfile)
    examples: list[NodeExample] = Field(default_factory=list)
    source: NodeSource
    version: str = "1.0.0"
    availability: NodeAvailability = Field(
        default_factory=lambda: NodeAvailability(status="available")
    )


class NodeCatalogDiagnostic(NodeCatalogModel):
    code: str
    node_id: str | None = None
    message: str


class NodeCatalogSourceSummary(NodeCatalogModel):
    internal_tool_count: int = 0
    system_node_count: int = 0
    mcp_node_count: int = 0
    plugin_node_count: int = 0


class NodeCatalogSnapshot(NodeCatalogModel):
    schema_version: int = 1
    generated_at: str
    nodes: list[NodeDefinition]
    diagnostics: list[NodeCatalogDiagnostic] = Field(default_factory=list)
    source_summary: NodeCatalogSourceSummary = Field(
        default_factory=NodeCatalogSourceSummary
    )

    def node_by_id(self, node_id: str) -> NodeDefinition:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(f"unknown catalog node: {node_id}")

    def available_capabilities(self) -> set[str]:
        capabilities = {"model.reasoning"}
        for node in self.nodes:
            if node.availability.status != "available":
                continue
            capabilities.add(node.node_id)
            capabilities.update(node.capabilities)
        return capabilities


class NodeCatalogBuilder:
    def __init__(self, *, tool_registry: ToolRegistry) -> None:
        self.tool_registry = tool_registry

    def build(
        self,
        *,
        additional_system_nodes: list[NodeDefinition] | None = None,
    ) -> NodeCatalogSnapshot:
        nodes = [
            node
            for tool in self.tool_registry.enabled_tools()
            for node in _nodes_from_tool_manifest(tool)
        ]
        system_nodes = [*_system_nodes(), *(additional_system_nodes or [])]
        nodes.extend(system_nodes)
        nodes, diagnostics = _deduplicate_nodes(nodes)
        return NodeCatalogSnapshot(
            generated_at=datetime.now(UTC).isoformat(),
            nodes=nodes,
            diagnostics=diagnostics,
            source_summary=NodeCatalogSourceSummary(
                internal_tool_count=sum(1 for node in nodes if node.source == "internal_tool"),
                system_node_count=sum(1 for node in nodes if node.source == "system"),
            ),
        )


def _nodes_from_tool_manifest(tool: ToolManifestSpec) -> list[NodeDefinition]:
    if tool.tool_id == "document.markitdown_convert":
        return [
            NodeDefinition(
                node_id="document.convert.markdown",
                kind="tool",
                display_name=tool.name,
                description=tool.description,
                category="document",
                capabilities=list(tool.capabilities),
                input_ports=[
                    NodePortDefinition(
                        id="document-input",
                        label="文档",
                        dataType="document",
                        description="项目内或附件中的待转换文档。",
                    )
                ],
                output_ports=[
                    NodePortDefinition(
                        id="markdown-output",
                        label="Markdown",
                        dataType="markdown",
                        description="转换后的 Markdown 文本或 artifact。",
                    )
                ],
                execution=NodeExecutionBinding(
                    type="tool",
                    tool_id=tool.tool_id,
                    operation="convert_local_file",
                ),
                permissions=_permissions_from_tool(tool),
                examples=[NodeExample(title=str(example.get("title", "")), input=dict(example.get("input", {}))) for example in tool.examples],
                source="internal_tool",
                version=tool.version,
            )
        ]
    if tool.tool_id == "document.typst_compile":
        return [
            NodeDefinition(
                node_id="document.render_pdf",
                kind="tool",
                display_name=tool.name,
                description=tool.description,
                category="document",
                capabilities=["document.render", "document.render.typst_pdf"],
                input_ports=[
                    NodePortDefinition(id="report-input", label="报告正文", dataType="text"),
                    NodePortDefinition(id="outline-input", label="整理内容", dataType="json"),
                ],
                output_ports=[
                    NodePortDefinition(id="pdf-output", label="PDF 文件", dataType="artifact")
                ],
                execution=NodeExecutionBinding(
                    type="tool",
                    tool_id=tool.tool_id,
                    operation="compile_report_pdf",
                ),
                permissions=_permissions_from_tool(tool),
                examples=[NodeExample(title=str(example.get("title", "")), input=dict(example.get("input", {}))) for example in tool.examples],
                source="internal_tool",
                version=tool.version,
            )
        ]
    if tool.tool_id == "document.read_write":
        return [
            _document_read_node(tool),
            _document_write_markdown_node(tool),
            _document_write_docx_node(tool),
        ]
    if tool.tool_id == "document.receive_attachment":
        return [
            NodeDefinition(
                node_id="document.receive_attachment",
                kind="tool",
                display_name="接收附件",
                description=tool.description,
                category="document",
                capabilities=["document_input"],
                input_ports=[],
                output_ports=[
                    NodePortDefinition(id="document-output", label="文档", dataType="document")
                ],
                execution=NodeExecutionBinding(
                    type="tool",
                    tool_id=tool.tool_id,
                    operation="receive_attachment",
                ),
                permissions=_permissions_from_tool(tool),
                source="internal_tool",
                version=tool.version,
            )
        ]
    return []


def _document_read_node(tool: ToolManifestSpec) -> NodeDefinition:
    return NodeDefinition(
        node_id="document.read",
        kind="tool",
        display_name="读取文档",
        description="读取项目内 txt、md、docx 文档。",
        category="document",
        capabilities=["document.read", "document.read_write"],
        input_ports=[NodePortDefinition(id="document-input", label="文档", dataType="document")],
        output_ports=[NodePortDefinition(id="text-output", label="正文", dataType="text")],
        execution=NodeExecutionBinding(type="tool", tool_id=tool.tool_id, operation="read"),
        permissions=_permissions_from_tool(tool),
        examples=[NodeExample(title=str(example.get("title", "")), input=dict(example.get("input", {}))) for example in tool.examples],
        source="internal_tool",
        version=tool.version,
    )


def _document_write_markdown_node(tool: ToolManifestSpec) -> NodeDefinition:
    return NodeDefinition(
        node_id="document.write_markdown",
        kind="tool",
        display_name="写 Markdown",
        description="把生成内容写入 Markdown artifact。",
        category="document",
        capabilities=["document.write", "document.write.markdown"],
        input_ports=[NodePortDefinition(id="content-input", label="正文", dataType="markdown")],
        output_ports=[NodePortDefinition(id="artifact-output", label="Markdown 文件", dataType="artifact")],
        execution=NodeExecutionBinding(type="tool", tool_id=tool.tool_id, operation="write_markdown"),
        permissions=_permissions_from_tool(tool),
        source="internal_tool",
        version=tool.version,
    )


def _document_write_docx_node(tool: ToolManifestSpec) -> NodeDefinition:
    return NodeDefinition(
        node_id="document.write_docx",
        kind="tool",
        display_name="写 Word",
        description="把生成内容写入 Word artifact。",
        category="document",
        capabilities=["document.write.docx"],
        input_ports=[NodePortDefinition(id="content-input", label="正文", dataType="text")],
        output_ports=[NodePortDefinition(id="artifact-output", label="Word 文件", dataType="artifact")],
        execution=NodeExecutionBinding(type="tool", tool_id=tool.tool_id, operation="write_docx"),
        permissions=_permissions_from_tool(tool),
        source="internal_tool",
        version=tool.version,
    )


def _system_nodes() -> list[NodeDefinition]:
    return [
        _model_node("document.extract_outline", "提取大纲", "document", ["document.extract_outline"]),
        _model_node("document.summarize", "文档摘要", "document", ["document.summarize", "model.reasoning"]),
        _model_node("document.extract_facts", "提取事实", "document", ["document.extract_facts"]),
        _model_node("document.compare", "多文档对比", "document", ["document.compare"]),
        _model_node("web.search", "联网搜索", "web", ["web.search"], network=True),
        _model_node("web.open_page", "打开网页", "web", ["web.open_page"], network=True),
        _model_node("web.extract_content", "网页正文抽取", "web", ["web.extract_content"], network=True),
        _model_node("web.evaluate_source", "来源评估", "web", ["web.evaluate_source"]),
        _model_node("web.collect_evidence", "证据整理", "web", ["web.collect_evidence"]),
        _model_node("web.citation_check", "引用检查", "web", ["web.citation_check"]),
        _model_node("research.synthesize", "研究综合", "web", ["research.synthesize", "model.reasoning"]),
        _model_node("research.write_report", "研究报告", "web", ["research.write_report"]),
        _model_node("data.read_table", "读取表格", "data", ["data.read_table"]),
        _model_node("data.clean_table", "清洗表格", "data", ["data.clean_table"]),
        _model_node("data.analyze_table", "分析表格", "data", ["data.analyze_table"]),
        _model_node("data.write_table", "导出表格", "data", ["data.write_table"]),
        _model_node("office.create_checklist", "生成任务清单", "data", ["office.create_checklist"]),
        _model_node("office.extract_action_items", "提取行动项", "data", ["office.extract_action_items"]),
        _model_node("office.compare_options", "方案对比", "data", ["office.compare_options"]),
        _model_node("office.write_memo", "写备忘录", "data", ["office.write_memo"]),
        _human_node("human.clarify", "澄清问题", ["human.clarify"]),
        _human_node("human.confirm_plan", "确认计划", ["human.confirm_plan"]),
        _human_node("human.choose_option", "选择方案", ["human.choose_option"]),
        _verifier_node("verify.artifact_exists", "产物存在检查", "artifact_exists", ["verify.artifact_exists"]),
        _verifier_node("verify.content_format", "内容格式检查", "schema_check", ["verify.content_format"]),
        _verifier_node("verify.requirements_covered", "需求覆盖检查", "coverage_check", ["verify.requirements_covered"]),
        NodeDefinition(
            node_id="output.final_response",
            kind="output",
            display_name="最终回复",
            description="向用户交付最终结果和产物说明。",
            category="output",
            capabilities=["output.final_response"],
            input_ports=[NodePortDefinition(id="result-input", label="结果", dataType="json")],
            output_ports=[NodePortDefinition(id="response-output", label="回复", dataType="text")],
            execution=NodeExecutionBinding(type="output", output_type="final_response"),
            permissions=NodePermissionProfile(),
            examples=[],
            source="system",
            version="1.0.0",
        ),
    ]


def _model_node(
    node_id: str,
    display_name: str,
    category: NodeCategory,
    capabilities: list[str],
    *,
    network: bool = False,
) -> NodeDefinition:
    permissions = NodePermissionProfile(
        permissions=["network"] if network else [],
        risk_level="medium" if network else "low",
        requires_approval=network,
        network="external" if network else "none",
    )
    return NodeDefinition(
        node_id=node_id,
        kind="model",
        display_name=display_name,
        description=f"Use the node reasoning model for {display_name}.",
        category=category,
        capabilities=capabilities,
        input_ports=[NodePortDefinition(id="input", label="输入", dataType="json")],
        output_ports=[NodePortDefinition(id="output", label="输出", dataType="json")],
        execution=NodeExecutionBinding(type="model", model_policy="node_reasoning"),
        permissions=permissions,
        examples=[],
        source="system",
        version="1.0.0",
    )


def _human_node(node_id: str, display_name: str, capabilities: list[str]) -> NodeDefinition:
    return NodeDefinition(
        node_id=node_id,
        kind="human",
        display_name=display_name,
        description=f"Interrupt execution and ask the user to complete: {display_name}.",
        category="human",
        capabilities=capabilities,
        input_ports=[NodePortDefinition(id="prompt-input", label="提示", dataType="text")],
        output_ports=[NodePortDefinition(id="decision-output", label="用户决定", dataType="decision")],
        execution=NodeExecutionBinding(type="human"),
        permissions=NodePermissionProfile(),
        examples=[],
        source="system",
        version="1.0.0",
    )


def _verifier_node(
    node_id: str,
    display_name: str,
    verifier_type: str,
    capabilities: list[str],
) -> NodeDefinition:
    return NodeDefinition(
        node_id=node_id,
        kind="verifier",
        display_name=display_name,
        description=f"Verify execution result: {display_name}.",
        category="verification",
        capabilities=capabilities,
        input_ports=[NodePortDefinition(id="result-input", label="结果", dataType="json")],
        output_ports=[NodePortDefinition(id="review-output", label="检查结果", dataType="json")],
        execution=NodeExecutionBinding(type="verifier", verifier_type=verifier_type),
        permissions=NodePermissionProfile(),
        examples=[],
        source="system",
        version="1.0.0",
    )


def _permissions_from_tool(tool: ToolManifestSpec) -> NodePermissionProfile:
    permissions = list(tool.permissions)
    filesystem = "none"
    if "write_project_outputs" in permissions:
        filesystem = "project_write"
    elif "read_project_files" in permissions:
        filesystem = "project_read"
    network = "external" if tool.security_policy.get("network") is True else "none"
    high_risk = {"run_local_cli", "run_python_plugin", "call_external_mcp_tool"}
    risk_level: RiskLevel = "high" if high_risk & set(permissions) else "medium" if permissions or network == "external" else "low"
    return NodePermissionProfile(
        permissions=permissions,
        risk_level=risk_level,
        requires_approval=risk_level == "high" or network == "external",
        filesystem=filesystem,
        network=network,
        sandbox="sidecar" if tool.runtime == "python_sidecar" else "none",
    )


def _deduplicate_nodes(
    nodes: list[NodeDefinition],
) -> tuple[list[NodeDefinition], list[NodeCatalogDiagnostic]]:
    seen: set[str] = set()
    unique: list[NodeDefinition] = []
    diagnostics: list[NodeCatalogDiagnostic] = []
    for node in nodes:
        if node.node_id in seen:
            diagnostics.append(
                NodeCatalogDiagnostic(
                    code="duplicate_node_id",
                    node_id=node.node_id,
                    message=f"Duplicate catalog node id: {node.node_id}",
                )
            )
            continue
        seen.add(node.node_id)
        unique.append(node)
    return unique, diagnostics
```

- [ ] **Step 4: Run catalog tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_node_catalog.py -q
Pop-Location
```

Expected: `3 passed`.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add -- python/agent_service/node_catalog.py python/tests/test_node_catalog.py
git commit -m "feat: add node catalog models"
```

## Task 2: Catalog Resolver And Deep Agent Graph Compilation

**Files:**
- Create: `python/agent_service/node_catalog_resolver.py`
- Create: `python/tests/test_node_catalog_resolver.py`
- Modify: `python/agent_service/deep_agent_models.py`
- Modify: `python/agent_service/deep_agent_graph_compile.py`
- Modify: `python/tests/test_deep_agent_graph_compile.py`

- [ ] **Step 1: Write failing resolver tests**

Create `python/tests/test_node_catalog_resolver.py`:

```python
from __future__ import annotations

import pytest

from agent_service.node_catalog import (
    NodeAvailability,
    NodeCatalogSnapshot,
    NodeDefinition,
    NodeExecutionBinding,
    NodePermissionProfile,
)
from agent_service.node_catalog_resolver import (
    NodeCatalogResolutionError,
    NodeCatalogResolver,
)


def _node(
    node_id: str,
    capabilities: list[str],
    *,
    risk_level: str = "low",
    available: bool = True,
) -> NodeDefinition:
    return NodeDefinition(
        node_id=node_id,
        kind="model",
        display_name=node_id,
        description=f"Node {node_id}.",
        category="reasoning",
        capabilities=capabilities,
        input_ports=[],
        output_ports=[],
        execution=NodeExecutionBinding(type="model", model_policy="node_reasoning"),
        permissions=NodePermissionProfile(risk_level=risk_level),
        examples=[],
        source="system",
        version="1.0.0",
        availability=NodeAvailability(
            status="available" if available else "unavailable",
            reason_code=None if available else "dependency_missing",
        ),
    )


def _snapshot(nodes: list[NodeDefinition]) -> NodeCatalogSnapshot:
    return NodeCatalogSnapshot(
        generated_at="2026-06-06T00:00:00+00:00",
        nodes=nodes,
    )


def test_resolver_uses_preferred_node_id_when_available() -> None:
    snapshot = _snapshot(
        [
            _node("document.summarize", ["document.summarize"]),
            _node("document.extract_facts", ["document.summarize"]),
        ]
    )

    resolved = NodeCatalogResolver(snapshot).resolve(
        required_capabilities=["document.summarize"],
        preferred_node_ids=["document.extract_facts"],
    )

    assert resolved.node_id == "document.extract_facts"


def test_resolver_prefers_lower_risk_for_equal_capability_match() -> None:
    snapshot = _snapshot(
        [
            _node("high", ["document.summarize"], risk_level="high"),
            _node("low", ["document.summarize"], risk_level="low"),
        ]
    )

    resolved = NodeCatalogResolver(snapshot).resolve(
        required_capabilities=["document.summarize"],
        preferred_node_ids=[],
    )

    assert resolved.node_id == "low"


def test_resolver_does_not_select_unavailable_nodes() -> None:
    snapshot = _snapshot(
        [
            _node("available", ["web.search"], available=True),
            _node("unavailable", ["web.search"], available=False),
        ]
    )

    resolved = NodeCatalogResolver(snapshot).resolve(
        required_capabilities=["web.search"],
        preferred_node_ids=["unavailable"],
    )

    assert resolved.node_id == "available"


def test_resolver_fails_for_unsupported_capability() -> None:
    snapshot = _snapshot([_node("reason", ["model.reasoning"])])

    with pytest.raises(NodeCatalogResolutionError) as error:
        NodeCatalogResolver(snapshot).resolve(
            required_capabilities=["document.unknown"],
            preferred_node_ids=[],
        )

    assert error.value.code == "unsupported_capability"
    assert error.value.capabilities == ["document.unknown"]
```

- [ ] **Step 2: Run resolver tests to verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_node_catalog_resolver.py -q
Pop-Location
```

Expected: fails with `ModuleNotFoundError: No module named 'agent_service.node_catalog_resolver'`.

- [ ] **Step 3: Add resolver implementation**

Create `python/agent_service/node_catalog_resolver.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from agent_service.node_catalog import NodeCatalogSnapshot, NodeDefinition


class NodeCatalogResolutionError(RuntimeError):
    def __init__(self, code: str, capabilities: list[str]) -> None:
        self.code = code
        self.capabilities = list(capabilities)
        super().__init__(f"{code}: {', '.join(capabilities)}")


@dataclass(frozen=True)
class NodeResolution:
    node: NodeDefinition
    reason: str

    @property
    def node_id(self) -> str:
        return self.node.node_id


class NodeCatalogResolver:
    def __init__(self, snapshot: NodeCatalogSnapshot) -> None:
        self.snapshot = snapshot

    def resolve(
        self,
        *,
        required_capabilities: list[str],
        preferred_node_ids: list[str],
    ) -> NodeResolution:
        required = [value for value in required_capabilities if value]
        preferred = [value for value in preferred_node_ids if value]
        candidates = [
            node
            for node in self.snapshot.nodes
            if node.availability.status == "available"
            and _matches_required(node, required)
        ]
        if not candidates:
            raise NodeCatalogResolutionError("unsupported_capability", required)

        ranked = sorted(
            candidates,
            key=lambda node: (
                _preferred_rank(node, preferred),
                _exact_capability_rank(node, required),
                _risk_rank(node),
                node.node_id,
            ),
        )
        selected = ranked[0]
        reason = (
            "preferred_node_id"
            if selected.node_id in preferred
            else "capability_match"
        )
        return NodeResolution(node=selected, reason=reason)


def _matches_required(node: NodeDefinition, required: list[str]) -> bool:
    if not required:
        return node.node_id == "document.summarize" or "model.reasoning" in node.capabilities
    node_keys = {node.node_id, *node.capabilities}
    return any(capability in node_keys for capability in required)


def _preferred_rank(node: NodeDefinition, preferred_node_ids: list[str]) -> int:
    if node.node_id not in preferred_node_ids:
        return 1
    return preferred_node_ids.index(node.node_id)


def _exact_capability_rank(node: NodeDefinition, required: list[str]) -> int:
    node_keys = {node.node_id, *node.capabilities}
    return 0 if all(capability in node_keys for capability in required) else 1


def _risk_rank(node: NodeDefinition) -> int:
    return {"low": 0, "medium": 1, "high": 2}[node.permissions.risk_level]
```

- [ ] **Step 4: Extend PlanStep with preferred node hints**

Modify `python/agent_service/deep_agent_models.py`:

```python
class PlanStep(DeepAgentBaseModel):
    step_id: NonEmptyStr
    title: NonEmptyStr
    objective: NonEmptyStr
    rationale: NonEmptyStr
    inputs: list[NonEmptyStr] = Field(default_factory=list)
    required_capabilities: list[NonEmptyStr] = Field(default_factory=list)
    preferred_node_ids: list[NonEmptyStr] = Field(default_factory=list)
    expected_output: NonEmptyStr
    verification_criteria: list[NonEmptyStr] = Field(default_factory=list)
    depends_on: list[NonEmptyStr] = Field(default_factory=list)
```

- [ ] **Step 5: Update compile tests for catalog binding and unsupported capability**

In `python/tests/test_deep_agent_graph_compile.py`, update the existing document binding tests so they assert `catalogNodeId` and remove the old fallback expectation:

```python
def test_compile_document_capability_uses_catalog_fixed_tool_binding() -> None:
    draft = _draft(["read"])
    document_step = draft.steps[0].model_copy(
        update={
            "required_capabilities": ["document.read"],
            "preferred_node_ids": ["document.read"],
        }
    )
    draft = draft.model_copy(update={"steps": [document_step]})

    graph = compile_agent_plan_graph(draft, task_id="task-1")

    assert graph["nodes"][0]["nodeType"] == "fixed_tool"
    assert graph["nodes"][0]["toolRef"] == "document.read_write"
    assert graph["nodes"][0]["toolBinding"] == {
        "toolId": "document.read_write",
        "operation": "read",
    }
    assert graph["nodes"][0]["metadata"]["catalogNodeId"] == "document.read"
    assert graph["nodes"][0]["metadata"]["nodeSelectionReason"] == "preferred_node_id"
    RunGraph.model_validate(graph)


def test_compile_unknown_tool_capability_fails_without_model_fallback() -> None:
    draft = _draft(["inspect"])
    document_step = draft.steps[0].model_copy(
        update={"required_capabilities": ["document.unknown_operation"]}
    )
    draft = draft.model_copy(update={"steps": [document_step]})

    with pytest.raises(NodeCatalogResolutionError) as error:
        compile_agent_plan_graph(draft, task_id="task-1")

    assert error.value.code == "unsupported_capability"
```

Add imports:

```python
import pytest

from agent_service.node_catalog_resolver import NodeCatalogResolutionError
```

- [ ] **Step 6: Replace hard-coded document bindings with resolver**

Modify `python/agent_service/deep_agent_graph_compile.py`:

```python
from agent_service.node_catalog import NodeCatalogBuilder, NodeCatalogSnapshot, NodeDefinition
from agent_service.node_catalog_resolver import NodeCatalogResolver
from agent_service.tool_registry import ToolRegistry
from agent_service.workspace import default_tool_packages_root
```

Change `compile_agent_plan_graph`:

```python
def compile_agent_plan_graph(
    draft: PlanDraft,
    *,
    task_id: str,
    node_catalog: NodeCatalogSnapshot | None = None,
) -> dict:
    catalog = node_catalog or _default_node_catalog()
    resolver = NodeCatalogResolver(catalog)
    nodes = [
        _compile_step_node(
            step,
            index=index,
            source_plan_draft_id=draft.plan_draft_id,
            resolver=resolver,
        )
        for index, step in enumerate(draft.steps)
    ]
    edges = [
        {
            "id": f"{dependency_id}->{step.step_id}",
            "source": dependency_id,
            "target": step.step_id,
        }
        for step in draft.steps
        for dependency_id in step.depends_on
    ]
    graph = {
        "graphId": f"{task_id}-deep-agent-graph",
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "generatedBy": "deep_agent_runtime",
            "sourcePlanDraftId": draft.plan_draft_id,
            "planningTraceId": task_id,
            "modelPolicy": "deep_reasoning",
            "successCriteria": list(draft.success_criteria),
            "verificationPlan": list(draft.verification_plan),
            "nodeCatalogSchemaVersion": catalog.schema_version,
        },
    }

    RunGraph.model_validate(graph)
    return graph
```

Change `_compile_step_node` to use catalog resolution:

```python
def _compile_step_node(
    step: PlanStep,
    *,
    index: int,
    source_plan_draft_id: str,
    resolver: NodeCatalogResolver,
) -> dict[str, Any]:
    resolution = resolver.resolve(
        required_capabilities=list(step.required_capabilities),
        preferred_node_ids=list(step.preferred_node_ids),
    )
    node_definition = resolution.node
    node: dict[str, Any] = {
        "nodeId": step.step_id,
        "nodeType": _graph_node_type(node_definition),
        "displayName": step.title,
        "status": "waiting",
        "inputPorts": [port.model_dump(by_alias=True) for port in node_definition.input_ports],
        "outputPorts": [port.model_dump(by_alias=True) for port in node_definition.output_ports],
        "dependencies": list(step.depends_on),
        "summary": step.objective,
        "createdBy": "agent",
        "artifactRefs": [],
        "retryCount": 0,
        "position": {"x": float(index * 240), "y": 0.0},
        "metadata": {
            "sourcePlanDraftId": source_plan_draft_id,
            "sourcePlanStepId": step.step_id,
            "rationale": step.rationale,
            "expectedOutput": step.expected_output,
            "verificationCriteria": list(step.verification_criteria),
            "requiredCapabilities": list(step.required_capabilities),
            "catalogNodeId": node_definition.node_id,
            "catalogDisplayName": node_definition.display_name,
            "nodeSelectionReason": resolution.reason,
            "executionKind": node_definition.execution.type,
            "catalogCapabilities": list(node_definition.capabilities),
            "catalogRiskLevel": node_definition.permissions.risk_level,
        },
        "permissionsRequired": list(node_definition.permissions.permissions),
    }
    _apply_execution_binding(node, node_definition)
    return node
```

Add helpers:

```python
def _default_node_catalog() -> NodeCatalogSnapshot:
    registry = ToolRegistry.from_packages_root(default_tool_packages_root())
    return NodeCatalogBuilder(tool_registry=registry).build()


def _graph_node_type(node: NodeDefinition) -> str:
    if node.kind == "tool":
        return "fixed_tool"
    if node.kind == "model":
        return "model"
    if node.kind == "output":
        return "output"
    return "planning"


def _apply_execution_binding(node: dict[str, Any], definition: NodeDefinition) -> None:
    execution = definition.execution
    if execution.type == "tool":
        node["toolRef"] = execution.tool_id
        node["toolBinding"] = {
            "toolId": execution.tool_id,
            "operation": execution.operation,
        }
        return
    if execution.type == "model":
        node["modelRef"] = execution.model_policy or "node_reasoning"
        return
    node["metadata"]["execution"] = execution.model_dump(mode="json")
```

Remove `_DOCUMENT_TOOL_BINDINGS` and `_document_tool_binding`.

- [ ] **Step 7: Run resolver and compile tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_node_catalog_resolver.py tests/test_deep_agent_graph_compile.py -q
Pop-Location
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit Task 2**

Run:

```powershell
git add -- python/agent_service/node_catalog_resolver.py python/agent_service/deep_agent_models.py python/agent_service/deep_agent_graph_compile.py python/tests/test_node_catalog_resolver.py python/tests/test_deep_agent_graph_compile.py
git commit -m "feat: resolve agent graph nodes from catalog"
```

## Task 3: Planning Context Catalog Summary

**Files:**
- Modify: `python/agent_service/context_manager.py`
- Modify: `python/agent_service/deep_agent_runtime_graph.py`
- Modify: `python/agent_service/deep_agent_planner.py`
- Modify: `python/tests/test_context_manager.py`
- Modify: `python/tests/test_deep_agent_planner.py`
- Modify: `python/tests/test_deep_agent_runtime_graph.py`

- [ ] **Step 1: Add failing context test for available nodes**

Append to `python/tests/test_context_manager.py`:

```python
def test_context_bundle_includes_catalog_node_summaries(tmp_path: Path) -> None:
    message = UserMessage(task_id="task-catalog", content="summarize a document")
    goal_spec = parse_goal_spec(message)
    registry = ToolRegistry.from_packages_root(
        Path(__file__).resolve().parents[2] / "tool-packages"
    )
    catalog = NodeCatalogBuilder(tool_registry=registry).build()

    bundle = build_context_bundle(
        message=message,
        goal_spec=goal_spec,
        project_path=str(tmp_path / "project.alita"),
        tool_registry=registry,
        node_catalog=catalog,
    )

    node_by_id = {node.node_id: node for node in bundle.available_nodes}

    assert "document.convert.markdown" in node_by_id
    assert node_by_id["document.convert.markdown"].kind == "tool"
    assert node_by_id["document.convert.markdown"].capabilities == [
        "document.convert.markdown"
    ]
    assert node_by_id["document.convert.markdown"].risk_level == "high"
```

Add imports:

```python
from agent_service.node_catalog import NodeCatalogBuilder
```

- [ ] **Step 2: Run context test to verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_context_manager.py::test_context_bundle_includes_catalog_node_summaries -q
Pop-Location
```

Expected: fails because `build_context_bundle` has no `node_catalog` argument.

- [ ] **Step 3: Add catalog summaries to ContextBundle**

Modify `python/agent_service/context_manager.py`:

```python
from agent_service.node_catalog import NodeCatalogSnapshot
```

Add model:

```python
class NodeCatalogSummary(BaseModel):
    node_id: str
    kind: str
    display_name: str
    category: str
    capabilities: list[str] = Field(default_factory=list)
    description: str
    input_ports: list[str] = Field(default_factory=list)
    output_ports: list[str] = Field(default_factory=list)
    risk_level: str
    availability: str
```

Add to `ContextBundle`:

```python
    available_nodes: list[NodeCatalogSummary] = Field(default_factory=list)
```

Add function parameter:

```python
    node_catalog: NodeCatalogSnapshot | None = None,
```

Add return field:

```python
        available_nodes=_node_summaries_from_catalog(node_catalog),
```

Add helper:

```python
def _node_summaries_from_catalog(
    node_catalog: NodeCatalogSnapshot | None,
) -> list[NodeCatalogSummary]:
    if node_catalog is None:
        return []
    return [
        NodeCatalogSummary(
            node_id=node.node_id,
            kind=node.kind,
            display_name=node.display_name,
            category=node.category,
            capabilities=list(node.capabilities),
            description=node.description,
            input_ports=[port.data_type for port in node.input_ports],
            output_ports=[port.data_type for port in node.output_ports],
            risk_level=node.permissions.risk_level,
            availability=node.availability.status,
        )
        for node in node_catalog.nodes
    ]
```

- [ ] **Step 4: Update Deep Agent runtime context build**

Modify `python/agent_service/deep_agent_runtime_graph.py` in `build_context`:

```python
def build_context(state: DeepAgentRuntimeState) -> dict[str, Any]:
    message = state["message"]
    tool_registry = ToolRegistry.from_packages_root(default_tool_packages_root())
    node_catalog = NodeCatalogBuilder(tool_registry=tool_registry).build()
    goal_spec = parse_goal_spec(message)
    context = build_context_bundle(
        message=message,
        goal_spec=goal_spec,
        project_path=state["project_path"],
        tool_registry=tool_registry,
        node_catalog=node_catalog,
        memory_records=[],
        memory_store=None,
    )
    context_bundle = context.model_dump()
    return {
        "context_bundle": context_bundle,
        "node_catalog": node_catalog.model_dump(mode="json"),
        "available_capabilities": node_catalog.available_capabilities(),
    }
```

Add import:

```python
from agent_service.node_catalog import NodeCatalogBuilder
```

Extend `DeepAgentRuntimeState`:

```python
    node_catalog: dict[str, Any]
```

Extend initial state:

```python
        "node_catalog": {},
```

- [ ] **Step 5: Add prompt test for preferred node ids**

In `python/tests/test_deep_agent_planner.py`, add or update a prompt-focused test:

```python
def test_planning_prompt_requests_preferred_node_ids() -> None:
    message = UserMessage(task_id="task-plan", content="summarize document")
    prompt = _planning_prompt(
        message,
        context_bundle={
            "available_nodes": [
                {
                    "node_id": "document.summarize",
                    "kind": "model",
                    "display_name": "文档摘要",
                    "category": "document",
                    "capabilities": ["document.summarize"],
                    "description": "Summarize a document.",
                    "input_ports": ["markdown"],
                    "output_ports": ["text"],
                    "risk_level": "low",
                    "availability": "available",
                }
            ]
        },
        revision_instructions=[],
    )

    assert "preferred_node_ids" in prompt
    assert "Use preferred_node_ids when an available node directly matches a step." in prompt
```

- [ ] **Step 6: Update planning prompt instructions**

Modify `python/agent_service/deep_agent_planner.py`:

```python
        "instructions": [
            "Return only valid JSON for PlanDraft.",
            "Use a non-empty success_criteria list.",
            "Use a non-empty steps list.",
            "Use a non-empty verification_plan list.",
            "Ensure recommended_strategy references a candidate strategyId.",
            "Ensure step depends_on values reference existing step_id values only.",
            "Use preferred_node_ids when an available node directly matches a step.",
            "Do not name nodes that are not present in context_bundle.available_nodes.",
        ],
```

Add `"preferred_node_ids"` to the prompt contract by adding it to a `step_optional_json_keys` field:

```python
        "step_optional_json_keys": [
            "preferred_node_ids",
        ],
```

- [ ] **Step 7: Run context and planner tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_context_manager.py tests/test_deep_agent_planner.py tests/test_deep_agent_runtime_graph.py -q
Pop-Location
```

Expected: selected tests pass.

- [ ] **Step 8: Commit Task 3**

Run:

```powershell
git add -- python/agent_service/context_manager.py python/agent_service/deep_agent_runtime_graph.py python/agent_service/deep_agent_planner.py python/tests/test_context_manager.py python/tests/test_deep_agent_planner.py python/tests/test_deep_agent_runtime_graph.py
git commit -m "feat: inject node catalog into deep planning"
```

## Task 4: Sidecar Catalog Endpoint

**Files:**
- Modify: `python/agent_service/app.py`
- Modify: `python/tests/test_app.py`

- [ ] **Step 1: Add failing API test**

Append to `python/tests/test_app.py`:

```python
def test_node_catalog_endpoint_returns_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV", "1")
    client = TestClient(app)

    response = client.get("/agent/node-catalog")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == 1
    node_ids = {node["node_id"] for node in payload["nodes"]}
    assert "document.convert.markdown" in node_ids
    assert "human.clarify" in node_ids
    assert "output.final_response" in node_ids
```

- [ ] **Step 2: Run API test to verify failure**

Run:

```powershell
Push-Location python
python -m pytest tests/test_app.py::test_node_catalog_endpoint_returns_snapshot -q
Pop-Location
```

Expected: fails with HTTP `404`.

- [ ] **Step 3: Add FastAPI endpoint**

Modify imports in `python/agent_service/app.py`:

```python
from agent_service.node_catalog import NodeCatalogBuilder, NodeCatalogSnapshot
from agent_service.tool_registry import ToolRegistry
from agent_service.workspace import default_tool_packages_root
```

Add endpoint after `/health`:

```python
@app.get("/agent/node-catalog", response_model=NodeCatalogSnapshot)
def node_catalog(
    _auth: None = Depends(require_sidecar_token),
) -> NodeCatalogSnapshot:
    registry = ToolRegistry.from_packages_root(default_tool_packages_root())
    return NodeCatalogBuilder(tool_registry=registry).build()
```

- [ ] **Step 4: Run API tests**

Run:

```powershell
Push-Location python
python -m pytest tests/test_app.py::test_node_catalog_endpoint_returns_snapshot -q
Pop-Location
```

Expected: `1 passed`.

- [ ] **Step 5: Commit Task 4**

Run:

```powershell
git add -- python/agent_service/app.py python/tests/test_app.py
git commit -m "feat: expose node catalog endpoint"
```

## Task 5: Frontend Catalog Types And API

**Files:**
- Modify: `src/shared/types.ts`
- Create: `src/features/nodeCatalog/nodeCatalogApi.ts`
- Create: `src/features/nodeCatalog/nodeCatalogApi.test.ts`
- Create: `src/features/nodeCatalog/useNodeCatalog.ts`
- Create: `src/features/nodeCatalog/useNodeCatalog.test.ts`

- [ ] **Step 1: Add TypeScript catalog types**

Modify `src/shared/types.ts`:

```ts
export type NodeCatalogAvailability = {
  status: "available" | "degraded" | "unavailable";
  reasonCode?: string | null;
  message?: string | null;
};

export type CatalogNodePort = {
  id: string;
  label: string;
  dataType:
    | "text"
    | "markdown"
    | "document"
    | "table"
    | "json"
    | "artifact"
    | "url"
    | "query"
    | "decision";
  required: boolean;
  multiple: boolean;
  description: string;
};

export type CatalogNodeExecution = {
  type: "tool" | "model" | "human" | "verifier" | "output";
  toolId?: string | null;
  operation?: string | null;
  modelPolicy?: string | null;
  verifierType?: string | null;
  outputType?: string | null;
};

export type CatalogNodePermissionProfile = {
  permissions: string[];
  riskLevel: "low" | "medium" | "high";
  requiresApproval: boolean;
  filesystem: "none" | "project_read" | "project_write";
  network: "none" | "external";
  sandbox: "none" | "sidecar" | "external";
};

export type NodeCatalogEntry = {
  nodeId: string;
  kind: "tool" | "model" | "human" | "verifier" | "output";
  displayName: string;
  description: string;
  category:
    | "document"
    | "web"
    | "data"
    | "reasoning"
    | "human"
    | "verification"
    | "output";
  capabilities: string[];
  inputPorts: CatalogNodePort[];
  outputPorts: CatalogNodePort[];
  execution: CatalogNodeExecution;
  permissions: CatalogNodePermissionProfile;
  examples: Array<{ title: string; input: Record<string, unknown> }>;
  source: "internal_tool" | "system" | "mcp" | "plugin";
  version: string;
  availability: NodeCatalogAvailability;
};

export type NodeCatalogSnapshot = {
  schemaVersion: number;
  generatedAt: string;
  nodes: NodeCatalogEntry[];
  diagnostics: Array<{
    code: string;
    nodeId?: string | null;
    message: string;
  }>;
  sourceSummary: {
    internalToolCount: number;
    systemNodeCount: number;
    mcpNodeCount: number;
    pluginNodeCount: number;
  };
};
```

- [ ] **Step 2: Write failing API mapping test**

Create `src/features/nodeCatalog/nodeCatalogApi.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";

import { getNodeCatalog } from "./nodeCatalogApi";

describe("node catalog API", () => {
  it("maps sidecar snake_case catalog payload to frontend camelCase", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        schema_version: 1,
        generated_at: "2026-06-06T00:00:00+00:00",
        nodes: [
          {
            node_id: "document.convert.markdown",
            kind: "tool",
            display_name: "文档转 Markdown",
            description: "Convert document.",
            category: "document",
            capabilities: ["document.convert.markdown"],
            input_ports: [
              {
                id: "document-input",
                label: "文档",
                data_type: "document",
                required: true,
                multiple: false,
                description: "",
              },
            ],
            output_ports: [],
            execution: {
              type: "tool",
              tool_id: "document.markitdown_convert",
              operation: "convert_local_file",
            },
            permissions: {
              permissions: ["read_project_files"],
              risk_level: "medium",
              requires_approval: false,
              filesystem: "project_read",
              network: "none",
              sandbox: "sidecar",
            },
            examples: [],
            source: "internal_tool",
            version: "0.1.0",
            availability: { status: "available" },
          },
        ],
        diagnostics: [],
        source_summary: {
          internal_tool_count: 1,
          system_node_count: 0,
          mcp_node_count: 0,
          plugin_node_count: 0,
        },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const catalog = await getNodeCatalog();

    expect(catalog.nodes[0].nodeId).toBe("document.convert.markdown");
    expect(catalog.nodes[0].inputPorts[0].dataType).toBe("document");
    expect(catalog.nodes[0].execution.toolId).toBe("document.markitdown_convert");
    expect(catalog.sourceSummary.internalToolCount).toBe(1);
  });
});
```

- [ ] **Step 3: Add frontend API module**

Create `src/features/nodeCatalog/nodeCatalogApi.ts`:

```ts
import { invoke } from "@tauri-apps/api/core";

import type {
  CatalogNodePort,
  NodeCatalogEntry,
  NodeCatalogSnapshot,
} from "../../shared/types";

const SIDECAR_URL = "http://127.0.0.1:8765";
const SIDECAR_TOKEN_HEADER = "X-Alita-Sidecar-Token";

export async function getNodeCatalog(): Promise<NodeCatalogSnapshot> {
  const response = await fetch(`${SIDECAR_URL}/agent/node-catalog`, {
    method: "GET",
    headers: await sidecarHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Agent sidecar returned ${response.status}`);
  }
  return toCatalogSnapshot(await response.json());
}

async function sidecarHeaders(): Promise<Record<string, string>> {
  const token = await getSidecarAuthToken();
  return token ? { [SIDECAR_TOKEN_HEADER]: token } : {};
}

async function getSidecarAuthToken(): Promise<string | null> {
  if (!("__TAURI_INTERNALS__" in globalThis)) {
    return null;
  }
  return invoke<string>("get_sidecar_auth_token");
}

function toCatalogSnapshot(payload: any): NodeCatalogSnapshot {
  return {
    schemaVersion: Number(payload.schema_version),
    generatedAt: String(payload.generated_at),
    nodes: Array.isArray(payload.nodes) ? payload.nodes.map(toCatalogNode) : [],
    diagnostics: Array.isArray(payload.diagnostics)
      ? payload.diagnostics.map((diagnostic: any) => ({
          code: String(diagnostic.code),
          nodeId: diagnostic.node_id ?? null,
          message: String(diagnostic.message),
        }))
      : [],
    sourceSummary: {
      internalToolCount: Number(payload.source_summary?.internal_tool_count ?? 0),
      systemNodeCount: Number(payload.source_summary?.system_node_count ?? 0),
      mcpNodeCount: Number(payload.source_summary?.mcp_node_count ?? 0),
      pluginNodeCount: Number(payload.source_summary?.plugin_node_count ?? 0),
    },
  };
}

function toCatalogNode(node: any): NodeCatalogEntry {
  return {
    nodeId: String(node.node_id),
    kind: node.kind,
    displayName: String(node.display_name),
    description: String(node.description),
    category: node.category,
    capabilities: Array.isArray(node.capabilities)
      ? node.capabilities.map(String)
      : [],
    inputPorts: Array.isArray(node.input_ports)
      ? node.input_ports.map(toPort)
      : [],
    outputPorts: Array.isArray(node.output_ports)
      ? node.output_ports.map(toPort)
      : [],
    execution: {
      type: node.execution?.type,
      toolId: node.execution?.tool_id ?? null,
      operation: node.execution?.operation ?? null,
      modelPolicy: node.execution?.model_policy ?? null,
      verifierType: node.execution?.verifier_type ?? null,
      outputType: node.execution?.output_type ?? null,
    },
    permissions: {
      permissions: Array.isArray(node.permissions?.permissions)
        ? node.permissions.permissions.map(String)
        : [],
      riskLevel: node.permissions?.risk_level ?? "low",
      requiresApproval: Boolean(node.permissions?.requires_approval),
      filesystem: node.permissions?.filesystem ?? "none",
      network: node.permissions?.network ?? "none",
      sandbox: node.permissions?.sandbox ?? "none",
    },
    examples: Array.isArray(node.examples) ? node.examples : [],
    source: node.source,
    version: String(node.version),
    availability: {
      status: node.availability?.status ?? "unavailable",
      reasonCode: node.availability?.reason_code ?? null,
      message: node.availability?.message ?? null,
    },
  };
}

function toPort(port: any): CatalogNodePort {
  return {
    id: String(port.id),
    label: String(port.label),
    dataType: port.data_type,
    required: Boolean(port.required),
    multiple: Boolean(port.multiple),
    description: String(port.description ?? ""),
  };
}
```

- [ ] **Step 4: Add hook tests and hook implementation**

Create `src/features/nodeCatalog/useNodeCatalog.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
  nodeCatalogFailed,
  nodeCatalogLoaded,
  nodeCatalogLoading,
} from "./useNodeCatalog";
import type { NodeCatalogSnapshot } from "../../shared/types";

describe("node catalog state helpers", () => {
  it("transitions through loading loaded and failed states", () => {
    const initial = { catalog: null, loading: false, error: null };
    const loading = nodeCatalogLoading(initial);
    const catalog = {
      schemaVersion: 1,
      generatedAt: "2026-06-06T00:00:00+00:00",
      nodes: [],
      diagnostics: [],
      sourceSummary: {
        internalToolCount: 0,
        systemNodeCount: 0,
        mcpNodeCount: 0,
        pluginNodeCount: 0,
      },
    } satisfies NodeCatalogSnapshot;
    const loaded = nodeCatalogLoaded(loading, catalog);
    const failed = nodeCatalogFailed(loaded, "failed");

    expect(loading.loading).toBe(true);
    expect(loaded.catalog).toBe(catalog);
    expect(loaded.loading).toBe(false);
    expect(failed.error).toBe("failed");
  });
});
```

Create `src/features/nodeCatalog/useNodeCatalog.ts`:

```ts
import { useCallback, useEffect, useState } from "react";

import { getNodeCatalog } from "./nodeCatalogApi";
import type { NodeCatalogSnapshot } from "../../shared/types";

export type NodeCatalogState = {
  catalog: NodeCatalogSnapshot | null;
  loading: boolean;
  error: string | null;
};

export function nodeCatalogLoading(state: NodeCatalogState): NodeCatalogState {
  return { ...state, loading: true, error: null };
}

export function nodeCatalogLoaded(
  state: NodeCatalogState,
  catalog: NodeCatalogSnapshot,
): NodeCatalogState {
  return { ...state, catalog, loading: false, error: null };
}

export function nodeCatalogFailed(
  state: NodeCatalogState,
  error: string,
): NodeCatalogState {
  return { ...state, loading: false, error };
}

export function useNodeCatalog() {
  const [state, setState] = useState<NodeCatalogState>({
    catalog: null,
    loading: false,
    error: null,
  });

  const reload = useCallback(async () => {
    setState(nodeCatalogLoading);
    try {
      const catalog = await getNodeCatalog();
      setState((current) => nodeCatalogLoaded(current, catalog));
      return catalog;
    } catch (error) {
      setState((current) => nodeCatalogFailed(current, String(error)));
      return null;
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { state, reload };
}
```

- [ ] **Step 5: Run frontend API tests**

Run:

```powershell
npm test -- --run src/features/nodeCatalog/nodeCatalogApi.test.ts src/features/nodeCatalog/useNodeCatalog.test.ts
```

Expected: selected tests pass.

- [ ] **Step 6: Commit Task 5**

Run:

```powershell
git add -- src/shared/types.ts src/features/nodeCatalog/nodeCatalogApi.ts src/features/nodeCatalog/nodeCatalogApi.test.ts src/features/nodeCatalog/useNodeCatalog.ts src/features/nodeCatalog/useNodeCatalog.test.ts
git commit -m "feat: add frontend node catalog API"
```

## Task 6: Read-Only Node Catalog Panel

**Files:**
- Create: `src/features/nodeCatalog/NodeCatalogPanel.tsx`
- Create: `src/features/nodeCatalog/NodeCatalogPanel.test.tsx`
- Modify: `src/app/App.tsx`
- Modify: `src/app/app.css`

- [ ] **Step 1: Write panel rendering tests**

Create `src/features/nodeCatalog/NodeCatalogPanel.test.tsx`:

```tsx
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { NodeCatalogPanel } from "./NodeCatalogPanel";
import type { NodeCatalogSnapshot } from "../../shared/types";

const catalog: NodeCatalogSnapshot = {
  schemaVersion: 1,
  generatedAt: "2026-06-06T00:00:00+00:00",
  nodes: [
    {
      nodeId: "document.convert.markdown",
      kind: "tool",
      displayName: "文档转 Markdown",
      description: "把文档转换为 Markdown。",
      category: "document",
      capabilities: ["document.convert.markdown"],
      inputPorts: [{ id: "in", label: "文档", dataType: "document", required: true, multiple: false, description: "" }],
      outputPorts: [{ id: "out", label: "Markdown", dataType: "markdown", required: true, multiple: false, description: "" }],
      execution: { type: "tool", toolId: "document.markitdown_convert", operation: "convert_local_file" },
      permissions: {
        permissions: ["read_project_files"],
        riskLevel: "medium",
        requiresApproval: false,
        filesystem: "project_read",
        network: "none",
        sandbox: "sidecar",
      },
      examples: [],
      source: "internal_tool",
      version: "0.1.0",
      availability: { status: "available" },
    },
    {
      nodeId: "human.clarify",
      kind: "human",
      displayName: "澄清问题",
      description: "向用户澄清缺失信息。",
      category: "human",
      capabilities: ["human.clarify"],
      inputPorts: [],
      outputPorts: [],
      execution: { type: "human" },
      permissions: {
        permissions: [],
        riskLevel: "low",
        requiresApproval: false,
        filesystem: "none",
        network: "none",
        sandbox: "none",
      },
      examples: [],
      source: "system",
      version: "1.0.0",
      availability: { status: "available" },
    },
  ],
  diagnostics: [],
  sourceSummary: {
    internalToolCount: 1,
    systemNodeCount: 1,
    mcpNodeCount: 0,
    pluginNodeCount: 0,
  },
};

describe("NodeCatalogPanel", () => {
  it("renders catalog search categories and node details", () => {
    const markup = renderToStaticMarkup(
      <NodeCatalogPanel
        catalog={catalog}
        error={null}
        loading={false}
        onClose={() => undefined}
        onReload={() => undefined}
      />,
    );

    expect(markup).toContain("节点库");
    expect(markup).toContain("文档转 Markdown");
    expect(markup).toContain("document.convert.markdown");
    expect(markup).toContain("read_project_files");
    expect(markup).toContain("澄清问题");
  });

  it("renders loading and error states", () => {
    const markup = renderToStaticMarkup(
      <NodeCatalogPanel
        catalog={null}
        error="load failed"
        loading={true}
        onClose={() => undefined}
        onReload={() => undefined}
      />,
    );

    expect(markup).toContain("正在加载节点库");
    expect(markup).toContain("load failed");
  });
});
```

- [ ] **Step 2: Implement panel**

Create `src/features/nodeCatalog/NodeCatalogPanel.tsx`:

```tsx
import { useMemo, useState } from "react";

import type { NodeCatalogEntry, NodeCatalogSnapshot } from "../../shared/types";

type NodeCatalogPanelProps = {
  catalog: NodeCatalogSnapshot | null;
  loading: boolean;
  error: string | null;
  onClose(): void;
  onReload(): void;
};

const categoryLabels: Record<NodeCatalogEntry["category"], string> = {
  document: "文档",
  web: "联网研究",
  data: "数据/办公",
  reasoning: "模型推理",
  human: "人机交互",
  verification: "验证",
  output: "输出",
};

export function NodeCatalogPanel({
  catalog,
  loading,
  error,
  onClose,
  onReload,
}: NodeCatalogPanelProps) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<NodeCatalogEntry["category"] | "all">("all");
  const nodes = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return (catalog?.nodes ?? []).filter((node) => {
      const categoryMatches = category === "all" || node.category === category;
      const queryMatches =
        !normalizedQuery ||
        [
          node.nodeId,
          node.displayName,
          node.description,
          ...node.capabilities,
        ]
          .join(" ")
          .toLowerCase()
          .includes(normalizedQuery);
      return categoryMatches && queryMatches;
    });
  }, [catalog, category, query]);

  return (
    <aside className="nodeCatalogPanel" aria-label="节点库">
      <header className="nodeCatalogHeader">
        <div>
          <p className="nodeCatalogKicker">Node Catalog</p>
          <h2>节点库</h2>
        </div>
        <div className="nodeCatalogActions">
          <button type="button" onClick={onReload}>刷新</button>
          <button type="button" onClick={onClose}>关闭</button>
        </div>
      </header>
      {loading ? <p className="nodeCatalogState">正在加载节点库</p> : null}
      {error ? <p className="nodeCatalogState nodeCatalogError">{error}</p> : null}
      <div className="nodeCatalogControls">
        <input
          aria-label="搜索节点"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索节点、能力或说明"
          type="search"
          value={query}
        />
        <select
          aria-label="节点分类"
          onChange={(event) =>
            setCategory(event.target.value as NodeCatalogEntry["category"] | "all")
          }
          value={category}
        >
          <option value="all">全部</option>
          {Object.entries(categoryLabels).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </div>
      <div className="nodeCatalogList">
        {nodes.map((node) => (
          <article className="nodeCatalogItem" key={node.nodeId}>
            <header>
              <div>
                <h3>{node.displayName}</h3>
                <p>{node.nodeId}</p>
              </div>
              <span className={`nodeCatalogStatus nodeCatalogStatus-${node.availability.status}`}>
                {node.availability.status}
              </span>
            </header>
            <p>{node.description}</p>
            <dl>
              <div>
                <dt>分类</dt>
                <dd>{categoryLabels[node.category]}</dd>
              </div>
              <div>
                <dt>能力</dt>
                <dd>{node.capabilities.join(", ") || "无"}</dd>
              </div>
              <div>
                <dt>输入</dt>
                <dd>{node.inputPorts.map((port) => port.label).join(", ") || "无"}</dd>
              </div>
              <div>
                <dt>输出</dt>
                <dd>{node.outputPorts.map((port) => port.label).join(", ") || "无"}</dd>
              </div>
              <div>
                <dt>权限</dt>
                <dd>{node.permissions.permissions.join(", ") || "无"}</dd>
              </div>
              <div>
                <dt>来源</dt>
                <dd>{node.source}</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
    </aside>
  );
}
```

- [ ] **Step 3: Add App entry**

Modify `src/app/App.tsx`:

```tsx
import { NodeCatalogPanel } from "../features/nodeCatalog/NodeCatalogPanel";
import { useNodeCatalog } from "../features/nodeCatalog/useNodeCatalog";
```

Inside `App` component state:

```tsx
  const [nodeCatalogOpen, setNodeCatalogOpen] = useState(false);
  const nodeCatalog = useNodeCatalog();
```

Add a top-bar or workbench button near preferences:

```tsx
<button
  className="topBarButton"
  onClick={() => setNodeCatalogOpen(true)}
  type="button"
>
  节点库
</button>
```

Render panel near existing dialogs:

```tsx
{nodeCatalogOpen ? (
  <NodeCatalogPanel
    catalog={nodeCatalog.state.catalog}
    error={nodeCatalog.state.error}
    loading={nodeCatalog.state.loading}
    onClose={() => setNodeCatalogOpen(false)}
    onReload={() => void nodeCatalog.reload()}
  />
) : null}
```

- [ ] **Step 4: Add panel CSS**

Modify `src/app/app.css`:

```css
.nodeCatalogPanel {
  background: #ffffff;
  border-left: 1px solid #d7dee8;
  bottom: 0;
  box-shadow: -12px 0 30px rgba(15, 23, 42, 0.12);
  display: flex;
  flex-direction: column;
  max-width: 520px;
  position: fixed;
  right: 0;
  top: 0;
  width: min(520px, 100vw);
  z-index: 50;
}

.nodeCatalogHeader,
.nodeCatalogActions,
.nodeCatalogControls {
  align-items: center;
  display: flex;
  gap: 8px;
}

.nodeCatalogHeader {
  border-bottom: 1px solid #e2e8f0;
  justify-content: space-between;
  padding: 16px;
}

.nodeCatalogKicker {
  color: #64748b;
  font-size: 12px;
  margin: 0;
}

.nodeCatalogHeader h2,
.nodeCatalogItem h3 {
  margin: 0;
}

.nodeCatalogState {
  color: #475569;
  margin: 12px 16px 0;
}

.nodeCatalogError {
  color: #b91c1c;
}

.nodeCatalogControls {
  border-bottom: 1px solid #e2e8f0;
  padding: 12px 16px;
}

.nodeCatalogControls input,
.nodeCatalogControls select {
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font: inherit;
  min-height: 34px;
  padding: 6px 8px;
}

.nodeCatalogControls input {
  flex: 1;
}

.nodeCatalogList {
  display: grid;
  gap: 10px;
  overflow: auto;
  padding: 12px 16px 20px;
}

.nodeCatalogItem {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px;
}

.nodeCatalogItem header {
  align-items: start;
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.nodeCatalogItem p {
  color: #475569;
  margin: 6px 0;
}

.nodeCatalogItem dl {
  display: grid;
  gap: 6px;
  margin: 8px 0 0;
}

.nodeCatalogItem dl div {
  display: grid;
  grid-template-columns: 58px 1fr;
  gap: 8px;
}

.nodeCatalogItem dt {
  color: #64748b;
}

.nodeCatalogItem dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.nodeCatalogStatus {
  border-radius: 999px;
  font-size: 12px;
  padding: 3px 8px;
}

.nodeCatalogStatus-available {
  background: #dcfce7;
  color: #166534;
}

.nodeCatalogStatus-degraded {
  background: #fef3c7;
  color: #92400e;
}

.nodeCatalogStatus-unavailable {
  background: #fee2e2;
  color: #991b1b;
}
```

- [ ] **Step 5: Run panel tests**

Run:

```powershell
npm test -- --run src/features/nodeCatalog/NodeCatalogPanel.test.tsx
npm run typecheck
```

Expected: selected test passes and typecheck passes.

- [ ] **Step 6: Commit Task 6**

Run:

```powershell
git add -- src/features/nodeCatalog/NodeCatalogPanel.tsx src/features/nodeCatalog/NodeCatalogPanel.test.tsx src/app/App.tsx src/app/app.css
git commit -m "feat: add read-only node catalog panel"
```

## Task 7: Canvas Catalog Provenance

**Files:**
- Modify: `src/shared/types.ts`
- Modify: `src/features/canvas/NodePopover.tsx`
- Modify: `src/features/canvas/NodePopover.test.tsx`

- [ ] **Step 1: Extend metadata typing**

Modify `src/shared/types.ts`:

```ts
export type PlanNodeProvenance = {
  sourcePlanDraftId?: string;
  sourcePlanStepId?: string;
  rationale?: string;
  expectedOutput?: string;
  verificationCriteria?: string[];
  requiredCapabilities?: string[];
  catalogNodeId?: string;
  catalogDisplayName?: string;
  catalogCapabilities?: string[];
  catalogRiskLevel?: "low" | "medium" | "high";
  executionKind?: "tool" | "model" | "human" | "verifier" | "output";
  nodeSelectionReason?: string;
};
```

- [ ] **Step 2: Add failing NodePopover test**

Append to `src/features/canvas/NodePopover.test.tsx`:

```tsx
it("renders catalog provenance when graph node has catalog metadata", () => {
  const markup = renderPopover({
    ...toolNode,
    metadata: {
      catalogNodeId: "document.convert.markdown",
      catalogDisplayName: "文档转 Markdown",
      catalogCapabilities: ["document.convert.markdown"],
      catalogRiskLevel: "high",
      executionKind: "tool",
      nodeSelectionReason: "preferred_node_id",
    },
  });

  expect(markup).toContain("节点库来源");
  expect(markup).toContain("document.convert.markdown");
  expect(markup).toContain("文档转 Markdown");
  expect(markup).toContain("preferred_node_id");
  expect(markup).toContain("high");
});
```

- [ ] **Step 3: Render provenance in NodePopover**

Modify `src/features/canvas/NodePopover.tsx` inside `NodePopover`:

```tsx
  const catalogNodeId = readableString(node.metadata?.catalogNodeId);
  const catalogDisplayName = readableString(node.metadata?.catalogDisplayName);
  const nodeSelectionReason = readableString(node.metadata?.nodeSelectionReason);
  const executionKind = readableString(node.metadata?.executionKind);
  const catalogRiskLevel = readableString(node.metadata?.catalogRiskLevel);
```

Add to the `<dl>` after “将调用的功能”:

```tsx
        {catalogNodeId ? (
          <div>
            <dt>节点库来源</dt>
            <dd>
              <div>{catalogDisplayName ?? catalogNodeId}</div>
              <div>{catalogNodeId}</div>
              {executionKind ? <div>执行类型: {executionKind}</div> : null}
              {catalogRiskLevel ? <div>风险: {catalogRiskLevel}</div> : null}
              {nodeSelectionReason ? <div>选择原因: {nodeSelectionReason}</div> : null}
              {renderStringList(node.metadata?.catalogCapabilities)}
            </dd>
          </div>
        ) : null}
```

- [ ] **Step 4: Run popover tests**

Run:

```powershell
npm test -- --run src/features/canvas/NodePopover.test.tsx
npm run typecheck
```

Expected: selected test and typecheck pass.

- [ ] **Step 5: Commit Task 7**

Run:

```powershell
git add -- src/shared/types.ts src/features/canvas/NodePopover.tsx src/features/canvas/NodePopover.test.tsx
git commit -m "feat: show catalog provenance on graph nodes"
```

## Task 8: Verification Gates And Traceability

**Files:**
- Modify: `docs/test-traceability/alita-v035-feature-test-map.md`
- Create: `docs/superpowers/progress/2026-06-06-node-catalog-progress.md`

- [ ] **Step 1: Run focused Python test gate**

Run:

```powershell
Push-Location python
python -m pytest tests/test_node_catalog.py tests/test_node_catalog_resolver.py tests/test_context_manager.py tests/test_deep_agent_models.py tests/test_deep_agent_planner.py tests/test_deep_agent_graph_compile.py tests/test_app.py -q
Pop-Location
```

Expected: selected tests pass.

- [ ] **Step 2: Run focused frontend test gate**

Run:

```powershell
npm test -- --run src/features/nodeCatalog/nodeCatalogApi.test.ts src/features/nodeCatalog/useNodeCatalog.test.ts src/features/nodeCatalog/NodeCatalogPanel.test.tsx src/features/canvas/NodePopover.test.tsx
npm run typecheck
```

Expected: selected tests pass and typecheck passes.

- [ ] **Step 3: Run broader regression gates**

Run:

```powershell
Push-Location python
python -m pytest tests/test_agent_runtime_engine_deep_agent.py tests/test_deep_agent_runtime_graph.py tests/test_agent_plan_compile.py tests/test_execution_graph.py -q
Pop-Location
npm test -- --run
npm run typecheck
```

Expected: selected Python tests pass, all frontend tests pass, and typecheck passes.

- [ ] **Step 4: Update traceability map**

Add a row to `docs/test-traceability/alita-v035-feature-test-map.md`:

```markdown
| Shared Node Catalog for Agent planning and frontend display | `python/tests/test_node_catalog.py`, `python/tests/test_node_catalog_resolver.py`, `python/tests/test_deep_agent_graph_compile.py`, `python/tests/test_app.py`, `src/features/nodeCatalog/*.test.ts*`, `src/features/canvas/NodePopover.test.tsx` | none | planned A/B/D catalog eval cases | Node Catalog panel smoke in desktop app |
```

- [ ] **Step 5: Write progress note**

Create `docs/superpowers/progress/2026-06-06-node-catalog-progress.md`:

```markdown
# Node Catalog Progress

## Status

Implemented the first Node Catalog vertical slice:

- backend `NodeDefinition` and `NodeCatalogSnapshot`;
- internal tool and system node catalog builder;
- resolver-based Deep Agent graph compilation;
- planning context catalog summaries;
- `/agent/node-catalog` sidecar endpoint;
- frontend read-only node library;
- canvas catalog provenance display.

## Verification

- `python -m pytest tests/test_node_catalog.py tests/test_node_catalog_resolver.py tests/test_context_manager.py tests/test_deep_agent_models.py tests/test_deep_agent_planner.py tests/test_deep_agent_graph_compile.py tests/test_app.py -q`
- `npm test -- --run src/features/nodeCatalog/nodeCatalogApi.test.ts src/features/nodeCatalog/useNodeCatalog.test.ts src/features/nodeCatalog/NodeCatalogPanel.test.tsx src/features/canvas/NodePopover.test.tsx`
- `npm run typecheck`

## Remaining Work

- Add real web/data tool-backed nodes.
- Add desktop smoke coverage for the Node Catalog panel.
- Decide when to expose manual drag-in behavior.
```

- [ ] **Step 6: Commit Task 8**

Run:

```powershell
git add -- docs/test-traceability/alita-v035-feature-test-map.md docs/superpowers/progress/2026-06-06-node-catalog-progress.md
git commit -m "docs: record node catalog verification"
```

## Final Verification

- [ ] **Step 1: Check working tree**

Run:

```powershell
git status --short
```

Expected: no uncommitted files.

- [ ] **Step 2: Run full Python test gate**

Run:

```powershell
Push-Location python
python -m pytest -q
Pop-Location
```

Expected: all Python tests pass.

- [ ] **Step 3: Run frontend gate**

Run:

```powershell
npm test -- --run
npm run typecheck
```

Expected: all frontend tests pass and typecheck passes.

## Self-Review Notes

- Spec coverage: tasks cover backend catalog models, resolver, planning context, graph compile, sidecar API, frontend read-only node library, canvas provenance, tests, and traceability.
- Scope check: manual composition, user nodes, hot reload, plugin marketplace, and full MCP node productization remain excluded.
- Type consistency: backend uses snake_case Pydantic fields; frontend API maps to camelCase before React consumes the snapshot.
- Risk callout: Task 2 changes graph compilation behavior from fallback model nodes to explicit catalog resolution. Keep the unsupported-capability tests strict so regressions are visible.
