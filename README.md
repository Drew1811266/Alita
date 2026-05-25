# Alita

Alita 是一个本地优先的 AI Agent 桌面工作台。它不是单纯的聊天窗口，而是把本地大模型、工程文件、节点化任务流程、文档工具、联网查询工具、语音输入、运行历史和 artifact 预览整合到一个 Windows 桌面应用中。

当前仓库版本为 `0.27.0`。这个阶段的重点是：桌面工程闭环已经成型，Agent 具备 LangGraph 路由、模型调用策略、文档处理流程、复杂研究流程、天气工具节点和搜索 provider chain。项目仍处于开发期，不是稳定发行版，但已经不再只是 UI 原型。

## 当前阶段

Alita 目前达到了一个“本地 Agent 工作台 MVP+”阶段：

- 可以创建、打开、保存 `.alita` 工程文件，并保存聊天、附件、节点图、运行历史和工具快照。
- 可以通过 Tauri 桌面窗口运行完整工作台，而不是依赖浏览器页面。
- 可以连接本地 `llama.cpp` OpenAI-compatible chat server 调用 GGUF Agent 模型。
- 可以通过模型调用策略在快速聊天、快速事实问答、深度规划和节点推理之间切换。
- 可以根据用户意图区分聊天、本地问答、简单联网问答、复杂联网研究、文档/任务流程和缺失输入。
- 可以使用 Open-Meteo 天气工具回答天气问题。
- 可以使用 Brave Search + DuckDuckGo fallback 的搜索 provider chain 执行联网搜索。
- 可以为复杂研究问题生成研究节点图，并执行搜索、来源审查、来源读取、报告合成和 Markdown 输出。
- 可以为文档处理任务生成并运行节点流程，产出 Markdown、Typst 和 PDF 等 artifact。
- 可以在首选项中管理本地 Agent 模型和语音转文字模型。
- 可以录音并通过本地 Qwen3-ASR 模型转写为输入文本。
- 可以预览和打开生成的文本、Markdown、PDF、图片、音视频等 artifact。

当前还没有把所有通用任务都做成完全自治执行。文档处理、研究流程、天气查询和基础 web 搜索是当前最完整的几个闭环。

## 核心能力

### 1. 工程文件和桌面工作台

应用启动后先进入工程主页，用户可以新建、打开或从最近工程列表恢复 `.alita` 文件。工程文件记录：

- 聊天消息与附件元数据
- 当前节点图
- 附件引用和缺失附件警告
- 当前模型引用
- 工具节点启用状态快照
- 节点运行历史
- artifact 引用

这使 Alita 更接近一个长期工作的项目环境：用户围绕一个工程持续与 Agent 协作，而不是一次性问答。

### 2. Agent 意图路由

Python sidecar 使用 LangGraph 编排 Agent 主路由。入口消息会被分成几类：

- `chat`：普通对话，走快速本地模型回复。
- `local_inquiry`：不需要联网的本地知识问答。
- `web_simple_inquiry`：当前信息、天气、版本、价格、法律、GitHub、官方文档等简单联网问题。
- `web_complex_choice`：调研、比较、方案、报告等复杂联网问题，先让用户选择快速回答或研究流程。
- `web_complex_research_flow`：生成研究节点图。
- `task`：文档处理或可执行任务，生成任务节点图。
- `missing_input`：缺少问题、缺少文档、缺少天气城市等输入。

路由代码主要位于：

- `python/agent_service/intent.py`
- `python/agent_service/graph.py`
- `python/agent_service/tool_router.py`

### 3. 模型调用策略

Alita 在模型客户端和 LangGraph 路由结果之间加入了模型调用策略层。不同任务会使用不同策略：

| Policy | 用途 | thinking | token 预算 |
| --- | --- | --- | --- |
| `fast_chat` | 普通聊天、本地问答 | `off` | 768 |
| `fast_factual` | 简单联网事实问答、研究模式选择 | `auto` | 1024 |
| `deep_reasoning` | 任务规划、复杂研究流程 | `deep` | 8192 |
| `node_reasoning` | 节点内模型推理 | `auto` | 4096 |

策略会转换为 `llama.cpp` OpenAI-compatible 请求参数，包括 `temperature`、`max_tokens`、`stream` 和 Qwen thinking 相关的 `chat_template_kwargs`。如果当前 `llama.cpp` runtime 不支持这些额外字段，客户端会降级重试，不让策略字段导致请求失败。

