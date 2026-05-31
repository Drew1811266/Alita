# Alita v0.35 测试与排查方案

生成日期：2026-05-31
核验对象：`D:\Software Project\Alita`
版本：`0.35.1`
目标：验证 README 声明、真实软件功能、Agent 逻辑闭环和错误处理是否一致，并建立后续版本可重复执行的测试门禁。

实施追踪表见 `docs/test-traceability/alita-v035-feature-test-map.md`；分阶段实施任务见 `docs/superpowers/plans/2026-05-31-alita-v035-test-implementation-plan.md`。

## 1. 结论摘要

当前代码基线健康，主要自动化验证已通过：

| 验证项 | 命令 | 当前结果 |
| --- | --- | --- |
| Git whitespace | `git diff --check` | passed |
| Frontend typecheck | `npm run frontend:typecheck` | passed |
| Frontend tests | `npm run frontend:test` | 32 files / 211 tests passed |
| Frontend production build | `npm run frontend:build` | passed |
| Python tests | `Push-Location python; python -m pytest -q; Pop-Location` | 823 passed |
| Agent eval | `npm run agent:eval` | 87/87 passed |
| Rust/Tauri tests | `cargo test --manifest-path src-tauri/Cargo.toml` | 162 passed |
| Rust fmt | `Push-Location src-tauri; cargo fmt --check; Pop-Location` | passed |
| MVP script | `.\scripts\verify-mvp.ps1` | passed |

初始审计发现的文档/门禁漂移及当前处理状态：

| 风险 | 初始审计证据 | 当前状态 | 优先级 |
| --- | --- | --- | --- |
| README 测试文件数量曾经过期 | 初始 README 写 Python 39、Rust 12、Frontend 23；最终基线为 Python 71、Rust 17、Frontend 32 | 已把 README 更新为 71/17/32，并新增 `scripts/collect-test-baseline.ps1` 便于本地发现后续漂移；后续每次测试基线变化都必须同步 | P1 已修复，持续同步 |
| README 验证结果曾经过期 | 初始 README 写 Agent eval 67/67、Python 780；最终基线为 Agent eval 87/87、Python 823、frontend 211 | 已把 README 更新为 Agent eval 87/87、Python 823、frontend build passed、`verify-mvp.ps1` passed 等当前基线；后续发布前必须重新跑验证并同步结果 | P1 已修复，持续同步 |
| GitHub Actions 未跑 Rust/Tauri | 初始 `.github/workflows/ci.yml` 只跑 frontend、Python、agent eval；Rust 只在本地 `verify-mvp.ps1` 中跑 | 已新增 Windows `rust` job，包含 Tauri 测试资源准备、`cargo fmt --check`、`cargo test --manifest-path src-tauri/Cargo.toml` | P0 已修复 |
| 桌面 E2E 缺自动化 | 现有测试覆盖 controller/API/序列化，缺真实 Tauri 窗口端到端脚本 | README 中“桌面工作台闭环”主要靠人工和局部测试证明 | P0 |
| Agent model-loop eval 仍浅 | 初始 deterministic eval 有 68 条且 `model_loop` 只有 1 条 scripted case | 已扩展为 87 条 deterministic eval，其中 `model_loop` 12 条覆盖工具调用、错误、预算、权限和脱敏观察 | P1 已修复 |
| Runtime 主线仍有兼容路径 | `/agent/message` 已进入 `AgentRuntimeEngine`，但 `run_from_state()` 仍调用 legacy router；图运行仍直接走 `run_graph_events()` | README 中“Runtime Mainline”容易被误读为完全新内核接管 | P1 |

## 2. 测试目标

本轮测试不只判断“测试是否通过”，而是回答四个问题：

1. README 声称的功能是否有真实实现入口。
2. 每个实现入口是否至少有一层自动化测试保护。
3. Agent 的路由、规划、工具调用、权限、记忆、trace、checkpoint、恢复是否有可重复验证的逻辑测试。
4. 对需要本地模型、联网、桌面窗口、ASR 模型、外部 MCP 的能力，是否有明确的手动验证步骤和可替代 mock 自动化。

## 3. 测试分层

