# Alita Agent 开发优化文档（0.34.0 代码核验版）

生成日期：2026-05-31
核验对象：当前工作区 `D:\Software Project\Alita`，`main` 分支，提交 `06d9a26`
代码版本：`0.34.0`
输入材料：用户提供的外部 AI 评审结论（附件 `pasted-text.txt`）

## 1. 总体判断

外部分析的主方向是正确的，而且对 0.34.0 的评价比 README 层面的描述更接近真实代码状态。

Alita 0.34.0 确实已经比 0.33.0 更像一个 Agent Runtime Mainline：CI、`AgentRuntimeEngine`、`RuntimeState`、checkpoint v2 字段、`TraceStore`、memory v2 字段、tool catalog chain planner、schema validation、authority、bounded ReAct、MCP provider seam 都有了代码实体和测试覆盖。

但它现在仍然是“Runtime Mainline 骨架”，不是成熟 runtime 主内核。最核心的问题没有变化：

```text
默认用户消息入口仍是 app.py -> run_agent_from_state() -> graph.py LangGraph router。

AgentRuntimeEngine 目前反过来调用旧 run_agent_from_state()，
而不是由 RuntimeEngine 接管 route/context/plan/act/observe/verify/replan/final。

run_graph_events() 仍是增强型 DAG runner，
会按图拓扑顺序运行已有节点，并在 research / planned-task / document 三类 executor 间分支。
```

因此，下一阶段最重要的优化不是继续堆新功能，而是“控制流收束”：让 RuntimeEngine 成为唯一主入口，让 RuntimeState 成为唯一状态源，让 RuntimeAction 成为唯一执行单位，让 checkpoint/trace/memory/eval 都围绕这条主线落盘和回放。

## 2. 评分修正

外部评分整体中肯。核验后建议小幅修正如下：

| 维度 | 外部评分 | 核验后评分 | 判断 |
| --- | ---: | ---: | --- |
| 本地 AI 工作台 MVP+ | 8.7/10 | 8.7/10 | 准确。桌面工作台、文档/研究/artifact/偏好/CI 已比较扎实 |
| 单 Agent Runtime 雏形 | 7.4/10 | 7.3/10 | 基本准确，但 `AgentRuntimeEngine` 未接管主入口，实际主权弱于命名 |
| 通用自治 Agent 平台 | 6.1/10 | 6.0/10 | 准确。默认自治 loop 尚未打通，planner/execution 仍偏图执行 |
| Tool / MCP 生态 | 6.3/10 | 6.1/10 | tool gateway 较清楚；真实 MCP client/runtime 仍未启用 |
| 安全执行能力 | 6.1/10 | 6.0/10 | authority 有进步；sandbox 仍不是 OS 隔离，budget 未硬执行 |
| 可观测与评测 | 6.7/10 | 6.5/10 | TraceStore/CI/eval 有进步；model/tool/planner trace 和 model-loop eval 仍浅 |

## 3. 当前项目真实架构

### 3.1 前后端主路径

代码事实：

- `src-tauri/src/agent_client.rs:120` 调用 sidecar `/agent/message`。
- `python/agent_service/app.py:113-122` 的 `/agent/message` 直接调用 `run_agent_from_state()`。
- `python/agent_service/app.py:239-245` 的 message stream 也走 `stream_agent_events_from_state()`。
- `python/agent_service/app.py:248-256` 的 graph stream 走 `run_graph_events()`。

当前默认路径是：

```text
Frontend / Tauri
  -> FastAPI /agent/message
  -> run_agent_from_state()
  -> graph.py build_graph()
  -> classify_intent
  -> answer_with_model / answer_with_web / choose_research_mode / plan_research_graph / request_required_inputs / plan_task_graph
  -> END
```

图运行路径是：

```text
Frontend / Tauri
  -> FastAPI /agent/graph/run/stream
  -> run_graph_events()
  -> _topological_nodes()
  -> select nodes by run mode
  -> ResearchFlowExecutor / PlannedTaskExecutor / DocumentFlowExecutor
  -> checkpoint / trace / memory / authority events
```

