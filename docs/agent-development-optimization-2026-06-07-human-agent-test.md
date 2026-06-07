# Alita Agent 真人任务测试与开发优化文档

生成日期：2026-06-07
核验对象：当前开发版 `D:\Software Project\Alita\.worktrees\node-catalog`
测试方式：通过当前运行中的桌面开发版、sidecar API 和本地模型模拟真人用户任务。
目标：确认 Alita Agent 在真实用户任务中的能力边界、失败模式、架构断点，并形成下一阶段可执行的优化路线。

## 1. 总体判断

本轮测试显示，当前 Alita Agent 已经具备较好的任务理解、中文上下文保持、天气工具调用、复杂任务规划和节点图生成能力。尤其在“一万元电脑配置并生成报告”这类复杂任务上，Agent 已经可以生成包含 `web.search.parallel`、`web.fetch.sources`、`research.synthesize`、`output.final_response` 的合理流程图。

但现在最核心的问题不是“Agent 不会想”，而是“想完以后跑不通”。新 Deep Agent Runtime、legacy graph、tool gateway、execution runtime 之间还没有完全闭环，导致几类真实用户任务会卡在产品路径边界：

```text
用户任务
  -> Deep Agent reasoning/planning 能理解
  -> 能生成或确认节点图
  -> 执行阶段进入 legacy 或 unsupported tool
  -> 用户看到失败、英文错误、重复澄清或无法继续
```

下一阶段开发重点应从“继续增加节点数量”转向“统一产品路径与执行闭环”。节点目录已经开始成形，但每个可规划节点必须对应可执行 runtime binding，否则 Agent 会生成看似正确但无法落地的图。

## 2. 本轮真人任务测试矩阵

| 编号 | 用户任务 | 期望 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- |
| H01 | 空输入 | 中文提示用户输入任务 | 返回 `planning.clarification_required`，但提示是英文 | P1 文案/guard 问题 |
| H02 | “帮我把这个文档整理成中文报告”，无附件 | 提示添加文档 | 返回中文澄清，能指出缺文档 | 基本通过，但应 deterministic guard |
| H03 | “今天上海天气怎么样？” | 调用天气工具并中文回答 | 返回 Open-Meteo 天气，中文正常 | 通过 |
| H04 | 带历史：“预算一万元、3A 游戏和剪辑”，追问是否记得 | 使用上下文中文回答 | 能记住预算和用途 | 通过 |
| H05 | “最新 Python 稳定版本是什么？给来源” | 搜索网络并返回来源 | 返回 `I could not complete the web search: 没有找到相关搜索结果。` | P1 搜索 provider 与英文文案问题 |
| H06 | 上传 README，要求摘要并导出 PDF | 生成文档处理图并确认/执行 | `tool_action` 退回 legacy，随后 `legacy_graph_blocked` | P0 产品路径断裂 |
| H07 | 复杂联网电脑配置并写文档 | 生成 web/search/fetch/synthesize/output 图 | 能生成合理图，并进入确认 | 规划通过 |
| H08 | 对 H07 点击确认执行 | 执行 web search/fetch 并生成输出 | 执行时报 `unsupported tool: web.search.parallel` | P0 执行层未接 web 工具 |
| H09 | 给已有 currentGraph 加约束“不含显示器键鼠” | 修改现有图，返回 `graph.replanned` | 重新深度规划并询问用途 | P0/P1 图反馈路径被绕开 |
| H10 | “研究并比较主流 Python Web 框架并写报告” | 生成研究流程 | 生成 web search/fetch/synthesize/final response 图 | 规划通过，执行仍待验证 |
| H11 | “你好” | 直接中文问候，不生成任务图 | 进入 Deep Agent planning，长时间等待后返回 `llama.cpp chat request failed: timed out` | P0 路由/编排入口问题 |

## 3. 主要问题清单

### P0-1：文档附件任务无法走新产品路径

用户上传 README 并要求“整理中文摘要并导出 PDF”时，reasoning gate 返回：

```json
{
  "intent": "document_generation",
  "complexity": "bounded_tool",
  "next_action": "tool_action"
}
```

随后 `AgentRuntimeEngine` 将 `tool_action` 视为 `allow_legacy_response`，交给 legacy route。legacy route 生成了 `node_graph.created`，但新产品路径又禁止 legacy graph 创建，于是返回：

