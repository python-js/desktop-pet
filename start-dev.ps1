$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$petPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
$viteEntry = Join-Path $PSScriptRoot 'web\node_modules\vite\bin\vite.js'
if (-not (Test-Path -LiteralPath $petPython)) {
    throw '未找到项目虚拟环境。请先按 README.md 创建 .venv 并安装 Python 依赖。'
}
if (-not $nodeCommand -or -not (Test-Path -LiteralPath $viteEntry)) {
    throw '未找到 Node.js 或 Vite 依赖。请安装 Node.js 18+，并在 web 目录运行 npm ci。'
}

$previousDev = $env:DESKTOP_PET_DEV
$previousDevUrl = $env:DESKTOP_PET_DEV_URL
$previousDebugging = $env:QTWEBENGINE_REMOTE_DEBUGGING
$logBase = Join-Path $env:TEMP ("desktop-pet-vite-" + $PID)
$viteProcess = $null
$ownsViteProcess = $false
$devPort = $null
try {
    $env:DESKTOP_PET_DEV = '1'
    $env:QTWEBENGINE_REMOTE_DEBUGGING = '127.0.0.1:9223'

    for ($port = 5173; $port -le 5190; $port++) {
        $url = "http://127.0.0.1:$port/"
        $probe = [System.Net.Sockets.TcpClient]::new()
        $portBusy = $false
        try {
            $connect = $probe.BeginConnect([System.Net.IPAddress]::Loopback, $port, $null, $null)
            if ($connect.AsyncWaitHandle.WaitOne(500)) {
                try {
                    $probe.EndConnect($connect)
                    $portBusy = $true
                } catch { }
            }
        } catch {
            # A refused or timed-out connection means the local port is available.
        } finally {
            $probe.Close()
        }

        if ($portBusy) {
            Write-Host "端口 $port 已被其他服务占用，继续查找。"
            continue
        }

        $devPort = $port
        break
    }

    if ($null -eq $devPort) {
        throw '未找到可用的 Vite 开发端口（5173–5190）。'
    }
    $devUrl = "http://127.0.0.1:$devPort/"
    $env:DESKTOP_PET_DEV_URL = $devUrl

    $viteProcess = Start-Process -FilePath $nodeCommand.Source `
        -ArgumentList @("`"$viteEntry`"", '--host', '127.0.0.1', '--port', "$devPort", '--strictPort') `
        -WorkingDirectory (Join-Path $PSScriptRoot 'web') `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput "$logBase.out.log" `
        -RedirectStandardError "$logBase.err.log"
    $ownsViteProcess = $true

    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ($viteProcess -and $viteProcess.HasExited) { break }
        try {
            $response = Invoke-WebRequest -Uri $devUrl -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $serverReady = $true; break }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $serverReady) {
        $details = if ($ownsViteProcess -and (Test-Path -LiteralPath "$logBase.err.log")) {
            Get-Content -LiteralPath "$logBase.err.log" -Raw
        } else { 'Vite 未能在 127.0.0.1:5173 启动。' }
        throw "前端开发服务器启动失败。`n$details"
    }

    Write-Host "Vite 热更新已启动：$devUrl"
    Write-Host '现在启动桌面窗口。关闭桌面程序后会自动停止 Vite。'
    & $petPython -m desktop_pet
} finally {
    if ($ownsViteProcess -and $viteProcess -and -not $viteProcess.HasExited) {
        Stop-Process -Id $viteProcess.Id -Force -ErrorAction SilentlyContinue
    }
    $env:DESKTOP_PET_DEV = $previousDev
    $env:DESKTOP_PET_DEV_URL = $previousDevUrl
    $env:QTWEBENGINE_REMOTE_DEBUGGING = $previousDebugging
}
