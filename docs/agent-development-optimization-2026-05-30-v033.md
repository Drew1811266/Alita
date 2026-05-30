# Alita Agent 开发优化文档（0.33.0 代码核验版）

生成日期：2026-05-30  
核验对象：当前工作区 `D:\Software Project\Alita`，`main` 分支，代码版本 `0.33.0`  
输入材料：用户提供的外部 AI 评审结论（附件 `pasted-text.txt`）

## 1. 总体判断

外部分析的主方向是正确的，而且比普通 README 层面的评价更贴近当前 Alita 的真实短板。当前仓库确实已经从“本地文档工作流 + 聊天 UI”推进到“本地优先、可审计的 Agent Runtime Workbench 雏形”，但 0.33.0 的核心问题也正如外部分析所说：很多 Agent 平台关键词已经变成了代码里的字段、类型、事件或 primitive，还没有统一成系统的默认控制平面。

更精确地说：

```text
Alita 0.33.0 已经有可运行的 DAG 执行层、checkpoint、authority、tool gateway、trace primitive、MCP provider seam、受控 ReAct、memory context 和 deterministic eval。

但主入口仍然是 route -> answer / create graph -> END；
AgentRuntimeGraph 还没有接管 plan / act / observe / verify / replan 的主循环；
工具规划、MCP、sandbox、observability 和 model-loop eval 仍处于可测试雏形或接口预留状态。
```

因此，下一阶段最重要的不是继续堆 UI 或更多业务流，而是做一次架构收束：统一 runtime、统一 action、统一 state、统一 trace、统一 tool planning。只有这些成为默认路径，Alita 才会从“能跑几个闭环的工作台”升级成“可扩展的本地 Agent 平台”。

## 2. 评分修正

外部评分整体中肯，但个别维度可以略微修正。原因是当前代码已经具备指定 checkpoint resume、authority grant、tool observation、MCP lifecycle seam、schema-aware 单工具 planner 等增量；但这些增量仍不等同于成熟 runtime。

| 维度 | 外部评分 | 核验后评分 | 判断 |
| --- | ---: | ---: | --- |
| 本地 AI 工作台 MVP+ | 8.5/10 | 8.5/10 | 准确。桌面工程、artifact、文档/研究闭环和首选项系统已成型 |
| 单 Agent Runtime 雏形 | 7.0/10 | 7.1/10 | 基本准确。执行层有闭环 primitive，但 `AgentRuntimeGraph` 不是主内核 |
| 通用自治 Agent 平台 | 5.7/10 | 5.8/10 | 基本准确。主入口不是自治 loop，多工具规划和 MCP 生态未打通 |
| Tool / MCP 生态 | 5.8/10 | 6.0/10 | 略低估。manifest/gateway/provider seam 已较清楚，但真实 MCP client path 缺失 |
| 安全执行能力 | 5.8/10 | 6.0/10 | 略低估权限进展，但 sandbox 批评完全成立 |
| 可观测与评测 | 6.0/10 | 6.2/10 | runtime events 和 observation metadata 已贯通，trace-first/eval gate 仍弱 |

## 3. 关键代码事实

### 3.1 版本事实

代码事实：

- `package.json` 版本是 `0.33.0`。
- `python/pyproject.toml` 版本是 `0.33.0`。
- `README.md` 也已更新为 `0.33.0`。
- 当前分支是 `main`，最近提交包含 `Release 0.33.0 agent runtime optimization`。

结论：外部分析针对 0.33.0 的版本判断是准确的。

### 3.2 AgentRuntimeGraph 是薄壳，不是主内核

代码依据：

- `python/agent_service/agent_runtime_graph.py`
- `python/tests/test_agent_runtime_graph.py`
- `python/agent_service/graph.py`

`AgentRuntimeGraphState` 已定义：

- `route`
- `plan`
- `execute`
- `observe`
- `verify`
- `replan`
- `final`
- `failed`

但 `AgentRuntimeGraph` 当前只有非常薄的 stage transition：

- `route()` 直接把 stage 改成 `plan`。
- `plan_ready()` 有 `graph_payload` 就进入 `execute`，没有就 `failed`。
- `execution_ready()` 直接进入 `observe`。
- `final()` 直接进入 `final`。

测试也只覆盖这些 stage 跳转，没有覆盖真实 plan/action/observation/verification/replan 状态机。

与此同时，真正的主入口仍在 `graph.py`：

```text
classify_intent
  -> answer_with_model
  -> answer_with_web
  -> choose_research_mode
  -> plan_research_graph
  -> request_required_inputs
  -> plan_task_graph
  -> END
```

`_with_model_policy_metadata()` 只是把 `agentRuntime: runtime_metadata("plan")` 写进 graph metadata，没有让 `AgentRuntimeGraph` 执行后续步骤。

结论：外部分析“AgentRuntimeGraph 有名字但没有权力”基本正确。它现在是 runtime metadata/stage primitive，不是主运行时。

### 3.3 执行层比主入口更成熟，但仍是 DAG runner

代码依据：

- `python/agent_service/execution.py`
- `python/agent_service/runtime_loop.py`
- `python/agent_service/run_journal.py`
- `python/agent_service/runtime_events.py`

执行层已经具备：

