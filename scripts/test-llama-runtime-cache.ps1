$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
. (Join-Path $PSScriptRoot "llama-runtime-cache.ps1")

function Assert-Equal {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Actual,
        [Parameter(Mandatory = $true)]
        [object]$Expected,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if ($Actual -ne $Expected) {
        throw "$Message Expected '$Expected', got '$Actual'."
    }
}

function Write-TestFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    Set-Content -LiteralPath (Join-Path $runtimeDir $Name) -Encoding ASCII -Value "placeholder"
}

function Write-VersionFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Backend
    )

    Set-Content -LiteralPath (Join-Path $runtimeDir "VERSION.txt") -Encoding ASCII -Value @(
        "release=test",
        "backend=$Backend"
    )
}

$testRoot = Join-Path $env:TEMP ("alita-llama-runtime-cache-test-" + [guid]::NewGuid().ToString("N"))
try {
    $runtimeDir = Join-Path $testRoot "llama-cpp"

    Assert-Equal `
        -Actual (Test-AlitaLlamaRuntimeInstalled -RuntimeDir $runtimeDir) `
        -Expected $false `
        -Message "Missing runtime directory should not be considered installed."

    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    Write-TestFile "llama-server.exe"
    Write-VersionFile "cpu"

    Assert-Equal `
        -Actual (Test-AlitaLlamaRuntimeInstalled -RuntimeDir $runtimeDir) `
        -Expected $false `
        -Message "Runtime without DLL files should not be considered installed."

    Write-TestFile "ggml.dll"

    Assert-Equal `
        -Actual (Test-AlitaLlamaRuntimeInstalled -RuntimeDir $runtimeDir) `
        -Expected $false `
        -Message "Runtime with only one DLL should not be considered installed."

    Write-TestFile "ggml-base.dll"
    Write-TestFile "ggml-cpu-x64.dll"
    Write-TestFile "llama.dll"
    Write-TestFile "llama-common.dll"

    Assert-Equal `
        -Actual (Test-AlitaLlamaRuntimeInstalled -RuntimeDir $runtimeDir) `
        -Expected $true `
        -Message "CPU runtime with required core DLLs should be considered installed."

    Remove-Item -LiteralPath (Join-Path $runtimeDir "VERSION.txt") -Force

    Assert-Equal `
        -Actual (Test-AlitaLlamaRuntimeInstalled -RuntimeDir $runtimeDir) `
        -Expected $false `
        -Message "Runtime without VERSION.txt should not be considered installed."

    Write-VersionFile "cuda"

    Assert-Equal `
        -Actual (Test-AlitaLlamaRuntimeInstalled -RuntimeDir $runtimeDir) `
        -Expected $false `
        -Message "CUDA runtime without CUDA backend DLLs should not be considered installed."

    Write-TestFile "ggml-cuda.dll"
    Write-TestFile "cudart64_13.dll"
    Write-TestFile "cublasLt64_13.dll"

    Assert-Equal `
        -Actual (Test-AlitaLlamaRuntimeInstalled -RuntimeDir $runtimeDir) `
        -Expected $false `
        -Message "CUDA runtime without cublas64 DLL should not be considered installed."

    Write-TestFile "cublas64_13.dll"

    Assert-Equal `
        -Actual (Test-AlitaLlamaRuntimeInstalled -RuntimeDir $runtimeDir) `
        -Expected $true `
        -Message "CUDA runtime with required core and backend DLLs should be considered installed."

    Write-Output "Llama runtime cache test passed."
}
finally {
    Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
}