| 层级 | 范围 | 目标 | 必跑时机 |
| --- | --- | --- | --- |
| L0 静态一致性 | README、版本号、manifest、配置、lockfile、CI 脚本 | 防止文档领先或落后于真实能力 | 每次发布前 |
| L1 单元测试 | Python/Rust/TS 单模块 | 锁住纯逻辑、序列化、错误处理、redaction | 每次 PR |
| L2 集成测试 | sidecar API、tool gateway、execution graph、Tauri command helpers | 验证跨模块契约 | 每次 PR |
| L3 deterministic Agent eval | router/planner/tool/research/security/model_loop JSONL | 验证 Agent 逻辑不依赖真实模型也能回归 | 每次 PR |
| L4 桌面 E2E | Tauri 窗口、工程文件、偏好、流程运行、artifact UI | 验证用户真实路径 | 每个候选版本 |
| L5 外部依赖验证 | llama.cpp、Brave/DDG、Open-Meteo、Qwen ASR、MCP stdio、Typst | 验证真实环境闭环 | 每个候选版本，或相关功能改动后 |
| L6 压力与韧性 | cancel/resume、并发 run、长文档、慢网络、模型失败、权限拒绝 | 找 Agent 运行时边界 bug | 每个大版本 |

## 4. README 声明核验矩阵

| README 功能声明 | 当前实现证据 | 自动化覆盖 | 缺口/建议 |
| --- | --- | --- | --- |
| `.alita` 工程创建、打开、保存，保存聊天/附件/图/历史/artifact | `src-tauri/src/project.rs`，`src/features/project` | `src-tauri/tests/project_tests.rs`，`src/features/project/*.test.tsx` | 增加桌面 E2E：真实保存、重启、重新打开后 UI 状态一致 |
| Tauri 桌面窗口运行完整工作台 | `src-tauri/src/lib.rs`，`scripts/dev-desktop.ps1` | Rust sidecar/window 配置测试，MVP 手动文档 | CI 未启动真实 Tauri 窗口；发布前必须手动或自动截图验证 |
| 本地 `llama.cpp` GGUF Agent 模型 | `src-tauri/src/llama_runtime.rs`，`python/agent_service/model_client.py` | Rust runtime tests，Python model client tests | 增加 fake llama server E2E：启动、注册 session、聊天、停止后端口释放 |
| 模型调用策略切换 | `python/agent_service/model_policy.py`，`model_runtime.py` | `python/tests/test_model_policy.py`，`test_model_client.py` | 加 eval case 验证不同 intent 使用预期 policy |
| Agent intent 路由 | `python/agent_service/intent.py`，`graph.py`，`router_v2.py` | `test_intent.py`，`test_router_v2.py`，router eval 15 条 | 继续扩充真实任务集，尤其混合文档+联网+缺输入 |
| 天气工具 Open-Meteo | `tool_providers/weather.py` | `test_weather_provider.py`，tool eval | 加网络超时、隐私拦截、城市歧义的 integration mock |
| Brave + DuckDuckGo 搜索链 | `tool_providers/web_search.py`，`web_search.py` | `test_web_provider_chain.py`，`test_web_search.py` | 加 release 手动：无 Brave key fallback、有 key Brave、provider timeout |
| 复杂联网研究流程 | `web_research.py`，`flow_templates/research.py`，`execution.py` | `test_web_research.py`，`test_flow_templates.py`，research eval 10 条 | 加端到端 artifact 内容检查：citation、claim/evidence、partial output |
| 文档处理任务节点图 | `task_planner.py`，`graph_compiler.py`，`flow_templates/document.py` | `test_task_planner.py`，`test_graph_compiler.py`，`test_execution.py` | 加真实 docx/pdf/xlsx 样本文档回归集 |
| Markdown/Typst/PDF artifact | `python/tools/document_tool.py`，`typst_tool.py` | `test_document_tool.py`，`test_typst_tool.py`，artifact preview tests | Typst CLI 真实安装路径需纳入 L5 验证 |
| 显式 authority context 和高风险能力默认不自动批准 | `authority.py`，`permission_gate.py`，`tool_gateway.py` | `test_authority.py`，`test_permission_gate.py`，security eval 24 条 | 加 UI E2E：pending permission 显示、拒绝、批准后继续 |
| manifest `entrypoint` 工具运行时 | `tool-packages/*/manifest.json`，`tool_registry.py`，`tool_execution.py` | `test_tool_manifest_tests.rs`，`test_tool_execution.py` | 加 manifest schema snapshot，防止新增工具漏字段 |
| checkpoint 和指定 checkpoint resume | `runtime_loop.py`，`run_journal.py`，`runtime_store.py`，`execution.py` | `test_run_journal.py`，`test_runtime_store.py`，`test_execution.py` | 增加真实 run 中断后指定 checkpoint resume 的端到端验证 |
| 低风险失败补丁自动继续 | `replan.py`，`execution.py` | `test_replan.py`，`test_execution.py` | 加 eval：失败 -> recovery proposal -> once-only continue -> final |
| 项目 memory 读取/写回 | `memory_store.py`，`context_manager.py`，`execution.py` | `test_memory_store.py`，`test_context_manager.py`，`test_execution.py` | 加 UI/文件级验收：重复 run 不无限写、过期 memory 不进入 context |
| claim/evidence 记录 | `research_evidence.py` | `test_research_evidence.py`，research eval | 加真实研究报告 markdown 中 citation 映射检查 |
| 本地 Agent 模型和 ASR 模型偏好 | `src-tauri/src/preferences.rs`，`src/features/preferences` | Rust preferences tests，frontend preferences tests | 加真实 keyring smoke，确认 API key 不落入偏好和工程文件 |
| Qwen ASR 录音转写 | `src/features/voice`，`src-tauri/src/asr.rs`，`python/agent_service/asr.py` | voice frontend tests，Rust asr tests，Python asr tests | 真实 Qwen3-ASR 模型属于 L5 手动/夜间验证 |
| Artifact 预览和打开定位 | `src/features/artifacts`，`src-tauri/src/commands.rs` | artifact preview tests，artifact open Rust tests | 加浏览器/桌面截图验证 PDF、图片、视频、Markdown 都可见 |
| MCP provider 接入 | `mcp_client_factory.py`，`tool_providers/mcp.py` | `test_mcp_client_factory.py`，`test_mcp_tool_provider.py` | 当前 stdio 最小闭环有测试；HTTP transport 仍返回 unsupported，README 应避免暗示全 MCP transport 完成 |
| Runtime observability events | `runtime_trace.py`，`trace_store.py`，`src/features/task/useGraphRuntimeController.ts` | trace/store/execution tests，frontend controller tests | README 已说明完整 UI 仍需后续补齐；增加 UI 筛选/查看 E2E |