- topological node execution；
- `before_node`、`after_node`、`retrying`、`failed` checkpoint；
- `resume_checkpoint` 模式；
- latest checkpoint 与指定 checkpoint id 读取；
- low-risk retry 的一次自动继续；
- `runtime.checkpoint_recorded`、`runtime.resume_started`、`runtime.span_recorded` 事件；
- `authority.decision_recorded` 事件；
- run/node/audit/checkpoints JSON journal。

但它仍是“执行一个已经生成的图”，不是“统一 Agent runtime 主循环”。它不会自己从用户消息开始持续做：

```text
route -> build_context -> plan -> select_action -> execute -> observe -> verify -> replan/continue/final
```

结论：外部分析说“checkpoint/resume 有了但不是 durability”准确；同时需要补充，当前执行层已经不是空壳，它是一个可恢复 DAG runner 雏形。

### 3.4 业务流特化仍然存在

代码依据：

- `python/agent_service/execution.py`
- `python/agent_service/execution_graph.py`

`execution.py` 仍定义硬编码集合：

- `DOCUMENT_FLOW_NODE_IDS`
- `DATA_DEPENDENT_NODE_IDS`

`DocumentFlowExecutor.run()` 仍按具体 node id 分支：

- `document-input`
- `document-parse`
- `content-organize`
- `report-generate`
- `typst-export`
- `file-export`

`PlannedTaskExecutor` 虽然可以执行 `fixed_tool`，但仍内嵌 `DocumentFlowExecutor`，并在 node id 命中文档流时回退到文档 executor。

`execution_graph.py` 已抽象出：

- `ExecutionToolBinding`
- `ExecutionArgumentTemplate`
- `ExecutionInputMapping`
- `ExpectedArtifact`
- `ExecutionPermissionScope`

但默认模板仍围绕文档工具写死：

- `_DEFAULT_OPERATION_BY_TOOL`
- `_DOCUMENT_ARGUMENT_TEMPLATES`
- `_DOCUMENT_INPUT_MAPPINGS`
- `_DOCUMENT_EXPECTED_ARTIFACTS`

结论：外部分析“不是通用 Runtime 支持文档流，而是文档流长出了通用 Runtime 外观”偏尖锐，但核心判断正确。fixed_tool 路径已经泛化了一部分，所以不能说完全硬编码；但文档流仍是 runtime 层的特殊公民。

### 3.5 ToolCatalogPlanner 是单工具 planner

代码依据：

- `python/agent_service/tool_catalog_planner.py`
- `python/tests/test_tool_catalog_planner.py`

`ToolCatalogPlanner.plan()` 当前流程是：

1. `_select_tool()` 根据 token overlap 选一个工具。
2. `_operation_for_message()` 在该工具内选一个 operation。
3. `_argument_values_for_tool()` 绑定少量常见参数。
4. 生成一个 `fixed_tool` node。
5. 再接一个 `task-output` node。

它确实支持：

- `message` / `query`；
- `source_text` / `text` / `input`；
- `input_path`；
- `input_paths`；
- `output_path`；
- `source_output_path`；
- `pdf_output_path`；
- `metadata_value`。

但它不支持真正的多工具 DAG search，不做 input/output schema matching，不做 dependency output type unification，也不做替代工具选择。

结论：外部分析完全正确。当前 planner 对“用一个工具完成任务”越来越稳，但对“多个工具组合完成复杂任务”还没有核心解法。

### 3.6 ReAct 是局部能力，不是默认执行模型

代码依据：

- `python/agent_service/planner_chain.py`
- `python/agent_service/execution.py`
- `python/agent_service/react_controller.py`

`PlannerChain._react_metadata_for_request()` 只有在 `strategy == "legacy_task_planner"` 时返回 metadata。默认配置：

- `nativeToolCalls: False`
- `maxSteps: 4`
- `maxToolCalls: min(3, ...)`
- allowed permissions 只允许低风险读类权限。

`execution.py` 的 `_react_policy_for_node()` 会从 graph metadata 或 node-level `actionPolicies` 读取 ReAct policy。也就是说，ReAct 已经能跟 node 绑定，但它仍是 planner 生成的局部策略，不是 runtime 每一步 action selection 的默认模型。

结论：外部分析正确。ReAct 不应继续埋在某些 model node 分支里，而应成为 `AgentRuntimeEngine` 的 action selection 策略之一。

### 3.7 Checkpoint 是可恢复运行记录，不是持久化状态机

代码依据：

- `python/agent_service/runtime_loop.py`
- `python/agent_service/run_journal.py`
- `python/agent_service/schemas.py`

`RuntimeCheckpoint.to_record()` 当前生成：

```json
{
  "checkpointId": "{node_id}:{status}:{recovery_count}",
  "runId": "...",
  "nodeId": "...",
  "status": "...",
  "completedOutputs": {},
  "pendingNodeIds": [],
  "createdAt": "...",
  "recoveryCount": 0
}
```

`RunJournal` 将状态写入项目目录旁边的 `node-runs/{run_id}`：

- `run.json`
- `{node_id}.json`
- `audit.json`
- `checkpoints.json`

优点是简单、可审计、易调试。缺点是：

- checkpoint id 没有 thread id、sequence、parent checkpoint、graph hash、state version；
- JSON 写入没有事务性和并发写保护；
- checkpoint 存的是 completed outputs + pending nodes，不是完整 runtime state；
- 没有 state diff、pending writes、rollback/fork/time travel。

结论：外部分析准确。当前 checkpoint 是“可恢复 DAG run journal”，不是成熟 Agent durability。

