$ErrorActionPreference = 'Stop'
$petBuildPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $petBuildPython)) {
    throw 'Create the desktop-pet virtual environment first. See README.md.'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $petBuildPython 'tools\build_windows.py'
    if ($LASTEXITCODE -ne 0) { throw 'Windows build failed. See the output above.' }
} finally {
    Pop-Location
}
