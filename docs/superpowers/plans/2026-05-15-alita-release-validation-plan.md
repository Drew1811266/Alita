# Alita Release Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute a full pre-release validation of Alita and produce a signed evidence package that supports a Pass, Fail, or Blocked release decision.

**Architecture:** This plan runs as a layered release gate: preflight, automated suites, release packaging, release runtime, manual workflow validation, cleanup, and final reporting. It writes all command output and manual results to a timestamped evidence directory under `docs/test-results`, while keeping test projects and fixture files under `%TEMP%` and restoring the user's Alita preferences after the run.

**Tech Stack:** PowerShell, Tauri 2, Rust/Cargo, React/Vite/TypeScript/Vitest, Python/FastAPI/pytest, llama.cpp, Windows WebView2, NSIS, Alita `.alita` project files.

---

## Source Documents

- Strategy: `D:\Software Project\Alita\docs\superpowers\specs\2026-05-15-alita-release-test-strategy-design.md`
- Existing MVP verifier: `D:\Software Project\Alita\scripts\verify-mvp.ps1`
- Desktop build script: `D:\Software Project\Alita\scripts\build-windows-app.ps1`
- Desktop runbook: `D:\Software Project\Alita\docs\windows-desktop-runbook.md`

## Files And Artifacts

This plan creates runtime evidence and test data only. It does not modify product source code.

- Create: `D:\Software Project\Alita\docs\test-results\full-release-<timestamp>\context.json`
- Create: `D:\Software Project\Alita\docs\test-results\full-release-<timestamp>\manual-checklist.md`
- Create: `D:\Software Project\Alita\docs\test-results\full-release-<timestamp>\summary.md`
- Create: `%TEMP%\alita-release-validation-<timestamp>\fixtures\sample-report.md`
- Create: `%TEMP%\alita-release-validation-<timestamp>\fixtures\sample-notes.txt`
- Create: `%TEMP%\alita-release-validation-<timestamp>\fixtures\sample-document.docx`
- Create: `%TEMP%\alita-release-validation-<timestamp>\fixtures\sample-reference.pdf`
- Create: `%TEMP%\alita-release-validation-<timestamp>\fixtures\fake-import-model.gguf`
- Create: `%TEMP%\alita-release-validation-<timestamp>\scan-models\fake-scanned-model.gguf`
- Create: `%TEMP%\alita-release-validation-<timestamp>\model-storage`
- Create: `%TEMP%\alita-release-validation-<timestamp>\projects\release-validation.alita`
- Create: `%TEMP%\alita-release-validation-<timestamp>\projects\release-validation-copy.alita`
- Read/backup: `%APPDATA%\com.alita.ai-workbench\preferences.json`
- Read/verify: `D:\Software Project\Alita\dist\index.html`
- Read/verify: `D:\Software Project\Alita\src-tauri\target\release\alita.exe`
- Read/verify: `D:\Software Project\Alita\src-tauri\target\release\bundle`

## Execution Rules

- Run this from an ordinary PowerShell session, not from an interactive prompt inside `cargo`, `npm`, or `python`.
- Use one PowerShell session when possible so `$evidenceRoot`, `$testRoot`, and `$modelPath` remain available.
- If a new PowerShell session is opened after Task 1, run the context load command at the start of the next task.
- Stop at the first P0 or unclassified failure. Save evidence first, then classify the result in `summary.md`.
- Do not delete the user's real model directory.
- Do not overwrite existing user `.alita` project files.
- Do not use `git reset --hard`, `git checkout --`, or any destructive git command.

## Context Load Command

Run this at the start of any task when variables are not already loaded in the current PowerShell session:

```powershell
$repoRoot = "D:\Software Project\Alita"
$latestContext = Get-ChildItem -Path "$repoRoot\docs\test-results" -Filter "context.json" -Recurse |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
if (-not $latestContext) {
  throw "No release validation context.json was found. Run Task 1 first."
}
$context = Get-Content -LiteralPath $latestContext.FullName -Raw | ConvertFrom-Json
$evidenceRoot = $context.evidenceRoot
$testRoot = $context.testRoot
$fixtureRoot = $context.fixtureRoot
$projectRoot = $context.projectRoot
$modelStorageRoot = $context.modelStorageRoot
$scanModelRoot = $context.scanModelRoot
$prefsPath = $context.prefsPath
$prefsBackup = $context.prefsBackup
$modelPath = $context.modelPath
$releaseExe = $context.releaseExe
$sampleMarkdown = $context.sampleMarkdown
$sampleText = $context.sampleText
$sampleDocx = $context.sampleDocx
$samplePdf = $context.samplePdf
$fakeImportModel = $context.fakeImportModel
$fakeScannedModel = $context.fakeScannedModel
$primaryProject = $context.primaryProject
$copiedProject = $context.copiedProject
"Loaded context from $($latestContext.FullName)"
```

Expected: command prints the path to the latest `context.json`.

---

### Task 1: Preflight Evidence, Backup, And Fixtures

**Files:**
- Create: `docs/test-results/full-release-<timestamp>/context.json`
- Create: `docs/test-results/full-release-<timestamp>/preflight.txt`
- Create: `%TEMP%/alita-release-validation-<timestamp>/fixtures/*`
- Read/backup: `%APPDATA%/com.alita.ai-workbench/preferences.json`

- [ ] **Step 1: Create evidence and test directories**

Run:

```powershell
$ErrorActionPreference = "Stop"
$repoRoot = "D:\Software Project\Alita"
Set-Location $repoRoot
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$evidenceRoot = Join-Path $repoRoot "docs\test-results\full-release-$stamp"
$testRoot = Join-Path $env:TEMP "alita-release-validation-$stamp"
$fixtureRoot = Join-Path $testRoot "fixtures"
$projectRoot = Join-Path $testRoot "projects"
$modelStorageRoot = Join-Path $testRoot "model-storage"
$scanModelRoot = Join-Path $testRoot "scan-models"
New-Item -ItemType Directory -Force -Path $evidenceRoot,$testRoot,$fixtureRoot,$projectRoot,$modelStorageRoot,$scanModelRoot | Out-Null
"Evidence root: $evidenceRoot" | Tee-Object -FilePath "$evidenceRoot\preflight.txt"
"Test root: $testRoot" | Tee-Object -FilePath "$evidenceRoot\test-root.txt"
```

Expected: both directories are created and `preflight.txt` contains the evidence path.

- [ ] **Step 2: Record git and repository state**

Run:

```powershell
git status --short | Tee-Object -FilePath "$evidenceRoot\git-status-before.txt"
git log --oneline -5 | Tee-Object -FilePath "$evidenceRoot\git-log-before.txt"
Get-Content -Path "package.json" -Raw | Tee-Object -FilePath "$evidenceRoot\package-json.txt" | Out-Null
Get-Content -Path "src-tauri\tauri.conf.json" -Raw | Tee-Object -FilePath "$evidenceRoot\tauri-conf-json.txt" | Out-Null
Get-Content -Path "python\pyproject.toml" -Raw | Tee-Object -FilePath "$evidenceRoot\python-pyproject.txt" | Out-Null
```

