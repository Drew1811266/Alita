# MVP 验证说明

本文档用于验证第一版本地优先 AI Agent 生产力工具的最小闭环。

## 启动服务

1. 启动 Python Agent sidecar：

   ```powershell
   npm run sidecar:dev
   ```

   该脚本只会在本地开发启动 sidecar 时设置 `ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV=1`，方便浏览器/Vite 调试；packaged 桌面应用不使用该绕过，而是由 Tauri 提供 `ALITA_SIDECAR_TOKEN`。

2. 启动前端开发服务：

   ```powershell
   npm run dev
   ```

3. 打开前端页面：

   ```text
   http://127.0.0.1:1420/
   ```

## 手动验证

1. 在聊天框输入 `帮我把这个文档整理成一份中文报告`，不要添加附件，点击 `发送`。

   预期结果：AI 回复 `请把需要处理的文档添加到聊天框里。`

2. 点击 `添加文件`，再输入 `输出为 docx，并保留要点结构`，点击 `发送`。

   预期结果：AI 回复 `已生成右侧工具流程。`，右侧出现自上而下的数据流节点图。

3. 点击任意节点。

   预期结果：节点旁边出现简要信息弹窗，展示该节点的调用能力、任务、输入和输出。

4. 检查节点图方向。

   预期结果：节点端口位于上下方向，数据流从上到下，支持中间分支并在导出节点汇合。

## Alita Agent Harness Phase 1 验收

1. 打开 `首选项`，在 `工具节点` 中禁用 MarkItDown 文档转换工具。
2. 创建或打开工程，发送带文档附件的处理请求，等待右侧生成节点流程。
3. 点击 `运行流程`。
4. 预期结果：流程不会执行被禁用工具，聊天区提示流程失败；对应节点状态为失败，节点弹窗的最近运行详情显示错误码 `tool_disabled`。
5. 重新启用 MarkItDown 工具，再次运行流程。
6. 预期结果：文档转 Markdown 节点生成 artifact；如果节点输出为空、导出节点缺少真实 artifact，Result Verifier 会拦截流程并返回标准错误码。该异常分支主要由自动测试覆盖，手动验收以正常 artifact 产出和禁用工具失败为主。
7. 点击失败节点或临时脚本节点。
8. 预期结果：节点弹窗能显示最近运行错误码；临时脚本节点只显示安全审查状态和所需权限，不显示执行脚本或从该节点重跑的入口。

## 自动验证

运行：

```powershell
.\scripts\verify-mvp.ps1
```

脚本会执行：

- 前端 TypeScript 类型检查：`npm run frontend:lint`
- 前端生产构建：`npm run frontend:build`，覆盖 lazy-loaded artifact preview chunks，并验证 PDF worker path 能被 Vite 构建解析
- Python 测试：在 `python` 目录运行 `python -m pytest`
- Agent deterministic eval gate：`python -m agent_service.eval_harness --cases-dir evals --output ..\.codex-run\evals`
- 如果 Rust 测试需要而 sidecar binary 不存在，会先运行 `scripts\build-sidecar.ps1`
- 如果 Tauri 资源目录不存在，会创建 `src-tauri\resources\llama-cpp`
- Rust 格式检查：`cargo fmt --check`
- Rust 测试：`cargo test`

GitHub Actions 当前把快速门禁拆成 frontend、python 和 rust 三个 job；本地全量门禁仍由 `verify-mvp.ps1` 串联前端、Python、Agent eval 与 Rust/Tauri 验证。

也可以单独运行 Agent eval：

```powershell
npm run agent:eval
```

该命令会执行 router、planner、tool、research、security、model_loop 六类 deterministic eval；当前基线共 87 个 case，并在任一 case 失败时返回非零退出码。

当前机器如果未安装 Visual Studio Build Tools 的 C++ 工具链和 Windows SDK，Rust 测试会因为缺少 `link.exe` 被阻塞。这个结果代表本机编译环境不完整，不代表 Rust 源码测试断言失败。

## 桌面窗口验证

先运行环境检查：

```powershell
npm run check:desktop-prereqs
```

通过后启动桌面开发版：

```powershell
npm run desktop:dev
```

预期结果：应用以标题为 `Alita` 的 Windows 独立窗口打开，而不是要求用户手动打开浏览器地址。

候选版本发布前还必须执行 `docs/release-smoke/alita-v035-release-smoke.md` 中的 manual release smoke checklist，并保存证据目录。