```text
runtime.legacy_graph_blocked
task.failed: legacy_graph_blocked
```

代码断点：

- `python/agent_service/agent_runtime_engine.py`：`_deep_agent_product_path_decision()` 对 `simple_answer/tool_action/bounded_tool` 允许 legacy fallback。
- `python/agent_service/graph.py`：legacy `stream_agent_events_from_state()` 仍会对 task 创建 `node_graph.created`。
- 新 Runtime 又会拦截 legacy graph event，导致用户任务不可完成。

判断：这是产品路径设计冲突，不是模型能力问题。

### P0-2：Deep Agent 生成的 web 节点无法执行

复杂联网任务已经能生成如下节点：

```text
step-web-search: fixed_tool web.search.parallel
step-fetch-sources: fixed_tool web.fetch.sources
step-synthesize: model research.synthesize
step-final-output: output output.final_response
```

用户确认执行后，流程进入：

```text
planning.confirmed
agent_plan_graph.compiled
agent_plan_graph.execution_ready
agent_execution.started
task.failed: unsupported tool: web.search.parallel
agent_execution.repair_proposed
```

根因是执行层只对旧 research graph 放行 web 工具：

```python
if _is_research_graph(request) and node.toolRef in {
    "web.search.parallel",
    "web.fetch.sources",
}:
    continue
```

Deep Agent 编译出的通用图不是旧 `research-*` graph，因此 `web.search.parallel` 被 `_validate_graph_tools()` 判定为 unsupported。

判断：节点目录、规划、图编译已经具备 web 节点概念，但 tool gateway/execution runtime 还没有真正注册可执行 binding。

### P0-3：currentGraph 图反馈没有进入正确路径

用户在已有图上追加约束：“最终方案不要包含显示器和键鼠，只计算主机配件。”期望是修改当前图，返回 `graph.replanned`。

实际结果是 Deep Agent 重新进行任务规划，并询问“具体使用场景”，没有利用 currentGraph。

根因：

- legacy `graph.py` 内部有 `_should_handle_graph_feedback()` 和 `apply_graph_feedback()`。
- 但 `/agent/message` 先进入 `AgentRuntimeEngine -> Deep Agent reasoning_gate`。
- Deep Agent reasoning gate 没有 graph feedback action，也没有在 reasoning 前前置 currentGraph feedback guard。

判断：图反馈能力仍停留在 legacy router 内部，没有上升到 RuntimeEngine 主入口。

### P0-4：普通聊天误入 Deep Agent 规划导致超时

用户只发送“你好”时，期望是轻量中文聊天回复。实际路径却进入：

```text
AgentRuntimeEngine
  -> Deep Agent reasoning/planning
  -> llama.cpp long request
  -> planning failed: timed out
```

根因是 RuntimeEngine 在进入 Deep Agent 前没有完成 Semantic Router 编排：入口应先处理非语义状态守卫，再由 Semantic Router 判断自然语言意图，否则普通聊天、本地问答和简单工具问答都可能被当作需要任务规划的请求处理。

修复原则：

- `AgentRuntimeEngine.run_from_state()` 和 `stream_from_state()` 先执行非语义状态守卫，例如空输入、pending choice、附件状态、权限状态、工具可用性和明确图反馈。
- 自然语言意图统一交给 Semantic Router，输出 `response_only`、`local_answer`、`simple_tool_answer`、`web_answer`、`graph_feedback`、`deep_planning`、`research_planning` 或 `clarification_required`。
- `response_only`、`local_answer`、`simple_tool_answer` 和 `web_answer` 不进入 Deep Agent 规划；`graph_feedback` 进入图反馈路径；只有 `deep_planning` 和 `research_planning` 进入 Deep Agent 规划；`clarification_required` 返回中文澄清。
- 程序不再用 deterministic/keyword router 判断自然语言意图；旧 deterministic/legacy route 仅用于兼容测试或非语义状态 guard。
- 增加同步与流式回归测试，断言普通问候由 Semantic Router 决策后不会调用 Deep Agent。

判断：这是 Semantic Router 编排层优先级错误，不应通过增大 token 预算解决。增大预算会让错误路径等待更久，不能改变“普通聊天不该规划”的事实。

