# Alita Agent 开发优化文档（0.32.0 代码核验版）

生成日期：2026-05-30  
核验对象：当前工作区 `D:\Software Project\Alita`，`main` 分支，代码版本 `0.32.0`

## 1. 总体结论

外部分析的方向基本正确，但它描述的是 Alita 较早阶段的架构状态。当前仓库已经合入 `Release 0.31.0 agent runtime closed loop` 和 `Release 0.32.0 agent runtime optimization`，所以很多 P0 级问题已经被修复或推进到“可测试雏形”。

当前最准确的定位是：

```text
Alita 是一个本地优先、可视化、可审计的 Agent Runtime Workbench。
它已经具备单 Agent 闭环执行的早期内核，但还不是成熟的通用自治 Agent 平台。
```

外部分析里最核心的判断仍然成立：

- 主入口 `graph.py` 仍是一次性 `route -> answer / create graph -> END`，不是默认的 `plan -> act -> observe -> verify -> replan -> final` 状态机。
- 文档流和研究流仍保留明显的业务特化 executor。
- MCP 还不是默认工具生态，真实 stdio/http client lifecycle、凭据注入和 planner 默认发现没有打通。
- Sandbox 仍是受控 subprocess runner，不是 OS 级隔离。
- Eval 仍以 deterministic regression 为主，不足以证明模型自治能力持续变强。

但外部分析里这些判断已经过时：

- 权限不再默认允许 CLI/Python plugin；`PermissionGate` 默认只允许 `read_attachment`、`read_project_files`、`write_project_artifact`。
- `AuthorityContext.from_invocation()` 不再把 requested permissions 自动批准；read roots 与 write roots 已分离。
- 工具系统不再是纯 adapter dict；`ToolRuntimeLoader` 已支持 `module:function` Python function entrypoint。
- 执行层已经有 `before_node`、`after_node`、`retrying`、`failed` checkpoint，并支持 `resume_checkpoint`。
- 后端已经 emit `runtime.checkpoint_recorded`、`authority.decision_recorded`、`recovery.action_proposed/action_applied`，前端 reducer 也能接收这些事件。
- planning 前会读取项目 `MemoryStore`；run 完成和 fixed-tool 失败会默认写入安全摘要 memory，除非 graph metadata 显式关闭。
- PlannerChain 已能输出 node-level `actionPolicies`，ReAct 不再完全依赖手写 graph metadata。

建议更新后的评分：

| 维度 | 当前评分 | 说明 |
| --- | ---: | --- |
| 本地 AI 桌面工作台 MVP+ | 8.5/10 | 工程文件、桌面壳、文档/研究/工具/artifact 闭环已经扎实 |
| 单 Agent Runtime 雏形 | 7.3/10 | 有状态、权限、gateway、checkpoint、resume、ReAct、memory、eval，但默认 AgentRuntimeGraph 未完成 |
| 可扩展 Tool Runtime | 6.4/10 | 有统一 gateway、provider、manifest、function entrypoint、MCP provider 抽象；runtime enum/lifecycle/schema-aware planner 仍不足 |
| 安全可执行本地 Agent | 6.2/10 | 权限已明显收紧，但 sandbox 不是 OS 隔离，network/domain/budget enforcement 仍弱 |
| 可观测与可评测工程 | 6.6/10 | runtime events 和 observation metadata 已贯通；trace-first、model-in-loop eval、成本/延迟指标仍缺 |
| 通用自治 Agent 平台 | 6.0/10 | 还没有默认自治 loop、多工具动态规划、MCP 生态、多 Agent team 和强沙箱 |

## 2. 当前代码事实

### 2.1 版本状态

代码事实：

- `package.json` 版本是 `0.32.0`。
- `python/pyproject.toml` 版本是 `0.32.0`。
- `src-tauri/Cargo.toml` 和 `src-tauri/tauri.conf.json` 也已随 0.32.0 release 更新。
- `README.md` 仍写着“当前仓库版本为 `0.31.0`”，这是文档滞后。

结论：外部分析如果基于 0.30/0.31 代码，需要按 0.32.0 重新修正优先级。

### 2.2 主 Agent 入口仍是 Router

代码依据：

- `python/agent_service/graph.py`

`build_graph()` 仍使用 LangGraph `StateGraph`，入口是 `classify_intent`，随后按 intent 分发到：

- `answer_with_model`
- `answer_with_web`
- `choose_research_mode`
- `plan_research_graph`
- `request_required_inputs`
- `plan_task_graph`

这些节点最后都接到 `END`。

这说明主 Agent 入口仍是：

```text
classify -> answer / ask / create graph -> END
```

而不是成熟 Agent runtime 常见的：

```text
plan -> act -> observe -> verify -> replan -> continue -> final
```

外部分析关于“主图还是路由器，不是自治运行时”的判断仍然正确。

### 2.3 执行层已经比外部描述更强

代码依据：

- `python/agent_service/execution.py`
- `python/agent_service/runtime_loop.py`
- `python/agent_service/run_journal.py`
- `python/agent_service/runtime_events.py`
- `python/agent_service/schemas.py`

当前执行层已经具备：

- `RuntimeCheckpoint`，记录 `runId`、`nodeId`、`status`、`completedOutputs`、`pendingNodeIds`、`recoveryCount`。
- 每个节点执行前写 `before_node` checkpoint。
- 节点完成后写 `after_node` checkpoint。
- 低风险自动恢复时写 `retrying` checkpoint。
- 节点失败时写 `failed` checkpoint。
- `RunMode.type` 支持 `resume_checkpoint`。
- resume 时读取 `RunJournal.read_latest_checkpoint()`，恢复 completed outputs，只执行 pending nodes。
- 后端 emit `runtime.resume_started`。
- 后端 emit checkpoint、authority decision、recovery action 观测事件。

