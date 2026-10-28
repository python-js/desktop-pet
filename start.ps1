$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$petPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $petPython)) {
    Write-Host '请先按 README.md 创建虚拟环境并安装依赖。'
    exit 1
}
& $petPython -m desktop_pet