## 5. 自动化门禁

### 5.1 PR 快速门禁

每个 PR 必跑：

```powershell
git diff --check
npm run frontend:typecheck
npm run frontend:test
Push-Location python; python -m pytest -q; Pop-Location
npm run agent:eval
```

期望：

- `git diff --check` 无输出。
- frontend 32 个 test files / 211 tests 通过，除非本 PR 增加测试。
- Python 823 tests 通过，除非本 PR 增加测试。
- Agent eval 87/87 通过，除非本 PR 增加 eval case。

### 5.2 桌面/Rust 门禁

每个涉及 `src-tauri`、桌面启动、工程文件、偏好、模型、sidecar、ASR、artifact open 的 PR 必跑：

```powershell
Push-Location src-tauri
cargo fmt --check
Pop-Location
cargo test --manifest-path src-tauri/Cargo.toml
```

当前 GitHub Actions 已新增 Windows `rust` job，执行 Rust 格式检查、准备 Tauri 测试资源，并运行 Rust/Tauri 测试：

```yaml
rust:
  runs-on: windows-latest
  steps:
    - uses: actions/checkout@v4
    - uses: dtolnay/rust-toolchain@stable
      with:
        targets: x86_64-pc-windows-msvc
    - name: Rust format
      working-directory: src-tauri
      run: cargo fmt --check
    - name: Prepare Tauri test resources
      shell: pwsh
      run: |
        New-Item -ItemType Directory -Force -Path src-tauri/binaries
        New-Item -ItemType File -Force -Path src-tauri/binaries/alita-agent-sidecar-x86_64-pc-windows-msvc.exe
        New-Item -ItemType Directory -Force -Path src-tauri/resources/llama-cpp
    - name: Rust tests
      run: cargo test --manifest-path src-tauri/Cargo.toml
```

### 5.3 Release 全量门禁

每个候选版本必须跑：

```powershell
.\scripts\verify-mvp.ps1
npm run frontend:test
npm run frontend:build
```

Release manager 还要保存以下证据：

- 命令输出摘要。
- 当前 commit hash。
- `git status --short`。
- 真实桌面窗口截图。
- 至少一个 `.alita` 工程保存/重新打开样本。
- 至少一个 artifact 预览截图。

## 6. 功能测试方案

### 6.1 工程文件和桌面工作台

自动化：

- Rust：`.alita` schema、保存/读取、缺失附件 warning、run history/artifact refs。
- Frontend：ProjectHome、projectApi、useProjectController。

