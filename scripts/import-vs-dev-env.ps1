$ErrorActionPreference = "Stop"

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
    throw "Visual Studio Installer / vswhere was not found. Install Visual Studio Build Tools first."
}

$installationPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $installationPath) {
    throw "MSVC C++ tools were not found. Install Visual Studio Build Tools with 'Desktop development with C++'."
}

$vcvars = Join-Path $installationPath "VC\Auxiliary\Build\vcvars64.bat"
if (-not (Test-Path $vcvars)) {
    throw "vcvars64.bat was not found at $vcvars"
}

$environment = cmd /c "`"$vcvars`" >nul && set"
foreach ($line in $environment) {
    $equalsIndex = $line.IndexOf("=")
    if ($equalsIndex -gt 0) {
        $name = $line.Substring(0, $equalsIndex)
        $value = $line.Substring($equalsIndex + 1)
        Set-Item -Path "Env:$name" -Value $value
    }
}

Write-Host "[ok] Visual Studio developer environment loaded from $vcvars"
