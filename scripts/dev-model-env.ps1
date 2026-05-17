$ErrorActionPreference = "Stop"

function Get-AlitaDevModelPath {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [string]$PreferencesPath = (Join-Path $env:APPDATA "com.alita.ai-workbench\preferences.json")
    )

    $configuredModelPath = $env:ALITA_LLAMA_MODEL_PATH
    if (-not [string]::IsNullOrWhiteSpace($configuredModelPath)) {
        return $configuredModelPath.Trim()
    }

    if (Test-Path -LiteralPath $PreferencesPath -PathType Leaf) {
        try {
            $preferences = Get-Content -LiteralPath $PreferencesPath -Raw | ConvertFrom-Json
            $defaultModelId = $null
            if ($preferences.PSObject.Properties.Name -contains "modelAssignments" -and $null -ne $preferences.modelAssignments) {
                $defaultModelId = $preferences.modelAssignments.agentChatModelId
            }
            if ([string]::IsNullOrWhiteSpace($defaultModelId)) {
                $defaultModelId = $preferences.defaultModelId
            }
            if (-not [string]::IsNullOrWhiteSpace($defaultModelId)) {
                $defaultModel = @($preferences.models) |
                    Where-Object { $_.modelId -eq $defaultModelId } |
                    Select-Object -First 1
                if ($defaultModel -and
                    -not [string]::IsNullOrWhiteSpace($defaultModel.path) -and
                    (Test-Path -LiteralPath $defaultModel.path -PathType Leaf)) {
                    return $defaultModel.path
                }
            }

            $firstExistingModel = @($preferences.models) |
                Where-Object {
                    -not [string]::IsNullOrWhiteSpace($_.path) -and
                    (Test-Path -LiteralPath $_.path -PathType Leaf)
                } |
                Select-Object -First 1
            if ($firstExistingModel) {
                return $firstExistingModel.path
            }
        }
        catch {
            Write-Warning "Could not read Alita preferences at ${PreferencesPath}: $_"
        }
    }

    $repoModel = Get-ChildItem -LiteralPath (Join-Path $RepoRoot "models") -Filter "*.gguf" -File -ErrorAction SilentlyContinue |
        Sort-Object Name |
        Select-Object -First 1
    if ($repoModel) {
        return $repoModel.FullName
    }

    return $null
}

function Set-AlitaDevModelEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [string]$PreferencesPath = (Join-Path $env:APPDATA "com.alita.ai-workbench\preferences.json")
    )

    $modelPath = Get-AlitaDevModelPath -RepoRoot $RepoRoot -PreferencesPath $PreferencesPath
    if ([string]::IsNullOrWhiteSpace($modelPath)) {
        Write-Warning "No GGUF model found for the development sidecar. Configure one in Preferences or set ALITA_LLAMA_MODEL_PATH."
        return $false
    }

    $env:ALITA_LLAMA_MODEL_PATH = $modelPath
    $env:ALITA_LLAMA_BASE_URL = "http://127.0.0.1:8766"
    $env:ALITA_LLAMA_MODEL_NAME = [System.IO.Path]::GetFileNameWithoutExtension($modelPath)
    Write-Host "Using dev model: $modelPath"
    return $true
}
