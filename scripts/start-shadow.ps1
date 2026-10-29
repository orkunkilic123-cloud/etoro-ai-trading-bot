[CmdletBinding()]
param(
    [string]$Root = '',
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [string]$NewsArchive = '',
    [switch]$Initialize,
    [switch]$RunFixtures,
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'Create the documented Python 3.12+ virtual environment first.'
}
if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = Join-Path $ProjectRoot '.backtest-output\shadow'
}
$Root = [System.IO.Path]::GetFullPath($Root)

function Invoke-Shadow([string[]]$Arguments) {
    & $Python -m etoro_demo_bot.shadow @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw 'Shadow operation blocked. Existing state is preserved; inspect local status.'
    }
}

# Initialization is explicit and refuses existing state. No packages are installed or secrets read.
if ($Initialize) {
    Invoke-Shadow -Arguments @('init', '--root', $Root)
}
if (-not (Test-Path -LiteralPath (Join-Path $Root 'runs.sqlite') -PathType Leaf)) {
    throw 'Shadow journal missing. Use -Initialize only for a new isolated research root.'
}
if ($RunFixtures) {
    foreach ($Pipeline in @('hourly', 'orb')) {
        foreach ($Budget in @('500', '1000')) {
            Invoke-Shadow -Arguments @('run', '--root', $Root, '--pipeline', $Pipeline, '--eur', $Budget)
        }
    }
}
$ViewerArguments = @('serve', '--root', $Root, '--port', [string]$Port)
if (-not [string]::IsNullOrWhiteSpace($NewsArchive)) {
    $ViewerArguments += @('--news-archive', [System.IO.Path]::GetFullPath($NewsArchive))
}
if (-not $NoBrowser) {
    $ViewerArguments += '--open-browser'
}
Invoke-Shadow -Arguments $ViewerArguments