这说明 Alita 的可运行闭环已经很强，但 runtime 控制面还没有成为主入口。

### 3.2 RuntimeEngine 状态

代码事实：

- `python/agent_service/agent_runtime_engine.py:22` 定义 `AgentRuntimeEngine`。
- `start_run()` 会创建 `RuntimeState` 并发出 `runtime.run_started`。
- `step()` 在 `python/agent_service/agent_runtime_engine.py:52-76` 中把 `RuntimeState` 还原成 `AgentRunState`，然后直接调用 `run_agent_from_state()`。
- `step()` 只包装一个 `runtime.state_delta`，其中 `decision={"kind": "route_and_plan"}`。
- `resume()` 只发 `runtime.resume_requested`。
- `interrupt()` 只把 stage 改成 `interrupted`。

结论：外部分析说它现在是 facade，不是 runtime kernel，准确。

当前方向应该反转为：

```text
run_agent_from_state()
  -> AgentRuntimeEngine.start_run()
  -> AgentRuntimeEngine.step_until_interrupt_or_final()
```

而不是：

```text
AgentRuntimeEngine.step()
  -> run_agent_from_state()
```

### 3.3 RuntimeState 状态

代码事实：

- `python/agent_service/runtime_state.py:26-35` 定义 `RuntimeAction`。
- `python/agent_service/runtime_state.py:39-54` 定义 `RuntimeState`，包含 `thread_id`、`run_id`、`stage`、`messages`、`goal_spec`、`context_bundle`、`action_graph`、`selected_action`、`observations`、`verification`、`pending_approvals`、`memory_writes`。
- `python/agent_service/runtime_state.py:57-64` 定义 `RuntimeStateDelta`。

字段设计方向正确，但当前状态没有成为唯一状态源。`run_graph_events()` 仍主要依赖 `RunGraphRequest`、`NodeOutput`、`RunJournal` 和各类 executor 内部状态；checkpoint 里保存的 `runtime_state` 也只是简化结构。

### 3.4 AgentRuntimeGraph 状态

代码事实：

- `python/agent_service/agent_runtime_graph.py:8-21` 定义了 route/context/plan/approve/act/execute/observe/verify/replan/final/failed/interrupted 等 stage。
- 但 `AgentRuntimeGraph.route()` 只把 stage 改成 `plan`。
- `plan_ready()` 有 graph 就进 `execute`，没有 graph 就 `failed`。
- `execution_ready()` 直接进 `observe`。
- `final()` 直接进 `final`。

结论：它仍是 stage transition shell，不是实际状态机。

## 4. 外部建议逐条核验

| 外部判断 / 建议 | 核验结论 | 代码依据 | 处理优先级 |
| --- | --- | --- | --- |
| CI 已落地，是重要工程门槛 | 准确 | `.github/workflows/ci.yml` 跑 frontend typecheck/test、Python pytest、agent eval | 保持并扩展 |
| RuntimeEngine/State/Delta 有实体 | 准确 | `agent_runtime_engine.py`、`runtime_state.py` | 继续推进 |
| AgentRuntimeEngine 仍是 facade | 准确 | `AgentRuntimeEngine.step()` 调 `run_agent_from_state()` | P0 |
| 主入口仍是 route -> answer/create graph -> END | 准确 | `graph.py:425-479` | P0 |
| graph execution 仍是 DAG runner | 准确 | `execution.py:1334-1412`、`_topological_nodes()` | P0/P1 |
| 文档流/研究流仍是 runtime 特权路径 | 准确 | `DOCUMENT_FLOW_NODE_IDS`、`ResearchFlowExecutor`、`DocumentFlowExecutor` | P1 |
| Tool planner 只是最多两步启发式链条 | 准确 | `tool_catalog_planner.py:70-101` | P1/P2 |
| checkpoint v2 字段有了，但 checkpointId 弱 | 准确 | `runtime_loop.py:10-45` | P1 |
| TraceStore 有持久化，但 trace 很浅 | 准确 | `trace_store.py`、`execution.py:1801-1837` | P1 |
| memory v2 字段有了，但 retrieval 轻量 | 准确 | `memory_store.py`、`context_policy.py` | P1/P2 |
| authority 更严，但 capability-first 不完整 | 部分准确 | network domain 已加强；empty approved_tool_ids 仍表示不限制 tool id | P1 |
| runtime budget 只是审计字段，不是硬控制 | 准确 | `tool_gateway.py:66-107` 计算 budget 但 `provider.call_tool(invocation)` 不传 timeout | P1 |
| sandbox 不是安全边界 | 准确 | `sandbox.py:27-28`、`subprocess.run()` | P1/P2 |
| MCP 仍是 provider seam | 准确，而且问题更明确 | `mcp_client_factory.py:30-44` 真实 client 未启用 | P1/P2 |
| model-loop eval 仍偏占位 | 准确 | `eval_harness.py:199-235` | P1 |
| 暂时不要做多 Agent team | 准确 | 单 Agent runtime 主权尚未打穿 | P3 |