相关代码：

- `python/agent_service/model_policy.py`
- `python/agent_service/model_client.py`
- `python/agent_service/model_runtime.py`

### 4. 联网工具节点

0.27 版本加入了第一阶段联网工具节点。

天气问题会先经过 `route_tool_for_message()` 检测。如果识别为天气意图，会调用天气 provider，而不是泛搜索：

- 当前天气：`weather.current`
- 天气预报：`weather.forecast`
- 缺少城市：返回 `input.required`
- 默认 provider：Open-Meteo

示例：

```text
今天上海天气怎么样？
What's the weather in New York?
Will it rain in Boston?
```

简单联网搜索使用 provider chain：

1. Brave Search，配置 `ALITA_BRAVE_SEARCH_API_KEY` 后启用。
2. DuckDuckGo HTML fallback，无需 API key。

搜索 provider chain 会：

- 跳过未配置 provider。
- 在 timeout、network error、provider error 时回退。
- 在隐私拦截时停止，不把原始 query 传给后续 provider。
- 对 provider metadata 和失败消息做白名单处理，避免泄露本地路径、API key 或异常细节。

相关代码：

- `python/agent_service/tool_result.py`
- `python/agent_service/tool_router.py`
- `python/agent_service/tool_providers/weather.py`
- `python/agent_service/tool_providers/web_search.py`
- `python/agent_service/web_research.py`
- `python/agent_service/web_search.py`

### 5. 复杂联网研究流程

对于调研、比较、报告、方案等复杂联网问题，Agent 会先让用户选择：

- `Quick answer`：立即搜索并给出简短来源回答。
- `Research flow`：生成一个可运行的研究节点图。

研究节点图包含：

1. Research intent analysis
2. Privacy guard
3. Query plan
4. Parallel web search
5. Source review
6. Source reading
7. Report synthesis
8. Report quality check
9. Markdown output

研究执行器会保存中间结果，失败时可以保留 partial output，最终输出 Markdown artifact。

相关代码：

- `python/agent_service/web_research.py`
- `python/agent_service/execution.py`
- `python/agent_service/privacy.py`

### 6. 文档处理和任务节点图

当用户添加文档附件并提出总结、整理、报告、导出等请求时，Agent 会生成任务节点图。当前文档处理路径包括：

- `document-input`：接收附件。
- `document-parse`：通过 MarkItDown 转 Markdown。
- `content-organize`：模型整理结构。
- `report-generate`：模型生成报告。
- `typst-export`：通过 Typst 输出 `.typ` 和 PDF。
- `file-export`：输出最终 Markdown 或 artifact。

任务规划使用 `GoalSpec`、上下文构建、Planner V2、TaskGraph 和 GraphCompiler。图节点带有状态、依赖、端口、运行记录、资源估计、风险等级和权限信息。

相关代码：

- `python/agent_service/goal_spec.py`
- `python/agent_service/context_manager.py`
- `python/agent_service/planner_v2.py`
- `python/agent_service/task_planner.py`
- `python/agent_service/task_graph.py`
- `python/agent_service/graph_compiler.py`
- `python/agent_service/execution.py`

### 7. 工具包和安全边界

工具节点通过 `tool-packages` 下的 manifest 描述：

- tool id
- 名称和说明
- 输入输出 schema
- runtime
- permissions
- capabilities
- dependency policy
- artifact policy
- security policy

当前仓库内已有工具包：

| Tool | 说明 |
| --- | --- |
| `document.read_write` | 读取 txt、md、docx，并导出 md/docx |
| `document.markitdown_convert` | 调用 MarkItDown 把本地文档转为 Markdown |
| `document.typst_compile` | 调用 Typst CLI 生成 `.typ` 和 PDF artifact |

执行器会校验工具启用状态、路径边界、权限、运行结果和产物。

### 8. 语音输入和本地 ASR

前端支持录音输入。录音结束后：

1. 前端把音频编码为 WAV。
2. Tauri 把音频写入临时文件。
3. Python sidecar 调用 Qwen3-ASR 模型转写。
4. 转写文本插入聊天框。

当前 ASR 运行时面向 Qwen3-ASR-1.7B，使用可选依赖 `qwen-asr`。模型不随仓库提交，需要用户在首选项中配置模型目录，或通过 `ALITA_ASR_MODEL_PATH` 临时覆盖。

