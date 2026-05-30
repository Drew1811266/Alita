# Alita Agent 开发优化文档（0.30.0 代码核验版）

生成日期：2026-05-30
核验对象：当前仓库 `main` 分支，版本 `0.30.0`

> 2026-05-30 closed-loop 实施补充：本文第 1-11 节记录的是 `0.30.0` baseline 代码核验和优化建议。本分支 `codex/agent-runtime-closed-loop` 已按阶段计划实现其中一批 P0/P1/P2 能力，并作为 `0.31.0` 发布内容合入主线；实施结果和残余风险见第 12 节。

## 1. 核验结论

这次外部分析对 Alita 0.30.0 的总体判断基本准确。当前项目已经不是 UI 原型，也不只是一个有节点图外壳的工作台；它已经具备 Agent Runtime 的主要零件：

- LangGraph 主路由。
- `AgentRunState` 运行态。
- `PlannerChain`、`ExecutionGraph` 和节点执行器。
- `UnifiedToolGateway`、内部工具 provider 和 MCP provider 协议层。
- action-time `AuthorityContext`。
- ReAct 控制器和 OpenAI-compatible native tool call 适配。
- research evidence、memory store、eval harness。
- 前端 workbench/controller 拆分。

但这些零件还没有形成成熟 Agent 平台需要的默认闭环。Alita 现在更准确的定位是：

```text
本地优先的 Agent 工作台 + 正在成型的 runtime core
```

而不是：

```text
可恢复、可审计、可扩展、可持续自治的 Agent 平台
```

最大的架构差距仍然是主系统没有把以下循环变成一等路径：

```text
route -> plan -> act -> observe -> verify -> replan -> act -> final
```

当前更接近：

```text
route -> answer / create graph -> END
run graph -> sequential execute nodes -> final / fail
```

所以后续优化重点不应继续堆 UI 或随意增加工具，而应集中打穿一条主线：

```text
ExecutionGraph-driven execution
  + ReAct observe/replan loop
  + strong AuthorityContext
  + provider-based tool runtime
  + eval quality gate
```

## 2. 当前真实代码状态

### 2.1 主 Agent Loop

代码依据：

- `python/agent_service/graph.py`
- `python/agent_service/execution.py`

`build_graph()` 仍是一次性路由图。`classify_intent` 根据意图转到 `answer_with_model`、`answer_with_web`、`choose_research_mode`、`plan_research_graph`、`request_required_inputs` 或 `plan_task_graph`，然后全部指向 `END`。

这验证了外部分析中最核心的判断：主 Agent graph 仍更像任务路由器，不是持续自治的 agent loop。

`run_graph_events()` 的执行层已经比主路由强很多：它会 topological sort、写 run journal、检查权限、执行节点、校验节点输出、触发 `FailureReplanner` 生成 patch suggestion。但它仍是固定 DAG 的顺序执行器。失败时通常是记录失败并建议 patch，而不是自动进入可控 replan/continue 循环。

结论：外部建议准确。下一步必须新增真正的 `AgentRuntimeGraph` 或等价执行内核，把执行、观察、验证、修补和继续运行纳入一个可恢复状态机。

### 2.2 ExecutionGraph

代码依据：

- `python/agent_service/execution_graph.py`
- `python/agent_service/schemas.py`
- `python/agent_service/execution.py`

0.30.0 的 `ExecutionGraph` 已经明显比上一阶段更完整。它包含：

- `ExecutionArgumentTemplate`
- `ExecutionInputMapping`
- `ExpectedArtifact`
- `ExecutionPermissionScope`
- `ExecutionToolBinding`
- `ExecutionModelBinding`

`GraphNode` 也支持 `toolBinding`，能够表达 `toolId`、`providerId`、`operation`、`argumentsTemplate`、`inputMappings`、`outputSchema`、`expectedArtifacts` 和 `permissionScope`。

但泛化仍没有完全闭环：

- `_DEFAULT_OPERATION_BY_TOOL` 只覆盖三个文档工具。
- `_DOCUMENT_ARGUMENT_TEMPLATES`、`_DOCUMENT_INPUT_MAPPINGS`、`_DOCUMENT_EXPECTED_ARTIFACTS` 全部围绕文档流。
- `PlannedTaskExecutor` 虽然可以按 binding 渲染 fixed tool 调用，但仍持有 `DocumentFlowExecutor`，并复用其 artifact dir 和 allowed roots。
- `execution.py` 仍保留 `DOCUMENT_FLOW_NODE_IDS`、`DOCUMENT_FLOW_RUNTIME_TOOL_BINDINGS` 和 document-flow 特判路径。

