# 节点流程执行系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让右侧节点流程图从“执行计划”升级为可运行的第一版执行系统，支持文档输入、文档解析、本地模型处理、分支汇合、导出产物和实时节点状态更新。

**Architecture:** 第一版执行引擎放在 Python sidecar 中，因为文档工具、LangGraph 和本地模型客户端已经在 Python 侧。前端通过 SSE 调用新的流程运行接口，接收 `node.running`、`node.completed`、`node.failed`、`artifact.created`、`task.completed` 等事件并更新右侧节点画布。

**Tech Stack:** Tauri 2, React, TypeScript, FastAPI, Python, LangGraph, llama.cpp OpenAI-compatible API, Vitest, pytest.

---

## 文件结构

- Create: `python/agent_service/execution.py`
  - 负责节点图校验、拓扑执行、节点输入输出传递、节点运行事件生成。
- Modify: `python/agent_service/schemas.py`
  - 增加执行流程请求模型 `RunGraphRequest`、`GraphNode`、`GraphEdge`、`RunAttachment`。
- Modify: `python/agent_service/app.py`
  - 增加 `/agent/graph/run/stream` SSE 接口。
- Modify: `python/tests/test_execution.py`
  - 覆盖拓扑排序、分支汇合、文档流程成功执行、失败节点事件。
- Modify: `python/tests/test_app.py`
  - 覆盖新 SSE 运行接口。
- Modify: `src/shared/types.ts`
  - 增加 `ArtifactRef`、`NodeRunSummary`，给节点弹窗展示运行结果预留结构。
- Modify: `src/shared/events.ts`
  - 如有必要，补齐 `node.completed` 和 `artifact.created` payload 字段。
- Modify: `src/features/task/useTaskEvents.ts`
  - 增加 `runNodeGraphStream`，复用现有 SSE parser。
- Modify: `src/app/backendEvents.ts`
  - 处理节点运行、完成、失败、产物创建、任务完成事件。
- Modify: `src/app/App.tsx`
  - 新增 `handleRunGraph`，传给画布组件。
- Modify: `src/features/canvas/NodeCanvas.tsx`
  - 增加 `运行流程` 按钮、运行中禁用态。
- Modify: `src/features/canvas/NodePopover.tsx`
  - 展示节点产物、错误和最近运行摘要。
- Create: `src/features/canvas/NodeCanvas.test.tsx`
  - 覆盖运行按钮渲染和点击。
- Modify: `src/app/backendEvents.test.ts`
  - 覆盖节点状态事件 reducer。

---

### Task 1: Python 执行请求模型

**Files:**
- Modify: `python/agent_service/schemas.py`
- Test: `python/tests/test_execution.py`

- [ ] **Step 1: 写失败测试**

```python
from pathlib import Path

from agent_service.execution import run_graph_events
from agent_service.schemas import RunGraphRequest


def test_rejects_graph_with_missing_dependency(tmp_path: Path) -> None:
    request = RunGraphRequest(
        task_id="task-1",
        project_path=str(tmp_path / "project.alita"),
        attachments=[],
        graph={
            "graphId": "graph-1",
            "nodes": [
                {
                    "nodeId": "document-parse",
                    "nodeType": "fixed_tool",
                    "displayName": "解析文档",
                    "status": "waiting",
                    "inputPorts": [],
                    "outputPorts": [],
                    "dependencies": ["missing-node"],
                    "toolRef": "document.extract_text",
                    "summary": "读取文档正文。",
                    "createdBy": "agent",
                    "artifactRefs": [],
                    "retryCount": 0,
                    "position": {"x": 0, "y": 0},
                }
            ],
            "edges": [],
        },
    )

    events = list(run_graph_events(request))

    assert events[0].type == "task.failed"
    assert "missing-node" in events[0].payload["error"]
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest python/tests/test_execution.py::test_rejects_graph_with_missing_dependency -v`

Expected: FAIL，原因是 `agent_service.execution` 或 `RunGraphRequest` 尚不存在。

- [ ] **Step 3: 实现请求模型**

在 `python/agent_service/schemas.py` 增加：

