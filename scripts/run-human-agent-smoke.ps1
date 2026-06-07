param(
    [string]$PythonPath = "python",
    [string]$PytestArgs = ""
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

if ($PytestArgs.Trim()) {
    $argsList += $PytestArgs.Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)
}

& $PythonPath @argsList
exit $LASTEXITCODE