结论：外部建议准确但需要细化。ExecutionGraph 的 schema 层已经接近通用 runtime binding，但执行层仍受文档流历史包袱牵制。

### 2.3 工具生态

代码依据：

- `python/agent_service/tool_execution.py`
- `python/agent_service/tool_gateway.py`
- `python/agent_service/tool_providers/internal.py`
- `tool-packages/*/manifest.json`

当前工具 manifest 已经很像插件协议，但 `ToolExecutor` 仍然是 adapter dict：

- `document.receive_attachment / receive_attachment`
- `document.markitdown_convert / convert_local_file`
- `document.typst_compile / compile_report_pdf`

仓库里还有 `document.read_write` 和 `test.echo_values` manifest，但默认 `ToolExecutor` 没有对应 adapter。工具能被 registry/catalog 看见，不等于能被 runtime 执行。

`ToolCatalogPlanner` 已经能基于工具目录生成简单 fixed-tool graph，但选工具逻辑仍是 token overlap，参数绑定只支持 `message/query/source_text/text/input/metadata_value` 等少量字段。面对复杂工具 schema、跨节点数据依赖和多工具组合时，它会很快触顶。

结论：外部建议准确。工具系统的下一阶段应从 adapter dict 迁移到 provider runtime/entrypoint loader，让 manifest 真正决定可执行入口。

### 2.4 AuthorityContext 与权限

代码依据：

- `python/agent_service/authority.py`
- `python/agent_service/tool_gateway.py`
- `python/agent_service/permission_gate.py`
- `python/agent_service/execution.py`

0.30.0 已经有 action-time authorization。`UnifiedToolGateway.call_tool()` 会在 schema 校验之后构建或读取 `AuthorityContext`，再调用 `authorize_tool_invocation()`。授权逻辑会检查：

- tool id 是否在 approved tool ids 中。
- sensitive permissions 是否被批准。
- `input_path`、`output_path`、`source_output_path`、`pdf_output_path`、`paths` 等参数是否落在 read/write roots 内。

这说明方向正确。

但仍有几个明显漏洞：

- `UnifiedToolGateway` 没有显式 authority context 时，会走 `_legacy_authority_context()`。
- `_legacy_authority_context()` 会把 invocation requested permissions 和 tool permissions 都放进 `approved_permissions`。
- `AuthorityContext.from_invocation()` 会把 `allowed_roots` 同时作为 `read_roots` 和 `write_roots`。
- `PermissionGate.DEFAULT_ALLOWED_PERMISSIONS` 仍默认允许 `run_local_cli`、`run_python_plugin`、`write_project_outputs` 等高风险能力。
- `SENSITIVE_PERMISSIONS` 只覆盖 `network`、`run_local_cli`、`run_python_plugin`，没有把外部读写、项目写入、MCP 外部调用等全部纳入强授权。

结论：外部建议准确。当前权限模型是正确方向上的过渡状态，不是强权限边界。

### 2.5 Sandbox

代码依据：

- `python/agent_service/sandbox.py`
- `python/agent_service/execution.py`
- `python/evals/security_cases.jsonl`

当前 sandbox 已经增加了很多实用限制：

- 脚本大小限制。
- stdout/stderr 大小限制。
- artifact 数量和大小限制。
- 禁止部分网络、动态 import、secret env、process launch API。
- 对字面量路径的 `open()`、`Path.read_text()`、`Path.read_bytes()` 做路径检查。
- 使用最小环境变量集。
- 要求 stdout 为 JSON。

但它本质仍是：

```text
AST preflight + 当前 Python 解释器 subprocess runner
```

不是安全沙箱。它没有 OS 级隔离、文件系统虚拟化、syscall 限制、低权限身份、进程树隔离、CPU/内存硬限制。动态构造路径、未覆盖标准库 API、解释器能力面和 Windows 进程权限仍然是风险。

