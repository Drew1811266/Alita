# Alita 发布前全量测试方案设计

日期：2026-05-15  
状态：设计已确认，等待执行计划  
适用范围：Alita Windows 桌面开发版、release 构建、Python Agent sidecar、llama.cpp 本地模型运行框架、工程文件、工具流程与 artifact 产出

## 1. 目标

本方案用于回答一个发布前问题：当前 Alita 软件是否能在真实 Windows 桌面环境中完成核心用户工作流，并且在自动化测试、打包、运行时服务、用户数据持久化、模型调用、工具流程和输出文件方面没有阻断发布的问题。

测试结论只分三类：

- `Pass`：所有发布门禁通过，未发现阻断发布问题。
- `Fail`：发现产品缺陷或回归，发布应停止。
- `Blocked`：环境、模型文件、系统权限或外部依赖导致无法完成测试，不能据此判定产品可发布。

## 2. 测试策略

采用分层发布门禁。每一层都保存命令输出、运行时状态、截图或人工记录。前一层失败时停止后续测试，先定位失败属于产品问题、测试环境问题还是已知限制。

分层顺序：

1. Preflight：确认测试环境、端口、依赖、进程和用户数据备份。
2. 自动化门禁：运行前端、Python sidecar、Rust/Tauri 的现有自动化测试与静态检查。
3. 打包门禁：构建 release 桌面程序、sidecar、llama.cpp runtime 和 NSIS 安装包。
4. Release 运行时门禁：直接启动 release `alita.exe`，验证窗口、sidecar、llama.cpp、端口和关闭清理。
5. 核心功能验收：按真实用户路径验证首选项、模型、工程、聊天、附件、节点图、流程运行、artifact 和重启恢复。
6. 发布判定：汇总证据，给出明确发布结论和失败分级。

## 3. 数据隔离与恢复

测试允许临时改动当前机器的 Alita 用户数据，因为 release 验收需要覆盖真实持久化路径。测试必须先备份再改动，测试结束后恢复。

需要备份：

- `%APPDATA%\com.alita.ai-workbench\preferences.json`
- 当前 Alita 相关进程列表
- 当前 `127.0.0.1:8765` 和 `127.0.0.1:8766` 端口占用
- 当前模型目录清单，尤其是 `.gguf` 文件路径

测试数据位置：

- 临时工程目录：`%TEMP%\alita-release-validation-<timestamp>`
- 测试工程文件：临时目录下的 `.alita` 文件
- 测试附件：临时目录下的 `.md`、`.txt`、`.docx`、`.pdf` 样例文件
- 证据目录：`docs/test-results/full-release-<timestamp>`

禁止事项：

- 不删除用户真实模型目录。
- 不覆盖用户现有工程文件。
- 不强杀用户无关进程。
- 不把测试产物写入仓库源码目录，证据目录除外。

## 4. Preflight 门禁

Preflight 必须确认：

- `npm run check:desktop-prereqs` 通过，包含 Rust MSVC toolchain、Node、npm、Python、Visual Studio Build Tools、WebView2。
- `package.json`、`src-tauri/tauri.conf.json` 和 `python/pyproject.toml` 中的版本、脚本和入口符合当前项目结构。
- `node_modules`、Python 依赖、Cargo 依赖可用。
- `8765` 和 `8766` 未被无关服务占用；如果已被 Alita 测试服务占用，记录并关闭或复用前必须说明。
- 当前 `alita.exe`、`alita-agent-sidecar.exe`、`llama-server.exe`、`node.exe`、`python.exe`、`cargo.exe` 状态已记录。
- 至少存在一个可用于 release 验收的 `.gguf` 模型，或明确记录模型相关测试为 `Blocked`。

## 5. 自动化门禁

自动化门禁使用现有项目测试入口，不引入新的测试框架。

必跑命令：

- `npm run frontend:lint`
- `npm run frontend:test`
- `python -m pytest`，在 `python` 目录执行
- `cargo fmt --check`，在 `src-tauri` 目录执行
- `cargo test`，在 `src-tauri` 目录执行
- `npm run frontend:build`

覆盖目标：

- 前端组件、聊天、附件、节点画布、artifact 预览、工程主页和首选项的组件级行为。
- Python Agent sidecar 的 API、图执行、工具注册、工具执行、schema 校验、运行日志、结果验证和文档工具。
- Rust/Tauri 的工程文件、偏好设置、模型配置、sidecar 生命周期、llama.cpp 启动决策、artifact 打开和工具 manifest。
- TypeScript 类型正确性和 release 前端构建可用性。

