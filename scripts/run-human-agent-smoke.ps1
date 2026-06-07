param(
    [string]$PythonPath = "python",
    [string[]]$PytestArgs = @()
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$env:PYTHONPATH = "python"

$argsList = @(
    "-m",
    "pytest",
    "python/tests/test_human_task_smoke.py",
    "-q"
)

function Expand-PytestArgs {
    param([string[]]$Values)

    $expanded = @()
    foreach ($value in $Values) {
        if ($value -match ",") {
            $parts = [regex]::Matches($value, "'([^']*)'|`"([^`"]*)`"|([^,]+)")
            if ($parts.Count -gt 1) {
                foreach ($part in $parts) {
                    $expandedValue = if ($part.Groups[1].Success) {
                        $part.Groups[1].Value
                    } elseif ($part.Groups[2].Success) {
                        $part.Groups[2].Value
                    } else {
                        $part.Groups[3].Value.Trim()
                    }
                    if ($expandedValue) {
                        $expanded += $expandedValue
                    }
                }
                continue
            }
        }
        if ($value) {
            $expanded += $value
        }
    }
    return $expanded
}

$extraArgs = Expand-PytestArgs -Values $PytestArgs
if ($extraArgs.Count -gt 0) {
    $argsList += $extraArgs
}

& $PythonPath @argsList
exit $LASTEXITCODE
