# Alita Rename Regression Test Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify that the full project and software rename to `Alita` did not break any project-owned user workflows, runtime services, persisted settings, generated artifacts, or packaged outputs.

**Architecture:** Test in layers: static naming checks, automated suites, packaged build, runtime processes, persisted preferences, project file lifecycle, Agent chat, document workflow execution, and restart persistence. Use current release binaries for smoke tests and automated suites for regression coverage. Preserve the user's current AppData configuration before any stateful test.

**Tech Stack:** Tauri 2, Rust, React, TypeScript, Vite, Python FastAPI sidecar, PyInstaller, llama.cpp, PowerShell, Vitest, pytest, cargo test.

---

## Scope

This plan verifies rename-related breakage in:

- App identity: window title, Tauri product name, app identifier, executable, sidecar, installer.
- Persistent configuration: `%APPDATA%\com.alita.ai-workbench\preferences.json`, `%LOCALAPPDATA%\com.alita.ai-workbench\models`, recovered default model, recent projects.
- Project files: `.alita` create, save, save-as, open, reject non-Alita extension.
- Runtime services: packaged `alita-agent-sidecar.exe`, `llama-server.exe`, ports `8765` and `8766`.
- Agent workflows: plain chat, streamed fallback behavior, attachment-driven graph generation, graph execution, artifact creation, tool disabled failure, retry/cancel controls.
- Generated outputs and docs: scanner coverage across source and generated project-owned files.

Out of scope:

- Rewriting product behavior unrelated to the rename.
- Benchmarking model quality.
- Installing the NSIS package system-wide unless the user explicitly approves that separate step.

## Evidence Directory

Use this directory for command outputs and screenshots:

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$evidenceRoot = "D:\Software Project\Alita\docs\test-results\rename-regression-$stamp"
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
"Evidence: $evidenceRoot"
```

Expected: a new `docs\test-results\rename-regression-<timestamp>` directory exists.

## Safety Rules

- Before changing AppData, copy current Alita preferences.
- Before closing processes, record current `alita`, `alita-agent-sidecar`, and `llama-server` PIDs.
- Do not delete the user's `models` directory.
- Use temporary project files under `%TEMP%\alita-rename-regression`.
- If a command fails, stop that task, save the output, and record the exact failure.

---

### Task 1: Preflight and AppData Backup

**Files:**
- Read: `package.json`
- Read: `src-tauri/tauri.conf.json`
- Read/backup: `%APPDATA%\com.alita.ai-workbench\preferences.json`

- [ ] **Step 1: Create a temp test workspace**

Run:

```powershell
$testRoot = Join-Path $env:TEMP "alita-rename-regression"
New-Item -ItemType Directory -Force -Path $testRoot | Out-Null
$testRoot
```

Expected: command prints a writable temp directory.

- [ ] **Step 2: Capture current process state**

Run:

```powershell
Get-Process -Name alita,alita-agent-sidecar,llama-server -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,MainWindowTitle,Path |
  Tee-Object -FilePath "$evidenceRoot\processes-before.txt"
```

Expected: either no rows, or rows showing currently running Alita-related processes.

- [ ] **Step 3: Backup current Alita preferences**

Run:

```powershell
$prefs = Join-Path $env:APPDATA "com.alita.ai-workbench\preferences.json"
if (Test-Path $prefs) {
  Copy-Item -LiteralPath $prefs -Destination "$evidenceRoot\preferences-before.json" -Force
  Get-Content -Raw $prefs | Tee-Object -FilePath "$evidenceRoot\preferences-before.pretty.json"
} else {
  "No Alita preferences file exists yet." | Tee-Object -FilePath "$evidenceRoot\preferences-before.txt"
}
```

Expected: backup file exists if preferences existed. If not, the note is saved.

- [ ] **Step 4: Confirm model fixture exists**

Run:

```powershell
Get-ChildItem -Path "D:\Software Project\Alita\models" -Filter "*.gguf" -File |
  Select-Object Name,Length,FullName |
  Tee-Object -FilePath "$evidenceRoot\models-before.txt"
