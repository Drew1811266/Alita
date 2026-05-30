# Alita Agent 开发优化文档（0.31.0 代码核验版）

生成日期：2026-05-30  
核验对象：当前工作区 `D:\Software Project\Alita`，仓库版本 `0.31.0`

## 1. 总体结论

外部分析对 `0.30.0` 的判断整体中肯，但对当前仓库已经部分过时。当前代码已经合入 `Release 0.31.0 agent runtime closed loop`，`package.json` 和 `python/pyproject.toml` 都是 `0.31.0`，并且已有一批 closed-loop 方向的实现：

- planning 前默认读取项目 `MemoryStore`。
- tool gateway 默认执行路径会构造显式 `AuthorityContext`，read/write roots 已分离。
- `PermissionGate` 默认权限已收窄，不再默认允许 CLI/Python plugin。
- `ToolRuntimeLoader` 已支持 `module:function` Python function entrypoint。
- graph run 执行层已经写入 before/after/failed/retrying checkpoint。
- 低风险 `retry_node` 建议可以自动重试一次。
- PlannerChain 会在 legacy task planner 路径下生成受限 ReAct metadata。
- research flow 已输出 claim/evidence 结构。
- 前端已有 runtime observability 类型和 reducer，但后端事件还没有真正贯通。

因此，当前最准确的定位是：

```text
Alita 已经从“偏工作流的 Agent Runtime 原型”推进到“具备闭环执行雏形的本地 Agent Runtime”。

但它还不是成熟 Agent 平台，因为主入口仍是 route -> answer/plan -> END；
可恢复状态、MCP 生命周期、工具生态、强沙箱、观测面板和 model-in-loop eval 仍未打穿。
```

如果按本地 AI 工作台看，当前可以给 `8.3/10`；如果按成熟 Agent Runtime 看，当前约 `7.1/10`。相比外部分析里的 `6.7/10`，分数应上调，因为 0.31.0 已经修复了若干 P0 问题；但“默认自治 Agent 平台”的核心差距仍然存在。

## 2. 代码核验摘要

| 领域 | 当前状态 | 代码证据 | 结论 |
| --- | --- | --- | --- |
| 版本 | 已是 `0.31.0` | `package.json`, `python/pyproject.toml` | 外部文本的 `0.30.0` 判断已过时 |
| 主入口图 | 仍是一次路由到终点 | `python/agent_service/graph.py` `build_graph()` | 仍不是一等 `AgentRuntimeGraph` |
| 执行层闭环 | 有 checkpoint、失败建议、一次自动 retry | `python/agent_service/execution.py`, `runtime_loop.py`, `run_journal.py` | 比外部文本更强，但仍是 DAG runner |
| ExecutionGraph | binding schema 完整，但仍有文档流遗留 | `execution_graph.py`, `execution.py` | 部分正确，泛化未完成 |
| 工具运行时 | 已支持 function entrypoint，但 adapter dict 仍存在 | `tool_runtime.py`, `tool_execution.py` | 已从“纯 adapter”前进到混合态 |
| 权限 | 默认路径已强很多，但 fallback 仍会 approve invocation permissions | `authority.py`, `tool_gateway.py`, `permission_gate.py` | 方向正确，仍需强制 grant |
| Sandbox | AST preflight + subprocess | `sandbox.py` | 外部批评仍成立 |
| ReAct | native tool calls 可用；planner 只在 legacy 路径自动启用 | `react_controller.py`, `planner_chain.py` | 已增强，但还不是全局默认策略 |
| Memory | planning 默认读；run memory 写入仍需 metadata autoWrite | `graph.py`, `memory_store.py`, `execution.py` | 已部分闭环 |
| Eval | 63 条 deterministic eval；无真实模型质量基准 | `eval_harness.py`, `python/evals/*.jsonl` | 外部批评基本成立，但数量应更新 |
| MCP | Python provider 可注入；Tauri refresh 仅返回 status stub | `tool_gateway.py`, `tool_providers/mcp.py`, `src-tauri/src/commands.rs` | 还不是默认工具生态 |
| Research | claim/evidence 有结构；支持质量仍是引用存在性级别 | `research_evidence.py`, `execution.py` | 方向正确，严肃验证不足 |
| 前端观测 | 类型/reducer 有了；后端事件缺失 | `src/shared/events.ts`, `useGraphRuntimeController.ts`, `execution.py` | 前后端 contract 未贯通 |

