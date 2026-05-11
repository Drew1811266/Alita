# Alita Agent Harness Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前硬编码节点执行系统升级为第一阶段 Alita Agent Harness：工具注册可查询、工具调用受网关约束、节点结果可验证、失败事件标准化，并为临时脚本节点保留安全审查状态。

**Architecture:** 第一阶段主要落在 Python sidecar 和少量前端/Rust 元数据扩展。Python sidecar 新增 `ToolRegistry`、`ToolInvocationGateway`、`ResultVerifier` 和标准错误模型；现有 `DocumentFlowExecutor` 继续保留，但工具调用和节点完成判断必须通过 Harness 组件。前端继续只展示状态，不直接执行工具。

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest, Tauri 2, Rust, React, TypeScript, Vitest.

**Repo Note:** 当前 `D:\Software Project\Alita` 不是 git 仓库，`git status` 会失败。因此本计划里的“提交”步骤在当前环境改为“记录检查点并运行对应验证命令”。如果项目后续初始化为 git 仓库，再恢复正常 commit。

---

## Scope

本计划实现 Harness 第一阶段，不开放真实临时脚本执行，不做独立工具沙箱，不做在线工具市场，不替换 LangGraph。第一阶段完成后，Agent 仍然可以用现有文档流程，但工具和节点执行会走更明确的 Harness 边界。

## File Structure

### Create

- `D:\Software Project\Alita\python\agent_service\tool_registry.py`  
  Python sidecar 的工具注册表，读取 `tool-packages/*/manifest.json`，并提供工具查询、启用过滤和 operation 查询。

- `D:\Software Project\Alita\python\agent_service\schema_validation.py`  
  轻量 JSON schema 校验器，覆盖当前 manifest 需要的 `required`、`type`、`enum` 和对象属性校验。

- `D:\Software Project\Alita\python\agent_service\harness_errors.py`  
  标准 Harness 错误类型，统一错误码、错误消息和事件 payload。

- `D:\Software Project\Alita\python\agent_service\result_verifier.py`  
  节点结果验证器，检查必需文本值、artifact 存在性和空输出。

- `D:\Software Project\Alita\python\tests\test_tool_registry.py`  
  Tool Registry 单元测试。

- `D:\Software Project\Alita\python\tests\test_schema_validation.py`  
  schema 校验测试。

- `D:\Software Project\Alita\python\tests\test_result_verifier.py`  
  Result Verifier 单元测试。

### Modify

- `D:\Software Project\Alita\python\agent_service\tool_execution.py`  
  把现有 `ToolExecutor` 升级为受 manifest 约束的工具调用网关。

- `D:\Software Project\Alita\python\agent_service\execution.py`  
  接入 Tool Registry、工具启用检查、标准错误事件和 Result Verifier。

- `D:\Software Project\Alita\python\agent_service\schemas.py`  
  扩展节点安全状态和错误 payload 所需字段。

- `D:\Software Project\Alita\python\agent_service\graph.py`  
  生成节点图时为临时脚本节点保留 `scriptReview` 状态；文档流程继续使用固定工具节点。

- `D:\Software Project\Alita\python\tests\test_tool_execution.py`  
  覆盖 operation/schema/禁用工具/未知工具等 Harness 网关行为。

- `D:\Software Project\Alita\python\tests\test_execution.py`  
  覆盖结果验证失败、标准错误事件、工具注册预检。

- `D:\Software Project\Alita\python\tests\test_graph.py`  
  覆盖临时脚本节点安全状态协议。

- `D:\Software Project\Alita\src\shared\events.ts`  
  前端事件类型加入可选 `errorCode`。

- `D:\Software Project\Alita\src\shared\types.ts`  
  确认或扩展 `ScriptReviewState` 和 `NodeRunRecord.errorCode`。

- `D:\Software Project\Alita\src\app\backendEvents.ts`  
  reducer 保存标准错误码。

- `D:\Software Project\Alita\src\features\canvas\NodePopover.tsx`  
  节点弹窗展示最近错误码和临时脚本安全审查状态。

- `D:\Software Project\Alita\src\features\canvas\NodePopover.test.tsx`  
  覆盖错误码和脚本审查状态展示。

---

## Task 1: Python Tool Registry

**Files:**

- Create: `D:\Software Project\Alita\python\agent_service\tool_registry.py`
- Create: `D:\Software Project\Alita\python\tests\test_tool_registry.py`

- [ ] **Step 1: 写 Tool Registry 失败测试**

在 `python\tests\test_tool_registry.py` 写入：

