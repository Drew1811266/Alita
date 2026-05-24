# Alita

Alita 是一款正在开发中的本地优先 AI Agent 桌面工作台。它的目标不是做一个只负责聊天的前端壳，而是把本地大模型、语音输入、文件处理、节点化任务流程和工程持久化整合到一个 Windows 桌面软件里，让用户可以围绕一个具体工程持续与 Agent 协作。

当前版本仍处于早期开发阶段，但已经形成了一个可运行的最小闭环：用户可以创建或打开 `.alita` 工程，在聊天区向 Agent 提需求，添加本地文档附件，让系统生成并运行文档处理节点流程；也可以在首选项里管理 Agent 模型来源和本地模型，把 Agent 模型和语音转文字模型统一配置起来。

## 当前定位

Alita 的产品方向是“本地 AI 生产力工作台”：

- **本地优先**：语音转文字模型和文档处理工具优先在用户电脑本地运行；Agent LLM 默认支持本地模型，也可以由用户显式切换到兼容 API 模型。
- **工程化协作**：聊天记录、附件引用、节点流程、运行历史和产物会保存到 `.alita` 工程文件中。
- **节点化任务执行**：Agent 不只是回复文本，还可以把文档处理任务拆成可观察、可运行、可重试的节点流程。
- **可扩展模型配置**：软件首选项里维护 Agent 模型来源、Agent GGUF 模型、OpenAI-compatible API provider 和语音转文字模型，后续可以继续扩展到其他模型模块。
- **桌面软件体验**：开发版和构建版都以 Tauri Windows 桌面窗口运行，而不是要求用户手动打开浏览器页面。

## 已有主要能力

### 1. 工程文件系统

软件启动后先进入工程主页，用户可以新建、打开或从最近工程列表恢复 `.alita` 文件。工程文件保存当前工作状态，包括：

- 聊天消息和附件元数据
- 当前节点图
- 工程附件引用和缺失附件警告
- 当前模型引用
- 工具节点启用状态快照
- 节点运行历史和产物引用

这使 Alita 的使用方式更接近 IDE 或创作工具：用户不是一次性问答，而是在一个工程上下文里持续推进任务。

### 2. 聊天式 Agent 入口

聊天区是当前主要交互入口。用户可以输入自然语言请求，也可以附加本地文件。Agent sidecar 会根据请求和附件判断任务类型：

- 普通聊天请求会交给当前 Agent 模型生成回复，可以是本地 GGUF 模型，也可以是配置好的 API 模型。
- 文档处理类请求会生成节点流程。
- 当用户提到需要处理文档但没有提供附件时，系统会要求补充文件。

本地 Agent 模型通过 `llama.cpp` runtime 调用，模型文件使用 GGUF 格式。也可以在首选项中切换到 OpenAI-compatible API 模型。

### 3. 语音转文字输入

当前版本已经加入本地语音输入模块。用户点击聊天框附近的语音按钮后可以开始录音，录音期间聊天框下方会显示实时音轨，帮助用户确认声音正在被采集。

录音结束后，音频会通过 Tauri 命令传给 Python sidecar，再由本地 ASR 模型转写成文本。转写结果会插入聊天框：

- 聊天框为空时，直接填入转写文本。
- 聊天框已有内容但没有显式光标位置时，默认追加到末尾。
- 如果用户把光标放在已有文本的某个位置，转写文本会插入该位置。

当前 ASR 运行时面向 Qwen3-ASR-1.7B，使用 `qwen-asr` Python 包，并设计为走 CPU 加载，避免和 Agent LLM 抢占 GPU 显存。

### 4. 统一模型库

首选项中已经有统一的模型库视图，用来管理软件需要调用的本地模型。当前支持两类本地模型：

- **Agent 模型**：GGUF 文件，通过 `llama.cpp` runtime 运行。
- **语音转文字模型**：Qwen3-ASR-1.7B 目录，通过 `qwen_asr` runtime 运行。

模型库支持的操作包括：

- 导入 GGUF 到模型存储目录
- 引用外部 GGUF 文件
- 扫描模型目录
- 添加语音转文字模型目录
- 设置当前 Agent 模型
- 设置当前语音转文字模型
- 配置模型存储目录

首选项会保存在用户应用数据目录中，不写入项目仓库。

### API Agent 模型

进入 `首选项 -> Agent 模型配置` 后，可以在 `本地模型` 与 `API 模型` 间切换当前 Agent 模型来源。API 模型支持 OpenAI-compatible 接口，预设包含 OpenAI、DeepSeek、Kimi、GLM、MiniMax，也支持填写自定义兼容接口。