## 5. 需要补充修正的地方

### 5.1 Alita 已经有 bounded ReAct，但不是默认 runtime loop

外部分析没有充分强调这一点。当前代码确实有 bounded ReAct：

- `python/agent_service/react_controller.py` 定义 `ReActController`。
- `python/agent_service/execution.py:759-811` 在 planned model node 上按 metadata 启用 ReAct。
- 测试覆盖 native tool calls、JSON action parsing、tool budget、step budget 等。

但它是“某个 model node 内部的执行策略”，不是全局 RuntimeEngine 的主 loop。也就是说，Alita 已经有局部 ReAct 能力，但不是：

```text
RuntimeEngine -> select action -> tool/model -> observe -> verify -> replan
```

所以外部结论“默认自治 loop 未打通”仍然成立。

### 5.2 Checkpoint v2 是字段进步，不是 durable state 完成

`RuntimeCheckpoint` 已有 `thread_id`、`sequence`、`parent_checkpoint_id`、`graph_hash`、`state_version`、`writes`、`pending_approvals`、`runtime_state`。

但：

- `checkpointId` 仍由 `f"{node_id}:{status}:{recovery_count}"` 生成。
- `execution.py:1438-1441` 写入的 `runtime_state` 只有 `nodeId` 和 `status`。
- `RuntimeStateDelta` 没有统一写进 journal。
- resume 主要恢复 `completedOutputs` 和 `pendingNodeIds`，不是完整 runtime replay。

因此它现在是 checkpoint v2 schema seed，不是 durable runtime replay。

### 5.3 Memory 有自动写入，但没有闭环治理

当前 `execution.py:2204-2296` 会在 run 完成后写 `graph_summary`、`tool_outcome` 和 `artifact_summary`，失败时也会写 tool failure summary。规划前 `graph.py:276-283` 会读取 `MemoryStore(project_path).list()`。

这比“没有 memory”强很多。

但 memory 仍缺：

- upsert/dedupe，`MemoryStore.append()` 是 append-only。
- `last_used_at` 更新。
- `expires_at` 过滤。
- conflict resolution。
- 用户可编辑/禁用 UI。
- 将失败经验转为下次 planner policy 的闭环。

### 5.4 Observability 已能进前端，但 span 类型还不够

当前后端会发：

- `runtime.checkpoint_recorded`
- `runtime.span_recorded`
- `authority.decision_recorded`
- `recovery.action_proposed`
- `recovery.action_applied`

前端 `useGraphRuntimeController.ts:47-112` 会把这些 reduce 到 observability state。

但 span 主要是 `runtime.node`，且 `parent_span_id=None`。还缺成熟 Agent runtime 需要的 span：

- `agent.route`
- `context.build`
- `planner.call`
- `model.call`
- `tool.call`
- `authority.check`
- `memory.read`
- `memory.write`
- `verifier.check`
- `replan.decide`
- `human.approval`

尤其缺 `model.call`。没有模型调用 span，就很难解释一次计划为什么生成、token/latency/retry/fallback/finish reason 怎么变化。

## 6. 当前最重要的架构问题

### P0: RuntimeEngine 没有控制流主权

这是当前最大问题。`AgentRuntimeEngine` 已存在，但默认 API 和 frontend 没有接入它。`app.py` 仍直接调用 `run_agent_from_state()`。

