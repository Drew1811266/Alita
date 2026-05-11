param(
    [switch]$IncludeGenerated
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptRoot "..")

$forbiddenTokens = @(
    ("Boo" + "ook"),
    ("boo" + "ook"),
    ("BOO" + "OOK"),
    ("." + "boo" + "ook"),
    ("X-" + "Boo" + "ook" + "-Sidecar-Token"),
    ("AI Agent" + " Productivity Tool"),
    ("AI Agent" + " Productivity Sidecar"),
    ("AI Agent" + " Productivity MVP"),
    ("AI Tool" + "-Using" + " Productivity Platform"),
    ("ai-agent" + "-productivity-tool"),
    ("boo" + "ook-agent-sidecar"),
    ("com." + "boo" + "ook.ai-workbench")
)

$excludedPrefixes = @(
    "node_modules\",
    ".git\",
    "models\",
    "python\.pytest_cache\"
)

$excludedPathFragments = @(
    "\__pycache__\"
)

if (-not $IncludeGenerated) {
    $excludedPrefixes += @(
        "dist\",
        "src-tauri\target\",
        "python\build\",
        "python\dist\",
        "python\alita_sidecar.egg-info\"
    )
}

$excludedFileNames = @(
    "rename-clean-baseline.txt",
    "rename-docs-pass-1.txt",
    "rename-docs-only.txt",
    "rename-data-pass-1.txt",
    "rename-data-only.txt"
)

$binaryExtensions = @(
    ".exe", ".dll", ".pdb", ".lib", ".rlib", ".o", ".obj", ".ilk", ".exp", ".res", ".zip", ".pyz", ".pkg",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".gguf", ".node", ".pyc"
)

$pattern = ($forbiddenTokens | ForEach-Object { [regex]::Escape($_) }) -join "|"
$files = & rg --files --hidden
$findings = [System.Collections.ArrayList]::new()

foreach ($file in $files) {
    $normalized = $file -replace "/", "\"
    $skip = $false
    foreach ($prefix in $excludedPrefixes) {
        if ($normalized.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $skip = $true
            break
        }
    }
    if ($skip) {
        continue
    }

    foreach ($fragment in $excludedPathFragments) {
        if ($normalized.IndexOf($fragment, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            $skip = $true
            break
        }
    }
    if ($skip) {
        continue
    }

    $fileName = [System.IO.Path]::GetFileName($normalized)
    if ($excludedFileNames -contains $fileName) {
        continue
    }

    if ($normalized -match $pattern) {
        [void]$findings.Add(("{0}: filename contains legacy naming" -f $file))
    }

    $extension = [System.IO.Path]::GetExtension($normalized)
    if ($binaryExtensions -contains $extension) {
        continue
    }

    $fullPath = Join-Path $repoRoot $file
    $fileMatches = Select-String -LiteralPath $fullPath -Pattern $pattern -CaseSensitive -AllMatches -ErrorAction SilentlyContinue
    foreach ($match in $fileMatches) {
        [void]$findings.Add(("{0}:{1}: {2}" -f $file, $match.LineNumber, $match.Line.Trim()))
    }
}

if ($findings.Count -gt 0) {
    $findings | ForEach-Object { Write-Output $_ }
    Write-Error ("Found {0} legacy naming occurrence(s)." -f $findings.Count)
    exit 1
}

Write-Output "No forbidden legacy naming tokens found."