API provider 的 Base URL、模型名、启用状态等非敏感配置保存在本机首选项中；API Key 保存在系统凭据库，不写入 `.alita` 工程文件或 `preferences.json`。保存后的 key 不会在界面中回显。如果更改 provider type 或 Base URL，需要重新输入 key，避免旧 key 被绑定到新的 endpoint。

第一版 API Agent 模型只覆盖通用文本聊天与流式输出。工具调用、结构化输出、多模态输入输出以及供应商专有能力不在第一版范围内。

### 5. 文档处理节点流程

当用户添加文档附件并提出整理、总结、导出等请求时，Agent 会生成一个自上而下的数据流节点图。当前文档流程包括：

- 接收用户附件
- 使用 MarkItDown 把本地文档转换为 Markdown
- 用本地模型整理内容或生成报告
- 使用 Typst 生成排版产物
- 输出最终 artifact

节点图在右侧画布中展示，节点支持运行状态、最近运行详情、错误信息和产物引用。流程执行由 Python sidecar 负责编排，并包含工具启用状态校验、运行记录和结果校验。

### 6. 插件式工具节点基础

工具节点通过 `tool-packages` 下的 manifest 描述能力、输入输出 schema、权限、依赖和产物策略。当前已有工具方向包括：

- `document.markitdown_convert`：把本地文档转换为 Markdown。
- `document.typst_compile`：把报告内容编译为 Typst 源文件和 PDF artifact。

这个结构为后续加入更多本地工具节点预留了基础。

## 技术架构

Alita 由四层组成：

```text
React / TypeScript 前端
  |
  | Tauri invoke / event stream
  v
Rust / Tauri 桌面壳
  |
  | HTTP / sidecar process / local runtime process
  v
Python FastAPI Agent sidecar
  |
  | local model runtime / local tools
  v
llama.cpp、Qwen ASR、MarkItDown、Typst 等本地能力
```

### 前端

前端位于 `src`，使用 React、TypeScript、Vite 和 `@xyflow/react`。主要模块包括：

- `src/app`：应用主状态、聊天流、工程状态、节点运行状态和首选项入口。
- `src/features/chat`：聊天面板、附件展示和语音入口。
- `src/features/voice`：录音、音轨、ASR 状态、转写请求和文本插入逻辑。
- `src/features/canvas`：节点画布、节点布局和节点详情弹窗。
- `src/features/preferences`：模型库和工具节点首选项。
- `src/features/project`：工程创建、打开、保存和另存为。

### 桌面壳

桌面壳位于 `src-tauri`，使用 Tauri 2 和 Rust。它负责：

- 打开 Windows 桌面窗口
- 暴露前端可调用的 Tauri commands
- 管理 `.alita` 工程文件读写
- 管理首选项和模型库
- 启动或连接 Python Agent sidecar
- 启动 `llama-server.exe`
- 把录音数据写成临时 WAV 文件并提交给 ASR sidecar

Tauri 配置文件是 `src-tauri/tauri.conf.json`，当前产品名为 `Alita`，应用标识为 `com.alita.ai-workbench`。

### Python Agent sidecar

Python sidecar 位于 `python/agent_service`，使用 FastAPI、Pydantic 和 LangGraph。它负责：

- `/health` 健康检查
- `/agent/message` 和 `/agent/message/stream` 聊天与流式回复
- `/agent/graph/run/stream` 节点流程执行
- `/agent/graph/run/cancel` 流程取消
- `/asr/status` 语音模型状态检查
- `/asr/transcribe` 本地语音转文字

sidecar 也是文档工具、节点执行、运行日志、结果校验和本地模型调用的编排层。

### 本地模型运行

本地 Agent LLM 通过 `llama.cpp` 的 `llama-server.exe` 运行。开发脚本会在配置了 Agent 模型后自动启动本地模型服务，默认地址是：

```text
http://127.0.0.1:8766
```

语音转文字当前通过 Python 包 `qwen-asr` 加载 Qwen3-ASR-1.7B 模型目录。第一次转写会延迟加载模型，因此首次响应会比后续更慢。

## 项目目录

```text
.
├── src/                       # React / TypeScript 前端
├── src-tauri/                 # Tauri 2 桌面壳和 Rust 后端命令
├── python/                    # Python Agent sidecar、工具执行和测试
├── scripts/                   # Windows 开发、构建和 runtime 安装脚本
├── tool-packages/             # 工具节点 manifest 和工具包描述
├── docs/                      # 设计文档、计划、验证说明和测试结果
├── dist/                      # 前端构建输出
├── models/                    # 项目级模型目录占位，不是首选项模型库
├── package.json               # 前端、Tauri 和开发脚本入口
└── README.md                  # 当前项目说明
```