手动/E2E：

1. 启动 `npm run desktop:dev`。
2. 新建 `D:\Temp\alita-smoke\v035.alita`。
3. 发送普通聊天，确认聊天区新增消息。
4. 添加附件并生成节点图。
5. 保存工程，关闭窗口，重新启动。
6. 打开工程，确认聊天、附件引用、节点图、运行历史、artifact refs 都恢复。
7. 删除原附件后重新打开，确认缺失附件 warning 出现。

失败记录必须包含：工程文件、sidecar 日志、前端 console、`runHistory` JSON。

### 6.2 聊天与模型配置

矩阵：

| 场景 | 预期 |
| --- | --- |
| 未配置本地模型 | 回复明确提示模型未启用，不崩溃 |
| 配置 fake llama server | `/agent/message` 返回模型文本 |
| API provider 缺 key | UI/sidecar 返回安全错误，不泄露 key |
| API provider endpoint 改变 | 旧 key 不复用，要求重新输入 |
| 模型请求遇到 unsupported field | client 降级重试 |
| stream endpoint | SSE 顺序正确，runtime control event 不暴露到 public stream |

补测建议：

- 增加 fake OpenAI-compatible server，覆盖 chat completions、stream、400 unsupported field、超时、断流。
- 增加 Agent eval case 验证 intent -> policy 映射。

### 6.3 文档处理闭环

样本集：

| 文件 | 用途 |
| --- | --- |
| `sample-note.md` | 纯 Markdown 转报告 |
| `sample-report.docx` | MarkItDown 文档解析 |
| `sample-table.xlsx` | 表格内容抽取 |
| `sample-slide.pptx` | 幻灯片内容抽取 |
| `sample-large.pdf` | 大文件、分页、超时 |
| `sample-corrupt.docx` | 解析失败路径 |

测试步骤：

1. 无附件发送“帮我整理成报告”，预期 `missing_input`。
2. 添加样本文档，发送“整理成中文报告并导出 PDF”。
3. 验证生成节点：document input、parse、organize、report、typst/export、output。
4. 运行流程。
5. 验证每个节点状态、lastRun、artifactRefs、runtimeNotice。
6. 打开 Markdown/PDF artifact，确认内容非空。
7. 禁用 MarkItDown 工具，重跑，预期 `tool_disabled`。

自动化缺口：

- 目前有大量 execution 单测，但缺真实多格式样本文档的端到端 golden output。
- 建议新增 `python/tests/fixtures/documents/`，将生成 artifact 的关键文本做 snapshot。

### 6.4 联网搜索、天气和研究

自动化：

- Weather provider mock：城市、forecast/current、错误。
- Web provider chain：Brave skip、DDG fallback、timeout、privacy guard。
- Research eval：query plan、source review、citation。

手动：

1. 无 Brave key：搜索“今天上海天气怎么样”，预期走 weather 而非泛搜索。
2. 无 Brave key：搜索当前版本问题，预期 DuckDuckGo fallback。
3. 配置 Brave key：确认 Brave provider 被调用。
4. 复杂问题选择 quick answer，确认直接返回来源摘要。
5. 复杂问题选择 research flow，确认生成 9 步研究节点图并产出 Markdown artifact。

补测建议：

- 对外部网络测试必须区分 `mock gate` 和 `live smoke`。PR 只跑 mock，release 跑 live smoke。
- Research flow 应增加 evidence JSON 与 Markdown citation 的一致性断言。

### 6.5 Artifact 预览

覆盖对象：

- text/Markdown
- PDF
- image
- audio
- video
- reveal in file manager
- open with default handler

当前自动化主要验证组件和 Rust command helper。补测：

- 增加 Browser/Playwright 截图：打开 artifact panel，确认预览区域非空。
- 对 PDF worker lazy chunk 做 production build 后验证，避免 dev 下正常、build 后路径错误。

### 6.6 语音输入与 ASR

自动化：

- WAV 编码、audio capture guard、ASR API、Tauri payload、Python ASR service。

手动：

1. 未配置 ASR 模型，语音按钮 disabled 或给出明确提示。
2. 配置 Qwen3-ASR 模型目录。
3. 录制 3 秒中文语音。
4. 预期转写文本进入聊天框。
5. 连续点击录音，确认不会并发启动多个转写。
6. 使用超大音频，确认前后端都拒绝并返回安全错误。

补测建议：

- ASR 属于可选依赖，CI 不应下载真实模型；用 fake ASR service 覆盖 UI 端到端。
- Release 需要真实模型 smoke，记录首次加载耗时和内存峰值。

