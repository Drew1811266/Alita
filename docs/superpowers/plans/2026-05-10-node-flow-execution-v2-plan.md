# 节点流程执行系统 V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 V1 可运行文档流程的基础上，增加运行控制、取消执行、失败恢复、运行记录、产物管理，以及临时脚本节点的安全模型预留。

**Architecture:** Python sidecar 继续作为节点执行引擎，新增运行注册表、取消令牌和节点运行日志。前端负责创建 `runId`、触发运行、停止运行、重试失败节点，并通过 SSE 事件实时更新右侧节点图和聊天区提示。工程文件只保存运行摘要和产物引用，大体积中间结果写入工程旁的 `node-runs/<runId>/` 目录。

**Tech Stack:** Tauri 2, React, TypeScript, FastAPI, Python, llama.cpp OpenAI-compatible API, Vitest, pytest, Rust command tests.

---

## 范围

本阶段实现：

- 运行 ID：每次执行都有稳定 `runId`。
- 运行状态：`running`、`completed`、`failed`、`cancelled`。
- 节点运行记录：记录每个节点开始、完成、失败、产物和错误。
- 停止运行：用户点击停止后，当前运行进入取消状态；执行引擎在节点边界停止。
- 失败恢复：支持重新运行失败节点及其下游节点。
- 从节点重新运行：支持选中某个节点后从该节点开始重跑下游。
- 产物管理：节点弹窗显示产物，支持打开文件和打开所在文件夹。
- 临时脚本节点安全模型预留：只做数据结构和 UI 状态，不执行脚本。

本阶段不实现：

- 真实脚本执行。
- AI 自动修复失败节点。
- 长模型调用的强制中断。
- 多个流程同时并发执行。
- 完整产物库页面。

取消语义明确为：如果当前节点正在调用模型，停止请求会先记录取消意图；执行引擎在当前节点返回后停止后续节点。

---

## 文件结构

- Modify: `python/agent_service/schemas.py`
  - 增加运行请求字段、取消请求模型、重试模式模型。
- Create: `python/agent_service/run_registry.py`
  - 管理活跃运行、取消令牌、运行状态。
- Create: `python/agent_service/run_journal.py`
  - 持久化 `node-runs/<runId>/run.json` 和 `<nodeId>.json`。
- Modify: `python/agent_service/execution.py`
  - 接入 `runId`、取消检查、运行日志、重试模式。
- Modify: `python/agent_service/app.py`
  - 增加取消接口 `/agent/graph/run/cancel`。
- Test: `python/tests/test_run_registry.py`
- Test: `python/tests/test_run_journal.py`
- Modify: `python/tests/test_execution.py`
- Modify: `python/tests/test_app.py`
- Modify: `src/shared/types.ts`
  - 增加运行记录、节点运行记录、产物引用和临时脚本安全状态类型。
- Modify: `src/shared/events.ts`
  - 增加 `run.started`、`run.cancelled`、`node.skipped`、`node.run_recorded`。
- Modify: `src/features/task/useTaskEvents.ts`
  - 支持 `runId`、取消请求、AbortController。
- Modify: `src/app/backendEvents.ts`
  - 回写运行状态、节点运行摘要、取消状态。
- Modify: `src/app/App.tsx`
  - 管理当前运行、停止运行、重试失败节点、从节点重跑。
- Modify: `src/features/canvas/NodeCanvas.tsx`
  - 工具栏增加运行、停止、重试失败节点。
- Modify: `src/features/canvas/NodePopover.tsx`
  - 展示最近运行、错误、产物操作、从此节点重跑。
- Modify: `src-tauri/src/commands.rs`
  - 增加打开产物文件和显示所在文件夹命令。
- Modify: `src-tauri/src/lib.rs`
  - 注册新命令。
- Test: `src-tauri/tests/artifact_open_tests.rs`
- Modify: `src/app/backendEvents.test.ts`
- Modify: `src/features/task/useTaskEvents.test.ts`
- Modify: `src/features/canvas/NodeCanvas.test.tsx`
- Modify: `src/features/canvas/NodePopover.test.tsx`