但它还不是成熟 durability：

- checkpoint 是 Alita 自有 JSON journal，不是 LangGraph checkpointer thread state。
- `checkpoint_id` 字段存在，但当前 resume 主路径读取的是 latest checkpoint，不是按指定 checkpoint 精确恢复。
- 没有 rollback、fork run、time travel、后台多 run 队列。
- 主入口 `graph.py` 没有默认进入这个 runtime loop；用户仍需要生成 graph 后运行 graph。

结论：外部分析“状态/恢复偏轻”需要修正为“执行层已有 checkpoint/resume 雏形，但还没有平台级可恢复状态机”。

### 2.4 ExecutionGraph 已通用化到中段

代码依据：

- `python/agent_service/execution_graph.py`
- `python/agent_service/execution.py`

当前 `ExecutionGraph` 已经包含：

- `ExecutionToolBinding`
- `ExecutionModelBinding`
- `ExecutionArgumentTemplate`
- `ExecutionInputMapping`
- `ExpectedArtifact`
- permission scope

`PlannedTaskExecutor._run_fixed_tool_node()` 会按 binding 渲染参数，通过 `UnifiedToolGateway` 调用工具。这说明固定工具节点已经不再完全依赖 node id 特判。

遗留问题仍然明显：

- `execution.py` 仍保留 `DOCUMENT_FLOW_NODE_IDS` 和 `DocumentFlowExecutor`。
- `ResearchFlowExecutor` 仍按 `research-*` node id 分支执行。
- `execution_graph.py` 的默认 operation/template/input mapping/expected artifacts 仍主要围绕文档工具。
- `DocumentFlowExecutor` 和 `ResearchFlowExecutor` 仍是业务流特权路径。

结论：外部分析“执行器被文档流/研究流绑定”仍然部分成立，但需要补充：0.32.0 已经把一部分 fixed-tool 执行迁到 binding/gateway 路径。

### 2.5 工具系统已从纯 adapter 进入混合态

代码依据：

- `python/agent_service/tool_execution.py`
- `python/agent_service/tool_runtime.py`
- `python/agent_service/tool_gateway.py`
- `python/agent_service/tool_providers/internal.py`
- `tool-packages/*/manifest.json`

正面变化：

- `UnifiedToolGateway` 是工具调用入口。
- `InternalToolProvider` 把 manifest tool 映射成 `UnifiedToolDefinition`。
- `ToolRuntimeLoader` 支持 `entrypoint` 为 `module:function` 的 Python function runtime。
- `tool-packages/test_echo/manifest.json` 已使用 `runtime: python_function` 和 `entrypoint: tools.test_echo_tool:echo_values`。
- tool result metadata 已包含 observation：`toolId`、`providerId`、`ok`、`durationMs`、`authorityCode`、`errorCode`。

仍然不足：

- `ToolExecutor` 仍保留三类核心 adapter：`document.receive_attachment`、`document.markitdown_convert`、`document.typst_compile`。
- `document.read_write` manifest 的 entrypoint 是脚本路径 `python/tools/document_tool.py`，不是 `module:function`；且 manifest 没有 `operations` 列表，当前不是真正完整可执行插件。
- `markitdown` 和 `typst` manifest 仍是 `python_sidecar` + adapter 路径，不是统一 runtime enum。
- 没有 provider lifecycle：start/list/call/stop/health/reload。
- CLI runtime、Python script runtime、builtin runtime、MCP runtime 还没有统一 contract。

结论：外部分析“工具生态太薄”仍成立，但“只有三个 adapter”已经不完整。准确表述应是：Alita 已有 gateway/provider/runtime loader 骨架，但真实可执行工具生态仍薄，核心业务工具仍依赖历史 adapter。

### 2.6 ToolCatalogPlanner 仍是启发式

代码依据：

- `python/agent_service/tool_catalog_planner.py`

当前工具选择逻辑仍是：

```text
user text tokens 与 tool id/name/capabilities/operations tokens 求交集
score >= 2 才选择工具
```

参数填充只支持少量字段：

- `message`
- `query`
- `source_text`
- `text`
- `input`
- `metadata_value`

这不足以处理：

- 多工具组合 DAG。
- schema required/optional 参数推断。
- 上游输出到下游输入的类型匹配。
- 文件/目录集合、Excel、邮件草稿、浏览器、MCP 工具链等复杂任务。
- 失败后替代工具选择。

结论：外部分析“Tool Planner 近似关键词匹配”仍然正确，是 P1/P2 之间的关键优化点。

### 2.7 权限模型已明显收紧

代码依据：

- `python/agent_service/authority.py`
- `python/agent_service/permission_gate.py`
- `python/agent_service/tool_gateway.py`
- `python/agent_service/execution.py`

已修复的点：

- `PermissionGate.DEFAULT_ALLOWED_PERMISSIONS` 只包含 `read_attachment`、`read_project_files`、`write_project_artifact`。
- `run_local_cli`、`run_python_plugin`、`network`、`call_external_mcp_tool` 是 sensitive permissions。
- `AuthorityContext.from_invocation()` 不再把 `requested_permissions` 自动批准。
- `with_invocation_scope()` 不再把 invocation requested permissions 合并进 approved permissions。
- read roots 与 write roots 已分离。
- graph runtime 默认 write root 是项目旁的 `artifacts` 目录。
- gateway 在调用 provider 前会进行 schema 校验、authority 校验，并 emit authority decision。