Expected: files are written. Existing unrelated working tree changes are recorded, not modified.

- [ ] **Step 3: Snapshot running Alita-related processes and ports**

Run:

```powershell
Get-Process -Name alita,alita-agent-sidecar,llama-server,node,python,cargo,powershell -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,MainWindowTitle,Path |
  Tee-Object -FilePath "$evidenceRoot\processes-before.txt"

Get-NetTCPConnection -LocalPort 1420,8765,8766 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,OwningProcess |
  Tee-Object -FilePath "$evidenceRoot\ports-before.txt"
```

Expected: the files exist. Empty output is acceptable only when no matching process or listener exists.

- [ ] **Step 4: Back up existing Alita preferences**

Run:

```powershell
$prefsPath = Join-Path $env:APPDATA "com.alita.ai-workbench\preferences.json"
$prefsBackup = Join-Path $evidenceRoot "preferences-before.json"
if (Test-Path -LiteralPath $prefsPath -PathType Leaf) {
  Copy-Item -LiteralPath $prefsPath -Destination $prefsBackup -Force
  Get-Content -LiteralPath $prefsPath -Raw | Tee-Object -FilePath "$evidenceRoot\preferences-before.pretty.json"
  "Preferences backup: $prefsBackup" | Tee-Object -FilePath "$evidenceRoot\preferences-backup-status.txt"
} else {
  "No existing Alita preferences file at $prefsPath" | Tee-Object -FilePath "$evidenceRoot\preferences-backup-status.txt"
}
```

Expected: existing preferences are copied, or the no-preferences note is saved.

- [ ] **Step 5: Select a real GGUF model for runtime validation**

Run:

```powershell
$modelCandidates = @()
if (-not [string]::IsNullOrWhiteSpace($env:ALITA_LLAMA_MODEL_PATH) -and (Test-Path -LiteralPath $env:ALITA_LLAMA_MODEL_PATH -PathType Leaf)) {
  $modelCandidates += Get-Item -LiteralPath $env:ALITA_LLAMA_MODEL_PATH
}
$modelCandidates += Get-ChildItem -Path (Join-Path $repoRoot "models") -Filter "*.gguf" -File -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $prefsPath -PathType Leaf) {
  try {
    $prefs = Get-Content -LiteralPath $prefsPath -Raw | ConvertFrom-Json
    foreach ($entry in @($prefs.models)) {
      if ($entry.path -and (Test-Path -LiteralPath $entry.path -PathType Leaf) -and $entry.path.EndsWith(".gguf", [StringComparison]::OrdinalIgnoreCase)) {
        $modelCandidates += Get-Item -LiteralPath $entry.path
      }
    }
  } catch {
    "Could not inspect preferences for model candidates: $_" | Tee-Object -FilePath "$evidenceRoot\model-candidate-warning.txt"
  }
}
$modelPath = ($modelCandidates | Sort-Object FullName -Unique | Select-Object -First 1).FullName
if ([string]::IsNullOrWhiteSpace($modelPath)) {
  "BLOCKED: No real .gguf model was found for llama.cpp runtime validation." | Tee-Object -FilePath "$evidenceRoot\model-selection.txt"
} else {
  "Selected model: $modelPath" | Tee-Object -FilePath "$evidenceRoot\model-selection.txt"
}
```

Expected: `model-selection.txt` contains a real `.gguf` model path. If it says `BLOCKED`, the final release result cannot be `Pass`.

- [ ] **Step 6: Create fixture files**

Run:

```powershell
$sampleMarkdown = Join-Path $fixtureRoot "sample-report.md"
$sampleText = Join-Path $fixtureRoot "sample-notes.txt"
$sampleDocx = Join-Path $fixtureRoot "sample-document.docx"
$samplePdf = Join-Path $fixtureRoot "sample-reference.pdf"
$fakeImportModel = Join-Path $fixtureRoot "fake-import-model.gguf"
$fakeScannedModel = Join-Path $scanModelRoot "fake-scanned-model.gguf"

Set-Content -LiteralPath $sampleMarkdown -Encoding UTF8 -Value @(
  "# Alita Release Validation",
  "",
  "这是一份发布验收测试文档。",
  "",
  "- 目标：验证附件、节点图、流程运行和 artifact 输出。",
  "- 输出：生成中文摘要报告。"
)

Set-Content -LiteralPath $sampleText -Encoding UTF8 -Value @(
  "Alita release validation text fixture",
  "测试重点：聊天、附件、节点执行、artifact 预览。"
)

Set-Content -LiteralPath $fakeImportModel -Encoding ASCII -Value "fake gguf import fixture for preferences UI only"
Set-Content -LiteralPath $fakeScannedModel -Encoding ASCII -Value "fake gguf scan fixture for preferences UI only"

$fixtureScript = Join-Path $fixtureRoot "create-fixtures.py"
Set-Content -LiteralPath $fixtureScript -Encoding UTF8 -Value @(
  "from pathlib import Path",
  "import os",
  "from docx import Document",
  "",
  "docx_path = Path(os.environ['ALITA_SAMPLE_DOCX'])",
  "doc = Document()",
  "doc.add_heading('Alita Release Validation', level=1)",
  "doc.add_paragraph('这是一份用于发布验收的 Word 附件。')",
  "doc.add_paragraph('请整理为中文报告，并保留关键要点。')",
  "doc.save(docx_path)",
  "",
  "pdf_path = Path(os.environ['ALITA_SAMPLE_PDF'])",
  "objects = []",
  "objects.append('1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')",
  "objects.append('2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n')",
  "objects.append('3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\nendobj\n')",
  "stream = 'BT /F1 24 Tf 72 720 Td (Alita Test PDF) Tj ET'",
  "objects.append(f'4 0 obj\n<< /Length {len(stream)} >>\nstream\n{stream}\nendstream\nendobj\n')",
  "objects.append('5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n')",
  "content = '%PDF-1.4\n'",
  "offsets = [0]",
  "for obj in objects:",
  "    offsets.append(len(content.encode('ascii')))",
  "    content += obj",
  "xref_offset = len(content.encode('ascii'))",
  "content += f'xref\n0 {len(objects) + 1}\n'",
  "content += '0000000000 65535 f \n'",
  "for offset in offsets[1:]:",
  "    content += f'{offset:010d} 00000 n \n'",
  "content += f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n'",
  "pdf_path.write_bytes(content.encode('ascii'))"
)
$env:ALITA_SAMPLE_DOCX = $sampleDocx
$env:ALITA_SAMPLE_PDF = $samplePdf
python $fixtureScript

Get-ChildItem -LiteralPath $fixtureRoot,$scanModelRoot -File |
  Select-Object Name,Length,FullName |
  Tee-Object -FilePath "$evidenceRoot\fixtures-created.txt"
```

