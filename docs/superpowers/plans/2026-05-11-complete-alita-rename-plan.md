# Complete Alita Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every project-owned file consistently use `Alita` as the project and software name, including all historical development plans and specifications.

**Architecture:** Treat this as a breaking final rename. Remove legacy brand compatibility paths, migrate or delete legacy sample data, regenerate build output, then enforce the result with a repeatable scanner. Third-party dependencies and binary model files are not project-owned naming surfaces.

**Tech Stack:** Tauri 2, Rust, React, TypeScript, Vite, Python FastAPI sidecar, PyInstaller, PowerShell validation scripts.

---

## Final Scope

This plan targets a strict final state:

- Product name, package names, app title, sidecar title, installer name, docs, development plans, sample data, and generated outputs use `Alita`.
- Legacy brand strings, legacy project extensions, legacy environment variables, and legacy auth headers are removed from project-owned files.
- Old compatibility behavior is intentionally removed. Keeping it would require old-name literals in source and tests, which conflicts with the requested full cleanup.
- `node_modules/`, `models/`, and opaque binary dependencies are not manually rewritten. Generated project-owned outputs are cleaned and rebuilt.

Current workspace note: `D:\Software Project\Alita` is not a Git repository. Replace commit checkpoints with a saved changed-file list unless a repository is initialized before execution.

## File Structure

Known source and test files to modify:

- `index.html`: browser document title.
- `src/features/project/projectApi.ts`: project file dialogs and fallback prompts.
- `src/app/App.tsx`: project name derivation from file name.
- `src/features/project/projectApi.test.ts` if present after scan: dialog expectations.
- `src-tauri/src/preferences.rs`: remove legacy preference directory lookup and path migration.
- `src-tauri/src/commands.rs`: load preferences from the current Alita path only.
- `src-tauri/src/llama_runtime.rs`: remove legacy environment-variable fallback.
- `src-tauri/tests/preferences_tests.rs`: replace legacy-migration tests with Alita-only preference tests.
- `src-tauri/tests/llama_runtime_tests.rs`: replace fallback tests with Alita-only env tests.
- `python/agent_service/app.py`: accept only the Alita sidecar token header and env var.
- `python/agent_service/model_client.py`: read only Alita model runtime env vars.
- `python/tests/test_app.py`: remove legacy auth-header test.
- `python/tests/test_model_client.py`: replace fallback env test with Alita-only env test.
- `docs/**/*.md`: normalize all development plans, specs, runbooks, and verification docs to Alita-only naming.
- `book files/**`: migrate or delete legacy sample project data.
- `scripts/check-alita-rename-clean.ps1`: new validation guard.

Generated and disposable files to clean or regenerate:

- `dist/`
- `src-tauri/target/`
- `python/build/`
- `python/dist/`
- `python/*.egg-info/`
- root `*.log`

---

### Task 1: Add a Rename-Clean Guard

**Files:**
- Create: `scripts/check-alita-rename-clean.ps1`

- [x] **Step 1: Create the scanner script**

Use `apply_patch` to create `scripts/check-alita-rename-clean.ps1` with this content:

```powershell
param(
    [switch]$IncludeGenerated
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptRoot "..")

$forbiddenTokens = @(
    ("Boo" + "ook"),
    ("boo" + "ook"),
    ("BOO" + "OOK"),
    ("." + "boo" + "ook"),
    ("X-" + "Boo" + "ook" + "-Sidecar-Token"),
    ("AI Agent" + " Productivity Tool"),
    ("AI Agent" + " Productivity Sidecar"),
    ("AI Agent" + " Productivity MVP"),
    ("AI Tool" + "-Using" + " Productivity Platform"),
    ("ai-agent" + "-productivity-tool"),
    ("boo" + "ook-agent-sidecar"),
    ("com." + "boo" + "ook.ai-workbench")
)

$excludedPrefixes = @(
    "node_modules\",
    ".git\",
    "models\"
)

if (-not $IncludeGenerated) {
    $excludedPrefixes += @(
        "dist\",
        "src-tauri\target\",
        "python\build\",
        "python\dist\",
        "python\alita_sidecar.egg-info\"
    )
}

$binaryExtensions = @(
    ".exe", ".dll", ".pdb", ".lib", ".rlib", ".o", ".obj", ".ilk", ".exp", ".res", ".zip", ".pyz", ".pkg",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".gguf", ".node", ".pyc"
)

$pattern = ($forbiddenTokens | ForEach-Object { [regex]::Escape($_) }) -join "|"
$files = & rg --files --hidden
$matches = New-Object System.Collections.Generic.List[string]

foreach ($file in $files) {
    $normalized = $file -replace "/", "\"
    $skip = $false
    foreach ($prefix in $excludedPrefixes) {
        if ($normalized.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $skip = $true
            break
        }
    }
    if ($skip) {
        continue
    }

    $extension = [System.IO.Path]::GetExtension($normalized)
    if ($binaryExtensions -contains $extension) {
        continue
    }

    $fullPath = Join-Path $repoRoot $file
    $fileMatches = Select-String -LiteralPath $fullPath -Pattern $pattern -CaseSensitive -AllMatches -ErrorAction SilentlyContinue
    foreach ($match in $fileMatches) {
        $matches.Add(("{0}:{1}: {2}" -f $file, $match.LineNumber, $match.Line.Trim()))
    }
}

if ($matches.Count -gt 0) {
    $matches | ForEach-Object { Write-Output $_ }
    Write-Error ("Found {0} legacy naming occurrence(s)." -f $matches.Count)
    exit 1
}

Write-Output "No forbidden legacy naming tokens found."
```

- [x] **Step 2: Run the scanner and confirm it fails now**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-alita-rename-clean.ps1
```

Expected: FAIL with matches in `index.html`, source fallback code, tests, docs, logs, and sample project data.

- [x] **Step 3: Save the baseline output**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-alita-rename-clean.ps1 *> rename-clean-baseline.txt
```

Expected: `rename-clean-baseline.txt` exists and records every remaining occurrence to burn down.

---

### Task 2: Remove Legacy Naming From Frontend Source

**Files:**
- Modify: `index.html`
- Modify: `src/features/project/projectApi.ts`
- Modify: `src/app/App.tsx`
- Test: frontend tests under `src/features/project/` and `src/app/`

- [x] **Step 1: Update the HTML title**

Change `index.html` so the title is exactly:

```html
<title>Alita</title>
```

- [x] **Step 2: Make project dialogs Alita-only**

In `src/features/project/projectApi.ts`, make these behavioral changes:

- Create fallback prompt asks for a `.alita` path.
- Open fallback prompt asks for a `.alita` path only.
- Open dialog filter has only `extensions: ["alita"]`.
- Save-as fallback prompt asks for a `.alita` path.
- Remove the helper that rewrites the legacy extension.
- Save-as default path uses `currentPath` when it already ends in `.alita`; otherwise append `.alita`.

Use this helper:

```ts
function ensureAlitaProjectPath(path: string): string {
  return /\.alita$/i.test(path) ? path : `${path}.alita`;
}
```

- [x] **Step 3: Update project-name derivation**

In `src/app/App.tsx`, change project creation name cleanup to strip only `.alita`:

```ts
const name = fileName.replace(/\.alita$/i, "");
```

- [x] **Step 4: Update frontend tests**

Run:

```powershell
rg -n "alita|legacy|extensions|projectApi|打开工程|新建工程" src\features src\app
```

Update tests so they assert:

- create default path is the unnamed Alita project file.
- open dialog accepts only the Alita extension.
- save-as returns an Alita path.

- [x] **Step 5: Verify frontend behavior**

Run:

```powershell
npm run frontend:test
npm run frontend:lint
```