仍然不足：

- `approved_tool_ids` 为空表示“不限制 tool id”，不是 deny by default。
- `network_domains` 和 `runtime_budget_ms` 存在于 context，但当前没有形成强 enforcement。
- RunGraphRequest 仍以 `approved_permissions` 为主，没有完整的 `AuthorityGrant` 请求结构，例如 tool allowlist、domain allowlist、runtime budget、approval token scope。
- 对外部 MCP provider 的权限粒度还停留在 `call_external_mcp_tool`，没有 provider/tool/domain/budget 细分。

结论：外部分析“权限默认偏宽”的具体说法已经过时；但如果目标是成熟本地 Agent 平台，Authority 仍需升级为显式 grant/capability token 模型。

### 2.8 Sandbox 仍不是安全边界

代码依据：

- `python/agent_service/sandbox.py`

当前 sandbox 已明确标注：

```text
SANDBOX_SECURITY_MODEL = "constrained_subprocess_runner"
SANDBOX_SECURITY_BOUNDARY = "preflight_and_runtime_limits_not_os_isolation"
```

它已有实用 guard：

- AST preflight。
- 脚本大小限制。
- stdout/stderr 限制。
- artifact 数量和大小限制。
- 最小环境变量集。
- 拦截部分 import、dynamic import、secret env、network socket、process launch。
- 检查部分 literal path 文件 API。
- 强制 stdout JSON。

但它仍然不是 OS isolation：

- 没有 Windows Job Object 进程树限制。
- 没有低权限 Windows 用户或 AppContainer。
- 没有 Docker/WSL backend。
- 没有文件系统 overlay。
- 没有 network egress ACL。
- 没有 secret broker。
- 动态构造路径、未覆盖标准库 API 和解释器能力面仍有风险。

结论：外部分析“不要把它宣传成安全沙箱”完全正确。当前更准确的名称是 constrained local script runner。

### 2.9 ReAct 已进 planner，但还不是默认行动模型

代码依据：

- `python/agent_service/react_controller.py`
- `python/agent_service/planner_chain.py`
- `python/agent_service/execution.py`
- `python/agent_service/model_client.py`
- `python/agent_service/model_tool_adapter.py`

当前能力：

- `ReActController` 支持 native tool calls 和 JSON fallback。
- `OpenAICompatibleModelClient.chat_with_tools()` 能发送 OpenAI-compatible `tools` / `tool_choice` 并解析 `tool_calls`。
- `PlannerChain` 在 `legacy_task_planner` 策略下会生成 graph-level `react` metadata。
- `PlannerChain` 也会生成 node-level `actionPolicies`。
- `execution.py` 优先读取 node-level action policy，再 fallback graph-level ReAct metadata。

限制：

- `document_template` 和 `tool_catalog` 策略不会自动生成 ReAct policy。
- `nativeToolCalls` 默认仍是 false。
- action policy 只覆盖 planner 认为需要 legacy model exploration 的场景。
- ReAct observation 还没有进入长期 planner quality loop。
- 主入口 chat agent 仍不是默认 ReAct tool-calling agent。

结论：外部分析“ReAct 是补丁，不是主运行模型”需要修正为：ReAct 已进入 planner/executor contract，但仍不是 Alita 的默认 Agent 行动模型。

### 2.10 Memory 已默认读写，但还不是长期语义记忆

代码依据：

- `python/agent_service/graph.py`
- `python/agent_service/memory_store.py`
- `python/agent_service/context_manager.py`
- `python/agent_service/context_policy.py`
- `python/agent_service/execution.py`

当前能力：

- planning 前调用 `MemoryStore(project_path).list()`。
- `ContextBundle` 有 `memory_summaries`。
- `context_policy` 按预算选择 memory。
- run 完成后默认写 `graph_summary`、fixed-tool `tool_outcome`、`artifact_summary`。
- fixed-tool 失败会写失败 outcome。
- `graph.metadata.memory.autoWrite == false` 时可以关闭自动写入。

限制：

- 存储仍是项目旁 JSONL。
- 检索是 recent/kind/tag/budget 筛选，不是 semantic search。
- 没有 embedding、BM25、去重、压缩、冲突消解、TTL、scope policy。
- preference memory 缺少用户确认和 UI 管理。
- verifier diagnostics、failure pattern 对 planner 的反馈仍很弱。

结论：外部分析“Memory 没进入默认闭环”已经过时；准确问题是 Memory 进入了默认闭环，但还只是可追踪摘要，不是长期语义记忆系统。

### 2.11 Research flow 方向正确，但仍是特化流程

代码依据：

- `python/agent_service/web_research.py`
- `python/agent_service/execution.py`
- `python/agent_service/research_evidence.py`

当前研究流包含：

- intent analysis。
- privacy guard。
- query plan。
- research-parallel-search。
- source review。
- source reading。
- report synthesis。
- quality check。
- Markdown output。
- `ResearchClaim` 和 `EvidenceRef`。
- citation coverage 和 claim-level citation diagnostics。

问题：

- `research-parallel-search` 当前仍是 `for query_unit in query_units` 顺序调用，不是真正并发搜索。
- 报告合成仍主要是 deterministic markdown synthesis。
- `ResearchClaim.support_status` 主要基于是否存在 citation/excerpt，不是语义支持判断。
- 没有 source dedupe graph、crawl budget、claim conflict resolution、多轮 query refinement。