## 3. 外部建议逐条判定

| 外部判断 | 当前判定 | 说明 |
| --- | --- | --- |
| 当前仓库仍是 `0.30.0` | 过时 | 当前 `package.json` 和 `pyproject.toml` 均为 `0.31.0` |
| 主 Agent Loop 不是默认自治闭环 | 仍然正确 | `graph.py` 仍是 `route -> answer/plan -> END` |
| ExecutionGraph 变厚且方向正确 | 正确 | binding、input mapping、expected artifact、permission scope 都存在 |
| ExecutionGraph 仍被文档流硬编码牵制 | 部分正确 | fixed_tool 已走 binding，但 `DOCUMENT_FLOW_NODE_IDS`、`DocumentFlowExecutor` 仍存在 |
| 工具系统像硬编码 adapter | 需要修正 | 现在已有 `ToolRuntimeLoader` 和 function entrypoint；但 document tools 仍走 adapter/file entrypoint，插件生态未完成 |
| Authority 默认授权偏宽 | 部分修复 | runtime 路径有显式 context；但 `AuthorityContext.from_invocation()` 和 `with_invocation_scope()` 仍会合并 requested permissions |
| PermissionGate 默认过宽 | 已明显修复 | 默认只允许 `read_attachment`、`read_project_files`、`write_project_artifact` |
| Sandbox 不是强隔离 | 正确 | 仍是 AST 检查 + `subprocess.run([sys.executable, script])` |
| ReAct 增强但不是默认执行策略 | 基本正确 | legacy planner 可自动写 metadata，但 document/tool catalog 路径不会自动启用 |
| Memory 没有默认进入 planning | 已修复一半 | `graph.py` planning 时读取 `MemoryStore(project_path).list()` |
| Memory 没有默认写入 | 仍正确 | run 后写 memory 仍依赖 `graph.metadata.memory.autoWrite == true` |
| Eval 偏冒烟测试 | 基本正确 | 已有 63 条 deterministic eval，但缺 model-in-loop benchmark |
| MCP 没进入默认网关 | 部分修复 | gateway 支持 provider config + client factory；默认执行路径还没有真实 preference/client lifecycle |
| Research 不是严肃 claim/evidence pipeline | 基本正确 | 有 `ResearchClaim`，但支持判断仍是 citation/excerpt presence |
| 下一步应做 Agent Team | 方向正确但优先级应降低 | 单 Agent runtime 的 checkpoint/resume、sandbox、eval、MCP 生命周期应先完成 |

## 4. 当前架构评价

### 4.1 主入口仍是 Router，不是一等 Runtime Graph

`graph.py` 的 `build_graph()` 仍然把 `classify_intent` 分发到 `answer_with_model`、`answer_with_web`、`choose_research_mode`、`plan_research_graph`、`request_required_inputs`、`plan_task_graph`，随后全部接 `END`。

这说明 Alita 的入口层仍是：

```text
route -> answer / create graph -> END
```

执行层 `run_graph_events()` 已经更接近：

```text
execute node -> observe output -> verify -> retry/fail/continue -> final verify
```

但这仍发生在“用户点击运行一个已有 graph”的阶段，而不是主 Agent graph 默认进入 `plan -> act -> observe -> verify -> replan -> final` 状态机。

下一步不应继续把逻辑塞进 `graph.py` 或 `execution.py`，而应单独抽出 `AgentRuntimeGraph` / `AgentRuntimeStateMachine`：

