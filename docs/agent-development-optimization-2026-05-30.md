# Alita Agent 开发优化文档（代码核验版）

生成日期：2026-05-30

## 1. 核验基准

本文件最初核验的是 Git 远端跟踪分支 `origin/main` 的代码快照。随后已按本文件路线图在隔离 worktree 中完成分阶段实施。

核验与实施基准：

- `origin/main`: `0d058f9 Merge pull request #3 from Drew1811266/codex/chinese-weather-prefix-fix`
- 实施分支：`codex/reapply-local-root-changes`
- 实施 worktree：`D:\Software Project\Alita\.worktrees\reapply-local-root-changes`

说明：

- 根目录 `main` 已同步到 `origin/main`，不再保留此前“本地落后远端”的前置问题。
- 第 3-12 节保留对 baseline 的核验和路线图解释，用于说明这些建议为什么成立。
- 第 13 节记录本轮 goal 模式实施完成后的真实状态、验证证据和剩余风险。

## 2. 总体结论

附件分析的核心判断是正确的：Alita 0.29.0 已经从“节点化文档处理工作台”进化到“有 Agent Runtime 骨架的本地工作台”，但还没有形成成熟 Agent 系统需要的强闭环。

更精确地说，Alita 现在已经具备以下骨架：

- 桌面端工作台、项目文件、聊天、附件、节点图、artifact、运行历史。
- Python FastAPI sidecar 与 LangGraph 主路由。
- `AgentRunState` 作为内部运行态。
- `RouterV2` 的结构化路由 schema。
- `PlannerChain` 的策略入口。
- `ExecutionGraph` 的内部执行图投影。
- `UnifiedToolGateway`、内部 provider、MCP provider 的统一工具协议。
- `ReActController` 的受控 JSON action loop。
- 临时脚本 sandbox 的最小实现。
- 研究证据集、项目 memory store、eval harness 的最小实现。
- 前端若干 controller hook 拆分。

但这些能力大多仍处于“最小可用/受控实验/结构预埋”阶段，尚未合成默认的自治闭环：

```text
plan -> act -> observe -> verify -> replan -> act -> journal/memory/eval
```

当前最值得投入的不是继续堆 UI 功能或增加工具清单，而是把 runtime core 做实：执行图绑定、统一工具网关、权限、沙箱、ReAct/native tool calls、verifier/replanner、memory、eval 必须进入同一条可运行、可恢复、可审计的路径。

## 3. 当前代码真实状态

### 3.1 入口与主路由

相关文件：

- `python/agent_service/app.py`
- `python/agent_service/graph.py`
- `python/agent_service/agent_run_state.py`
- `python/agent_service/router_v2.py`

`app.py` 已经把 endpoint request 转换成 `AgentRunState`：

- `AgentRunState.from_message_request()`
- `AgentRunState.from_run_graph_request()`

`graph.py` 已经支持从 `AgentRunState` 进入：

- `run_agent_from_state()`
- `stream_agent_events_from_state()`

但主 LangGraph 结构仍是典型的一次路由：

```text
classify_intent
  -> answer_with_model
  -> END

classify_intent
  -> answer_with_web
  -> END

classify_intent
  -> choose_research_mode
  -> END

classify_intent
  -> plan_research_graph
  -> END

classify_intent
  -> request_required_inputs
  -> END

classify_intent
  -> plan_task_graph
  -> END
```

这说明附件中“主 Agent Graph 更像路由器，不像真正 Agent Loop”的判断准确。

### 3.2 结构化路由

相关文件：

- `python/agent_service/router_v2.py`
- `python/agent_service/intent.py`
- `python/agent_service/tool_router.py`

`RouterV2Decision` 已经包含：

- `intent`
- `confidence`
- `task_type`
- `missing_inputs`
- `required_permissions`
- `tool_candidates`
- `reason`
- `source`
- `should_clarify`
- `clarification_prompt`
- `legacy_route`

但模型路由只有在环境变量 `ALITA_STRUCTURED_ROUTER` 为 `1/true/yes/on` 时启用。默认路径仍是 `deterministic_route()`。

并且 `_is_protected_fast_path()` 会保护以下路径不进入模型路由：

- 缺失输入
- 天气工具
- 已有人类 research choice
- 文档处理
- 已选择的复杂研究流

所以附件中“RouterV2 方向正确，但默认仍偏保守”的判断准确。需要补充的是：即使默认不用模型路由，系统已经把 deterministic 结果包装成结构化 schema，这为后续切换默认策略降低了迁移成本。

### 3.3 规划链

相关文件：

- `python/agent_service/planner_chain.py`
- `python/agent_service/planner_v2.py`
- `python/agent_service/task_planner.py`
- `python/agent_service/graph_compiler.py`

`PlannerChain` 当前只有两个 strategy：

- `document_template`
- `legacy_task_planner`