```python
from typing import Any, Literal


class RunAttachment(Attachment):
    pass


class GraphNode(BaseModel):
    nodeId: str
    nodeType: Literal["fixed_tool", "model", "output", "temporary_placeholder"]
    displayName: str
    status: str
    inputPorts: list[dict[str, Any]] = Field(default_factory=list)
    outputPorts: list[dict[str, Any]] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    toolRef: str | None = None
    modelRef: str | None = None
    summary: str
    createdBy: str
    artifactRefs: list[str] = Field(default_factory=list)
    retryCount: int = 0
    position: dict[str, float]


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str


class RunGraph(BaseModel):
    graphId: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class RunGraphRequest(BaseModel):
    task_id: str
    project_path: str
    graph: RunGraph
    attachments: list[RunAttachment] = Field(default_factory=list)
```

- [ ] **Step 4: 实现最小执行入口**

创建 `python/agent_service/execution.py`：

```python
from __future__ import annotations

from collections.abc import Iterator

from agent_service.schemas import AgentEvent, RunGraphRequest


def run_graph_events(request: RunGraphRequest) -> Iterator[AgentEvent]:
    node_ids = {node.nodeId for node in request.graph.nodes}
    for node in request.graph.nodes:
        for dependency in node.dependencies:
            if dependency not in node_ids:
                yield AgentEvent(
                    type="task.failed",
                    payload={
                        "taskId": request.task_id,
                        "error": f"节点 {node.nodeId} 依赖不存在: {dependency}",
                    },
                )
                return

    yield AgentEvent(type="task.completed", payload={"taskId": request.task_id})
```

- [ ] **Step 5: 运行测试并确认通过**

Run: `python -m pytest python/tests/test_execution.py::test_rejects_graph_with_missing_dependency -v`

Expected: PASS。

---

### Task 2: 拓扑执行和分支汇合

**Files:**
- Modify: `python/agent_service/execution.py`
- Test: `python/tests/test_execution.py`

- [ ] **Step 1: 写失败测试**

```python
def test_runs_nodes_after_all_dependencies_complete(tmp_path: Path) -> None:
    request = build_request(
        tmp_path,
        nodes=[
            build_node("document-input", "fixed_tool", [], tool_ref="document.receive_attachment"),
            build_node("document-parse", "fixed_tool", ["document-input"], tool_ref="document.extract_text"),
            build_node("content-organize", "model", ["document-parse"], model_ref="local-content-organizer"),
            build_node("report-generate", "model", ["document-parse"], model_ref="local-report-writer"),
            build_node("file-export", "output", ["content-organize", "report-generate"]),
        ],
    )

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    running_node_ids = [
        event.payload["nodeId"]
        for event in events
        if event.type == "node.running"
    ]
    assert running_node_ids == [
        "document-input",
        "document-parse",
        "content-organize",
        "report-generate",
        "file-export",
    ]
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest python/tests/test_execution.py::test_runs_nodes_after_all_dependencies_complete -v`

Expected: FAIL，原因是 `run_graph_events` 还没有执行节点。

- [ ] **Step 3: 增加执行器协议和拓扑排序**

在 `python/agent_service/execution.py` 中实现：

```python
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class NodeOutput:
    artifacts: list[str] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)


class NodeExecutor(Protocol):
    def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
        ...


class EmptyNodeExecutor:
    def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
        return NodeOutput(values={"text": node_id})


def _topological_nodes(request: RunGraphRequest):
    nodes_by_id = {node.nodeId: node for node in request.graph.nodes}
    ordered = []
    completed: set[str] = set()

    while len(ordered) < len(request.graph.nodes):
        ready = [
            node
            for node in request.graph.nodes
            if node.nodeId not in completed
            and all(dependency in completed for dependency in node.dependencies)
        ]
        if not ready:
            raise ValueError("节点流程存在循环依赖或不可满足依赖")
        for node in ready:
            ordered.append(node)
            completed.add(node.nodeId)

    return ordered
```

并让 `run_graph_events` 接收 `executor: NodeExecutor | None = None`，按 `_topological_nodes` 逐个执行。

- [ ] **Step 4: 运行测试并确认通过**

Run: `python -m pytest python/tests/test_execution.py::test_runs_nodes_after_all_dependencies_complete -v`

Expected: PASS。

---

### Task 3: 文档流程节点执行器

**Files:**
- Modify: `python/agent_service/execution.py`
- Test: `python/tests/test_execution.py`

- [ ] **Step 1: 写失败测试**