结论：外部建议准确。文档和 UI 都应明确把它称为受控执行器，而不是可信沙箱。模型生成脚本自动执行前，必须升级到 Windows Job Object/AppContainer、低权限用户、Docker/WSL 或等价隔离层。

### 2.6 ReAct 与 Native Tool Calls

代码依据：

- `python/agent_service/react_controller.py`
- `python/agent_service/model_client.py`
- `python/agent_service/model_tool_adapter.py`
- `python/agent_service/execution.py`

当前 ReAct 已经支持两条路径：

- `use_native_tool_calls=True` 且 model client 支持 `chat_with_tools()` 时，走 OpenAI-compatible tool schema 和 `tool_calls`。
- 否则走 JSON action fallback。

`OpenAICompatibleModelClient.chat_with_tools()` 会把 `tools` 和 `tool_choice` 写入 payload，并解析 `message.tool_calls`。这验证了外部分析中“native tool call 方向已经接上”的正面评价。

但 ReAct 仍不是默认 Agent 行为：

- `_react_policy_from_graph_metadata()` 只从 `graph.metadata["react"]` 读取配置。
- `enabled` 必须显式为 `true`。
- PlannerChain 不会自动为需要工具探索的 model node 生成 ReAct policy。
- 允许哪些工具、哪些权限、多少步预算，仍需要上游手工/测试图 metadata 配置。

结论：外部建议准确。ReAct 现在是可用组件，不是默认行动机制。

### 2.7 Memory

代码依据：

- `python/agent_service/memory_store.py`
- `python/agent_service/context_manager.py`
- `python/agent_service/context_policy.py`
- `python/agent_service/graph.py`
- `python/agent_service/execution.py`

MemoryStore 已经能写 `*-memory/memory.jsonl`，支持：

- `preference`
- `graph_summary`
- `artifact_summary`
- `tool_outcome`

`ContextBundle` 也有 `memory_summaries`，`context_policy` 能按 chat/planning/execution/research 模式筛选 memory。

但默认闭环没打通：

- `graph.py` 调用 `build_context_bundle()` 时没有读取 `MemoryStore`。
- execution 完成时只有 `request.graph.metadata["memory"]["autoWrite"] is True` 才自动写 memory。
- 当前检索是 JSONL + kind/tag/recent 筛选，没有 embedding、关键词 BM25、压缩、冲突消解、过期策略或 UI 管理。
- 失败经验、工具 outcome 和 verifier diagnostics 还没有稳定反馈给 planner。

结论：外部建议准确。Memory 是机制存在，但不是默认质量飞轮。

### 2.8 Eval Harness

代码依据：

- `python/agent_service/eval_harness.py`
- `python/evals/*.jsonl`
- `package.json`

当前 eval 已经不是只有 4 条 smoke case。仓库中有 56 条 deterministic eval：

- router：10
- planner：11
- tool：10
- research：10
- security：15

`package.json` 提供 `npm run agent:eval`，会运行全集并输出 summary。

但外部分析的核心批评仍成立：这些 eval 主要是 deterministic regression harness，不是 Agent 质量 benchmark。它还不能衡量：

- 模型路由准确率。
- ReAct/native tool call 成功率。
- plan correctness 和参数绑定质量。
- artifact correctness。
- claim-level citation support。
- 权限越权拦截率在真实模型行为下的表现。
- 自动恢复成功率。
- token、耗时、成本。

结论：外部建议基本准确，但应修正为：0.30.0 已经有不错的 deterministic eval baseline，只是还没成为能力增长和模型行为质量评估体系。

### 2.9 Research Flow

代码依据：

- `python/agent_service/execution.py`
- `python/agent_service/research_evidence.py`
- `python/agent_service/web_research.py`

当前研究流已经有 evidence set：

- accepted/rejected/duplicate/failed reads。
- source id。
- content excerpt。
- content hash。
- citation id 检查。
- `claim_level_citation_diagnostics()`。

但合成仍然是 `_synthesize_research_markdown()` 的确定性模板。它把 source title、snippet、excerpt 拼成报告，而不是先生成结构化 claim，再验证每条 claim 是否被证据 span 支持。

`research_claims_from_markdown()` 也只是从 Markdown 中解析引用存在性。它能发现某些无引用段落，但不能证明 `[S1]` 的 excerpt 真能支撑该 claim。