Expected: both commands pass.

---

### Task 3: Remove Legacy Naming From Rust Runtime and Preferences

**Files:**
- Modify: `src-tauri/src/preferences.rs`
- Modify: `src-tauri/src/commands.rs`
- Modify: `src-tauri/src/llama_runtime.rs`
- Modify: `src-tauri/tests/preferences_tests.rs`
- Modify: `src-tauri/tests/llama_runtime_tests.rs`

- [x] **Step 1: Simplify preference loading**

In `src-tauri/src/preferences.rs`, delete:

- the legacy app-dir constant.
- the legacy candidate function.
- the legacy path migration function.
- the private legacy path text helper.
- the fallback-loading function.

Keep `load_preferences_from_path` as the single loading API.

- [x] **Step 2: Update command preference loading**

In `src-tauri/src/commands.rs`, change imports to remove legacy helpers, then update `load_preferences_for_app` to:

```rust
fn load_preferences_for_app(app: &AppHandle) -> Result<(PathBuf, AppPreferences), String> {
    let path = preferences_path(app)?;
    let mut preferences = load_preferences_from_path(&path)?;
    let default_storage_dir = default_model_storage_dir(app)?;
    let changed = ensure_model_storage_dir(&mut preferences, default_storage_dir)?;
    if changed {
        save_preferences_to_path(&path, &preferences)?;
    }
    Ok((path, preferences))
}
```

- [x] **Step 3: Update llama runtime env loading**

In `src-tauri/src/llama_runtime.rs`, remove legacy env constants and the `env_var_with_legacy` function. `from_env_with_preference` should read only:

```rust
Self::from_sources(
    env::var(MODEL_PATH_ENV).ok(),
    env::var(GPU_LAYERS_ENV).ok(),
    preference_model_path,
)
```

Also replace preference loading in `default_model_path_for_app` with `load_preferences_from_path(preferences_path)?`.

- [x] **Step 4: Update Rust tests**

In `src-tauri/tests/preferences_tests.rs`, remove legacy fallback and path-migration tests. Add or keep tests for:

- missing current preferences returns defaults.
- saving and loading current preferences works.
- default model storage directory is created under Alita app data.

In `src-tauri/tests/llama_runtime_tests.rs`, rename the env test to:

```rust
fn env_config_uses_alita_vars()
```

The test should set only `ALITA_LLAMA_MODEL_PATH` and `ALITA_LLAMA_GPU_LAYERS`, then assert the resulting config uses those values.

- [x] **Step 5: Verify Rust**

Run:

```powershell
Set-Location src-tauri
cargo test
Set-Location ..
```

Expected: all Rust tests pass.

---

### Task 4: Remove Legacy Naming From Python Sidecar

**Files:**
- Modify: `python/agent_service/app.py`
- Modify: `python/agent_service/model_client.py`
- Modify: `python/tests/test_app.py`
- Modify: `python/tests/test_model_client.py`

- [x] **Step 1: Make sidecar auth Alita-only**

In `python/agent_service/app.py`, keep only:

```python
SIDECAR_TOKEN_ENV = "ALITA_SIDECAR_TOKEN"
SIDECAR_TOKEN_HEADER = "X-Alita-Sidecar-Token"
```

Change `require_sidecar_token` to accept only `sidecar_token` and compare it with `os.getenv(SIDECAR_TOKEN_ENV)`.

- [x] **Step 2: Make model runtime env Alita-only**

In `python/agent_service/model_client.py`, remove `_env_with_legacy` usage. `ModelClientConfig.from_env` should read:

```python
model_path = os.getenv("ALITA_LLAMA_MODEL_PATH", "").strip()
return cls(
    enabled=bool(model_path),
    base_url=os.getenv("ALITA_LLAMA_BASE_URL", "http://127.0.0.1:8766").rstrip("/"),
    model=os.getenv("ALITA_LLAMA_MODEL_NAME", "local-llama-cpp"),
)
```