```

Expected: at least one `.gguf` model appears. Current expected model is `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf`.

---

### Task 2: Static Rename Integrity

**Files:**
- Test: `scripts/check-alita-rename-clean.ps1`
- Read: `package.json`
- Read: `src-tauri/tauri.conf.json`
- Read: `python/agent_service/app.py`

- [ ] **Step 1: Run source/docs rename scanner**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-alita-rename-clean.ps1 |
  Tee-Object -FilePath "$evidenceRoot\rename-scan-source.txt"
```

Expected:

```text
No forbidden legacy naming tokens found.
```

- [ ] **Step 2: Run generated-output rename scanner**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-alita-rename-clean.ps1 -IncludeGenerated |
  Tee-Object -FilePath "$evidenceRoot\rename-scan-generated.txt"
```

Expected:

```text
No forbidden legacy naming tokens found.
```

- [ ] **Step 3: Check app identity files**

Run:

```powershell
Select-String -Path package.json -Pattern '"name": "alita"','"version": "0.1.0"' |
  Tee-Object -FilePath "$evidenceRoot\package-identity.txt"
Select-String -Path src-tauri\tauri.conf.json -Pattern '"productName": "Alita"','"identifier": "com.alita.ai-workbench"','"title": "Alita"' |
  Tee-Object -FilePath "$evidenceRoot\tauri-identity.txt"
Select-String -Path python\agent_service\app.py -Pattern 'FastAPI\(title="Alita Agent Sidecar"\)','ALITA_SIDECAR_TOKEN','X-Alita-Sidecar-Token' |
  Tee-Object -FilePath "$evidenceRoot\sidecar-identity.txt"