目标结构应该变成：

```text
/agent/message
  -> AgentRuntimeEngine.start_run()
  -> step_until_interrupt_or_final()
  -> RuntimeStateDelta persisted
  -> RuntimeCheckpoint persisted
  -> RuntimeSpan persisted
  -> AgentEvent stream
```

`run_agent_from_state()` 应降级为 legacy router node，作为 RuntimeEngine 的 `route` 或 `legacy_plan` action，而不是被 RuntimeEngine 调用。

### P0: RuntimeState 没有成为唯一状态源

当前状态分散在：

- `AgentRunState`
- `RunGraphRequest`
- `RunJournal`
- executor 局部变量
- `outputs: dict[str, NodeOutput]`
- checkpoint record
- graph metadata
- frontend graph state

这会让 resume、interrupt、replan、time travel、debug trace 都变复杂。

下一步应把 `RuntimeState` 变成可持久化状态源：

- route/context/plan/act/observe/verify/replan 每一步只接受 `RuntimeState`，返回 `RuntimeStateDelta`。
- checkpoint 保存 state hash、delta、writes、pending approvals、selected action、observations。
- journal 支持按 checkpoint id 恢复完整 `RuntimeState`。

### P0/P1: execution.py 继续膨胀会阻碍 runtime 主线

`execution.py` 目前承担：

- document flow
- research flow
- planned task runtime
- model node
- tool gateway
- temporary script sandbox
- checkpoint
- trace
- memory write
- permission gate
- recovery/replan
- final verification

这已经超过一个 runtime execution module 的合理边界。下一阶段不应继续往里塞业务分支，而应拆成：

```text
runtime_engine.py       # state machine and control flow
runtime_store.py        # state/delta/checkpoint persistence
action_executor.py      # execute RuntimeAction
action_compiler.py      # compile RunGraph/template -> RuntimeActionGraph
flow_templates/         # document/research templates
observability.py        # span/redaction/event bridge
```

## 7. 推荐目标架构

### 7.1 Runtime 控制面

建议定义明确的 runtime step contract：

```text
RuntimeNode:
  input: RuntimeState
  output: RuntimeStateDelta
  side effects: journal writes, trace spans, emitted events
```

核心 step：

```text
route
  -> context
  -> plan
  -> approve
  -> act
  -> execute
  -> observe
  -> verify
  -> replan | final | failed | interrupted
```

每个 step 的职责：

| Step | 职责 | 产物 |
| --- | --- | --- |
| route | 判断任务类型、风险、是否需要工具/联网/文档 | route decision |
| context | 构建 project/tool/memory/attachment context | context bundle |
| plan | 生成 RuntimeActionGraph | action graph |
| approve | 聚合权限、预算、人类确认需求 | pending approvals / grants |
| act | 选择下一步 action | selected action |
| execute | 执行 model/tool/human/control action | raw result |
| observe | 标准化 observation | observations |
| verify | 判断是否满足目标/是否需要修复 | verification |
| replan | patch action graph 或请求用户输入 | revised action graph |
| final | 输出最终消息/artifact summary | final event |

### 7.2 Action 执行面

runtime 不应该知道 `document-parse`、`research-query-plan` 这类业务节点。它应该只认识四类 action：

```text
model action
tool action
human action
control action
```

文档流和研究流应变成 template/compiler：

```text
DocumentFlowTemplate
  -> RuntimeActionGraph
  -> model/tool/control actions

ResearchFlowTemplate
  -> RuntimeActionGraph
  -> tool/model/verifier/output actions
```

### 7.3 Tool planner

当前 planner 是：

```text
token overlap -> first tool -> maybe second tool -> output node
```

目标 planner 应变成：

```text
tool retrieval
  -> IO type normalization
  -> bounded DAG search
  -> authority/budget validation
  -> artifact/failure policy validation
```

短期不需要追求大型搜索。建议先支持 3-5 个工具节点、确定性 ranking、schema-constrained path validation。

### 7.4 Observability

TraceStore 应成为 runtime 的一等基础设施，而不是只在 node run 上补 span。