Expected: the fixture list contains `sample-report.md`, `sample-notes.txt`, `sample-document.docx`, `sample-reference.pdf`, `fake-import-model.gguf`, and `fake-scanned-model.gguf`.

- [ ] **Step 7: Write reusable context**

Run:

```powershell
$context = [ordered]@{
  repoRoot = $repoRoot
  evidenceRoot = $evidenceRoot
  testRoot = $testRoot
  fixtureRoot = $fixtureRoot
  projectRoot = $projectRoot
  modelStorageRoot = $modelStorageRoot
  scanModelRoot = $scanModelRoot
  prefsPath = $prefsPath
  prefsBackup = $prefsBackup
  modelPath = $modelPath
  releaseExe = Join-Path $repoRoot "src-tauri\target\release\alita.exe"
  sampleMarkdown = $sampleMarkdown
  sampleText = $sampleText
  sampleDocx = $sampleDocx
  samplePdf = $samplePdf
  fakeImportModel = $fakeImportModel
  fakeScannedModel = $fakeScannedModel
  primaryProject = Join-Path $projectRoot "release-validation.alita"
  copiedProject = Join-Path $projectRoot "release-validation-copy.alita"
}
$context | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath "$evidenceRoot\context.json" -Encoding UTF8
Get-Content -LiteralPath "$evidenceRoot\context.json"
```

Expected: `context.json` exists and includes `evidenceRoot`, `testRoot`, `modelPath`, and `releaseExe`.

---

### Task 2: Automated Gate

**Files:**
- Read/Test: `src/**/*.test.ts`
- Read/Test: `src/**/*.test.tsx`
- Read/Test: `python/tests/*.py`
- Read/Test: `src-tauri/tests/*.rs`
- Create: `docs/test-results/full-release-<timestamp>/*test*.txt`

- [ ] **Step 1: Run desktop prerequisite check**

Run:

```powershell
Set-Location $repoRoot
npm run check:desktop-prereqs *> "$evidenceRoot\desktop-prereqs.txt"
if ($LASTEXITCODE -ne 0) {
  Get-Content "$evidenceRoot\desktop-prereqs.txt"
  throw "BLOCKED: desktop prerequisite check failed."
}
Get-Content "$evidenceRoot\desktop-prereqs.txt"
```

Expected: output includes `[ok] rustup`, `[ok] cargo`, `[ok] node`, `[ok] npm`, `[ok] python`, Visual Studio Build Tools, `link.exe`, and WebView2.

- [ ] **Step 2: Load Visual Studio developer environment**

Run:

```powershell
. .\scripts\import-vs-dev-env.ps1 *> "$evidenceRoot\vs-dev-env.txt"
Get-Content "$evidenceRoot\vs-dev-env.txt"
```

Expected: output says the Visual Studio developer environment was loaded.

- [ ] **Step 3: Run frontend typecheck**

Run:

```powershell
Set-Location $repoRoot
npm run frontend:lint *> "$evidenceRoot\frontend-lint.txt"
if ($LASTEXITCODE -ne 0) {
  Get-Content "$evidenceRoot\frontend-lint.txt"
  throw "FAIL: frontend typecheck failed."
}
Get-Content "$evidenceRoot\frontend-lint.txt"
```

Expected: command exits `0` and contains no TypeScript errors.

- [ ] **Step 4: Run frontend tests**

Run:

```powershell
Set-Location $repoRoot
npm run frontend:test *> "$evidenceRoot\frontend-test.txt"
if ($LASTEXITCODE -ne 0) {
  Get-Content "$evidenceRoot\frontend-test.txt"
  throw "FAIL: frontend tests failed."
}
Get-Content "$evidenceRoot\frontend-test.txt"
```

Expected: Vitest reports all test files and tests passed.

- [ ] **Step 5: Run Python sidecar tests**

Run:

```powershell
Set-Location (Join-Path $repoRoot "python")
python -m pytest *> "$evidenceRoot\python-pytest.txt"
$pytestCode = $LASTEXITCODE
Set-Location $repoRoot
if ($pytestCode -ne 0) {
  Get-Content "$evidenceRoot\python-pytest.txt"
  throw "FAIL: Python pytest failed."
}
Get-Content "$evidenceRoot\python-pytest.txt"
```

Expected: pytest reports all tests passed.

- [ ] **Step 6: Run Rust formatting check**

Run:

```powershell
Set-Location (Join-Path $repoRoot "src-tauri")
cargo fmt --check *> "$evidenceRoot\rust-fmt.txt"
$fmtCode = $LASTEXITCODE
Set-Location $repoRoot
if ($fmtCode -ne 0) {
  Get-Content "$evidenceRoot\rust-fmt.txt"
  throw "FAIL: Rust formatting check failed."
}
Get-Content "$evidenceRoot\rust-fmt.txt"
```

Expected: command exits `0`.

- [ ] **Step 7: Run Rust tests**

Run:

```powershell
Set-Location (Join-Path $repoRoot "src-tauri")
$previousCargoTargetDir = $env:CARGO_TARGET_DIR
$env:CARGO_TARGET_DIR = Join-Path (Get-Location) "target\release-validation"
cargo test *> "$evidenceRoot\rust-cargo-test.txt"
$cargoTestCode = $LASTEXITCODE
if ([string]::IsNullOrEmpty($previousCargoTargetDir)) {
  Remove-Item Env:CARGO_TARGET_DIR -ErrorAction SilentlyContinue
} else {
  $env:CARGO_TARGET_DIR = $previousCargoTargetDir
}
Set-Location $repoRoot
if ($cargoTestCode -ne 0) {
  Get-Content "$evidenceRoot\rust-cargo-test.txt"
  throw "FAIL: Rust cargo test failed."
}
Get-Content "$evidenceRoot\rust-cargo-test.txt"
```

Expected: Cargo reports all Rust tests passed.

- [ ] **Step 8: Run frontend production build**

Run:

```powershell
Set-Location $repoRoot
npm run frontend:build *> "$evidenceRoot\frontend-build.txt"
if ($LASTEXITCODE -ne 0) {
  Get-Content "$evidenceRoot\frontend-build.txt"
  throw "FAIL: frontend production build failed."
}
Get-Content "$evidenceRoot\frontend-build.txt"
Select-String -Path "dist\index.html" -Pattern "<title>Alita</title>" |
  Tee-Object -FilePath "$evidenceRoot\dist-title.txt"
```

Expected: frontend build exits `0`, and `dist-title.txt` contains `<title>Alita</title>`.

---

### Task 3: Release Packaging Gate

**Files:**
- Run: `scripts/build-windows-app.ps1`
- Verify: `src-tauri/target/release/alita.exe`
- Verify: `src-tauri/target/release/bundle`
- Create: `docs/test-results/full-release-<timestamp>/desktop-build.txt`

- [ ] **Step 1: Build the Windows release application**

Run:

```powershell
Set-Location $repoRoot
npm run desktop:build *> "$evidenceRoot\desktop-build.txt"
if ($LASTEXITCODE -ne 0) {
  Get-Content "$evidenceRoot\desktop-build.txt"
  throw "FAIL: desktop release build failed."
}
Get-Content "$evidenceRoot\desktop-build.txt"
```

Expected: command exits `0`.

- [ ] **Step 2: Verify release binaries and bundle outputs**

Run:

```powershell
$releaseExe = Join-Path $repoRoot "src-tauri\target\release\alita.exe"
$releaseSidecar = Join-Path $repoRoot "src-tauri\target\release\alita-agent-sidecar.exe"
$bundleDir = Join-Path $repoRoot "src-tauri\target\release\bundle"
$llamaRuntimeDir = Join-Path $repoRoot "src-tauri\target\release\llama-cpp"

$releaseChecks = [ordered]@{
  releaseExe = Test-Path -LiteralPath $releaseExe -PathType Leaf
  releaseSidecar = Test-Path -LiteralPath $releaseSidecar -PathType Leaf
  bundleDir = Test-Path -LiteralPath $bundleDir -PathType Container
  llamaServer = Test-Path -LiteralPath (Join-Path $llamaRuntimeDir "llama-server.exe") -PathType Leaf
  llamaDll = [bool](Get-ChildItem -LiteralPath $llamaRuntimeDir -Filter "*.dll" -File -ErrorAction SilentlyContinue | Select-Object -First 1)
}
$releaseChecks.GetEnumerator() |
  ForEach-Object { "$($_.Key)=$($_.Value)" } |
  Tee-Object -FilePath "$evidenceRoot\release-output-checks.txt"
if ($releaseChecks.Values -contains $false) {
  throw "FAIL: one or more release output checks failed."
}
```

Expected: every line in `release-output-checks.txt` ends with `=True`.

- [ ] **Step 3: Capture release output inventory**

Run:

```powershell
Get-ChildItem -LiteralPath "src-tauri\target\release" -File |
  Where-Object { $_.Name -in @("alita.exe","alita-agent-sidecar.exe") } |
  Select-Object Name,Length,FullName |
  Tee-Object -FilePath "$evidenceRoot\release-binaries.txt"

Get-ChildItem -LiteralPath "src-tauri\target\release\bundle" -Recurse -File |
  Select-Object Name,Length,FullName |
  Tee-Object -FilePath "$evidenceRoot\nsis-bundle-output.txt"

Get-ChildItem -LiteralPath "src-tauri\target\release\llama-cpp" -File |
  Select-Object Name,Length,FullName |
  Tee-Object -FilePath "$evidenceRoot\llama-runtime-output.txt"
```

Expected: inventory includes `alita.exe`, `alita-agent-sidecar.exe`, an installer under `bundle`, `llama-server.exe`, and llama runtime DLL files.

- [ ] **Step 4: Verify product identity**

Run:

```powershell
Select-String -Path "package.json" -Pattern '"name": "alita"','"version": "0.1.0"' |
  Tee-Object -FilePath "$evidenceRoot\package-identity.txt"
Select-String -Path "src-tauri\tauri.conf.json" -Pattern '"productName": "Alita"','"identifier": "com.alita.ai-workbench"','"title": "Alita"' |
  Tee-Object -FilePath "$evidenceRoot\tauri-identity.txt"
Select-String -Path "python\agent_service\app.py" -Pattern 'FastAPI\(title="Alita Agent Sidecar"\)','ALITA_SIDECAR_TOKEN','X-Alita-Sidecar-Token' |
  Tee-Object -FilePath "$evidenceRoot\sidecar-identity.txt"
```

Expected: each file contains all requested identity lines.

---

### Task 4: Release Runtime Gate

**Files:**
- Run: `src-tauri/target/release/alita.exe`
- Create: `docs/test-results/full-release-<timestamp>/runtime-processes.txt`
- Create: `docs/test-results/full-release-<timestamp>/sidecar-health.txt`
- Create: `docs/test-results/full-release-<timestamp>/llama-health.txt`

- [ ] **Step 1: Close Alita-owned release validation processes from previous attempts**

Run:

```powershell
$repoPrefix = (Resolve-Path $repoRoot).Path
$existing = Get-Process -Name alita,alita-agent-sidecar,llama-server -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -and $_.Path.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase) }
$existing | Select-Object Id,ProcessName,Path | Tee-Object -FilePath "$evidenceRoot\runtime-cleanup-before.txt"
foreach ($process in $existing) {
  if ($process.ProcessName -eq "alita" -and $process.MainWindowHandle -ne 0) {
    [void]$process.CloseMainWindow()
  }
}
Start-Sleep -Seconds 5
$stillRunning = $existing | Where-Object { -not $_.HasExited }
foreach ($process in $stillRunning) {
  Stop-Process -Id $process.Id -Force
}
Get-Process -Name alita,alita-agent-sidecar,llama-server -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,Path |
  Tee-Object -FilePath "$evidenceRoot\runtime-cleanup-after.txt"
```

Expected: only Alita-owned processes under the current repository are closed. Unrelated processes are not stopped.

- [ ] **Step 2: Start release app with model environment**

Run:

```powershell
if ([string]::IsNullOrWhiteSpace($modelPath) -or -not (Test-Path -LiteralPath $modelPath -PathType Leaf)) {
  "BLOCKED: release runtime will start without llama.cpp model because modelPath is empty or missing." |
    Tee-Object -FilePath "$evidenceRoot\runtime-model-blocked.txt"
} else {
  $env:ALITA_LLAMA_MODEL_PATH = $modelPath
  $env:ALITA_LLAMA_BASE_URL = "http://127.0.0.1:8766"
  $env:ALITA_LLAMA_MODEL_NAME = [System.IO.Path]::GetFileNameWithoutExtension($modelPath)
  "Runtime model: $env:ALITA_LLAMA_MODEL_PATH" | Tee-Object -FilePath "$evidenceRoot\runtime-model-env.txt"
}

$releaseExe = Join-Path $repoRoot "src-tauri\target\release\alita.exe"
if (-not (Test-Path -LiteralPath $releaseExe -PathType Leaf)) {
  throw "FAIL: release alita.exe does not exist."
}
$releaseProcess = Start-Process -FilePath $releaseExe -WorkingDirectory (Split-Path -Parent $releaseExe) -PassThru
Start-Sleep -Seconds 20
$releaseProcess.Id | Tee-Object -FilePath "$evidenceRoot\release-process-id.txt"
```

Expected: `release-process-id.txt` contains the started `alita.exe` PID.

- [ ] **Step 3: Verify runtime processes and ports**

Run:

```powershell
Get-Process -Name alita,alita-agent-sidecar,llama-server -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,MainWindowTitle,Path |
  Tee-Object -FilePath "$evidenceRoot\runtime-processes.txt"

Get-NetTCPConnection -LocalPort 8765,8766 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,OwningProcess |
  Tee-Object -FilePath "$evidenceRoot\runtime-ports.txt"

$windowTitle = (Get-Process -Name alita -ErrorAction SilentlyContinue | Select-Object -First 1).MainWindowTitle
"WindowTitle=$windowTitle" | Tee-Object -FilePath "$evidenceRoot\window-title.txt"
if ($windowTitle -ne "Alita") {
  throw "FAIL: release window title is not Alita."
}
```

Expected: `runtime-processes.txt` includes `alita`; `window-title.txt` contains `WindowTitle=Alita`.

- [ ] **Step 4: Verify sidecar health**

Run:

```powershell
try {
  Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 5 |
    ConvertTo-Json -Depth 4 |
    Tee-Object -FilePath "$evidenceRoot\sidecar-health.txt"
} catch {
  $_.Exception.Message | Tee-Object -FilePath "$evidenceRoot\sidecar-health.txt"
  throw "FAIL: sidecar health endpoint failed."
}
```

Expected: `sidecar-health.txt` contains `"status": "ok"`.

- [ ] **Step 5: Verify llama.cpp health**

Run:

```powershell
if ([string]::IsNullOrWhiteSpace($modelPath) -or -not (Test-Path -LiteralPath $modelPath -PathType Leaf)) {
  "BLOCKED: no model was available for llama.cpp health validation." | Tee-Object -FilePath "$evidenceRoot\llama-health.txt"
  throw "BLOCKED: no model was available for llama.cpp health validation."
}
try {
  Invoke-RestMethod -Uri "http://127.0.0.1:8766/health" -TimeoutSec 10 |
    ConvertTo-Json -Depth 4 |
    Tee-Object -FilePath "$evidenceRoot\llama-health.txt"
} catch {
  $_.Exception.Message | Tee-Object -FilePath "$evidenceRoot\llama-health.txt"
  throw "FAIL: llama.cpp health endpoint failed."
}
```

Expected: `llama-health.txt` contains a healthy llama.cpp response and does not contain a connection failure.

---

### Task 5: Preferences And Model Manual Validation

**Files:**
- Create/Update: `docs/test-results/full-release-<timestamp>/manual-checklist.md`
- Read/Write through app: `%APPDATA%/com.alita.ai-workbench/preferences.json`
- Use fixture: `%TEMP%/alita-release-validation-<timestamp>/fixtures/fake-import-model.gguf`
- Use fixture: `%TEMP%/alita-release-validation-<timestamp>/scan-models/fake-scanned-model.gguf`

- [ ] **Step 1: Create manual checklist file**

Run:

```powershell
@"
# Alita Full Release Manual Checklist

Evidence root: $evidenceRoot
Test root: $testRoot

## Preferences And Model
- [ ] Preferences opens from project home.
- [ ] Preferences opens from workbench.
- [ ] Model storage directory can be changed to $modelStorageRoot.
- [ ] Fake import model can be imported from $fakeImportModel.
- [ ] Real external model can be referenced from $modelPath.
- [ ] Real external model can be set as default.
- [ ] Scan model directory loads fake scanned model from $scanModelRoot.
- [ ] Tool enablement can be toggled off and back on.
- [ ] Preferences persist after closing and reopening Preferences.

## Project Lifecycle
- [ ] New project saved at $(Join-Path $projectRoot "release-validation.alita").
- [ ] Save marks the project as saved.
- [ ] Save As writes $(Join-Path $projectRoot "release-validation-copy.alita").
- [ ] Opening the copied project restores project content.
- [ ] Non-.alita extension is rejected.
- [ ] Missing attachment warning appears when an attachment path is unavailable.

## Chat, Graph, Flow, Artifact
- [ ] No-attachment document prompt asks for an attachment.
- [ ] Normal chat returns an assistant response.
- [ ] Document attachment prompt generates a node graph.
- [ ] Node graph layout is top-to-bottom.
- [ ] Node popover shows type, capability, inputs, outputs, dependencies, latest run details, and artifact refs.
- [ ] Full workflow run succeeds and produces artifacts.
- [ ] Markdown or text artifact preview renders content.
- [ ] PDF artifact preview renders or shows a clear PDF fallback.
- [ ] Open artifact launches the system file handler.
- [ ] Reveal artifact opens File Explorer at the file.
- [ ] Disabling MarkItDown causes tool_disabled failure.
- [ ] Re-enabling MarkItDown allows retry or rerun.
- [ ] Cancel stops an active run or is recorded as not reproducible because the run completed before cancellation.

## Restart Persistence
- [ ] Preferences survive app restart.
- [ ] Recent or manually opened project restores.
- [ ] Chat messages survive restart.
- [ ] Node graph survives restart.
- [ ] Run history survives restart.
- [ ] Artifact refs survive restart.
- [ ] Sidecar health returns ok after restart.
- [ ] llama.cpp health returns ok after restart.
"@ | Set-Content -LiteralPath "$evidenceRoot\manual-checklist.md" -Encoding UTF8
Get-Content -LiteralPath "$evidenceRoot\manual-checklist.md"
```

Expected: `manual-checklist.md` exists with unchecked items.

- [ ] **Step 2: Validate project-home Preferences**

Manual:

1. Bring the `Alita` release window to the front.
2. If the app opens to the project home, click `首选项`.
3. Confirm the Preferences dialog opens.
4. Confirm model and tool sections are visible.
5. Close Preferences.

Record:

```powershell
"PASS manual: Preferences opens from project home and shows model/tool sections." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
```

Expected: Preferences opens without freezing the app.

- [ ] **Step 3: Set test model storage directory**

Manual:

1. Open `首选项`.
2. In the model storage directory control, choose this exact directory: `%TEMP%\alita-release-validation-<timestamp>\model-storage`.
3. Confirm the displayed model storage path matches `$modelStorageRoot`.
4. Close and reopen Preferences.
5. Confirm the same model storage path is still displayed.

Record:

```powershell
"PASS manual: Model storage directory persisted as $modelStorageRoot." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
```

Expected: model storage path remains `$modelStorageRoot`.

- [ ] **Step 4: Validate model import, external reference, scan, and default model**

Manual:

1. In Preferences, click `导入 GGUF 到模型库`.
2. Select `$fakeImportModel`.
3. Confirm the imported fake model appears with model-library source.
4. Click `引用外部 GGUF`.
5. Select `$modelPath`.
6. Confirm the real external model appears and its path remains `$modelPath`.
7. Set the real external model as default.
8. Click `扫描模型目录`.
9. Select `$scanModelRoot`.
10. Confirm `fake-scanned-model.gguf` appears in the model list.
11. Close and reopen Preferences.
12. Confirm the real external model is still the default model.

Record:

```powershell
"PASS manual: Model import, external reference, scan, and default model persisted." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
Get-Content -LiteralPath $prefsPath -Raw |
  Tee-Object -FilePath "$evidenceRoot\preferences-after-model-validation.json"
```

