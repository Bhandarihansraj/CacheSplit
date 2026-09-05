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
    echo     Please create it or ensure dependencies are installed.
    pause
    exit /b 1
)

echo Starting FastAPI / Uvicorn Server in new window...
start "CacheSplit API Server" cmd /k "cd /d "%~dp0" && set PYTHONPATH=%~dp0 && ".\.venv\Scripts\python.exe" -m uvicorn api.server:app --reload --port 8000"

echo Connecting to server and seeding cluster nodes...
".\.venv\Scripts\python.exe" seed_data.py

echo.
echo ============================================================
echo [✓] CacheSplit Cluster is Running!
echo [✓] UI Dashboard: http://127.0.0.1:8000
echo ============================================================
echo.
echo To test anomaly injection / quarantine, open another terminal and run:
echo     python inject_anomaly.py
echo.
pause
