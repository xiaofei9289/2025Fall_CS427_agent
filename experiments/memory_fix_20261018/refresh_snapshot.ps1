# Refresh desktop_validation/memory-fix-20261018 from the freshly pulled repository.
# Run on the Windows desktop after `git pull`: mirrors src/ and tests/ into the
# snapshot, then verifies the freshness checks used by desktop.py launchers.

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$snapshot = Join-Path $root "desktop_validation\memory-fix-20261018"

robocopy (Join-Path $root "src") (Join-Path $snapshot "src") /MIR /XD __pycache__ .pytest_cache /XF .DS_Store ._* /NFL /NDL /NJH
if ($LASTEXITCODE -band 8) { throw "robocopy src failed with exit code $LASTEXITCODE" }
robocopy (Join-Path $root "tests") (Join-Path $snapshot "tests") /MIR /XD __pycache__ .pytest_cache /XF .DS_Store ._* /NFL /NDL /NJH
if ($LASTEXITCODE -band 8) { throw "robocopy tests failed with exit code $LASTEXITCODE" }

$defaultPy = Get-Content (Join-Path $snapshot "src\minisweagent\agents\default.py") -Raw
if ([regex]::Matches($defaultPy, [regex]::Escape("Your task: {{task}}")).Count -ne 1) {
    throw "Stale snapshot: task text must appear exactly once in default.py"
}
foreach ($relative in @(
    "src\minisweagent\memory\history.py",
    "src\minisweagent\run\extra\memory_replay.py",
    "experiments\memory_fix_20261018\on.yaml"
)) {
    if (-not (Test-Path (Join-Path $root $relative))) { throw "Repository is missing $relative; pull first" }
}
$onYaml = Get-Content (Join-Path $root "experiments\memory_fix_20261018\on.yaml") -Raw
if ($onYaml -notmatch "memory_max_messages:\s*40") {
    throw "on.yaml still has the old 12-message budget; pull the latest commit first"
}

Write-Host "Snapshot refreshed and verified at $snapshot"
