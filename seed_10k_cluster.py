"""
seed_10k_cluster.py
High-Throughput Cluster Scaler & Seeder for CacheSplit v4.
Generates 10,000+ entities per node across us-east-1, eu-west-1, and asia-south-1 (30,000+ total),
populates multiple branches (main, dev/cardiology, dev/billing, qa/load-test),
allocates dynamic DHCP leases with canonical aliases, updates dot-indexer paths,
and stores lightweight hash pointers in lazy-cache with SQLite persistence.
"""
import asyncio
import hashlib
import json
import logging
import sqlite3
import time
import os
from typing import List, Dict, Any

from core.dhcp_discovery import dhcp_engine
from core.dot_indexer import dot_indexer
from core.lazy_cache import lazy_cache
from core.branch_engine import BranchEngine
from api.branches import node_branch_engines

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_10k")

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "cache_split.db"))

NODES = [
    ("us-east-1", "US-East", ["main", "dev/cardiology", "dev/billing", "qa/load-test"]),
    ("eu-west-1", "EU-West", ["main", "dev/cardiology", "dev/billing", "qa/load-test"]),
    ("asia-south-1", "Asia-South", ["main", "dev/cardiology", "dev/billing", "qa/load-test"]),
]

CATEGORIES = ["healthcare", "billing", "telemetry"]
CONDITIONS = ["Arrhythmia", "Hypertension", "Post-Surgery", "Oncology", "Stable", "Critical Care"]


def generate_node_entities(node_id: str, region: str, count: int = 10000) -> List[Dict[str, Any]]:
    entities = []
    reg_code = node_id.replace("-1", "").replace("-", "_")

    for i in range(1, count + 1):
        cat = CATEGORIES[(i - 1) % len(CATEGORIES)]
        if cat == "healthcare":
            eid = f"pat_{reg_code}_{i:05d}"
            etype = "patient"
            data = {
                "name": f"Patient {reg_code.upper()}-{i:05d}",
                "condition": CONDITIONS[i % len(CONDITIONS)],
                "vital_bpm": 60 + (i % 55),
                "room": f"Wing-{(i % 8) + 1}",
                "status": "admitted" if (i % 5 != 0) else "discharged",
            }
        elif cat == "billing":
            eid = f"inv_{reg_code}_{i:05d}"
            etype = "invoice"
            data = {
                "invoice_number": f"INV-{reg_code.upper()}-{i:05d}",
                "amount": round(150.0 + (i * 3.75) % 12500, 2),
                "status": "PAID" if (i % 3 == 0) else "PENDING",
                "insurance_provider": f"Provider-{(i % 6) + 1}",
            }
        else:
            eid = f"sensor_{reg_code}_{i:05d}"
            etype = "telemetry"
            data = {
                "sensor_id": f"SNS-{reg_code.upper()}-{i:05d}",
                "temperature_c": round(20.0 + (i % 15) * 0.8, 2),
                "vibration_hz": round(50.0 + (i % 30) * 1.5, 2),
                "status": "nominal" if (i % 20 != 0) else "alert",
            }

        data_str = json.dumps(data, sort_keys=True)
        local_hash = hashlib.sha256(f"{eid}:{etype}:{data_str}".encode()).hexdigest()

        entities.append({
            "entity_id": eid,
            "entity_type": etype,
            "category": cat,
            "region": region,
            "node_id": node_id,
            "data": data,
            "data_json": data_str,
            "local_hash": local_hash,
            "merkle_root_hash": local_hash,
            "parent_id": None,
            "children_ids_json": "[]",
            "updated_at": time.time(),
        })

    return entities