结论：外部建议准确。研究系统已经有 claim-level 方向，但还没有真正的 claim/evidence graph。

### 2.10 MCP

代码依据：

- `python/agent_service/tool_providers/mcp.py`
- `python/agent_service/tool_gateway.py`
- `python/agent_service/mcp_server.py`
- `src-tauri/src/preferences.rs`
- `src-tauri/src/commands.rs`

MCP 在协议层存在：

- `ToolSource = internal | mcp`
- `McpToolProvider`
- 前端/首选项有 MCP provider config。
- Alita 自身也有 MCP server wrapper。

但默认 runtime 没有真正加载用户配置的 MCP provider：

- `default_unified_tool_gateway()` 只注册 `InternalToolProvider`。
- Tauri 的 `refresh_mcp_tool_provider_tools_for_preferences()` 当前对启用 provider 返回 `Ok(Vec::new())`。
- Python sidecar 默认执行路径没有从 preferences 构建 MCP clients/providers。

结论：外部建议准确。MCP 是架构预留和部分 UI/config，而不是默认工具生态。

### 2.11 前端工作台

代码依据：

- `src/app/App.tsx`
- `src/features/task/*`
- `src/features/chat/*`
- `src/features/permissions/*`
- `src/features/preferences/*`

前端拆分已经开始，`App.tsx` 当前约 1330 行。它比早期更好，但仍是总装容器，聚合了项目、聊天、附件、图运行、权限、首选项、artifact、语音等大量状态和动作。

结论：外部建议基本准确。前端不是当前最高优先级，但如果后续引入多 run、checkpoint、memory UI 和 MCP provider 管理，`App.tsx` 继续承载所有协调会变成明显瓶颈。

## 3. 外部建议逐条判定

| 外部判断/建议 | 判定 | 代码核验结论 | 优先级 |
| --- | --- | --- | --- |
| 0.30.0 已有 runtime core 形状 | 正确 | ExecutionGraph、AuthorityContext、ReAct、eval、memory 都已出现 | P0 |
| 主 Agent loop 不是自治闭环 | 正确 | `graph.py` 一次路由到 END；`execution.py` 顺序执行 DAG | P0 |
| ExecutionGraph 变实了 | 正确 | binding schema 明显增强 | P0 |
| ExecutionGraph 仍受文档流硬编码牵制 | 正确 | 默认模板、mapping、expected artifacts 仍是文档工具中心 | P0 |
| 工具生态卡在内部 adapter | 正确 | ToolExecutor 默认只有三个 adapter | P0 |
| ToolCatalogPlanner 仍是启发式匹配 | 正确 | token overlap + 少量参数名绑定 | P1 |
| AuthorityContext 方向正确但 fallback 偏宽 | 正确 | legacy context 自动批准 tool.permissions | P0 |
| PermissionGate 默认过宽 | 正确 | 默认允许 CLI、Python plugin、项目输出写入 | P0 |
| Sandbox 不是强沙箱 | 正确 | subprocess + AST preflight，不是 OS 隔离 | P0 |
| ReAct/native tool calls 已接上但不是默认行为 | 正确 | metadata 开关启用，planner 不自动生成 policy | P1 |
| MemoryStore 已有但未进入主上下文闭环 | 正确 | planning 默认没有读取 MemoryStore；auto write opt-in | P1 |
| Eval harness 是进步但非质量 benchmark | 基本正确 | 已有 56 条 deterministic eval，但缺 model-in-loop benchmark | P1 |
| Research 有 evidence 方向但合成偏模板 | 正确 | deterministic markdown synthesis，不是 claim/evidence pipeline | P1 |
| MCP 不是主路径工具生态 | 正确 | provider/config 存在，默认 gateway 只注册 internal | P1 |
| 应引入 Agent Team | 方向正确但不宜过早 | 单 Agent runtime 还没强闭环，多 Agent 应放 P3 | P3 |

## 4. 与成熟 Agent 项目的差距

这些外部项目不应被照搬。Alita 的优势是本地优先、桌面工作台、可视节点图、artifact 和用户可审计流程。可借鉴的是 runtime 能力。

### LangGraph

LangGraph 的关键启发是 checkpointed、stateful、可中断和可恢复的长运行 agent runtime。Alita 使用了 LangGraph，但当前主要用作入口路由图，没有把 persistence/checkpoint/human-in-the-loop/time travel 变成核心执行路径。

