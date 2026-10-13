@echo off
setlocal
cd /d "%~dp0"
title StorePro - User Recovery Utility

rem 1. Verify that the script is being run from the StorePro project root
if not exist "app.py" goto :err_no_root
if not exist "scripts\reset_users.py" goto :err_no_script

rem 2. Detect existing Python virtual environment
if not exist ".venv\Scripts\python.exe" goto :err_no_venv

rem 3. Start user recovery utility through existing .venv Python interpreter
.venv\Scripts\python.exe scripts\reset_users.py %*
set "RECOVERY_EXIT_CODE=%ERRORLEVEL%"

echo.
pause
exit /b %RECOVERY_EXIT_CODE%

:err_no_root
echo [ERROR] StorePro project root not detected.
echo Please execute reset_users.bat directly from the StorePro application directory.
echo.
pause
exit /b 1

:err_no_script
echo [ERROR] User recovery script 'scripts\reset_users.py' is missing.
echo The StorePro installation appears to be incomplete.
echo.
pause
exit /b 1

:err_no_venv
echo [ERROR] Python virtual environment was not found: .venv\Scripts\python.exe
echo Please run run.bat first to initialize StorePro and its dependencies.
echo.
pause
exit /b 1
