$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$sidecarPort = 8765
$frontendPort = 1420
$sidecarStartedHere = $false
$sidecarProcess = $null
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if (Test-Path $cargoBin) {
    $env:PATH = "$cargoBin;$env:PATH"
}
. (Join-Path $PSScriptRoot "dev-sidecar-health.ps1")

Push-Location $repoRoot
try {
    & (Join-Path $PSScriptRoot "check-windows-tauri-prereqs.ps1")
    . (Join-Path $PSScriptRoot "import-vs-dev-env.ps1")
    . (Join-Path $PSScriptRoot "dev-model-env.ps1")
    Set-AlitaDevModelEnvironment -RepoRoot $repoRoot | Out-Null

    $frontendListeners = Get-NetTCPConnection -LocalPort $frontendPort -State Listen -ErrorAction SilentlyContinue
    if ($frontendListeners) {
        Write-Warning "Port $frontendPort is already in use. Close the existing browser preview dev server before starting the Tauri desktop window, otherwise Tauri may fail when it starts Vite."
    }

    if (-not (Test-AlitaSidecarHealthy "http://127.0.0.1:$sidecarPort/health")) {
        $sidecarListeners = Get-NetTCPConnection -LocalPort $sidecarPort -State Listen -ErrorAction SilentlyContinue
        if ($sidecarListeners) {
            $ownerIds = $sidecarListeners | Select-Object -ExpandProperty OwningProcess -Unique
            $owners = $ownerIds | ForEach-Object {
                $process = Get-Process -Id $_ -ErrorAction SilentlyContinue
                if ($process) {
                    "$($process.ProcessName)($_)"
                }
                else {
                    "pid $_"
                }
            }
            throw "Port $sidecarPort is already used by a non-Alita service: $($owners -join ', '). Stop it before starting Alita."
        }

        Write-Host "Starting Python Agent sidecar on 127.0.0.1:$sidecarPort..."
        $previousBypass = $env:ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV
        $env:ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV = "1"
        try {
            $sidecarProcess = Start-Process `
                -FilePath "python" `
                -ArgumentList @("-m", "uvicorn", "agent_service.app:app", "--host", "127.0.0.1", "--port", "$sidecarPort") `
                -WorkingDirectory (Join-Path $repoRoot "python") `
                -PassThru `
                -WindowStyle Hidden
        }
        finally {
            if ($null -eq $previousBypass) {
                Remove-Item Env:\ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV -ErrorAction SilentlyContinue
            }
            else {
                $env:ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV = $previousBypass
            }
        }
        $sidecarStartedHere = $true

        for ($attempt = 1; $attempt -le 20; $attempt++) {
            if (Test-AlitaSidecarHealthy "http://127.0.0.1:$sidecarPort/health") {
                break
            }
            Start-Sleep -Milliseconds 500
        }

        if (-not (Test-AlitaSidecarHealthy "http://127.0.0.1:$sidecarPort/health")) {
            throw "Python Agent sidecar did not become healthy on port $sidecarPort."
        }
    }

    Write-Host "Starting Tauri desktop window..."
    npm run dev
    if ($LASTEXITCODE -ne 0) {
        throw "Tauri desktop dev command failed. Exit code: $LASTEXITCODE"
    }
}
finally {
    if ($sidecarStartedHere -and $sidecarProcess -and -not $sidecarProcess.HasExited) {
        Stop-Process -Id $sidecarProcess.Id -Force
    }
    Pop-Location
}