建议 span schema：

```text
traceId
spanId
parentSpanId
runId
threadId
checkpointId
kind
name
status
startedAt
endedAt
durationMs
metadata
redaction
```

最先补齐：

- `model.call`: provider/model/policy/tokens/latency/retry/fallback/finish_reason/prompt_hash
- `tool.call`: tool/provider/operation/authority/budget/duration/error/artifacts
- `planner.call`: planner/version/input summary/action count/diagnostics
- `memory.read` and `memory.write`: selected ids/scores/kinds/redaction

### 7.5 Durable state

checkpoint id 应改为稳定唯一 ID：

```text
ckpt-{run_id}-{sequence}-{short_state_hash}
```

并保留 human-readable fields：

```json
{
  "nodeId": "...",
  "status": "...",
  "recoveryCount": 0
}
```

不要让 `node_id:status:recovery_count` 承担 identity。它可以是 label，不应该是 checkpoint primary key。

## 8. 分阶段 Roadmap

### Phase 1: RuntimeEngine 接管主入口（P0）

目标：所有 `/agent/message` 默认走 RuntimeEngine。

建议改动：

- 新增 `RuntimeEngine.step_until_interrupt_or_final(state)`。
- 在 `app.py` 的 `/agent/message` 和 `/agent/message/stream` 接入 `AgentRuntimeEngine`。
- 保留 `run_agent_from_state()`，但作为 legacy route/plan action。
- `AgentRuntimeEngine.step()` 不再直接调用 `run_agent_from_state()`，而是根据 `state.stage` dispatch。
- 每步产出 `RuntimeStateDelta`。

验收标准：

- 新增测试证明 `/agent/message` 调用 RuntimeEngine。
- `AgentRuntimeEngine.step(route)` 产生 route delta，不直接吐旧 graph events。
- `AgentRuntimeEngine.step(plan)` 可以生成 node graph 或 action graph。
- interrupt/resume 能基于 RuntimeState，而不是只发请求事件。

### Phase 2: RuntimeState 持久化和 checkpoint identity（P0/P1）

目标：checkpoint 能恢复完整 RuntimeState，而不只是 node outputs。

建议改动：

- 新增 `runtime_store.py`，封装 run/state/delta/checkpoint/trace 写入。
- `RuntimeCheckpoint.to_record()` 使用新的 `checkpoint_id` 字段。
- `RuntimeStateDelta` 写入 journal。
- checkpoint 记录 `state_hash`、`graph_hash`、`parent_checkpoint_id`、`runtime_state`。
- resume 从 checkpoint 恢复 `RuntimeState`，再继续 step。

验收标准：

- 同一 node/status/recovery_count 多次出现不会产生 checkpoint id 冲突。
- 从指定 checkpoint resume 后，stage、selected_action、observations、pending_approvals 能恢复。
- 新增 replay 测试：执行到 checkpoint，恢复后继续，最终输出一致。

### Phase 3: 文档流和研究流模板化（P1）

目标：runtime 不再硬编码 document/research 特权节点。

建议改动：

- 建立 `python/agent_service/flow_templates/document.py`。
- 建立 `python/agent_service/flow_templates/research.py`。
- 模板输出 `RuntimeActionGraph` 或统一 `ExecutionGraph`。
- `DocumentFlowExecutor` 和 `ResearchFlowExecutor` 逐步降级为 action compiler/executor helpers。
- `execution.py` 删除按业务类型选择 executor 的主分支。

验收标准：

- runtime 层没有 `DOCUMENT_FLOW_NODE_IDS` 和 research node id 常量。
- 文档/研究流程仍能生成原有 artifact。
- 旧 graph payload 可以通过 compatibility compiler 运行。

### Phase 4: Trace 扩展到 model/tool/planner/memory（P1）

目标：一次 Agent 决策可被解释和调试。

建议改动：