---

### Task 1: 扩展运行与节点运行类型

**Files:**
- Modify: `src/shared/types.ts`
- Modify: `src/shared/events.ts`
- Modify: `python/agent_service/schemas.py`
- Test: `src/app/backendEvents.test.ts`
- Test: `python/tests/test_execution.py`

- [ ] **Step 1: 写前端类型使用测试**

在 `src/app/backendEvents.test.ts` 增加测试，证明 reducer 能识别运行开始事件：

```ts
it("records the active run when run.started is received", () => {
  const result = reduceBackendEvents(
    { messages: [], graph: null, dirty: false, activeRunId: null },
    [
      {
        type: "run.started",
        payload: {
          runId: "run-1",
          taskId: "task-1",
          startedAt: "2026-05-10T00:00:00.000Z",
        },
      },
    ],
    createAssistantMessage,
  );

  expect(result.activeRunId).toBe("run-1");
  expect(result.dirty).toBe(true);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run frontend:test -- src/app/backendEvents.test.ts`

Expected: FAIL，原因是 `BackendEventState.activeRunId` 和 `run.started` 尚不存在。

- [ ] **Step 3: 扩展 TypeScript 类型**

在 `src/shared/types.ts` 增加：

```ts
export type RunStatus = "running" | "completed" | "failed" | "cancelled";

export type ArtifactRef = {
  artifactId: string;
  path: string;
  sourceNodeId: string;
  createdAt: string;
};

export type NodeRunRecord = {
  nodeRunId: string;
  runId: string;
  nodeId: string;
  status: NodeStatus;
  startedAt: string;
  completedAt?: string;
  artifactRefs: string[];
  error?: string;
};

export type ScriptReviewState = {
  status: "not_reviewed" | "reviewing" | "approved" | "rejected";
  summary: string;
  permissions: string[];
};
```

扩展 `AgentNode`：

```ts
lastRun?: NodeRunRecord;
scriptReview?: ScriptReviewState;
```

扩展 `RunHistoryEntry`：

```ts
nodeRunIds: string[];
artifactRefs: string[];
```

在 `src/shared/events.ts` 增加：

```ts
| {
    type: "run.started";
    payload: { runId: string; taskId: string; startedAt: string };
  }
| {
    type: "run.cancelled";
    payload: { runId: string; taskId: string; completedAt: string };
  }
| {
    type: "node.run_recorded";
    payload: { record: NodeRunRecord };
  }
| {
    type: "node.skipped";
    payload: { nodeId: string; reason: string };
  }
```

- [ ] **Step 4: 扩展 Python schema**

在 `python/agent_service/schemas.py` 增加：

```python
class RunMode(BaseModel):
    type: Literal["full", "failed_only", "from_node"] = "full"
    source_run_id: str | None = None
    node_id: str | None = None


class CancelRunRequest(BaseModel):
    run_id: str


class RunGraphRequest(BaseModel):
    task_id: str
    project_path: str
    graph: RunGraph
    attachments: list[RunAttachment] = Field(default_factory=list)
    run_id: str
    mode: RunMode = Field(default_factory=RunMode)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `npm run frontend:test -- src/app/backendEvents.test.ts`

Expected: PASS。

---

### Task 2: 后端运行注册表与取消令牌

**Files:**
- Create: `python/agent_service/run_registry.py`
- Test: `python/tests/test_run_registry.py`

- [ ] **Step 1: 写失败测试**

```python
from agent_service.run_registry import RunRegistry


def test_registers_and_cancels_run() -> None:
    registry = RunRegistry()

    token = registry.start("run-1")
    assert token.cancelled is False

    assert registry.cancel("run-1") is True
    assert token.cancelled is True
    assert registry.cancel("missing") is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest python/tests/test_run_registry.py -v`

Expected: FAIL，原因是 `run_registry.py` 不存在。

- [ ] **Step 3: 实现运行注册表**

创建 `python/agent_service/run_registry.py`：

```python
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass
class CancelToken:
    run_id: str
    cancelled: bool = False


class RunRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._tokens: dict[str, CancelToken] = {}

    def start(self, run_id: str) -> CancelToken:
        with self._lock:
            token = CancelToken(run_id=run_id)
            self._tokens[run_id] = token
            return token

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            token = self._tokens.get(run_id)
            if token is None:
                return False
            token.cancelled = True
            return True

    def finish(self, run_id: str) -> None:
        with self._lock:
            self._tokens.pop(run_id, None)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest python/tests/test_run_registry.py -v`

Expected: PASS。

---

### Task 3: 节点运行日志

**Files:**
- Create: `python/agent_service/run_journal.py`
- Test: `python/tests/test_run_journal.py`

- [ ] **Step 1: 写失败测试**

```python
from pathlib import Path

from agent_service.run_journal import RunJournal


def test_writes_run_and_node_records(tmp_path: Path) -> None:
    journal = RunJournal(project_path=str(tmp_path / "demo.alita"), run_id="run-1")

    journal.write_run({"runId": "run-1", "status": "running"})
    journal.write_node("document-parse", {"nodeId": "document-parse", "status": "completed"})

    assert (tmp_path / "node-runs" / "run-1" / "run.json").exists()
    assert (tmp_path / "node-runs" / "run-1" / "document-parse.json").exists()
    assert journal.read_node("document-parse")["status"] == "completed"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest python/tests/test_run_journal.py -v`

Expected: FAIL，原因是 `run_journal.py` 不存在。

- [ ] **Step 3: 实现运行日志**

创建 `python/agent_service/run_journal.py`：

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RunJournal:
    def __init__(self, *, project_path: str, run_id: str) -> None:
        self.base_dir = Path(project_path).parent / "node-runs" / run_id
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def write_run(self, payload: dict[str, Any]) -> None:
        self._write_json(self.base_dir / "run.json", payload)

    def write_node(self, node_id: str, payload: dict[str, Any]) -> None:
        self._write_json(self.base_dir / f"{node_id}.json", payload)

    def read_node(self, node_id: str) -> dict[str, Any]:
        return json.loads((self.base_dir / f"{node_id}.json").read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest python/tests/test_run_journal.py -v`

Expected: PASS。

---

### Task 4: 执行引擎接入运行状态和取消

**Files:**
- Modify: `python/agent_service/execution.py`
- Test: `python/tests/test_execution.py`

- [ ] **Step 1: 写失败测试**

```python
def test_run_emits_started_and_cancelled_between_nodes(tmp_path: Path) -> None:
    request = build_document_flow_request(tmp_path, tmp_path / "input.md", run_id="run-cancel")
    request.attachments[0].path = str(tmp_path / "input.md")
    Path(request.attachments[0].path).write_text("正文", encoding="utf-8")
    registry = RunRegistry()

    class CancellingExecutor(FakeNodeExecutor):
        def __init__(self) -> None:
            self.calls = 0

        def run(self, node_id: str, inputs: dict[str, NodeOutput]) -> NodeOutput:
            self.calls += 1
            if self.calls == 1:
                registry.cancel("run-cancel")
            return NodeOutput(values={"text": node_id})

    events = list(
        run_graph_events(
            request,
            executor=CancellingExecutor(),
            registry=registry,
        )
    )

    assert events[0].type == "run.started"
    assert "run.cancelled" in [event.type for event in events]
    assert "task.completed" not in [event.type for event in events]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest python/tests/test_execution.py::test_run_emits_started_and_cancelled_between_nodes -v`

Expected: FAIL，原因是执行引擎还没有 `registry` 和取消事件。

- [ ] **Step 3: 修改执行入口**

将 `run_graph_events` 签名改为：

```python
def run_graph_events(
    request: RunGraphRequest,
    *,
    executor: NodeExecutor | None = None,
    model_client: ModelClient | None = None,
    registry: RunRegistry | None = None,
) -> Iterator[AgentEvent]:
```

运行开始时：