执行计划：`docs/superpowers/plans/2026-06-07-semantic-router-agent-judgment-implementation-plan.md`。

验收标准：

- `route_message()` 主路径不调用 `classify_route()`。
- RuntimeEngine 普通聊天由 Semantic Router 决策为 `response_only` 后直接回复。
- Semantic Router 模型失败时不回退关键词规则，而是进入中文澄清。
- Deep Agent 只接收 Semantic Router 判定为 `deep_planning` 或 `research_planning` 的请求。
- 本轮可补充 smoke/API 回归验证，覆盖普通问候、语义路由失败澄清和 Deep Agent 入口门禁；执行层完整验证仍以后续任务和主线程全量测试为准。

### P1-1：简单联网搜索 provider 返回 no_results

测试：

```text
用户：现在最新的 Python 稳定版本是什么？请给出来源。
```

结果：

```text
I could not complete the web search: 没有找到相关搜索结果。
```

额外验证：

- PowerShell 可访问 `https://duckduckgo.com/html/?q=latest%20Python%20stable%20version`，页面包含 `result__a`。
- PowerShell 可访问 `https://www.python.org/downloads/`。
- Python `DuckDuckGoHtmlSearchProvider` 返回页面不含 `result__a`，parser 得到 0 个结果。

根因可能是 Python provider 的 DuckDuckGo URL、User-Agent、cookie/redirect 或反爬页面兼容问题。

判断：机器不是断网，问题在搜索 provider 可靠性和诊断不足。

### P1-2：中文用户场景仍有英文文案

已观察英文：

- 空输入澄清：
  ```text
  The input is empty, so no task can be executed...
  ```
- 简单联网失败：
  ```text
  I could not complete the web search...
  ```

根因：

- reasoning clarification 直接使用模型生成的 `why_this_path`，没有 deterministic 中文 guard。
- `web_research.py` 的 `_synthesize_answer()` 有英文硬编码失败文案。

判断：需要把用户可见文案统一纳入 `response_language` 策略，并对常见缺输入走 deterministic guard。

### P1-3：缺输入澄清策略不够产品化

缺文档任务能让用户补文档，但提示来自模型自由文本。空输入也交给模型判断，导致英文。

这类问题不应该消耗 reasoning model，也不应该依赖模型生成稳定文案。应在 RuntimeEngine 入口增加 deterministic input guard：

```text
empty message -> input.required: 请先输入你想让我处理的问题或任务。
document task with no attachment -> input.required: 请添加需要处理的文档。
ambiguous task -> planning.clarification_required
```

### P1-4：模型调用与上下文预算偏保守，且实际调用和策略不一致

README 原先记录的模型策略预算为 `fast_chat=768`、`fast_factual=1024`、`deep_reasoning=8192`、`node_reasoning=4096`。这些预算对早期 MVP 可以接受，但对现在的 Agent 形态偏保守。用户期望的是“理解需求 -> 澄清 -> 规划 -> 调工具 -> 综合输出”的多阶段协作，模型不仅要回答一句话，还要稳定输出结构化 JSON、保留上下文约束、生成可执行节点图并在节点内综合资料。

用户已确认新的硬性要求：

- 本地 `llama.cpp` 默认启动上下文从 `16384` 提升到 `131072`。
- 之前列出的所有模型输出预算按 4 倍扩大。
- README、代码、测试和开发文档必须保持一致。

目标预算：

| 场景/Policy | 原预算 | 新预算 |
| --- | ---: | ---: |
| `fast_chat` 普通聊天、本地问答 | 768 | 3072 |
| `fast_factual` 简单联网事实问答、研究模式选择 | 1024 | 4096 |
| `deep_reasoning` 任务规划、复杂研究流程 | 8192 | 32768 |
| `node_reasoning` 节点内模型推理 | 4096 | 16384 |
| 结构化 router v2 | 512 | 2048 |
| legacy 文档内容整理节点 | 1024 | 4096 |
| legacy 文档报告生成节点 | 1536 | 6144 |
| 无 policy 默认模型调用 | 1024 | 4096 |

修复前的代码核查还发现实际调用存在更低的旧预算：