```python
from __future__ import annotations

import json
from pathlib import Path

from agent_service.tool_registry import ToolRegistry


def write_manifest(root: Path, tool_id: str, *, operation: str = "convert_local_file") -> None:
    package_dir = root / tool_id.replace(".", "_")
    package_dir.mkdir(parents=True)
    (package_dir / "manifest.json").write_text(
        json.dumps(
            {
                "tool_id": tool_id,
                "name": "测试工具",
                "description": "测试工具描述",
                "version": "0.1.0",
                "source_type": "python_plugin",
                "license": "internal",
                "runtime": "python_sidecar",
                "entrypoint": "python/tools/test_tool.py",
                "capabilities": ["document.convert.markdown"],
                "operations": [{"name": operation, "description": "转换文件"}],
                "input_schema": {
                    "type": "object",
                    "required": ["operation", "input_path"],
                    "properties": {
                        "operation": {"type": "string", "enum": [operation]},
                        "input_path": {"type": "string"},
                    },
                },
                "output_schema": {"type": "object"},
                "permissions": ["read_project_files"],
                "examples": [{"title": "示例", "input": {"operation": operation}}],
                "error_codes": ["conversion_failed"],
                "timeout_policy": {"seconds": 60},
                "artifact_policy": {"writes_to": "artifacts/converted"},
                "security_policy": {"network": False, "plugins": False},
                "node_templates": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_loads_manifests_and_virtual_document_input_tool(tmp_path: Path) -> None:
    write_manifest(tmp_path, "document.markitdown_convert")

    registry = ToolRegistry.from_packages_root(tmp_path)

    assert registry.get("document.markitdown_convert").tool_id == "document.markitdown_convert"
    assert registry.get("document.receive_attachment").tool_id == "document.receive_attachment"
    assert registry.has_operation("document.markitdown_convert", "convert_local_file")


def test_filters_disabled_tools(tmp_path: Path) -> None:
    write_manifest(tmp_path, "document.markitdown_convert")
    registry = ToolRegistry.from_packages_root(tmp_path)

    enabled = registry.enabled_tools(disabled_tool_ids=["document.markitdown_convert"])

    assert "document.receive_attachment" in {tool.tool_id for tool in enabled}
    assert "document.markitdown_convert" not in {tool.tool_id for tool in enabled}


def test_unknown_tool_raises_key_error(tmp_path: Path) -> None:
    registry = ToolRegistry.from_packages_root(tmp_path)

    try:
        registry.get("missing.tool")
    except KeyError as error:
        assert "missing.tool" in str(error)
    else:
        raise AssertionError("missing tool should raise KeyError")
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m pytest python\tests\test_tool_registry.py -v
```

Expected: FAIL，原因是 `agent_service.tool_registry` 不存在。

- [ ] **Step 3: 实现 Tool Registry**

创建 `python\agent_service\tool_registry.py`：

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolOperationSpec:
    name: str
    description: str


@dataclass(frozen=True)
class ToolManifestSpec:
    tool_id: str
    name: str
    description: str
    version: str
    source_type: str
    license: str
    runtime: str | None
    entrypoint: str
    capabilities: list[str]
    operations: list[ToolOperationSpec]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    permissions: list[str]
    error_codes: list[str]
    timeout_policy: dict[str, Any]
    artifact_policy: dict[str, Any]
    security_policy: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self, tools: list[ToolManifestSpec]) -> None:
        self._tools = {tool.tool_id: tool for tool in tools}

    @classmethod
    def from_packages_root(cls, packages_root: str | Path) -> "ToolRegistry":
        root = Path(packages_root)
        tools = [_virtual_document_input_tool()]
        if root.exists():
            for manifest_path in sorted(root.glob("*/manifest.json")):
                tools.append(_load_manifest(manifest_path))
        return cls(tools)

    def get(self, tool_id: str) -> ToolManifestSpec:
        try:
            return self._tools[tool_id]
        except KeyError as error:
            raise KeyError(f"unknown tool: {tool_id}") from error

    def has_operation(self, tool_id: str, operation: str) -> bool:
        tool = self.get(tool_id)
        return any(spec.name == operation for spec in tool.operations)

    def enabled_tools(self, disabled_tool_ids: list[str]) -> list[ToolManifestSpec]:
        disabled = set(disabled_tool_ids)
        return [tool for tool in self._tools.values() if tool.tool_id not in disabled]


def _load_manifest(path: Path) -> ToolManifestSpec:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ToolManifestSpec(
        tool_id=str(data["tool_id"]),
        name=str(data["name"]),
        description=str(data["description"]),
        version=str(data["version"]),
        source_type=str(data["source_type"]),
        license=str(data["license"]),
        runtime=data.get("runtime"),
        entrypoint=str(data["entrypoint"]),
        capabilities=[str(value) for value in data.get("capabilities", [])],
        operations=[
            ToolOperationSpec(
                name=str(operation["name"]),
                description=str(operation.get("description", "")),
            )
            for operation in data.get("operations", [])
        ],
        input_schema=dict(data["input_schema"]),
        output_schema=dict(data["output_schema"]),
        permissions=[str(value) for value in data.get("permissions", [])],
        error_codes=[str(value) for value in data.get("error_codes", [])],
        timeout_policy=dict(data.get("timeout_policy", {})),
        artifact_policy=dict(data.get("artifact_policy", {})),
        security_policy=dict(data.get("security_policy", {})),
    )