构建安装包：

```powershell
npm run desktop:build
```

预期结果：Tauri 安装包输出到 `src-tauri\target\release\bundle`。当前机器如果仍缺少 Visual Studio Build Tools 或 Windows SDK，这一步会在环境检查阶段停止。

## 工程文件系统验证

启动桌面程序后，预期首先进入工程主页，而不是直接进入工作台。

1. 点击 `新建工程`，选择一个 `.alita` 文件保存路径。
2. 预期进入工作台，顶部栏显示工程名和 `已保存`。
3. 在聊天区发送一条任务，或添加示例文档后发送任务。
4. 预期顶部栏变为 `未保存`，右侧生成节点流程时工程仍保持可保存状态。
5. 点击 `保存`，预期顶部栏恢复为 `已保存`。
6. 点击 `另存为`，选择新的 `.alita` 路径，预期当前工程路径切换到新文件。
7. 关闭程序后重新启动，点击 `打开工程`，选择刚才保存的 `.alita` 文件。
8. 预期聊天记录、附件引用和节点图恢复；如果附件原始路径已不存在，顶部提示缺失附件警告。

## 首选项验证

1. 在工程主页点击 `首选项`。
2. 预期可以看到 `模型` 和 `工具节点` 两个主要区域。
3. 预期 `模型存储目录` 自动指向用户本机应用数据目录下的 `models` 文件夹，例如 `%LOCALAPPDATA%\Alita\models`。
4. 点击 `更改目录`，选择例如 `D:\AI Models\Alita`。
5. 预期 `模型存储目录` 显示为新路径，关闭后重新打开首选项仍保持不变。
6. 点击 `导入 GGUF 到模型库`，选择本地 `.gguf` 文件。
7. 预期软件把该文件复制到模型存储目录，并在模型列表中显示来源为 `模型库`。
8. 预期第一个加入的模型会自动成为默认模型；如果存在多个模型，可以点击 `设为默认` 切换默认模型。
9. 关闭并重启软件，预期 `llama.cpp` runtime 使用默认模型路径启动；Python Agent sidecar 同步收到默认模型路径、base URL 和模型名环境变量。
10. 点击 `引用外部 GGUF`，选择本地 `.gguf` 文件。
11. 预期该模型出现在模型列表中，但路径保持为原始外部路径，来源为 `外部引用`。
12. 点击 `扫描模型目录`，选择包含 `.gguf` 文件的目录。
13. 预期目录中的 `.gguf` 文件进入模型列表，并且目录路径被持久化。
14. 在 `工具节点` 列表中切换工具启用状态。
15. 关闭后重新打开首选项，预期模型列表、默认模型、模型存储目录和工具启用状态保持不变。

## llama.cpp 运行框架验证

刷新官方 Windows NVIDIA CUDA x64 版 `llama.cpp` runtime：

```powershell
npm run llama:install
```

预期结果：`src-tauri\resources\llama-cpp` 中出现 `llama-server.exe`、`ggml-cuda.dll`、`cudart64_*.dll`、`cublas*.dll` 和 `VERSION.txt`。`VERSION.txt` 中的 `backend` 应为 `cuda`。

如需临时回退到 CPU 版：

```powershell
.\scripts\install-llama-cpp.ps1 -Backend cpu
```

当前版本还没有内置具体模型。未设置模型路径时，桌面程序会跳过启动 `llama.cpp`，但软件窗口和 Agent sidecar 仍应正常启动。

配置 GGUF 模型路径后可验证本地模型服务：

```powershell
$env:ALITA_LLAMA_MODEL_PATH = "D:\Models\your-model.gguf"
$env:ALITA_LLAMA_GPU_LAYERS = "all"
npm run desktop:dev
```

预期结果：Tauri 启动 `llama-server.exe`，本地模型服务监听 `http://127.0.0.1:8766`。默认会使用 `--gpu-layers all` 将模型层尽可能放到 NVIDIA GPU；也可以把 `ALITA_LLAMA_GPU_LAYERS` 设置为 `auto` 或具体数字。

构建后可以直接启动 release 版程序：

```powershell
.\src-tauri\target\release\alita.exe
```

预期结果：窗口独立打开，程序自动启动 packaged Agent sidecar，`http://127.0.0.1:8765/health` 返回 `{"status":"ok"}`。关闭主窗口后，`127.0.0.1:8765` 不应继续被 sidecar 占用。