通过标准：

- 所有命令退出码为 `0`。
- 测试输出中没有未解释的 `FAILED`、`panic`、`Traceback`、TypeScript error 或 Rust compile error。
- 如果 Rust 测试被 MSVC linker 环境阻塞，结果为 `Blocked`，不能进入发布通过状态。

## 6. 打包门禁

打包门禁运行 `npm run desktop:build`，验证 release 构建真实可用，而不是只验证开发服务器。

必须确认：

- `src-tauri/target/release/alita.exe` 存在。
- `src-tauri/target/release/alita-agent-sidecar.exe` 或配置的 external binary 存在。
- `src-tauri/target/release/bundle` 下生成 Windows 安装包。
- `src-tauri/target/release/llama-cpp` 或 Tauri bundle resource 中包含 `llama-server.exe` 和必要 DLL。
- `dist/index.html` title 为 `Alita`。
- Tauri `productName` 为 `Alita`，identifier 为 `com.alita.ai-workbench`。

通过标准：

- 构建命令退出码为 `0`。
- release 二进制、sidecar、runtime 和安装包都存在。
- 构建日志无未解释错误。

## 7. Release 运行时门禁

Release 运行时门禁直接启动 release 程序，不使用 Vite dev server。

必须验证：

- `alita.exe` 能打开 Windows 桌面窗口，窗口标题为 `Alita`。
- 程序自动启动 `alita-agent-sidecar.exe`。
- `http://127.0.0.1:8765/health` 返回 HTTP 200，内容包含 `status: ok`。
- 如果默认模型存在，程序自动启动 `llama-server.exe`。
- `http://127.0.0.1:8766/health` 返回 HTTP 200。
- 正常关闭主窗口后，Alita 负责启动的 sidecar 和 llama.cpp 子进程退出。
- 强制结束主进程造成的子进程残留只作为风险记录，不等同于正常关闭失败。

通过标准：

- release 程序可启动、可关闭。
- sidecar 和模型服务健康。
- 正常关闭后没有 Alita-owned 子进程遗留。

## 8. 核心功能验收矩阵

### 8.1 首选项与模型

验证项：

- 首选项入口在工程主页和工作台可打开。
- 模型存储目录默认指向 Alita 应用数据路径。
- 更改模型存储目录后能持久化。
- 导入 `.gguf` 到模型库后文件复制到模型存储目录。
- 引用外部 `.gguf` 后路径保持为原始路径。
- 扫描模型目录后 `.gguf` 文件进入模型列表。
- 默认模型可设置，重启后仍保持。
- 工具节点启用状态可切换，重启后仍保持。

阻断失败：

- 首选项无法打开。
- 默认模型无法保存或重启丢失。
- 工具开关不生效。
- 导入模型误删或覆盖用户文件。

### 8.2 工程文件生命周期

验证项：

- 新建 `.alita` 工程。
- 保存工程。
- 另存为新 `.alita` 路径。
- 打开已有 `.alita` 工程。
- 非 `.alita` 扩展被拒绝。
- 工程包含聊天记录、附件引用、节点图、run history 和 artifact refs。
- 附件缺失时给出缺失附件警告。

阻断失败：

- 工程无法保存或打开。
- 工程重启后关键数据丢失。
- 非 `.alita` 文件被当作有效工程接受。

### 8.3 聊天与附件

验证项：

- 无附件发送文档处理请求时，提示用户添加文件。
- 普通聊天请求能得到模型或 sidecar 返回。
- 添加附件后发送文档整理请求，能生成节点图。
- 附件 metadata 正确显示文件名、类型和路径。
- 中文输入不因编码问题变成问号。

阻断失败：

- 消息无法发送。
- sidecar stream 无响应。
- 附件路径错误或丢失。
- 中文输入被破坏。

### 8.4 节点画布与弹窗

验证项：

- 节点图自上而下布局。
- 节点类型、端口、依赖关系和连接线正确显示。
- 节点状态能显示 waiting、running、succeeded、failed、cancelled。
- 点击节点后显示工具/模型能力、输入、输出、摘要、artifact refs 和最近运行记录。
- 未知工具或模型显示友好 fallback，不暴露内部 raw id 作为用户主文本。

阻断失败：

- 节点图无法生成或无法渲染。
- 节点状态与实际运行结果不一致。
- 失败节点不显示错误码。

### 8.5 流程运行与失败恢复

验证项：