```python
started_at = _now_iso()
run_registry = registry or DEFAULT_RUN_REGISTRY
cancel_token = run_registry.start(request.run_id)
yield AgentEvent(
    type="run.started",
    payload={"runId": request.run_id, "taskId": request.task_id, "startedAt": started_at},
)
```

每个节点前检查：

```python
if cancel_token.cancelled:
    completed_at = _now_iso()
    yield AgentEvent(
        type="run.cancelled",
        payload={"runId": request.run_id, "taskId": request.task_id, "completedAt": completed_at},
    )
    return
```

函数退出前调用：

```python
run_registry.finish(request.run_id)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest python/tests/test_execution.py::test_run_emits_started_and_cancelled_between_nodes -v`

Expected: PASS。

---

### Task 5: 失败节点重试和从节点重跑

**Files:**
- Modify: `python/agent_service/execution.py`
- Modify: `python/agent_service/run_journal.py`
- Test: `python/tests/test_execution.py`

- [ ] **Step 1: 写失败节点重试测试**

```python
def test_failed_only_reruns_failed_node_and_downstream(tmp_path: Path) -> None:
    source_run = "run-original"
    journal = RunJournal(project_path=str(tmp_path / "demo.alita"), run_id=source_run)
    journal.write_node("document-input", {"nodeId": "document-input", "status": "completed", "values": {"paths": "input.md"}})
    journal.write_node("document-parse", {"nodeId": "document-parse", "status": "completed", "values": {"text": "正文"}})
    journal.write_node("content-organize", {"nodeId": "content-organize", "status": "failed", "error": "model failed"})

    request = build_document_flow_request(tmp_path, tmp_path / "input.md", run_id="run-retry")
    request.mode.type = "failed_only"
    request.mode.source_run_id = source_run

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    running = [event.payload["nodeId"] for event in events if event.type == "node.running"]
    assert running == ["content-organize", "file-export"]
```

- [ ] **Step 2: 写从节点重跑测试**

```python
def test_from_node_reruns_target_and_downstream(tmp_path: Path) -> None:
    request = build_document_flow_request(tmp_path, tmp_path / "input.md", run_id="run-from-node")
    request.mode.type = "from_node"
    request.mode.node_id = "report-generate"

    events = list(run_graph_events(request, executor=FakeNodeExecutor()))

    running = [event.payload["nodeId"] for event in events if event.type == "node.running"]
    assert running == ["report-generate", "file-export"]
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest python/tests/test_execution.py -v`

Expected: FAIL，原因是执行引擎还没有运行模式过滤。

- [ ] **Step 4: 实现运行范围选择**

在 `execution.py` 增加：

```python
def _selected_nodes_for_mode(request: RunGraphRequest, ordered_nodes: list[GraphNode]) -> list[GraphNode]:
    if request.mode.type == "full":
        return ordered_nodes

    downstream = _downstream_node_ids(request)

    if request.mode.type == "from_node" and request.mode.node_id:
        selected = {request.mode.node_id, *downstream[request.mode.node_id]}
        return [node for node in ordered_nodes if node.nodeId in selected]

    if request.mode.type == "failed_only" and request.mode.source_run_id:
        failed = _failed_node_ids_from_journal(request)
        selected = set(failed)
        for node_id in failed:
            selected.update(downstream[node_id])
        return [node for node in ordered_nodes if node.nodeId in selected]

    return ordered_nodes
```

对未执行但依赖需要复用的上游节点，从 source run journal 读取 `values`。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest python/tests/test_execution.py -v`

Expected: PASS。

---

### Task 6: FastAPI 取消接口

**Files:**
- Modify: `python/agent_service/app.py`
- Test: `python/tests/test_app.py`

- [ ] **Step 1: 写失败测试**

```python
def test_cancel_graph_run_returns_cancelled_flag() -> None:
    client = TestClient(app)

    response = client.post("/agent/graph/run/cancel", json={"run_id": "missing"})

    assert response.status_code == 200
    assert response.json() == {"cancelled": False}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest python/tests/test_app.py::test_cancel_graph_run_returns_cancelled_flag -v`

Expected: FAIL，原因是取消接口不存在。

- [ ] **Step 3: 增加接口**

在 `app.py` 增加：

```python
from agent_service.run_registry import DEFAULT_RUN_REGISTRY
from agent_service.schemas import CancelRunRequest