文档处理走 `PlannerV2`，其他任务回落到旧的 `analyze_task()`、`select_tools()`、`resolve_tool_gaps()`、`build_task_graph()`。

因此附件中“PlannerChain 现在只是二选一策略器，不是通用动态规划器”的判断准确。

目前缺失的能力：

- 根据统一工具 schema 动态生成可执行 DAG。
- 从上游输出 schema 推断下游参数。
- 自动插入验证节点。
- 基于 observation 进行计划修补。
- 失败后重排计划，而不是只给出建议。

### 3.4 执行图与执行器

相关文件：

- `python/agent_service/execution_graph.py`
- `python/agent_service/execution.py`
- `python/agent_service/tool_execution.py`

`ExecutionGraph` 已经存在，且 `run_graph_events()` 会调用 `compile_execution_graph()`。但当前 `ExecutionToolBinding` 只有：

- `tool_id`
- `operation`
- `arguments_template`

实际编译时主要从 `GraphNode.toolRef` 提取 provider tool id，`operation` 和 `arguments_template` 没有被完整编译。

`PlannedTaskExecutor._run_fixed_tool_node()` 仍然硬编码识别：

- `document.receive_attachment`
- `document.markitdown_convert`
- `document.typst_compile`

其他 fixed tool 会落到 `unsupported_runtime`。

`ToolExecutor` 的 adapter 也只有三组：

- `document.receive_attachment / receive_attachment`
- `document.markitdown_convert / convert_local_file`
- `document.typst_compile / compile_report_pdf`

所以附件中“ExecutionGraph 抽象出现了，但执行绑定还太薄”的判断准确。需要补充的是：0.29 已经比之前更进一步，文档工具与 planned task fixed tool 已开始经过 `UnifiedToolGateway`，但最终执行行为仍被 Python 分支逻辑限制。

### 3.5 统一工具网关

相关文件：

- `python/agent_service/tool_gateway.py`
- `python/agent_service/tool_protocol.py`
- `python/agent_service/tool_providers/internal.py`
- `python/agent_service/tool_providers/mcp.py`
- `python/agent_service/model_tool_adapter.py`

`UnifiedToolGateway` 能做：

- provider 聚合
- tool 查找
- enabled 检查
- input schema 校验
- provider 分发

`default_unified_tool_gateway()` 默认只注册 `InternalToolProvider`。

MCP provider 已经存在，`model_tool_adapter.py` 也能把统一工具定义转换成 OpenAI function schema，并把模型 tool call 映射回 gateway invocation。但这些还没有成为主模型客户端和主执行路径的默认能力。

因此附件中“UnifiedToolGateway 还没有变成真正工具生态入口”的判断准确。

下一步关键不是再做一个 provider，而是把所有工具来源都纳入同一个强制路径：

```text
Tool discovery
  -> Tool selection
  -> Permission/safety validation
  -> Gateway call
  -> Observation sanitizer
  -> Journal
  -> Verifier/replanner
```

### 3.6 ReAct 控制器

相关文件：

- `python/agent_service/react_controller.py`
- `python/agent_service/execution.py`
- `python/agent_service/model_tool_adapter.py`
- `python/agent_service/model_client.py`

`ReActPolicy` 默认 `enabled=False`。只有当 graph metadata 中：

```json
{
  "react": {
    "enabled": true
  }
}
```

才会在 model node 中启用 ReAct。

当前 ReAct 模型输出要求是严格 JSON：

```json
{"kind": "tool", "tool_id": "...", "arguments": {}}
```

或者：

```json
{"kind": "final", "text": "..."}
```

`_parse_action()` 使用 `ReActAction.model_validate_json(raw)`，模型输出一旦混入解释文本就会 `malformed_action`。

`model_client.py` 虽然已有 `supports_native_tool_calls` 配置字段，但 `OpenAICompatibleModelClient._payload()` 仍只发送 `model/messages/temperature/max_tokens/stream`，没有 `tools`、`tool_choice`，也没有解析 `tool_calls`。

因此附件中“ReActController 有了，但更像受控实验组件，不是主运行时”的判断准确。

建议方向：

- API provider：优先支持 native tool calls。
- 本地模型：保留严格 JSON ReAct fallback。
- 两种模式共用 `UnifiedToolGateway`、permission gate、observation schema。

### 3.7 沙箱

相关文件：

- `python/agent_service/sandbox.py`
- `python/agent_service/execution.py`

`sandbox.py` 当前做了这些限制：

- AST 扫描禁止部分网络/动态导入相关模块。
- 检查传入 arguments 中看起来像路径的字符串是否在 allowed roots 内。
- 使用当前 Python 解释器 `subprocess.run()` 执行脚本。
- 限制 timeout。
- 要求 stdout 是 JSON。
- 检查 artifact 路径在 artifact_dir 内。
- 清洗绝对路径值。

但它不是强安全沙箱：