### 3.8 Trace primitive 已有，但还不是 trace-first

代码依据：

- `python/agent_service/runtime_trace.py`
- `python/agent_service/runtime_events.py`
- `python/agent_service/tool_observation.py`
- `src/shared/events.ts`
- `src/features/task/useGraphRuntimeController.ts`

`RuntimeSpan` 已有：

- `trace_id`
- `span_id`
- `parent_span_id`
- `run_id`
- `node_id`
- `kind`
- `name`
- `status`
- `duration_ms`
- `metadata`

执行层会对 node execution 成功/失败 emit `runtime.span_recorded`。工具 gateway 会写 observation metadata，包括 tool id、provider id、duration、authority code、error code、runtime budget。

但缺口仍明显：

- model call 没有统一 `model.call` span；
- prompt 摘要、model id、token、finish reason、fallback/retry 未进入 span；
- 没有 AgentState / RuntimeState diff；
- 工具输入输出没有统一 redaction summary；
- trace 只作为事件发给前端状态，不是可查询、可回放、可对比的 trace store；
- eval case 没有绑定 trace。

结论：外部分析准确。当前是 observability primitive，不是 trace-first runtime。

### 3.9 Authority 进步明显，但不是 deny-by-default capability system

代码依据：

- `python/agent_service/authority.py`
- `python/agent_service/permission_gate.py`
- `python/agent_service/tool_gateway.py`
- `python/agent_service/execution.py`

已完成的进步：

- `AuthorityContext.from_invocation()` 不会把 `requested_permissions` 自动升级成 approved permissions。
- read roots 和 write roots 分离。
- sensitive permissions 覆盖 `network`、`run_local_cli`、`run_python_plugin`、`call_external_mcp_tool`。
- `_runtime_authority_context()` 会聚合 `request.approved_permissions` 和 `authority_grants`。
- `approved_tool_ids`、`read_roots`、`write_roots`、`network_domains`、`runtime_budget_ms` 已有 schema。
- `PermissionGate` 默认只允许 `read_attachment`、`read_project_files`、`write_project_artifact`。

仍存在的问题：

- `_authorize_tool_id()` 在 `approved_tool_ids` 为空时不限制工具 id。
- network domain enforcement 依赖 `invocation.metadata["networkDomain"]`，如果 provider 不填 domain，就不会触发。
- runtime budget 目前主要进入 observation metadata，并没有在 gateway 层强制 cancel provider execution。
- permission 仍偏字符串集合，没有形成 first-class capability request/approval object。
- write roots 默认是项目 artifacts 目录，这比之前安全，但仍不是全系统 deny-by-default grant。

结论：外部分析基本正确，但“安全模型只是半成品”的表述需要区分：权限和 authority 已经是可测试的进步；真正缺的是 capability-first enforcement 和强隔离执行。

### 3.10 Sandbox 不能宣传成强沙箱

代码依据：

- `python/agent_service/sandbox.py`

代码已经诚实标注：

- `SANDBOX_SECURITY_MODEL = "constrained_subprocess_runner"`
- `SANDBOX_SECURITY_BOUNDARY = "preflight_and_runtime_limits_not_os_isolation"`
- `backend = "subprocess"`
- `is_os_isolated = False`
- `is_process_tree_limited = False`

实际执行方式仍是：

```text
subprocess.run([sys.executable, script_path], ...)
```

它有价值的控制包括：

- AST preflight；
- 禁止常见网络 import/call；
- 禁止部分 process launch；
- 限制输出大小；
- 限制 artifact 数量与大小；
- 校验路径不逃逸 allowed roots；
- 清理 secret env 读取；
- timeout。

但这些不是 OS 级隔离，无法承受恶意 Python 代码的完整攻击面。

结论：外部分析完全正确。当前 sandbox 适合低风险临时脚本试运行，不适合宣传为“安全执行任意 Agent 代码”。

### 3.11 MCP 是 typed provider handoff，不是生态闭环

代码依据：

- `python/agent_service/tool_providers/mcp.py`
- `python/agent_service/tool_gateway.py`
- `src-tauri/src/preferences.rs`
- `src-tauri/src/commands.rs`
- `src-tauri/src/agent_client.rs`
- `python/agent_service/app.py`

当前已有：

- `McpProviderConfig`：provider id、display name、enabled、transport、command、url。
- `McpClient` protocol：`list_tools()`、`call_tool()`。
- `McpToolProvider`：将 MCP tool 映射成 `mcp:{provider_id}:{tool.name}`。
- lifecycle seam：`start()`、`health()`、`stop()` 按 `hasattr` 调用。
- `default_unified_tool_gateway()` 可注入 `mcp_provider_configs` 与 `mcp_client_factory`。
- Tauri preferences 支持 MCP provider config 保存、删除和刷新入口。

但默认路径仍没打通：

- 没有真实 stdio/http `McpClientFactory`。
- `default_unified_tool_gateway()` 没有 factory 时直接不加载 MCP provider。
- `AgentMessageRequest` 没有携带 MCP provider configs 或 external tools。
- `app.py` 的 `/agent/message` 不会从 preferences 构建 MCP provider。
- `src-tauri/src/agent_client.rs` 发送消息时没有 MCP handoff。
- `refresh_mcp_tool_provider_tools_for_preferences()` 只返回 synthetic `mcp:{provider_id}:status` 工具，而不是真实 `tools/list` 结果。