@app.post("/agent/graph/run/cancel")
def cancel_graph_run(request: CancelRunRequest) -> dict[str, bool]:
    return {"cancelled": DEFAULT_RUN_REGISTRY.cancel(request.run_id)}
```

并确保 `run_graph_events` 使用同一个 `DEFAULT_RUN_REGISTRY`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest python/tests/test_app.py::test_cancel_graph_run_returns_cancelled_flag -v`

Expected: PASS。

---

### Task 7: 前端运行 API 支持 runId、取消和重试模式

**Files:**
- Modify: `src/features/task/useTaskEvents.ts`
- Test: `src/features/task/useTaskEvents.test.ts`

- [ ] **Step 1: 写失败测试**

```ts
it("posts runId and mode when running a graph", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response('data: {"type":"run.started","payload":{"runId":"run-1","taskId":"task-1","startedAt":"2026-05-10T00:00:00.000Z"}}\n\n'),
  );

  await runNodeGraphStream(
    {
      runId: "run-1",
      taskId: "task-1",
      projectPath: "D:\\Project\\demo.alita",
      graph: { graphId: "g", nodes: [], edges: [] },
      attachments: [],
      mode: { type: "failed_only", sourceRunId: "run-old" },
    },
    () => undefined,
  );

  expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
    run_id: "run-1",
    mode: { type: "failed_only", source_run_id: "run-old" },
  });
});
```

- [ ] **Step 2: 写取消请求测试**

```ts
it("posts cancel requests to the sidecar", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ cancelled: true }), {
      headers: { "Content-Type": "application/json" },
    }),
  );

  await cancelNodeGraphRun("run-1");

  expect(fetchMock).toHaveBeenCalledWith(
    "http://127.0.0.1:8765/agent/graph/run/cancel",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ run_id: "run-1" }),
    }),
  );
});
```

- [ ] **Step 3: 运行测试确认失败**

Run: `npm run frontend:test -- src/features/task/useTaskEvents.test.ts`

Expected: FAIL，原因是 API 参数和 `cancelNodeGraphRun` 尚不存在。

- [ ] **Step 4: 实现前端 API**

扩展 payload：

```ts
export type RunNodeGraphMode =
  | { type: "full" }
  | { type: "failed_only"; sourceRunId: string }
  | { type: "from_node"; nodeId: string; sourceRunId?: string };

export type RunNodeGraphPayload = {
  runId: string;
  taskId: string;
  projectPath: string;
  graph: NodeGraph;
  attachments: ChatAttachment[];
  mode: RunNodeGraphMode;
  signal?: AbortSignal;
};
```

增加取消函数：

```ts
export async function cancelNodeGraphRun(runId: string): Promise<{ cancelled: boolean }> {
  const response = await fetch(`${SIDECAR_URL}/agent/graph/run/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId }),
  });
  if (!response.ok) throw new Error(`Agent sidecar returned ${response.status}`);
  return (await response.json()) as { cancelled: boolean };
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `npm run frontend:test -- src/features/task/useTaskEvents.test.ts`

Expected: PASS。

---

### Task 8: 前端状态 reducer 接入运行记录

**Files:**
- Modify: `src/app/backendEvents.ts`
- Test: `src/app/backendEvents.test.ts`

- [ ] **Step 1: 写失败测试**

```ts
it("stores the last node run record on the matching node", () => {
  const result = reduceBackendEvents(
    {
      messages: [],
      graph: graphWithNode,
      dirty: false,
      activeRunId: "run-1",
    },
    [
      {
        type: "node.run_recorded",
        payload: {
          record: {
            nodeRunId: "nr-1",
            runId: "run-1",
            nodeId: "document-parse",
            status: "failed",
            startedAt: "2026-05-10T00:00:00.000Z",
            completedAt: "2026-05-10T00:00:01.000Z",
            artifactRefs: [],
            error: "读取失败",
          },
        },
      },
    ],
    createAssistantMessage,
  );

  expect(result.graph?.nodes[0].lastRun?.error).toBe("读取失败");
  expect(result.graph?.nodes[0].status).toBe("failed");
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run frontend:test -- src/app/backendEvents.test.ts`

