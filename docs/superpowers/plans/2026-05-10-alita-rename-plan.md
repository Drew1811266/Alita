# Alita Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将软件、工程格式、构建配置、sidecar、环境变量、文档和最终项目目录统一命名为 Alita，并保留Alita 工程与 Alita 环境变量。

**Architecture:** 先改行为边界和测试，再改源码命名。新名称使用 `Alita/alita/ALITA`，不再保留旧命名 fallback。生成目录不手动修改，由测试和构建刷新。

**Tech Stack:** React + TypeScript + Vitest, Tauri 2 + Rust, Python FastAPI/LangGraph sidecar, PowerShell scripts.

**Repo Note:** 当前 `D:\Software Project\Alita` 不是 git 仓库，`git status` 会失败。因此本计划中的检查点不执行 git commit，只运行对应验证命令并记录变更。

---

## File Structure

- Modify: `package.json`  
  前端包名改为 `alita`。

- Modify: `src-tauri/Cargo.toml`  
  Rust crate、lib name、描述和作者改为 Alita。

- Modify: `src-tauri/tauri.conf.json`  
  产品名、identifier、窗口标题、externalBin 改为 Alita。

- Modify: `src-tauri/src/project.rs`, `src/shared/types.ts`, `src-tauri/src/commands.rs`, `src/app/App.tsx`, `src/features/project/projectApi.ts`  
  工程类型改为 `AlitaProject`，新扩展名 `.alita`，旧 `.alita` 继续读取。

- Modify: `src-tauri/src/preferences.rs`, `src-tauri/src/llama_runtime.rs`, `src-tauri/src/sidecar.rs`, `src-tauri/src/agent_client.rs`  
  默认产品命名、环境变量和 token header 改为 Alita，并保留 Alita fallback。

- Modify: `python/agent_service/app.py`, `python/agent_service/model_client.py`, `python/agent_service/graph.py`, `python/agent_service/__init__.py`  
  FastAPI 标题、env/header、系统提示、用户可见名称改为 Alita。

- Modify: `scripts/build-sidecar.ps1`, `scripts/dev-desktop.ps1`, `scripts/install-llama-cpp.ps1`, `scripts/build-windows-app.ps1`, `scripts/verify-mvp.ps1`  
  sidecar 二进制命名、进程名、文档化 env 改为 Alita。

- Rename/Create: `python/alita-agent-sidecar.spec`  
  用新的 PyInstaller spec 替换旧 `python/alita-agent-sidecar.spec`。

- Rename/Create binary: `src-tauri/binaries/alita-agent-sidecar-x86_64-pc-windows-msvc.exe`  
  由 sidecar 构建脚本生成；旧二进制不再被 Tauri 引用。

- Modify tests: `src/**/*.test.*`, `src-tauri/tests/*.rs`, `python/tests/*.py`  
  测试更新为 Alita 新行为，并新增 legacy 兼容断言。

- Modify docs: `docs/mvp-verification.md`, `docs/windows-desktop-runbook.md`, active specs/plans  
  当前运行文档改为 Alita；历史计划文档可以保留历史记录，但验收扫描要排除旧历史计划或标注为 legacy。

## Task 1: 前端工程文件与显示名称

**Files:**
- Modify: `src/shared/types.ts`
- Modify: `src/features/project/projectApi.ts`
- Modify: `src/features/project/ProjectHome.tsx`
- Modify: `src/app/App.tsx`
- Modify: `src/features/project/ProjectHome.test.tsx`
- Modify: `src/app/App.test.tsx`

- [ ] **Step 1: Write failing frontend tests**

Update assertions so project home expects `Alita`, recent project examples use `.alita`, and project API dialog filters prefer `alita`.

Run:

```powershell
npm run frontend:test -- src/features/project/ProjectHome.test.tsx src/app/App.test.tsx
```

Expected: tests fail while production code still contains Alita and `.alita`.

- [ ] **Step 2: Implement frontend rename**