结论：外部分析准确。MCP 不是空接口，但仍是 provider seam 和配置入口，不是默认工具生态。

### 3.12 Memory 是安全上下文摘要，不是长期记忆系统

代码依据：

- `python/agent_service/memory_store.py`
- `python/agent_service/context_policy.py`
- `python/agent_service/context_manager.py`
- `python/agent_service/execution.py`

当前 `MemoryRecord.kind` 只有：

- `preference`
- `graph_summary`
- `artifact_summary`
- `tool_outcome`

存储方式是项目旁边的 JSONL。planning 时 `graph.py` 会读取 `MemoryStore(project_path).list()`，`context_policy.py` 会按 mode 选择 allowed kinds、max records 和 max chars。执行完成和 fixed-tool 失败会写 memory，除非 metadata 显式关闭 `memory.autoWrite`。

这已经是实用的“项目上下文摘要”。但它还不是长期记忆系统：

- 没有 schema version；
- 没有 importance、confidence、last_used_at、expires_at；
- 没有 semantic retrieval 或 BM25；
- 没有 conflict resolution；
- 没有用户可编辑/删除 UI；
- 没有 episodic memory；
- 没有从错误中抽取可复用经验；
- 没有 memory write approval/redaction policy。

结论：外部分析正确。短期应继续把它定位为 safe context memory，不要过早宣传长期记忆。

### 3.13 Eval 有基线，但 model-loop 仍是占位

代码依据：

- `python/agent_service/eval_harness.py`
- `python/evals/*.jsonl`
- `package.json`

当前 eval case 数量：

| 文件 | case 数 |
| --- | ---: |
| `router_cases.jsonl` | 10 |
| `planner_cases.jsonl` | 11 |
| `tool_cases.jsonl` | 10 |
| `research_cases.jsonl` | 10 |
| `security_cases.jsonl` | 22 |
| `model_loop_cases.jsonl` | 1 |
| 总计 | 64 |

`package.json` 已有：

```text
npm run agent:eval
```

但 `model_loop` 当前逻辑是：

- 环境变量 `ALITA_MODEL_LOOP_EVAL` 未开启时返回 skipped；
- 开启后返回 `model loop eval runner is not configured` 并失败。

仓库没有 `.github` 目录，也没有 GitHub Actions workflow。也就是说 eval harness 已经有，但还没有 CI gate。

结论：外部分析完全正确。Alita 已经开始像 Agent 平台一样写 eval 入口，但还没像 Agent 平台一样用 eval 管住质量。

### 3.14 多 Agent 不是下一阶段最高优先级

当前代码没有：

- agent role；
- team；
- handoff；
- termination condition；
- agent-to-agent messages；
- team-level shared state；
- role-specific tool grants。

这不是问题本身。当前更紧迫的是单 Agent runtime 主循环、durability、tool planning、MCP、sandbox、trace 和 eval。过早引入多 Agent 会放大现有 planner、state、权限和观测问题。

结论：外部分析关于“多 Agent 不是优先级第一”的判断正确。

## 4. 外部建议逐条判定

| 外部判断 | 核验结论 | 证据摘要 | 优先级 |
| --- | --- | --- | --- |
| `AgentRuntimeGraph` 是壳，不是主运行时 | 正确 | `agent_runtime_graph.py` 仅 stage transition；`graph.py` 仍 route 到 END | P0 |
| 业务流特化重 | 正确 | `DOCUMENT_FLOW_NODE_IDS`、`DocumentFlowExecutor.run()`、文档模板常量仍存在 | P0 |
| Tool Planner 不是 Agent 级规划器 | 正确 | `ToolCatalogPlanner` 只生成单 fixed_tool + output | P0 |
| ReAct 是局部策略 | 正确 | 仅 legacy planner 自动写 ReAct metadata，非 runtime 默认策略 | P1 |
| checkpoint/resume 不是 durability | 正确 | checkpoint 缺 thread/seq/parent/hash/state version/writes | P0 |
| trace primitive 不是 observability | 正确 | 有 span/event，但缺 model span、state diff、trace store、eval binding | P1 |
| 安全模型进步但不能宣传强沙箱 | 正确 | authority 进步明显；sandbox 明确不是 OS isolation | P0 |
| MCP lifecycle 只是 handoff | 正确 | provider seam 有，真实 stdio/http client 和 default sidecar path 缺 | P1 |
| memory 是摘要上下文，不是长期记忆 | 正确 | JSONL + recency/budget selection，无 retrieval/版本/置信度/过期 | P2 |
| model-in-loop eval 仍占位 | 正确 | `ALITA_MODEL_LOOP_EVAL` 开启后仍提示 runner 未配置 | P0 |
| 不急着做多 Agent | 正确 | 单 Agent runtime 未完成，多 Agent 会放大问题 | P2 |

## 5. 和成熟 Agent 项目的差距校准

这里不把外部项目当作“照抄目标”，而是抽取成熟 Agent runtime 的共性。

### 5.1 LangGraph：durable state 是运行语义，不是日志附件

LangGraph 的官方 persistence 文档将 persistence 绑定到 threads、checkpoints、state history、fault tolerance 和 time travel。对 Alita 的启发是：checkpoint 不应只是节点完成记录，而应成为 runtime state machine 的状态版本。

Alita 下一步应补：

- `thread_id`
- `checkpoint_seq`
- `parent_checkpoint_id`
- `graph_hash`
- `state_version`
- `writes`
- `pending_approvals`
- `runtime_state`
- `state_diff`