```

Expected: every query returns matching lines.

---

### Task 3: Automated Regression Suites

**Files:**
- Test: `src/**/*.test.ts`
- Test: `src/**/*.test.tsx`
- Test: `python/tests/*.py`
- Test: `src-tauri/tests/*.rs`

- [ ] **Step 1: Run frontend tests**

Run:

```powershell
npm run frontend:test *> "$evidenceRoot\frontend-test.txt"
if ($LASTEXITCODE -ne 0) { Get-Content "$evidenceRoot\frontend-test.txt"; exit $LASTEXITCODE }
Get-Content "$evidenceRoot\frontend-test.txt"
```

Expected: all Vitest files and tests pass.

- [ ] **Step 2: Run frontend typecheck**

Run:

```powershell
npm run frontend:lint *> "$evidenceRoot\frontend-lint.txt"
if ($LASTEXITCODE -ne 0) { Get-Content "$evidenceRoot\frontend-lint.txt"; exit $LASTEXITCODE }
Get-Content "$evidenceRoot\frontend-lint.txt"
```

Expected: command exits `0`.

- [ ] **Step 3: Run Python sidecar tests**

Run:

```powershell
Push-Location python
python -m pytest *> "$evidenceRoot\python-pytest.txt"
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Get-Content "$evidenceRoot\python-pytest.txt"; exit $code }
Get-Content "$evidenceRoot\python-pytest.txt"
```

Expected: all Python tests pass.

- [ ] **Step 4: Run Rust desktop tests**

Run:

```powershell
Push-Location src-tauri
cargo test *> "$evidenceRoot\rust-cargo-test.txt"
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Get-Content "$evidenceRoot\rust-cargo-test.txt"; exit $code }
Get-Content "$evidenceRoot\rust-cargo-test.txt"
```

Expected: all Rust tests pass. Existing dead-code warnings in test-only modules are acceptable if exit code is `0`.

---

### Task 4: Build and Packaged Output Verification

**Files:**
- Build: `dist/`
- Build: `python/dist/`
- Build: `src-tauri/target/release/`
- Build: `src-tauri/target/release/bundle/nsis/`

- [ ] **Step 1: Build frontend**

Run:

```powershell
npm run frontend:build *> "$evidenceRoot\frontend-build.txt"
if ($LASTEXITCODE -ne 0) { Get-Content "$evidenceRoot\frontend-build.txt"; exit $LASTEXITCODE }
Select-String -Path dist\index.html -Pattern '<title>Alita</title>' |
  Tee-Object -FilePath "$evidenceRoot\dist-title.txt"
```

Expected: build exits `0`, and `dist\index.html` has `<title>Alita</title>`.

- [ ] **Step 2: Build desktop package**

Run:

```powershell
npm run desktop:build *> "$evidenceRoot\desktop-build.txt"
if ($LASTEXITCODE -ne 0) { Get-Content "$evidenceRoot\desktop-build.txt"; exit $LASTEXITCODE }
Get-ChildItem src-tauri\target\release\bundle\nsis -Filter "Alita_*_x64-setup.exe" |
  Select-Object Name,Length,FullName |
  Tee-Object -FilePath "$evidenceRoot\nsis-output.txt"
```

Expected: build exits `0`, `alita.exe` exists, and the NSIS setup executable name starts with `Alita_`.

- [ ] **Step 3: Verify packaged sidecar and llama runtime files**

Run:

```powershell
Get-ChildItem src-tauri\target\release -File |
  Where-Object { $_.Name -in @("alita.exe", "alita-agent-sidecar.exe") } |
  Select-Object Name,Length,FullName |
  Tee-Object -FilePath "$evidenceRoot\release-binaries.txt"
Get-ChildItem src-tauri\target\release\llama-cpp -Filter "llama-server.exe" -File |
  Select-Object Name,Length,FullName |
  Tee-Object -FilePath "$evidenceRoot\llama-runtime-binary.txt"
```

Expected: all three binaries are present.

---

### Task 5: Runtime Startup and Process Ownership

**Files:**
- Run: `src-tauri/target/release/alita.exe`
- Read: `%APPDATA%\com.alita.ai-workbench\preferences.json`

- [ ] **Step 1: Stop previous test processes**

Run:

```powershell
Get-Process -Name alita,alita-agent-sidecar,llama-server -ErrorAction SilentlyContinue |
  Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Get-Process -Name alita,alita-agent-sidecar,llama-server -ErrorAction SilentlyContinue |
  Tee-Object -FilePath "$evidenceRoot\processes-after-stop.txt"
```

Expected: no process rows remain.

- [ ] **Step 2: Launch release app**

Run:

```powershell
$exe = Resolve-Path "src-tauri\target\release\alita.exe"
Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe)
Start-Sleep -Seconds 10
Get-Process -Name alita,alita-agent-sidecar,llama-server -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,MainWindowTitle,Path |
  Tee-Object -FilePath "$evidenceRoot\processes-after-launch.txt"
```

Expected:

- `alita.exe` is running.
- main window title is `Alita`.
- `alita-agent-sidecar.exe` is running.
- `llama-server.exe` is running when a default model exists.

- [ ] **Step 3: Verify sidecar health**

Run:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8765/health" -UseBasicParsing -TimeoutSec 5 |
  Select-Object StatusCode,Content |
  Tee-Object -FilePath "$evidenceRoot\sidecar-health.txt"
```

Expected: `StatusCode` is `200`, content is `{"status":"ok"}`.

- [ ] **Step 4: Verify llama.cpp health**

Run:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8766/health" -UseBasicParsing -TimeoutSec 5 |
  Select-Object StatusCode,Content |
  Tee-Object -FilePath "$evidenceRoot\llama-health.txt"
```

Expected: `StatusCode` is `200`, content is `{"status":"ok"}`.

- [ ] **Step 5: Verify runtime command lines use Alita paths**

Run:

```powershell
Get-CimInstance Win32_Process -Filter "name='alita.exe' or name='alita-agent-sidecar.exe' or name='llama-server.exe'" |
  Select-Object ProcessId,ParentProcessId,Name,CommandLine |
  Format-List |
  Tee-Object -FilePath "$evidenceRoot\runtime-command-lines.txt"
```

Expected:

- `alita.exe` command line points to `D:\Software Project\Alita\...`.
- `llama-server.exe` command line includes `--model "D:\Software Project\Alita\models\...gguf"`.
- no command line points to the old project directory.

---

### Task 6: Preferences and Model Configuration

**Files:**
- Read: `%APPDATA%\com.alita.ai-workbench\preferences.json`
- UI: `首选项`

- [ ] **Step 1: Inspect persisted preferences**

Run:

```powershell
Get-Content -Raw "$env:APPDATA\com.alita.ai-workbench\preferences.json" |
  Tee-Object -FilePath "$evidenceRoot\preferences-after-launch.json"
```

Expected:

- `modelStorageDir` points under `%LOCALAPPDATA%\com.alita.ai-workbench\models` unless the user changed it.
- `models` contains at least one `.gguf` entry.
- `defaultModelId` is not `null`.
- default model path points to `D:\Software Project\Alita\models\...gguf`.

- [ ] **Step 2: Open Preferences UI**

Manual:

1. Click `首选项`.
2. Inspect the `模型` section.
3. Inspect the `工具节点` section.

Expected:

- dialog opens without error.
- model list contains the recovered model.
- one model has the `默认模型` badge.
- tool list includes `文档处理工具包` and `MarkItDown 文档转 Markdown`.

- [ ] **Step 3: Toggle a tool and verify persistence**

Manual:

1. In `工具节点`, disable `MarkItDown 文档转 Markdown`.
2. Close preferences.
3. Reopen preferences.
4. Re-enable `MarkItDown 文档转 Markdown`.

Expected:

- disabled state persists after closing and reopening.
- re-enabled state persists after closing and reopening.
- `preferences.json` updates `toolEnablement` for the toggled tool.

- [ ] **Step 4: Verify model actions do not use old names**

Manual:

1. Click `引用外部 GGUF`.
2. Cancel the dialog.
3. Click `扫描模型目录`.
4. Cancel the dialog.

Expected:

- dialogs are titled for GGUF/model directory selection.
- no old product name or old extension is visible.
- cancelling leaves preferences unchanged.

---

### Task 7: Project File Lifecycle

**Files:**
- Create: `%TEMP%\alita-rename-regression\rename-lifecycle.alita`
- Create: `%TEMP%\alita-rename-regression\rename-lifecycle-copy.alita`

- [ ] **Step 1: Create a new project**

Manual:

1. On the home screen, click `新建工程`.
2. Save to `%TEMP%\alita-rename-regression\rename-lifecycle.alita`.

Expected:

- workbench opens.
- top bar shows project name `rename-lifecycle`.
- top bar shows `已保存`.
- file exists with `.alita` extension.

- [ ] **Step 2: Save after a message**

Manual:

1. Send message `你好，请用一句话回复。`
2. Wait for the assistant response or streamed response completion.
3. Click `保存`.

Expected:

- no `本地模型暂未启用` response appears.
- after message, top bar becomes `未保存`.
- after saving, top bar returns to `已保存`.

- [ ] **Step 3: Save As**

Manual:

1. Click `另存为`.
2. Save to `%TEMP%\alita-rename-regression\rename-lifecycle-copy.alita`.

Expected:

- copied project opens.
- top bar shows `rename-lifecycle-copy`.
- file exists with `.alita` extension.

- [ ] **Step 4: Reopen the saved project**

Manual:

1. Close Alita.
2. Reopen Alita.
3. Click `打开工程`.
4. Select `%TEMP%\alita-rename-regression\rename-lifecycle-copy.alita`.

Expected:

- project loads without error.
- chat history is present.
- project path appears in recent projects.

- [ ] **Step 5: Reject non-Alita project extension**

Run:

```powershell
Copy-Item "$env:TEMP\alita-rename-regression\rename-lifecycle-copy.alita" "$env:TEMP\alita-rename-regression\not-alita.txt" -Force
Push-Location src-tauri
cargo test rejects_non_alita_project_extension *> "$evidenceRoot\reject-non-alita-extension.txt"
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Get-Content "$evidenceRoot\reject-non-alita-extension.txt"; exit $code }
Get-Content "$evidenceRoot\reject-non-alita-extension.txt"
```

Expected: targeted Rust test passes.

---

### Task 8: Agent Chat Runtime

**Files:**
- UI: chat panel
- Services: sidecar `8765`, llama.cpp `8766`

- [ ] **Step 1: Send a plain chat message**

Manual:

1. Open or create a project.
2. Send `你好，请用一句中文说明你已经可以响应。`
3. Wait up to 180 seconds for the model response.

Expected:

- user message appears immediately.
- assistant message appears or streams.
- assistant response is not `本地模型暂未启用`.
- no sidecar error banner appears.

- [ ] **Step 2: Verify services remain healthy after chat**

Run:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8765/health" -UseBasicParsing -TimeoutSec 5 |
  Select-Object StatusCode,Content |
  Tee-Object -FilePath "$evidenceRoot\sidecar-health-after-chat.txt"
Invoke-WebRequest -Uri "http://127.0.0.1:8766/health" -UseBasicParsing -TimeoutSec 5 |
  Select-Object StatusCode,Content |
  Tee-Object -FilePath "$evidenceRoot\llama-health-after-chat.txt"
```

Expected: both return HTTP `200`.

- [ ] **Step 3: Verify no old sidecar auth path is accepted**

Run:

```powershell
Push-Location python
python -m pytest tests\test_app.py::test_agent_endpoints_reject_non_alita_sidecar_token_header *> "$evidenceRoot\sidecar-auth-negative.txt"
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Get-Content "$evidenceRoot\sidecar-auth-negative.txt"; exit $code }
Get-Content "$evidenceRoot\sidecar-auth-negative.txt"
```

Expected: targeted Python test passes.

---

### Task 9: Attachment-Driven Node Graph Generation

**Files:**
- Create: `%TEMP%\alita-rename-regression\sample-note.txt`
- UI: chat panel and node canvas

- [ ] **Step 1: Create a sample text attachment**

Run:

```powershell
$sample = Join-Path $testRoot "sample-note.txt"
Set-Content -LiteralPath $sample -Value "这是一个 Alita 回归测试附件。请总结为一句话。" -Encoding UTF8
Get-Item $sample | Select-Object FullName,Length | Tee-Object -FilePath "$evidenceRoot\sample-attachment.txt"
```

Expected: sample text file exists.

- [ ] **Step 2: Add attachment and request a document task**

Manual:

1. Click `添加文件`.
2. Select `%TEMP%\alita-rename-regression\sample-note.txt`.
3. Send `请总结这个文档，并生成处理流程。`

Expected:

- attachment chip appears before sending.
- user message includes attachment name.
- right canvas changes from empty state to a node graph.
- graph contains document input, document parse, model, and export nodes.

- [ ] **Step 3: Save and reload attachment graph**

Manual:

1. Click `保存`.
2. Close Alita.
3. Reopen the saved project.

Expected:

- project loads.
- attachment reference remains in project.
- node graph remains visible.
- missing attachment warnings do not appear while sample file exists.

---

### Task 10: Graph Execution, Artifacts, Retry, and Cancel

**Files:**
- Project artifacts under `%TEMP%\alita-rename-regression\artifacts` or the active project directory.
- UI: node canvas, node popover.

- [ ] **Step 1: Run the generated workflow**

Manual:

1. With the graph from Task 9 visible, click `运行流程`.
2. Wait until the run completes.

Expected:

- `运行流程` changes to running state.
- nodes transition through running/completed or a clear failure state.
- at least one artifact is created for successful export.
- run history is recorded in the project state.

- [ ] **Step 2: Open node popover**

Manual:

1. Click each node in the canvas.
2. Inspect popover details.

Expected:

- node type, capability, inputs, outputs, dependencies, summary, and latest run details render.
- if artifact refs exist, `打开` and `定位` actions are visible.

- [ ] **Step 3: Open and reveal artifact**

Manual:

1. In the node popover, click `打开` for an artifact.
2. Click `定位` for the same artifact.

Expected:

- `打开` launches the artifact with the default file handler.
- `定位` opens File Explorer with the artifact selected.

- [ ] **Step 4: Tool disabled failure path**

Manual:

1. Open `首选项`.
2. Disable `MarkItDown 文档转 Markdown`.
3. Return to the graph and click `运行流程`.

Expected:

- run fails at the disabled tool node.
- chat or node details show a disabled-tool failure.
- node status becomes failed.

- [ ] **Step 5: Retry after re-enabling tool**

Manual:

1. Reopen `首选项`.
2. Re-enable `MarkItDown 文档转 Markdown`.
3. Click retry failed or run from the failed node.

Expected:

- retry starts from the selected failed scope.
- disabled-tool failure does not recur.

- [ ] **Step 6: Cancel a running workflow**

Manual:

1. Start a full graph run.
2. Click cancel/stop while the run is still active.

Expected:

- UI enters cancelling state.
- active run stops.
- no new orphan `alita-agent-sidecar.exe` or `llama-server.exe` process is created.

---

### Task 11: Restart Persistence and Process Cleanup

**Files:**
- Read: active `.alita` project file.
- Read: `%APPDATA%\com.alita.ai-workbench\preferences.json`

- [ ] **Step 1: Close app and verify child processes stop**

Manual:

1. Close the Alita window.
2. Wait 5 seconds.

Run:

```powershell
Get-Process -Name alita,alita-agent-sidecar,llama-server -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,Path |
  Tee-Object -FilePath "$evidenceRoot\processes-after-close.txt"
```

Expected: no Alita-owned processes remain. If an unrelated process is still on a port, record it before continuing.

- [ ] **Step 2: Reopen app and verify restored state**

Run:

```powershell
$exe = Resolve-Path "src-tauri\target\release\alita.exe"
Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe)
Start-Sleep -Seconds 10
Get-Process -Name alita,alita-agent-sidecar,llama-server -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,MainWindowTitle,Path |
  Tee-Object -FilePath "$evidenceRoot\processes-after-reopen.txt"
```

Manual:

1. Open the saved regression project from recent projects or `打开工程`.
2. Open `首选项`.

Expected:

- window title is `Alita`.
- recovered default model is still present.
- sidecar and llama health endpoints return HTTP `200`.
- saved messages, graph, run history, and artifacts still load.

---

### Task 12: Final Evidence Review

**Files:**
- Read: `$evidenceRoot\*.txt`
- Read: generated `.alita` project file.

- [ ] **Step 1: Run final scanners**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-alita-rename-clean.ps1 |
  Tee-Object -FilePath "$evidenceRoot\final-rename-scan-source.txt"
powershell -ExecutionPolicy Bypass -File scripts/check-alita-rename-clean.ps1 -IncludeGenerated |
  Tee-Object -FilePath "$evidenceRoot\final-rename-scan-generated.txt"
```

Expected: both scans print `No forbidden legacy naming tokens found.`

- [ ] **Step 2: Confirm no test audit files contain unexpected failures**

Run:

```powershell
Select-String -Path "$evidenceRoot\*.txt" -Pattern "FAILED","error:","panic","Traceback","本地模型暂未启用","old project directory" -CaseSensitive
```

Expected: no unexpected failure lines. Allowed exceptions must be explicitly explained in the final report.

- [ ] **Step 3: Write the test report**

Create `docs/test-results/<evidence-folder>/summary.md` with:

```markdown
# Alita Rename Regression Summary

## Result
- Overall:
- Date:
- Build:

## Commands
- frontend:test:
- frontend:lint:
- python pytest:
- cargo test:
- desktop build:
- source scanner:
- generated scanner:

## Runtime
- window title:
- sidecar health:
- llama health:
- recovered model path:

## Manual Workflows
- preferences:
- project lifecycle:
- chat:
- attachment graph:
- graph run:
- artifact open/reveal:
- restart persistence:

## Failures Or Deviations
- None, or list exact failure with evidence file.
```

Expected: final report exists and references any failed or skipped steps.

---

## Pass Criteria

The rename regression passes only if all of these are true:

- All automated tests exit `0`.
- Both rename scanners pass.
- Desktop build exits `0`.
- `alita.exe` opens with window title `Alita`.
- `alita-agent-sidecar.exe` health endpoint returns `200`.
- `llama-server.exe` health endpoint returns `200` when a default model is configured.
- Preferences contain a default `.gguf` model under the current Alita path or a valid user-selected path.
- Plain Agent chat does not return `本地模型暂未启用`.
- `.alita` create/save/save-as/open works.
- Non-Alita project extensions are rejected.
- Attachment task generates a node graph.
- Graph execution either succeeds with artifacts or fails with a clear expected reason.
- Tool disabled and re-enabled paths work.
- Artifacts can be opened and revealed.
- Closing Alita does not leave Alita-owned child processes running.
- Reopening Alita preserves preferences, recent projects, project content, graph, and run history.

## Failure Handling

If any step fails:

1. Save the command output or screenshot in `$evidenceRoot`.
2. Identify whether the failure is rename-related, environment-related, or an existing functional bug.
3. Create a focused fix plan before changing code.
4. Add or update an automated regression test for rename-related failures.
5. Re-run the failed task plus Task 12.

## Current Known Risk

The rename introduced a new Alita app identifier and config directory. The current code includes model preference recovery from the previous config when the new Alita config lacks a valid default model. This plan must verify that recovery through both automated tests and actual runtime startup.