Expected: FAIL。

- [ ] **Step 3: 实现 reducer**

处理：

```ts
if (event.type === "node.run_recorded") {
  return updateNode(current, event.payload.record.nodeId, {
    status: event.payload.record.status,
    artifactRefs: event.payload.record.artifactRefs,
    lastRun: event.payload.record,
  });
}

if (event.type === "run.cancelled") {
  return {
    ...current,
    activeRunId: null,
    messages: [...current.messages, createAssistantMessage("流程已停止。")],
    dirty: true,
  };
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npm run frontend:test -- src/app/backendEvents.test.ts`

Expected: PASS。

---

### Task 9: 画布工具栏运行控制

**Files:**
- Modify: `src/features/canvas/NodeCanvas.tsx`
- Modify: `src/app/App.tsx`
- Test: `src/features/canvas/NodeCanvas.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
it("renders stop and retry controls while graph is running or failed", () => {
  const graph = createDocumentGraph();
  graph.nodes[1].status = "failed";

  const markup = renderToStaticMarkup(
    <NodeCanvas
      graph={graph}
      running={true}
      canRetryFailed={true}
      onRun={() => undefined}
      onStop={() => undefined}
      onRetryFailed={() => undefined}
    />,
  );

  expect(markup).toContain("停止运行");
  expect(markup).toContain("重试失败节点");
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run frontend:test -- src/features/canvas/NodeCanvas.test.tsx`

Expected: FAIL。

- [ ] **Step 3: 扩展 NodeCanvas props**

```ts
type NodeCanvasProps = {
  graph: NodeGraph | null;
  running?: boolean;
  cancelling?: boolean;
  canRetryFailed?: boolean;
  onRun?: () => void;
  onStop?: () => void;
  onRetryFailed?: () => void;
  onRunFromNode?: (nodeId: string) => void;
};
```

工具栏规则：

- 未运行：显示 `运行流程`。
- 运行中：显示 `停止运行`。
- 有失败节点：显示 `重试失败节点`。

- [ ] **Step 4: App 接线**

在 `App.tsx` 增加：

```ts
const [activeRunId, setActiveRunId] = useState<string | null>(null);
const [runAbortController, setRunAbortController] = useState<AbortController | null>(null);

const handleStopGraph = async () => {
  if (!activeRunId) return;
  runAbortController?.abort();
  await cancelNodeGraphRun(activeRunId);
};
```

运行时生成：

```ts
const runId = createId("run");
const controller = new AbortController();
setActiveRunId(runId);
setRunAbortController(controller);
await runNodeGraphStream({ runId, mode: { type: "full" }, signal: controller.signal, ... }, applyBackendEvent);
```

- [ ] **Step 5: 运行测试确认通过**

Run: `npm run frontend:test -- src/features/canvas/NodeCanvas.test.tsx`

Expected: PASS。

---

### Task 10: 节点弹窗运行详情与从此节点重跑

**Files:**
- Modify: `src/features/canvas/NodePopover.tsx`
- Test: `src/features/canvas/NodePopover.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
it("renders last run error and rerun-from-node action", () => {
  const markup = renderToStaticMarkup(
    <NodePopover
      node={{
        ...toolNode,
        status: "failed",
        lastRun: {
          nodeRunId: "nr-1",
          runId: "run-1",
          nodeId: "document-parse",
          status: "failed",
          startedAt: "2026-05-10T00:00:00.000Z",
          completedAt: "2026-05-10T00:00:01.000Z",
          artifactRefs: [],
          error: "读取失败",
        },
      }}
      onClose={() => undefined}
      onRunFromNode={() => undefined}
    />,
  );

  expect(markup).toContain("读取失败");
  expect(markup).toContain("从此节点重跑");
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run frontend:test -- src/features/canvas/NodePopover.test.tsx`