- 没有隔离真实文件系统。
- 没有独立低权限用户或 AppContainer。
- 没有系统调用限制。
- 没有 CPU/内存限制。
- 脚本仍可用 `open()`、`pathlib`、`os` 等访问硬编码路径。
- AST blacklist 不能构成安全边界。
- 只拦截有限 import，无法覆盖 Python 逃逸面。

所以附件中“这更像 controlled subprocess runner，不是真正 sandbox”的判断准确，而且这是 P0 安全风险。

### 3.8 权限系统

相关文件：

- `python/agent_service/permission_gate.py`
- `python/agent_service/tool_providers/internal.py`
- `python/agent_service/tool_protocol.py`

`PermissionGate` 默认允许：

- `read_attachment`
- `read_project_files`
- `run_local_cli`
- `run_python_plugin`
- `write_project_artifact`
- `write_project_outputs`

这对 MVP 方便，但不符合 Agent Runtime 的 least privilege。

当前权限判断主要是 permission string 集合判断，不是 action-time authorization。它不会根据一次工具调用的实际参数判断：

- 读了哪个路径
- 写到哪个目录
- 调了哪个外部域名
- 是否使用了 secret
- artifact 是否越界
- CLI 是否可执行

因此附件中“PermissionGate 默认权限过宽”的判断准确。

### 3.9 研究证据系统

相关文件：

- `python/agent_service/research_evidence.py`
- `python/agent_service/execution.py`
- `python/agent_service/web_research.py`

`ResearchEvidenceSet` 已经支持：

- accepted/rejected/duplicate/failed reads
- URL normalize
- content hash
- content excerpt
- citation id 检查

但 scoring 是启发式：

- title 是否存在
- snippet 长度
- https
- `.gov/.edu/official/docs` URL marker

`validate_citation_coverage()` 只检查 accepted source id 是否在 markdown 中出现过，不能证明每个关键 claim 被对应证据支持。

因此附件中“ResearchEvidence 是进步，但还不是 claim-level evidence graph”的判断准确。

### 3.10 记忆与可恢复性

相关文件：

- `python/agent_service/memory_store.py`
- `python/agent_service/context_manager.py`
- `python/agent_service/context_policy.py`
- `python/agent_service/model_sessions.py`
- `python/agent_service/run_journal.py`
- `python/agent_service/run_registry.py`

0.29 已经新增 `MemoryStore`，能写入 `memory.jsonl`，记录：

- `preference`
- `graph_summary`
- `artifact_summary`
- `tool_outcome`

`context_manager.py` 也能把 memory summary 注入 `ContextBundle`。

但当前 memory 仍是最小实现：

- 缺少自动写入策略。
- 缺少向量/关键词检索。
- 缺少压缩、淘汰、冲突处理。
- 缺少用户可见的管理/删除机制。
- 缺少把工具失败率、偏好、项目事实反馈到 planner/router 的闭环。

`ModelSessionRegistry` 是 300 秒 TTL 且 `consume()` 后 `pop()` 的一次性凭据传递机制，不是会话记忆。

`RunJournal` 是普通 JSON 文件记录，不是事务性 event log，也没有 checkpoint、branch、rollback、state diff。

因此附件中“记忆和可恢复性仍然不够”的判断准确，但需要修正为：0.29 已经有 memory 最小层，不是完全没有。

### 3.11 前端状态拆分

相关文件：

- `src/app/App.tsx`
- `src/features/task/useGraphRunController.ts`
- `src/features/artifacts/useArtifactPreviewController.ts`
- `src/features/preferences/usePreferencesController.ts`
- `src/features/voice/useVoiceInputController.ts`

`origin/main` 的 `App.tsx` 约 1315 行。它已经引入了若干 controller hook，但仍然承担大量职责：

- active project
- messages
- draft
- pending/context attachments
- graph run
- run history
- project warnings/errors
- save/open/create
- preferences dialog
- voice input
- artifact preview
- recent projects
- graph cancellation

附件中“前端拆分已经开始，但 App.tsx 仍然是巨型容器”的判断准确。行数不是附件中提到的 1447，而是当前快照约 1315，但性质不变。

### 3.12 Eval 体系

相关文件：

- `python/agent_service/eval_harness.py`
- `python/evals/router_cases.jsonl`
- `python/evals/planner_cases.jsonl`
- `python/evals/tool_cases.jsonl`
- `python/evals/research_cases.jsonl`
- `scripts/verify-mvp.ps1`
- `package.json`

0.29 已经有 eval harness，并且有 4 个 smoke case：

- router 1 条
- planner 1 条
- tool 1 条
- research 1 条

`scripts/verify-mvp.ps1` 会运行 `python -m agent_service.eval_harness --cases evals/router_cases.jsonl`。

但 `package.json` 仍没有独立 agent eval 脚本。当前 eval 也远未覆盖 Agent 系统真实风险：