def _virtual_document_input_tool() -> ToolManifestSpec:
    return ToolManifestSpec(
        tool_id="document.receive_attachment",
        name="文档输入",
        description="接收用户在聊天区提供的文档附件。",
        version="0.1.0",
        source_type="virtual_system_tool",
        license="internal",
        runtime="python_sidecar",
        entrypoint="agent_service.execution.DocumentFlowExecutor",
        capabilities=["document.receive_attachment"],
        operations=[ToolOperationSpec(name="receive_attachment", description="接收附件")],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        permissions=["read_project_files"],
        error_codes=["missing_attachment"],
        timeout_policy={"seconds": 1},
        artifact_policy={"writes_to": "none"},
        security_policy={"network": False, "plugins": False},
    )
```

- [ ] **Step 4: 运行 Tool Registry 测试**

Run:

```powershell
python -m pytest python\tests\test_tool_registry.py -v
```

Expected: PASS，3 个测试通过。

- [ ] **Step 5: 运行 Python 全量测试**

Run:

```powershell
python -m pytest python\tests -v
```

Expected: PASS。

- [ ] **Step 6: 记录检查点**

记录：`Task 1 complete: Python Tool Registry added and tested.`

---

## Task 2: Lightweight Schema Validation

**Files:**

- Create: `D:\Software Project\Alita\python\agent_service\schema_validation.py`
- Create: `D:\Software Project\Alita\python\tests\test_schema_validation.py`

- [ ] **Step 1: 写 schema 校验失败测试**

在 `python\tests\test_schema_validation.py` 写入：

```python
from agent_service.schema_validation import validate_json_schema_subset


def test_accepts_required_string_and_enum_values() -> None:
    schema = {
        "type": "object",
        "required": ["operation", "input_path"],
        "properties": {
            "operation": {"type": "string", "enum": ["convert_local_file"]},
            "input_path": {"type": "string"},
        },
    }

    validate_json_schema_subset(
        schema,
        {"operation": "convert_local_file", "input_path": "input.docx"},
    )


def test_rejects_missing_required_field() -> None:
    schema = {"type": "object", "required": ["input_path"], "properties": {}}

    try:
        validate_json_schema_subset(schema, {})
    except ValueError as error:
        assert "missing_required:input_path" in str(error)
    else:
        raise AssertionError("missing required field should fail")


def test_rejects_wrong_type_and_invalid_enum() -> None:
    schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["convert_local_file"]},
            "input_path": {"type": "string"},
        },
    }

    for payload, expected in [
        ({"operation": "delete_file", "input_path": "input.docx"}, "invalid_enum:operation"),
        ({"operation": "convert_local_file", "input_path": 123}, "invalid_type:input_path"),
    ]:
        try:
            validate_json_schema_subset(schema, payload)
        except ValueError as error:
            assert expected in str(error)
        else:
            raise AssertionError(f"{expected} should fail")
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m pytest python\tests\test_schema_validation.py -v
```

Expected: FAIL，原因是 `agent_service.schema_validation` 不存在。

- [ ] **Step 3: 实现轻量校验器**

创建 `python\agent_service\schema_validation.py`：

```python
from __future__ import annotations

from typing import Any


def validate_json_schema_subset(schema: dict[str, Any], payload: dict[str, Any]) -> None:
    if schema.get("type") == "object" and not isinstance(payload, dict):
        raise ValueError("invalid_type:root")

    for field_name in schema.get("required", []):
        if field_name not in payload:
            raise ValueError(f"missing_required:{field_name}")

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return

    for field_name, field_schema in properties.items():
        if field_name not in payload:
            continue
        if not isinstance(field_schema, dict):
            continue
        value = payload[field_name]
        expected_type = field_schema.get("type")
        if expected_type == "string" and not isinstance(value, str):
            raise ValueError(f"invalid_type:{field_name}")
        if expected_type == "number" and not isinstance(value, int | float):
            raise ValueError(f"invalid_type:{field_name}")
        if expected_type == "boolean" and not isinstance(value, bool):
            raise ValueError(f"invalid_type:{field_name}")
        enum_values = field_schema.get("enum")
        if isinstance(enum_values, list) and value not in enum_values:
            raise ValueError(f"invalid_enum:{field_name}")