Expected: fake model import does not become the final default; the real `$modelPath` model is default.

- [ ] **Step 5: Validate tool enablement persistence**

Manual:

1. In Preferences, locate the MarkItDown document conversion tool.
2. Disable it.
3. Close and reopen Preferences.
4. Confirm it remains disabled.
5. Re-enable it.
6. Close and reopen Preferences.
7. Confirm it remains enabled.

Record:

```powershell
"PASS manual: Tool enablement persisted off and on." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
Get-Content -LiteralPath $prefsPath -Raw |
  Tee-Object -FilePath "$evidenceRoot\preferences-after-tool-toggle.json"
```

Expected: tool state persists across Preferences close/reopen.

---

### Task 6: Project Lifecycle Manual Validation

**Files:**
- Create via app: `%TEMP%/alita-release-validation-<timestamp>/projects/release-validation.alita`
- Create via app: `%TEMP%/alita-release-validation-<timestamp>/projects/release-validation-copy.alita`
- Use fixture: `%TEMP%/alita-release-validation-<timestamp>/fixtures/sample-document.docx`

- [ ] **Step 1: Create and save a new project**

Manual:

1. From the project home, click `新建工程`.
2. Save to `$projectRoot\release-validation.alita`.
3. Confirm the workbench opens.
4. Confirm the top bar shows the project name and saved state.

Record:

```powershell
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "release-validation.alita") -PathType Leaf)) {
  throw "FAIL manual: primary .alita project file was not created."
}
"PASS manual: New project created and saved." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
Get-Item -LiteralPath (Join-Path $projectRoot "release-validation.alita") |
  Select-Object Name,Length,FullName |
  Tee-Object -FilePath "$evidenceRoot\primary-project-created.txt"
```

Expected: `release-validation.alita` exists.

- [ ] **Step 2: Add fixture attachment and save project**

Manual:

1. In the chat composer, click the attachment control.
2. Select `$sampleDocx`.
3. Confirm the attachment filename appears in the composer.
4. Type `请把这个文档整理成一份中文报告，并输出为 Markdown 和 PDF。`
5. Send the message.
6. Wait until the node graph appears.
7. Click `保存`.
8. Confirm the top bar returns to saved state.

Record:

```powershell
"PASS manual: Attachment added, graph generated, project saved." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
Get-Content -LiteralPath (Join-Path $projectRoot "release-validation.alita") -Raw |
  Tee-Object -FilePath "$evidenceRoot\primary-project-after-graph.json"
```

Expected: the project file contains chat messages, attachment references, and graph data.

- [ ] **Step 3: Save As and reopen copied project**

Manual:

1. Click `另存为`.
2. Save to `$projectRoot\release-validation-copy.alita`.
3. Confirm the top bar shows the copied project path or name.
4. Return to project home.
5. Click `打开工程`.
6. Select `$projectRoot\release-validation-copy.alita`.
7. Confirm chat messages, attachment reference, and node graph are restored.

Record:

```powershell
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "release-validation-copy.alita") -PathType Leaf)) {
  throw "FAIL manual: copied .alita project file was not created."
}
"PASS manual: Save As and reopen copied project restored content." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
Get-Content -LiteralPath (Join-Path $projectRoot "release-validation-copy.alita") -Raw |
  Tee-Object -FilePath "$evidenceRoot\copied-project-after-reopen.json"
```

Expected: copied project exists and includes the same user workflow data.

- [ ] **Step 4: Validate non-.alita rejection**

Manual:

1. Create a text file path in the file dialog flow by attempting to save or open `not-a-project.txt` under `$projectRoot`.
2. Confirm the app rejects the non-`.alita` extension or prevents selecting it.

Record:

```powershell
"PASS manual: Non-.alita project extension was rejected or unavailable in the project dialog." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
```

Expected: a non-`.alita` file is not accepted as an Alita project.

- [ ] **Step 5: Validate missing attachment warning**

Manual:

1. Close the app window.
2. Rename `$sampleDocx` to `$sampleDocx.moved`.
3. Start release `alita.exe` again.
4. Open `$projectRoot\release-validation-copy.alita`.
5. Confirm the app shows a missing attachment warning.
6. Close the app.
7. Rename `$sampleDocx.moved` back to `$sampleDocx`.
8. Start release `alita.exe` again for the next task.

Run for rename and restart:

```powershell
$currentAlita = Get-Process -Name alita -ErrorAction SilentlyContinue | Select-Object -First 1
if ($currentAlita) {
  [void]$currentAlita.CloseMainWindow()
  Start-Sleep -Seconds 5
}
Rename-Item -LiteralPath $sampleDocx -NewName "sample-document.docx.moved"
$releaseProcess = Start-Process -FilePath $releaseExe -WorkingDirectory (Split-Path -Parent $releaseExe) -PassThru
Start-Sleep -Seconds 15
"Restarted release app for missing attachment validation with PID $($releaseProcess.Id)" |
  Tee-Object -FilePath "$evidenceRoot\missing-attachment-restart.txt"
```

After manual validation, run:

```powershell
$currentAlita = Get-Process -Name alita -ErrorAction SilentlyContinue | Select-Object -First 1
if ($currentAlita) {
  [void]$currentAlita.CloseMainWindow()
  Start-Sleep -Seconds 5
}
Rename-Item -LiteralPath "$sampleDocx.moved" -NewName "sample-document.docx"
$releaseProcess = Start-Process -FilePath $releaseExe -WorkingDirectory (Split-Path -Parent $releaseExe) -PassThru
Start-Sleep -Seconds 15
"PASS manual: Missing attachment warning appeared and fixture was restored." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
```

Expected: missing attachment warning is visible when the attachment path is unavailable.

---

### Task 7: Chat, Graph, Workflow, And Artifact Manual Validation

**Files:**
- Use project: `%TEMP%/alita-release-validation-<timestamp>/projects/release-validation-copy.alita`
- Create via app: project artifact files under the temp project artifact directory
- Update: `docs/test-results/full-release-<timestamp>/manual-results.txt`

- [ ] **Step 1: Validate no-attachment prompt handling**

Manual:

1. Open or create a project in the release app.
2. Send this exact message without adding an attachment: `请把这个文档整理成一份中文报告。`
3. Confirm the assistant asks the user to attach the document.

Record:

```powershell
"PASS manual: No-attachment document prompt requested an attachment." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
```

Expected: the response does not pretend to process a missing document.

- [ ] **Step 2: Validate normal chat**

Manual:

1. Send this exact message: `用一句中文说明你已经准备好执行发布验收测试。`
2. Confirm the assistant returns a relevant Chinese response and does not say the local model is disabled.

Record:

```powershell
"PASS manual: Normal chat returned a model-backed response." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
```

Expected: assistant responds through the sidecar/model path.

- [ ] **Step 3: Validate attachment graph generation**

Manual:

1. Add `$sampleDocx` as an attachment.
2. Send this exact message: `请把附件整理成结构化中文报告，生成 Markdown 摘要，并导出 PDF。`
3. Wait until the node graph appears.
4. Confirm the graph includes document input, conversion, model, Typst or export, and output-related nodes.
5. Confirm the layout is top-to-bottom.

Record:

```powershell
"PASS manual: Attachment prompt generated a top-to-bottom node graph." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
```

Expected: node graph is visible and not blank.

- [ ] **Step 4: Validate node popovers**

Manual:

1. Click each visible node.
2. Confirm each popover shows node type, capability, inputs, outputs, dependency summary, and recent run information when available.
3. Confirm model nodes do not show raw unknown model ids as primary user text.
4. Confirm tool nodes do not show raw unknown tool ids as primary user text.

Record:

```powershell
"PASS manual: Node popovers showed user-facing details and recent run data." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
```

Expected: node popovers explain what each node does.

- [ ] **Step 5: Run the full workflow**

Manual:

1. Click `运行流程`.
2. Wait until the run completes.
3. Confirm node states progress through running and finish as succeeded, or fail with an explicit user-visible error.
4. If the run succeeds, confirm artifact refs appear in node details or the artifact preview panel.

Record:

```powershell
"PASS manual: Full workflow run completed with visible node states and artifact refs." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
Get-ChildItem -LiteralPath $testRoot -Recurse -File -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -match "\\artifacts\\" -or $_.Extension -in @(".md",".pdf",".typ",".txt") } |
  Select-Object Name,Length,FullName |
  Tee-Object -FilePath "$evidenceRoot\artifact-inventory-after-run.txt"
```

Expected: run completes successfully with artifact outputs. If it fails, the error code and failing node are recorded as a release issue.

- [ ] **Step 6: Validate artifact preview, open, and reveal**

Manual:

1. Select a Markdown or text artifact.
2. Confirm content appears in the preview panel.
3. Select a PDF artifact if one was generated.
4. Confirm PDF preview renders or shows a clear PDF fallback with filename.
5. Click artifact `打开`.
6. Confirm Windows opens the artifact with the default file handler.
7. Click artifact `定位`.
8. Confirm File Explorer opens at the artifact location.

Record:

```powershell
"PASS manual: Artifact preview, open, and reveal worked for generated outputs." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
```

Expected: artifact paths match files under the test project artifact directory.

- [ ] **Step 7: Validate disabled tool failure**

Manual:

1. Open Preferences.
2. Disable the MarkItDown document conversion tool.
3. Return to the workbench.
4. Run the same document workflow again.
5. Confirm the run fails at the disabled tool.
6. Confirm the error code or message includes `tool_disabled`.

Record:

```powershell
"PASS manual: Disabled MarkItDown tool produced tool_disabled failure." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
```

Expected: disabled tool is not executed.

- [ ] **Step 8: Validate retry after re-enabling tool**

Manual:

1. Open Preferences.
2. Re-enable the MarkItDown document conversion tool.
3. Return to the workbench.
4. Retry the failed run or rerun the workflow.
5. Confirm `tool_disabled` does not recur.

Record:

```powershell
"PASS manual: Re-enabled MarkItDown allowed retry or rerun without tool_disabled." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
```

Expected: workflow can proceed after re-enabling the tool.

- [ ] **Step 9: Validate cancel behavior**

Manual:

1. Start a workflow run that invokes the model.
2. Click cancel while a node is running.
3. If the run finishes before cancellation is possible, record that the run completed before cancel could be triggered.
4. If cancellation is triggered, confirm UI enters a cancelling or stopped state and no new orphan child process remains.

Record cancellation success:

```powershell
"PASS manual: Cancel stopped an active workflow run." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
Get-Process -Name alita,alita-agent-sidecar,llama-server -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,Path |
  Tee-Object -FilePath "$evidenceRoot\processes-after-cancel.txt"
```

Record fast-completion case:

```powershell
"P2 manual: Cancel was not reproducible because the workflow completed before cancellation could be triggered." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
```

Expected: if cancellation occurs, the app does not keep writing new artifacts after cancellation.

---

### Task 8: Restart Persistence And Normal Shutdown

**Files:**
- Read: `%TEMP%/alita-release-validation-<timestamp>/projects/release-validation-copy.alita`
- Create: `docs/test-results/full-release-<timestamp>/processes-after-close.txt`
- Create: `docs/test-results/full-release-<timestamp>/processes-after-restart.txt`

- [ ] **Step 1: Save active project and close app normally**

Manual:

1. Click `保存`.
2. Close the Alita window with the standard window close button.
3. Wait 10 seconds.

Run:

```powershell
Start-Sleep -Seconds 10
Get-Process -Name alita,alita-agent-sidecar,llama-server -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,Path |
  Tee-Object -FilePath "$evidenceRoot\processes-after-close.txt"
```

Expected: no Alita-owned `alita`, `alita-agent-sidecar`, or `llama-server` process remains. If unrelated same-name processes exist, record their paths.

- [ ] **Step 2: Restart release app**

Run:

```powershell
$releaseProcess = Start-Process -FilePath $releaseExe -WorkingDirectory (Split-Path -Parent $releaseExe) -PassThru
Start-Sleep -Seconds 20
Get-Process -Name alita,alita-agent-sidecar,llama-server -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,MainWindowTitle,Path |
  Tee-Object -FilePath "$evidenceRoot\processes-after-restart.txt"
Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 5 |
  ConvertTo-Json -Depth 4 |
  Tee-Object -FilePath "$evidenceRoot\sidecar-health-after-restart.txt"
Invoke-RestMethod -Uri "http://127.0.0.1:8766/health" -TimeoutSec 10 |
  ConvertTo-Json -Depth 4 |
  Tee-Object -FilePath "$evidenceRoot\llama-health-after-restart.txt"
```

Expected: app, sidecar, and llama.cpp are running; both health checks succeed.

- [ ] **Step 3: Validate persisted app and project state**

Manual:

1. Open Preferences.
2. Confirm model storage path, default real model, scanned model, and tool enablement state are preserved.
3. Open `$projectRoot\release-validation-copy.alita` from recent projects or `打开工程`.
4. Confirm chat messages are present.
5. Confirm the node graph is present.
6. Confirm run history is present.
7. Confirm artifact refs are present.
8. Confirm artifact files still open or preview.

Record:

```powershell
"PASS manual: Restart restored preferences, project, chat, graph, run history, and artifact refs." |
  Add-Content -LiteralPath "$evidenceRoot\manual-results.txt"
Get-Content -LiteralPath (Join-Path $projectRoot "release-validation-copy.alita") -Raw |
  Tee-Object -FilePath "$evidenceRoot\copied-project-after-restart.json"
Get-Content -LiteralPath $prefsPath -Raw |
  Tee-Object -FilePath "$evidenceRoot\preferences-after-restart.json"
```

Expected: persisted state matches the state created earlier in the validation run.

---

### Task 9: Final Evidence Review And Summary