```python
def test_document_flow_exports_markdown_artifact(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("# 标题\n\n正文内容", encoding="utf-8")
    request = build_document_flow_request(tmp_path, source)

    events = list(run_graph_events(request, model_client=FakeModelClient()))

    artifact_events = [event for event in events if event.type == "artifact.created"]
    assert len(artifact_events) == 1
    exported_path = Path(artifact_events[0].payload["path"])
    assert exported_path.exists()
    assert exported_path.suffix == ".md"
    assert "整理结果" in exported_path.read_text(encoding="utf-8")
    assert events[-1].type == "task.completed"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest python/tests/test_execution.py::test_document_flow_exports_markdown_artifact -v`

Expected: FAIL，原因是还没有真实文档节点执行器。

- [ ] **Step 3: 实现固定工具、模型、输出节点**

实现 `DocumentFlowExecutor`：

```python
from pathlib import Path
from uuid import uuid4

from agent_service.model_client import ChatMessage as ModelChatMessage, LlamaCppModelClient
from tools.document_tool import read_documents, write_markdown


class DocumentFlowExecutor:
    def __init__(self, request: RunGraphRequest, model_client=None) -> None:
        self.request = request
        self.model_client = model_client or LlamaCppModelClient()
        self.artifact_dir = Path(request.project_path).with_suffix("").parent / "artifacts"

    def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
        if node_id == "document-input":
            if not self.request.attachments:
                raise ValueError("缺少可执行的文档附件")
            return NodeOutput(values={"paths": "\n".join(a.path for a in self.request.attachments)})

        if node_id == "document-parse":
            paths = self.request.attachments
            result = read_documents([attachment.path for attachment in paths])
            return NodeOutput(values={"text": result.text})

        if node_id == "content-organize":
            text = _first_input_value(inputs, "text")
            content = self.model_client.chat(
                [
                    ModelChatMessage(role="system", content="请把用户文档整理成结构化中文要点。"),
                    ModelChatMessage(role="user", content=text),
                ],
                temperature=0.2,
                max_tokens=1024,
            )
            return NodeOutput(values={"outline": content})

        if node_id == "report-generate":
            text = _first_input_value(inputs, "text")
            content = self.model_client.chat(
                [
                    ModelChatMessage(role="system", content="请根据用户文档生成一份简洁中文报告。"),
                    ModelChatMessage(role="user", content=text),
                ],
                temperature=0.2,
                max_tokens=1536,
            )
            return NodeOutput(values={"report": content})

        if node_id == "file-export":
            outline = _first_input_value(inputs, "outline")
            report = _first_input_value(inputs, "report")
            output_path = self.artifact_dir / f"report-{uuid4().hex[:8]}.md"
            exported = write_markdown(
                f"# 文档处理结果\n\n## 整理结果\n\n{outline}\n\n## 报告正文\n\n{report}\n",
                str(output_path),
            )
            return NodeOutput(artifacts=[exported], values={"artifact": exported})

        raise ValueError(f"未支持的节点: {node_id}")
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `python -m pytest python/tests/test_execution.py::test_document_flow_exports_markdown_artifact -v`

Expected: PASS。

---

### Task 4: FastAPI SSE 运行接口

**Files:**
- Modify: `python/agent_service/app.py`
- Test: `python/tests/test_app.py`

- [ ] **Step 1: 写失败测试**

```python
def test_graph_run_stream_returns_node_events(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("正文内容", encoding="utf-8")
    client = TestClient(app)

    response = client.post(
        "/agent/graph/run/stream",
        json={
            "task_id": "task-run",
            "project_path": str(tmp_path / "demo.alita"),
            "attachments": [
                {
                    "attachment_id": "a1",
                    "name": "input.md",
                    "path": str(source),
                    "size_bytes": 12,
                    "mime_type": "text/markdown",
                }
            ],
            "graph": build_document_graph_payload(),
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "node.running" in response.text
    assert "task.completed" in response.text
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest python/tests/test_app.py::test_graph_run_stream_returns_node_events -v`

Expected: FAIL，原因是接口不存在。

- [ ] **Step 3: 增加接口**

在 `python/agent_service/app.py` 增加：

```python
from agent_service.execution import run_graph_events
from agent_service.schemas import RunGraphRequest


@app.post("/agent/graph/run/stream")
def graph_run_stream(request: RunGraphRequest) -> StreamingResponse:
    return StreamingResponse(
        _serialize_graph_sse_events(request),
        media_type="text/event-stream",
    )


def _serialize_graph_sse_events(request: RunGraphRequest):
    for event in run_graph_events(request):
        yield f"data: {event.model_dump_json()}\n\n"
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `python -m pytest python/tests/test_app.py::test_graph_run_stream_returns_node_events -v`

Expected: PASS。

---

### Task 5: 前端运行 API

**Files:**
- Modify: `src/features/task/useTaskEvents.ts`
- Test: `src/features/task/useTaskEvents.test.ts`

- [ ] **Step 1: 写失败测试**

```ts
it("parses graph run SSE events with the shared parser", () => {
  const events: BackendEvent[] = [];
  const parse = createSseEventParser((event) => events.push(event));

  parse('data: {"type":"node.running","payload":{"nodeId":"document-parse"}}\n\n');

  expect(events).toEqual([
    {
      type: "node.running",
      payload: { nodeId: "document-parse" },
    },
  ]);
});
```

- [ ] **Step 2: 运行测试并确认失败或确认缺失 API**

Run: `npm run frontend:test -- src/features/task/useTaskEvents.test.ts`

Expected: 当前 parser 可能通过，但 `runNodeGraphStream` 还不存在，需要继续添加 API。

- [ ] **Step 3: 增加 `runNodeGraphStream`**

```ts
import type { ChatAttachment, NodeGraph } from "../../shared/types";

export type RunNodeGraphPayload = {
  taskId: string;
  projectPath: string;
  graph: NodeGraph;
  attachments: ChatAttachment[];
};

export async function runNodeGraphStream(
  payload: RunNodeGraphPayload,
  onEvent: (event: BackendEvent) => void,
): Promise<void> {
  const response = await fetch(`${SIDECAR_URL}/agent/graph/run/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      task_id: payload.taskId,
      project_path: payload.projectPath,
      graph: payload.graph,
      attachments: payload.attachments.map((attachment) => ({
        attachment_id: attachment.attachmentId,
        name: attachment.name,
        path: attachment.path,
        size_bytes: attachment.sizeBytes,
        mime_type: attachment.mimeType,
      })),
    }),
  });

  if (!response.ok) {
    throw new Error(`Agent sidecar returned ${response.status}`);
  }
  if (!response.body) {
    throw new Error("Agent sidecar did not return a streaming body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parseChunk = createSseEventParser(onEvent);

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    parseChunk(decoder.decode(value, { stream: true }));
  }

  const remainder = decoder.decode();
  if (remainder) parseChunk(remainder);
}
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `npm run frontend:test -- src/features/task/useTaskEvents.test.ts`