### 9. 统一模型库和首选项

首选项中维护模型库和 Agent 模型来源，目前支持两类本地模型：

- Agent LLM：GGUF 文件，runtime 为 `llama_cpp`。
- Speech-to-text：Qwen ASR 模型目录，runtime 为 `qwen_asr`。

模型库支持：

- 导入 GGUF 到应用模型库。
- 引用外部 GGUF 文件。
- 扫描模型目录。
- 添加语音转文字模型目录。
- 设置当前 Agent 模型。
- 设置当前语音转文字模型。
- 配置模型存储目录。
- 启用或禁用工具节点。

`首选项 -> Agent 模型配置` 可以在 `本地模型` 和 `API 模型` 间切换当前 Agent 模型来源。API 模型支持 OpenAI-compatible 接口，预设包含 OpenAI、DeepSeek、Kimi、GLM、MiniMax，也支持自定义兼容接口。

API provider 的 Base URL、模型名、启用状态等非敏感配置保存在本机首选项中；API Key 保存在系统凭据库，不写入 `.alita` 工程文件或 `preferences.json`。保存后的 key 不会在界面中回显；如果更改 provider type 或 Base URL，需要重新输入 key，避免旧 key 被绑定到新的 endpoint。

第一版 API Agent 模型只覆盖通用文本聊天与流式输出。工具调用、结构化输出、多模态输入输出以及供应商专有能力不在第一版范围内。

首选项保存在用户应用配置目录，不写入 `.alita` 工程文件。

### 10. Artifact 预览和运行历史

节点流程运行后会产生 artifact。前端支持：

- Markdown/text 预览
- PDF 预览
- 图片预览
- 视频预览
- 音频/视频文件打开
- 在文件管理器中定位 artifact

运行历史记录每次 run 的状态、节点 run record、artifact refs 和 runtime notice。

## 技术架构

```text
React / TypeScript / Vite
  |
  | Tauri invoke + event stream
  v
Rust / Tauri 2 desktop shell
  |
  | HTTP + sidecar process + local runtime process
  v
Python FastAPI Agent sidecar
  |
  | LangGraph + local model client + tool executors
  v
llama.cpp / Qwen ASR / MarkItDown / Typst / Open-Meteo / Web search providers
```

### 前端

前端位于 `src`。

主要技术：

- React `19.2`
- TypeScript `6`
- Vite `8`
- Vitest
- `@xyflow/react` 节点画布
- `react-pdf`、PhotoSwipe、Plyr 等预览组件

主要目录：

| 路径 | 说明 |
| --- | --- |
| `src/app` | 应用主状态、后端事件 reducer、全局样式 |
| `src/features/chat` | 聊天面板、附件选择 |
| `src/features/task` | Agent 消息提交、节点图运行、SSE 事件处理 |
| `src/features/canvas` | 节点画布、布局、节点弹窗 |
| `src/features/artifacts` | artifact 预览、打开、定位 |
| `src/features/preferences` | 模型库和工具节点首选项 |
| `src/features/project` | 工程创建、打开、保存 |
| `src/features/voice` | 录音、WAV 编码、ASR API、转写插入 |
| `src/shared` | 共享类型和后端事件定义 |

### Tauri 桌面壳

桌面壳位于 `src-tauri`，使用 Tauri 2 和 Rust。

它负责：

- 打开 Windows 桌面窗口。
- 读写 `.alita` 工程文件。
- 管理首选项、模型库和工具开关。
- 启动/复用 Python sidecar。
- 启动/停止 `llama.cpp` runtime。
- 代理前端对 Agent、ASR、节点运行和 artifact 的调用。
- 管理 sidecar token，避免无认证本地请求。

主要文件：

| 路径 | 说明 |
| --- | --- |
| `src-tauri/src/lib.rs` | Tauri app setup、runtime 启停、invoke handler |
| `src-tauri/src/commands.rs` | 前端可调用的 Tauri commands |
| `src-tauri/src/project.rs` | `.alita` 工程文件 |
| `src-tauri/src/preferences.rs` | 首选项和模型库 |
| `src-tauri/src/sidecar.rs` | Python sidecar 管理 |
| `src-tauri/src/llama_runtime.rs` | llama.cpp runtime 管理 |
| `src-tauri/src/agent_client.rs` | 调用 Python sidecar |
| `src-tauri/src/asr.rs` | 语音音频处理 |

