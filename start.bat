@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%~dp0

echo ============================================================
echo           CacheSplit v3 - Production Node Cluster
echo ============================================================
echo Workspace Directory: %~dp0

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment .venv was not found in %~dp0
    echo     Please run setup.bat first!
    pause
    exit /b 1
)

echo Starting FastAPI / Uvicorn Server in new window...
start "CacheSplit API Server" cmd /k "cd /d "%~dp0" && set PYTHONPATH=%~dp0 && ".\.venv\Scripts\python.exe" -m uvicorn api.server:app --reload --host 127.0.0.1 --port 8000"

echo Wait for server to start...
timeout /t 3 /nobreak >nul

echo Connecting to server and seeding cluster nodes...
".\.venv\Scripts\python.exe" seed_data.py

echo.
echo ============================================================
echo [√] CacheSplit Cluster is Running!
echo [√] UI Dashboard: http://127.0.0.1:8000
echo ============================================================
echo.
echo To run the interactive Menu-Driven Demo CLI, open another terminal and run:
echo     python ops\demo_menu.py
echo.
echo To test anomaly injection / quarantine, run:
echo     python inject_anomaly.py
echo.
pause
