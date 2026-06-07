$ALITA_SIDECAR_HEALTH_NAME = "alita-agent-sidecar"

function Test-AlitaSidecarResponse {
    param([object]$Response)

    if ($null -eq $Response) {
        return $false
    }

    $name = ""
    if ($null -ne $Response.PSObject.Properties["name"]) {
        $name = [string]$Response.name
    }
    $status = ""
    if ($null -ne $Response.PSObject.Properties["status"]) {
        $status = [string]$Response.status
    }
    return $name -eq $ALITA_SIDECAR_HEALTH_NAME -and $status -eq "ok"
}

function Test-AlitaSidecarHealthy {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        $response = Invoke-RestMethod -Uri $Url -TimeoutSec 2
        return Test-AlitaSidecarResponse $response
    }
    catch {
        return $false
    }
}