## 开发环境要求

当前主要面向 Windows 开发环境。

需要准备：

- Node.js 和 npm
- Python 3.10 或更高版本
- Rust toolchain
- Visual Studio Build Tools，包含 Desktop development with C++、MSVC C++ toolset 和 Windows SDK
- Microsoft Edge WebView2 Runtime
- 可选：NVIDIA GPU 和 CUDA 版 `llama.cpp` runtime

可以先运行环境检查：

```powershell
npm run check:desktop-prereqs
```

## 安装依赖

前端和 Tauri CLI 依赖：

```powershell
npm install
```

Python sidecar 依赖：

```powershell
cd python
python -m pip install -e .
```

如果需要运行测试：

```powershell
cd python
python -m pip install -e .[test]
```

如果需要本地语音转文字：

```powershell
cd python
python -m pip install -e .[asr]
```

如果需要打包 sidecar：

```powershell
cd python
python -m pip install -e .[package]
```

## 启动开发版桌面软件

推荐使用统一开发脚本：

```powershell
npm run desktop:dev
```

这个命令会：

1. 检查 Windows/Tauri 开发环境。
2. 加载 Visual Studio C++ 编译环境。
3. 启动或复用 Python Agent sidecar，默认端口 `8765`。
4. 启动 Vite 前端开发服务，默认端口 `1420`。
5. 启动 Tauri 桌面窗口。
6. 如果已经配置 Agent GGUF 模型，启动 `llama.cpp` 本地模型服务，默认端口 `8766`。

如果只需要前端开发服务：

```powershell
npm run frontend:dev
```

如果只需要 Python sidecar：

```powershell
npm run sidecar:dev
```

## 配置本地模型

常规配置入口是软件内的 `首选项 -> 模型库`。

### Agent 模型

Agent 模型使用 GGUF 文件，通过 `llama.cpp` 运行。可以在模型库中导入、引用或扫描 GGUF 文件，然后把其中一个模型设为当前 Agent 模型。

开发时也可以用环境变量临时覆盖：

```powershell
$env:ALITA_LLAMA_MODEL_PATH = "D:\Models\your-model.gguf"
$env:ALITA_LLAMA_GPU_LAYERS = "all"
npm run desktop:dev
```

`ALITA_LLAMA_GPU_LAYERS` 可以设为 `all`、`auto` 或具体层数。

### 语音转文字模型

语音转文字模型当前面向 Qwen3-ASR-1.7B。正常使用方式是在模型库中选择模型目录，并设置为当前语音转文字模型。

开发时也可以用环境变量临时覆盖：

```powershell
$env:ALITA_ASR_MODEL_PATH = "D:\Models\Qwen3-ASR-1.7B"
npm run desktop:dev
```

ASR 模型路径必须指向完整模型目录，而不是单个文件。

## 构建安装包

```powershell
npm run desktop:build
```

构建脚本会执行：

1. Windows/Tauri 编译环境检查。
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
npm run frontend:lint
```

Python 测试：

```powershell
cd python
python -m pytest
```

Rust 测试：

```powershell
cargo test --manifest-path src-tauri/Cargo.toml
```

MVP 验证脚本：

```powershell
.\scripts\verify-mvp.ps1
```

## 运行时端口

开发环境默认使用以下本地端口：

| 端口 | 服务 | 说明 |
| --- | --- | --- |
| `1420` | Vite dev server | 前端开发服务 |
| `8765` | Python Agent sidecar | Agent、节点流程、ASR API |
| `8766` | llama.cpp server | 本地 Agent LLM 服务 |

## 当前限制

当前项目还在开发中，以下能力仍处于早期或局部实现状态：

- Agent 的通用任务规划能力仍在扩展中，文档处理流程是当前最完整的闭环。
- 本地模型不随仓库提交，用户需要自行配置 GGUF Agent 模型和 Qwen3-ASR 模型目录。
- ASR 第一次转写会在 CPU 上加载模型，首次延迟和内存占用会明显高于普通聊天输入。
- 工具节点体系已经具备 manifest 和执行基础，但可用工具数量仍然有限。
- 当前桌面构建主要面向 Windows，跨平台发布还没有作为主线目标。

## 相关文档

- `docs/windows-desktop-runbook.md`：Windows 桌面开发、构建和本地模型运行说明。
- `docs/mvp-verification.md`：MVP 手动和自动验证说明。
- `docs/superpowers/specs/`：已实现功能的设计文档。
- `docs/superpowers/plans/`：功能实现计划。

## License

本仓库当前包含 `LICENSE` 文件，许可证文本以该文件为准。
