# Windows Desktop Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前浏览器开发版收进真正的 Windows Tauri 独立应用窗口，并为后续打包成 Windows 安装包做好 sidecar 方案。

**Architecture:** React UI 继续作为前端界面，但不再由用户直接打开浏览器访问，而是由 Tauri WebView 承载为 Windows 原生窗口。Python LangGraph/FastAPI Agent sidecar 在开发阶段由启动脚本管理，在打包阶段转换成 Windows sidecar 可执行文件并由 Tauri 生命周期管理。

**Tech Stack:** Tauri 2.11.1, Rust MSVC toolchain, Microsoft C++ Build Tools, Microsoft Edge WebView2, React 19, Vite 8, Python 3.12, FastAPI, LangGraph, PyInstaller.

**Primary References:**
- Tauri Windows 前置条件：<https://v2.tauri.app/start/prerequisites/>
- Tauri sidecar / external binary：<https://v2.tauri.app/zh-cn/develop/sidecar/>
- Microsoft C++ Build Tools 说明：<https://learn.microsoft.com/en-us/cpp/build/projects-and-build-systems-cpp?view=msvc-170>

---

## 当前判断

现在 `http://127.0.0.1:1420/` 是 Vite 浏览器开发预览。真正的 Windows 软件窗口需要 `npm run dev` 启动 Tauri，但当前机器运行 Rust/Tauri 时被 `link.exe` 缺失阻塞。`link.exe` 属于 MSVC Build Tools 工具链，因此第一步必须先把 Windows 编译环境补齐。

目标交付分两级：

1. **开发版独立窗口：** 运行 `npm run desktop:dev`，自动启动 Python Agent sidecar，并打开 Tauri Windows 窗口。
2. **可分发安装包：** 运行 `npm run desktop:build`，构建 Tauri 安装包，并把 Python sidecar 作为 external binary 捆绑。

---

## File Structure

- Create: `scripts/check-windows-tauri-prereqs.ps1`
  - 检查 MSVC、`link.exe`、Rust MSVC toolchain、WebView2、Node、Python。
- Create: `scripts/dev-desktop.ps1`
  - 开发阶段统一启动入口：先确保 sidecar 可用，再运行 `npm run dev` 打开 Tauri 窗口。
- Create: `scripts/build-sidecar.ps1`
  - 使用 PyInstaller 把 Python Agent sidecar 打成 Windows 可执行文件。
- Create: `scripts/build-windows-app.ps1`
  - 构建 sidecar，再执行 Tauri build。
- Modify: `package.json`
  - 增加桌面启动、桌面构建、环境检查脚本。
- Modify: `src-tauri/tauri.conf.json`
  - 调整窗口标题、尺寸、bundle 配置、externalBin 占位。
- Create: `src-tauri/src/sidecar.rs`
  - 后续打包阶段由 Rust 管理 sidecar 生命周期。
- Modify: `src-tauri/src/lib.rs`
  - 注册 sidecar 生命周期和现有 Tauri command。
- Create: `src-tauri/tests/sidecar_tests.rs`
  - 测试 sidecar 命令构造和端口健康检查逻辑。
- Modify: `python/pyproject.toml`
  - 增加 PyInstaller 到可选打包依赖。
- Create: `docs/windows-desktop-runbook.md`
  - 给出安装依赖、启动桌面窗口、构建安装包的人工说明。

---

## Task 1: Verify Windows Tauri Prerequisites

**Files:**
- Create: `scripts/check-windows-tauri-prereqs.ps1`

- [x] **Step 1: Create prerequisite checker**

Create `scripts/check-windows-tauri-prereqs.ps1`:

```powershell
$ErrorActionPreference = "Stop"

function Assert-Command {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$InstallHint
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "$Name was not found. $InstallHint"
    }

    Write-Host "[ok] $Name -> $($command.Source)"
}

function Test-WebView2 {
    $paths = @(
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients",
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients"
    )

    foreach ($path in $paths) {
        if (Test-Path $path) {
            $match = Get-ChildItem $path -ErrorAction SilentlyContinue |
                Get-ItemProperty |
                Where-Object { $_.name -like "*WebView2*" }
            if ($match) {
                Write-Host "[ok] Microsoft Edge WebView2 runtime is installed."
                return
            }
        }
    }

    Write-Warning "Microsoft Edge WebView2 runtime was not found in registry. Windows 10 1803+ or Windows 11 usually already has it; install WebView2 Evergreen Runtime if Tauri reports a WebView2 error."
}

Assert-Command "node" "Install Node.js LTS."
Assert-Command "npm" "Install Node.js LTS."
Assert-Command "python" "Install Python 3.10+ and add it to PATH."
Assert-Command "rustup" "Install Rust through rustup."
Assert-Command "cargo" "Install Rust through rustup."

$toolchain = rustup show active-toolchain
Write-Host "[info] Rust active toolchain: $toolchain"
if ($toolchain -notmatch "msvc") {
    throw "Rust is not using the MSVC toolchain. Run: rustup default stable-x86_64-pc-windows-msvc"
}

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
    throw "Visual Studio Installer / vswhere was not found. Install Visual Studio Build Tools and select 'Desktop development with C++'."
}

$installationPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $installationPath) {
    throw "MSVC C++ tools were not found. Install Visual Studio Build Tools and select 'Desktop development with C++'."
}
Write-Host "[ok] Visual Studio Build Tools -> $installationPath"

Test-WebView2
Write-Host ""
Write-Host "Prerequisite scan completed. If cargo still cannot find link.exe, restart PowerShell after installing Build Tools and rerun this script."
```

