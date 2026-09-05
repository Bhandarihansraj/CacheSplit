@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%~dp0

echo ============================================================
echo           CacheSplit v4 - Production Node Cluster
echo ============================================================
echo Workspace Directory: %~dp0
echo Architecture:       Multi-Node Distributed Cache + Merkle DAG
echo AI / AgentDB:       Semantic Vector Cache + RL Stampede Governor
echo Networking:         QUIC UDP Mesh + Invalidation Bus + Raft
echo ============================================================

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment .venv was not found in %~dp0
    echo     Please run: python -m venv .venv ^&^& .\.venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo [1] Starting FastAPI / Uvicorn Server...
start "CacheSplit v4 API Server" cmd /k "cd /d "%~dp0" && set PYTHONPATH=%~dp0 && ".\.venv\Scripts\python.exe" -m uvicorn api.server:app --reload --host 127.0.0.1 --port 8000"

echo [2] Waiting for server startup...
timeout /t 3 /nobreak >nul

echo [3] Seeding cluster nodes and topology...
".\.venv\Scripts\python.exe" seed_data.py
if %errorlevel% neq 0 (
    echo  [!] Seed data encountered errors — check server logs
)

echo.
echo ============================================================
echo [√] CacheSplit v4 Cluster is Running!
echo [√] Ops Console (v4):     http://127.0.0.1:8000/v4_dashboard.html
echo [√] Main UI Dashboard:    http://127.0.0.1:8000/dashboard
echo [√] Simulation Arena:     http://127.0.0.1:8000/simulation
echo [√] Developer Demo:       http://127.0.0.1:8000/demo
echo [√] Test Suite:           http://127.0.0.1:8000/test_cases.html
echo [√] OpenAPI Docs:         http://127.0.0.1:8000/docs
echo ============================================================
echo.
echo [Optional Tools]:
echo   - 10k Node Seeder:       python seed_10k_cluster.py
echo   - Run All Test Suite:    .\.venv\Scripts\pytest tests/ -v
echo   - Semantic Cache Demo:   python -m core.semantic_cache
echo   - QUIC UDP Mesh Test:    python -m core.quic_transport
echo.
pause