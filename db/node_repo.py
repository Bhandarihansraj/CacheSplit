"""
CacheSplit v3 — Node Repository
Async SQLite operations for the nodes table.
"""
import json
import time
import logging
from typing import Optional
from db.database import get_db

logger = logging.getLogger(__name__)


async def upsert_node(
    node_id: str,
    region: str,
    tier: str = "main",
    health: str = "ok",
    last_heartbeat: Optional[float] = None,
    heartbeat_enabled: bool = True,
    agent_flags: Optional[list] = None,
    version_number: int = 0,
    current_commit_hash: str = "",
) -> None:
    db = get_db()
    flags_json = json.dumps(agent_flags or [])
    ts = time.time()
    lb = last_heartbeat if last_heartbeat is not None else ts
    await db.execute(
        """
        INSERT INTO nodes (node_id, region, tier, health, last_heartbeat, heartbeat_enabled,
                           agent_flags, version_number, current_commit_hash, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(node_id) DO UPDATE SET
            region=excluded.region,
            tier=excluded.tier,
            health=excluded.health,
            last_heartbeat=excluded.last_heartbeat,
            heartbeat_enabled=excluded.heartbeat_enabled,
            agent_flags=excluded.agent_flags,
            version_number=excluded.version_number,
            current_commit_hash=excluded.current_commit_hash
        """,
        (node_id, region, tier, health, lb, int(heartbeat_enabled),
         flags_json, version_number, current_commit_hash, ts),
    )
    await db.commit()


async def update_node_health(node_id: str, health: str, agent_flags: Optional[list] = None) -> None:
    db = get_db()
    if agent_flags is not None:
        await db.execute(
            "UPDATE nodes SET health=?, agent_flags=? WHERE node_id=?",
            (health, json.dumps(agent_flags), node_id),
        )
    else:
        await db.execute("UPDATE nodes SET health=? WHERE node_id=?", (health, node_id))
    await db.commit()


async def update_node_heartbeat(
    node_id: str, last_heartbeat: float, version_number: int, current_commit_hash: str
) -> None:
    db = get_db()
    await db.execute(
        """
        UPDATE nodes SET last_heartbeat=?, version_number=?, current_commit_hash=?,
                         health=CASE WHEN health='stale' THEN 'ok' ELSE health END,
                         agent_flags=CASE WHEN health='stale' THEN '[]' ELSE agent_flags END
        WHERE node_id=?
        """,
        (last_heartbeat, version_number, current_commit_hash, node_id),
    )
    await db.commit()


async def toggle_heartbeat(node_id: str, enabled: bool) -> None:
    db = get_db()
    await db.execute(
        "UPDATE nodes SET heartbeat_enabled=? WHERE node_id=?",
        (int(enabled), node_id),
    )
    await db.commit()


async def recover_node(node_id: str) -> None:
    db = get_db()
    ts = time.time()
    await db.execute(
        "UPDATE nodes SET health='ok', agent_flags='[]', heartbeat_enabled=1, last_heartbeat=? WHERE node_id=?",
        (ts, node_id),
    )
    await db.commit()


async def get_all_nodes() -> list[dict]:
    db = get_db()
    async with db.execute("SELECT * FROM nodes ORDER BY region") as cur:
        rows = await cur.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["agent_flags"] = json.loads(d.get("agent_flags") or "[]")
        d["heartbeat_enabled"] = bool(d.get("heartbeat_enabled", 1))
        result.append(d)
    return result


async def get_node(node_id: str) -> Optional[dict]:
    db = get_db()
    async with db.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    d = dict(row)
    d["agent_flags"] = json.loads(d.get("agent_flags") or "[]")
    d["heartbeat_enabled"] = bool(d.get("heartbeat_enabled", 1))
    return d


async def update_node(node_id: str, region: Optional[str] = None, tier: Optional[str] = None,
                      health: Optional[str] = None) -> bool:
    db = get_db()
    fields, vals = [], []
    if region is not None:
        fields.append("region=?"); vals.append(region)
    if tier is not None:
        fields.append("tier=?"); vals.append(tier)
    if health is not None:
        fields.append("health=?"); vals.append(health)
    if not fields:
        return False
    vals.append(node_id)
    await db.execute(f"UPDATE nodes SET {', '.join(fields)} WHERE node_id=?", vals)
    await db.commit()
    return True


async def delete_node(node_id: str) -> bool:
    db = get_db()
    async with db.execute("DELETE FROM nodes WHERE node_id=?", (node_id,)) as cur:
        deleted = cur.rowcount
    await db.commit()
    return deleted > 0


async def get_node_count() -> int:
    db = get_db()
    async with db.execute("SELECT COUNT(*) as c FROM nodes") as cur:
        row = await cur.fetchone()
    return row["c"] if row else 0