### 5.2 AutoGen：team 抽象有价值，但需要建立在单 Agent runtime 之上

AutoGen 的 AgentChat 团队模型强调多个 agents 通过 team 协议协作，例如 round-robin、selector、swarm 等团队模式。Alita 未来可以借鉴 role/team/handoff/termination condition，但现在不应优先实现 team。

原因是 Alita 还没有稳定的一等 action protocol 和 state machine。先做 team 会让权限、trace、eval、memory 和 tool planning 都变复杂。

### 5.3 CrewAI：agent/task/process/memory 应成为一等对象

CrewAI 的组织方式强调 agents、tasks、crews、process、memory 等概念。Alita 当前有节点图和 run，但 agent、task、process、memory 的对象边界还不清晰。后续可借鉴的是：

- task spec 和 action graph 分离；
- process 负责调度策略；
- memory 有可配置读写策略；
- usage metrics 和 callbacks 成为默认观测面。

### 5.4 MCP：工具生态需要真实 list/call/schema/lifecycle 闭环

MCP tools spec 围绕 `tools/list`、`tools/call`、`inputSchema`、`outputSchema`、tool annotations 和人工确认安全边界展开。Alita 的 `McpToolProvider` 映射模型方向正确，但还缺真实 transport client、schema cache、凭据注入、健康检查、reconnect、trace 和权限映射。

## 6. 下一阶段架构目标

建议把 0.34/0.35 的主题定义为：

```text
Agent Runtime Mainline
```

目标不是新增一个类，而是让所有任务进入统一 runtime state machine。

### 6.1 新增 AgentRuntimeEngine

建议新增 `AgentRuntimeEngine`，让它成为消息到执行的默认入口。

核心接口：

```python
class AgentRuntimeEngine:
    def start_run(self, message, project_context) -> RuntimeRun:
        ...

    def step(self, run_id: str) -> list[AgentEvent]:
        ...

    def resume(self, run_id: str, checkpoint_id: str | None = None) -> list[AgentEvent]:
        ...

    def interrupt(self, run_id: str, reason: str) -> list[AgentEvent]:
        ...
```

核心 state：

```python
class RuntimeState:
    thread_id: str
    run_id: str
    task_id: str
    stage: Literal[
        "route",
        "context",
        "plan",
        "approve",
        "act",
        "observe",
        "verify",
        "replan",
        "final",
        "failed",
        "interrupted",
    ]
    messages: list[dict]
    goal_spec: dict | None
    context_bundle: dict | None
    action_graph: dict | None
    selected_action: dict | None
    observations: list[dict]
    verification: dict | None
    pending_approvals: list[dict]
    memory_writes: list[dict]
    metadata: dict
```

每次 `step()` 都产生 `RuntimeStateDelta`：

```python
class RuntimeStateDelta:
    previous_checkpoint_id: str | None
    checkpoint_id: str
    stage_before: str
    stage_after: str
    decision: dict
    writes: list[dict]
    emitted_events: list[dict]
```

### 6.2 统一 Action Protocol

Runtime 层只认识四类 action：

```text
model_action
tool_action
human_action
control_action
```

文档处理、研究、代码任务、MCP 工具调用、临时脚本、用户澄清，都应该编译成这四类 action。

建议 schema：

```python
class RuntimeAction:
    action_id: str
    action_type: Literal["model", "tool", "human", "control"]
    name: str
    inputs: dict
    expected_outputs: dict
    permissions: list[CapabilityRequest]
    timeout_ms: int | None
    retry_policy: dict | None
    dependencies: list[str]
```

### 6.3 业务 executor 降级为 templates

迁移目标：

```text
document_flow_template -> ActionGraph
research_flow_template -> ActionGraph
runtime executes ActionGraph generically
```

保留文档/研究能力，但不要让它们在 runtime 层拥有特殊分支权。

阶段性迁移：

1. 让 `DocumentFlowExecutor` 只作为 compatibility adapter 存在。
2. 把 `document-input/document-parse/...` 编译成通用 `RuntimeAction`。
3. 删除 `DOCUMENT_FLOW_NODE_IDS` 对执行路径的控制。
4. 把 `ResearchFlowExecutor` 也迁移成 action graph template。

## 7. Tool Planning 优化方案

### 7.1 三层 planner

建议把当前 `ToolCatalogPlanner` 拆成三层。

第一层：Capability Retrieval

```text
TaskSpec -> RequiredCapabilities[] -> CandidateTools[]
```

可以先用 deterministic rules + token search，后续再接 BM25/embedding/LLM rerank。

第二层：Schema Planner

```text
CandidateTools + input/output schema -> ActionGraph
```

职责：

- 读取工具 input/output schema；
- 匹配已有 artifact/message/attachment/memory；
- 推断工具之间的 output -> input binding；
- 生成多节点 action graph；
- 标注缺失输入和需要用户确认的参数。

第三层：Graph Verifier

```text
ActionGraph -> validated executable graph
```

必须 deterministic：

- required arguments 全部满足；
- permissions 全部可解释；
- dependency outputs 类型匹配；
- artifact paths 不逃逸；
- network/domain grant 存在；
- failure fallback 可用；
- budget 不超过上限。

### 7.2 最小可行多工具规划

先支持以下常见 pipeline：

```text
attachments -> parse documents -> extract fields -> synthesize report -> export artifact
```

然后扩展：