```text
route
  -> build_context
  -> plan
  -> validate_plan
  -> execute_next_action
  -> observe
  -> verify
  -> decide_continue_replan_or_interrupt
  -> final
```

### 4.2 执行层已有闭环雏形，但不是可恢复平台

0.31.0 的执行层比外部文本描述更强：

- 每个节点前写 `before_node` checkpoint。
- 节点完成后写 `after_node` checkpoint。
- 自动 retry 时写 `retrying` checkpoint 和 audit event。
- 节点失败时写 `failed` checkpoint。
- `RunJournal` 支持读取 latest checkpoint。
- `_can_auto_continue()` 限制只有自动 `retry_node` 且每节点最多一次。

但它还不是成熟 durability：

- checkpoint 是 Alita 自有 JSON 文件，不是 LangGraph checkpointer state。
- 没有用户级 resume/rollback/time travel API。
- 没有从 checkpoint 恢复 outputs 后继续 pending nodes 的主路径。
- 前端声明了 `runtime.checkpoint_recorded`，但 Python 后端当前没有 emit 这个事件。

参考 LangGraph 官方 persistence 设计，成熟路径应能按 thread/checkpoint 保存 state，并支持 human-in-the-loop、memory、time travel 和 fault-tolerance。

### 4.3 ExecutionGraph 通用化进入中段

正面变化：

- `ExecutionToolBinding` 已包含 provider、operation、arguments template、input mappings、output schema、expected artifacts、permission scope。
- fixed_tool 节点优先走 `_run_fixed_tool_node()`，按 binding 渲染参数，再通过 `UnifiedToolGateway` 调用工具。
- `validate_execution_graph_bindings()` 能拒绝缺失 binding 的 fixed_tool/model node。

遗留问题：

- `DOCUMENT_FLOW_NODE_IDS` 仍存在。
- `DocumentFlowExecutor` 仍被 `PlannedTaskExecutor` 持有，并复用其 artifact dir/allowed roots。
- `execution_graph.py` 中默认 operation/template/mapping/expected artifacts 仍主要围绕 document flow。
- `ResearchFlowExecutor` 是另一套特化 executor。

目标不是一次性删除所有特化 executor，而是把特化行为降级到工具/模型 binding 和 provider 层，让 runtime 不再靠 node id 识别业务流程。

### 4.4 工具系统已经不是纯 adapter，但还不是插件生态

0.31.0 引入了 `ToolRuntimeLoader`：

```text
manifest.entrypoint contains ":" -> load module:function
otherwise -> fallback adapter dict
```

`test_echo` 已经用 `runtime: python_function` 和 `entrypoint: tools.test_echo_tool:echo_values` 走真实 function entrypoint。这是从 demo adapter 走向插件 runtime 的关键一步。

仍然不足：

- document/markitdown/typst 仍主要依赖内置 adapter 或脚本式 entrypoint。
- manifest 对 CLI、Python function、内置 virtual tool、MCP tool 的 lifecycle 还没有统一。
- provider 启动/关闭、超时、日志、stderr、artifact、schema coercion 还没有形成完整 runtime contract。
- ToolCatalogPlanner 仍是 token overlap，required 参数只支持 `message/query/source_text/text/input/metadata_value`。

建议下一步定义统一 provider observation：

```json
{
  "toolId": "...",
  "providerId": "...",
  "ok": true,
  "structuredContent": {},
  "artifacts": [],
  "safeSummary": "...",
  "authorityCode": "allowed",
  "durationMs": 1234
}
```

### 4.5 Authority 已收紧，但 grant 模型还不够硬

当前已修复：

- runtime 默认构造 `AuthorityContext(approved_permissions, read_roots, write_roots)`。
- read roots 包含项目目录和附件目录。
- write roots 只指向项目旁的 `artifacts` 目录。
- sensitive permissions 已包含 `network`、`run_local_cli`、`run_python_plugin`、`call_external_mcp_tool`。
- PermissionGate 默认权限已缩到低风险读写。

