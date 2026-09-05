@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo           CacheSplit v3 - Setup Script
echo ============================================================
echo Workspace Directory: %~dp0

echo [1] Checking for Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python is not installed or not in PATH. Please install Python 3.10+
    pause
    exit /b 1
)

echo [2] Creating Virtual Environment (.venv)...
if not exist ".venv" (
    python -m venv .venv
    echo Virtual environment created.
) else (
    echo Virtual environment already exists.
)

echo [3] Installing dependencies...
".\.venv\Scripts\python.exe" -m pip install --upgrade pip
".\.venv\Scripts\python.exe" -m pip install fastapi uvicorn[standard] pydantic aiosqlite httpx websockets

echo [4] Creating Data Directory...
if not exist "data" (
    mkdir data
    echo Data directory created.
)

echo ============================================================
echo Setup Complete!
echo Run start.bat to launch the cluster and UI.
echo ============================================================
pause