```text
docx/xlsx/pdf -> normalized table/text -> compare/join -> markdown report -> docx/pdf export
```

短期不要追求 LLM 一次性规划完美。先把 deterministic schema validation 和 dependency resolution 做硬，再让 LLM 只参与候选排序和参数草拟。

## 8. Durability 优化方案

### 8.1 Checkpoint record v2

建议新增 v2 结构：

```json
{
  "threadId": "thread-...",
  "runId": "run-...",
  "checkpointId": "ckpt-...",
  "parentCheckpointId": "ckpt-...",
  "sequence": 12,
  "graphHash": "sha256:...",
  "stateVersion": 1,
  "stage": "observe",
  "createdAt": "...",
  "writes": [],
  "pendingApprovals": [],
  "runtimeState": {}
}
```

### 8.2 RunJournal v2

保留 JSON 文件可调试性，但增加基本可靠性：

- schema version；
- atomic write：写临时文件后 rename；
- append-only event log；
- checkpoint index；
- state snapshot；
- migration hook；
- partial write recovery；
- run lock。

### 8.3 Resume semantics

明确三种恢复：

- `resume_latest`：从最新 checkpoint 继续。
- `resume_checkpoint`：从指定 checkpoint 继续。
- `fork_checkpoint`：从指定 checkpoint 分叉新 run。

不要让“resume checkpoint”混用 source run id 和 current run id 的语义。

## 9. Observability 优化方案

### 9.1 Span taxonomy

统一 span kind：

```text
agent.route
agent.context
agent.plan
agent.action.select
model.call
tool.call
runtime.observe
runtime.verify
runtime.replan
human.approval
memory.read
memory.write
checkpoint.write
```

### 9.2 必填字段

每个 span 至少包含：

- trace id；
- span id；
- parent span id；
- run id；
- thread id；
- action id；
- kind；
- status；
- duration；
- sanitized input summary；
- sanitized output summary；
- error code；
- retry count；
- policy/budget。

### 9.3 Redaction 规则

默认不得进入 trace：

- API key、token、password；
- 本地绝对路径；
- 完整文档正文；
- 未授权的文件内容；
- provider raw error 中的敏感 header；
- 模型完整 prompt。

允许进入 trace：

- 文件名或 artifact id；
- schema 名称；
- 字符数、token 数、hash；
- 安全摘要；
- citation id；
- tool id 和 operation。

### 9.4 Trace UI

前端不只是 reducer 收事件，应提供：

- run timeline；
- action tree；
- model/tool span 明细；
- authority decision；
- checkpoint list；
- resume/fork 按钮；
- eval failure replay 链接。

## 10. 安全优化方案

### 10.1 Capability-first grant

把 permission string 升级为 capability request：

```python
class CapabilityRequest:
    capability: Literal["tool", "filesystem", "network", "process", "mcp", "model"]
    provider_id: str | None
    tool_id: str | None
    operation: str | None
    read_roots: list[str]
    write_roots: list[str]
    network_domains: list[str]
    runtime_budget_ms: int | None
    reason: str
```

原则：

```text
没有 grant，就不能执行。
```

gateway 不能只相信 tool/provider metadata，而应根据 manifest + invocation arguments 计算 capability request，然后和 grant 做匹配。

### 10.2 Sandbox 分层

短期：

- Windows Job Object；
- 子进程树回收；
- 工作目录 overlay；
- 环境变量白名单；
- 网络禁用；
- stdout/stderr/artifact 限额；
- runtime timeout 强制中断。

中期：

- Windows AppContainer 或低权限用户；
- WSL/Docker worker；
- 独立 sandbox service；
- 文件系统 mount/overlay；
- network namespace 或 deny-by-default proxy。

长期：

- tool execution worker pool；
- untrusted code 与 sidecar 进程隔离；
- policy engine + audit log；
- sandbox escape regression tests。

### 10.3 不应宣传的能力

在 README 和 UI 中避免使用：

- “安全执行任意代码”
- “强沙箱”
- “隔离运行环境”

更准确的表述：

```text
低风险脚本使用受控 subprocess runner，带 AST preflight、路径/输出/时间限制；它不是 OS 级隔离安全边界。
```

## 11. MCP 优化方案

### 11.1 真实 MCP client factory

新增：

- `StdioMcpClient`
- `HttpMcpClient`
- `McpClientFactory`
- provider supervisor；
- schema cache；
- credential resolver；
- lifecycle manager。

### 11.2 Preferences 到 sidecar

打通链路：

```text
Tauri preferences
  -> AgentMessageRequest / sidecar config endpoint
  -> McpProviderConfig
  -> McpClientFactory
  -> UnifiedToolGateway
  -> ContextBundle.available_tools
  -> PlannerChain
  -> Tool call
  -> Trace + Eval
```

### 11.3 MCP eval

新增 offline fake MCP eval：

- list tools；
- planner 发现 MCP tool；
- authority 拦截未授权 MCP call；
- 授权后调用；
- tool observation 包含 provider；
- trace 有 `tool.call` span；
- MCP failure 可恢复。

## 12. Memory 优化方案

### 12.1 Memory schema v2

建议字段：

```python
class MemoryRecordV2:
    memory_id: str
    schema_version: int
    scope: Literal["project", "global"]
    kind: str
    summary: str
    source_refs: list[str]
    source_type: str
    created_at: str
    updated_at: str | None
    last_used_at: str | None
    expires_at: str | None
    importance: float
    confidence: float
    visibility: Literal["private", "project", "global"]
    tags: list[str]
```