结论：外部分析“parallel search 名不副实”和“研究 Agent 还不强”仍然正确，但当前 claim/evidence 结构已经比外部文本描述更进一步。

### 2.12 MCP 是 typed handoff，不是默认生态

代码依据：

- `python/agent_service/tool_providers/mcp.py`
- `python/agent_service/tool_gateway.py`
- `python/agent_service/context_manager.py`
- `src-tauri/src/preferences.rs`
- `src-tauri/src/commands.rs`
- `python/agent_service/app.py`
- `src-tauri/src/agent_client.rs`

当前能力：

- `McpProviderConfig` 已有 `provider_id`、`display_name`、`enabled`、`transport`、`command`、`url`。
- `McpToolProvider.list_tools()` 能把 MCP tool 映射为 `mcp:{provider_id}:{tool.name}`。
- MCP tool permissions 包含 `call_external_mcp_tool`。
- `default_unified_tool_gateway()` 支持传入 `mcp_provider_configs` 和 `mcp_client_factory`。
- `ContextBundle` 支持 external tool capability merge。
- Tauri preferences 支持 MCP provider config 的 CRUD。

核心缺口：

- 默认 sidecar API path 没有从 preferences 构建 MCP client factory。
- `AgentMessageRequest` 没有携带 MCP provider config 或 external tools。
- `src-tauri/src/agent_client.rs` 发送 agent message 时没有 MCP provider handoff。
- `refresh_mcp_tool_provider_tools_for_preferences()` 仍返回 synthetic `mcp:{provider_id}:status` 工具，而不是真实 `tools/list`。
- 没有 stdio/http MCP process lifecycle、credential injection、schema cache、health、reconnect、timeout、redaction、tool list changed handling。

结论：外部分析“MCP 还停在接入口”仍然基本正确；只是当前已经不是空 stub，而是 typed provider handoff + fake/discovery path。

### 2.13 Observability 已贯通事件，但还不是 trace-first

代码依据：

- `python/agent_service/runtime_events.py`
- `python/agent_service/tool_observation.py`
- `python/agent_service/execution.py`
- `src/shared/events.ts`
- `src/shared/types.ts`
- `src/features/task/useGraphRuntimeController.ts`
- `src/features/permissions/usePermissionController.ts`

当前能力：

- 后端 emit runtime checkpoint、authority decision、recovery proposed/applied。
- `UnifiedToolGateway` 把 observation metadata 写入 tool result。
- node output 会携带 observation。
- 前端 reducer 保存 checkpoints、authority decisions、recovery actions。
- 前端也兼容 `recovery.continued` legacy event。

缺口：

- 没有统一 trace id / span id / parent span id。
- 没有 LLM call prompt/response/token/latency/cost trace。
- 没有 tool args/output redaction policy。
- 没有 trace viewer、filter、export、eval replay。
- 没有把 eval case 和 runtime trace 绑定。

结论：外部分析“只有 JSON 日志”已经过时；但“缺少 trace-first 思维”仍是准确的下一阶段问题。

### 2.14 Eval 是强 regression harness，不是能力 benchmark

代码依据：

- `python/agent_service/eval_harness.py`
- `python/evals/*.jsonl`
- `package.json`

当前 eval case 数：

| 文件 | 数量 |
| --- | ---: |
| planner_cases.jsonl | 11 |
| research_cases.jsonl | 10 |
| router_cases.jsonl | 10 |
| security_cases.jsonl | 22 |
| tool_cases.jsonl | 10 |
| 总计 | 63 |

Eval 已覆盖：

- router。
- planner。
- tool。
- research。
- security。
- action policy count。
- claim count / unsupported claim count。

仍然不能衡量：

- 真实模型路由准确率。
- ReAct/native tool call 参数质量。
- 多工具组合规划正确性。
- checkpoint resume 的真实长任务恢复率。
- claim 是否被 evidence span 语义支持。
- memory 对规划质量的提升。
- token、耗时、成本、失败聚类。

结论：外部分析“eval 还不是能力飞轮”仍然正确，但应承认当前 deterministic eval baseline 已经不错。

### 2.15 多 Agent 不是当前最高优先级

当前 Alita 没有 AutoGen/CrewAI 意义上的 agent/team abstraction：

- 没有 `PlannerAgent`、`ExecutorAgent`、`VerifierAgent`、`ResearchAgent` 等角色对象。
- 没有 team state。
- 没有 agent-to-agent message bus。
- 没有 termination policy。
- 没有 handoff protocol。

但现在不应优先做复杂多 Agent。原因：

- 单 AgentRuntimeGraph 未完成。
- MCP lifecycle 未打通。
- sandbox 非 OS 隔离。
- schema-aware planner 未完成。
- model-in-loop eval 未建立。

多 Agent 会放大权限、安全、观测和评测压力。应该放到 P4。

## 3. 外部建议逐条判定