Rename TypeScript type `AlitaProject` to `AlitaProject`. Change create/open/save prompts and filters:

- Default file: `未命名工程.alita`
- Filter: `Alita 工程`
- Extensions for open: `["alita", "Alita"]`
- Extensions for save/create: `["alita"]`
- Name extraction removes `.alita` and `.alita`.

- [ ] **Step 3: Verify frontend task**

Run:

```powershell
npm run frontend:test -- src/features/project/ProjectHome.test.tsx src/app/App.test.tsx
npm run frontend:lint
```

Expected: exit code 0.

## Task 2: Rust 工程格式与偏好设置兼容

**Files:**
- Modify: `src-tauri/src/project.rs`
- Modify: `src-tauri/src/commands.rs`
- Modify: `src-tauri/src/preferences.rs`
- Modify: `src-tauri/tests/project_tests.rs`
- Modify: `src-tauri/tests/preferences_tests.rs`

- [ ] **Step 1: Write failing Rust tests**

Update tests so new project examples use `.alita`, temp save file uses `.alita.tmp`, and a legacy `.alita` fixture still opens.

Run:

```powershell
cd src-tauri
cargo test project_tests preferences_tests
```

Expected: tests fail before implementation.

- [ ] **Step 2: Implement Rust project rename**

Rename Rust type `AlitaProject` to `AlitaProject`. Keep JSON fields unchanged. Change error strings from `.alita` to `.alita` where they describe the current format, and explicitly mention legacy `.alita` only in compatibility paths.

- [ ] **Step 3: Verify Rust project task**

Run:

```powershell
cd src-tauri
cargo test project_tests preferences_tests
```

Expected: exit code 0.

## Task 3: Tauri 产品名、crate 名、sidecar 二进制

**Files:**
- Modify: `package.json`
- Modify: `src-tauri/Cargo.toml`
- Modify: `src-tauri/tauri.conf.json`
- Modify: `src-tauri/src/sidecar.rs`
- Modify: `scripts/build-sidecar.ps1`
- Rename: `python/alita-agent-sidecar.spec` to `python/alita-agent-sidecar.spec`
- Modify: `src-tauri/tests/sidecar_tests.rs`

- [ ] **Step 1: Write failing tests/config checks**

Update sidecar tests to expect `alita-agent-sidecar` and `ALITA_SIDECAR_TOKEN`.

Run:

```powershell
cd src-tauri
cargo test sidecar_tests
```

Expected: tests fail before implementation.

- [ ] **Step 2: Implement product and sidecar rename**

Set:

- package name: `alita`
- Cargo package name: `alita`
- Cargo lib name: `alita_lib`
- Tauri productName/title: `Alita`
- Tauri identifier: `com.alita.ai-workbench`
- Tauri externalBin: `binaries/alita-agent-sidecar`
- packaged sidecar: `alita-agent-sidecar`

- [ ] **Step 3: Verify sidecar task**

Run:

```powershell
cd src-tauri
cargo test sidecar_tests
```

Expected: exit code 0.

## Task 4: Env/Header 迁移兼容

**Files:**
- Modify: `src-tauri/src/llama_runtime.rs`
- Modify: `src-tauri/src/agent_client.rs`
- Modify: `python/agent_service/app.py`
- Modify: `python/agent_service/model_client.py`
- Modify: `src-tauri/tests/llama_runtime_tests.rs`
- Modify: `src-tauri/tests/agent_client_tests.rs`
- Modify: `python/tests/test_app.py`
- Modify: `python/tests/test_model_client.py`

- [ ] **Step 1: Write failing compatibility tests**

Tests must prove:

- New `ALITA_LLAMA_MODEL_PATH` is read.
- Old `ALITA_LLAMA_MODEL_PATH` remains fallback.
- New `X-Alita-Sidecar-Token` is sent.
- Python accepts both new and legacy token headers.

Run:

```powershell
cd src-tauri
cargo test llama_runtime_tests agent_client_tests
cd ..\python
python -m pytest tests/test_app.py tests/test_model_client.py
```

