$ErrorActionPreference = "Stop"

function Test-AlitaLlamaRuntimeInstalled {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RuntimeDir
    )

    if (-not (Test-Path -LiteralPath $RuntimeDir -PathType Container)) {
        return $false
    }

    $requiredFiles = @(
        "llama-server.exe",
        "VERSION.txt",
        "ggml.dll",
        "ggml-base.dll",
        "llama.dll",
        "llama-common.dll"
    )

    foreach ($fileName in $requiredFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $RuntimeDir $fileName) -PathType Leaf)) {
            return $false
        }
    }

    $cpuDll = Get-ChildItem -LiteralPath $RuntimeDir -Filter "ggml-cpu*.dll" -File -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $cpuDll) {
        return $false
    }

    $versionProperties = @{}
    foreach ($line in (Get-Content -LiteralPath (Join-Path $RuntimeDir "VERSION.txt") -ErrorAction Stop)) {
        if ($line -match "^([^=]+)=(.*)$") {
            $versionProperties[$Matches[1]] = $Matches[2]
        }
    }

    switch ($versionProperties["backend"]) {
        "cpu" {
            return $true
        }
        "cuda" {
            if (-not (Test-Path -LiteralPath (Join-Path $RuntimeDir "ggml-cuda.dll") -PathType Leaf)) {
                return $false
            }

            $cudartDll = Get-ChildItem -LiteralPath $RuntimeDir -Filter "cudart*.dll" -File -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($null -eq $cudartDll) {
                return $false
            }

            $cublasDll = Get-ChildItem -LiteralPath $RuntimeDir -Filter "cublas64_*.dll" -File -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($null -eq $cublasDll) {
                return $false
            }

            $cublasLtDll = Get-ChildItem -LiteralPath $RuntimeDir -Filter "cublasLt64_*.dll" -File -ErrorAction SilentlyContinue |
                Select-Object -First 1
            return $null -ne $cublasLtDll
        }
        default {
            return $false
        }
    }
}

function Test-AlitaForceLlamaRuntimeRefresh {
    $value = $env:ALITA_REFRESH_LLAMA_RUNTIME
    return $value -in @("1", "true", "TRUE", "yes", "YES")
}