### Python sidecar

Python sidecar 位于 `python/agent_service`，使用 FastAPI、Pydantic、LangGraph 和标准库网络能力。

主要 API：

| API | 说明 |
| --- | --- |
| `GET /health` | sidecar 健康检查 |
| `POST /agent/message` | 非流式 Agent 消息 |
| `POST /agent/message/stream` | SSE 流式 Agent 消息 |
| `POST /agent/research/choose` | 复杂研究模式选择 |
| `POST /agent/graph/run/stream` | SSE 运行节点图 |
| `POST /agent/graph/run/cancel` | 取消节点图运行 |
| `POST /agent/scripts/approve` | 批准临时脚本节点 |
| `POST /agent/scripts/reject` | 拒绝临时脚本节点 |
| `GET /asr/status` | ASR 模型状态 |
| `POST /asr/transcribe` | ASR 转写 |

## 项目目录

```text
.
├── src/                         # React / TypeScript 前端
├── src-tauri/                   # Tauri 2 桌面壳和 Rust 后端命令
├── python/                      # Python Agent sidecar、工具执行和测试
│   ├── agent_service/           # Agent、LangGraph、模型策略、工具路由
│   ├── tools/                   # Python 工具入口
│   └── tests/                   # Python 测试
├── scripts/                     # Windows 开发、构建和 runtime 安装脚本
├── tool-packages/               # 工具节点 manifest
├── docs/                        # 设计文档、计划和验证说明
├── models/                      # 项目级模型目录占位
├── package.json                 # 前端、Tauri 和开发脚本入口
└── README.md                    # 当前说明文档
```

当前仓库大约包含：

- Python 测试文件：39 个
- Rust/Tauri 测试文件：12 个
- 前端测试文件：23 个

## 开发环境要求

当前主线面向 Windows 桌面开发。

需要准备：

- Windows 10/11
- PowerShell 7 推荐
- Node.js 和 npm
- Python 3.10 或更高版本
- Rust toolchain
- Visual Studio Build Tools
  - Desktop development with C++
  - MSVC C++ toolset
  - Windows SDK
- Microsoft Edge WebView2 Runtime
- 可选：NVIDIA GPU 和 CUDA 版 `llama.cpp` runtime

先运行环境检查：

```powershell
npm run check:desktop-prereqs
```

## 安装依赖

安装前端和 Tauri CLI 依赖：

```powershell
npm install
```

安装 Python sidecar：

```powershell
cd python
python -m pip install -e .
```

安装 Python 测试依赖：

```powershell
cd python
python -m pip install -e .[test]
```

安装 ASR 可选依赖：

```powershell
cd python
python -m pip install -e .[asr]
```

安装 sidecar 打包依赖：

```powershell
cd python
python -m pip install -e .[package]
```

## 启动开发版

推荐使用统一桌面开发脚本：

```powershell
npm run desktop:dev
```

该命令会：

1. 检查 Windows/Tauri 开发环境。
2. 加载 Visual Studio C++ 编译环境。
3. 根据首选项或环境变量设置本地模型环境。
4. 启动或复用 Python Agent sidecar，默认端口 `8765`。
5. 启动 Vite dev server，默认端口 `1420`。
6. 启动 Tauri 桌面窗口。
7. 如果已配置 GGUF Agent 模型，启动 `llama.cpp` server，默认端口 `8766`。

只启动前端：

```powershell
npm run frontend:dev
```

只启动 sidecar：

```powershell
npm run sidecar:dev
```

## 本地模型配置

### Agent GGUF 模型

常规方式是在应用内打开：

```text
首选项 -> 模型库
```

然后导入、引用或扫描 GGUF 文件，并设置为当前 Agent 模型。

开发时也可以用环境变量覆盖：

```powershell
$env:ALITA_LLAMA_MODEL_PATH = "D:\Models\your-model.gguf"
$env:ALITA_LLAMA_GPU_LAYERS = "all"
npm run desktop:dev
```

可用环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ALITA_LLAMA_MODEL_PATH` | 空 | GGUF 模型路径；为空时本地模型 runtime 禁用 |
| `ALITA_LLAMA_BASE_URL` | `http://127.0.0.1:8766` | llama.cpp OpenAI-compatible endpoint |
| `ALITA_LLAMA_MODEL_NAME` | `local-llama-cpp` | chat completions model name |
| `ALITA_LLAMA_GPU_LAYERS` | 脚本决定 | `all`、`auto` 或具体层数 |

