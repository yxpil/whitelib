@echo off
rem ------------------------------------------------------------
rem  build_exe.bat —— 一键打包为单文件 exe
rem  产物: dist\ColorBlockClicker.exe
rem ------------------------------------------------------------
setlocal
cd /d "%~dp0"

where python >nul 2>nul || (echo [ERROR] Python not found & exit /b 1)

rem 创建(或复用)项目虚拟环境，保持全局环境干净
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating venv ...
    python -m venv .venv --system-site-packages || exit /b 1
)
set "VPY=.venv\Scripts\python.exe"

echo [2/3] Installing pyinstaller ...
"%VPY%" -m pip install -q pyinstaller || exit /b 1

echo [3/3] Building exe ...
"%VPY%" -m PyInstaller ColorBlockClicker.spec --noconfirm || exit /b 1

echo.
echo [DONE] dist\ColorBlockClicker.exe
endlocal
