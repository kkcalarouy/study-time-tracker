$ErrorActionPreference = "Stop"

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonCandidates = @()

if ($env:STUDY_TRACKER_PYTHON) {
    $pythonCandidates += $env:STUDY_TRACKER_PYTHON
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCommand) {
    $pythonCandidates += $pythonCommand.Source
}

$pyCommand = Get-Command py -ErrorAction SilentlyContinue
if ($pyCommand) {
    $pythonCandidates += $pyCommand.Source
}

$pythonCandidates += Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

$python = $pythonCandidates |
    Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
    Select-Object -First 1

if (-not $python) {
    Write-Error "Python 3 was not found. Set STUDY_TRACKER_PYTHON to a Python executable."
    exit 127
}

& $python (Join-Path $scriptDirectory "study_tracker.py") @args
exit $LASTEXITCODE