- 路由准确率
- 计划可执行率
- 工具参数正确率
- 权限拦截率
- sandbox escape 阻断率
- research citation support rate
- 失败恢复率
- token/耗时成本

因此附件中“评估体系还没有成为开发主轴”的判断基本准确，但应修正为：已有 eval harness 和 smoke baseline，只是规模、指标和 CI gate 不够。

## 4. 附件建议逐条判定

| 建议/判断 | 判定 | 说明 | 优先级 |
| --- | --- | --- | --- |
| 0.29 不是 UI 原型，但也不是成熟 Agent 平台 | 准确 | Runtime 骨架已出现，闭环未形成 | P0 |
| 版本纪律变好，前后端/sidecar 同步到 0.29.0 | 已处理 | 根目录 `main` 已同步到 `origin/main`，实施在隔离 worktree 分支进行 | P0 |
| `AgentRunState` 是正确方向 | 准确 | 已统一消息、图、权限、运行模式、route 等状态 | P0 |
| 主图仍是一次路由到 END | 准确 | LangGraph 当前承担 router，不是 durable agent loop | P0 |
| `RouterV2` 是进步但默认保守 | 准确 | 模型路由由 `ALITA_STRUCTURED_ROUTER` 控制，默认 deterministic | P1 |
| `PlannerChain` 不是通用动态规划器 | 准确 | 只有 document template 与 legacy planner | P0 |
| `ExecutionGraph` 绑定过薄 | 准确 | 只初步绑定 tool/model，参数/operation/input mapping 不完整 | P0 |
| 工具系统看起来通用但 runtime 不够通用 | 准确 | Gateway 已接入部分执行，但 fixed tool 仍有硬编码分支 | P0 |
| `UnifiedToolGateway` 不是完整工具生态入口 | 准确 | 默认只有 internal provider，MCP 不在默认执行生态中 | P1 |
| `ReActController` 是受控实验组件 | 准确 | 需要 metadata 显式启用，JSON action 脆弱，native tool calls 未接入 | P1 |
| 沙箱不是安全边界 | 准确 | subprocess + AST blacklist 只能算受控执行器 | P0 |
| 默认权限过宽 | 准确 | 多个读写/执行权限默认允许，不是 deny by default | P0 |
| ResearchEvidence 不到 claim-level | 准确 | citation coverage 只检查 source id 出现，不验证 claim 支持 | P1 |
| 记忆和可恢复性不足 | 基本准确 | 0.29 已有 memory store，但仍是最小存储层 | P1 |
| `App.tsx` 仍是巨型容器 | 准确 | 已拆 controller hook，但 `App.tsx` 仍聚合多个 domain | P2 |
| eval 没成为主轴 | 基本准确 | 已有 eval harness，但只有 smoke cases，缺 CI 质量门 | P0 |

## 5. 与成熟 Agent 项目的差距

这里不建议照搬任何一个外部项目。Alita 的差异化是本地优先、桌面工作台、可视节点图、artifact 和用户可审计流程。外部项目更适合作为能力参照。

参考项目和对应启发：

- LangGraph：强调有状态、可持久化、可中断、可恢复、可观测的长期 agent orchestration。Alita 已使用 LangGraph，但主要作为一次路由图，没有把 durable execution、checkpoint、interrupt、time travel 变成核心路径。
- OpenHands：强调可信执行环境、workspace、agentic software development workflow。Alita 的最大短板正是执行环境和权限边界。
- AutoGen：强调 agent runtime、AgentChat、工具化 agent、事件/消息传递。Alita 暂时不应先做多 agent，而应先把单 agent 的工具调用、observation、verifier 做稳。
- CrewAI：把自治协作的 Crews 和确定性流程的 Flows 区分开。Alita 当前更接近 Flow/Workbench，适合先强化 Flow 内部的 runtime，而不是过早引入 Crew。

外部项目带来的架构启发可以概括为：

```text
可持久运行状态
  + 可信执行环境
  + 标准工具协议
  + 可验证 observation
  + 人类可中断/审批
  + 任务级 eval
```

## 6. 目标架构

Alita 不应该变成一个不可见的全自动黑盒 Agent。更合理的目标是：

```text
用户仍然看到节点图、artifact、运行历史、权限提示。
系统内部把每个节点图 run 变成可恢复、可审计、可验证的 Agent Runtime。
```

建议的目标 pipeline：

```text
User Message
  -> AgentRunState
  -> Deterministic Fast Router
  -> Structured Router for ambiguous/complex tasks
  -> GoalSpec
  -> Context Bundle + Project Memory
  -> PlannerChain
  -> Plan Validator
  -> ExecutionGraph Compiler
  -> Execution Kernel
  -> UnifiedToolGateway
  -> Action-Time Permission Gate
  -> Sandbox / Provider Adapter
  -> Observation Sanitizer
  -> Node Verifier
  -> Replanner / Patch Proposal
  -> RunJournal + MemoryStore + Eval Trace
```

