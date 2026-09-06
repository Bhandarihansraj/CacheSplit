# ==============================================================================
# CacheSplit v4 — Production Dockerfile
# Distributed Relational Cache Fabric with Cryptographic Merkle-DAG Integrity,
# Git-Style Branch Isolation, HNSW Vector Indexing, and Redis Compatibility Engine
# ==============================================================================

FROM python:3.13-slim AS base

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000 \
    HOST=0.0.0.0

# Set working directory
WORKDIR /app

# Install system runtime dependencies and build essentials
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies first for efficient Docker layer caching
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy entire application codebase
COPY . .

# Ensure data directory exists for SQLite database persistence
RUN mkdir -p /app/data

# Expose primary application port (HTTP/WebSocket/Dashboard), Redis port, and QUIC port
EXPOSE 8000 6379 4433/udp

# Container Healthcheck
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/dashboard/node-map || exit 1

# Default startup command: Launch CacheSplit FastAPI Server
CMD ["python", "-m", "uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