def seed_cluster_10k(entities_per_node: int = 10000):
    start_time = time.time()
    logger.info(f"Starting 10K+ Scaler Seeding: {entities_per_node} entities per node across {len(NODES)} nodes...")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Ensure entity_cache table exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS entity_cache (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            region TEXT NOT NULL,
            node_id TEXT NOT NULL,
            data_json TEXT NOT NULL,
            local_hash TEXT NOT NULL,
            merkle_root_hash TEXT NOT NULL,
            parent_id TEXT,
            children_ids_json TEXT DEFAULT '[]',
            updated_at REAL NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_entity_node ON entity_cache(node_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_entity_type ON entity_cache(entity_type)")

    total_seeded = 0
    total_dhcp_leases = 0

    for node_id, region, branches in NODES:
        logger.info(f"Generating {entities_per_node} entities for node '{node_id}' ({region})...")
        node_entities = generate_node_entities(node_id, region, entities_per_node)

        # 1. Batch insert into SQLite DB
        db_rows = [
            (
                e["entity_id"],
                e["entity_type"],
                e["region"],
                e["node_id"],
                e["data_json"],
                e["local_hash"],
                e["merkle_root_hash"],
                e["parent_id"],
                e["children_ids_json"],
                e["updated_at"],
            )
            for e in node_entities
        ]
        cur.executemany("""
            INSERT OR REPLACE INTO entity_cache (
                entity_id, entity_type, region, node_id, data_json,
                local_hash, merkle_root_hash, parent_id, children_ids_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, db_rows)
        conn.commit()
        total_seeded += len(node_entities)

        # 2. Initialize Branch Engine for this node with branches
        engine = node_branch_engines.get(node_id)
        if not engine:
            engine = BranchEngine(node_id=node_id)
            node_branch_engines[node_id] = engine

        for b_name in branches:
            if b_name != "main" and b_name not in engine._branches:
                engine.create_branch(b_name, developer_id=f"dev-{node_id}", from_branch="main")

        # Add sampled mutations to main and feature branches
        sample_mutations = [
            {"entity_id": e["entity_id"], "entity_type": e["entity_type"], "data": e["data"]}
            for e in node_entities[:100]
        ]
        engine.commit("main", sample_mutations, developer_id=f"lead-{node_id}", message="Baseline 10k cluster initialization")

        cardio_mutations = [
            {"entity_id": e["entity_id"], "entity_type": e["entity_type"], "data": {"cardio_lead": "Dr. Vance", "arrhythmia_score": 0.88}}
            for e in node_entities if e["category"] == "healthcare"
        ][:50]
        if "dev/cardiology" in engine._branches and cardio_mutations:
            engine.commit("dev/cardiology", cardio_mutations, developer_id="dev-cardio", message="Telemetry & Cardio enhancements")

        # 3. Register DHCP dynamic leases & canonical aliases
        for idx, e in enumerate(node_entities):
            lease = dhcp_engine.allocate_lease(
                raw_id=e["entity_id"],
                entity_type=e["entity_type"],
                node_id=node_id,
                branch_name="main",
                category=e["category"],
                custom_name=e["entity_id"].replace("_", "-"),
            )
            total_dhcp_leases += 1

            # 4. Store ultra-lightweight hash pointer in Lazy Cache
            lazy_cache.put_pointer(
                key=e["entity_id"],
                sha256_hash=e["local_hash"],
                version=1,
                node_id=node_id,
                state="FRESH",
            )

            # 5. Populate hierarchical dot index paths for first 200 entities per node
            if idx < 200:
                dot_path = f"nodes.{node_id}.branches.main.entities.{e['entity_id']}"
                dot_indexer.set_path(dot_path, {
                    "entity_type": e["entity_type"],
                    "category": e["category"],
                    "alias": lease.canonical_alias,
                    "local_hash": e["local_hash"],
                    "data": e["data"],
                })

        # Set summary index paths
        dot_indexer.set_path(f"nodes.{node_id}.summary", {
            "entity_count": entities_per_node,
            "region": region,
            "branches": branches,
            "merkle_root": engine.get_dag("main").compute_root_hash(),
        })

    conn.close()
    elapsed = time.time() - start_time
    logger.info(f"✅ Seeding Complete in {elapsed:.2f}s!")
    logger.info(f"📊 Total DB Entities: {total_seeded:,} across {len(NODES)} nodes")
    logger.info(f"🌐 Total DHCP Leases: {total_dhcp_leases:,}")
    logger.info(f"⚡ Lazy Cache Pointers: {lazy_cache.stats()['pointer_count']:,}")


if __name__ == "__main__":
    seed_cluster_10k(entities_per_node=10000)