关键原则：

```text
任何工具调用、模型 tool call、MCP 调用、web/search 调用、临时脚本、文件读写、CLI 执行，都不能绕过：

UnifiedToolGateway
  -> permission/safety policy
  -> provider adapter
  -> observation sanitizer
  -> verifier
  -> journal
```

## 7. 优先级路线图

### P0：先把 Runtime Core 打实

目标：把现有骨架变成可信的单 agent 执行内核。

建议 0-4 周内完成：

1. 同步本地工作区到 `origin/main`，解决本地 0.28/0.27 与远端 0.29.0 的差异。
2. 扩展 `ExecutionGraph` binding contract。
3. 去除 `PlannedTaskExecutor._run_fixed_tool_node()` 对文档工具的硬编码。
4. 把 operation、参数模板、输入映射、输出 schema、artifact 预期写入 runtime binding。
5. 把 `PermissionGate` 从权限字符串判断升级为 action-time authorization。
6. 把默认权限改成 deny by default，仅保留明确低风险能力。
7. 加强 sandbox，至少限制资源、输出大小、路径访问和网络。
8. 扩充 eval cases 到 50 条以上，并加入 `verify-mvp.ps1` 和 CI gate。

### P1：让 Agent 能动态行动

目标：让复杂任务默认进入结构化认知层，并让工具调用观察结果能影响下一步。

建议 4-8 周内完成：

1. 复杂/低置信任务默认启用 `RouterV2` 模型路由。
2. 新增 tool-catalog planner，根据 `UnifiedToolDefinition` 生成可执行计划。
3. 新增 plan repair pass：发现 unsupported tool、缺参数、权限不足时修补计划。
4. 为 API 模型实现 native tool calls。
5. 为本地模型保留 JSON ReAct fallback，并增强 JSON 提取容错。
6. 给每次 tool result 生成标准 observation。
7. 将 verifier 结果反馈给 replanner，而不是只生成失败事件。

### P2：形成长期工作台

目标：从单次运行变成项目级长期协作。

建议 8-12 周内完成：

1. 引入 run checkpoint 和恢复语义。
2. 建立 project memory 自动写入与检索策略。
3. 研究流升级为 claim/evidence graph。
4. 前端拆成清晰 domain controller。
5. MCP provider 接入用户配置和默认工具发现。
6. 多 run 队列和后台任务管理。

### P3：再考虑多 Agent 与生态

在单 agent runtime 可测、可恢复、可审计之前，不建议优先做多 agent。

后续可以考虑：

- Researcher / Planner / Executor / Verifier 角色化。
- Agent-as-tool。
- 工具市场或 provider marketplace。
- Docker/WSL/cloud sandbox backend。
- 多项目长期任务调度。

## 8. 关键优化项设计

### 8.1 ExecutionGraph Binding V2

当前问题：

- `ExecutionToolBinding` 只有薄字段。
- planner 没有输出完整 operation。
- fixed tool 执行依赖 Python if/else。

建议扩展为：

```python
class ExecutionToolBinding(BaseModel):
    tool_id: str
    provider_id: str
    operation: str
    arguments_template: dict[str, Any]
    input_mappings: dict[str, str]
    output_schema: dict[str, Any]
    expected_artifacts: list[ExpectedArtifact]
    permission_scope: PermissionScope
```

执行时不再写：

```python
if tool_id == "document.markitdown_convert":
    ...
```

而是统一：

```text
resolve binding
  -> render arguments from input_mappings
  -> authorize action
  -> gateway.call_tool()
  -> normalize output
  -> verify output_schema/artifacts
```

验收标准：

- 新增一个 internal fixed tool 时，不需要修改 `execution.py`。
- 工具 manifest 或 planner binding 能决定 operation 和参数。
- unsupported tool 的失败发生在 plan validation 阶段，而不是运行到一半才失败。

### 8.2 UnifiedToolGateway 强制路径

当前问题：

- 默认 gateway 只有 internal provider。
- gateway 本身只做 schema 校验和分发，不做强权限。
- MCP provider 存在，但不是默认生态。

建议：

- 新增 `ToolProviderRegistry`，从 preferences/project config 加载 provider。
- `UnifiedToolGateway.call_tool()` 前置 `AuthorityContext` 校验。
- 所有 provider result 必须转换成统一 `Observation`。
- gateway 写 audit event。

目标 provider：

- internal document tools
- MCP tools
- web/search/weather tools
- filesystem/project tools
- future browser/computer tools
- future sandboxed script tools

验收标准：

- `rg "ToolExecutor(" python/agent_service` 不应显示主执行路径绕过 gateway。
- 所有工具调用都有 invocation id、run id、node id、tool id、arguments hash、permission decision、result summary。

### 8.3 Action-Time Permission

当前问题：

- 默认权限过宽。
- 只看 permission 字符串，不看参数。

