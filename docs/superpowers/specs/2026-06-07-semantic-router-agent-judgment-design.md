# Semantic Router Agent Judgment Design

生成日期：2026-06-07

## 背景

Alita 现在已经具备 Deep Agent Runtime、结构化 Router v2、Agent Plan Graph、统一工具网关和执行运行时。但当前顶层判断仍混有关键词、正则和启发式规则，例如 `intent.py::classify_route()` 会根据“帮我”、“解释”、“最新”、“搜索”、“研究”、“比较”等语言片段推断用户意图。`router_v2.deterministic_route()` 又把这些结果包装成结构化路由，导致表面是结构化 Router，底层仍可能是关键词路由。

这种方式不适合 Agent 产品。自然语言表达方式高度多样，同一句话在不同上下文中可能代表闲聊、解释、图反馈、文档处理、联网研究或任务执行。靠关键词判断会导致：

- 普通聊天误入 Deep Agent 规划并超时。
- 复杂任务被误判成简单问答。
- currentGraph 场景下的用户反馈被当成新任务或闲聊。
- 不同用户表达习惯导致不可预测的路由。
- 后续继续补关键词，系统会越来越僵硬且难以维护。

本设计定义新的 Agent 判断算法：自然语言语义判断必须由模型 Router 完成，程序只处理非语义的产品状态。

## 核心决策

Alita 顶层判断分为两类：

```text
自然语言意图判断 -> Semantic Router LLM
确定性产品状态判断 -> State Guard / Capability Gate
```

禁止再用关键词、正则、startswith、token overlap 或模板库作为主路由依据来判断用户自然语言意图。规则可以用于安全、结构校验、产品状态和能力校验，但不能用于理解“用户到底想做什么”。

## 目标

- 用模型语义 Router 取代自然语言关键词路由。
- 保留确定性 State Guard，但只处理明确产品状态。
- 让 Router 输出可审计、可验证的结构化 JSON。
- 低置信度或上下文不足时进入澄清，而不是用规则猜测。
- Deep Agent 只处理明确需要规划、研究、执行或图修改的请求。
- 简单聊天和问答由模型判断后快速回复，不再机械命中特定短语。
- Router 决策必须包含语言、上下文引用、工具需求、图需求和置信度。

## 非目标

- 不让 Router 直接生成最终业务答案。
- 不让 Router 直接执行工具。
- 不让 Router 直接生成 Agent Plan Graph。
- 不在第一阶段重写全部 Deep Agent Planner。
- 不移除空输入、pending choice、权限确认、工具可用性这类非语义状态检查。

## 硬性约束

1. 自然语言语义判断必须来自模型 Router。
2. 关键词规则不得作为主路由 fallback。
3. 模型 Router 失败时，系统应进入安全澄清或可解释失败，不得静默退回关键词规则。
4. State Guard 只能处理不需要理解语言的产品状态。
5. Capability Gate 只能判断工具、权限、附件、上下文窗口和执行能力是否满足。
6. Router 输出必须是 schema-valid JSON；schema-invalid 不得继续规划。
7. Router 必须保持用户语言，中文用户默认中文澄清和回复。

## 总体架构

```text
UserMessage
  -> Runtime Envelope Builder
  -> State Guard
  -> Semantic Router LLM
  -> Router Validator
  -> Capability Gate
  -> Dispatch
      response_only
      local_answer
      simple_tool_answer
      web_answer
      graph_feedback
      clarification_required
      deep_planning
      research_planning
```

### Runtime Envelope Builder

构建 Router 需要的最小上下文，不把完整工程或全部历史塞给 Router：

- 当前用户消息。
- 用户语言。
- 最近对话摘要。
- 最近 3 到 5 轮关键用户约束。
- 是否有附件及附件类型摘要。
- 是否有 currentGraph 及图摘要。
- 是否存在 pending choice。
- 当前可用工具能力摘要。
- 当前项目是否允许联网、文件写入、执行工具。

Router 看到的是“判断所需上下文”，不是完整执行上下文。

### State Guard

State Guard 是确定性状态机，不做语义理解：