- 给 model client 增加 trace hook 或 wrapper，不直接污染 transport。
- 给 `UnifiedToolGateway.call_tool()` 增加 `tool.call` span。
- 给 `PlannerChain.plan()` 和 `ToolCatalogPlanner.plan()` 增加 planner span。
- 给 `build_context_bundle()` / memory selection 增加 `memory.read` span。
- 给 `_auto_write_memory_records()` 增加 `memory.write` span。
- 增加 redaction policy，span metadata 只存摘要/hash/计数，不直接存敏感 prompt。

验收标准：

- 每次 graph run 的 `trace.jsonl` 至少包含 planner/model/tool/node span。
- 前端 observability 能看到非 node span。
- 测试覆盖 sensitive metadata 不落盘。

### Phase 5: Tool planner 升级为 schema-constrained DAG planner（P1/P2）

目标：工具规划从“两步 chain”变成小规模通用 DAG。

建议改动：

- 给工具 schema 规范化 input/output port type。
- 建立 `ToolPortType`：text/file/path/json/artifact/url/table/image/pdf。
- 工具召回仍可先用 token overlap，但 ranking 应加入 schema compatibility。
- DAG search 支持最多 3-5 个工具节点。
- validator 检查 dependency、port type、required args、artifact policy、authority policy、failure policy。

验收标准：

- 可规划 `read document -> summarize -> compile/export` 这类 3 步链。
- 不兼容 output/input 类型会被 validator 拦截。
- planner eval 增加多工具 DAG case。

### Phase 6: MCP 真实最小闭环（P1/P2）

目标：至少一个 stdio MCP server 能被配置、启动、发现、授权、执行、trace。

建议改动：

- 实现 stdio MCP client。
- 支持 process lifecycle：start/initialize/list_tools/call_tool/stop。
- 加 schema cache、health、timeout、reconnect。
- 将 MCP tool 权限映射到 `AuthorityContext`。
- preferences 只保存非敏感配置，secret 继续走系统凭据库。

验收标准：

- `create_mcp_client()` 不再对合法 stdio config 返回 `unsupported_transport_runtime`。
- gateway 能 list 外部 MCP tool。
- planner 能看到 MCP tool。
- authority 能拒绝/允许 MCP call。
- trace 记录 `tool.call` span。

### Phase 7: Sandbox 安全边界升级（P1/P2）

目标：不要把当前 subprocess runner 当安全边界。

短期：

- Windows Job Object 限制进程树。
- 子进程低权限 token。
- cwd overlay。
- 环境变量白名单。
- 禁止继承用户 shell/profile。
- 明确网络禁用策略。

中期：

- AppContainer 或 WSL/Docker backend。
- 工具 worker 进程隔离。
- artifact-only write boundary。

验收标准：

- `SandboxResult.is_process_tree_limited=True` 对应真实实现。
- 进程树逃逸测试覆盖。
- 网络/文件越界测试覆盖。
- 文档明确当前 backend 的边界和风险。

### Phase 8: Memory v2 闭环治理（P2）

目标：memory 从“可读写摘要”升级为可治理长期记忆。

建议改动：

- `MemoryStore.upsert(record)`，按 `memory_id` 或 source_ref 去重。
- retrieval 后更新 `last_used_at`。
- retrieval 过滤 `expires_at`。
- 增加 conflict policy：同 scope/kind/source_ref 下保留最新或高 confidence。
- 增加 memory write policy：哪些成功/失败值得写。
- 前端增加 memory review/disable/edit。

验收标准：

- 重复 run 不会无限追加同一 summary。
- 过期 memory 不会进入 context。
- 选中的 memory 会更新 `last_used_at`。
- 用户可以查看并禁用项目 memory。

## 9. 建议优先级

### 必须先做

1. RuntimeEngine 接管 `/agent/message`。
2. RuntimeStateDelta 和完整 RuntimeState 持久化。
3. checkpoint id 改为唯一稳定 ID。
4. execution.py 拆分，并把 document/research 从 runtime 特权路径移走。
5. model/tool/planner trace span。

### 接着做

1. schema-constrained multi-step tool DAG planner。
2. stdio MCP 最小真实闭环。
3. authority timeout/cancel 传递到 provider。
4. memory upsert、last_used、expires 过滤。
5. model-loop scripted eval。

### 暂缓做

