# AI Agent 生产力工具软件设计文档

日期：2026-05-09  
状态：设计已确认，等待用户审阅  
目标平台：Windows  

## 1. 产品定位与 MVP 边界

这款软件定位为 Windows 本地优先的 AI Agent 生产力工具。用户通过左侧聊天区用自然语言描述目标，并可以附加本地文件；后台 Agent 理解意图后，在右侧生成自上而下的数据流节点图，调用软件中的工具节点完成任务。工具主要面向 AI 调用，不面向用户手动操作。

第一版 MVP 的目标是验证完整闭环：

```text
用户输入需求和文档
→ AI 判断输入是否完整
→ 缺少信息时追问用户
→ 生成右侧节点流程
→ 调用固定文档工具节点
→ 输出 md 或 docx 结果文件
```

第一版包含：

- Tauri + Rust + Web 前端桌面应用
- Python LangGraph sidecar
- 内置 llama.cpp 模型运行后端
- 左侧简洁聊天区
- 右侧自上而下节点画布
- 文档处理工具包
- 输入 txt、md、docx
- 输出 md、docx
- 命令行插件和 Python 插件协议
- 临时节点 UI 占位和协议设计

第一版不包含：

- PDF、xlsx、pptx 支持
- 真实执行 AI 生成的临时脚本
- 完整工具市场
- 完整多模态工具链
- 复杂项目管理系统
- 外部 API 优先模式

## 2. 总体架构与进程边界

第一版采用三层运行结构：

```text
前端 UI
  ↓
Tauri / Rust 主程序
  ↓
Python LangGraph sidecar
```

Rust 主程序是本地核心，负责稳定、可控、和系统交互强的部分：

- Tauri 窗口和前后端桥接
- 项目工作区管理
- 文件读写和输出目录管理
- 模型运行层
- llama.cpp 后端封装
- 工具注册中心
- 命令行插件执行
- Python 插件执行入口
- 权限控制和日志记录
- 与 Python sidecar 通信

Python LangGraph sidecar 负责后台 Agent 流程：

- 意图理解
- 输入完整性检查
- 缺少文件或约束时追问用户
- 节点计划生成
- 工具调用决策
- 等待用户确认
- 失败节点处理和重试策略
- 任务状态保存与恢复

前端 UI 不直接实现 Agent 逻辑，也不直接调用本地工具。前端只负责：

- 聊天消息和附件展示
- 右侧节点画布渲染
- 节点端口、连线、分支、汇合
- 节点摘要浮窗
- 权限确认弹窗
- 任务状态展示
- 结果预览和导出入口

进程通信建议：

```text
前端 → Rust：Tauri command / event
Rust → sidecar：本地 HTTP 或 IPC
sidecar → Rust：状态事件和执行请求
Rust → 前端：事件流推送 UI 更新
```

关键原则：

- 前端不绑定 LangGraph
- 工具协议不绑定 LangGraph
- 模型运行层不绑定 LangGraph
- LangGraph 只负责任务状态机和 Agent 编排
- Rust 是权限、文件、模型和工具执行的可信边界

## 3. 前端 UI 与交互设计

第一版主界面是左右分栏操作台：

```text
左侧 40%：聊天区
右侧 60%：节点画布
```

左侧聊天区第一版保持简洁，只做核心能力：

- 多轮聊天
- 文件附件
- 发送消息
- AI 追问缺失输入
- 输入完整后触发右侧节点流程生成

第一版左侧暂不做复杂任务摘要、模型状态、完整文件管理、历史任务侧栏和高级参数面板。

用户可以在聊天框里添加文件，并和文字要求一起发送。如果用户只说“帮我处理这个文档”但没有提供文件，AI 必须先追问用户上传文件，不能直接生成节点图。

右侧节点画布采用类似 Nuke / Houdini 的上下游节点逻辑：

- 数据流方向从上到下
- 节点上方是输入端口
- 节点下方是输出端口
- 节点之间用连线表达依赖和执行顺序
- 支持分支
- 支持汇合
- 最终产物位于下游底部

节点类型第一版包括：

- 固定工具节点
- 模型/推理节点
- 输出节点
- 临时节点占位

临时节点第一版只显示和保存协议，不实际执行 AI 生成的脚本。

节点被点击后，在节点旁边弹出轻量摘要浮窗。浮窗只显示简要信息：

- 节点名称
- 节点类型
- 当前状态
- AI 调用目的
- 将调用的功能
- 输入摘要
- 输出摘要
- 查看详情入口

完整参数、日志、错误堆栈、执行记录和安全审查结果不放在浮窗里，放到二级详情入口中。

## 4. 节点、工具插件与文档工具包设计