- `python/agent_service/router_v2.py`：结构化 router 使用 `max_tokens=512`。
- `python/agent_service/task_graph.py`：旧文档模型节点使用 `1024/1536`。
- `python/agent_service/execution.py`：planned model node 虽然先解析到 `NODE_REASONING_POLICY=4096`，但实际调用又硬编码 `max_tokens=1536`。
- `python/agent_service/context_policy.py`：聊天上下文仅 `1600` 字符，规划上下文仅 `2400` 字符，容易让多轮约束和用户补充信息被压缩掉。
- `python/agent_service/model_client.py`：诊断信息没有记录 prompt 规模、实际 max_tokens、finish_reason 或截断状态，导致难以判断失败是否由预算不足触发。

判断：

- 预算偏低不是 `unsupported tool: web.search.parallel`、`legacy_graph_blocked`、DDG provider 失效这类 P0 的根因。
- 但它很可能加重“规划不稳定、节点综合太薄、反复澄清、中文约束丢失、JSON schema 输出偶发失败”等问题。
- 对本地 GGUF 模型尤其明显：小模型/量化模型通常需要更明确的上下文和更宽松的输出空间来稳定遵循 schema。

下一步应继续将策略从“单个 max_tokens”升级为“用途 profile + 输入上下文预算 + 输出预算 + 截断恢复”。注意：这里说的是输出预算，不等于模型总上下文窗口。`131072` 是 prompt + 输出的总窗口；若某个 profile 设置 `max_tokens=32768`，仍需要为 system prompt、用户历史、工具目录、节点图和检索内容保留足够输入空间。

### P2-1：确认执行后的用户体验不清晰

复杂任务确认后，系统确实进入 `agent_execution.started`，但失败后用户只能看到工具 unsupported 或 repair proposal。对普通用户来说，这不解释“为什么刚刚能生成节点但现在不能执行”。

需要更明确的产品级错误：

```text
当前流程包含尚未接入执行器的节点：web.search.parallel。
我已经生成了修复建议：启用或实现该工具执行绑定。
```

## 4. 目标架构

下一阶段目标不是再堆更多 prompt，而是把“可规划节点”和“可执行节点”统一起来。

目标路径：

```text
/agent/message
  -> RuntimeEngine input guard
  -> RuntimeEngine graph feedback guard
  -> Deep Agent reasoning
  -> Deep Agent planning / simple answer / clarification
  -> Node Catalog resolution
  -> Agent plan graph compile
  -> Unified execution graph
  -> ToolGateway / ModelRuntime / HumanApproval / Output
  -> Verify / Repair / Final
```

关键原则：

1. **不再允许会创建图的任务退回 legacy graph。**
2. **Node Catalog 中 available 的 tool 节点必须能通过统一执行层运行。**
3. **currentGraph feedback 必须是 RuntimeEngine 一等路径。**
4. **所有用户可见文案都必须按用户语言输出。**
5. **搜索/联网能力必须有 provider 诊断和 fallback。**
6. **模型调用预算必须按真实用途分层，并记录截断/降级诊断。**

## 5. 分阶段开发方案

执行说明：本文档是后续集中开发的规划基线。模型上下文和 token 预算属于横切配置，应在修复 runtime、web execution、graph feedback 等任务前先统一，否则后续测试结果会继续受旧预算限制影响。

### Phase 1：产品路径收束（P0）

目标：文档附件任务、bounded tool 任务不再触发 `legacy_graph_blocked`。

建议改动：

- 修改 `AgentRuntimeEngine._deep_agent_product_path_decision()`：
  - `simple_answer` 继续允许 response path。
  - `tool_action`、`bounded_tool` 不再允许 legacy graph fallback。
  - 如果任务需要工具或文件输出，应进入 Deep Agent planning。
- 修改 reasoning prompt：
  - 文档读取、摘要、导出 PDF 等任务应返回 `deep_planning`，不是 `tool_action`。
- 增加 review guard：
  - 若 `next_action=tool_action/bounded_tool` 且任务需要 artifact 或 graph，则返回 runtime diagnostic 或强制转 planning。

验收标准：

- 上传 README 并要求“中文摘要 + PDF”不再出现 `legacy_graph_blocked`。
- 事件链应是：
  ```text
  reasoning.decision_created
  planning.started
  planning.draft_created
  planning.review_completed
  node_graph.created
  planning.confirmation_required
  ```

建议测试：