Expected: FAIL。

- [ ] **Step 3: 扩展弹窗**

增加 props：

```ts
type NodePopoverProps = {
  node: AgentNode;
  onClose(): void;
  onRunFromNode?: (nodeId: string) => void;
  onOpenArtifact?: (path: string) => void;
  onRevealArtifact?: (path: string) => void;
};
```

显示字段：

- 最近状态。
- 开始时间和结束时间。
- 错误信息。
- 产物路径。
- `从此节点重跑` 按钮。
- `打开文件` 和 `打开所在文件夹` 按钮。

- [ ] **Step 4: 运行测试确认通过**

Run: `npm run frontend:test -- src/features/canvas/NodePopover.test.tsx`

Expected: PASS。

---

### Task 11: 产物打开与显示所在文件夹

**Files:**
- Modify: `src-tauri/src/commands.rs`
- Modify: `src-tauri/src/lib.rs`
- Test: `src-tauri/tests/artifact_open_tests.rs`

- [ ] **Step 1: 写 Rust 参数构造测试**

```rust
#[path = "../src/commands.rs"]
mod commands;

#[test]
fn builds_explorer_select_args_for_artifact() {
    let args = commands::explorer_select_args("D:\\Project\\artifacts\\report.md");

    assert_eq!(args, vec!["/select,".to_string(), "D:\\Project\\artifacts\\report.md".to_string()]);
}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `Push-Location src-tauri; cargo test --test artifact_open_tests; Pop-Location`

Expected: FAIL，原因是 helper 不存在。

- [ ] **Step 3: 实现命令**

在 `commands.rs` 增加：

```rust
pub fn explorer_select_args(path: &str) -> Vec<String> {
    vec!["/select,".to_string(), path.to_string()]
}