- 完整文档流程可运行。
- MarkItDown 转换节点产出 Markdown artifact。
- Typst 或导出节点产出预期 artifact。
- Result Verifier 能拦截空输出或缺失 artifact。
- 禁用工具后运行失败，错误码为 `tool_disabled`。
- 重新启用工具后可重新运行或从失败节点重试。
- 运行中取消能让 UI 和 sidecar 停止当前 run。

阻断失败：

- 正常流程无法启动。
- 节点失败无错误信息。
- 禁用工具仍被执行。
- 取消后运行继续写入新 artifact。

### 8.6 Artifact 预览、打开与定位

验证项：

- Markdown artifact 以 Markdown 预览渲染。
- Text artifact 以纯文本预览渲染。
- PDF artifact 显示 PDF 预览或明确 fallback。
- 点击打开 artifact 会调用系统默认程序。
- 点击定位 artifact 会在文件管理器中定位文件。
- 预览只读取允许的 artifact 路径，不能越权读取任意文件。

阻断失败：

- 成功运行后没有 artifact。
- artifact 路径越权。
- 打开或定位调用错误文件。

### 8.7 重启恢复

验证项：

- 关闭 release 程序后重新启动。
- 默认模型、模型目录、工具开关仍保持。
- 最近工程或手工打开工程可恢复。
- 聊天记录、节点图、run history 和 artifact refs 仍存在。
- sidecar 和 llama.cpp 重启后健康。

阻断失败：

- 重启后偏好或工程状态丢失。
- 重启后 sidecar 或模型服务无法恢复。
- artifact refs 指向不存在路径但没有警告。

## 9. 证据留存

每次全量验收创建独立证据目录：

```text
docs/test-results/full-release-<timestamp>
```

证据目录至少包含：

- `preflight.txt`
- `processes-before.txt`
- `ports-before.txt`
- `preferences-before.json` 或无偏好文件说明
- `frontend-lint.txt`
- `frontend-test.txt`
- `python-pytest.txt`
- `rust-fmt.txt`
- `rust-cargo-test.txt`
- `frontend-build.txt`
- `desktop-build.txt`
- `runtime-processes.txt`
- `sidecar-health.txt`
- `llama-health.txt`
- `manual-checklist.md`
- `summary.md`

如某一步失败，必须保存对应输出并在 `summary.md` 中说明失败归类。

## 10. 失败分级

`P0 阻断发布`：

- 软件无法启动、无法关闭、无法构建 release。
- sidecar 无法健康启动。
- 配置了有效模型但 llama.cpp 无法健康启动。
- 工程无法保存或打开。
- 核心流程无法运行。
- 用户数据丢失、误删或写入越权。

`P1 必须修复后发布`：

- 某个核心功能失败但存在安全 workaround。
- artifact 预览或定位失败。
- 重试、取消、禁用工具等恢复路径失败。
- 重启后部分状态丢失。

`P2 可延期但必须记录`：

- 非核心 UI 文案、布局、轻微状态显示问题。
- 不影响功能的日志噪声。
- 已知环境限制导致的可解释偏差。

`Blocked 环境阻塞`：

- 缺少 Visual Studio Build Tools、Windows SDK、WebView2、Python、Node、Rust。
- 缺少可用 `.gguf` 模型。
- 端口被用户无关服务占用且不能关闭。
- 系统权限阻止打开文件或定位文件。

## 11. 发布通过标准

发布前全量验收通过必须同时满足：

- Preflight 无阻断。
- 所有自动化门禁命令退出码为 `0`。
- release build 成功并生成预期二进制和安装包。
- release `alita.exe` 能启动窗口。
- sidecar 健康。
- 有默认模型时 llama.cpp 健康。
- 首选项和模型配置持久化。
- 工程新建、保存、另存为、打开和重启恢复通过。
- 聊天、附件、节点图和流程运行通过。
- artifact 预览、打开、定位通过。
- 工具禁用、重试、取消路径通过或有明确非阻断风险说明。
- 正常关闭后无 Alita-owned 子进程残留。
- `summary.md` 写明最终结论、命令结果、手工结果、失败分级和风险。

## 12. 后续执行计划边界

本设计文档定义测试目标、范围、门禁和判定标准。后续执行计划应把这些门禁拆成可逐项执行的任务，包含具体 PowerShell 命令、预期输出、手工操作步骤、截图/日志保存路径和测试后恢复步骤。

执行计划不应修改产品代码，除非测试发现产品缺陷并另行创建修复计划。
