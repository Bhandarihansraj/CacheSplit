"""
CacheSplit v3 — FastAPI Server
Handles startup: DB init, node registration, cache seeding, background loops.
"""
import os
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from db import init_db, close_db
from db import node_repo
from services.registry import registry
from services.cache_store import cache_store
from services.analytics import analytics
from services.state_manager import state_manager
from api.dashboard import router as dashboard_router
from api.query import router as query_router
from api.propagation import router as propagation_router
from api.users import router as users_router
from api.payments import router as payments_router
from api.scanner import router as scanner_router
from services.sync_loop import sync_loop

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("Initializing SQLite database…")
    await init_db()

    logger.info("Registering cluster nodes in DB…")
    node_configs = [
        ("us-east-1",    "US-East",    "main"),
        ("eu-west-1",    "EU-West",    "main"),
        ("asia-south-1", "Asia-South", "main"),
    ]
    for node_id, region, tier in node_configs:
        await node_repo.upsert_node(
            node_id=node_id, region=region, tier=tier,
            health="ok", last_heartbeat=time.time(),
            heartbeat_enabled=True,
        )
        registry.register_node(node_id, region, tier)

    logger.info("Seeding regional ER cluster data…")
    await cache_store.seed_regional_cluster_data(entities_per_zone=50)

    logger.info("Seeding baseline access patterns + training ML model…")
    analytics.seed_baseline_traffic()

    # Sync in-memory registry from DB
    db_nodes = await node_repo.get_all_nodes()
    for n in db_nodes:
        registry.heartbeat(
            n["node_id"], n["current_commit_hash"] or "genesis",
            n["version_number"], {},
        )

    # Start background health sweep + auto-heartbeat emitter
    registry.start_sweep(enable_auto_heartbeat=True)
    sync_loop.start()
    logger.info("CacheSplit v3 ready — http://127.0.0.1:8000")
    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    sync_loop.stop()
    registry.stop_sweep()
    await close_db()
    logger.info("Server shutdown complete.")


app = FastAPI(title="CacheSplit v3", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard_router)
app.include_router(query_router)
app.include_router(propagation_router)
app.include_router(users_router)
app.include_router(payments_router)
app.include_router(scanner_router)


# ──────────────────────── Core API Routes ────────────────────────────────────

class HeartbeatRequest(BaseModel):
    node_id: str
    current_commit_hash: str
    version_number: int
    cache_summary: dict


@app.post("/api/heartbeat")
async def heartbeat(req: HeartbeatRequest):
    registry.heartbeat(
        node_id=req.node_id,
        current_commit_hash=req.current_commit_hash,
        version_number=req.version_number,
        cache_summary=req.cache_summary,
    )
    await node_repo.update_node_heartbeat(
        req.node_id, time.time(), req.version_number, req.current_commit_hash
    )
    return {"status": "ok"}


class HandshakeRequest(BaseModel):
    node_id: str
    version_number: int
    join_token: str

@app.post("/api/handshake")
async def handshake(req: HandshakeRequest):
    success = registry.handshake(req.node_id, req.version_number, req.join_token)
    status = "approved" if success else "rejected"
    await node_repo.update_handshake_status(req.node_id, status)
    return {"status": status}


@app.post("/api/register")
async def register(node_id: str, region: str, tier: str, join_token: str, parent_node_id: str = None):
    registry.register_node(node_id, region, tier, parent_node_id, join_token)
    await node_repo.upsert_node(node_id=node_id, region=region, tier=tier, join_token=join_token)
    return {"status": "registered"}


@app.get("/api/status/{node_id}")
async def get_status(node_id: str):
    return await node_repo.get_node(node_id)


@app.post("/api/debug/quarantine")
async def debug_quarantine(node_id: str, reason: str):
    registry.mark_quarantined(node_id, reason)
    node = registry.nodes.get(node_id)
    flags = node.agent_flags if node else [reason]
    await node_repo.update_node_health(node_id, "quarantined", flags)
    return {"status": "quarantined", "node_id": node_id}


@app.websocket("/api/ws/state")
async def websocket_endpoint(websocket: WebSocket):
    await state_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        state_manager.disconnect(websocket)

# ──────────────────────── Static UI ──────────────────────────────────────────

_ui_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ui"))
_dashboard_file = os.path.join(_ui_dir, "dashboard.html")


@app.get("/")
async def root():
    if os.path.exists(_dashboard_file):
        return FileResponse(_dashboard_file)
    return {"status": "CacheSplit v3 running"}


if os.path.exists(_ui_dir):
    app.mount("/", StaticFiles(directory=_ui_dir, html=True), name="ui")
