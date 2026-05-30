$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonRoot = Join-Path $repoRoot "python"
$binaryDir = Join-Path $repoRoot "src-tauri\binaries"

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage Exit code: $LASTEXITCODE"
    }
}

New-Item -ItemType Directory -Force -Path $binaryDir | Out-Null

Push-Location $pythonRoot
try {
    Invoke-NativeCommand {
        python -m pip install -e ".[package]"
    } "Python sidecar packaging dependencies could not be installed."

    Invoke-NativeCommand {
        python -m PyInstaller `
            --noconfirm `
            --onefile `
            --name "alita-agent-sidecar" `
            --paths "$pythonRoot" `
            --collect-submodules "agent_service" `
            --collect-all "langgraph" `
            --collect-all "langchain_core" `
            --collect-all "markitdown" `
            --collect-all "magika" `
            --collect-all "docx" `
            --add-data "$repoRoot\tool-packages;tool-packages" `
            "agent_service\sidecar_entry.py"
    } "PyInstaller did not build the Python sidecar."

    $exe = Join-Path $pythonRoot "dist\alita-agent-sidecar.exe"
    if (-not (Test-Path $exe)) {
        throw "PyInstaller did not create $exe"
    }

    Copy-Item $exe (Join-Path $binaryDir "alita-agent-sidecar-x86_64-pc-windows-msvc.exe") -Force

    $releaseBinary = Join-Path $repoRoot "src-tauri\target\release\alita-agent-sidecar.exe"
    $releaseDir = Split-Path $releaseBinary -Parent
    if (Test-Path $releaseDir) {
        Copy-Item $exe $releaseBinary -Force
    }
}
finally {
    Pop-Location
}