- [x] **Step 2: Add npm script**

Modify `package.json` scripts:

```json
"check:desktop-prereqs": "powershell -ExecutionPolicy Bypass -File scripts/check-windows-tauri-prereqs.ps1"
```

- [x] **Step 3: Run prerequisite checker**

Run:

```powershell
npm run check:desktop-prereqs
```

Expected before installing Build Tools: FAIL with a clear message about Visual Studio Build Tools or MSVC tools.

Expected after installing Build Tools: PASS, then `cargo test` can proceed past the previous `link.exe` error.

Observed on 2026-05-09: Node, npm, Python, rustup, cargo, the MSVC Rust toolchain, Visual Studio Build Tools, `link.exe`, and WebView2 are present. `npm run check:desktop-prereqs` passes.

---

## Task 2: Add a Single Desktop Development Startup Command

**Files:**
- Create: `scripts/dev-desktop.ps1`
- Modify: `package.json`

- [x] **Step 1: Create desktop dev launcher**

Create `scripts/dev-desktop.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$sidecarPort = 8765
$sidecarStartedHere = $false
$sidecarProcess = $null

function Test-HttpOk {
    param([string]$Url)

    try {
        $response = Invoke-RestMethod -Uri $Url -TimeoutSec 2
        return $null -ne $response
    }
    catch {
        return $false
    }
}

Push-Location $repoRoot
try {
    if (-not (Test-HttpOk "http://127.0.0.1:$sidecarPort/health")) {
        Write-Host "Starting Python Agent sidecar on 127.0.0.1:$sidecarPort..."
        $sidecarProcess = Start-Process `
            -FilePath "python" `
            -ArgumentList @("-m", "uvicorn", "agent_service.app:app", "--host", "127.0.0.1", "--port", "$sidecarPort") `
            -WorkingDirectory (Join-Path $repoRoot "python") `
            -PassThru `
            -WindowStyle Hidden
        $sidecarStartedHere = $true

        for ($attempt = 1; $attempt -le 20; $attempt++) {
            if (Test-HttpOk "http://127.0.0.1:$sidecarPort/health") {
                break
            }
            Start-Sleep -Milliseconds 500
        }

        if (-not (Test-HttpOk "http://127.0.0.1:$sidecarPort/health")) {
            throw "Python Agent sidecar did not become healthy on port $sidecarPort."
        }
    }

    Write-Host "Starting Tauri desktop window..."
    npm run dev
}
finally {
    if ($sidecarStartedHere -and $sidecarProcess -and -not $sidecarProcess.HasExited) {
        Stop-Process -Id $sidecarProcess.Id -Force
    }
    Pop-Location
}
```

- [x] **Step 2: Add npm desktop scripts**

Modify `package.json` scripts:

```json
"sidecar:dev": "python -m uvicorn agent_service.app:app --host 127.0.0.1 --port 8765",
"desktop:dev": "powershell -ExecutionPolicy Bypass -File scripts/dev-desktop.ps1"
```

- [x] **Step 3: Start desktop dev app**

Run:

```powershell
npm run desktop:dev
```

Expected after Build Tools are installed: a Tauri Windows application window opens. The user should no longer need to type `http://127.0.0.1:1420/` into a browser.

Observed on 2026-05-09: `npm run desktop:dev` starts the sidecar as needed, launches Vite on `127.0.0.1:1420`, and opens the Tauri desktop window.

---

## Task 3: Polish the Tauri Window Configuration

**Files:**
- Modify: `src-tauri/tauri.conf.json`

- [x] **Step 1: Update product and window settings**