1. 多 Agent team。
2. 大型 marketplace。
3. 复杂向量记忆系统。
4. 过早的分布式 runtime。
5. 只为了展示效果的新业务流。

## 10. 测试和评测优化

当前 CI 已经是重要进步：

- frontend typecheck
- frontend test
- Python pytest
- deterministic agent eval

下一步建议新增这些测试：

| 测试类型 | 目标 |
| --- | --- |
| RuntimeEngine integration | `/agent/message` 必须经过 RuntimeEngine |
| State replay | checkpoint resume 后继续执行结果一致 |
| Delta persistence | 每个 stage 都有可回放 delta |
| Tool DAG planner eval | 多工具 3-5 节点规划 |
| Scripted model-loop eval | mock model: tool call -> observation -> final |
| Trace redaction test | prompt/secrets/path 不直接落盘 |
| MCP stdio integration | 启动测试 server、list/call/stop |
| Sandbox escape tests | 子进程树、路径、网络、env 越界 |

`eval_harness.py` 的 model-loop case 应从当前的 skipped/mock 升级为 deterministic scripted runner：

```text
step1 model response -> requests tool call
step2 model response -> consumes observation
step3 model response -> final answer
```

这样不用真实 API 也能证明 ReAct/tool/replan 能力没有退化。

## 11. 与成熟 Agent Runtime 的差距

成熟 Agent Runtime 通常需要具备这些能力：

| 能力 | Alita 0.34.0 状态 | 差距 |
| --- | --- | --- |
| Durable execution | 有 checkpoint 字段和 resume，但不是完整 state replay | checkpoint identity/state delta/replay |
| Human-in-the-loop | 有 permission gate 和 approval primitive | 需要统一 pending approval model |
| Tool ecosystem | 有 unified gateway 和 manifest | 真实 MCP runtime、schema DAG planner |
| Observability | 有 trace.jsonl 和 runtime events | 缺 model/tool/planner/memory spans |
| Memory | 有 v2 fields 和 lightweight retrieval | 缺治理、更新、冲突处理、可编辑 UI |
| Sandboxed execution | 有 constrained subprocess runner | 缺 OS isolation/process tree/network boundary |
| Eval | 有 deterministic eval 和 CI | 缺 model-loop deterministic eval 与 regression gate |
| Runtime control plane | 有 Engine/State 类型 | 未接管主入口 |

外部参考坐标：

- LangGraph 强调 durable execution、persistence 和 human-in-the-loop 等 runtime 能力。
- Model Context Protocol 强调标准化 tools/resources/transports/lifecycle。
- OpenAI Agents SDK 强调 tools、handoffs、guardrails 和 tracing。

这些不是要求 Alita 照搬某个框架，而是说明成熟 Agent 项目的共同主线：控制流、状态、工具、安全、trace、eval 必须合成一个默认运行时，而不是散落在业务流里。

参考链接：

- LangGraph docs: https://docs.langchain.com/oss/python/langgraph/overview
- Model Context Protocol docs: https://modelcontextprotocol.io/docs
- OpenAI Agents SDK docs: https://openai.github.io/openai-agents-python/

## 12. 最终结论

外部分析可以采纳，而且大部分建议应该进入下一轮主线开发。

更精确地说：

```text
Alita 0.34.0 已经有 RuntimeEngine、RuntimeState、Checkpoint v2、TraceStore、Memory v2、
Unified Tool Gateway、bounded ReAct、ToolActionGraph 和 CI/eval。

但这些还没有形成一个默认控制平面。

当前系统仍是旧 router + 旧 DAG runner 在承担主要工作，
新 runtime 在旁边记录、包装、补强。
```

下一轮真正的突破点是夺回控制流：

1. RuntimeEngine 成为唯一主入口。
2. RuntimeState 成为唯一状态源。
3. RuntimeAction 成为唯一执行单位。
4. checkpoint/trace/memory/eval 都围绕 RuntimeStateDelta 建立。
5. document/research/tool/MCP/sandbox 都降级为 runtime 可组合 action。

完成这些之后，Alita 才会从“可审计 Agent Workbench”进入“可扩展 Agent Runtime 平台”。