### 12.2 Retrieval

短期做 BM25/keyword scorer 即可：

- recency score；
- tag match；
- kind match；
- term overlap；
- importance/confidence；
- last_used boost。

后续再加 optional embedding，不要先引入复杂向量库。

### 12.3 Memory write policy

写入前需要：

- redaction；
- duplicate check；
- contradiction check；
- source trace；
- user-editable/delete path；
- task-level opt out。

## 13. Eval 与 CI 优化方案

### 13.1 三层 eval

第一层：deterministic regression，PR 必跑。

- router；
- planner；
- tool；
- authority/security；
- sandbox；
- research citation；
- MCP fake provider；
- checkpoint/resume。

第二层：offline model-loop。

- mock model；
- fixed responses；
- tool calling；
- ReAct action selection；
- failure recovery；
- verifier/replan。

第三层：real model benchmark。

- 本地 GGUF；
- 可选 API model；
- 成功率；
- tool call accuracy；
- replan success；
- citation correctness；
- latency；
- token/cost。

### 13.2 GitHub Actions

仓库当前没有 `.github` workflow。建议新增：

```yaml
name: ci

on:
  pull_request:
  push:
    branches: [main]

jobs:
  frontend:
    runs-on: windows-latest
    steps:
      - checkout
      - setup-node
      - npm ci
      - npm run frontend:typecheck
      - npm run frontend:test

  python:
    runs-on: windows-latest
    steps:
      - checkout
      - setup-python
      - pip install -e "python[test]"
      - pytest python/tests -q
      - npm run agent:eval
```

后续再加 nightly model-loop eval，不要阻塞普通 PR。

## 14. 推荐路线图

### P0：Agent Runtime Mainline

目标：统一主入口与运行状态。

任务：

1. 新增 `AgentRuntimeEngine`。
2. 定义 `RuntimeState`、`RuntimeAction`、`RuntimeStateDelta`。
3. 让 `/agent/message` 对 task 默认进入 runtime engine，而不是只创建 graph。
4. 把 `AgentRuntimeGraph` 从 stage wrapper 升级为 state machine。
5. 将 `run_graph_events()` 挂到 engine 的 `act/observe/verify` 阶段。
6. 为每个 step 写 checkpoint v2。
7. 增加 engine tests：route、plan、act、observe、verify、replan、final、interrupt、resume。

验收：

- 用户发起 task 后，系统能创建 run 并执行第一个 action。
- 每一步都有 checkpoint、span、state delta。
- task 可从 latest checkpoint 恢复。
- graph metadata 不再只是 `agentRuntime: plan`。

### P0：Checkpoint / Durability v2

目标：从 run journal 升级为可恢复 state machine。

任务：

1. 增加 checkpoint v2 schema。
2. 引入 thread id 与 checkpoint sequence。
3. 支持 parent checkpoint。
4. 记录 graph hash 和 state version。
5. atomic write。
6. resume latest / resume checkpoint / fork checkpoint 语义分离。
7. 增加 rollback/fork tests。

验收：

- 指定 checkpoint id 可以精确恢复。
- 同一 run 内 checkpoint 顺序稳定。
- graph 改变时能检测 hash mismatch。
- partial write 不破坏后续读取。

### P0：Eval + CI Gate

目标：防止 runtime 迭代破坏 invisible contract。

任务：

1. 增加 `.github/workflows/ci.yml`。
2. PR 跑 frontend typecheck/test。
3. PR 跑 Python pytest。
4. PR 跑 `agent:eval`。
5. model-loop 先用 mock runner，不依赖真实模型。
6. eval summary 产出 artifact。

验收：

- CI 能在 PR 上失败。
- `model_loop` 不再只是 skipped/未配置。
- runtime engine 核心 case 有 eval 覆盖。

### P0：Capability-first Safety

目标：所有工具调用统一由 gateway 计算 capability request。

任务：

1. 定义 `CapabilityRequest` 和 `CapabilityGrant`。
2. gateway 从 manifest + invocation arguments 计算 capability request。
3. network provider 必须报告 domain，否则拒绝联网。
4. runtime budget 变为实际 timeout/cancel。
5. `approved_tool_ids` 空集合不再意味着任意工具默认通过；改成按 action grant 或 low-risk default profile。
6. security eval 覆盖 MCP/network/write/process/runtime budget。

验收：

- 无 grant 的 MCP/network/CLI/script/write 默认拒绝。
- domain 缺失时联网工具拒绝。
- 超时能中断 provider。

### P1：Business Flow Template Migration

目标：文档/研究降级为 templates。

任务：

1. 定义 `ActionGraph`。
2. 编译 document template 到 ActionGraph。
3. 编译 research template 到 ActionGraph。
4. `PlannedTaskExecutor` 只执行 action，不识别业务 node id。
5. 删除或隔离 `DOCUMENT_FLOW_NODE_IDS`。
6. 保留 compatibility tests。

验收：

- 文档流不依赖 `DocumentFlowExecutor.run()` node id 分支。
- 研究流不依赖 runtime 特判。
- 新增业务流无需改 executor 主分支。

### P1：Multi-tool Planner

目标：从单工具 planner 升级为 schema-aware DAG planner。

任务：