| 状态 | 处理 |
| --- | --- |
| 空消息且无附件 | `input.required` |
| pending confirmation / clarification | 转换为 resume command |
| 用户点击确认/取消按钮 | 转换为 resume command |
| 已有权限请求等待处理 | 进入权限处理 |
| 附件上传失败或不可读 | `input.required` 或 `task.failed` |
| sidecar/model 未配置 | 产品级错误 |

State Guard 不能判断“这句话是不是任务”。例如不能因为看到“帮我”就返回 task。

### Semantic Router LLM

Router 模型负责理解用户语言和上下文，并输出结构化决策。

建议 schema：

```json
{
  "route": "response_only",
  "intent": "greeting",
  "complexity": "simple",
  "requires_graph": false,
  "requires_tools": false,
  "requires_web": false,
  "requires_files": false,
  "requires_clarification": false,
  "language": "zh",
  "confidence": 0.97,
  "context_used": ["current_message"],
  "missing_inputs": [],
  "required_capabilities": [],
  "reason": "用户是在进行普通问候，应直接中文回复。"
}
```

Route 枚举：

| route | 含义 |
| --- | --- |
| `response_only` | 普通聊天、问候、轻量交流 |
| `local_answer` | 可基于模型知识、当前项目上下文或对话上下文回答 |
| `simple_tool_answer` | 单工具即可回答，例如天气 |
| `web_answer` | 简单联网事实问答 |
| `graph_feedback` | 用户在修改或询问当前图 |
| `clarification_required` | 目标、输入或约束不足 |
| `deep_planning` | 需要多步骤任务图、文件输出或工具编排 |
| `research_planning` | 需要多来源搜索、比较、综合和报告 |

Router 需要结合上下文判断。例如“解释一下这个概念”：

- 没有上下文：`local_answer`。
- 有 currentGraph 且用户在看节点：`graph_feedback` 或 `local_answer`，并引用图上下文。
- 有附件：可能是文档内容解释。
- 用户要求最新来源：`web_answer` 或 `research_planning`。
- 用户要求生成报告：`deep_planning`。

这类判断不能由关键词完成。

### Router Validator

Validator 负责让模型输出可控：

- JSON schema 校验。
- route 枚举校验。
- confidence 范围校验。
- required capabilities 格式校验。
- missing inputs 格式校验。
- 用户语言校验。
- 隐私字段清洗。

如果 Router 输出不合法：

```text
schema-invalid -> retry once with repair prompt
still invalid -> clarification_required 或 router.failed
```

不得退回关键词路由。

### Capability Gate

Capability Gate 不理解语言，只验证 Router 的决策能否执行：

| 检查 | 示例 |
| --- | --- |
| 工具可用性 | Router 需要 `web.search.parallel`，但工具未注册 |
| 权限 | 需要写文件、联网、执行命令 |
| 附件 | 需要处理文档但没有可读附件 |
| 上下文预算 | 请求需要更多上下文或长历史压缩 |
| 输出形态 | 用户要求 PDF，但当前导出节点是否可用 |

如果能力不足，返回产品级澄清或能力缺口，而不是生成不可执行图：

```text
当前任务需要联网搜索节点，但该节点尚未接入执行器。可以先生成研究计划，或改为离线分析。
```

### Dispatch

Dispatch 只根据已验证的 Router 决策分发：

| route | 运行路径 |
| --- | --- |
| `response_only` | fast chat response |
| `local_answer` | local answer response |
| `simple_tool_answer` | tool call + answer |
| `web_answer` | web provider + synthesis |
| `graph_feedback` | graph feedback runtime |
| `clarification_required` | one-shot clarification |
| `deep_planning` | Deep Agent reasoning + planning |
| `research_planning` | Deep Agent research planning |

Deep Agent Planner 不再承担“这个请求是不是任务”的第一责任。它只处理 Router 已经判定为需要规划的任务。

## 置信度策略

建议阈值：

| confidence | 行为 |
| ---: | --- |
| `>= 0.80` | 接受 Router 决策 |
| `0.55 - 0.79` | 低风险 route 可接受，高风险 route 先澄清 |
| `< 0.55` | `clarification_required` |

高风险 route 包括：