#[tauri::command]
pub fn reveal_artifact(path: String) -> Result<(), String> {
    std::process::Command::new("explorer")
        .args(explorer_select_args(&path))
        .spawn()
        .map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn open_artifact(path: String) -> Result<(), String> {
    std::process::Command::new("cmd")
        .args(["/C", "start", "", &path])
        .spawn()
        .map_err(|error| error.to_string())?;
    Ok(())
}
```

在 `lib.rs` 注册命令。

- [ ] **Step 4: 前端 API 接入**

新增 `src/features/artifacts/artifactApi.ts`：

```ts
import { invoke } from "@tauri-apps/api/core";

export function openArtifact(path: string): Promise<void> {
  return invoke("open_artifact", { path });
}

export function revealArtifact(path: string): Promise<void> {
  return invoke("reveal_artifact", { path });
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `Push-Location src-tauri; cargo test --test artifact_open_tests; Pop-Location`

Expected: PASS。

---

### Task 12: 工程文件保存运行历史和产物引用

**Files:**
- Modify: `src/app/App.tsx`
- Modify: `src/shared/types.ts`
- Test: `src/app/backendEvents.test.ts`
- Test: `src-tauri/tests/project_tests.rs`

- [ ] **Step 1: 写前端 reducer 测试**

```ts
it("adds completed runs to run history", () => {
  const result = reduceBackendEvents(
    {
      messages: [],
      graph: null,
      dirty: false,
      activeRunId: "run-1",
      runHistory: [],
    },
    [
      {
        type: "task.completed",
        payload: { taskId: "task-1", runId: "run-1" },
      },
    ],
    createAssistantMessage,
  );

  expect(result.runHistory[0].runId).toBe("run-1");
  expect(result.runHistory[0].status).toBe("completed");
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run frontend:test -- src/app/backendEvents.test.ts`

Expected: FAIL。

- [ ] **Step 3: 保存运行摘要**

扩展 `BackendEventState`：

```ts
runHistory: RunHistoryEntry[];
artifacts: ArtifactRef[];
```

`buildCurrentProject()` 返回：

```ts
return {
  ...activeProject,
  messages,
  graph,
  runHistory,
  attachments: collectProjectAttachments(...),
};
```

- [ ] **Step 4: Rust 工程保存兼容性测试**

在 `project_tests.rs` 增加：打开旧工程时如果 `runHistory` 缺字段，默认空数组；保存新工程时保留 `nodeRunIds` 和 `artifactRefs`。

- [ ] **Step 5: 运行测试确认通过**

Run: `npm run frontend:test -- src/app/backendEvents.test.ts`

Run: `Push-Location src-tauri; cargo test --test project_tests; Pop-Location`

Expected: PASS。

---

### Task 13: 临时脚本节点安全模型预留

**Files:**
- Modify: `src/shared/types.ts`
- Modify: `src/features/canvas/NodePopover.tsx`
- Test: `src/features/canvas/NodePopover.test.tsx`

- [ ] **Step 1: 写安全状态展示测试**

```tsx
it("renders temporary script review state without execution controls", () => {
  const markup = renderToStaticMarkup(
    <NodePopover
      node={{
        ...toolNode,
        nodeType: "temporary_placeholder",
        displayName: "临时脚本",
        scriptReview: {
          status: "not_reviewed",
          summary: "等待 AI 安全审查。",
          permissions: ["read_project_files"],
        },
      }}
      onClose={() => undefined}
    />,
  );

  expect(markup).toContain("等待 AI 安全审查");
  expect(markup).toContain("read_project_files");
  expect(markup).not.toContain("运行脚本");
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run frontend:test -- src/features/canvas/NodePopover.test.tsx`

Expected: FAIL。

- [ ] **Step 3: 实现只读展示**

在弹窗增加：

- 安全审查状态。
- AI 审查摘要。
- 请求权限列表。
- 固定说明：`临时脚本节点当前仅可审查，尚不能执行。`

不增加任何脚本运行按钮。

- [ ] **Step 4: 运行测试确认通过**

Run: `npm run frontend:test -- src/features/canvas/NodePopover.test.tsx`

Expected: PASS。

---

### Task 14: 端到端验证

**Files:**
- Verify only

- [ ] **Step 1: Python 测试**

Run: `python -m pytest python\tests`

Expected: all tests pass。

- [ ] **Step 2: 前端测试**

Run: `npm run frontend:test`

Expected: all tests pass。

- [ ] **Step 3: 前端类型检查**

Run: `npm run frontend:lint`

Expected: exit 0。

- [ ] **Step 4: Rust 测试**

Run: `Push-Location src-tauri; cargo test; Pop-Location`

Expected: all tests pass。

- [ ] **Step 5: MVP 验证脚本**

Run: `.\scripts\verify-mvp.ps1`

Expected: MVP verification passed。

- [ ] **Step 6: sidecar 打包**

Run: `.\scripts\build-sidecar.ps1`

Expected: `python\dist\alita-agent-sidecar.exe` rebuilt successfully。

- [ ] **Step 7: Windows 桌面构建**

Run: `npm run build`

Expected: app exe and NSIS installer are generated under `src-tauri\target\release\bundle\nsis`。

---

## 验收标准

- 用户可以点击 `运行流程` 开始执行。
- 运行中可以点击 `停止运行`。
- 取消后不会继续执行后续节点。
- 节点失败后可以点击 `重试失败节点`。
- 用户可以从某个节点开始重跑下游流程。
- 节点弹窗展示最近一次运行状态、错误和产物。
- 产物可以打开，也可以显示所在文件夹。
- 工程保存后保留运行摘要和产物引用。
- 临时脚本节点能显示安全审查状态，但没有执行入口。

## 自检

- 计划覆盖 v2 的运行控制、失败恢复、运行记录、产物管理和临时脚本安全模型预留。
- 计划没有把 AI 自动修复、真实脚本执行和多流程并发混入本阶段。
- 前后端字段采用同一语义：前端 `runId` 对应后端 `run_id`，前端 `sourceRunId` 对应后端 `source_run_id`。
- 取消语义明确为节点边界取消，不承诺中断正在进行的模型调用。


