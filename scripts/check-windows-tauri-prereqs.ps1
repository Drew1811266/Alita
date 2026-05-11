$ErrorActionPreference = "Stop"

function Resolve-CommandPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [string[]]$Fallbacks = @()
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    foreach ($fallback in $Fallbacks) {
        if (Test-Path $fallback) {
            return $fallback
        }
    }

    return $null
}

function Assert-Command {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$InstallHint,
        [string[]]$Fallbacks = @()
    )

    $path = Resolve-CommandPath -Name $Name -Fallbacks $Fallbacks
    if (-not $path) {
        throw "$Name was not found. $InstallHint"
    }

    Write-Host "[ok] $Name -> $path"
    return $path
}

function Test-WebView2 {
    $paths = @(
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients",
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
    )

    foreach ($path in $paths) {
        if (Test-Path $path) {
            $match = Get-ChildItem $path -ErrorAction SilentlyContinue |
                Get-ItemProperty |
                Where-Object { $_.name -like "*WebView2*" }
            if ($match) {
                Write-Host "[ok] Microsoft Edge WebView2 runtime is installed."
                return
            }
        }
    }

    Write-Warning "Microsoft Edge WebView2 runtime was not found in registry. Windows 10 1803+ or Windows 11 usually already has it; install WebView2 Evergreen Runtime if Tauri reports a WebView2 error."
}

$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
$rustupPath = Assert-Command "rustup" "Install Rust through rustup." @((Join-Path $cargoBin "rustup.exe"))
$cargoPath = Assert-Command "cargo" "Install Rust through rustup." @((Join-Path $cargoBin "cargo.exe"))
[void](Assert-Command "node" "Install Node.js LTS.")
[void](Assert-Command "npm" "Install Node.js LTS.")
[void](Assert-Command "python" "Install Python 3.10+ and add it to PATH.")

$toolchain = & $rustupPath show active-toolchain
Write-Host "[info] Rust active toolchain: $toolchain"
if ($toolchain -notmatch "msvc") {
    throw "Rust is not using the MSVC toolchain. Run: rustup default stable-x86_64-pc-windows-msvc"
}

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
    throw "Visual Studio Installer / vswhere was not found. Install Visual Studio Build Tools and select 'Desktop development with C++'."
}

$installationPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $installationPath) {
    throw "MSVC C++ tools were not found. Install Visual Studio Build Tools and select 'Desktop development with C++'."
}
Write-Host "[ok] Visual Studio Build Tools -> $installationPath"

$linkPath = Get-ChildItem -Path $installationPath -Recurse -Filter "link.exe" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -like "*\VC\Tools\MSVC\*\bin\Hostx64\x64\link.exe" } |
    Select-Object -First 1
if (-not $linkPath) {
    throw "link.exe was not found under Visual Studio Build Tools. Modify Build Tools and include MSVC C++ x64/x86 build tools plus Windows SDK."
}
Write-Host "[ok] link.exe -> $($linkPath.FullName)"

Test-WebView2
Write-Host ""
Write-Host "Prerequisite scan completed. If cargo still cannot find link.exe, restart PowerShell after installing Build Tools and rerun this script."