Expected: tests fail before implementation.

- [ ] **Step 2: Implement compatibility layer**

Use helper functions for env lookup:

- Rust: read `ALITA_*` first, then `Alita_*`.
- Python: read `ALITA_*` first, then `Alita_*`.
- Header send: Rust sends `X-Alita-Sidecar-Token`.
- Header receive: Python accepts `X-Alita-Sidecar-Token`; if missing, accepts `X-Alita-Sidecar-Token`.

- [ ] **Step 3: Verify env/header task**

Run:

```powershell
cd src-tauri
cargo test llama_runtime_tests agent_client_tests
cd ..\python
python -m pytest tests/test_app.py tests/test_model_client.py
```

Expected: exit code 0.

## Task 5: Python Agent 用户可见名称

**Files:**
- Modify: `python/agent_service/__init__.py`
- Modify: `python/agent_service/app.py`
- Modify: `python/agent_service/graph.py`
- Modify: `python/tests/test_graph.py`

- [ ] **Step 1: Write failing Python tests**

Update graph tests to expect assistant/system text containing `Alita` instead of `Alita AI 工作台`.

Run:

```powershell
cd python
python -m pytest tests/test_graph.py
```

Expected: tests fail before implementation.

- [ ] **Step 2: Implement Python visible rename**

Change FastAPI title and all assistant-facing prompts/messages to Alita while keeping behavior unchanged.

- [ ] **Step 3: Verify Python Agent task**

Run:

```powershell
cd python
python -m pytest tests/test_graph.py
```

Expected: exit code 0.

## Task 6: 脚本和文档

**Files:**
- Modify: `scripts/build-sidecar.ps1`
- Modify: `scripts/dev-desktop.ps1`
- Modify: `scripts/build-windows-app.ps1`
- Modify: `scripts/verify-mvp.ps1`
- Modify: `scripts/install-llama-cpp.ps1`
- Modify: `docs/windows-desktop-runbook.md`
- Modify: `docs/mvp-verification.md`

- [ ] **Step 1: Update scripts**

Replace process/binary/env names in scripts with Alita names. Any process-stop lists should include old Alita process names only as legacy cleanup entries.

- [ ] **Step 2: Update active docs**

Current user-facing docs should say `Alita`, `.alita`, `ALITA_*`, and `alita-agent-sidecar`.

- [ ] **Step 3: Verify docs/scripts scan**

Run:

```powershell
rg -n "Alita|Alita|Alita|\.alita" docs scripts src src-tauri python --glob '!src-tauri/target/**' --glob '!python/build/**' --glob '!python/dist/**' --glob '!**/__pycache__/**'
```

Expected: remaining hits are only explicit legacy compatibility references.

## Task 7: Full verification and directory rename

**Files:**
- All modified source files
- Directory: `D:\Software Project\Alita`

- [ ] **Step 1: Run full tests**

Run:

```powershell
npm run frontend:test
npm run frontend:lint
cd src-tauri
cargo test
cd ..\python
python -m pytest
```

Expected: exit code 0 for each command.

- [ ] **Step 2: Rebuild sidecar**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-sidecar.ps1
```

Expected: `src-tauri\binaries\alita-agent-sidecar-x86_64-pc-windows-msvc.exe` exists.

- [ ] **Step 3: Build desktop app**

Run:

```powershell
npm run desktop:build
```

Expected: Alita installer/build output is generated.

- [ ] **Step 4: Rename physical project directory**

Stop running Alita/Alita dev processes, then from parent directory run:

```powershell
Rename-Item -LiteralPath "D:\Software Project\Alita" -NewName "Alita"
```

Expected: project path becomes `D:\Software Project\Alita`.

- [ ] **Step 5: Start app from new directory**

Run:

```powershell
cd "D:\Software Project\Alita"
powershell -ExecutionPolicy Bypass -File scripts/dev-desktop.ps1
```

Expected: desktop window title is `Alita`; new project uses `.alita`; old `.alita` can still be opened.