### AutoGen

AutoGen 的启发是 agent runtime、agent/tool 抽象、多 agent message passing 和 extensions 分层。Alita 当前已经有 ReAct 和 tool schema adapter，但还缺稳定的默认 tool-calling loop 和 observation/replan 机制。

### CrewAI

CrewAI 的启发是区分自主协作的 Crews 和确定性流程控制的 Flows。Alita 现在更接近 Flow/Workbench。现阶段应先把 Flow 内的 execution、permission、memory 和 eval 做强，再考虑角色化 Agent Team。

### OpenHands

OpenHands 的启发是把 agentic coding workflow、workspace、工具执行和产品化入口结合。Alita 的最大短板正是可信执行环境和权限边界，尤其是临时脚本、CLI 和文件系统访问。

## 5. 目标架构

Alita 的目标不应是不可见的全自动黑盒 Agent，而应是：

```text
可视节点工作台 + 可恢复/可审计/可评估的本地 Agent Runtime
```

建议目标 pipeline：

```text
User Message
  -> AgentRunState
  -> Router
  -> GoalSpec
  -> ContextBundle + ProjectMemory
  -> PlannerChain
  -> PlanValidator
  -> ExecutionGraph
  -> Runtime Loop
  -> Tool/Model Action
  -> AuthorityContext
  -> Provider Runtime / Sandbox
  -> Observation
  -> Verifier
  -> Replanner
  -> Journal + Memory + Eval Trace
```

核心原则：

```text
任何工具调用、MCP 调用、模型 tool call、临时脚本、文件读写、CLI 执行，都不能绕过：

UnifiedToolGateway
  -> AuthorityContext
  -> provider runtime
  -> observation sanitizer
  -> verifier
  -> journal
```

## 6. 优先级路线图

### P0：打穿 Runtime Core

目标：把已有零件收束成一条可信、可恢复、可审计的单 Agent 执行主线。

建议任务：

1. 新增 `AgentRuntimeGraph` 或等价状态机，表达 `plan -> act -> observe -> verify -> replan/continue -> final`。
2. 让 `run_graph_events()` 从顺序 DAG executor 升级为可 checkpoint 的 runtime loop。
3. 移除 `_legacy_authority_context()` 的自动批准逻辑。
4. 将 `PermissionGate` 默认改成 deny by default。
5. 将 `read_roots` 与 `write_roots` 分离，不再从 `allowed_roots` 同步赋值。
6. 所有 fixed tool 只按 `ExecutionToolBinding` 执行，文档流不再被节点 id 特判。
7. `ToolExecutor` 改为 provider runtime，根据 manifest `entrypoint/runtime/source_type` 加载执行器。
8. security eval 增加真实越权场景：动态路径、项目写入、MCP 外部调用、CLI、网络域名。

验收标准：

- `execution.py` 中不再需要按文档节点 id 决定工具运行方式。
- 默认权限下，CLI、Python plugin、网络、项目写入、外部 MCP 调用都不能自动通过。
- 每个 tool invocation 都有 authority decision、argument hash、observation summary 和 journal record。

### P1：让 Planner/ReAct/Memory 形成闭环

目标：让复杂任务能根据观察结果继续行动，而不是只生成图或失败建议。

建议任务：

1. PlannerChain 为需要工具探索的 model node 自动生成 ReAct policy。
2. ReAct policy 由 planner 根据工具候选、权限范围、step budget 和风险等级生成。
3. ToolCatalogPlanner 从 token overlap 升级到 schema-aware planner。
4. MemoryStore 在 planning 前默认读取项目 memory。
5. run 成功和失败都写 memory，尤其是 tool outcome、failure pattern、verifier diagnostics。
6. FailureReplanner 的 patch suggestion 进入受控继续执行流程，低风险场景允许自动重试。
7. Eval 新增 model-in-loop 小集：tool call、planner binding、recovery 和 citation support。

验收标准：

- 一次工具调用失败后，系统能在低风险条件下自动修补参数或重试，而不是直接结束。
- planning context 默认能看到相关项目记忆。
- ReAct 不再只靠手工 graph metadata 启用。

### P2：形成长期工作台能力

目标：支持可恢复项目级长期任务，而不是一次性 run。

