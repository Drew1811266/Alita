$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$previousBypass = $env:ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV
$env:ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV = "1"

Push-Location (Join-Path $repoRoot "python")
try {
    python -m uvicorn agent_service.app:app --host 127.0.0.1 --port 8765
}
finally {
    if ($null -eq $previousBypass) {
        Remove-Item Env:\ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV -ErrorAction SilentlyContinue
    }
    else {
        $env:ALITA_SIDECAR_ALLOW_UNAUTHENTICATED_DEV = $previousBypass
    }
    Pop-Location
}