仍需修：

- `UnifiedToolGateway` 如果没有 authority context，会 fallback 到 `AuthorityContext.from_invocation()`。
- `AuthorityContext.from_invocation()` 会把 invocation 的 requested permissions 放入 approved permissions。
- `with_invocation_scope()` 会把 context permissions 和 invocation requested permissions 合并，这会削弱“grant 决定权限”的边界。
- `network_domains` 和 `runtime_budget_ms` 目前是字段，不是实际强约束。
- `approved_tool_ids` 为空时表示不限制工具 id，而不是 deny by default。

建议的 Authority V2 原则：

```text
没有 explicit AuthorityGrant -> 只允许无副作用工具，拒绝所有 sensitive permissions。
invocation.requested_permissions 只能作为请求，不得自动升级为批准。
network domain、runtime budget、read/write roots 必须实际 enforce。
```

### 4.6 Sandbox 仍不是安全边界

当前 sandbox 已经具备脚本大小、输出大小、artifact 数量/大小、禁用危险 import、禁用进程 API、限制 artifact path 等 guard。本轮实施还将其安全模型显式标注为 `constrained_subprocess_runner` / `preflight_and_runtime_limits_not_os_isolation`，并补充了 `Path.write_text/write_bytes` 越过 artifact 目录、`socket.socket()` 等回归测试。

但它仍然是：

```text
AST preflight + subprocess.run([sys.executable, script_path])
```

这不是 OS-level sandbox。它没有：

- Windows Job Object 进程树限制。
- 低权限 Windows 用户/AppContainer。
- 文件系统虚拟化。
- syscall/network 硬隔离。
- CPU/内存硬限制。
- secret broker 隔离。

所以文档和 UI 仍应避免称它为“安全沙箱”。更准确的名字是：

```text
constrained local script runner
```

### 4.7 ReAct 已进入 planner，但覆盖面有限

外部文本说 ReAct 完全靠手工 metadata，这在 0.31.0 需要修正。`PlannerChain` 已经会在 `legacy_task_planner` 策略下根据 route tool candidates 生成：

- `enabled: true`
- `nativeToolCalls: false`
- `maxSteps: 4`
- `maxToolCalls`
- `allowedToolIds`
- `allowedPermissions`

但限制仍然明显：

- document_template 和 tool_catalog 策略不会自动生成 ReAct metadata。
- native tool calls 默认仍是 false。
- ReAct policy 还是 graph-level，不是 node-level。
- 工具失败后的 observation 没有统一进入 planner/replanner 的长期策略学习。

下一步应让 planner 输出 node-level action policy：

```text
model node requires exploration -> ReAct enabled
known deterministic fixed tool -> ReAct disabled
high-risk tool -> human approval required
```

### 4.8 Memory 已参与 planning，但还不是质量飞轮

0.31.0 已经在 `_graph_payload_for_task()` 中调用：

```text
MemoryStore(project_path).list()
```

这说明 planning 默认读 memory 的外部批评已经过时。

但仍未完成：

- run 后写 memory 仍要 graph metadata `memory.autoWrite == true`。
- 只支持 JSONL + scope/tags 过滤，没有关键词检索、embedding、去重、冲突消解、过期策略。
- preference memory 没有明确的人类确认路径。
- memory 没有可视化管理 UI。
- failure pattern/verifier diagnostics 没有稳定反馈给 PlannerChain。

建议从“默认写所有东西”改成“默认写低风险运行事实，敏感偏好需确认”：

```text
tool_outcome / graph_summary / artifact_summary: 默认写，脱敏后可删除。
preference: 只有用户确认后写。
security-sensitive failure: 只写错误类型和安全摘要，不写参数原文。
```

### 4.9 Eval 是 regression harness，不是能力基准

当前 eval 数量是 63 条：

- planner：11
- research：10
- router：10
- security：22
- tool：10

这比外部文本中的描述更强，且 security case 已覆盖 authority/sandbox/permission。