Delete `_env_with_legacy` if no longer used.

- [x] **Step 3: Update Python tests**

In `python/tests/test_app.py`, delete the legacy header acceptance test. Keep the Alita token-required test.

In `python/tests/test_model_client.py`, replace the env fallback test with an Alita-only test:

```python
def test_model_config_uses_alita_env(monkeypatch) -> None:
    monkeypatch.setenv("ALITA_LLAMA_MODEL_PATH", "D:\\Alita\\model.gguf")
    monkeypatch.setenv("ALITA_LLAMA_BASE_URL", "http://127.0.0.1:8766/")
    monkeypatch.setenv("ALITA_LLAMA_MODEL_NAME", "alita-model")

    config = ModelClientConfig.from_env()

    assert config.enabled
    assert config.base_url == "http://127.0.0.1:8766"
    assert config.model == "alita-model"
```

- [x] **Step 4: Verify Python**

Run:

```powershell
Set-Location python
python -m pytest
Set-Location ..
```

Expected: all Python tests pass.

---

### Task 5: Normalize All Development Plans and Specs

**Files:**
- Modify: `docs/**/*.md`
- Modify: `.superpowers/**` only if those files are intended to remain part of this project archive.

- [x] **Step 1: Generate a docs-only occurrence list**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-alita-rename-clean.ps1 *> rename-docs-pass-1.txt
Select-String -LiteralPath rename-docs-pass-1.txt -Pattern "^docs\\|^\.superpowers\\" | Set-Content rename-docs-only.txt
```

Expected: `rename-docs-only.txt` lists all planning/spec/runbook files that still mention legacy names.

- [x] **Step 2: Rewrite historical docs to Alita-only wording**

For each docs hit, preserve the design intent but remove literal legacy names. Use these replacements:

- legacy product name -> `Alita`
- legacy lowercase package name -> `alita`
- legacy upper env prefix -> `ALITA`
- legacy project extension -> `.alita`
- legacy sidecar binary name -> `alita-agent-sidecar`
- old English product phrase -> `Alita`
- old English MVP heading -> `Alita MVP Implementation Plan`

For historical rename documents, reframe them as naming-unification documents. Example title:

```markdown
# Alita 全项目命名统一设计
```

- [x] **Step 3: Rewrite development plans**

Apply the same policy to every file under `docs/superpowers/plans/`, including earlier implementation plans. If a plan describes a transition from a legacy name, rewrite it as a transition from “旧名称” without spelling the old string.

- [x] **Step 4: Decide whether `.superpowers/` is project archive or disposable cache**

If `.superpowers/` is a disposable local working cache, delete it after confirming no active task depends on it:

```powershell
Remove-Item -LiteralPath .superpowers -Recurse -Force
```

If it must remain as project archive, rewrite its HTML titles and content to Alita-only naming, then run the scanner again.

- [x] **Step 5: Verify docs**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-alita-rename-clean.ps1
```

Expected: no docs or source hits remain. Generated outputs may still be excluded until Task 7.

---

### Task 6: Migrate or Remove Legacy Sample Project Data

**Files:**
- Modify or delete: sample project data under `book files/`

- [x] **Step 1: Identify sample data hits**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-alita-rename-clean.ps1 *> rename-data-pass-1.txt
Select-String -LiteralPath rename-data-pass-1.txt -Pattern "^book files\\" | Set-Content rename-data-only.txt
```

Expected: `rename-data-only.txt` lists legacy project files and node-run JSON files.

- [x] **Step 2: Choose data policy**

Use one of these two policies:

- `Migrate`: keep sample data, rename legacy project files to `.alita`, update internal `path`, message content, artifact refs, and node-run JSON paths to `D:\Software Project\Alita\...`.
- `Delete`: remove old sample project and old node-run records if they are throwaway test artifacts.

For the current workspace, prefer `Migrate` for the main sample project and `Delete` for stale node-run records that point to missing artifacts.

- [x] **Step 3: Verify sample data**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-alita-rename-clean.ps1
```

