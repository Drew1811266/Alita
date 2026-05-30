$ErrorActionPreference = "Stop"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Label"
    $global:LASTEXITCODE = 0
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$cargoPath = Join-Path $env:USERPROFILE ".cargo\bin\cargo.exe"
if (-not (Test-Path $cargoPath)) {
    $cargoPath = "cargo"
}

Push-Location $repoRoot
try {
    $vsEnvScript = Join-Path $PSScriptRoot "import-vs-dev-env.ps1"
    if (Test-Path $vsEnvScript) {
        . $vsEnvScript
    }

    Invoke-CheckedCommand "Frontend typecheck" {
        npm run frontend:lint
    }

    Invoke-CheckedCommand "Python tests" {
        Push-Location "python"
        try {
            python -m pytest
        }
        finally {
            Pop-Location
        }
    }

    Invoke-CheckedCommand "Agent eval deterministic gate" {
        Push-Location "python"
        try {
            python -m agent_service.eval_harness --cases-dir evals --output ..\.codex-run\evals
        }
        finally {
            Pop-Location
        }
    }

    $sidecarBinary = Join-Path $repoRoot "src-tauri\binaries\alita-agent-sidecar-x86_64-pc-windows-msvc.exe"
    if (-not (Test-Path $sidecarBinary)) {
        Invoke-CheckedCommand "Build Python sidecar binary for Rust tests" {
            & (Join-Path $repoRoot "scripts\build-sidecar.ps1")
        }
    }

    $llamaResourceDir = Join-Path $repoRoot "src-tauri\resources\llama-cpp"
    if (-not (Test-Path $llamaResourceDir)) {
        Invoke-CheckedCommand "Prepare Tauri resource directory for Rust tests" {
            New-Item -ItemType Directory -Force -Path $llamaResourceDir | Out-Null
        }
    }

    Invoke-CheckedCommand "Rust formatting" {
        Push-Location "src-tauri"
        try {
            & $cargoPath fmt --check
        }
        finally {
            Pop-Location
        }
    }

    Invoke-CheckedCommand "Rust tests" {
        Push-Location "src-tauri"
        try {
            $previousCargoTargetDir = $env:CARGO_TARGET_DIR
            $env:CARGO_TARGET_DIR = Join-Path (Get-Location) "target\verify"
            $previousErrorActionPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            $output = & $cargoPath test 2>&1
            $exitCode = $LASTEXITCODE
            $ErrorActionPreference = $previousErrorActionPreference
            $outputText = $output |
                ForEach-Object { $_.ToString() } |
                Where-Object { $_ -ne "System.Management.Automation.RemoteException" }
            $outputText | ForEach-Object { Write-Host $_ }

            if ($exitCode -ne 0) {
                $joined = $outputText -join "`n"
                if ($joined -match "link\.exe" -or $joined -match "MSVC linker") {
                    throw "Rust tests are blocked because the Windows MSVC linker is unavailable. Install Visual Studio Build Tools with the C++ toolchain and Windows SDK, then rerun this script."
                }

                throw "Rust tests failed with exit code $exitCode."
            }
        }
        finally {
            if ([string]::IsNullOrEmpty($previousCargoTargetDir)) {
                Remove-Item Env:CARGO_TARGET_DIR -ErrorAction SilentlyContinue
            }
            else {
                $env:CARGO_TARGET_DIR = $previousCargoTargetDir
            }

            if ($null -ne $previousErrorActionPreference) {
                $ErrorActionPreference = $previousErrorActionPreference
            }
            Pop-Location
        }
    }

    Write-Host ""
    Write-Host "MVP verification passed."
}
finally {
    Pop-Location
}