但它仍然无法度量：

- 模型路由准确率。
- ReAct/native tool call 参数质量。
- 工具组合规划正确性。
- 自动恢复成功率。
- claim 是否真的被 evidence span 支撑。
- memory 对规划质量的影响。
- token、耗时、成本、失败率。

建议分三层：

```text
PR gate: deterministic eval 全量 + 单元测试。
nightly: 小规模 model-in-loop eval，覆盖 planner/tool/recovery/research。
release gate: 安全、sandbox、MCP、claim support、cost regression。
```

### 4.10 MCP 仍是“可注入”，不是默认生态

Python 层 `default_unified_tool_gateway()` 已支持传入 `mcp_provider_configs` 和 `mcp_client_factory`。这比外部文本中的“只注册 internal”更进一步。

但默认运行路径仍没有真正接通：

- `_default_tool_gateway()` 没有从 preferences 读取 MCP provider config。
- 没有 stdio/http MCP client lifecycle。
- Tauri `refresh_mcp_tool_provider_tools_for_preferences()` 只返回一个 synthetic status tool。
- MCP tools 没有进入 PlannerChain 默认可用工具目录。
- `call_external_mcp_tool` 虽是 sensitive permission，但还缺 provider/domain/budget 级约束。

MCP 下一步的目标应该是端到端：

```text
Preferences -> sidecar provider config -> MCP client lifecycle
  -> UnifiedToolGateway.list_tools()
  -> PlannerChain available_tools
  -> AuthorityGrant
  -> call_tool()
  -> observation/journal/eval
```

### 4.11 前端 observability contract 还没有闭合

前端已有：

- `RuntimeCheckpointRecord`
- `AuthorityDecisionRecord`
- `RecoveryActionRecord`
- `runtime.checkpoint_recorded`
- `authority.decision_recorded`
- `recovery.action_proposed`
- `recovery.action_applied`
- `useGraphRuntimeController()` reducer

但后端当前没有 emit `runtime.checkpoint_recorded` / `authority.decision_recorded` / `recovery.action_proposed` / `recovery.action_applied`。执行层实际 emit 的是 `recovery.continued`，而前端事件类型没有定义它。

这会导致一个产品风险：前端看起来为 observability 做好了状态模型，但真实运行时用户看不到这些关键事件。

## 5. 与主流 Agent 项目的对照

这些项目不应被照搬，但它们揭示了当前成熟 Agent Runtime 的共同方向。

| 项目 | 可借鉴能力 | Alita 当前缺口 |
| --- | --- | --- |
| LangGraph | checkpointed graph state、threads、human-in-the-loop、time travel、fault tolerance | Alita 只有 journal/checkpoints 文件，还没有 resume/time travel 主路径 |
| LangSmith | end-to-end traces、evaluation、monitoring | Alita 有 node journal/eval，但缺统一 trace 和观测 UI |
| AutoGen | event-driven multi-agent runtime、MCP/Docker/distributed extensions | Alita ReAct/tool gateway 有雏形，但多 agent 与隔离执行不宜过早 |
| CrewAI | Crews + Flows，把协作 agent 和确定性 workflow 分层 | Alita 更像强 Flow 工作台，应先强化 runtime，再引入 Agent Team |
| OpenHands | SDK/CLI/Local GUI/Cloud 多入口、权限/RBAC/预算/集成 | Alita 本地桌面优势明显，但 sandbox、provider lifecycle、预算和协作还弱 |

## 6. 目标架构

Alita 最适合走的路线不是“全自动黑盒 Agent”，而是：

```text
本地优先、可视化、可审计、可恢复、可评估的 Agent Runtime Workbench
```

建议目标架构：

