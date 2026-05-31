$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    $pythonTestFiles = @(Get-ChildItem python\tests -Filter "test_*.py").Count
    $rustTestFiles = @(Get-ChildItem src-tauri\tests -Filter "*.rs").Count
    $frontendTestFiles = @(Get-ChildItem src -Recurse -Include "*.test.ts", "*.test.tsx").Count

    $evalCounts = [ordered]@{}
    Get-ChildItem python\evals -Filter "*.jsonl" | Sort-Object Name | ForEach-Object {
        Get-Content $_.FullName -Encoding UTF8 | Where-Object { $_.Trim() } | ForEach-Object {
            $case = $_ | ConvertFrom-Json
            $category = [string]$case.category
            if (-not $evalCounts.Contains($category)) {
                $evalCounts[$category] = 0
            }
            $evalCounts[$category]++
        }
    }

    [pscustomobject]@{
        pythonTestFiles = $pythonTestFiles
        rustTauriTestFiles = $rustTestFiles
        frontendTestFiles = $frontendTestFiles
        evalTotal = [int]($evalCounts.Values | Measure-Object -Sum).Sum
        evalCounts = $evalCounts
    } | ConvertTo-Json -Depth 5
}
finally {
    Pop-Location
}
