@echo off
setlocal
cd /d "%~dp0"
title StorePro - Restart

rem 1. Enforce canonical directory and prevent restarting from an outdated Desktop copy
set "CURRENT_DIR=%~dp0"
if "%CURRENT_DIR:~-1%"=="\" set "CURRENT_DIR=%CURRENT_DIR:~0,-1%"

echo %CURRENT_DIR% | findstr /i "\\Desktop\\store-app \\Downloads\\store-app" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo ======================================================================
    echo  [ERROR] Cannot restart StorePro from an unverified Desktop or Downloads copy.
    echo ======================================================================
    echo  Current directory: %CURRENT_DIR%
    echo  Please run StorePro from its canonical project installation.
    echo ======================================================================
    echo.
    pause
    exit /b 1
)

if not exist "app.py" (
    echo [ERROR] StorePro project root not detected in: %CURRENT_DIR%
    pause
    exit /b 1
)
if not exist "templates\base.html" (
    echo [ERROR] Incomplete StorePro installation. Missing templates\base.html.
    pause
    exit /b 1
)
if not exist "models\__init__.py" (
    echo [ERROR] Incomplete StorePro installation. Missing models\__init__.py.
    pause
    exit /b 1
)

echo Restarting the StorePro server from canonical installation: %CURRENT_DIR%...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $runtimePath=Join-Path (Get-Location).Path '.venv\Scripts\python.exe'; $servers=Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $runtimePath -and $_.CommandLine -match '(?i)(?:^|\s)app\.py(?:\s|$)' }; foreach($server in $servers) { & taskkill.exe /PID $server.ProcessId /T /F; if($LASTEXITCODE -ne 0) { throw 'Windows could not stop the existing StorePro server.' } }"
if errorlevel 1 (
    echo Close the existing StorePro server, then run run.bat.
    pause
    exit /b 1
)
call run.bat
endlocal
