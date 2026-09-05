"""
CacheSplit v3 — Commit & Entity Repository
Async SQLite operations for commit_log and entity_cache tables.
"""
import json
import time
import logging
from typing import Optional
from db.database import get_db

logger = logging.getLogger(__name__)


# ─────────────────────────── COMMIT LOG ────────────────────────────

async def insert_commit(
    transaction_id: str,
    commit_hash: str,
    entity_ids: list,
    mutations_json: str,
    merkle_roots_json: str,
    hashable_json: str = "",
) -> None:
    db = get_db()
    await db.execute(
        """
        INSERT OR IGNORE INTO commit_log
            (transaction_id, commit_hash, entity_ids, mutations_json, merkle_roots_json, hashable_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (transaction_id, commit_hash, json.dumps(entity_ids),
         mutations_json, merkle_roots_json, hashable_json, time.time()),
    )
    await db.commit()


async def get_recent_commits(limit: int = 20) -> list[dict]:
    db = get_db()
    async with db.execute(
        "SELECT * FROM commit_log ORDER BY created_at DESC LIMIT ?", (limit,)
    ) as cur:
        rows = await cur.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["entity_ids"] = json.loads(d.get("entity_ids") or "[]")
        d["mutations"] = json.loads(d.get("mutations_json") or "{}")
        d["merkle_roots"] = json.loads(d.get("merkle_roots_json") or "{}")
        result.append(d)
    return result


# ─────────────────────────── ENTITY CACHE ────────────────────────────

async def upsert_entity(
    entity_id: str,
    entity_type: str,
    region: str,
    node_id: str,
    data_dict: dict,
    local_hash: str,
    merkle_root_hash: str,
    parent_id: Optional[str] = None,
    children_ids: Optional[list] = None,
) -> None:
    db = get_db()
    now = time.time()
    await db.execute(
        """
        INSERT INTO entity_cache
            (entity_id, entity_type, region, node_id, data_json, local_hash,
             merkle_root_hash, parent_id, children_ids_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_id) DO UPDATE SET
            data_json=excluded.data_json,
            local_hash=excluded.local_hash,
            merkle_root_hash=excluded.merkle_root_hash,
            parent_id=excluded.parent_id,
            children_ids_json=excluded.children_ids_json,
            updated_at=excluded.updated_at
        """,
        (
            entity_id, entity_type, region, node_id,
            json.dumps(data_dict), local_hash, merkle_root_hash,
            parent_id, json.dumps(children_ids or []), now, now,
        ),
    )
    await db.commit()


async def get_entities_by_node(node_id: str, limit: int = 50) -> list[dict]:
    db = get_db()
    # Return entities for this node
    async with db.execute(
        """
        SELECT * FROM entity_cache
        WHERE node_id=?
        ORDER BY entity_id ASC LIMIT ?
        """,
        (node_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["data"] = json.loads(d.get("data_json") or "{}")
        d["children_ids"] = json.loads(d.get("children_ids_json") or "[]")
        result.append(d)
    return result


async def get_entity(entity_id: str) -> Optional[dict]:
    db = get_db()
    async with db.execute(
        "SELECT * FROM entity_cache WHERE entity_id=?", (entity_id,)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    d = dict(row)
    d["data"] = json.loads(d.get("data_json") or "{}")
    d["children_ids"] = json.loads(d.get("children_ids_json") or "[]")
    return d


async def get_entity_children(entity_id: str) -> list[dict]:
    db = get_db()
    async with db.execute(
        "SELECT * FROM entity_cache WHERE parent_id=? ORDER BY entity_type, entity_id",
        (entity_id,),
    ) as cur:
        rows = await cur.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["data"] = json.loads(d.get("data_json") or "{}")
        d["children_ids"] = json.loads(d.get("children_ids_json") or "[]")
        result.append(d)
    return result


async def count_entities_by_node(node_id: str) -> int:
    db = get_db()
    async with db.execute(
        "SELECT COUNT(*) as cnt FROM entity_cache WHERE node_id=?", (node_id,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row)["cnt"] if row else 0


async def get_signed_commits(limit: int = 20) -> list[dict]:
    """Recent commits with the exact hashable payload stored at write time (for chain verification)."""
    db = get_db()
    async with db.execute(
        "SELECT transaction_id, commit_hash, hashable_json, created_at "
        "FROM commit_log ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(row) for row in rows]
