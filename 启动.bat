@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Color Block Transparency Tool
echo ============================================
echo.

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python not found. Please install Python 3.8+ and add it to PATH.
    echo         Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

"%PY%" -c "import PyQt5" >nul 2>nul
if not errorlevel 1 goto RUN
echo [INFO] Installing dependencies: PyQt5 / Pillow / numpy ...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo.

:RUN
"%PY%" main.py
if errorlevel 1 (
    echo.
    echo [ERROR] The program exited with an error. See the message above.
    pause
)
endlocal