```text
User Message
  -> AgentRunState
  -> Router
  -> GoalSpec
  -> ContextBundle + ProjectMemory
  -> PlannerChain
  -> PlanValidator
  -> ExecutionGraph
  -> AgentRuntimeGraph
  -> AuthorityGrant
  -> UnifiedToolGateway
  -> Provider Runtime / Sandbox
  -> Observation
  -> ResultVerifier / FinalVerifier
  -> Replanner
  -> Journal + Trace + Memory
  -> Eval Feedback
```

强约束：

```text
任何工具调用、MCP 调用、模型 tool call、临时脚本、文件读写、CLI 执行，
都必须经过 UnifiedToolGateway -> AuthorityContext -> provider runtime -> observation -> verifier -> journal。
```

## 7. 优先级路线图

### P0：把 0.31.0 的闭环雏形变成一等 Runtime

目标：从 graph-run-level 闭环升级为默认 Agent Runtime 状态机。

建议任务：

1. 新增 `AgentRuntimeGraph`，显式建模 `plan/act/observe/verify/replan/final`。
2. 把 `run_graph_events()` 的 checkpoint、retry、failure suggestion 抽象成 runtime loop service。
3. 后端 emit `runtime.checkpoint_recorded`、`authority.decision_recorded`、`recovery.action_proposed/applied`，并统一替换或补齐 `recovery.continued`。
4. 实现 checkpoint resume：读取 latest checkpoint，恢复 completed outputs，只执行 pending nodes。
5. 实现 rollback/time travel 的最小 API：列 checkpoint、选择 checkpoint、fork run。
6. 将 `AuthorityContext.from_invocation()` 改为 deny-sensitive-by-default，requested permissions 不再自动批准。
7. `with_invocation_scope()` 不再合并 requested permissions，只合并 request metadata。

验收标准：

- 用户可从一次失败 run 的 checkpoint 恢复并继续。
- 前端能看到 checkpoint、authority decision、recovery action。
- 没有 explicit grant 时，高风险工具/MCP/network/CLI/script 都不能执行。

### P1：工具生态和 MCP 端到端

目标：让 manifest + provider 真正决定工具可发现、可授权、可执行、可观测。

建议任务：

1. 定义 `runtime` 枚举：`python_function`、`python_script`、`cli`、`builtin`、`mcp`。
2. document/markitdown/typst 迁移到统一 runtime loader，减少 adapter dict。
3. Provider lifecycle：start/list/call/stop/health。
4. Tauri preferences -> Python sidecar 的 MCP provider config 同步。
5. 实现 stdio/http MCP client factory。
6. MCP tools 进入 `ContextBundle.available_tools`。
7. ToolCatalogPlanner 升级为 schema-aware binding planner。
8. Provider observation 写入 journal/eval。

验收标准：

- 新增一个内部工具只需要 manifest + entrypoint，不需要改 `execution.py`。
- 配置 MCP provider 后，planner 能发现 MCP tool，并能在授权后调用。
- 所有 tool call 都有统一 observation 和 authority record。

### P2：安全与执行隔离

目标：模型生成代码和外部工具调用具备真实安全边界。

建议任务：

1. 将 `sandbox.py` 改名或标注为 constrained runner，避免误导。
2. 引入 Windows Job Object，限制进程树、CPU 时间、内存。
3. 支持低权限 Windows 用户或 AppContainer。
4. 可选 Docker/WSL backend。
5. 将网络访问改成代理 API，按 domain grant 放行。
6. 将 secret 访问改成 broker，工具不能继承完整 env。
7. 增加 sandbox escape eval：动态路径、符号链接/目录穿越、进程树、网络、secret、超大输出、artifact 越界。

验收标准：

- 低风险临时脚本不继承用户完整权限。
- 网络和 secret 必须通过授权 broker。
- 安全 eval 成为 release gate。

### P3：质量飞轮

目标：让 Agent 能力增长可度量、可回归、可调优。

建议任务：