| 外部判断 | 当前判定 | 0.32.0 代码核验 |
| --- | --- | --- |
| 项目不是烂项目，但不是成熟 Agent 平台 | 仍正确 | 更准确说：已经是本地 Agent Runtime Workbench，但不是成熟通用自治平台 |
| 主 graph 是一次性 router，不是持续自主 runtime | 正确 | `graph.py` 仍 route 到 answer/plan 后 END |
| 执行器被文档流/研究流绑死 | 部分正确 | fixed-tool 已走 binding/gateway，但 document/research executor 仍特化 |
| ToolExecutor 只有三个 adapter | 已过时 | 仍有三个 adapter，但已有 `ToolRuntimeLoader` 和 function entrypoint |
| ToolCatalogPlanner 是关键词匹配 | 正确 | token overlap + 少量参数名绑定 |
| ReAct 是补丁 | 部分过时 | PlannerChain 已输出 node-level action policy，但不是默认主 loop |
| 状态/恢复机制偏轻 | 部分过时 | checkpoint/resume 已有；rollback/fork/time travel/thread state 仍缺 |
| Memory 没默认进 planning | 已过时 | planning 默认读取 `MemoryStore(project_path).list()` |
| Memory 没默认写入 | 已过时 | run 成功/失败默认写摘要，除非 `autoWrite=false` |
| research-parallel-search 实际顺序执行 | 正确 | 当前代码仍顺序循环 query units |
| MCP 是接入口，不是生态 | 基本正确 | typed provider handoff 已有，真实 lifecycle/default runtime 未打通 |
| 权限默认偏宽 | 大幅过时 | `PermissionGate` 和 `AuthorityContext` 已收紧；但 grant 模型还可强化 |
| Sandbox 不是强隔离 | 正确 | 代码明确标注不是 OS isolation |
| 可观测性只有 JSON 日志 | 部分过时 | runtime events 和 observation metadata 已贯通；trace-first 仍缺 |
| Eval 偏 deterministic harness | 正确 | 63 条 eval 是好的 regression gate，但不是 model-in-loop benchmark |
| 没有多 Agent 抽象 | 正确 | 但不应作为下一阶段 P0 |

## 4. 与主流 Agent 项目的对照

这些项目不应被照搬。Alita 的优势是本地优先、桌面工作台、节点图、artifact 和可审计权限。需要借鉴的是 runtime 原语。

### 4.1 LangGraph / LangSmith

LangGraph 官方 persistence 把 graph state 保存为 checkpoint，并围绕 threads、human-in-the-loop、memory、time travel 和 fault-tolerant execution 建模。Alita 当前也有 checkpoint，但它仍是 graph-run journal 层，没有成为主 Agent graph 的状态内核。

LangSmith 的启发是 trace-first：一次 Agent run 应能看到模型调用、工具调用、决策点、延迟、成本和输出评价。Alita 已有 runtime events，但还缺统一 trace schema 和 UI。

### 4.2 AutoGen

AutoGen AgentChat 把 agents、teams、termination conditions 和 state save/load 当作核心概念。Alita 当前没有 team state，也没有角色化 agent 协作抽象。短期不需要照搬 AutoGen team，但需要学习它的状态边界和可保存运行单元。

### 4.3 CrewAI

CrewAI 区分 Crews、Tasks、Processes 和 Flows。这个分层对 Alita 很有参考价值：Alita 现在更像强 Flow 工作台，而不是多角色 Crew。下一步应先把 Flow runtime 做硬，再引入 roles。

### 4.4 MCP

MCP tools spec 明确包含 tools/list、tools/call、inputSchema、outputSchema 和 human-in-the-loop 安全建议。Alita 的 `McpToolProvider` 已经贴近这个模型，但缺真实 transport client lifecycle、schema cache、credential handling 和 tool list refresh。

### 4.5 OpenHands

OpenHands 当前文档把 Docker sandbox 作为本地推荐隔离方式，同时明确 process sandbox 没有隔离。这个对 Alita 的启发非常直接：如果未来允许 Agent 自动执行模型生成代码，Alita 不能只靠 AST preflight，需要 OS/container/VM 级隔离选项。

## 5. 目标架构

建议 Alita 的目标不是“黑盒全自动 Agent”，而是：

```text
本地优先、可视化、可审计、可恢复、可评估的 Agent Runtime Workbench
```

目标主链路：

```text
User Message
  -> AgentRunState
  -> Router
  -> GoalSpec
  -> ContextBundle + ProjectMemory + ToolCatalog
  -> PlannerChain
  -> PlanValidator
  -> ExecutionGraph
  -> AgentRuntimeGraph
  -> ActionPolicy
  -> AuthorityGrant
  -> UnifiedToolGateway
  -> Provider Runtime / Sandbox
  -> Observation
  -> ResultVerifier / FinalVerifier
  -> Replanner
  -> Journal + Trace + Memory
  -> Eval Feedback
```

必须维持的架构约束：

```text
所有工具调用、MCP 调用、模型 tool call、临时脚本、文件读写、CLI 执行，
都必须经过：

UnifiedToolGateway
  -> AuthorityContext / AuthorityGrant
  -> Provider Runtime
  -> Observation Sanitizer
  -> Verifier
  -> Journal / Trace
```

## 6. 优先级路线图

### P0：把 graph-run 闭环升级成默认 AgentRuntimeGraph

目标：让 Alita 的默认 Agent 入口从 route/plan 输出图，升级为可恢复、可观测、可中断的状态机。

建议任务：

1. 新增 `AgentRuntimeGraph` 或 `AgentRuntimeStateMachine`，显式建模 `route/build_context/plan/validate/act/observe/verify/replan/final`。
2. 把 `run_graph_events()` 中的 checkpoint、authority event、recovery event、resume 逻辑抽成 runtime loop service，供主 Agent graph 复用。
3. `RunMode.checkpoint_id` 真正生效，支持指定 checkpoint resume，而不是只读 latest checkpoint。
4. 实现 checkpoint list、rollback、fork run 最小 API。
5. 前端增加 runtime observability 面板，显示 checkpoint、authority decision、tool observation、recovery action。
6. 更新 README 版本到 `0.32.0`，并同步当前 runtime 能力与限制。