- `deep_planning`
- `research_planning`
- 文件写入或修改
- 外部联网
- 执行本地命令
- 修改 currentGraph

低风险 route 包括：

- `response_only`
- `local_answer`

## 失败策略

| 失败 | 处理 |
| --- | --- |
| Router 模型超时 | 中文说明需要确认目标，提供短澄清 |
| Router JSON 无效 | repair prompt 重试一次 |
| repair 仍失败 | `router.failed` 或 `clarification_required` |
| Router 低置信度 | 澄清 |
| Capability Gate 不满足 | 能力缺口提示，不生成假图 |
| Deep Agent 后续失败 | 不回退 legacy graph，返回可解释失败和 repair proposal |

## 迁移方案

### Phase 1：引入 Semantic Router 主入口

- 新增 `semantic_router.py`。
- 定义 `SemanticRouteDecision` Pydantic schema。
- Router 默认使用模型 JSON 输出。
- 保留 `router_v2` 对外兼容字段，但内部不再调用关键词 `classify_route()` 做主判断。
- `ALITA_STRUCTURED_ROUTER` 不再作为“是否启用模型 Router”的长期主开关；模型 Router 应成为默认路径。

### Phase 2：限制 legacy keyword router

- `intent.py::classify_route()` 降级为测试兼容或迁移适配层。
- 删除 RuntimeEngine 中基于 `deterministic_route()` 的自然语言预路由。
- 所有主入口改为：

```text
State Guard -> Semantic Router -> Capability Gate -> Dispatch
```

### Phase 3：接入 RuntimeEngine

- `AgentRuntimeEngine.run_from_state()` 和 `stream_from_state()` 使用 Semantic Router 决定是否进入 Deep Agent。
- 普通问候由模型 Router 判为 `response_only`，不是硬编码。
- currentGraph 场景由 Router 判断是否 `graph_feedback`，State Guard 只负责 pending/resume 状态。

### Phase 4：评估与回归

建立 Router eval 集，不用少量单元测试替代真实语言覆盖：

- 问候、寒暄、身份询问。
- 本地概念问答。
- 模糊任务。
- 文档任务。
- 有附件和无附件的相同表达。
- 有 currentGraph 和无 currentGraph 的相同表达。
- 简单联网事实。
- 复杂联网研究。
- 文件输出任务。
- 用户表达口语化、反问式、省略式、长句式。
- 中英文混合。

每个 case 记录：

- route
- confidence
- missing inputs
- required capabilities
- should clarify
- 是否进入 Deep Agent

## 测试要求

- Router schema contract tests。
- Router malformed JSON repair tests。
- Router low confidence clarification tests。
- No keyword fallback tests：禁用模型或让模型失败时，不允许关键词分类接管自然语言路由。
- RuntimeEngine dispatch tests：简单聊天不进 Deep Agent，复杂任务进入 Deep Agent。
- currentGraph tests：同一句话在有图和无图上下文中可能得到不同 route。
- 中文语言保持测试。
- Capability Gate tests：工具不可用时不生成不可执行图。
- Human smoke tests：覆盖真实用户表达，而不是只覆盖标准句式。

## 成功标准

- 普通聊天不会进入规划器，也不是靠硬编码短语判断。
- 复杂任务不会因为缺少关键词而被当成普通问答。
- Router 决策可在事件和日志中审计。
- 当 Router 不确定时，Agent 能问一个必要问题，而不是重复追问或盲目规划。
- Deep Agent 只接收需要规划的任务。
- 没有自然语言关键词规则作为主路由 fallback。

## 与现有文档的关系

这份设计替代早期“结构化 Router 包装 deterministic route”的方向。早期 Router v2 的结构化输出、schema 校验、置信度和可审计性仍然保留，但主判断来源从关键词/启发式迁移到模型语义 Router。

`2026-06-01-deep-agent-reasoning-runtime-design.md` 中“每个用户请求都经过 reasoning”的原则需要重新解释：简单请求应经过 Semantic Router 的语义判断，但不需要进入 Deep Agent Planning。Deep Agent Planning 是图规划能力，不应承担所有自然语言入口判断。
