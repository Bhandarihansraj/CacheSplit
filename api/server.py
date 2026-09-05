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
from api.developer import router as developer_router
from api.simulation import router as simulation_router
from services.sync_loop import sync_loop
from services.raft_node import raft_node
from services.write_behind import write_behind


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
    raft_node.start()
    write_behind.start()
    logger.info("CacheSplit v3 ready — http://127.0.0.1:8000")
    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    write_behind.stop()
    raft_node.stop()
    sync_loop.stop()
    registry.stop_sweep()
    await close_db()
    logger.info("Server shutdown complete.")


app = FastAPI(title="CacheSplit v3", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,   # Fixed: True + wildcard origin = OWASP CORS-01

    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard_router)
app.include_router(query_router)
app.include_router(propagation_router)
app.include_router(users_router)
app.include_router(payments_router)
app.include_router(scanner_router)
app.include_router(developer_router)
app.include_router(simulation_router)


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


class RaftRequestVote(BaseModel):
    term: int
    candidate_id: str
    last_log_index: int
    last_log_term: int

@app.post("/api/raft/request-vote")
async def raft_request_vote(req: RaftRequestVote):
    return raft_node.handle_request_vote(req.term, req.candidate_id, req.last_log_index, req.last_log_term)


class RaftHeartbeat(BaseModel):
    term: int
    leader_id: str

@app.post("/api/raft/heartbeat")
async def raft_heartbeat(req: RaftHeartbeat):
    return raft_node.handle_heartbeat(req.term, req.leader_id)


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


class RegisterRequest(BaseModel):
    node_id: str
    region: str
    tier: str
    join_token: str
    parent_node_id: str = None

@app.post("/api/register")
async def register(req: RegisterRequest):
    registry.register_node(req.node_id, req.region, req.tier, req.parent_node_id, req.join_token)
    await node_repo.upsert_node(node_id=req.node_id, region=req.region, tier=req.tier, join_token=req.join_token)
    return {"status": "registered"}


@app.get("/api/status/{node_id}")
async def get_status(node_id: str):
    return await node_repo.get_node(node_id)


class QuarantineRequest(BaseModel):
    node_id: str
    reason: str

@app.post("/api/debug/quarantine")
async def debug_quarantine(req: QuarantineRequest):
    registry.mark_quarantined(req.node_id, req.reason)
    node = registry.nodes.get(req.node_id)
    flags = node.agent_flags if node else [req.reason]
    await node_repo.update_node_health(req.node_id, "quarantined", flags)
    return {"status": "quarantined", "node_id": req.node_id}


from core.consistent_hash import HashRing

@app.get("/api/sharding/locate/{entity_id}")
async def locate_entity(entity_id: str):
    nodes = list(registry.nodes.keys())
    if not nodes:
        return {"entity_id": entity_id, "node_id": None}
    ring = HashRing(nodes)
    node = ring.get_node(entity_id)
    return {"entity_id": entity_id, "node_id": node}

@app.websocket("/api/ws/state")
async def websocket_endpoint(websocket: WebSocket):
    await state_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        state_manager.disconnect(websocket)

# ──────────────────────── Classic UI & Page Routes ───────────────────────────

_ui_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ui"))
_dashboard_file = os.path.join(_ui_dir, "dashboard.html")
_sim_dashboard = os.path.join(_ui_dir, "simulation_dashboard.html")
_dev_demo = os.path.join(_ui_dir, "developer_demo.html")
_test_cases = os.path.join(_ui_dir, "test_cases.html")


@app.get("/")
@app.get("/dashboard")
async def root():
    if os.path.exists(_dashboard_file):
        return FileResponse(_dashboard_file)
    return {"status": "CacheSplit v4 running"}


@app.get("/simulation")
async def simulation_page():
    if os.path.exists(_sim_dashboard):
        return FileResponse(_sim_dashboard)
    if os.path.exists(_dashboard_file):
        return FileResponse(_dashboard_file)
    return {"error": "Simulation dashboard not found"}


@app.get("/demo")
async def developer_demo():
    if os.path.exists(_dev_demo):
        return FileResponse(_dev_demo)
    return {"error": "Demo file not found"}


@app.get("/test_cases")
@app.get("/test_cases.html")
async def test_cases():
    if os.path.exists(_test_cases):
        return FileResponse(_test_cases)
    return {"error": "test_cases.html not found"}


@app.get("/style.css")
async def style_css():
    css_file = os.path.join(_ui_dir, "style.css")
    if os.path.exists(css_file):
        return FileResponse(css_file, media_type="text/css")
    return {"error": "style.css not found"}


@app.get("/app.js")
async def app_js():
    js_file = os.path.join(_ui_dir, "app.js")
    if os.path.exists(js_file):
        return FileResponse(js_file, media_type="application/javascript")
    return {"error": "app.js not found"}


if os.path.exists(_ui_dir):
    app.mount("/static", StaticFiles(directory=_ui_dir), name="static")

