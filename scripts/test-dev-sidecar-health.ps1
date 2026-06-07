$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
. (Join-Path $repoRoot "scripts\dev-sidecar-health.ps1")

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

Assert-Equal `
    -Actual (Test-AlitaSidecarResponse ([pscustomobject]@{ name = "alita-agent-sidecar"; status = "ok" })) `
    -Expected $true `
    -Message "Alita sidecar health response should be accepted."

Assert-Equal `
    -Actual (Test-AlitaSidecarResponse ([pscustomobject]@{ name = "diplomat-worker"; status = "ok" })) `
    -Expected $false `
    -Message "Unrelated service health response must not be accepted."

Assert-Equal `
    -Actual (Test-AlitaSidecarResponse ([pscustomobject]@{ status = "ok" })) `
    -Expected $false `
    -Message "Generic health response without Alita identity must not be accepted."

Assert-Equal `
    -Actual (Test-AlitaSidecarResponse $null) `
    -Expected $false `
    -Message "Null health response must not be accepted."

Write-Output "Dev sidecar health test passed."