Modify `src-tauri/tauri.conf.json`:

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "Alita",
  "version": "0.1.0",
  "identifier": "com.alita.ai-workbench",
  "build": {
    "beforeDevCommand": "npm run frontend:dev",
    "beforeBuildCommand": "npm run frontend:build",
    "devUrl": "http://127.0.0.1:1420",
    "frontendDist": "../dist"
  },
  "app": {
    "windows": [
      {
        "label": "main",
        "title": "Alita",
        "width": 1280,
        "height": 820,
        "minWidth": 1024,
        "minHeight": 680,
        "center": true,
        "resizable": true
      }
    ],
    "security": {
      "csp": null
    }
  },
  "bundle": {
    "active": true,
    "targets": ["nsis"],
    "icon": []
  }
}
```

- [x] **Step 2: Verify window opens with Chinese title**

Run:

```powershell
npm run desktop:dev
```

Expected: Windows taskbar/window title shows `Alita`; app window size is close to 1280x820.

Observed on 2026-05-09: `tauri.conf.json` validates as JSON, contains the Chinese title/window settings, and the real Tauri window opens with the title `Alita`.

---

## Task 4: Add Sidecar Lifecycle Boundary in Rust

**Files:**
- Create: `src-tauri/src/sidecar.rs`
- Modify: `src-tauri/src/lib.rs`
- Test: `src-tauri/tests/sidecar_tests.rs`

- [x] **Step 1: Write sidecar tests**

Create `src-tauri/tests/sidecar_tests.rs`:

```rust
#[path = "../src/sidecar.rs"]
mod sidecar;

#[test]
fn dev_sidecar_command_uses_python_uvicorn() {
    let command = sidecar::dev_sidecar_command();

    assert_eq!(command.program, "python");
    assert_eq!(
        command.args,
        vec![
            "-m",
            "uvicorn",
            "agent_service.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8765"
        ]
    );
}

#[test]
fn health_url_targets_local_agent_port() {
    assert_eq!(
        sidecar::agent_health_url(),
        "http://127.0.0.1:8765/health"
    );
}
```

- [x] **Step 2: Implement sidecar boundary**

Create `src-tauri/src/sidecar.rs`:

```rust
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SidecarCommand {
    pub program: &'static str,
    pub args: Vec<&'static str>,
}

pub fn agent_health_url() -> &'static str {
    "http://127.0.0.1:8765/health"
}

pub fn dev_sidecar_command() -> SidecarCommand {
    SidecarCommand {
        program: "python",
        args: vec![
            "-m",
            "uvicorn",
            "agent_service.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
        ],
    }
}
```

- [x] **Step 3: Wire module**

Modify `src-tauri/src/lib.rs`:

```rust
pub mod sidecar;
```

Keep the existing module declarations and existing `submit_user_message` command registration.

- [x] **Step 4: Run Rust tests**

Run:

```powershell
cd src-tauri
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --test sidecar_tests
```

Expected after Build Tools are installed: tests pass.

Observed on 2026-05-09: `cargo fmt --check` passes. Rust tests pass after loading the Visual Studio C++ build environment.

---

## Task 5: Prepare Python Sidecar Packaging

**Files:**
- Modify: `python/pyproject.toml`
- Create: `scripts/build-sidecar.ps1`

- [x] **Step 1: Add packaging dependency**

Modify `python/pyproject.toml`:

```toml
[project.optional-dependencies]
test = ["pytest"]
package = ["pyinstaller"]
```

Keep existing dependencies such as `fastapi`, `langgraph`, `pydantic`, `python-docx`, and `uvicorn`.

- [x] **Step 2: Create sidecar build script**

Create `scripts/build-sidecar.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonRoot = Join-Path $repoRoot "python"
$binaryDir = Join-Path $repoRoot "src-tauri\binaries"

New-Item -ItemType Directory -Force -Path $binaryDir | Out-Null