验收标准：

- 用户一次发送任务后，Agent 可以默认进入 `plan -> act -> observe -> verify -> replan/final`。
- 用户可以从指定 checkpoint 恢复、回滚或 fork。
- 前端能审计每次 tool call 的 authority 和 observation。

### P1：工具生态和 MCP 端到端

目标：让 manifest + provider lifecycle 真正决定工具发现、授权、执行、观测。

建议任务：

1. 定义统一 `runtime` 枚举：`python_function`、`python_script`、`cli`、`builtin`、`mcp`。
2. 将 `document.markitdown_convert`、`document.typst_compile`、`document.read_write` 迁移到统一 runtime loader。
3. 修复 `document.read_write` manifest：补充 `operations`，把 entrypoint 改为 `module:function` 或实现 `python_script` runtime。
4. 定义 `ProviderLifecycle`：`start/list_tools/call_tool/health/stop/reload`。
5. 实现 MCP stdio/http client factory。
6. Tauri preferences -> sidecar 传递启用 MCP configs，不能只停留在 Rust 侧 refresh。
7. MCP tools 进入 `ContextBundle.available_tools`，并由 PlannerChain 参与选择。
8. ToolCatalogPlanner 升级为 schema-aware planner：required/optional 参数、输入输出类型、上游依赖、dry-run validation。

验收标准：

- 新增一个内部工具只需 manifest + entrypoint，不需要改 `execution.py`。
- 配置 MCP provider 后，Agent planning 能发现真实 MCP tools。
- 授权后能调用真实 MCP tool，并记录 observation/journal/eval。

### P2：安全与执行隔离

目标：让模型生成代码、CLI 和外部工具调用具备真实边界。

建议任务：

1. UI 和文档统一称当前 sandbox 为 constrained runner。
2. Windows Job Object backend：限制进程树、CPU 时间、内存、超时。
3. 低权限 Windows 用户或 AppContainer backend。
4. 可选 Docker/WSL backend，用于高风险脚本和代码执行。
5. 网络访问改为 broker/API 代理，按 domain grant 放行。
6. Secret 访问改为 broker，工具不继承完整 env。
7. 扩展 security eval：动态路径、目录穿越、symlink、进程树、网络、secret、超大输出、artifact 越界。

验收标准：

- 临时脚本默认不能以用户完整权限运行。
- network/secret/file write 都必须由授权 broker 执行。
- release gate 包含 sandbox escape regression。

### P3：Trace-first 与 model-in-loop eval

目标：让能力增长可衡量、可回放、可比较。

建议任务：

1. 定义统一 trace schema：trace id、span id、parent span id、kind、input hash、redacted output、latency、token、cost。
2. 为 LLM call、tool call、planner decision、authority decision、verifier decision、replan decision 全部建 span。
3. 将 runtime trace 与 eval case 绑定。
4. 新增 model-in-loop eval：planner binding、native tool calls、ReAct recovery、checkpoint resume、citation support、memory usefulness。
5. 新增 cost/time regression report。
6. 生成 release eval report artifact。

验收标准：

- 每个 release 能回答：成功率是否提升、成本是否上升、失败模式是否变化。
- 一个失败 case 可以从 trace 直接回放到同样的 planner/tool/verifier 状态。

### P4：多 Agent Team

目标：在单 Agent runtime 稳定后，引入角色化协作。

建议最小角色：

- `PlannerAgent`
- `ExecutorAgent`
- `VerifierAgent`
- `ResearchAgent`
- `CriticAgent`

不建议当前立即做复杂多 Agent。多 Agent 只应在以下条件满足后启动：

- AgentRuntimeGraph 已稳定。
- MCP lifecycle 已端到端。
- sandbox 有 OS/container 级选项。
- trace/eval 能覆盖 agent-to-agent message。
- 权限 grant 可按 agent role 分配。

## 7. 建议的前 15 个 PR

1. `docs: align 0.32.0 runtime documentation`
   - 修改 `README.md` 当前版本和限制说明。
   - 将 0.32.0 真实能力同步到 docs。
   - 验证：`rg "0.31.0" README.md docs` 不再出现误导性当前版本。

2. `runtime: introduce AgentRuntimeGraph skeleton`
   - 新增 runtime state model。
   - 先只把现有 route/plan/run graph 串起来，不引入新能力。
   - 测试 route -> plan -> execute mock graph -> final。

3. `runtime: extract graph execution loop service`
   - 从 `run_graph_events()` 抽出 checkpoint、event、recovery、resume 公共 service。
   - 保持现有 API 行为不变。

4. `runtime: support checkpoint id resume`
   - `RunMode.checkpoint_id` 生效。
   - 新增 checkpoint list API。
   - 测试指定 checkpoint 恢复。

5. `runtime: add rollback and fork run`
   - 从 checkpoint 生成 forked run。
   - 保留原 run journal。

6. `observability: add trace span schema`
   - 新增 trace/span 数据结构。
   - 先覆盖 tool call、authority decision、checkpoint。

7. `observability: add runtime panel`
   - 前端显示 checkpoint、authority、recovery、tool observation。
   - 不重写整体 UI。

8. `authority: introduce request-level AuthorityGrant`
   - RunGraphRequest 支持 `authority_grants`。
   - grant 包含 permissions、tool ids、read/write roots、domains、budget。