节点不仅是 UI 图形，也是后台任务执行单元。每个节点至少包含：

```text
node_id
node_type
display_name
status
input_ports
output_ports
dependencies
tool_ref
model_ref
inputs
outputs
summary
created_by
logs_ref
artifact_refs
error_ref
retry_count
```

节点状态包括：

```text
waiting
ready
running
completed
failed
needs_user_input
needs_permission
skipped
```

工具插件统一通过工具清单接入。第一版支持两种插件类型：

- 命令行插件
- Python 插件

每个工具清单需要包含：

```text
tool_id
name
description
version
source_type
license
entrypoint
input_schema
output_schema
permissions
examples
error_codes
timeout_policy
artifact_policy
```

固定工具节点来自软件内置工具或 GitHub 开源工具封装。无论底层是自研代码、命令行程序还是 Python 库，都必须通过统一工具清单暴露给 Agent。

第一版 MVP 内置文档处理工具包，格式范围：

```text
输入：txt、md、docx
输出：md、docx
暂不支持：pdf、xlsx、pptx
```

文档工具包至少包含这些工具能力：

- 读取纯文本
- 读取 Markdown
- 读取 docx
- 提取文档结构
- 生成 Markdown
- 生成 docx
- 写入输出目录

临时节点第一版只做协议和 UI 占位，不执行脚本。临时节点协议需要预留：

```text
script_language
generated_code_ref
security_review_ref
requested_permissions
user_approval_status
sandbox_policy
```

## 5. Agent 流程与事件协议

后台 Agent 流程由 Python LangGraph sidecar 承载。第一版状态机至少包含这些阶段：

```text
receive_user_message
collect_context
check_required_inputs
ask_for_missing_inputs
plan_node_graph
request_user_confirmation_if_needed
execute_ready_nodes
handle_node_result
handle_node_failure
generate_final_artifact
complete_task
```

典型流程：

```text
用户发送文字和附件
→ Agent 收集上下文
→ 检查是否缺少文件或关键约束
→ 如果缺少，暂停并追问用户
→ 输入完整后生成节点图
→ 前端渲染节点画布
→ Rust 执行固定工具节点
→ 节点状态持续回传前端
→ 失败节点由 Agent 分析错误并尝试调整计划
→ 成功后生成 md/docx 产物
→ 用户在前端预览或打开结果
```

第一版事件协议建议采用事件流。后台向前端发送的事件包括：

```text
message.created
input.required
node_graph.created
node.created
node.updated
node.running
node.completed
node.failed
permission.required
artifact.created
task.completed
task.failed
```

前端向后台发送的事件包括：

```text
user.message_submitted
user.files_attached
user.permission_granted
user.permission_denied
user.node_selected
user.task_cancelled
```

Rust 主程序负责事件中转和可信执行：

```text
前端用户事件 → Rust
Rust 附加文件/权限/工具清单上下文 → Python sidecar
Python sidecar 返回 Agent 状态事件 → Rust
Rust 执行工具或更新任务状态 → 前端
```

第一版如果缺少输入，右侧节点图不生成正式流程，只显示等待输入状态。

## 6. 模型运行层与本地优先策略

第一版采用本地优先策略。软件内置模型运行框架，默认后端为 llama.cpp。

模型运行层属于 Rust 主程序核心，不直接属于 LangGraph，也不直接属于前端。它对上提供统一模型接口，对下封装具体推理后端。

第一版模型运行层需要提供：

```text
chat_completion
structured_output
tool_call_generation
embedding_generation
model_capability_query
streaming_response
cancel_generation
runtime_health_check
```

第一版默认内置 llama.cpp，目标能力：

- 文本大模型推理
- 结构化输出约束
- 工具调用参数生成
- 基础向量生成
- 流式输出
- 本地模型状态检测

第一版只要求多模态接口预留，不要求完整多模态能力落地。后续可扩展：

- Ollama 适配器
- LocalAI 适配器
- ONNX Runtime GenAI 适配器
- 外部 API 适配器
- 多模态模型适配器

模型能力需要以结构化方式声明，例如：

```text
supports_chat
supports_tools
supports_embeddings
supports_images
supports_audio
context_window
max_output_tokens
runtime_backend
local_only
```

本地优先规则：

- 默认使用本地模型
- 用户文件默认不出站
- 外部 API 是后续扩展，不是第一版主路径
- 敏感文件不得自动发送到外部 API
- 模型失败时先报告本地错误，不自动切换云端

## 7. 安全、权限、工作区与审计

第一版必须以项目工作区为安全边界。每个任务或项目拥有独立目录，用于保存输入引用、临时文件、节点输出、最终产物、日志和元数据。