- `python/tests/test_agent_runtime_engine_deep_agent.py`
- `python/tests/test_app.py`
- 新增附件 README 端到端 sidecar 测试。

### Phase 2：web 节点执行闭环（P0）

目标：Deep Agent 图中的 `web.search.parallel` 和 `web.fetch.sources` 可以被统一执行器运行。

建议改动：

- 在 UnifiedToolGateway 或 InternalToolProvider 中注册 system web tools：
  - `web.search.parallel`
  - `web.fetch.sources`
- 给这两个工具定义统一 invocation schema：
  - search 输入：`query` 或 `queries`
  - fetch 输入：`urls` 或 accepted search results
  - 输出：结构化 sources、snippets、sourceContents、failures
- 修改 `_validate_graph_tools()`：
  - 不再只用 `_is_research_graph()` 豁免 web 工具。
  - 应判断 tool gateway 是否真的支持该 tool id。
- 为 Deep Agent compiled graph 增加 web tool IO mapping：
  - `step-web-search` 输出可被 `step-fetch-sources` 使用。
  - `step-fetch-sources` 输出可被 `research.synthesize` 使用。

验收标准：

- PC 配置任务确认后不再报 `unsupported tool: web.search.parallel`。
- 至少能生成 search node output，失败时也应是 provider failure，而不是 unsupported tool。
- `agent_execution.status` 应能进入 `completed`、`interrupted` 或 provider-specific failed。

建议测试：

- `python/tests/test_execution.py`
- `python/tests/test_execution_gateway_integration.py`
- `python/tests/test_agent_execution_runtime.py`
- 新增 Deep Agent web graph execution fixture。

### Phase 3：图反馈前置（P0/P1）

目标：用户基于已有图追加约束时，直接修改当前图，不重新规划基础任务。

建议改动：

- 在 `AgentRuntimeEngine.run_from_state()` 和 `stream_from_state()` 进入 Deep Agent reasoning 前，增加 currentGraph feedback guard。
- 复用或上移 legacy 逻辑：
  - `_should_handle_graph_feedback()`
  - `apply_graph_feedback()`
  - `classify_graph_feedback()`
- 或在 Deep Agent reasoning schema 中新增：
  ```json
  "next_action": "graph_feedback"
  ```
- 对 graph feedback 事件保持产品路径一致：
  ```text
  graph.feedback_detected
  graph.replanned
  planning.confirmation_required
  ```

验收标准：

- 带 `current_graph` 的“不要包含显示器和键鼠”返回 `graph.replanned`。
- 不再询问预算、用途等已有上下文。
- 修改后的图 metadata 记录 feedback 来源和约束。

建议测试：

- `python/tests/test_agent_runtime_engine_deep_agent.py`
- `python/tests/test_graph.py`
- `src/app/backendEvents.test.ts`

### Phase 4：搜索 provider 可靠性（P1）

目标：简单联网查询和复杂研究不因 DDG provider 解析失败而直接无结果。

建议改动：

- DuckDuckGo provider 增加 fallback URL：
  - primary：`https://duckduckgo.com/html/`
  - fallback：`https://html.duckduckgo.com/html/`
- 调整 Python request headers，模拟普通浏览器请求。
- 如果页面没有 `result__a`，记录诊断：
  ```json
  {
    "provider": "duckduckgo",
    "status": "no_parseable_results",
    "bodyLength": 14259,
    "hasResultAnchor": false
  }
  ```
- 增加官方站点 direct fetch fallback：
  - 对 “latest Python stable version” 这类明显官方网站问题，允许 route 到 `web.fetch.sources` 或 curated source direct fetch。
- 所有 failure message 改为中文或按用户语言输出。

验收标准：

- `latest Python stable version` 返回至少一个 python.org 来源。
- Provider 不可用时，用户看到中文失败原因和下一步建议。
- provider metadata 可用于调试。

建议测试：

- `python/tests/test_web_search.py`
- `python/tests/test_web_provider_chain.py`
- `python/tests/test_web_research.py`

### Phase 5：中文文案和 deterministic input guard（P1）

目标：中文用户场景下，所有用户可见提示都使用中文，并且常见缺输入不依赖模型自由生成。

建议改动：

- RuntimeEngine 入口增加 deterministic guard：
  - empty content
  - document task missing attachment
  - weather missing location
  - planning resume payload invalid