建议引入：

```python
class AuthorityContext(BaseModel):
    task_id: str
    run_id: str
    approved_tools: list[str]
    approved_permissions: list[str]
    read_roots: list[str]
    write_roots: list[str]
    network_domains: list[str]
    max_runtime_ms: int
    approval_token: str | None
```

每次 invocation 校验：

- tool 是否允许
- operation 是否允许
- input path 是否在 read_roots
- output path 是否在 write_roots
- network domain 是否允许
- 写入 artifact 是否在 artifact_dir
- CLI/script 是否有显式批准

默认建议：

- 默认允许：`read_attachment`、写入受控 artifact_dir。
- 默认拒绝：读项目任意文件、运行 CLI、运行 Python plugin、网络访问、写项目文件。

### 8.4 Sandbox V2

当前问题：

- subprocess + AST blacklist 不能作为安全边界。

建议分三层推进：

第一层，立即改进：

- stdout/stderr 最大字节数。
- script 文件最大大小。
- artifact 数量和大小限制。
- 禁止 inherited env，保留最小环境。
- 禁止相对路径逃逸。
- 所有文件读写通过传入的受控路径或代理 API。

第二层，Windows 本地增强：

- Windows Job Object 限制子进程、CPU 时间、内存。
- 低权限运行身份或 AppContainer。
- 禁止子进程再拉起进程树。

第三层，可选强隔离：

- WSL/Docker backend。
- 每次 run 独立 workspace mount。
- 显式网络开关。

验收标准：

- sandbox escape eval 包含硬编码路径读取、环境变量读取、网络请求、进程启动、超大输出、artifact 越界。
- 低风险脚本失败时不会泄露本地绝对路径、secret、完整 stderr。

### 8.5 ReAct 与 Native Tool Calls

当前问题：

- ReAct 只能严格 JSON。
- API 模型没有 native tool calls。
- ReAct 不是主循环，只是 metadata 开关。

建议：

```text
API provider with native tool calls
  -> chat_with_tools()
  -> parse tool_calls
  -> gateway.call_tool()
  -> send tool observations back

Local model fallback
  -> strict JSON action
  -> tolerant JSON extraction
  -> gateway.call_tool()
  -> observation message
```

ReAct 不应全局默认开启，而应按节点策略启用：

- 需要查询/工具探索的 model node 可启用。
- 文档固定流程不需要 ReAct。
- 权限敏感任务必须先 plan and approve。

验收标准：

- API 模型的 native `tool_calls` 能执行内部工具并返回 observation。
- 本地模型混入少量解释文本时，JSON action 能被安全提取或明确失败。
- 工具调用次数、step 次数、运行时间都被强制预算限制。

### 8.6 PlannerChain V2

当前问题：

- `document_template` 和 `legacy_task_planner` 二选一。

建议 planner 分层：

```text
DocumentTemplatePlanner
ResearchTemplatePlanner
ToolCatalogPlanner
ModelAssistedPlanner
RepairPlanner
FallbackPlanner
```

核心产物不应只是 frontend graph payload，而应是：

```text
Plan
  -> public RunGraph
  -> internal ExecutionGraph bindings
  -> validation diagnostics
  -> permission forecast
  -> eval trace
```

验收标准：

- 对一个新工具，只要有 manifest schema 和 node template，planner 能生成 binding。
- planner 能报告不可执行原因：缺工具、缺权限、缺输入、schema 不匹配。
- planner 输出必须通过 PlanValidator 才能进入 execution。

### 8.7 Verifier/Replanner 闭环

当前问题：

- 已有 `ResultVerifier`、`FinalVerifier`、`FailureReplanner`，但没有形成默认闭环。

建议：

```text
Node executes
  -> Observation
  -> NodeVerifier
  -> if failed and recoverable:
       Replanner proposes patch
       PermissionGate checks patch
       continue or ask user
  -> FinalVerifier
```

初期不要自动改图太激进。可以先实现：

- 缺 artifact：重跑节点。
- unsupported tool：替换为可用工具或要求用户安装/启用。
- schema mismatch：修正参数模板。
- model empty output：重试一次低温/不同 prompt。

验收标准：

- 失败恢复率成为 eval 指标。
- 每次自动重试都有 audit event。

### 8.8 Research Claim/Evidence Graph

当前问题：

- evidence source 已有，但 claim 没有结构化。

建议新增：

```python
class ResearchClaim(BaseModel):
    claim_id: str
    text: str
    evidence_refs: list[EvidenceRef]
    confidence: float
    conflicts: list[str]
```

流程：

```text
source search
  -> source fetch
  -> evidence extraction
  -> claim drafting
  -> claim/evidence validation
  -> report rendering
```

验收标准：

- 每个 key finding 必须绑定至少一个 evidence span。
- 引用不能只出现 `[S1]`，必须能说明该 source 支持哪一句 claim。
- 过期信息、冲突信息、无来源 claim 要进入 diagnostics。