### Qwen ASR 模型

语音转文字模型需要完整模型目录。常规方式是在首选项中添加目录并设置为语音转文字模型。

开发时可以用环境变量覆盖：

```powershell
$env:ALITA_ASR_MODEL_PATH = "D:\Models\Qwen3-ASR-1.7B"
npm run desktop:dev
```

## 联网能力配置

### 天气

天气查询默认使用 Open-Meteo，不需要 API key。网络请求会先经过隐私 guard，避免把本地路径等私密内容发送给天气服务。

### 搜索

默认搜索 provider 为：

```text
ProviderChainSearchProvider
  -> BraveSearchProvider
  -> DuckDuckGoHtmlSearchProvider
```

如果未配置 Brave API key，会跳过 Brave 并使用 DuckDuckGo fallback。

可用环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ALITA_BRAVE_SEARCH_API_KEY` | 空 | Brave Search API key |
| `ALITA_WEB_SEARCH_PROVIDER` | `auto` | `auto`、`brave`、`duckduckgo`、`ddg` |
| `ALITA_WEB_SEARCH_TIMEOUT_SECONDS` | `8` | 搜索超时时间，最小 0.5 秒 |

示例：

```powershell
$env:ALITA_BRAVE_SEARCH_API_KEY = "your-key"
$env:ALITA_WEB_SEARCH_PROVIDER = "auto"
npm run desktop:dev
```

## 构建 Windows 安装包

```powershell
npm run desktop:build
```

构建脚本会：

1. 检查 Windows/Tauri 编译环境。
2. 安装或复用 `llama.cpp` runtime。
3. 使用 PyInstaller 构建 Python sidecar 可执行文件。
4. 执行 Tauri build。

安装包输出目录：

```text
src-tauri\target\release\bundle
```

## 验证命令

前端测试：

```powershell
npm run frontend:test
```

前端类型检查：

```powershell
npm run frontend:typecheck
```

Python 测试：

```powershell
python -m pytest python/tests -q
```

Rust/Tauri 测试：

```powershell
cargo test --manifest-path src-tauri/Cargo.toml
```

MVP 验证脚本：

```powershell
.\scripts\verify-mvp.ps1
```

0.27 发布前的主要验证结果：

```text
python -m pytest python/tests -q
465 passed

npm run frontend:typecheck
passed
```

## 运行时端口

| 端口 | 服务 | 说明 |
| --- | --- | --- |
| `1420` | Vite dev server | 前端开发服务 |
| `8765` | Python Agent sidecar | Agent、节点流程、ASR API |
| `8766` | llama.cpp server | 本地 Agent LLM 服务 |

## 当前限制

- 项目仍处于开发阶段，暂未作为稳定生产软件发布。
- 本地模型不随仓库提交，用户需要自行配置 GGUF Agent 模型和 Qwen ASR 模型目录。
- `llama.cpp` runtime 需要本地安装或由脚本下载到 `src-tauri/resources/llama-cpp`。
- ASR 首次转写需要加载模型，首次延迟和内存占用会高于普通聊天。
- 通用任务自动执行仍在扩展中；当前最完整闭环是文档处理、研究流程、天气查询和基础 web 搜索。
- 简单 web 问答目前主要基于搜索结果摘要；研究流程会进一步读取来源页面。
- Brave Search 需要 API key；没有 key 时会 fallback 到 DuckDuckGo。
- 桌面构建主线面向 Windows，跨平台发布尚未作为主线目标。

## 相关文档

- `docs/windows-desktop-runbook.md`：Windows 桌面开发、构建和本地模型运行说明。
- `docs/mvp-verification.md`：MVP 手动和自动验证说明。
- `docs/superpowers/specs/`：功能设计文档。
- `docs/superpowers/plans/`：实现计划和阶段任务。
- `docs/superpowers/specs/2026-05-23-model-call-policy-design.md`：模型调用策略设计。
- `docs/superpowers/specs/2026-05-23-web-tool-nodes-design.md`：联网工具节点设计。
- `docs/superpowers/plans/2026-05-23-web-tool-nodes-phase-1-implementation-plan.md`：联网工具节点第一阶段实现计划。

## License

本仓库包含 `LICENSE` 文件，许可证文本以该文件为准。