- 所有 fallback/failure 文案统一经过 language resolver。
- `ReasoningDecision.why_this_path` 不直接作为用户提示，除非经过语言和安全审查。

验收标准：

- 空输入返回：
  ```text
  请先输入你想让我处理的问题或任务。
  ```
- 简单 web failure 返回中文。
- 全量真人任务 smoke 中不出现英文固定错误句。

### Phase 0：模型调用与上下文预算升级（P1）

目标：让普通聊天、联网事实、任务规划、节点推理和研究综合使用用户确认的 4 倍输出预算，并把本地 `llama.cpp` 默认上下文提升到 128K。

建议改动：

- 修改 `python/agent_service/model_policy.py`：
  - `fast_chat`：`768 -> 3072`。
  - `fast_factual`：`1024 -> 4096`。
  - `deep_reasoning`：`8192 -> 32768`。
  - `node_reasoning`：`4096 -> 16384`。
- 修改 `python/agent_service/model_client.py`：
  - 无 policy 默认模型调用：`1024 -> 4096`。
- 修改 `python/agent_service/router_v2.py`：
  - 结构化 router：`512 -> 2048`。
- 修改 `python/agent_service/execution.py`：
  - 删除 planned model node 的 `max_tokens=1536` 硬编码。
  - 默认使用 `policy_for_graph_node()` 的实际预算。
  - 只有节点 metadata 明确声明更小预算时才允许覆盖。
- 修改 `python/agent_service/task_graph.py`：
  - 旧文档内容整理节点：`1024 -> 4096`。
  - 旧文档报告生成节点：`1536 -> 6144`。
- 修改 `python/agent_service/context_policy.py`：
  - 将聊天上下文从 `1600` 字符提升到 `6400` 字符。
  - 将规划上下文从 `2400` 字符提升到 `9600` 字符。
  - 将执行上下文从 `1200` 字符提升到 `4800` 字符。
  - 将研究上下文从 `2000` 字符提升到 `8000` 字符。
  - 后续改为 token-aware budget，而不是字符数裁剪。
- 修改 `src-tauri/src/llama_runtime.rs`：
  - 本地 `llama.cpp` 默认 `--ctx-size` 从 `16384` 提升到 `131072`。
- 修改 `src-tauri/src/model.rs`：
  - 本地模型能力 `context_window` 从 `16384` 提升到 `131072`。
- 更新 README：
  - 写入新的 4 倍预算。
  - 新增“输出预算”和“上下文窗口”区别，避免误把 `max_tokens` 当作总上下文。

后续增强项：

- `python/agent_service/model_client.py` 记录 `policyProfile`、实际 `max_tokens`、prompt 字符数、response 字符数、provider finish reason、是否疑似截断。
- 若 JSON schema parse 失败且疑似截断，自动用更大预算重试一次。
- 若 provider 不支持 thinking 参数，记录 degraded，而不是只记录 fallback。

目标预算：

| Profile | 输出预算 |
| --- | --- |
| `fast_chat` | 3072 |
| `fast_factual` | 4096 |
| `deep_reasoning` | 32768 |
| `node_reasoning` | 16384 |
| `router_v2` | 2048 |
| legacy 文档内容整理节点 | 4096 |
| legacy 文档报告生成节点 | 6144 |
| 无 policy 默认模型调用 | 4096 |

验收标准：

- README、`model_policy.py`、实际调用层的预算一致。
- 本地 `llama.cpp` 启动命令包含 `--ctx-size 131072`。
- planned model node 不再出现策略为 `node_reasoning` 但实际 `max_tokens=1536` 的情况，实际应使用 `16384`。
- 多轮中文任务中，用户已回答的预算、用途、限制条件不被上下文裁剪丢失。

建议测试：

- `python/tests/test_model_policy.py`
- `python/tests/test_model_client.py`
- `python/tests/test_execution.py::test_planned_model_nodes_use_node_reasoning_policy`
- 新增 JSON truncation retry fixture。

### Phase 6：真人任务回归集（P1）

目标：把本轮人工测试固化成可重复执行的 smoke/eval。

建议新增：

```text
python/tests/test_human_task_smoke.py
scripts/run-human-agent-smoke.ps1
docs/test-traceability/alita-human-agent-smoke.md
```

覆盖场景：

