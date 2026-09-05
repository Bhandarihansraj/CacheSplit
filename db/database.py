"""
CacheSplit v3 — Async SQLite Database Manager
Persistent storage using aiosqlite with WAL mode.
"""
import aiosqlite
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_db: Optional[aiosqlite.Connection] = None

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cachesplit.db")

CREATE_TABLES = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY,
    region TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'main',
    health TEXT NOT NULL DEFAULT 'ok',
    last_heartbeat REAL DEFAULT 0.0,
    heartbeat_enabled INTEGER NOT NULL DEFAULT 1,
    agent_flags TEXT NOT NULL DEFAULT '[]',
    version_number INTEGER NOT NULL DEFAULT 0,
    current_commit_hash TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    handshake_status TEXT NOT NULL DEFAULT 'pending',
    join_token TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS commit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT UNIQUE NOT NULL,
    commit_hash TEXT NOT NULL,
    hashable_json TEXT NOT NULL DEFAULT '',
    entity_ids TEXT NOT NULL DEFAULT '[]',
    mutations_json TEXT NOT NULL DEFAULT '{}',
    merkle_roots_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_cache (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    region TEXT NOT NULL,
    node_id TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}',
    local_hash TEXT NOT NULL DEFAULT '',
    merkle_root_hash TEXT NOT NULL DEFAULT '',
    parent_id TEXT,
    children_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS security_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'MEDIUM',
    target_entity_id TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rebac_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    target_id TEXT NOT NULL,
    UNIQUE(source_id, relation, target_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_node ON entity_cache(node_id);
CREATE INDEX IF NOT EXISTS idx_entity_parent ON entity_cache(parent_id);
CREATE INDEX IF NOT EXISTS idx_rebac_source ON rebac_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_rebac_target ON rebac_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_commit_created ON commit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_created ON security_events(created_at DESC);
"""


async def init_db(db_path: Optional[str] = None) -> aiosqlite.Connection:
    """Initialize the database, create all tables, return the connection."""
    global _db
    resolved_path = db_path or DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(resolved_path)), exist_ok=True)

    _db = await aiosqlite.connect(resolved_path)
    _db.row_factory = aiosqlite.Row

    # Execute each statement individually (aiosqlite doesn't support executescript with async)
    async with _db.executescript(CREATE_TABLES):
        pass

    # ── Migration: add hashable_json if missing (DBs created before signing was added)
    try:
        await _db.execute("ALTER TABLE commit_log ADD COLUMN hashable_json TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass  # column already exists

    try:
        await _db.execute("ALTER TABLE nodes ADD COLUMN handshake_status TEXT NOT NULL DEFAULT 'pending'")
        await _db.execute("ALTER TABLE nodes ADD COLUMN join_token TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass

    await _db.commit()
    logger.info(f"Database initialized at {resolved_path}")
    return _db


async def close_db() -> None:
    """Close the active database connection."""
    global _db
    if _db:
        await _db.close()
        _db = None
        logger.info("Database connection closed.")


def get_db() -> aiosqlite.Connection:
    """Return the active singleton database connection. Must call init_db first."""
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first (done in server lifespan).")
    return _db