```

- [ ] **Step 4: 运行 schema 测试**

Run:

```powershell
python -m pytest python\tests\test_schema_validation.py -v
```

Expected: PASS，3 个测试通过。

- [ ] **Step 5: 运行 Python 全量测试**

Run:

```powershell
python -m pytest python\tests -v
```

Expected: PASS。

- [ ] **Step 6: 记录检查点**

记录：`Task 2 complete: lightweight schema validation added.`

---

## Task 3: Harness Error Model

**Files:**

- Create: `D:\Software Project\Alita\python\agent_service\harness_errors.py`
- Modify: `D:\Software Project\Alita\python\tests\test_execution.py`

- [ ] **Step 1: 写标准错误 payload 失败测试**

在 `python\tests\test_execution.py` 增加：

```python
def test_failed_events_include_standard_error_code(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("正文", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)
    request.disabled_tool_ids = ["document.receive_attachment"]

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    failed = [event for event in events if event.type == "task.failed"][-1]
    assert failed.payload["errorCode"] == "tool_disabled"
    assert "document.receive_attachment" in failed.payload["error"]
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m pytest python\tests\test_execution.py::test_failed_events_include_standard_error_code -v
```

Expected: FAIL，原因是 `task.failed` payload 还没有 `errorCode`。

- [ ] **Step 3: 创建 HarnessError**

创建 `python\agent_service\harness_errors.py`：

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HarnessError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message

    def to_payload(self) -> dict[str, str]:
        return {"errorCode": self.code, "error": self.message}


def harness_error_payload(error: Exception) -> dict[str, str]:
    if isinstance(error, HarnessError):
        return error.to_payload()
    return {"errorCode": "execution_failed", "error": str(error)}
```

- [ ] **Step 4: 在 execution 中使用 HarnessError**

修改 `python\agent_service\execution.py`：

```python
from agent_service.harness_errors import HarnessError, harness_error_payload
```

把禁用工具分支中的：

```python
error = f"tool disabled: {node.toolRef}"
```

改为：

```python
error = HarnessError("tool_disabled", f"tool disabled: {node.toolRef}")
```

该分支里的 `record["error"]` 使用 `str(error)`，事件 payload 使用：

```python
payload={"nodeId": node.nodeId, **harness_error_payload(error)}
```

`task.failed` payload 使用：

```python
payload={
    "taskId": request.task_id,
    "runId": request.run_id,
    **harness_error_payload(error),
}
```

通用 `except Exception as error` 分支也用 `harness_error_payload(error)` 生成事件 payload。

- [ ] **Step 5: 运行目标测试**

Run:

```powershell
python -m pytest python\tests\test_execution.py::test_failed_events_include_standard_error_code -v
```

Expected: PASS。

- [ ] **Step 6: 运行 Python 全量测试**

Run:

```powershell
python -m pytest python\tests -v
```

Expected: PASS。

- [ ] **Step 7: 记录检查点**

记录：`Task 3 complete: standard Harness errors added.`

---

## Task 4: Tool Invocation Gateway

**Files:**

- Modify: `D:\Software Project\Alita\python\agent_service\tool_execution.py`
- Modify: `D:\Software Project\Alita\python\tests\test_tool_execution.py`

- [ ] **Step 1: 写网关失败测试**

在 `python\tests\test_tool_execution.py` 增加：

```python
from agent_service.harness_errors import HarnessError
from agent_service.tool_registry import ToolRegistry


def test_tool_executor_rejects_operation_not_declared_by_manifest(tmp_path) -> None:
    registry = ToolRegistry.from_packages_root("tool-packages")
    executor = ToolExecutor(registry=registry)

    invocation = ToolInvocation(
        tool_id="document.markitdown_convert",
        operation="delete_file",
        arguments={"operation": "delete_file", "input_path": "a.md", "output_path": "b.md"},
        project_path=str(tmp_path / "project.alita"),
        allowed_roots=[str(tmp_path)],
    )

    try:
        executor.run(invocation)
    except HarnessError as error:
        assert error.code == "unsupported_operation"
    else:
        raise AssertionError("unsupported operation should fail")


def test_tool_executor_validates_manifest_input_schema(tmp_path) -> None:
    registry = ToolRegistry.from_packages_root("tool-packages")
    executor = ToolExecutor(registry=registry)

    invocation = ToolInvocation(
        tool_id="document.markitdown_convert",
        operation="convert_local_file",
        arguments={"operation": "convert_local_file", "output_path": "b.md"},
        project_path=str(tmp_path / "project.alita"),
        allowed_roots=[str(tmp_path)],
    )

    try:
        executor.run(invocation)
    except HarnessError as error:
        assert error.code == "invalid_tool_input"
        assert "input_path" in error.message
    else:
        raise AssertionError("invalid input should fail")
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m pytest python\tests\test_tool_execution.py -v
```

Expected: FAIL，原因是 `ToolExecutor` 还没有接收 registry，也没有返回 HarnessError。

- [ ] **Step 3: 升级 ToolExecutor 构造函数和预检**

修改 `python\agent_service\tool_execution.py`：

```python
from agent_service.harness_errors import HarnessError
from agent_service.schema_validation import validate_json_schema_subset
from agent_service.tool_registry import ToolRegistry


class ToolExecutor:
    def __init__(self, *, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or ToolRegistry.from_packages_root("tool-packages")

    def run(self, invocation: ToolInvocation) -> ToolResult:
        try:
            manifest = self.registry.get(invocation.tool_id)
        except KeyError as error:
            raise HarnessError("unsupported_tool", str(error)) from error

        if not self.registry.has_operation(invocation.tool_id, invocation.operation):
            raise HarnessError(
                "unsupported_operation",
                f"unsupported operation for {invocation.tool_id}: {invocation.operation}",
            )

        arguments = {"operation": invocation.operation, **invocation.arguments}
        try:
            validate_json_schema_subset(manifest.input_schema, arguments)
        except ValueError as error:
            raise HarnessError("invalid_tool_input", str(error)) from error

        if invocation.tool_id == "document.markitdown_convert":
            return self._run_markitdown(invocation)

        raise HarnessError("unsupported_tool", f"unsupported tool: {invocation.tool_id}")
```

保留 `_run_markitdown` 内的实际执行逻辑。

- [ ] **Step 4: 运行工具执行测试**

Run:

```powershell
python -m pytest python\tests\test_tool_execution.py -v
```

Expected: PASS。

- [ ] **Step 5: 运行 Python 全量测试**

Run:

```powershell
python -m pytest python\tests -v
```

Expected: PASS。

- [ ] **Step 6: 记录检查点**

记录：`Task 4 complete: Tool Invocation Gateway validates manifest operations and input schema.`

---

## Task 5: Execution Preflight Against Tool Registry

**Files:**

- Modify: `D:\Software Project\Alita\python\agent_service\execution.py`
- Modify: `D:\Software Project\Alita\python\tests\test_execution.py`

- [ ] **Step 1: 写未知工具预检失败测试**

在 `python\tests\test_execution.py` 增加：

```python
def test_rejects_graph_with_unknown_tool_ref_before_running_nodes(tmp_path: Path) -> None:
    request = build_request(
        tmp_path,
        nodes=[
            build_node(
                "unknown-tool-node",
                "fixed_tool",
                [],
                tool_ref="missing.tool",
            )
        ],
    )

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    assert "node.running" not in [event.type for event in events]
    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "unsupported_tool"
    assert "missing.tool" in events[-1].payload["error"]
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m pytest python\tests\test_execution.py::test_rejects_graph_with_unknown_tool_ref_before_running_nodes -v
```

Expected: FAIL，原因是当前执行器不会预检 toolRef。

- [ ] **Step 3: 增加执行前工具预检**

修改 `python\agent_service\execution.py`：

```python
from agent_service.harness_errors import HarnessError, harness_error_payload
from agent_service.tool_registry import ToolRegistry
```

在 `run_graph_events` 签名中增加：

```python
tool_registry: ToolRegistry | None = None,
```

在拓扑排序后、启动 run registry 前增加：

```python
registry_for_tools = tool_registry or ToolRegistry.from_packages_root("tool-packages")
try:
    _validate_graph_tools(request, registry_for_tools)
except HarnessError as error:
    yield AgentEvent(
        type="task.failed",
        payload={
            "taskId": request.task_id,
            "runId": request.run_id,
            **harness_error_payload(error),
        },
    )
    return
```

在文件底部增加：

```python
def _validate_graph_tools(request: RunGraphRequest, registry: ToolRegistry) -> None:
    disabled = set(request.disabled_tool_ids)
    for node in request.graph.nodes:
        if node.nodeType != "fixed_tool" or not node.toolRef:
            continue
        try:
            registry.get(node.toolRef)
        except KeyError as error:
            raise HarnessError("unsupported_tool", str(error)) from error
        if node.toolRef in disabled:
            raise HarnessError("tool_disabled", f"tool disabled: {node.toolRef}")
```

- [ ] **Step 4: 运行目标测试**

Run:

```powershell
python -m pytest python\tests\test_execution.py::test_rejects_graph_with_unknown_tool_ref_before_running_nodes -v
```

Expected: PASS。

- [ ] **Step 5: 运行 Python 全量测试**

Run:

```powershell
python -m pytest python\tests -v
```

Expected: PASS。

- [ ] **Step 6: 记录检查点**

记录：`Task 5 complete: graph tool references are preflighted against Tool Registry.`

---

## Task 6: Result Verifier

**Files:**

- Create: `D:\Software Project\Alita\python\agent_service\result_verifier.py`
- Create: `D:\Software Project\Alita\python\tests\test_result_verifier.py`
- Modify: `D:\Software Project\Alita\python\agent_service\execution.py`
- Modify: `D:\Software Project\Alita\python\tests\test_execution.py`

- [ ] **Step 1: 写 Result Verifier 单元测试**

创建 `python\tests\test_result_verifier.py`：

```python
from pathlib import Path

from agent_service.execution import NodeOutput
from agent_service.harness_errors import HarnessError
from agent_service.result_verifier import ResultVerifier


def test_accepts_existing_artifact_and_required_value(tmp_path: Path) -> None:
    artifact = tmp_path / "report.md"
    artifact.write_text("# Report", encoding="utf-8")

    ResultVerifier().verify(
        "file-export",
        NodeOutput(artifacts=[str(artifact)], values={"artifact": str(artifact)}),
    )


def test_rejects_missing_artifact(tmp_path: Path) -> None:
    try:
        ResultVerifier().verify(
            "file-export",
            NodeOutput(artifacts=[str(tmp_path / "missing.md")], values={"artifact": "x"}),
        )
    except HarnessError as error:
        assert error.code == "missing_artifact"
    else:
        raise AssertionError("missing artifact should fail")


def test_rejects_empty_required_model_output() -> None:
    try:
        ResultVerifier().verify("content-organize", NodeOutput(values={"outline": ""}))
    except HarnessError as error:
        assert error.code == "empty_node_output"
    else:
        raise AssertionError("empty outline should fail")
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m pytest python\tests\test_result_verifier.py -v
```

Expected: FAIL，原因是 `agent_service.result_verifier` 不存在。

- [ ] **Step 3: 实现 ResultVerifier**

创建 `python\agent_service\result_verifier.py`：

```python
from __future__ import annotations

from pathlib import Path

from agent_service.execution import NodeOutput
from agent_service.harness_errors import HarnessError


REQUIRED_VALUE_BY_NODE = {
    "document-input": "paths",
    "document-parse": "text",
    "content-organize": "outline",
    "report-generate": "report",
    "file-export": "artifact",
}


class ResultVerifier:
    def verify(self, node_id: str, output: NodeOutput) -> None:
        required_value = REQUIRED_VALUE_BY_NODE.get(node_id)
        if required_value:
            value = output.values.get(required_value, "")
            if not value.strip():
                raise HarnessError(
                    "empty_node_output",
                    f"node {node_id} returned empty value: {required_value}",
                )

        for artifact in output.artifacts:
            if not Path(artifact).is_file():
                raise HarnessError("missing_artifact", f"artifact does not exist: {artifact}")
```

If this creates an import cycle because `result_verifier.py` imports `NodeOutput` from `execution.py`, move `NodeOutput` into a new file `python\agent_service\node_output.py`, update imports in `execution.py`, `result_verifier.py`, and tests, then rerun the same tests.

- [ ] **Step 4: 运行 Result Verifier 测试**

Run:

```powershell
python -m pytest python\tests\test_result_verifier.py -v
```

Expected: PASS。

- [ ] **Step 5: 写执行器集成失败测试**

在 `python\tests\test_execution.py` 增加：

```python
def test_execution_fails_when_result_verifier_rejects_empty_output(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("正文", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)

    class EmptyContentExecutor(FakeNodeExecutor):
        def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
            if node_id == "content-organize":
                return NodeOutput(values={"outline": ""})
            return NodeOutput(values={"text": "ok", "paths": str(source), "report": "ok", "artifact": "ok"})

    events = list(run_graph_events(request, executor=EmptyContentExecutor()))

    assert events[-1].type == "task.failed"
    assert events[-1].payload["errorCode"] == "empty_node_output"
```

- [ ] **Step 6: 在 execution 中调用 ResultVerifier**

修改 `python\agent_service\execution.py`：

```python
from agent_service.result_verifier import ResultVerifier
```

在 `run_graph_events` 签名中增加：

```python
result_verifier: ResultVerifier | None = None,
```

在创建 `outputs` 后增加：

```python
verifier = result_verifier or ResultVerifier()
```

在：

```python
output = node_executor.run(node.nodeId, dependency_outputs)
```

之后立即增加：

```python
verifier.verify(node.nodeId, output)
```

- [ ] **Step 7: 运行执行器集成测试**

Run:

```powershell
python -m pytest python\tests\test_execution.py::test_execution_fails_when_result_verifier_rejects_empty_output -v
```

Expected: PASS。

- [ ] **Step 8: 运行 Python 全量测试**

Run:

```powershell
python -m pytest python\tests -v
```

Expected: PASS。

- [ ] **Step 9: 记录检查点**

记录：`Task 6 complete: Result Verifier integrated into node execution.`

---

## Task 7: Temporary Script Safety State Protocol

**Files:**

- Modify: `D:\Software Project\Alita\python\agent_service\schemas.py`
- Modify: `D:\Software Project\Alita\python\agent_service\graph.py`
- Modify: `D:\Software Project\Alita\python\tests\test_graph.py`
- Modify: `D:\Software Project\Alita\src\shared\types.ts`

- [ ] **Step 1: 写临时脚本安全状态失败测试**

在 `python\tests\test_graph.py` 增加：

```python
def test_temporary_script_node_includes_script_review_state() -> None:
    events = run_agent(
        UserMessage(
            task_id="task-script",
            content="如果没有合适工具，就生成一个临时脚本节点处理文件",
            attachments=[],
        )
    )

    graph_events = [event for event in events if event.type == "node_graph.created"]
    if not graph_events:
        return

    temporary_nodes = [
        node
        for node in graph_events[0].payload["graph"]["nodes"]
        if node["nodeType"] == "temporary_placeholder"
    ]
    for node in temporary_nodes:
        assert node["scriptReview"]["status"] == "not_reviewed"
        assert "临时脚本节点当前仅可审查" in node["scriptReview"]["summary"]
```

This test allows no temporary nodes for current flows, but enforces protocol when a temporary node appears.

- [ ] **Step 2: 运行测试确认当前行为**

Run:

```powershell
python -m pytest python\tests\test_graph.py::test_temporary_script_node_includes_script_review_state -v
```

Expected: PASS if no temporary node is generated, or FAIL if an existing temporary node lacks `scriptReview`.

- [ ] **Step 3: 扩展 Python schema**

修改 `python\agent_service\schemas.py`：

```python
class ScriptReviewState(BaseModel):
    status: Literal["not_reviewed", "reviewing", "approved", "rejected"] = "not_reviewed"
    summary: str
    permissions: list[str] = Field(default_factory=list)
```

在 `GraphNode` 中增加：

```python
scriptReview: ScriptReviewState | None = None
```

- [ ] **Step 4: 确认前端类型已有对应结构**

检查 `src\shared\types.ts` 中存在：

```typescript
export type ScriptReviewState = {
  status: "not_reviewed" | "reviewing" | "approved" | "rejected";
  summary: string;
  permissions: string[];
};
```

如果 `AgentNode` 中缺少 `scriptReview?: ScriptReviewState;`，补上。

- [ ] **Step 5: 运行 schema 和图生成测试**

Run:

```powershell
python -m pytest python\tests\test_graph.py -v
npm run frontend:lint
```

Expected: PASS。

- [ ] **Step 6: 记录检查点**

记录：`Task 7 complete: temporary script safety state protocol is represented in backend and frontend types.`

---

## Task 8: Frontend Error and Safety State Display

**Files:**

- Modify: `D:\Software Project\Alita\src\shared\events.ts`
- Modify: `D:\Software Project\Alita\src\shared\types.ts`
- Modify: `D:\Software Project\Alita\src\app\backendEvents.ts`
- Modify: `D:\Software Project\Alita\src\features\canvas\NodePopover.tsx`
- Modify: `D:\Software Project\Alita\src\features\canvas\NodePopover.test.tsx`

- [ ] **Step 1: 写 NodePopover 失败测试**

在 `src\features\canvas\NodePopover.test.tsx` 增加：

```tsx
it("shows node error code and script review state", () => {
  const node = buildNode({
    nodeType: "temporary_placeholder",
    status: "needs_permission",
    lastRun: {
      nodeRunId: "run-1-temp-script",
      runId: "run-1",
      nodeId: "temp-script",
      status: "failed",
      startedAt: "2026-05-10T00:00:00.000Z",
      completedAt: "2026-05-10T00:00:01.000Z",
      artifactRefs: [],
      error: "tool disabled: document.markitdown_convert",
      errorCode: "tool_disabled",
    },
    scriptReview: {
      status: "not_reviewed",
      summary: "临时脚本节点当前仅可审查，尚不能执行。",
      permissions: ["read_project_files"],
    },
  });

  render(<NodePopover node={node} onClose={() => undefined} />);

  expect(screen.getByText("tool_disabled")).toBeInTheDocument();
  expect(screen.getByText("临时脚本节点当前仅可审查，尚不能执行。")).toBeInTheDocument();
  expect(screen.getByText("read_project_files")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
npm run frontend:test -- src/features/canvas/NodePopover.test.tsx
```

Expected: FAIL，原因是 UI 还没有展示错误码或脚本审查状态。

- [ ] **Step 3: 扩展前端类型和事件 reducer**

在 `src\shared\types.ts` 中扩展：

```typescript
export type NodeRunRecord = {
  nodeRunId: string;
  runId: string;
  nodeId: string;
  status: NodeStatus;
  startedAt: string;
  completedAt?: string;
  artifactRefs: string[];
  error?: string;
  errorCode?: string;
};
```

在 `src\shared\events.ts` 中让 `node.failed` 和 `task.failed` payload 包含可选：

```typescript
errorCode?: string;
```

在 `src\app\backendEvents.ts` 中保存 `node.run_recorded.payload.record.errorCode` 到 `node.lastRun.errorCode`。

- [ ] **Step 4: 修改 NodePopover 展示**

在 `src\features\canvas\NodePopover.tsx` 的运行详情区域增加：

```tsx
{node.lastRun?.errorCode ? (
  <>
    <dt>错误码</dt>
    <dd>{node.lastRun.errorCode}</dd>
  </>
) : null}
{node.scriptReview ? (
  <>
    <dt>安全审查</dt>
    <dd>{node.scriptReview.summary}</dd>
    <dt>请求权限</dt>
    <dd>{node.scriptReview.permissions.join("、") || "无"}</dd>
  </>
) : null}
```

- [ ] **Step 5: 运行前端目标测试**

Run:

```powershell
npm run frontend:test -- src/features/canvas/NodePopover.test.tsx
```

Expected: PASS。

- [ ] **Step 6: 运行前端全量测试和类型检查**

Run:

```powershell
npm run frontend:lint
npm run frontend:test
```

Expected: PASS。

- [ ] **Step 7: 记录检查点**

记录：`Task 8 complete: frontend displays Harness error codes and script review state.`

---

## Task 9: Update Harness Verification Document

**Files:**

- Modify: `D:\Software Project\Alita\docs\mvp-verification.md`
- Modify: `D:\Software Project\Alita\docs\superpowers\specs\2026-05-10-alita-agent-harness-design.md`

- [ ] **Step 1: 补充手动验收项**

在 `docs\mvp-verification.md` 增加 Harness 第一阶段验收：

```markdown
## Alita Agent Harness Phase 1 验收

1. 打开首选项，禁用 MarkItDown 工具。
2. 创建或打开工程，发送带文档附件的处理请求。
3. 点击运行流程。
4. 预期：流程不会执行被禁用工具，聊天区或节点状态显示失败，错误码为 `tool_disabled`。
5. 重新启用 MarkItDown 工具，再运行流程。
6. 预期：文档转 Markdown 节点生成 artifact，空输出或缺失 artifact 会被 Result Verifier 拦截。
7. 打开节点弹窗。
8. 预期：最近运行详情能看到错误码或 artifact 信息。
```

- [ ] **Step 2: 更新 Harness 设计文档当前状态**

在 `docs\superpowers\specs\2026-05-10-alita-agent-harness-design.md` 的“当前实现状态”中，把已完成的 Phase 1 能力列入：

```markdown
- Python Tool Registry。
- Tool Invocation Gateway。
- Result Verifier。
- 标准 Harness 错误码。
- 前端节点弹窗展示错误码和临时脚本安全审查状态。
```

- [ ] **Step 3: 做文档未完成标记检查**

Run:

```powershell
$patterns = @('TO' + 'DO', 'TB' + 'D', '待' + '定', '占位' + '符', 'FIX' + 'ME')
Select-String -Path docs\mvp-verification.md,docs\superpowers\specs\2026-05-10-alita-agent-harness-design.md -Pattern $patterns
```

Expected: Exit code 1，代表没有匹配项。

- [ ] **Step 4: 记录检查点**

记录：`Task 9 complete: Harness verification docs updated.`

---

## Task 10: Full Verification and Rebuild

**Files:**

- No source files should be changed in this task unless verification exposes a real defect.

- [ ] **Step 1: 停止旧进程**

Run:

```powershell
Get-Process | Where-Object { $_.ProcessName -in @('alita','alita-agent-sidecar','llama-server') } | Stop-Process -Force
```

Expected: Exit code 0。

- [ ] **Step 2: 运行 Python 全量测试**

Run:

```powershell
python -m pytest python\tests -v
```

Expected: PASS。

- [ ] **Step 3: 运行前端类型检查和测试**

Run:

```powershell
npm run frontend:lint
npm run frontend:test
```

Expected: PASS。

- [ ] **Step 4: 运行 Rust 测试**

Run:

```powershell
cargo test
```

Working directory:

```text
D:\Software Project\Alita\src-tauri
```

Expected: PASS。`agent_client_tests` 中如果仍有 dead code warning，只要测试 exit code 为 0，可以记录为非阻塞警告。

- [ ] **Step 5: 构建 Python sidecar**

Run:

```powershell
.\scripts\build-sidecar.ps1
```

Working directory:

```text
D:\Software Project\Alita
```

Expected: Exit code 0，并生成：

```text
D:\Software Project\Alita\src-tauri\binaries\alita-agent-sidecar-x86_64-pc-windows-msvc.exe
```

- [ ] **Step 6: 构建 Windows 桌面安装包**

Run:

```powershell
npm run build
```

Expected: Exit code 0，并生成：

```text
D:\Software Project\Alita\src-tauri\target\release\bundle\nsis\Alita_0.1.0_x64-setup.exe
```

- [ ] **Step 7: 启动 release exe 手动冒烟测试**

Run:

```powershell
Start-Process -FilePath 'D:\Software Project\Alita\src-tauri\target\release\alita.exe'
```

Expected:

- Windows 软件窗口打开。
- 首选项能正常打开。
- 工具列表能显示 MarkItDown。
- 创建或打开工程后，聊天区和节点画布能显示。

- [ ] **Step 8: 记录最终检查点**

记录：

```text
Harness Phase 1 verification complete:
- Python tests passed
- Frontend lint/test passed
- Rust tests passed
- sidecar build passed
- Windows build passed
- release smoke test passed
```

---

## Self-Review Checklist

- Spec coverage: 本计划覆盖 Tool Registry、Tool Invocation Gateway、Execution Orchestrator 安全预检、Safety Gate 的禁用工具拦截、Result Verifier、标准错误码、Run Journal 兼容、临时脚本安全状态预留和前端展示。
- Type consistency: `ToolRegistry`、`ToolManifestSpec`、`ToolExecutor`、`ToolInvocation`、`ResultVerifier`、`HarnessError`、`errorCode`、`scriptReview` 在任务之间名称一致。
- Scope control: 本计划不执行真实临时脚本、不实现独立沙箱、不做工具市场、不替换 LangGraph。
- Verification coverage: 每个任务都有目标测试，最后有 Python、Rust、前端、sidecar 和 Windows build 全量验证。


