# Windows 桌面窗口运行说明

## 目标

当前浏览器地址 `http://127.0.0.1:1420/` 只是 Vite 开发预览。真正的 Windows 软件窗口由 Tauri 提供。

## 一次性安装

1. 安装 Visual Studio Build Tools。
2. 在安装器中选择 `Desktop development with C++`。
3. 确认包含 MSVC C++ toolset 和 Windows SDK。
4. 确认 Microsoft Edge WebView2 Runtime 可用。
5. 关闭并重新打开 PowerShell。

## 检查环境

```powershell
npm run check:desktop-prereqs
```

如果看到 `Visual Studio Installer / vswhere was not found`，说明当前机器还没有安装 Visual Studio Build Tools。

如果看到 `link.exe was not found`，说明 Build Tools 安装不完整，需要在安装器中补选 MSVC C++ x64/x86 build tools 和 Windows SDK。

## 启动开发版桌面窗口

```powershell
npm run desktop:dev
```

预期结果：打开一个标题为 `Alita` 的 Windows 应用窗口。这个命令会先确认 Python Agent sidecar 是否在 `127.0.0.1:8765` 运行；如果没有运行，会自动启动。

## 构建安装包

```powershell
npm run desktop:build
```

这个命令会执行三件事：

1. 检查 Windows/Tauri 编译环境。
2. 下载并安装官方 Windows CUDA x64 版 `llama.cpp` 运行资源。
3. 使用 PyInstaller 构建 Python Agent sidecar 可执行文件。
4. 执行 Tauri build，生成 Windows 安装包。

预期结果：安装包输出到 `src-tauri\target\release\bundle`。

## 本地模型运行框架

当前版本已经内置 NVIDIA CUDA 版 `llama.cpp` 运行框架，但还没有内置具体模型。运行资源位于：

```text
src-tauri\resources\llama-cpp
```

如需手动刷新 `llama.cpp` runtime：

```powershell
npm run llama:install
```

默认会安装与当前 NVIDIA 驱动兼容的 CUDA 版 runtime。当前机器检测到 CUDA 13.1，因此会安装 `llama-*-bin-win-cuda-13.1-x64.zip` 和配套 `cudart-llama-bin-win-cuda-13.1-x64.zip`。如需强制安装 CPU 版 fallback：

```powershell
.\scripts\install-llama-cpp.ps1 -Backend cpu
```

配置模型路径后，软件启动时会自动拉起 `llama-server.exe`：

```powershell
$env:ALITA_LLAMA_MODEL_PATH = "D:\Models\your-model.gguf"
$env:ALITA_LLAMA_GPU_LAYERS = "all"
npm run desktop:dev
```

默认本地模型服务地址为 `http://127.0.0.1:8766`。默认 GPU 层数是 `all`，也可以把 `ALITA_LLAMA_GPU_LAYERS` 设置为 `auto` 或具体数字。如果没有设置 `ALITA_LLAMA_MODEL_PATH`，软件会跳过启动本地模型服务，Agent sidecar 和现有工作台功能仍然可以运行。

构建完成后，也可以直接运行 release 版程序做本地验证：

```powershell
.\src-tauri\target\release\alita.exe
```

预期结果：打开 `Alita` 窗口，并由 Tauri 自动启动同目录下的 `alita-agent-sidecar.exe`。关闭主窗口后，sidecar 会随主程序退出，不应继续占用 `127.0.0.1:8765`。

## 常见问题

如果 `npm run desktop:dev` 仍然打开失败，先运行：

```powershell
npm run check:desktop-prereqs
```

如果检查脚本通过，但 Tauri 仍然找不到 `link.exe`，关闭并重新打开 PowerShell 后再试。