Expected: PASS。

---

### Task 6: 前端事件 reducer 更新节点状态

**Files:**
- Modify: `src/app/backendEvents.ts`
- Test: `src/app/backendEvents.test.ts`

- [ ] **Step 1: 写失败测试**

```ts
it("updates node status and artifacts from graph run events", () => {
  const graph: NodeGraph = {
    graphId: "graph-1",
    edges: [],
    nodes: [
      {
        nodeId: "document-parse",
        nodeType: "fixed_tool",
        displayName: "解析文档",
        status: "waiting",
        inputPorts: [],
        outputPorts: [],
        dependencies: [],
        toolRef: "document.extract_text",
        summary: "读取正文",
        createdBy: "agent",
        artifactRefs: [],
        retryCount: 0,
        position: { x: 0, y: 0 },
      },
    ],
  };

  const result = reduceBackendEvents(
    { messages: [], graph, dirty: false },
    [
      { type: "node.running", payload: { nodeId: "document-parse" } },
      {
        type: "node.completed",
        payload: { nodeId: "document-parse", artifactRefs: ["artifact-1"] },
      },
    ],
    createAssistantMessage,
  );

  expect(result.graph?.nodes[0].status).toBe("completed");
  expect(result.graph?.nodes[0].artifactRefs).toEqual(["artifact-1"]);
  expect(result.dirty).toBe(true);
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `npm run frontend:test -- src/app/backendEvents.test.ts`

Expected: FAIL，原因是 reducer 当前忽略节点事件。

- [ ] **Step 3: 实现节点事件处理**

在 `reduceBackendEvents` 中增加：

```ts
if (event.type === "node.running") {
  return updateNode(current, event.payload.nodeId, { status: "running" });
}

