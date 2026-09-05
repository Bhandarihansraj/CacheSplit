"""
CacheSplit v3 — Security & ReBAC Repository
Async SQLite operations for security_events and rebac_edges tables.
"""
import time
import logging
from typing import Optional
from collections import deque
from db.database import get_db

logger = logging.getLogger(__name__)


# ─────────────────────────── SECURITY EVENTS ────────────────────────────

async def insert_security_event(
    node_id: str,
    event_type: str,
    reason: str,
    severity: str = "MEDIUM",
    target_entity_id: str = "",
) -> None:
    db = get_db()
    await db.execute(
        """
        INSERT INTO security_events (node_id, event_type, reason, severity, target_entity_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (node_id, event_type, reason, severity, target_entity_id, time.time()),
    )
    await db.commit()


async def get_recent_security_events(limit: int = 20) -> list[dict]:
    db = get_db()
    async with db.execute(
        "SELECT * FROM security_events ORDER BY created_at DESC LIMIT ?", (limit,)
    ) as cur:
        rows = await cur.fetchall()
    return [dict(row) for row in rows]


# ─────────────────────────── REBAC EDGES ────────────────────────────

async def upsert_rebac_edge(source_id: str, relation: str, target_id: str) -> None:
    db = get_db()
    await db.execute(
        """
        INSERT OR IGNORE INTO rebac_edges (source_id, relation, target_id)
        VALUES (?, ?, ?)
        """,
        (source_id, relation, target_id),
    )
    await db.commit()


async def get_edges_from(source_id: str) -> list[dict]:
    db = get_db()
    async with db.execute(
        "SELECT * FROM rebac_edges WHERE source_id=?", (source_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [dict(row) for row in rows]


async def get_edges_to(target_id: str) -> list[dict]:
    db = get_db()
    async with db.execute(
        "SELECT * FROM rebac_edges WHERE target_id=?", (target_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [dict(row) for row in rows]


async def check_path_exists(source_id: str, target_id: str, max_depth: int = 4) -> bool:
    """
    BFS over rebac_edges table to check if a path exists between source and target.
    This is the DB-backed version of the in-memory ReBAC BFS.
    """
    if source_id == target_id:
        return True

    db = get_db()
    visited = {source_id}
    queue = deque([(source_id, 0)])

    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue

        # Outbound edges
        async with db.execute(
            "SELECT target_id FROM rebac_edges WHERE source_id=?", (current,)
        ) as cur:
            rows = await cur.fetchall()
        for row in rows:
            neighbor = row[0]
            if neighbor == target_id:
                return True
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))

        # Inbound edges (reciprocal care relationships)
        async with db.execute(
            "SELECT source_id FROM rebac_edges WHERE target_id=?", (current,)
        ) as cur:
            rows = await cur.fetchall()
        for row in rows:
            neighbor = row[0]
            if neighbor == target_id:
                return True
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))

    return False