建议任务：

1. run checkpoint/resume/rollback。
2. 后台多 run 队列。
3. Memory 管理 UI：查看、删除、固定、来源追踪。
4. MCP provider 从 preferences 加载到 Python sidecar 默认 gateway。
5. Research claim/evidence graph 可视化和人工校正。
6. 前端继续拆分 App 容器，为多 run 和 memory/checkpoint UI 做准备。

验收标准：

- 用户关闭/重开项目后，可以恢复上次 agent run 的中间状态。
- MCP provider 配置后能进入 planner 可用工具目录。
- 用户能审计 memory 为什么进入上下文。

### P3：再做 Agent Team

目标：在单 Agent runtime 稳定后，引入角色化协作。

建议最小角色：

- `PlannerAgent`
- `ExecutorAgent`
- `VerifierAgent`
- `ResearchAgent`
- `CriticAgent`

不建议现在优先做多 Agent，因为当前单 Agent 的权限、沙箱、checkpoint、eval 仍不足以承受更高自治度。

## 7. 关键设计建议

### 7.1 AgentRuntimeGraph

新增一个 runtime graph，而不是继续让 `graph.py` 只做入口路由。

建议节点：

```text
route
  -> build_context
  -> plan
  -> validate_plan
  -> execute_next_action
  -> observe
  -> verify
  -> replan_or_continue
  -> final
```

状态必须包含：

- current plan。
- current execution graph。
- pending action。
- observations。
- verifier diagnostics。
- authority grants。
- retry budget。
- checkpoint id。

### 7.2 ExecutionGraph V3

下一版 ExecutionGraph 应完全由 binding 驱动。

需要强化：

- operation 必须显式。
- arguments template 必须能表达上游输出、附件、artifact dir、graph metadata。
- input mapping 必须支持 required/optional、类型转换、数组聚合。
- expected artifacts 必须进入 verifier。
- permission scope 必须转换为 AuthorityContext。

验收方式：

- 新增一个真实 internal tool，只写 manifest 和 entrypoint，不改 `execution.py`，planner 能生成图，runtime 能执行。

### 7.3 Provider Runtime

用 provider runtime 替换 adapter dict。

建议支持三类内部 entrypoint：

- Python function entrypoint。
- CLI entrypoint。
- Built-in virtual tool。

再统一外部 provider：

- MCP stdio。
- MCP HTTP。
- future browser/computer/file provider。

每个 provider 输出统一 observation：

```json
{
  "toolId": "...",
  "ok": true,
  "values": {},
  "artifacts": [],
  "errorCode": null,
  "safeSummary": "...",
  "authorityCode": "allowed"
}
```

### 7.4 Authority V2

将权限分三层：

1. 系统默认能力：极小，默认只允许无副作用能力。
2. 用户本次授权：具体 tool、permission、路径、域名、预算。
3. 工具调用 scope：由实际 invocation 参数推导。

禁止默认自动批准：

- `run_python_plugin`
- `run_local_cli`
- `network`
- `write_project_outputs`
- `external_read`
- `external_write`
- `call_external_mcp_tool`

### 7.5 Sandbox V2

短期：

- 保留 AST preflight。
- 禁止 inherited env。
- 限制 stdout/stderr/artifact/script。
- 扩大文件 API 拦截范围。
- 强制所有 artifact 只能写入 artifact dir。

中期：

- Windows Job Object 限制进程树、CPU 时间、内存。
- 低权限 Windows 用户或 AppContainer。
- 可选 Docker/WSL backend。

长期：

- 所有模型生成脚本默认运行在隔离 workspace。
- 网络、文件系统、secret 通过代理 API 授权访问。

### 7.6 Eval V2

保留 deterministic eval，但新增能力 benchmark。

建议新增指标：

- route accuracy。
- executable plan rate。
- schema binding pass rate。
- tool call success rate。
- authority denial precision。
- sandbox escape blocked rate。
- recovery success rate。
- citation support rate。
- memory usefulness rate。
- average runtime/token cost。

CI 策略：

- PR：跑 deterministic 全集 + 小型 model-in-loop mock eval。
- nightly：跑真实模型 eval。
- release：跑完整安全和研究质量 eval。

## 8. 建议的前 10 个 PR

