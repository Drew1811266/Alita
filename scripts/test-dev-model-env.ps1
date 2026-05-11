$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
. (Join-Path $PSScriptRoot "dev-model-env.ps1")

$testRoot = Join-Path $env:TEMP ("alita-dev-model-env-test-" + [guid]::NewGuid().ToString("N"))
$modelDir = Join-Path $testRoot "models"
$preferencesPath = Join-Path $testRoot "preferences.json"
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
$modelPath = Join-Path $modelDir "Qwen-Test.gguf"
Set-Content -Path $modelPath -Encoding UTF8 -Value "test model placeholder"

$preferences = @{
    schemaVersion = 1
    recentProjects = @()
    modelDirectories = @()
    modelStorageDir = $modelDir
    defaultModelId = "model-1"
    models = @(
        @{
            modelId = "model-1"
            name = "Qwen Test"
            path = $modelPath
            source = "manual"
            runtime = "llama.cpp"
            fileExists = $true
            createdAt = "2026-05-11T00:00:00Z"
            updatedAt = "2026-05-11T00:00:00Z"
        }
    )
    toolEnablement = @{}
} | ConvertTo-Json -Depth 10
Set-Content -Path $preferencesPath -Encoding UTF8 -Value $preferences

$previousModelPath = $env:ALITA_LLAMA_MODEL_PATH
$previousBaseUrl = $env:ALITA_LLAMA_BASE_URL
$previousModelName = $env:ALITA_LLAMA_MODEL_NAME
try {
    Remove-Item Env:\ALITA_LLAMA_MODEL_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:\ALITA_LLAMA_BASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:\ALITA_LLAMA_MODEL_NAME -ErrorAction SilentlyContinue

    Set-AlitaDevModelEnvironment -RepoRoot $repoRoot -PreferencesPath $preferencesPath

    if ($env:ALITA_LLAMA_MODEL_PATH -ne $modelPath) {
        throw "Expected ALITA_LLAMA_MODEL_PATH to be '$modelPath', got '$env:ALITA_LLAMA_MODEL_PATH'"
    }
    if ($env:ALITA_LLAMA_BASE_URL -ne "http://127.0.0.1:8766") {
        throw "Expected ALITA_LLAMA_BASE_URL to target the dev llama service, got '$env:ALITA_LLAMA_BASE_URL'"
    }
    if ($env:ALITA_LLAMA_MODEL_NAME -ne "Qwen-Test") {
        throw "Expected ALITA_LLAMA_MODEL_NAME to be 'Qwen-Test', got '$env:ALITA_LLAMA_MODEL_NAME'"
    }

    Write-Output "Dev model environment test passed."
}
finally {
    if ($null -eq $previousModelPath) {
        Remove-Item Env:\ALITA_LLAMA_MODEL_PATH -ErrorAction SilentlyContinue
    } else {
        $env:ALITA_LLAMA_MODEL_PATH = $previousModelPath
    }

    if ($null -eq $previousBaseUrl) {
        Remove-Item Env:\ALITA_LLAMA_BASE_URL -ErrorAction SilentlyContinue
    } else {
        $env:ALITA_LLAMA_BASE_URL = $previousBaseUrl
    }

    if ($null -eq $previousModelName) {
        Remove-Item Env:\ALITA_LLAMA_MODEL_NAME -ErrorAction SilentlyContinue
    } else {
        $env:ALITA_LLAMA_MODEL_NAME = $previousModelName
    }

    Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
}