建议工作区结构：

```text
workspace/
  inputs/
  temp/
  outputs/
  artifacts/
  logs/
  node-runs/
  manifests/
  security/
```

文件访问规则：

- 只读取用户明确添加到任务的文件
- 默认不扫描用户磁盘
- 默认不访问任意系统路径
- 输出文件只写入项目输出目录
- 原始输入文件默认不修改
- 删除操作第一版不开放给 Agent

工具权限分级：

```text
read_project_files
write_project_outputs
execute_plugin
run_python_plugin
network_access
system_command
```

第一版默认允许：

- read_project_files
- write_project_outputs
- execute_plugin
- run_python_plugin

第一版默认禁止：

- network_access
- system_command
- 修改原始文件
- 访问工作区外路径
- 读取系统密钥或环境变量

开源工具引入要求：

- 记录来源仓库
- 记录版本
- 记录许可证
- 记录二进制来源
- 记录封装适配器
- 记录工具清单

临时脚本节点第一版不执行，但协议必须保留安全字段：

- AI 安全审查结果
- 权限申请
- 用户授权状态
- 沙箱策略
- 脚本内容引用
- 运行日志引用

审计日志至少记录：

- 用户消息
- 附件加入
- Agent 决策
- 节点创建
- 工具调用
- 输入参数摘要
- 输出产物
- 错误信息
- 权限请求
- 用户确认结果

## 8. 测试策略与 MVP 验收标准

第一版测试需要覆盖六类核心风险：

- 前端交互
- Agent 状态机
- 节点图数据模型
- 工具插件协议
- 文档工具包
- 权限和工作区边界

建议测试范围：

- 聊天区可发送消息和附件
- 缺少文件时 AI 会追问
- 输入完整后生成节点图
- 节点图支持自上而下连接、分支和汇合
- 点击节点显示摘要浮窗
- 固定文档工具能读取 txt、md、docx
- 工具能输出 md 和 docx
- 节点状态能从 waiting、running、completed、failed 正确更新
- 失败节点能产生错误事件
- 工作区能保存输入、输出、日志和节点运行记录
- 工具不能访问未授权路径
- 第一版不会执行临时脚本节点

MVP 验收场景：

```text
用户打开软件
用户发送“帮我把这个文档整理成一份中文报告”
AI 发现缺少文件并请求上传
用户上传 docx
用户补充“输出为 docx，并保留要点结构”
AI 生成右侧节点图
节点从上到下展示：
  文档输入
  文档解析
  内容整理
  报告生成
  docx 导出
工具执行完成
用户获得输出 docx 文件
日志中能看到每个节点的输入、输出和状态
```

明确不验收：

- PDF 解析
- Excel/PPT 解析
- 真实临时脚本执行
- 外部 API 调用
- 完整多模态能力
- 工具市场
- 复杂项目管理

完成标准：

- 能在 Windows 上启动
- 能加载本地模型或模拟模型接口完成流程
- 能通过聊天触发任务
- 能生成节点图
- 能执行文档工具
- 能产出 md/docx 文件
- 能保存日志和工作区记录

## 9. 后续阶段

第二阶段可考虑：

- 真实执行临时脚本节点
- 临时脚本沙箱
- PDF 输入支持
- 外部 API 适配器
- Ollama / LocalAI / ONNX Runtime GenAI 适配器
- 更完整的任务历史和项目管理
- 工具市场或工具包管理

这些能力不进入第一版 MVP，避免影响核心闭环交付。

## 10. Alita Agent Harness 架构补充

本设计文档中的 Agent、LangGraph、工具插件、节点执行、安全权限、运行日志和模型运行层，统一归入 `Alita Agent Harness` 架构范畴。

`Alita Agent Harness` 是模型外部的控制层，负责让 AI 在受控环境中理解用户目标、规划节点流程、调用工具、验证结果、处理失败并记录运行过程。LangGraph 是 Harness 中的流程编排实现之一，但不是整个系统的唯一抽象。

核心边界如下：

- 前端只展示聊天、节点画布、运行状态和用户确认，不直接执行本地工具。
- Rust 主程序负责 Windows 桌面窗口、工程文件、首选项、本地安全边界、模型运行和 sidecar 生命周期。
- Python sidecar 负责 Agent 编排、节点执行、工具适配器和模型客户端。
- 工具必须通过 manifest 和 `ToolInvocation -> ToolResult` 协议接入，不能由 Agent 直接调用第三方库。
- 高风险能力，例如临时脚本节点、网络访问、删除文件、批量写入，必须经过安全审查和用户授权。

详细规范见：

```text
docs/superpowers/specs/2026-05-10-alita-agent-harness-design.md
```