1. model-in-loop eval：planner binding、native tool calls、ReAct recovery、research citation support。
2. scenario eval：从用户消息到 artifact 的端到端任务。
3. cost/time tracing：每个模型调用、工具调用、retry 都有耗时和 token/cost。
4. memory usefulness eval：有无 memory 时 plan 质量对比。
5. claim support eval：claim 与 evidence span 的语义支持评分。
6. eval dashboard 或 summary artifact。

验收标准：

- 每个 release 能回答“是否真的变强，成本是否上升，失败模式是什么”。
- regression 不只看 deterministic case，也看小规模真实模型任务。

### P4：Agent Team

目标：在单 Agent runtime 稳定后引入角色化协作。

最小角色建议：

- `PlannerAgent`
- `ExecutorAgent`
- `VerifierAgent`
- `ResearchAgent`
- `CriticAgent`

不建议现在优先做多 Agent。当前更重要的是 checkpoint/resume、Authority、sandbox、MCP、eval 和 observability。多 Agent 会放大现有系统复杂度和安全风险。

## 8. 建议的前 12 个 PR

1. `runtime: emit observability events from graph execution`
   - 后端 emit checkpoint/authority/recovery events。
   - 前端补齐 `recovery.continued` 或统一为 `recovery.action_applied`。

2. `runtime: resume graph run from latest checkpoint`
   - `RunJournal.read_latest_checkpoint()` 接入执行入口。
   - 恢复 `completed_outputs`，跳过已完成节点。

3. `security: make authority grants explicit`
   - 修改 `AuthorityContext.from_invocation()` 和 `with_invocation_scope()`。
   - requested permissions 不再自动成为 approved permissions。

4. `runtime: introduce AgentRuntimeGraph state machine`
   - 从 `graph.py` 的一次路由中抽出 default agent loop。

5. `tools: normalize provider observation contract`
   - 所有 internal/MCP/tool runtime 返回统一 metadata。

6. `tools: migrate document tools to runtime loader`
   - 减少 document adapter 特判。
   - 文档流完全靠 binding + manifest 执行。

7. `mcp: connect preferences to sidecar gateway`
   - Tauri provider config 传给 Python sidecar。
   - 实现 stdio/http client factory。

8. `planner: make ToolCatalogPlanner schema-aware`
   - 从 token overlap 升级到 schema required/optional 参数推断。

9. `react: emit node-level action policies`
   - planner 为 model node 输出 ReAct/native-tool policy。

10. `memory: default safe auto-write`
    - 默认写 graph/tool/artifact summary。
    - preference memory 需用户确认。

11. `sandbox: add Windows Job Object backend`
    - 限制进程树、CPU、内存和超时。

12. `eval: add model-in-loop benchmark suite`
    - 覆盖 planner/tool/recovery/research/memory/cost。

## 9. 不建议现在做的事

- 不建议现在大规模重写前端 UI。
- 不建议全局默认无限 ReAct。
- 不建议让模型自由生成并执行脚本。
- 不建议立即做复杂多 Agent team。
- 不建议先做工具市场。
- 不建议优先上云端分布式执行。

原因很简单：权限、沙箱、resume、MCP lifecycle、eval 和 observability 还没完成。先把单 Agent runtime 做硬，再扩张自治度。

## 10. 最终建议

外部分析的方向是对的，但需要按 0.31.0 当前代码修正优先级。Alita 已经不再只是“有 Agent 零件的工作流原型”，而是已经进入闭环 runtime 的早期实现阶段。

下一阶段最重要的主线是：

```text
AgentRuntimeGraph
  -> checkpoint resume
  -> explicit AuthorityGrant
  -> provider runtime/MCP lifecycle
  -> observability events/UI
  -> model-in-loop eval
  -> OS-level sandbox
```

这条线打通之后，Alita 才会真正从“可视工作台 + runtime core”升级为“可长期运行、可审计、可恢复、可扩展的本地 Agent 平台”。

## 11. Goal Mode 实施结果