9. `authority: enforce domains and runtime budget`
   - network provider 和 MCP provider 消耗 domain grant。
   - runtime budget 写入 observation。

10. `tools: define runtime enum and provider lifecycle`
    - `python_function`、`python_script`、`cli`、`builtin`、`mcp`。
    - Provider start/health/stop 接口。

11. `tools: migrate document tools off legacy adapters`
    - MarkItDown 和 Typst 走统一 runtime loader。
    - `ToolExecutor.adapters` 只作为 temporary compatibility fallback。

12. `tools: repair document.read_write manifest`
    - 补 `operations`。
    - 改 entrypoint 或实现 python_script runtime。
    - 加 end-to-end fixed-tool test。

13. `mcp: implement real stdio/http client lifecycle`
    - Tauri preferences 传到 sidecar。
    - Python sidecar 建立 client factory。
    - `refresh_mcp_tool_provider_tools` 调真实 `tools/list`。

14. `planner: schema-aware tool planner`
    - required argument binding。
    - input/output type matching。
    - multi-tool DAG dry run。

15. `eval: add model-in-loop benchmark`
    - 小规模 nightly eval。
    - 覆盖 ReAct、tool binding、resume、citation support、memory usefulness。

## 8. 不建议现在做的事

当前不建议优先做：

- 全局无限 ReAct。
- 复杂多 Agent team。
- 工具市场。
- 云端多租户。
- 大规模前端重写。
- 让模型自由生成并执行脚本。
- 直接宣传“安全沙箱”。

原因：

- 主 AgentRuntimeGraph 未完成。
- MCP lifecycle 未端到端。
- sandbox 仍不是 OS isolation。
- ToolCatalogPlanner 仍是启发式。
- model-in-loop eval 未建立。
- trace-first observability 未完成。

## 9. 阶段验收标准

### Runtime

- 主入口支持 `plan/act/observe/verify/replan/final`。
- checkpoint 支持 list/resume/rollback/fork。
- 前端能看到关键 runtime 事件。

### Tool

- 新工具通过 manifest + entrypoint 接入，不修改 executor。
- 内部工具和 MCP 工具有统一 observation。
- Tool planner 能基于 schema 生成多节点 DAG。

### Security

- Sensitive permission 必须显式 grant。
- network/domain/budget 被实际 enforce。
- 临时脚本至少支持 Job Object 或低权限执行。

### Memory

- planning 默认检索相关 memory。
- run 默认写低风险摘要。
- preference memory 需要用户确认。
- 用户能查看、删除、固定 memory。

### Research

- 真正并发 search/read。
- 每个 claim 绑定 evidence span。
- verifier 能判断 unsupported/conflicting claim。

### Eval

- PR gate：deterministic eval。
- Nightly：model-in-loop eval。
- Release：trace/eval/cost report。

## 10. 最终建议

外部分析对 Alita 的架构短板判断是中肯的，但它低估了当前 0.32.0 已经完成的 runtime 增量。Alita 已经不是“会画流程图并执行少数工具”的简单工作台，而是已经拥有一批真正 Agent Runtime 原语：

- `AgentRunState`
- `PlannerChain`
- `ExecutionGraph`
- `UnifiedToolGateway`
- `AuthorityContext`
- `ToolRuntimeLoader`
- `ReActController`
- `RuntimeCheckpoint`
- `RunJournal`
- runtime observability events
- `MemoryStore`
- deterministic eval harness

下一阶段不要横向堆功能。最重要的主线是：

```text
AgentRuntimeGraph
  -> checkpoint rollback/fork
  -> explicit AuthorityGrant
  -> provider runtime + MCP lifecycle
  -> trace-first observability
  -> schema-aware planner
  -> model-in-loop eval
  -> OS-level sandbox
```

这条线打通后，Alita 才会从“本地 Agent Runtime Workbench”升级为“可长期运行、可审计、可恢复、可扩展、可评估的本地 Agent 平台”。

## 11. Goal Mode 实施结果

本轮按 `docs/superpowers/plans/2026-05-30-agent-runtime-v032-implementation-plan.md` 执行，并用 `docs/superpowers/progress/2026-05-30-agent-runtime-v032-progress.md` 记录每阶段 gate。实现重点是把 0.32.0 的 runtime 优化从审计建议推进到一组可测试的小步增量，并作为 `0.33.0` 发布内容，同时避免夸大为完整生产级自治平台。

