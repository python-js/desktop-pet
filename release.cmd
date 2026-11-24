@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo 未找到 .venv：请先按 docs\WINDOWS_BUILD.md 创建虚拟环境并安装依赖。
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "tools\release.py" %*
set "code=%ERRORLEVEL%"
echo.
if not "%code%"=="0" (echo 发版失败，退出码 %code%。请按上方提示处理后重试。) else (echo 发版结束。)
pause
exit /b %code%
