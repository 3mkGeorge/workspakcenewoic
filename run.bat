@echo off
setlocal
cd /d "%~dp0"
title StorePro - Local Store Management

rem 1. Enforce canonical directory and prevent launching outdated Desktop or Downloads copies
set "CURRENT_DIR=%~dp0"
if "%CURRENT_DIR:~-1%"=="\" set "CURRENT_DIR=%CURRENT_DIR:~0,-1%"

echo %CURRENT_DIR% | findstr /i "\\Desktop\\store-app \\Downloads\\store-app" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo ======================================================================
    echo  [ERROR] Cannot launch StorePro from an unverified Desktop or Downloads copy.
    echo ======================================================================
    echo  Current directory: %CURRENT_DIR%
    echo  Please launch StorePro from its canonical project installation or use
    echo  the verified desktop shortcut.
    echo ======================================================================
    echo.
    pause
    exit /b 1
)

rem 2. Verify required StorePro project files exist
if not exist "app.py" (
    echo [ERROR] StorePro project root not detected. Missing app.py in: %CURRENT_DIR%
    pause
    exit /b 1
)
if not exist "templates\base.html" (
    echo [ERROR] Incomplete StorePro installation. Missing templates\base.html.
    pause
    exit /b 1
)
if not exist "static\css\app.css" (
    echo [ERROR] Incomplete StorePro installation. Missing static\css\app.css.
    pause
    exit /b 1
)
if not exist "static\css\pos.css" (
    echo [ERROR] Incomplete StorePro installation. Missing static\css\pos.css.
    pause
    exit /b 1
)
if not exist "models\__init__.py" (
    echo [ERROR] Incomplete StorePro installation. Missing models\__init__.py.
    pause
    exit /b 1
)

rem 3. Detect or create Python virtual environment
if exist ".venv\Scripts\python.exe" goto dependencies
python -c "import sys,struct; sys.exit(0 if sys.version_info[:2] == (3,13) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 goto python_launcher
python -m venv .venv
goto verify_environment
:python_launcher
py -3.13 -m venv .venv
:verify_environment
if not exist ".venv\Scripts\python.exe" (
    echo Python 3.13 for Windows x64 is required. Install it from python.org, then try again.
    pause
    exit /b 1
)
:dependencies
if not exist ".venv\storepro-installed" (
    echo Installing StorePro dependencies from the local offline package...
    .venv\Scripts\python.exe -m pip install --no-index --find-links wheels -r requirements-lock.txt
    if errorlevel 1 (
        echo Dependency installation failed. Check that you are using Python 3.13 x64.
        pause
        exit /b 1
    )
    type nul > ".venv\storepro-installed"
)

echo.
echo Launching StorePro from canonical installation: %CURRENT_DIR%
echo.
.venv\Scripts\python.exe app.py
if errorlevel 1 pause
endlocal