Expected: no `book files\` hits remain.

---

### Task 7: Clean and Regenerate Build Outputs

**Files:**
- Delete/regenerate: `dist/`
- Delete/regenerate: `src-tauri/target/`
- Delete/regenerate: `python/build/`
- Delete/regenerate: `python/dist/`
- Delete/regenerate: `python/alita_sidecar.egg-info/`
- Delete: root `*.log`

- [x] **Step 1: Remove stale logs**

Run:

```powershell
Remove-Item -LiteralPath desktop-dev.log, desktop-dev.err.log, vite-1420.log, vite-1420.err.log -ErrorAction SilentlyContinue
```

Expected: stale logs no longer appear in scanner output.

- [x] **Step 2: Remove stale generated directories**

Verify the target paths are inside `D:\Software Project\Alita`, then run:

```powershell
Remove-Item -LiteralPath dist -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath python\build -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath python\dist -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath python\alita_sidecar.egg-info -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath src-tauri\target -Recurse -Force -ErrorAction SilentlyContinue
```

Expected: stale generated files are removed.

- [x] **Step 3: Rebuild frontend**

Run:

```powershell
npm run frontend:build
```

Expected: `dist/index.html` exists and its title is `Alita`.

- [x] **Step 4: Rebuild Python sidecar**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-sidecar.ps1
```

Expected: `src-tauri/binaries/alita-agent-sidecar-x86_64-pc-windows-msvc.exe` exists.

- [x] **Step 5: Rebuild desktop installer**

Run:

```powershell
npm run desktop:build
```

Expected: the NSIS setup executable is generated with `Alita` in the file name.

---

### Task 8: Final Verification

**Files:**
- Read-only verification over the whole workspace.

- [x] **Step 1: Run all test suites**

Run:

```powershell
npm run frontend:test
npm run frontend:lint
Set-Location python
python -m pytest
Set-Location ..
Set-Location src-tauri
cargo test
Set-Location ..
```

Expected: every command passes.

- [x] **Step 2: Run final source and docs scanner**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-alita-rename-clean.ps1
```

Expected:

```text
No forbidden legacy naming tokens found.
```

- [x] **Step 3: Run final generated-output scanner**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check-alita-rename-clean.ps1 -IncludeGenerated
```

Expected:

```text
No forbidden legacy naming tokens found.
```

- [x] **Step 4: Smoke-test product naming**

Run:

```powershell
npm run desktop:dev
```

Expected:

- Tauri window title is `Alita`.
- Project home headline is `Alita`.
- New project defaults to an Alita project file.
- Preferences default model directory is under an Alita app data path.
- Sidecar OpenAPI title is `Alita Agent Sidecar`.

- [x] **Step 5: Remove temporary audit files**

Run:

```powershell
Remove-Item -LiteralPath rename-clean-baseline.txt, rename-docs-pass-1.txt, rename-docs-only.txt, rename-data-pass-1.txt, rename-data-only.txt -ErrorAction SilentlyContinue
```

Expected: no temporary audit text files remain.

---

## Self-Review

Spec coverage:

- Source product and software names: covered by Tasks 2, 3, and 4.
- Development plans and specs from the beginning through now: covered by Task 5.
- Sample project data: covered by Task 6.
- Generated output and stale logs: covered by Task 7.
- Repeatable proof of completion: covered by Tasks 1 and 8.

Residual risk:

- Removing legacy compatibility is a breaking change for old project files, old env vars, and old sidecar headers.
- If old user data must still open, then the final scanner must allow a documented compatibility exception. That is not this plan’s target.
- Binary installers may contain compiler metadata that scanners cannot inspect safely; the final generated scan filters opaque binary formats and validates surrounding text outputs instead.