1. 空输入
2. 缺附件文档
3. 带附件 README 摘要导出 PDF
4. 天气查询
5. 多轮上下文追问
6. 简单联网查询
7. 复杂联网规划
8. 确认执行复杂联网图
9. currentGraph 图反馈
10. 研究报告生成

每个 case 记录：

```json
{
  "caseId": "human-web-pc-build",
  "eventTypes": [],
  "finalType": "",
  "languageOk": true,
  "graphNodes": [],
  "failureCode": null,
  "accepted": true
}
```

## 6. 优先级路线图

### 立即修复（P0）

1. 禁止 `tool_action/bounded_tool` 退回 legacy graph。
2. 让文档附件任务进入 Deep Agent planning。
3. 注册并执行 `web.search.parallel` / `web.fetch.sources`。
4. currentGraph feedback 前置到 RuntimeEngine。

### 下一轮修复（P1）

1. 修复 DDG provider fallback。
2. 简单 web failure 中文化。
3. 空输入、缺附件 deterministic guard。
4. 升级模型调用与上下文预算。
5. 真实用户 smoke 自动化。

### 中期优化（P2）

1. Agent execution repair proposal 接入 UI 操作闭环。
2. Deep Agent compiled graph 的 IO mapping 更严格。
3. Runtime trace 增加 reasoning/planning/tool/model/human approval spans。
4. Memory 与 graph feedback 结合，支持“上次方案继续修改”。

## 7. 验收门禁

每个 P0 修复 PR 必跑：

```powershell
python -m pytest python\tests\test_agent_runtime_engine_deep_agent.py python\tests\test_app.py -q
python -m pytest python\tests\test_execution.py python\tests\test_execution_gateway_integration.py -q
npm run frontend:test -- src/app/App.test.tsx src/features/task/useTaskEvents.test.ts
npm run frontend:typecheck
```

每个候选版本必须跑真人任务 smoke：

```powershell
.\scripts\run-human-agent-smoke.ps1
```

通过标准：

- 10 个 smoke case 至少 8 个完全通过。
- P0 case 必须全部通过：
  - 文档附件到 PDF 不出现 `legacy_graph_blocked`。
  - Deep Agent web 图执行不出现 `unsupported tool: web.search.parallel`。
  - currentGraph feedback 返回 `graph.replanned`。
- 中文用户路径不出现英文硬编码错误。

## 8. 风险与取舍

### 不建议继续先加更多节点

节点数量不足确实会限制 Agent 编排能力，但当前更大的风险是“节点可见但不可执行”。如果继续只扩 Node Catalog，会扩大规划和执行之间的落差。

下一步应优先建立节点生命周期契约：

```text
catalog available
  -> planner can select
  -> compiler can resolve
  -> execution graph can bind
  -> runtime can invoke
  -> UI can display result/failure
```

只有通过这条链路的节点才应标记为真正 available。

### legacy 路径不能马上删除

legacy graph 仍承载大量已存在能力和测试。短期策略应是：

- 阻止新产品路径误退回 legacy graph。
- 对仍未迁移能力提供明确 fallback diagnostic。
- 按任务类型逐步迁移 document、research、graph feedback 到 RuntimeEngine。

### web execution 不应只用旧 ResearchFlowExecutor

旧 ResearchFlowExecutor 假定固定 `research-*` 节点 ID，不适合直接执行 Deep Agent 生成的任意图。应把 web search/fetch 抽象为普通 tool binding，而不是把 Deep Agent 图伪装成旧 research graph。

## 9. 推荐下一步

建议下一份实施计划按以下顺序拆任务：

1. **Model policy and context budget upgrade**：默认上下文提升到 128K，各用途预算按 4 倍扩大，移除旧路径硬编码。
2. **Runtime path convergence**：修 `tool_action/bounded_tool` 与文档附件任务。
3. **Executable web tools**：让 web search/fetch 进入 UnifiedToolGateway。
4. **Graph feedback first-class path**：把 currentGraph feedback 前置。
5. **Search provider hardening**：修 DDG fallback 和 failure metadata。
6. **Human task smoke harness**：固化本轮真人测试。

这些事项完成后，Alita Agent 才能从“会规划的 AI 工作台”推进到“能持续完成真实复杂任务的 Agent Runtime”。