Push-Location $pythonRoot
try {
    python -m pip install -e ".[package]"
    python -m PyInstaller `
        --noconfirm `
        --onefile `
        --name "alita-agent-sidecar" `
        --collect-all "langgraph" `
        --collect-all "langchain_core" `
        --collect-all "docx" `
        -m "uvicorn" "agent_service.app:app" "--host" "127.0.0.1" "--port" "8765"

    $exe = Join-Path $pythonRoot "dist\alita-agent-sidecar.exe"
    if (-not (Test-Path $exe)) {
        throw "PyInstaller did not create $exe"
    }

    Copy-Item $exe (Join-Path $binaryDir "alita-agent-sidecar-x86_64-pc-windows-msvc.exe") -Force
}
finally {
    Pop-Location
}
```

- [x] **Step 3: Build sidecar executable**

Run:

```powershell
.\scripts\build-sidecar.ps1
```

Expected: `src-tauri\binaries\alita-agent-sidecar-x86_64-pc-windows-msvc.exe` exists.

Observed on 2026-05-09: PyInstaller successfully built `src-tauri\binaries\alita-agent-sidecar-x86_64-pc-windows-msvc.exe`.

---

## Task 6: Configure Tauri Bundle for the Sidecar

**Files:**
- Modify: `src-tauri/tauri.conf.json`
- Modify: `src-tauri/Cargo.toml`
- Modify: `src-tauri/src/lib.rs`

- [x] **Step 1: Add shell plugin dependency**

Modify `src-tauri/Cargo.toml`:

```toml
tauri-plugin-shell = "2"
```

Keep existing dependencies.

- [x] **Step 2: Register shell plugin**

Modify `src-tauri/src/lib.rs`:

```rust
tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
    .invoke_handler(tauri::generate_handler![commands::submit_user_message])
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
```

- [x] **Step 3: Add external binary to bundle config**

Modify `src-tauri/tauri.conf.json` bundle block:

```json
"bundle": {
  "active": true,
  "targets": ["nsis"],
  "externalBin": ["binaries/alita-agent-sidecar"],
  "icon": []
}
```

- [x] **Step 4: Run Tauri build**

Run:

```powershell
npm run desktop:build
```

Expected after Build Tools and sidecar executable are present: Tauri creates a Windows installer under `src-tauri\target\release\bundle`.

Observed on 2026-05-09: `npm run desktop:build` includes the packaged sidecar and produces both the release executable and NSIS installer.

---

## Task 7: Add Windows Desktop Build Command

**Files:**
- Create: `scripts/build-windows-app.ps1`
- Modify: `package.json`

- [x] **Step 1: Create desktop build script**

Create `scripts/build-windows-app.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    npm run check:desktop-prereqs
    .\scripts\build-sidecar.ps1
    npm run build
}
finally {
    Pop-Location
}
```

- [x] **Step 2: Add npm script**

Modify `package.json` scripts:

```json
"desktop:build": "powershell -ExecutionPolicy Bypass -File scripts/build-windows-app.ps1"
```

- [x] **Step 3: Build packaged Windows app**

Run:

```powershell
npm run desktop:build
```

Expected: packaged Windows artifact appears in `src-tauri\target\release\bundle`.

Observed on 2026-05-09: `desktop:build` validates prerequisites, imports the Visual Studio build environment, packages the Python sidecar, and completes the Tauri Windows build.

---

## Task 8: Document the Desktop Workflow

**Files:**
- Create: `docs/windows-desktop-runbook.md`

- [x] **Step 1: Create runbook**

Create `docs/windows-desktop-runbook.md`:

```markdown
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

## 启动开发版桌面窗口

```powershell
npm run desktop:dev
```

预期结果：打开一个标题为 `Alita` 的 Windows 应用窗口。

## 构建安装包

```powershell
npm run desktop:build
```

预期结果：安装包输出到 `src-tauri\target\release\bundle`。

## 常见问题

如果看到 `link.exe not found`，说明 Visual Studio Build Tools 的 C++ 工具链没有安装完整，或安装后没有重启 PowerShell。
```

- [x] **Step 2: Verify instructions**

Run:

```powershell
npm run check:desktop-prereqs
```

Expected: if the machine is still missing Build Tools, the runbook explains the same root cause as the script output.

Observed on 2026-05-09: `docs/windows-desktop-runbook.md` documents the current desktop development and packaging workflow, including how the scripts load the Visual Studio build environment for `link.exe`.

---

## Task 9: Final Verification

**Files:**
- Modify: `docs/mvp-verification.md`

- [x] **Step 1: Update MVP verification doc**

Modify `docs/mvp-verification.md` and add:

```markdown
## 桌面窗口验证

运行：

```powershell
npm run desktop:dev
```

预期结果：应用以 Windows 独立窗口打开，而不是要求用户手动打开浏览器地址。
```

- [x] **Step 2: Run automated verification**

Run:

```powershell
npm run frontend:test
npm run frontend:build
python -m pytest
cd src-tauri
& "$env:USERPROFILE\.cargo\bin\cargo.exe" fmt --check
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test
```

Expected after Build Tools installation:

- frontend tests pass
- frontend build passes
- Python tests pass
- Rust formatting passes
- Rust tests pass
- `npm run desktop:dev` opens a Windows application window

Observed on 2026-05-09: frontend tests/build pass, Python tests pass, Rust formatting/tests pass, sidecar packaging succeeds, the desktop dev command opens the real Windows window, the release executable starts its packaged sidecar automatically, closing the release window clears the sidecar listener on `127.0.0.1:8765`, and the desktop build command produces the NSIS installer.

---

## Self-Review Notes

- Spec coverage: This plan covers the missing desktop window path, Windows build prerequisites, development launch workflow, sidecar lifecycle, and packaged Windows app path.
- Known blocker: None for the current desktop-window milestone. Visual Studio Build Tools with the C++ workload and Windows SDK are installed and verified on this machine.
- Security note: `csp: null` is acceptable for the immediate development transition, but should be tightened before a public release.
- Packaging note: PyInstaller sidecar bundling should be treated as the first practical packaging path; later we can replace it with a Rust-native or embedded runtime strategy if startup size or antivirus friction becomes a problem.