| Phase | 状态 | 主要结果 | 验证 |
| --- | --- | --- | --- |
| Phase 0 Baseline And Documentation Alignment | 完成 | README 当前版本更新为 `0.32.0`；创建分阶段实施计划和进度追踪文档 | `agent:eval` 63/63；关键 Python runtime 测试 99 passed；frontend typecheck exit 0 |
| Phase 1 Runtime Trace Primitives | 完成 | 新增 `RuntimeSpan`、`trace_id_for_run()`、`runtime.span_recorded` 事件；节点执行会 emit span；tool observation 支持可选 trace/span 字段 | `pytest tests/test_runtime_trace.py tests/test_tool_gateway.py tests/test_execution.py -q` -> 94 passed |
| Phase 2 Checkpoint Control API | 完成 | `RuntimeCheckpoint` 记录稳定 `checkpointId`；`RunJournal.read_checkpoint()` 支持按 id 读取；`resume_checkpoint` 支持指定 `checkpoint_id` | `pytest tests/test_run_journal.py tests/test_execution.py tests/test_agent_run_state.py -q` -> 92 passed |
| Phase 3 AgentRuntimeGraph Skeleton | 完成 | 新增 `AgentRuntimeGraph` 和 `AgentRuntimeGraphState`，为后续默认 runtime state machine 提供薄骨架；任务/研究 graph metadata 写入 `agentRuntime` | `pytest tests/test_agent_runtime_graph.py tests/test_graph.py tests/test_planner_chain.py -q` -> 84 passed |
| Phase 4 Explicit AuthorityGrant | 完成 | `RunGraphRequest` 增加 optional `authority_grants`；runtime authority 合并 tool/permission/root/domain/budget grant；network domain 可授权；observation 记录 `runtimeBudgetMs` | `pytest tests/test_authority.py tests/test_tool_gateway.py tests/test_execution_gateway_integration.py tests/test_eval_harness.py -q` -> 46 passed |
| Phase 5 Provider Runtime Normalization | 完成 | `ToolRuntimeLoader` 增加 runtime enum；`python_script`、`cli`、`mcp` 在 internal executor 中返回明确 `unsupported_runtime`；`document.read_write` manifest 补 runtime 和 operations | `pytest tests/test_tool_execution.py tests/test_tool_registry.py tests/test_tool_gateway.py -q` -> 32 passed |
| Phase 6 MCP Lifecycle Handoff | 完成 | `McpToolProvider` 对带 lifecycle 的 client lazy start，一次启动后复用；提供 `health()` 和 `stop()` seam | `pytest tests/test_mcp_tool_provider.py tests/test_context_manager.py tests/test_planner_chain.py tests/test_graph.py -q` -> 90 passed |
| Phase 7 Schema-Aware Tool Planner | 完成 | ToolCatalogPlanner 支持多 operation 选择、附件路径绑定、artifact 输出路径绑定和未绑定 required argument diagnostics | `pytest tests/test_tool_catalog_planner.py tests/test_planner_chain.py tests/test_eval_harness.py -q` -> 37 passed |
| Phase 8 Sandbox Posture Upgrade | 完成 | `SandboxResult` 暴露 backend、OS isolation、process tree limit 姿态字段；新增 Windows Job Object 可用性探针，但不声称已强制隔离 | `pytest tests/test_sandbox.py tests/test_eval_harness.py -q` -> 27 passed |
| Phase 9 Model-In-Loop Eval Harness Skeleton | 完成 | Eval harness 增加 `model_loop` category；默认无模型时跳过并计为通过；新增 `model_loop_cases.jsonl` | `pytest tests/test_eval_harness.py -q` -> 11 passed；`agent:eval` -> 64/64 |

最终 full gate：

- `git diff --check` exited `0`；输出仅包含 `README.md` 的既有 CRLF warning。
- `npm run agent:eval` -> `64/64 passed, 0 failed`。
- `Push-Location python; python -m pytest -q; Pop-Location` -> `753 passed`。
- `npm run frontend:typecheck` -> exit `0`。
- `npm run frontend:test` -> `32` test files / `210` tests passed。
- `cargo test --manifest-path src-tauri/Cargo.toml` -> exit `0`，Rust/Tauri 测试通过；worktree 中补齐了被 `.gitignore` 排除的本地 Tauri sidecar/resource 占位路径后才可执行构建脚本。

本轮已经实际增强的方向：

- runtime observation 从 checkpoint/authority/recovery 扩展到 span primitive。
- checkpoint resume 从 latest-only 扩展到指定 checkpoint id。
- AgentRuntimeGraph 有了独立骨架，后续可以逐步替代一次性 router。
- AuthorityGrant 进入 RunGraphRequest，但保持 backward compatibility。
- Tool runtime 开始按 runtime 类型显式区分，而不是所有 unsupported 都混成 tool 缺失。
- MCP provider 具备 lifecycle seam，但仍没有真实生产级 stdio/http supervisor。
- ToolCatalogPlanner 从 token-only 前进到 schema-aware required argument binding 的第一步。
- Sandbox posture 更诚实，明确当前不是 OS-level isolation。
- Eval harness 有了 model-in-loop 入口，但默认仍是 deterministic gate。

仍需明确的残余风险：

- `AgentRuntimeGraph` 仍是 skeleton，没有完全替换 `graph.py` 的 route -> answer/plan -> END 主入口。
- MCP lifecycle 仍是 provider/client seam，不包含真实凭据 broker、长进程 supervisor、stdio/http production client 管理。
- `python_script` 和 `cli` runtime 当前被明确拒绝，尚未成为可执行 provider。
- Sandbox 仍不是 Windows Job Object/AppContainer/Docker/WSL 级隔离；本轮只增加姿态字段和可用性探针。
- `model_loop` eval 默认跳过；真实模型质量基准、token/cost tracing 和 nightly runner 仍需后续建设。
- 多 Agent team 仍未启动，合理优先级仍在单 Agent runtime 稳定之后。

## 12. 参考资料

- LangGraph Persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- LangSmith Observability: https://docs.langchain.com/oss/python/langchain/observability
- AutoGen Managing State: https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/tutorial/state.html
- AutoGen Teams: https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/teams.html
- CrewAI Crews: https://docs.crewai.com/en/concepts/crews
- CrewAI Flows: https://docs.crewai.com/en/concepts/flows
- CrewAI Processes: https://docs.crewai.com/en/concepts/processes
- MCP Tools Specification: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- OpenHands Sandbox Overview: https://docs.openhands.dev/openhands/usage/runtimes/overview
- OpenHands Docker Sandbox: https://docs.openhands.dev/openhands/usage/runtimes/docker