1. capability retrieval。
2. schema planner。
3. deterministic graph verifier。
4. artifact flow binding。
5. fallback tool selection。
6. 多附件、多输出、多格式 eval。

验收：

- 能规划 `parse_docx -> parse_xlsx -> compare -> report -> export_docx` 这类多工具任务。
- 缺参数时请求用户输入，不生成不可执行图。
- schema mismatch 会在执行前失败。

### P1：MCP End-to-End

目标：真实 MCP 工具进入默认 planner/runtime。

任务：

1. stdio client。
2. HTTP client。
3. client factory。
4. credential resolver。
5. schema cache。
6. preferences -> sidecar handoff。
7. planner 默认发现 MCP tools。
8. MCP authority grant。
9. MCP trace/eval。

验收：

- 配置一个 stdio MCP server 后，Alita 能真实 list tools。
- planner 能看见 MCP tool。
- 授权后能 call tool。
- 失败能进入 trace 和 eval。

### P1：Trace-first Observability

目标：让复杂 Agent 任务可调试。

任务：

1. span taxonomy。
2. model.call span。
3. tool.call span。
4. state diff。
5. trace store。
6. trace UI。
7. eval case -> trace link。

验收：

- 每次 run 都能打开 trace timeline。
- 模型、工具、权限、checkpoint、replan 均可追踪。
- eval 失败能定位到具体 span。

### P2：Memory v2

目标：从上下文摘要升级为轻量长期记忆。

任务：

1. Memory schema v2。
2. migration。
3. retrieval scorer。
4. duplicate/conflict handling。
5. user-edit/delete UI。
6. memory write approval/redaction。

验收：

- planning 能按任务相关性选 memory。
- 过期/低置信 memory 不进入上下文。
- 用户可以删除错误记忆。

### P2：Multi-agent Team

目标：在单 Agent runtime 稳定后再引入角色协作。

前置条件：

- runtime action/state 稳定；
- capability grants 稳定；
- trace-first 已完成；
- eval 能覆盖 team failure；
- MCP/tool planning 已可控。

建议最小版本：

- `AgentRole`；
- `TeamSpec`；
- `handoff_action`；
- `termination_condition`；
- team-level trace；
- role-level grants。

## 15. 下一阶段应避免的坑

1. 不要继续让 README 领先代码。当前 README 的很多表述是事实，但容易让人误解 primitive 等于成熟能力。
2. 不要把 sandbox 说成强安全边界。当前代码很诚实，文档和 UI 也应保持诚实。
3. 不要急着做多 Agent。单 Agent 主循环未完成时，多 Agent 只会放大不可解释失败。
4. 不要继续按业务流堆 executor。新增能力应先变成 tool/action/template，而不是执行器里的 if 分支。
5. 不要把 LLM planner 当唯一解。最终必须有 deterministic graph validation。
6. 不要把 MCP 停留在 interface。下一轮必须跑通真实 server 的 list/call/eval/trace。
7. 不要只写 event，不建 trace store。事件能驱动 UI，但不能独立支撑复杂任务调试。

## 16. 建议提交序列

可以按下面顺序拆分开发分支：

1. `runtime: introduce AgentRuntimeEngine state model`
2. `runtime: route task messages through runtime engine`
3. `runtime: add checkpoint v2 with thread sequence and parent`
4. `runtime: emit state deltas for each engine step`
5. `eval: add mock model-loop runner`
6. `ci: add frontend python and agent eval gates`
7. `security: introduce capability request and grant schema`
8. `security: enforce network domains and runtime budgets`
9. `planner: add schema graph verifier`
10. `planner: support multi-tool action graph planning`
11. `runtime: migrate document flow to action template`
12. `runtime: migrate research flow to action template`
13. `mcp: implement stdio client factory`
14. `mcp: pass preferences provider configs to sidecar`
15. `observability: add model/tool span taxonomy and trace store`
16. `memory: add memory v2 schema and retrieval scorer`

## 17. 最终结论

外部分析整体准确，尤其是它抓住了 0.33.0 的主要矛盾：Alita 已经有 runtime、checkpoint、authority、trace、MCP、memory、eval 等关键 primitive，但这些还没有统一成为系统的控制平面。

当前最该做的是架构收束，而不是功能扩散：

```text
统一 runtime
统一 action
统一 state
统一 trace
统一 tool planning
统一 capability grant
```

只要这个内核打穿，Alita 后续接 MCP 生态、多工具任务、长期记忆、多 Agent team、模型 benchmark 都会顺很多。反过来，如果继续在当前业务 executor 和一次性 router 上堆功能，系统会越来越像“有很多 Agent 概念的工作流应用”，而不是可扩展的本地 Agent 平台。

## 18. 外部参考

- LangGraph Persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- AutoGen AgentChat Teams: https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/teams.html
- CrewAI Documentation: https://docs.crewai.com/
- Model Context Protocol Tools Specification: https://modelcontextprotocol.io/specification

## 19. Agent Runtime Mainline 实施结果

本轮实施完成了 runtime state/action/delta、AgentRuntimeEngine facade、checkpoint v2、mock model-loop eval、CI gate、capability request/grant、schema DAG planner、ActionGraph bridge、MCP client factory seam、TraceStore、Memory v2 retrieval。

仍未宣称完成的能力：

- 生产级 MCP stdio/http supervisor 和 credential broker。
- OS 级 sandbox 隔离。
- 完整多 Agent team runtime。
- 真实模型 benchmark 的 CI 门禁。