**Files:**
- Read: `docs/test-results/full-release-<timestamp>/*`
- Create: `docs/test-results/full-release-<timestamp>/summary.md`

- [ ] **Step 1: Scan evidence for unexpected failure markers**

Run:

```powershell
$failurePatterns = @(
  "FAILED",
  "Traceback",
  "panic",
  "error:",
  "FAIL:",
  "BLOCKED:",
  "本地模型暂未启用",
  "invalid sidecar token"
)
Select-String -Path "$evidenceRoot\*.txt","$evidenceRoot\*.json","$evidenceRoot\*.md" -Pattern $failurePatterns -CaseSensitive |
  Tee-Object -FilePath "$evidenceRoot\failure-scan.txt"
```

Expected: `failure-scan.txt` is empty or contains only expected lines that are explicitly explained in `summary.md`.

- [ ] **Step 2: Count manual checklist status**

Run:

```powershell
Get-Content -LiteralPath "$evidenceRoot\manual-results.txt" -ErrorAction SilentlyContinue |
  Tee-Object -FilePath "$evidenceRoot\manual-results-final.txt"

$manualPassCount = (Select-String -Path "$evidenceRoot\manual-results.txt" -Pattern "^PASS manual:" -ErrorAction SilentlyContinue | Measure-Object).Count
$manualP2Count = (Select-String -Path "$evidenceRoot\manual-results.txt" -Pattern "^P2 manual:" -ErrorAction SilentlyContinue | Measure-Object).Count
"manualPassCount=$manualPassCount" | Tee-Object -FilePath "$evidenceRoot\manual-counts.txt"
"manualP2Count=$manualP2Count" | Tee-Object -FilePath "$evidenceRoot\manual-counts.txt" -Append
```

Expected: manual pass count reflects completed manual records; P2 count is zero unless cancel was too fast to reproduce.

- [ ] **Step 3: Write final summary**

Run:

```powershell
$hasBlocked = Select-String -Path "$evidenceRoot\*.txt","$evidenceRoot\*.json","$evidenceRoot\*.md" -Pattern "BLOCKED:" -CaseSensitive -ErrorAction SilentlyContinue
$hasFail = Select-String -Path "$evidenceRoot\*.txt","$evidenceRoot\*.json","$evidenceRoot\*.md" -Pattern "FAIL:" -CaseSensitive -ErrorAction SilentlyContinue
$result = "Pass"
if ($hasFail) { $result = "Fail" }
elseif ($hasBlocked) { $result = "Blocked" }

@"
# Alita Full Release Validation Summary

## Result
- Overall: $result
- Date: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
- Evidence folder: $evidenceRoot
- Test root: $testRoot
- Release executable: $releaseExe
- Runtime model: $modelPath

## Automated Gates
- desktop prerequisites: see desktop-prereqs.txt
- frontend lint: see frontend-lint.txt
- frontend tests: see frontend-test.txt
- Python pytest: see python-pytest.txt
- Rust fmt: see rust-fmt.txt
- Rust cargo test: see rust-cargo-test.txt
- frontend build: see frontend-build.txt

## Packaging
- desktop build: see desktop-build.txt
- release outputs: see release-output-checks.txt
- bundle inventory: see nsis-bundle-output.txt
- llama runtime inventory: see llama-runtime-output.txt

## Runtime
- processes: see runtime-processes.txt
- ports: see runtime-ports.txt
- window title: see window-title.txt
- sidecar health: see sidecar-health.txt
- llama health: see llama-health.txt

## Manual Workflows
- manual records: see manual-results-final.txt
- checklist: see manual-checklist.md
- preferences after restart: see preferences-after-restart.json
- copied project after restart: see copied-project-after-restart.json

## Failure Scan
- failure scan: see failure-scan.txt

## Release Decision
- Pass means this build can proceed to release from the tested machine.
- Fail means release must stop until the recorded product defect is fixed and this plan is rerun from the failed layer.
- Blocked means the environment or external dependency must be fixed before release can be judged.
"@ | Set-Content -LiteralPath "$evidenceRoot\summary.md" -Encoding UTF8

Get-Content -LiteralPath "$evidenceRoot\summary.md"
```

Expected: `summary.md` exists and its `Overall` value is `Pass`, `Fail`, or `Blocked`.

---

### Task 10: Restore User State

**Files:**
- Restore/delete: `%APPDATA%/com.alita.ai-workbench/preferences.json`
- Create: `docs/test-results/full-release-<timestamp>/restore-status.txt`

- [ ] **Step 1: Close release app normally**

Run:

```powershell
$runningAlita = Get-Process -Name alita -ErrorAction SilentlyContinue | Select-Object -First 1
if ($runningAlita) {
  [void]$runningAlita.CloseMainWindow()
  Start-Sleep -Seconds 10
}
Get-Process -Name alita,alita-agent-sidecar,llama-server -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,Path |
  Tee-Object -FilePath "$evidenceRoot\processes-before-restore.txt"
```

Expected: app closes normally. Remaining Alita-owned processes are recorded before restore.

- [ ] **Step 2: Restore preferences backup**

Run:

```powershell
$prefsDir = Split-Path -Parent $prefsPath
New-Item -ItemType Directory -Force -Path $prefsDir | Out-Null
if (Test-Path -LiteralPath $prefsBackup -PathType Leaf) {
  Copy-Item -LiteralPath $prefsBackup -Destination $prefsPath -Force
  "Restored preferences from $prefsBackup to $prefsPath" |
    Tee-Object -FilePath "$evidenceRoot\restore-status.txt"
} else {
  Remove-Item -LiteralPath $prefsPath -Force -ErrorAction SilentlyContinue
  "Removed test-created preferences because no pre-test preferences backup existed." |
    Tee-Object -FilePath "$evidenceRoot\restore-status.txt"
}
Get-Content -LiteralPath "$evidenceRoot\restore-status.txt"
```

Expected: original preferences are restored, or test-created preferences are removed when no original file existed.

- [ ] **Step 3: Record final process and port state**

Run:

```powershell
Get-Process -Name alita,alita-agent-sidecar,llama-server,node,python,cargo -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,Path |
  Tee-Object -FilePath "$evidenceRoot\processes-final.txt"

Get-NetTCPConnection -LocalPort 1420,8765,8766 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,OwningProcess |
  Tee-Object -FilePath "$evidenceRoot\ports-final.txt"
```

Expected: no Alita-owned release validation process remains unless the tester intentionally left the app open after recording it.

---

## Execution Handoff

Execute tasks in order. A valid full release validation run produces:

- `docs/test-results/full-release-<timestamp>/summary.md`
- `docs/test-results/full-release-<timestamp>/manual-results-final.txt`
- `docs/test-results/full-release-<timestamp>/failure-scan.txt`
- restored user preferences
- no unexpected Alita-owned child processes after normal shutdown

The release can be considered validated only when `summary.md` says `Overall: Pass` and no P0 or P1 failures are recorded.
