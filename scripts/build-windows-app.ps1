$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if (Test-Path $cargoBin) {
    $env:PATH = "$cargoBin;$env:PATH"
}
. (Join-Path $PSScriptRoot "llama-runtime-cache.ps1")

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

Push-Location $repoRoot
try {
    Invoke-NativeCommand {
        npm run check:desktop-prereqs
    } "Desktop prerequisite check failed."

    . (Join-Path $PSScriptRoot "import-vs-dev-env.ps1")

    $llamaRuntimeDir = Join-Path $repoRoot "src-tauri\resources\llama-cpp"
    if ((Test-AlitaForceLlamaRuntimeRefresh) -or -not (Test-AlitaLlamaRuntimeInstalled -RuntimeDir $llamaRuntimeDir)) {
        .\scripts\install-llama-cpp.ps1
    }
    else {
        Write-Host "[ok] Reusing existing llama.cpp runtime -> $llamaRuntimeDir"
    }

    .\scripts\build-sidecar.ps1

    Invoke-NativeCommand {
        npm run build
    } "Tauri desktop build failed."
}
finally {
    Pop-Location
}
