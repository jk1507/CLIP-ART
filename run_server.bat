@echo off
title ClipEngine Launcher
echo ============================================================
echo               STARTING CLIPENGINE SERVER
echo ============================================================
echo.
cd /d "%~dp0"

echo [1/2] Verifying Python environment...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found in PATH!
    pause
    exit /b 1
)

echo [2/2] Launching ClipEngine at http://127.0.0.1:8000 ...
start http://127.0.0.1:8000
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload

pause
