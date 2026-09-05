@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo           CacheSplit v4 - Setup Script
echo ============================================================
echo Workspace Directory: %~dp0
echo Security:         HMAC-signed audit trail + tenant scoping
echo Scale:            Consistent hashing + per-tenant queues
echo AI/ML:            Priority model + anomaly detector + guardrail
echo ============================================================

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
".\.venv\Scripts\python.exe" -m pip install numpy scikit-learn pytest pytest-asyncio
".\.venv\Scripts\python.exe" -m pip install sqlalchemy asyncpg

echo [4] Creating Data Directory...
if not exist "data" (
    mkdir data
    echo Data directory created.
)

echo [5] Creating commitcache module directories...
if not exist "commitcache\api" mkdir "commitcache\api"
if not exist "commitcache\core" mkdir "commitcache\core"
if not exist "commitcache\coordination" mkdir "commitcache\coordination"
if not exist "commitcache\infra" mkdir "commitcache\infra"
if not exist "commitcache\scale" mkdir "commitcache\scale"
if not exist "commitcache\ai" mkdir "commitcache\ai"
if not exist "commitcache\observability" mkdir "commitcache\observability"
if not exist "commitcache\metering" mkdir "commitcache\metering"
echo commitcache module structure created.

echo [6] Creating UI files...
if not exist "ui" mkdir "ui"
echo UI directory verified.

echo [7] Copying __init__.py files for Python modules...
if not exist "commitcache\__init__.py" echo. > "commitcache\__init__.py"
if not exist "commitcache\api\__init__.py" echo. > "commitcache\api\__init__.py"
if not exist "commitcache\core\__init__.py" echo. > "commitcache\core\__init__.py"
if not exist "commitcache\coordination\__init__.py" echo. > "commitcache\coordination\__init__.py"
if not exist "commitcache\infra\__init__.py" echo. > "commitcache\infra\__init__.py"
if not exist "commitcache\scale\__init__.py" echo. > "commitcache\scale\__init__.py"
if not exist "commitcache\ai\__init__.py" echo. > "commitcache\ai\__init__.py"
if not exist "commitcache\observability\__init__.py" echo. > "commitcache\observability\__init__.py"

echo ============================================================
echo Setup Complete!
echo Run start.bat to launch the cluster and UI.
echo Run audit_checklist.py to audit the architecture.
echo ============================================================
pause