## 7. Agent 逻辑测试方案

### 7.1 Intent router

必须覆盖：

- 普通聊天。
- 本地问答。
- 简单联网事实。
- 天气。
- 复杂研究选择。
- 复杂研究流程。
- 文档任务。
- 缺输入。
- 混合需求：文档 + 研究、联网 + 导出、任务 + 权限。

当前 router eval 已从 10 条扩到 15 条；后续建议继续扩到 30 条，并保持中文真实表达、混合任务和缺输入场景覆盖。

### 7.2 Planner 和 Tool DAG

必须覆盖：

- 文档模板生成。
- 研究模板生成。
- schema-compatible 多工具 DAG。
- required args 缺失。
- output/input type 不兼容。
- disabled tool。
- tool manifest 缺字段。
- tool operation 选择错误。

当前 planner eval 已从 13 条扩到 16 条；后续建议继续扩到 25 条，并加入：

- `read document -> summarize -> typst compile -> output`
- `web search -> source review -> report synthesize`
- `mcp echo -> transform -> output`
- incompatible schema rejection

### 7.3 Unified Tool Gateway 和权限

必须覆盖：

- authority allow/deny。
- runtime budget 传入 provider。
- provider timeout。
- internal tool。
- MCP stdio tool。
- artifact path boundary。
- secret redaction。
- disabled tool 在执行前拦截。
- failure policy -> replan suggestion。

重点 bug 排查：

- 任意错误消息不得包含 API key、本地绝对路径、完整 prompt。
- 拒绝权限后不得继续执行工具。
- approval fingerprint 不匹配必须拒绝。

### 7.4 Runtime state、checkpoint、resume

必须覆盖：

- `/agent/message` 进入 `AgentRuntimeEngine`。
- `RuntimeStateDelta` 持久化。
- checkpoint id 唯一且可指定恢复。
- latest checkpoint resume。
- 指定 checkpoint id resume。
- resume 后 action/observation 不重复。
- 中断后继续不会丢 artifact refs。
- 失败恢复只自动继续一次。

当前风险：

- message entry 已接入 RuntimeEngine，但 public event 会过滤 `runtime.run_started` 和 `runtime.state_delta`。
- graph run stream 仍直接调用 `run_graph_events()`，需要测试证明这是兼容路径，而不是误认为全部 runtime 已统一。

### 7.5 ReAct 和 model loop

初始 deterministic eval 只有 1 条 `model_loop` case；当前已扩展为 12 条 scripted model-loop case，覆盖以下核心路径：

| Case | 预期 |
| --- | --- |
| tool then final | 一次工具调用后最终回答 |
| two tools then final | 两次工具调用顺序正确 |
| unknown tool | 返回 `tool_not_allowed` 或等价错误 |
| malformed JSON action | 触发 parse error，不执行工具 |
| tool budget exceeded | 停止继续工具调用 |
| step budget exceeded | 返回 bounded failure |
| tool returns error | observation 进入模型下一步 |
| model final immediately | 不调用工具 |
| permission denied | 不调用工具 |
| redacted observation | observation 不泄露 secret |
| permission allowed | 允许的权限路径可执行并返回最终回答 |
| explicit empty permissions | 显式空权限列表拒绝需要权限的工具 |

### 7.6 Memory

必须覆盖：

- 规划前读取项目 memory。
- 成功 tool outcome 写入。
- 失败 tool outcome 写入。
- artifact summary 写入。
- upsert/dedupe。
- expires_at 过滤。
- last_used_at 更新。
- 用户禁用/删除 memory 后不进入 context。

UI 缺口：

- README 已承认 memory 管理 UI 是后续增强。测试文档要求在 UI 未完成前，memory 功能只标注为 runtime/backend 能力，不标注为完整用户可治理能力。

### 7.7 Trace 和 observability

必须覆盖 span 类型：

- `runtime.node`
- `model.call`
- `tool.call`
- `planner.call`
- `memory.search`
- `memory.write`
- authority decision
- recovery action

断言：

- trace 文件存在。
- span 有 runId/threadId/checkpointId 或可关联字段。
- metadata 只保存摘要、计数、hash、状态，不保存 secret、完整 prompt、完整文件内容。
- frontend controller 能 reduce checkpoint、span、authority、recovery events。

## 8. 错误与 bug 排查清单

每次发现 Agent 错误，按此顺序排查：

