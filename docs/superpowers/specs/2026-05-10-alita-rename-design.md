# Alita 全项目改名设计

日期：2026-05-10  
适用范围：Windows 桌面应用、Tauri/Rust 后端、React 前端、Python Agent sidecar、工程文件、偏好设置、脚本、测试和开发文档。

## 目标

将当前软件和项目统一命名为 `Alita`。改名不只停留在界面标题，而是覆盖产品名、工程文件格式、构建配置、sidecar 命名、环境变量、文档和最终项目目录。

## 设计原则

1. 新名称统一使用 `Alita`。
2. 面向用户的新工程文件扩展名使用 `.alita`。
3. 旧 `.alita` 工程文件必须继续可以打开，避免已有测试工程失效。
4. 新环境变量使用 `ALITA_*`，只读取 `ALITA_*`。
5. 新 sidecar 二进制命名为 `alita-agent-sidecar`，旧构建产物不作为源码级依赖。
6. 新默认应用数据目录由 Tauri 产品名 `Alita` 决定。
7. 当前自定义模型目录不强制迁移，用户已设置的绝对路径继续按偏好设置读取。
8. 物理项目目录最后再从 `D:\Software Project\Alita` 改为 `D:\Software Project\Alita`，避免中途破坏正在运行的开发工具。

## 用户可见变化

- 窗口标题、主页标题、首选项、运行手册和验收文档显示 `Alita`。
- 新建工程默认文件名为 `未命名工程.alita`。
- 文件选择器显示 `Alita 工程`，优先创建 `.alita`。
- 打开工程时同时允许选择 `.alita` 和 legacy `.alita`。
- 新安装包和桌面应用产品名使用 `Alita`。

## 兼容策略

### 工程文件

新建和另存为默认使用 `.alita`。旧 `.alita` 文件读取逻辑保持不变，schema version 仍为 `1`，只改变文件扩展名和错误提示。

保存逻辑使用 `.alita.tmp` 作为临时文件扩展名，避免继续写出 `.alita.tmp`。

### 类型命名

Rust 和 TypeScript 内部类型从 `AlitaProject` 改为 `AlitaProject`。序列化字段不变，确保旧 JSON 文件可以直接反序列化。

### 环境变量

新环境变量：

- `ALITA_LLAMA_MODEL_PATH`
- `ALITA_LLAMA_BASE_URL`
- `ALITA_LLAMA_MODEL_NAME`
- `ALITA_LLAMA_GPU_LAYERS`
- `ALITA_SIDECAR_TOKEN`

兼容旧环境变量：

- `ALITA_LLAMA_MODEL_PATH`
- `ALITA_LLAMA_BASE_URL`
- `ALITA_LLAMA_MODEL_NAME`
- `ALITA_LLAMA_GPU_LAYERS`
- `ALITA_SIDECAR_TOKEN`

读取优先级：新变量优先，旧变量 fallback。

### HTTP Header

新 header 使用 `X-Alita-Sidecar-Token`。旧 header `X-Alita-Sidecar-Token` 在 Python sidecar 继续兼容接收一段时间，避免开发版前后端版本短暂不一致时直接 401。

### 偏好设置

Tauri 新产品名会让默认 app config/local data 目录变为 `Alita`。如果新的 `preferences.json` 不存在，软件会尝试读取旧 Alita 配置目录中的 `preferences.json`，并在成功读取后保存到新的 Alita 配置路径。模型文件不会被移动，用户设置过的绝对模型路径会原样保留。

## 不改的内容

- 不改 `llama-cpp` 运行时目录名称。
- 不改工具 manifest 的 tool id，除非 tool id 本身包含 Alita。
- 不移动模型文件。
- 不修改生成目录 `node_modules`、`dist`、`src-tauri/target`、`python/build`、`python/dist` 中的历史构建内容；这些由重新构建自然刷新。

## 验收标准

1. `rg "Alita|Alita|Alita|\\.alita"` 在源码、配置、脚本和当前开发文档中只剩明确标注为 legacy 兼容的内容。
2. 前端测试通过。
3. Rust 测试通过。
4. Python 测试通过。
5. sidecar 可以重新构建为 `alita-agent-sidecar`。
6. Tauri 配置中的产品名、identifier、externalBin 都使用 Alita 命名。
7. 新建工程默认生成 `.alita`，`.alita` 可以打开。
8. 项目目录最终可以改名为 `D:\Software Project\Alita`。