本轮按 `docs/superpowers/plans/2026-05-30-agent-runtime-v031-implementation-plan.md` 执行，完成了一组可测试的 runtime 增量。实现重点是让 0.31.0 已有的闭环雏形更可观测、可恢复、可授权和可评估，同时避免过早声称 OS 级强沙箱或完整 MCP 生命周期。

| Phase | 状态 | 主要结果 | 验证 |
| --- | --- | --- | --- |
| Phase 1 Runtime Observability | 完成 | 后端 emit checkpoint、authority decision、recovery action；前端兼容 `recovery.continued` | `pytest tests/test_execution.py tests/test_tool_gateway.py`, Vitest runtime/permission reducer, `agent:eval` |
| Phase 2 Checkpoint Resume | 完成 | 新增 `resume_checkpoint` run mode，可从 latest checkpoint 恢复 completed outputs 并只跑 pending nodes | `pytest tests/test_run_journal.py tests/test_execution.py tests/test_agent_run_state.py`, Vitest task events |
| Phase 3 Explicit AuthorityGrant | 完成 | 新增 `AuthorityGrant`；`requested_permissions` 不再自批 sensitive permissions；security eval 增补 authority case | `pytest tests/test_authority.py tests/test_tool_gateway.py tests/test_execution_gateway_integration.py tests/test_eval_harness.py`, `agent:eval` |
| Phase 4 Provider Observation | 完成 | Gateway 为工具调用记录 observation metadata；节点 journal 保存工具 observation | `pytest tests/test_tool_gateway.py tests/test_mcp_tool_provider.py tests/test_tool_execution.py tests/test_execution.py`, `agent:eval` |
| Phase 5 MCP Discovery Path | 完成 | MCP config 增加 transport/command/url；ContextBundle 支持 external MCP tool capability 注入 | `pytest tests/test_mcp_tool_provider.py tests/test_tool_gateway.py tests/test_context_manager.py tests/test_planner_chain.py`, `agent:eval` |
| Phase 6 Planner/ReAct/Memory/Eval | 完成 | Planner 输出 node-level action policy；执行器优先读取 node-level ReAct policy；memory 默认安全写入；eval 增加 action policy 指标 | `pytest tests/test_planner_chain.py tests/test_memory_store.py tests/test_eval_harness.py tests/test_react_controller.py tests/test_execution.py`, `agent:eval` |
| Phase 7 Sandbox Posture | 完成 | Sandbox 明确标注为 constrained subprocess runner，补充 write_text artifact escape 和 socket call 回归测试 | `pytest tests/test_sandbox.py tests/test_eval_harness.py`, `agent:eval` |

最终全量验证：

- `npm run agent:eval`：`63/63 passed, 0 failed`。
- `cd python; python -m pytest`：`734 passed`。
- `npm run frontend:typecheck`：exit `0`。
- `npm run frontend:test`：`32` test files，`210` tests passed。
- `cd src-tauri; cargo test`：exit `0`，Rust/Tauri 单元与集成测试通过。
- `git diff --check`：exit `0`，只有 CRLF 转换 warning。

仍未完成的长期项：

- `AgentRuntimeGraph` 仍是后续重点；本轮增强的是 graph-run execution loop，不是完全替换 `graph.py` 的入口路由。
- MCP 已有 typed discovery/injection path，但还没有真实 stdio/http client lifecycle 和 credential 管理。
- Sandbox 仍不是 OS-level isolation；Windows Job Object、AppContainer、低权限用户或 Docker/WSL backend 仍需后续阶段实现。
- Eval 仍是 deterministic regression harness；model-in-loop benchmark 和 cost tracing 仍需单独建设。

## 12. 参考资料

- LangGraph Persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- LangSmith Observability Quickstart: https://docs.langchain.com/langsmith/observability-quickstart
- AutoGen Documentation: https://microsoft.github.io/autogen/stable/index.html
- CrewAI Introduction: https://docs.crewai.com/en/introduction
- CrewAI Flows: https://docs.crewai.com/en/concepts/flows
- OpenHands Introduction: https://docs.openhands.dev/overview/introduction