1. 复现输入：用户消息、附件、工程路径、模型配置、工具开关。
2. 分类：router、planner、model、tool、authority、execution、artifact、memory、trace、frontend。
3. 收集证据：sidecar stdout/stderr、SSE event、run journal、trace jsonl、`.alita` 工程片段、artifact refs。
4. 判断是否为文档漂移：README 是否声称该能力已完整支持。
5. 写最小失败测试：优先 Python unit/integration，其次 frontend/Rust，外部依赖使用 fake provider。
6. 修复或降级文档：如果能力没有完成，README 必须写成限制或路线，而不是完成能力。
7. 加 eval case：如果是 Agent 决策错误，必须进入 JSONL eval。

Bug 报告模板：

```text
标题：
版本：
复现步骤：
期望结果：
实际结果：
是否 README 声称能力：
影响范围：
错误分类：
附件/工程：
runId/threadId：
checkpointId：
trace 文件：
最小失败测试：
建议优先级：
```

## 9. 推荐新增测试任务

### P0

1. 在 GitHub Actions 增加 Rust/Tauri job。
2. 建立桌面 E2E smoke：启动窗口、新建工程、保存、重启、打开、跑一次 fake graph。
3. 建立 fake model server，覆盖本地/API 模型聊天和 stream。

README 测试数量和验证结果的初始漂移已在 Phase 1 worktree 修正；后续不再作为未完成 P0 任务，只需要随 `scripts/collect-test-baseline.ps1` 和发布前验证结果持续同步。

### P1

1. model-loop eval 从 1 条扩到至少 12 条。
2. 加真实文档 fixture 和 artifact golden output。
3. 增加 checkpoint resume 端到端测试。
4. 增加 research report citation/evidence 一致性测试。
5. 增加 API key/keyring redaction 的 release smoke。
6. 增加 artifact preview build 后截图验证。

### P2

1. 增加长文档、大 artifact、慢网络、取消/恢复压力测试。
2. 增加 MCP stdio 进程异常退出、超时、stderr 噪声、schema 变化测试。
3. 增加 sandbox 子进程树、网络逃逸、环境变量泄露测试。
4. 增加 memory UI 治理测试，等 UI 功能完成后启用。

## 10. 发布验收标准

一个版本可以标记为可发布，必须满足：

1. PR 快速门禁全部通过。
2. Release 全量门禁全部通过。
3. README 中每个“可以”声明都能映射到至少一个自动化测试或明确的手动 release smoke。
4. README 中未完成能力必须出现在“当前限制”，不能放在“已实现能力”。
5. Agent eval 失败数为 0。
6. 桌面 E2E smoke 有截图和工程文件证据。
7. 外部依赖能力按 mock/live 分层记录，不把 live 网络失败误判为核心逻辑失败。
8. 任何 P0/P1 bug 必须修复或在 README/发行说明中降级说明。

## 11. 本轮已确认的事实

- 当前仓库版本配置为 `0.35.1`：`package.json`、`python/pyproject.toml`、`src-tauri/Cargo.toml`、`src-tauri/tauri.conf.json`。
- `src-tauri/Cargo.lock` 中本项目包版本已同步为 `0.35.1`，这是版本一致性修正。
- 当前测试文件数量：Python 71、Rust/Tauri 17、Frontend 32。
- 当前 deterministic eval case 数量：router 15、planner 16、tool 10、research 10、security 24、model_loop 12，共 87。
- 当前 CI 覆盖 frontend、Python tests、agent eval 与 Rust/Tauri。
- `verify-mvp.ps1` 增加前端生产构建，并在本机通过，说明 Windows Build Tools、sidecar binary、llama-cpp resource dir、Rust toolchain 当前可用。

## 12. 后续执行顺序

本轮测试实施已经按以下顺序落地；后续版本应沿用该顺序维护测试基线：

1. 保持 README 与 `scripts/collect-test-baseline.ps1` 输出及发布前验证结果同步；初始 README 漂移已在 Phase 1 worktree 修正。
2. 保持 CI 的 Rust/Tauri job 与本地 `verify-mvp.ps1` 一致。
3. 维护 fake model server 测试和 release smoke checklist。
4. 随 Agent loop 变化扩展 model-loop eval。
5. 维护文档 fixture/artifact golden 测试。
6. 维护 checkpoint resume 和 research evidence 端到端测试。
7. 维护 `docs/test-traceability/alita-v035-feature-test-map.md`，随新增测试和 release smoke 文档补齐真实测试 ID 与 smoke 证据。
