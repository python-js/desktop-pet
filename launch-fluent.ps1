$ErrorActionPreference = 'Stop'
$petPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $petPython)) { throw 'Create the project virtual environment first.' }
$petPreviousUi = $env:DESKTOP_PET_UI
Push-Location -LiteralPath $PSScriptRoot
try {
    $env:DESKTOP_PET_UI = 'fluent'
    & $petPython 'launch.py'
    if ($LASTEXITCODE -ne 0) { throw 'Fluent launch failed. Install requirements-fluent.txt and check the output.' }
} finally {
    $env:DESKTOP_PET_UI = $petPreviousUi
    Pop-Location
}