1. `refactor: introduce agent runtime loop`
   - 新增 runtime state machine。
   - 将 verify/replan/continue 明确纳入主流程。

2. `security: require explicit authority context`
   - 移除 legacy auto approval。
   - read/write roots 分离。

3. `security: tighten default permissions`
   - PermissionGate deny by default。
   - 高风险权限全部显式授权。

4. `refactor: execute document flow through bindings`
   - 移除 document node id 特判。
   - 文档流也作为普通 ExecutionGraph 执行。

5. `feat: add provider runtime loader`
   - 支持 Python function、CLI、virtual tool entrypoint。
   - manifest 无 adapter 不再天然不可执行。

6. `feat: planner emits react policy`
   - PlannerChain 根据任务和工具候选生成 ReAct policy。
   - 不再只靠手工 metadata 开启。

7. `feat: memory participates in planning`
   - graph planning 前读取 MemoryStore。
   - 成功/失败 run 都写 tool outcome。

8. `feat: checkpoint graph runs`
   - 每个节点前后保存可恢复状态。
   - 支持 resume/from checkpoint。

9. `feat: load MCP providers into gateway`
   - Python sidecar 从 preferences 接收 MCP provider config。
   - planner 可发现启用的 MCP 工具。

10. `test: add agent quality benchmark`
    - 新增 model-in-loop eval 分类。
    - 加入 recovery、ReAct、citation support 指标。

## 9. 不建议现在做的事

暂时不建议优先做：

- 全局默认无限 ReAct。
- 多 Agent team。
- 工具市场。
- 云端分布式执行。
- 大规模 UI 重写。
- 让模型自由生成并执行脚本。

原因：

- 权限边界仍偏宽。
- sandbox 不是强隔离。
- 工具执行仍受 adapter 限制。
- eval 还不能充分度量模型自治行为。
- 主 runtime loop 还没有 checkpoint/replan 闭环。

## 10. 阶段验收标准

### Runtime

- 主路径支持 act/observe/verify/replan。
- run 可以 checkpoint/resume。
- 失败恢复有 audit trail。

### 工具

- 新工具只需 manifest + entrypoint 即可被 runtime 调用。
- MCP provider 能进入默认工具目录。
- 所有工具调用都有统一 observation。

### 安全

- 默认 deny by default。
- read/write/network/CLI/script/MCP 都需要显式 scope。
- sandbox escape eval 覆盖动态路径、进程、网络、secret、超大输出和 artifact 越界。

### Memory

- planning 默认加载相关项目记忆。
- run 成功和失败都会写入可追踪 memory。
- 用户能查看和删除 memory。

### Research

- 报告先生成 structured claims。
- 每个 claim 绑定 evidence source/span/support level。
- verifier 能指出 unsupported claim 和 conflicting evidence。

### Eval

- deterministic eval 是 PR gate。
- model-in-loop eval 是 nightly gate。
- 每个 runtime 能力都有明确指标。

## 11. 最终建议

Alita 0.30.0 已经进入“runtime core 成型”的阶段。下一阶段不要再横向堆功能，应该纵向打穿一条可信 Agent 主线：

```text
ExecutionGraph 通用执行
  -> UnifiedToolGateway 唯一路径
  -> 强 AuthorityContext
  -> ReAct observe/replan
  -> checkpointed run
  -> Memory/Eval 反馈闭环
```

这条线打通之后，Alita 才会从“组件齐全的本地 Agent 工作台”跃迁为“可长期使用、可审计、可恢复、可扩展的本地 Agent Runtime”。

## 12. Closed-loop 实施结果（本分支）

本轮实施以 `docs/superpowers/plans/2026-05-30-agent-runtime-closed-loop-plan.md` 为准，按 Phase 0-9 分阶段执行，每个阶段都先补测试，再跑阶段 gate。当前分支已经完成以下能力：