### 8.9 Project Memory

当前问题：

- `MemoryStore` 是最小 JSONL。

建议：

- run 完成后自动写入 graph summary、artifact summary、tool outcome。
- 用户显式偏好写入 preference。
- planner 上下文只取与当前任务相关 memory。
- 提供删除/查看 memory 的 UI。
- 对 memory 做 redaction、长度限制和来源追踪。

验收标准：

- memory 不泄露 secret/path。
- memory 能影响 planner，但不会无界增长 prompt。
- eval 中包含“跨轮约束继承”和“用户偏好继承”案例。

### 8.10 Eval 体系

当前问题：

- 只有 smoke cases。

建议先建立 50 条基线：

- 10 条 router cases。
- 10 条 planner cases。
- 10 条 tool/gateway cases。
- 10 条 research evidence cases。
- 10 条 security/permission/sandbox cases。

指标：

- route accuracy
- plan executable rate
- tool success rate
- permission intercept rate
- sandbox escape blocked rate
- artifact validity
- citation support rate
- recovery success rate
- runtime duration

建议命令：

```powershell
Push-Location python
python -m agent_service.eval_harness --cases evals/router_cases.jsonl --output ..\.codex-run\evals\router
python -m agent_service.eval_harness --cases evals/planner_cases.jsonl --output ..\.codex-run\evals\planner
python -m agent_service.eval_harness --cases evals/tool_cases.jsonl --output ..\.codex-run\evals\tool
python -m agent_service.eval_harness --cases evals/research_cases.jsonl --output ..\.codex-run\evals\research
Pop-Location
```

验收标准：

- `scripts/verify-mvp.ps1` 至少跑 deterministic eval 全集。
- 模型相关 eval 可以 nightly 跑。
- PR 不允许降低 P0 指标。

### 8.11 前端 Domain Controller

当前问题：

- `App.tsx` 仍是总控容器。

建议拆分：

- `ProjectController`
- `ChatSessionController`
- `GraphRuntimeController`
- `ArtifactIndexController`
- `PermissionController`
- `PreferencesController`
- `VoiceController`

原则：

- `App.tsx` 只负责装配，不直接拥有所有业务流程。
- domain controller 暴露明确 action 和 state。
- 后续支持多 run、多项目、后台队列时，不再依赖单个 App 容器堆状态。

验收标准：

- `App.tsx` 降到 600 行以下。
- 每个 controller 有 reducer/unit tests。
- graph run 状态能支持未来多个 active/background run。

## 9. 不建议现在做的事

不建议立刻做：

- 全局自动 ReAct，无限工具调用。
- 多 Agent 团队协作。
- 工具市场。
- 大规模云端执行。
- 重做整个 UI。
- 把所有任务都交给模型动态生成脚本。

原因：

- 当前安全边界还不够。
- eval 不足以保护大范围自治能力。
- 单 agent runtime 合约还没有稳定。
- 本地模型对严格 tool planning 的可靠性需要先用 eval 校准。

## 10. 建议的前 10 个 PR

1. `chore: sync local baseline with 0.29.0`
   - 处理本地 dirty worktree。
   - 同步 `origin/main`。
   - 确保版本、README、pyproject、package 一致。

2. `test: expand deterministic agent eval baseline`
   - 增加 50 条 eval cases。
   - `verify-mvp.ps1` 跑 router/planner/tool/research/security deterministic eval。

3. `feat: add execution binding v2 schema`
   - 扩展 `ExecutionToolBinding`。
   - 添加 binding validation tests。

4. `refactor: execute fixed tools from bindings`
   - 移除 `_run_fixed_tool_node()` 的文档工具硬编码。
   - 通过 binding + gateway 执行。

5. `feat: enforce action-time permissions`
   - 新增 `AuthorityContext`。
   - 默认权限收紧。
   - 按 invocation 参数授权。

6. `feat: harden temporary script sandbox`
   - 增加输出、资源、路径、环境限制。
   - 增加 sandbox escape eval。

7. `feat: support api native tool calls`
   - `ModelClient` 增加 `chat_with_tools()`。
   - OpenAI-compatible payload 增加 `tools/tool_choice`。
   - 解析 `tool_calls`。

8. `feat: add tool catalog planner`
   - 根据 `UnifiedToolDefinition` 生成 plan/binding。
   - 缺工具/缺权限/缺输入前置失败。

9. `feat: close verifier replanner loop`
   - verifier 失败后输出可执行 patch。
   - 自动重试只覆盖低风险恢复。

10. `refactor: split app domain controllers`
    - `ProjectController`、`ChatSessionController`、`GraphRuntimeController` 第一批落地。
    - 降低 `App.tsx` 状态密度。

## 11. 阶段验收标准

### Runtime Core

