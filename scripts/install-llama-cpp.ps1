param(
    [string]$Release = "latest",
    [ValidateSet("cuda", "cpu")]
    [string]$Backend = "cuda",
    [string]$CudaVersion = "auto"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$runtimeDir = Join-Path $repoRoot "src-tauri\resources\llama-cpp"
$resolvedRuntimeParent = Resolve-Path (Join-Path $repoRoot "src-tauri")

if (-not $runtimeDir.StartsWith($resolvedRuntimeParent.Path, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to write llama.cpp runtime outside src-tauri: $runtimeDir"
}

function Get-LlamaCppRelease {
    param([string]$ReleaseName)

    $headers = @{ "User-Agent" = "Alita-local-runtime-integration" }
    if ($ReleaseName -eq "latest") {
        return Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
    }

    return Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/$ReleaseName"
}

function Get-NvidiaCudaVersion {
    try {
        $output = & nvidia-smi 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $null
        }

        $joined = $output -join "`n"
        if ($joined -match "CUDA Version:\s+([0-9]+\.[0-9]+)") {
            return [version]$Matches[1]
        }
    }
    catch {
        return $null
    }

    return $null
}

function Get-AvailableCudaVersions {
    param($Assets)

    $versions = @()
    foreach ($assetItem in $Assets) {
        if ($assetItem.name -match "^llama-.+-bin-win-cuda-([0-9]+\.[0-9]+)-x64\.zip$") {
            $versions += $Matches[1]
        }
    }

    return $versions | Sort-Object { [version]$_ } -Descending -Unique
}

function Resolve-CudaRuntimeVersion {
    param(
        $Assets,
        [string]$RequestedVersion
    )

    $availableVersions = @(Get-AvailableCudaVersions $Assets)
    if ($availableVersions.Count -eq 0) {
        throw "Could not find any Windows CUDA x64 llama.cpp assets."
    }

    if ($RequestedVersion -ne "auto") {
        if ($availableVersions -notcontains $RequestedVersion) {
            throw "Requested CUDA version $RequestedVersion is not available. Available versions: $($availableVersions -join ', ')"
        }
        return $RequestedVersion
    }

    $driverCudaVersion = Get-NvidiaCudaVersion
    if ($driverCudaVersion) {
        foreach ($candidate in $availableVersions) {
            if ([version]$candidate -le $driverCudaVersion) {
                return $candidate
            }
        }
    }

    return $availableVersions[0]
}

$releaseInfo = Get-LlamaCppRelease $Release
$selectedCudaVersion = $null
$cudartAsset = $null

if ($Backend -eq "cuda") {
    $selectedCudaVersion = Resolve-CudaRuntimeVersion $releaseInfo.assets $CudaVersion
    $runtimeAssetPattern = "^llama-.+-bin-win-cuda-$([regex]::Escape($selectedCudaVersion))-x64\.zip$"
    $cudartAssetPattern = "^cudart-llama-bin-win-cuda-$([regex]::Escape($selectedCudaVersion))-x64\.zip$"
    $asset = $releaseInfo.assets |
        Where-Object { $_.name -match $runtimeAssetPattern } |
        Select-Object -First 1
    $cudartAsset = $releaseInfo.assets |
        Where-Object { $_.name -match $cudartAssetPattern } |
        Select-Object -First 1

    if (-not $asset -or -not $cudartAsset) {
        throw "Could not find complete Windows CUDA $selectedCudaVersion x64 llama.cpp assets in release $($releaseInfo.tag_name)."
    }
}
else {
    $asset = $releaseInfo.assets |
        Where-Object { $_.name -match "^llama-.+-bin-win-cpu-x64\.zip$" } |
        Select-Object -First 1
}

if (-not $asset) {
    throw "Could not find a Windows $Backend x64 llama.cpp asset in release $($releaseInfo.tag_name)."
}

$tempRoot = Join-Path $env:TEMP "alita-llama-cpp-$($releaseInfo.tag_name)-$Backend"
if (Test-Path $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

$extractRoot = Join-Path $tempRoot "extracted"
New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null

$assetsToInstall = @($asset)
if ($cudartAsset) {
    $assetsToInstall += $cudartAsset
}

foreach ($assetToInstall in $assetsToInstall) {
    $zipPath = Join-Path $tempRoot $assetToInstall.name
    $assetExtractDir = Join-Path $extractRoot ([System.IO.Path]::GetFileNameWithoutExtension($assetToInstall.name))
    Write-Host "Downloading llama.cpp $($releaseInfo.tag_name) asset $($assetToInstall.name)"
    Invoke-WebRequest -UseBasicParsing -Uri $assetToInstall.browser_download_url -OutFile $zipPath
    Expand-Archive -LiteralPath $zipPath -DestinationPath $assetExtractDir -Force
}

$serverExe = Get-ChildItem -Path $extractRoot -Recurse -Filter "llama-server.exe" | Select-Object -First 1
if (-not $serverExe) {
    throw "Downloaded llama.cpp archive did not contain llama-server.exe."
}

if (Test-Path $runtimeDir) {
    Remove-Item -LiteralPath $runtimeDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

Copy-Item -LiteralPath $serverExe.FullName -Destination (Join-Path $runtimeDir "llama-server.exe") -Force
Get-ChildItem -Path $extractRoot -Recurse -Filter "*.dll" |
    ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $runtimeDir $_.Name) -Force
    }

$versionText = @(
    "release=$($releaseInfo.tag_name)",
    "backend=$Backend",
    "cuda_version=$selectedCudaVersion",
    "runtime_asset=$($asset.name)",
    "cudart_asset=$(if ($cudartAsset) { $cudartAsset.name } else { '' })",
    "source=$($releaseInfo.html_url)",
    "downloaded_at_utc=$((Get-Date).ToUniversalTime().ToString("o"))"
)
Set-Content -LiteralPath (Join-Path $runtimeDir "VERSION.txt") -Value $versionText -Encoding UTF8

Write-Host "Installed llama.cpp $Backend runtime to $runtimeDir"