if (event.type === "node.completed") {
  return updateNode(current, event.payload.nodeId, {
    status: "completed",
    artifactRefs: event.payload.artifactRefs,
  });
}

if (event.type === "node.failed") {
  return updateNode(current, event.payload.nodeId, { status: "failed" });
}
```

并增加 helper：

```ts
function updateNode(
  state: BackendEventState,
  nodeId: string,
  patch: Partial<AgentNode>,
): BackendEventState {
  if (!state.graph) return state;
  return {
    ...state,
    graph: {
      ...state.graph,
      nodes: state.graph.nodes.map((node) =>
        node.nodeId === nodeId ? { ...node, ...patch } : node,
      ),
    },
    dirty: true,
  };
}
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `npm run frontend:test -- src/app/backendEvents.test.ts`

Expected: PASS。

---

### Task 7: 画布运行按钮

**Files:**
- Modify: `src/features/canvas/NodeCanvas.tsx`
- Create: `src/features/canvas/NodeCanvas.test.tsx`
- Modify: `src/app/App.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { NodeCanvas } from "./NodeCanvas";
import { createDocumentGraph } from "./nodeLayout";

describe("NodeCanvas", () => {
  it("renders a run button when graph exists", () => {
    const markup = renderToStaticMarkup(
      <NodeCanvas graph={createDocumentGraph()} running={false} onRun={() => undefined} />,
    );

    expect(markup).toContain("运行流程");
  });
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `npm run frontend:test -- src/features/canvas/NodeCanvas.test.tsx`

Expected: FAIL，原因是组件 props 和按钮还不存在。

- [ ] **Step 3: 增加运行按钮 props**

```tsx
type NodeCanvasProps = {
  graph: NodeGraph | null;
  running?: boolean;
  onRun?: () => void;
};
```

在 `graph` 存在时渲染：

```tsx
<div className="nodeCanvasToolbar">
  <button
    className="nodeCanvasRunButton"
    disabled={running}
    onClick={onRun}
    type="button"
  >
    {running ? "运行中" : "运行流程"}
  </button>
</div>
```

- [ ] **Step 4: 接入 App**

在 `App.tsx` 增加：

```ts
const [graphRunning, setGraphRunning] = useState(false);

const handleRunGraph = async () => {
  if (!activeProject || !graph) return;
  setGraphRunning(true);
  try {
    await runNodeGraphStream(
      {
        taskId: activeProject.projectId,
        projectPath: activeProject.path,
        graph,
        attachments: contextAttachments,
      },
      applyBackendEvent,
    );
  } catch (error) {
    setMessages((current) => [
      ...current,
      createMessage("assistant", `流程执行失败：${String(error)}`),
    ]);
  } finally {
    setGraphRunning(false);
    setDirty(true);
  }
};
```

并传入：

```tsx
<NodeCanvas graph={graph} running={graphRunning} onRun={handleRunGraph} />
```

- [ ] **Step 5: 运行测试并确认通过**

Run: `npm run frontend:test -- src/features/canvas/NodeCanvas.test.tsx`

Expected: PASS。

---

### Task 8: 端到端验证

**Files:**
- Verify only

- [ ] **Step 1: Python 单元测试**

Run: `python -m pytest python/tests`

Expected: all tests pass。

- [ ] **Step 2: 前端测试**

Run: `npm run frontend:test`

Expected: all tests pass。

- [ ] **Step 3: 前端类型检查**

Run: `npm run frontend:lint`

Expected: exit 0。

- [ ] **Step 4: MVP 脚本**

Run: `.\scripts\verify-mvp.ps1`

Expected: MVP verification passed。

- [ ] **Step 5: 桌面构建**

Run: `npm run build`

Expected: Tauri build succeeds。

---

## 自检

- 覆盖需求：第一版执行系统覆盖运行按钮、节点状态、文档解析、模型处理、分支汇合、导出 Markdown、产物事件。
- 暂不覆盖：临时脚本节点、安全审查、用户授权、失败后 AI 自动修复、停止运行。这些进入第二版执行系统。
- 类型一致性：后端事件继续复用当前 `BackendEvent` 命名，前端状态继续复用 `AgentNode.status`。
- 风险：当前 Tauri 命令层还没有 graph-run 桥接，第一版先走 HTTP sidecar；后续如需离线桌面完整封装，再补 Rust command。