- 所有工具调用都经过 `UnifiedToolGateway`。
- fixed tool 节点不依赖 `execution.py` 中的 tool id 分支。
- 每次工具调用都有标准 observation。
- 每个 run 都有完整 audit trail。

### 安全

- 默认权限 deny by default。
- 运行 CLI、Python script、网络访问、项目文件写入都需要显式授权。
- sandbox escape eval 全部通过。
- 任何 artifact 写入都被限制到 artifact_dir。

### Agent 能力

- 复杂任务能进入结构化路由。
- planner 输出可执行绑定。
- verifier 能驱动低风险自动恢复。
- ReAct/native tool calls 能在预算内可靠执行。

### 研究能力

- key findings 都有 evidence span。
- citation diagnostics 能指出无证据 claim。
- source freshness 和冲突证据有结构化记录。

### 工程质量

- deterministic eval 是 CI gate。
- model eval 有 nightly 报告。
- `App.tsx` 不再是所有业务状态的聚合点。
- memory 可查看、可删除、可追踪来源。

## 12. 最终建议

Alita 的下一阶段目标应该定义为：

```text
把可视节点工作台升级成可恢复、可审计、可评估的本地 Agent Runtime。
```

不要急着把它做成多 Agent 平台，也不要把 UI 做得更复杂。当前真正决定上限的是 runtime core：

- `ExecutionGraph` 是否能表达真实运行绑定。
- `UnifiedToolGateway` 是否成为唯一工具入口。
- `PermissionGate` 和 sandbox 是否能承受模型生成行为。
- ReAct/native tool calls 是否能把 observation 反馈进下一步。
- verifier/replanner 是否能形成失败恢复闭环。
- eval 是否能阻止回归。

如果这些打通，Alita 才会从“有 Agent Runtime 骨架的工作台”进入“可信 Agent 系统”的阶段。

## 13. 本轮实施状态

本轮按 `docs/superpowers/plans/2026-05-30-agent-runtime-goal-implementation-plan.md` 执行了 0-10 阶段。阶段进度和证据记录在 `docs/superpowers/progress/2026-05-30-agent-runtime-goal-progress.md`。这一批开发内容归档为 `0.30.0` 版本。

已完成的关键变化：

| 阶段 | 状态 | 结果 |
| --- | --- | --- |
| 0 计划与基线 | 完成 | 固化实施计划、进度表和 baseline 验证。 |
| 1 Eval gate | 完成 | deterministic eval 扩展到 router/planner/tool/research/security，`npm run agent:eval` 可一次运行全集。 |
| 2 Execution Binding V2 | 完成 | 执行图包含 operation、参数模板、输入映射、输出 schema、artifact 和权限范围。 |
| 3 Generic fixed tool | 完成 | fixed tool 节点可由 binding + gateway 执行，新增测试工具无需改 `execution.py` 分支。 |
| 4 Authority gateway | 完成 | 新增 action-time `AuthorityContext`，gateway 在 provider dispatch 前拦截越权路径和权限不足调用。 |
| 5 Sandbox hardening | 完成 | 增加脚本大小、输出、artifact、文件 API、环境变量和进程启动限制，并纳入 security eval。 |
| 6 Dynamic planning | 完成 | 新增 tool-catalog planner，直接工具使用请求可进入 planner 并生成可执行 binding。 |
| 7 Tool-calling loop | 完成 | OpenAI-compatible native tool calls 和本地 JSON fallback 都通过 `UnifiedToolGateway`。 |
| 8 Recovery/evidence/memory | 完成 | recovery action、verifier diagnostics、claim evidence diagnostics 和 memory source refs 落地。 |
| 9 Frontend decomposition | 完成 | 项目、聊天、图运行、权限 refs 拆到 domain controller，`App.tsx` 从 1442 行降到 1330 行。 |
| 10 Final gate | 完成 | 文档已更新，Python/frontend/eval/Rust/`verify-mvp.ps1` 全量 gate 均通过。 |

这些变化把原先“建议路线图”中的 P0/P1 主干能力推进到了可测试实现状态，但仍应保持谨慎：当前 sandbox 仍不是 OS 级强隔离，MCP provider 生态和多 run 后台队列还不是默认工作流，模型相关 eval 仍应在后续 CI/nightly 中继续扩展。

下一步建议从“更强隔离和可恢复运行”继续推进：

1. Windows Job Object、低权限身份或 AppContainer 级别的 sandbox V2。
2. run checkpoint、resume、branch 和 rollback。
3. MCP provider 用户配置到默认工具发现路径。
4. claim/evidence graph 的 UI 可视化和人工校正。
5. 多 run 队列、后台任务和项目级长期 memory 管理。

## 14. 参考链接

- LangGraph: https://docs.langchain.com/langgraph-platform/
- AutoGen: https://microsoft.github.io/autogen/
- OpenHands: https://github.com/OpenHands/OpenHands
- CrewAI: https://docs.crewai.com/