| 阶段 | 实施结果 | 代码落点 |
| --- | --- | --- |
| Authority V2 | 移除 legacy 自动批准，read/write roots 分离，高风险权限默认不再放行，安全 eval 增补越权场景 | `python/agent_service/authority.py`, `python/agent_service/tool_gateway.py`, `python/agent_service/permission_gate.py`, `python/evals/security_cases.jsonl` |
| Provider Runtime Loader | 新增 `ToolRuntimeLoader`，支持 manifest `module:function` entrypoint，并将 `test.echo_values` 改为真实入口执行 | `python/agent_service/tool_runtime.py`, `python/agent_service/tool_execution.py`, `python/tools/test_echo_tool.py`, `tool-packages/test_echo/manifest.json` |
| Binding-Driven Document Flow | 文档 fixed-tool 节点通过 `ExecutionToolBinding` 执行，减少 document node id 特判和 runtime binding 表依赖 | `python/agent_service/execution.py`, `python/tests/test_execution.py` |
| Runtime Checkpoints And Continue | 写入 `before_node`、`after_node`、`retrying`、`failed` checkpoint，低风险 `retry_node` 建议允许一次自动继续并写 audit | `python/agent_service/runtime_loop.py`, `python/agent_service/run_journal.py`, `python/agent_service/execution.py` |
| Planner ReAct And Memory Defaults | PlannerChain 为可探索工具生成受限 ReAct metadata；planning 默认读取项目 memory；工具成功/失败写 `tool_outcome` memory | `python/agent_service/planner_chain.py`, `python/agent_service/graph.py`, `python/agent_service/execution.py` |
| MCP Provider Activation | 默认 gateway 可接收启用的 MCP provider config 和 client factory；Tauri 首选项刷新能返回 provider-scoped tool summary | `python/agent_service/tool_gateway.py`, `python/agent_service/tool_providers/mcp.py`, `src-tauri/src/commands.rs` |
| Claim Evidence Graph | `ResearchClaim` 和 `EvidenceRef` 记录 excerpt/support 状态，研究合成输出结构化 claims，eval 增加 claim 指标 | `python/agent_service/research_evidence.py`, `python/agent_service/execution.py`, `python/agent_service/eval_harness.py` |
| Frontend Runtime Observability | 前端事件类型和 controller 可保存 checkpoint、authority decision、recovery action 观测状态 | `src/shared/events.ts`, `src/shared/types.ts`, `src/features/task/*`, `src/features/permissions/*` |

这轮实施把原建议中的几个“架构预留”推进到了可测试实现：权限从宽 fallback 变成显式授权；工具 manifest 开始决定运行入口；运行日志具备 checkpoint；低风险失败有受控继续；planner、memory、ReAct 和 research claim/evidence 开始形成闭环。

仍需明确的残余风险：

- 主 `graph.py` 仍是入口路由图，不是完整 `AgentRuntimeGraph` 状态机；act/observe/verify/replan 主要落在 graph run 执行层。
- checkpoint 已持久化，但用户级 resume、rollback、time travel 和后台多 run 队列还没有完成。
- MCP provider 已有 gateway/config handoff 能力，但 preferences 到 Python sidecar 默认运行路径的连接生命周期、凭据注入和真实 stdio/http client 管理仍需继续做端到端闭环。
- 前端已经能接收和保存 runtime observability 状态，但完整 UI 面板、筛选、持久化查看和后端事件覆盖还需要后续阶段补齐。
- ToolCatalogPlanner 仍是启发式工具选择，复杂 schema-aware planning 还没有完成。
- 临时脚本仍不是 OS 级强沙箱；Windows Job Object、AppContainer、低权限用户或 Docker/WSL 隔离仍是高优先级安全工作。
- Eval 仍以 deterministic regression 为主；真实模型参与的 planner/tool-call/recovery/citation benchmark 仍需单独建设。

下一轮建议按以下顺序推进：

1. 实现真正的 `AgentRuntimeGraph`，把 plan/act/observe/verify/replan/final 做成一等状态机。
2. 补齐 checkpoint resume/rollback 和前端 runtime observability UI。
3. 把 MCP preferences 到 Python sidecar gateway 的端到端 provider lifecycle 做实。
4. 升级 ToolCatalogPlanner 到 schema-aware binding planner。
5. 建立小规模 model-in-loop eval，覆盖 ReAct、工具参数绑定、恢复成功率和 citation support。
6. 升级临时脚本执行隔离，至少加入 Windows Job Object/低权限执行边界。

## 13. 参考资料

- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- AutoGen documentation: https://microsoft.github.io/autogen/stable/index.html
- CrewAI documentation: https://docs.crewai.com/
- OpenHands repository: https://github.com/OpenHands/OpenHands
