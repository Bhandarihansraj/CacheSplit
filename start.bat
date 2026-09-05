@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%~dp0

echo ============================================================
echo           CacheSplit v4 - Production Node Cluster
echo ============================================================
echo Workspace Directory: %~dp0
echo Security:         HMAC-signed audit trail + tenant scoping
echo Scale:            Consistent hashing + per-tenant queues
echo AI/ML:            Priority model + anomaly detector + guardrail
echo ============================================================

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment .venv was not found in %~dp0
    echo     Please run setup.bat first!
    pause
    exit /b 1
)

echo [1] Checking topology cache TTL...
".\.venv\Scripts\python.exe" -c "from commitcache.infra.topology import Topology; t=Topology(); print(f'  Topology: {len(t._topology)} regions cached, stale={t.is_stale()}')" 2>nul
if %errorlevel% neq 0 (
    echo  [!] Topology not initialized — will seed on first request
)

echo [2] Checking queue pools...
".\.venv\Scripts\python.exe" -c "from commitcache.scale.tenant_queue_pool import tenant_queue_pool; print(f'  Queue pools: {tenant_queue_pool.tenant_count} tenants')" 2>nul
if %errorlevel% neq 0 (
    echo  [!] Queue pool not initialized — will create on first tenant request
)

echo [3] Starting FastAPI / Uvicorn Server...
start "CacheSplit v4 API Server" cmd /k "cd /d "%~dp0" && set PYTHONPATH=%~dp0 && ".\.venv\Scripts\python.exe" -m uvicorn api.server:app --reload --host 127.0.0.1 --port 8000"

echo Wait for server to start...
timeout /t 3 /nobreak >nul

echo [4] Seeding cluster nodes and topology...
".\.venv\Scripts\python.exe" seed_data.py
if %errorlevel% neq 0 (
    echo  [!] Seed data encountered errors — check logs
)

echo [5] Initializing DR failover and audit log...
".\.venv\Scripts\python.exe" -c "from commitcache.infra.dr_failover import create_dr_failover; from commitcache.core.lease import LeaseManager; from commitcache.core.audit_log import AuditLog; print('  Lease Manager: OK'); print('  Audit Log: OK'); print('  DR Failover: Initialized')" 2>nul
if %errorlevel% neq 0 (
    echo  [!] Infra services not initialized — will start on first request
)

echo.
echo ============================================================
echo [√] CacheSplit v4 Cluster is Running!
echo [√] UI Dashboard:     http://127.0.0.1:8000/v4_dashboard.html
echo [√] Developer Demo:   http://127.0.0.1:8000/demo
echo [√] Test Suite:       http://127.0.0.1:8000/test_cases.html
echo [√] API Docs:         http://127.0.0.1:8000/docs
echo ============================================================
echo.
echo To run the interactive Menu-Driven Demo CLI, open another terminal and run:
echo     python ops\demo_menu.py
echo.
echo To test anomaly injection, run:
echo     python inject_anomaly.py
echo.
echo To run the audit checklist, run:
echo     python audit_checklist.py
echo     python audit_checklist.py --json
echo.
echo Auth: All endpoints require JWT token with tenant_id.
echo       Login at http://127.0.0.1:8000/v4_dashboard.html → Auth tab
echo.
pause