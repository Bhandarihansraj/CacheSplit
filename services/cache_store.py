"""
CacheSplit v3 — Regional Cache Store
Wires MerkleDAG (in-memory graph) + SQLite (persistence) together.
All mutations are written through to DB. On startup, DB state is replayed
into the in-memory DAG for fast graph queries.
"""
import hashlib
import json
import random
import time
import logging
from typing import Dict, List, Optional, Any

from core.merkle_dag import MerkleDAG, EntityNode
from core.compound_commit import CompoundCommit, EntityMutation, RelationshipEdge
from agents.graph_security_agent import GraphSecurityAgent
from services.analytics import analytics

logger = logging.getLogger(__name__)


CONDITIONS = [
    "Hypertension", "Type-2 Diabetes", "Asthma",
    "Arrhythmia", "Recovery", "Stable", "Post-Surgery", "Oncology"
]
CLINICIANS = [
    ("doc_jenkins", "Dr. Sarah Jenkins", "US-East"),
    ("doc_vance",   "Dr. Robert Vance",  "EU-West"),
    ("doc_chen",    "Dr. Wei Chen",       "Asia-South"),
]
REGIONS = [
    ("us-east-1",     "US-East"),
    ("eu-west-1",     "EU-West"),
    ("asia-south-1",  "Asia-South"),
]


class RegionalCacheStore:
    def __init__(self):
        self.dag = MerkleDAG()
        self.graph_security = GraphSecurityAgent(self.dag)
        self.node_partitions: Dict[str, List[str]] = {}
        self.entity_to_node: Dict[str, str] = {}
        self.initialized = False

    # ──────────────────────────────── SEEDING ────────────────────────────────

    async def seed_regional_cluster_data(self, entities_per_zone: int = 50):
        """
        Seeds the DB and in-memory DAG with structured ER trees.
        Patient → Visit → [LabResult, BedAllocation]
        Clinician -ASSIGNED_TO-> Visit (first 15 per region)
        Also inserts one rogue orphan billing record for graph anomaly demo.
        """
        if self.initialized:
            return

        from db import node_repo, commit_repo, security_repo
        from db.database import get_db

        # Check if DB already has entities
        db = get_db()
        async with db.execute("SELECT COUNT(*) as c FROM entity_cache") as cur:
            row = await cur.fetchone()
            
        if row and row["c"] > 0:
            await self._hydrate_from_db()
            self.initialized = True
            return

        # Seed clinicians into DAG + DB
        for c_id, name, reg in CLINICIANS:
            node = EntityNode(
                entity_id=c_id, entity_type="clinician",
                region=reg, data={"name": name, "department": "Internal Medicine"},
            )
            self.dag.add_entity(node)
            node.compute_local_hash()
            await commit_repo.upsert_entity(
                entity_id=c_id, entity_type="clinician", region=reg,
                node_id=f"{reg.lower().replace('-', '_')}-node",
                data_dict=node.data, local_hash=node.local_hash,
                merkle_root_hash=node.local_hash,
            )

        for node_id, region in REGIONS:
            self.node_partitions[node_id] = []

            for i in range(1, entities_per_zone + 1):
                safe_region = region.lower().replace("-", "_")
                p_id = f"pat_{safe_region}_{i:03d}"
                v_id = f"vis_{safe_region}_{i:03d}"
                l_id = f"lab_{safe_region}_{i:03d}"
                b_id = f"bed_{safe_region}_{i:03d}"

                cond = random.choice(CONDITIONS)
                lab_val = round(random.uniform(70.0, 145.0), 1)
                bed_num = (i % 20) + 1

                # 1 — Patient
                p_node = EntityNode(
                    entity_id=p_id, entity_type="patient", region=region,
                    data={"name": f"Patient {i:04d}", "condition": cond, "status": "admitted"},
                )
                self.dag.add_entity(p_node)
                self.node_partitions[node_id].append(p_id)
                self.entity_to_node[p_id] = node_id

                # 2 — Visit
                v_node = EntityNode(
                    entity_id=v_id, entity_type="visit", region=region,
                    data={"admission_type": "inpatient", "room": f"Wing-{i % 4 + 1}"},
                )
                self.dag.add_entity(v_node)
                self.dag.add_edge(p_id, "HAS_CURRENT_VISIT", v_id)
                self.entity_to_node[v_id] = node_id

                # 3 — Lab Result
                l_node = EntityNode(
                    entity_id=l_id, entity_type="lab_result", region=region,
                    data={"panel": "Metabolic Comprehensive", "value": lab_val, "unit": "mg/dL"},
                )
                self.dag.add_entity(l_node)
                self.dag.add_edge(v_id, "CONTAINS_LAB", l_id)
                self.entity_to_node[l_id] = node_id

                # 4 — Bed
                b_node = EntityNode(
                    entity_id=b_id, entity_type="bed", region=region,
                    data={"bed_code": f"B-{bed_num:02d}", "status": "occupied"},
                )
                self.dag.add_entity(b_node)
                self.dag.add_edge(v_id, "ALLOCATED_BED", b_id)
                self.entity_to_node[b_id] = node_id

                # Clinician assignments (first 15 per region)
                if i <= 15:
                    clinician_id = (
                        "doc_jenkins" if region == "US-East"
                        else "doc_vance" if region == "EU-West"
                        else "doc_chen"
                    )
                    self.dag.add_edge(clinician_id, "ASSIGNED_TO", v_id)
                    await security_repo.upsert_rebac_edge(clinician_id, "ASSIGNED_TO", v_id)
                    await security_repo.upsert_rebac_edge(p_id, "HAS_CURRENT_VISIT", v_id)
                    await security_repo.upsert_rebac_edge(v_id, "CONTAINS_LAB", l_id)
                    await security_repo.upsert_rebac_edge(v_id, "ALLOCATED_BED", b_id)

                # Compute Merkle root
                merkle_root = self.dag.compute_merkle_root(p_id)
                p_node_dag = self.dag.entities[p_id]

                # Persist to DB
                await commit_repo.upsert_entity(
                    p_id, "patient", region, node_id, p_node.data,
                    p_node_dag.local_hash, merkle_root,
                    children_ids=[v_id],
                )
                await commit_repo.upsert_entity(
                    v_id, "visit", region, node_id, v_node.data,
                    self.dag.entities[v_id].local_hash,
                    self.dag.entities[v_id].local_hash,
                    parent_id=p_id, children_ids=[l_id, b_id],
                )
                await commit_repo.upsert_entity(
                    l_id, "lab_result", region, node_id, l_node.data,
                    self.dag.entities[l_id].local_hash,
                    self.dag.entities[l_id].local_hash,
                    parent_id=v_id,
                )
                await commit_repo.upsert_entity(
                    b_id, "bed", region, node_id, b_node.data,
                    self.dag.entities[b_id].local_hash,
                    self.dag.entities[b_id].local_hash,
                    parent_id=v_id,
                )

        # Orphan billing record for graph anomaly demo
        orphan = EntityNode(
            entity_id="bill_rogue_999", entity_type="billing",
            region="US-East",
            data={"amount": 14950.00, "status": "unlinked_scraping_target"},
        )
        self.dag.add_entity(orphan)
        orphan.compute_local_hash()
        await commit_repo.upsert_entity(
            "bill_rogue_999", "billing", "US-East", "us-east-1",
            orphan.data, orphan.local_hash, orphan.local_hash,
        )

        self.initialized = True
        logger.info("Regional cluster data seeded to DB and in-memory DAG.")

    async def _hydrate_from_db(self):
        """Replay DB entity_cache and rebac_edges back into the in-memory DAG."""
        from db.database import get_db
        db = get_db()

        async with db.execute("SELECT * FROM entity_cache") as cur:
            rows = await cur.fetchall()

        for row in rows:
            d = dict(row)
            node = EntityNode(
                entity_id=d["entity_id"],
                entity_type=d["entity_type"],
                region=d["region"],
                data=json.loads(d.get("data_json") or "{}"),
                parent_id=d.get("parent_id"),
                children_ids=json.loads(d.get("children_ids_json") or "[]"),
                local_hash=d.get("local_hash", ""),
                merkle_root_hash=d.get("merkle_root_hash", ""),
            )
            self.dag.entities[node.entity_id] = node
            node_id = d.get("node_id", "")
            if node_id:
                if node_id not in self.node_partitions:
                    self.node_partitions[node_id] = []
                if node.entity_type == "patient":
                    self.node_partitions[node_id].append(node.entity_id)
                self.entity_to_node[node.entity_id] = node_id

        async with db.execute("SELECT * FROM rebac_edges") as cur:
            rows = await cur.fetchall()
        for row in rows:
            d = dict(row)
            self.dag.add_edge(d["source_id"], d["relation"], d["target_id"])

        logger.info(f"In-memory DAG hydrated: {len(self.dag.entities)} entities, "
                    f"{sum(len(v) for v in self.dag.edges.values())} edges from SQLite DB.")

    # ──────────────────────────────── QUERIES ────────────────────────────────

    async def get_node_entities_from_db(self, node_id: str, limit: int = 50) -> List[Dict]:
        from db import commit_repo
        rows = await commit_repo.get_entities_by_node(node_id, limit=limit)
        result = []
        # Derive region from the first row for logging
        node_region = rows[0]["region"] if rows else ""
        for row in rows:
            analytics.log_access(
                node_id=node_id, entity_id=row["entity_id"],
                entity_type=row["entity_type"], access_type="read",
                requester_region=node_region, target_region=row["region"],
            )
            dag_node = self.dag.entities.get(row["entity_id"])
            short_hash = (row.get("merkle_root_hash") or "")[:16] + "..."
            result.append({
                "entity_id": row["entity_id"],
                "entity_type": row["entity_type"],
                "region": row["region"],
                "data": row["data"],
                "children_count": len(row.get("children_ids") or []),
                "merkle_root_hash": row.get("merkle_root_hash", ""),
                "short_hash": short_hash,
                "updated_at": row.get("updated_at", 0),
            })
        return result

    async def count_node_entities(self, node_id: str) -> int:
        from db import commit_repo
        return await commit_repo.count_entities_by_node(node_id)

    def get_entity_dag_tree(self, entity_id: str) -> Dict:
        return self.dag.get_relational_tree(entity_id)

    async def execute_compound_commit(self, commit: CompoundCommit) -> Dict:
        """Apply atomic compound commit and persist to DB."""
        from db import commit_repo, security_repo

        commit.compute_commit_hash()
        updated_roots = commit.apply_to_dag(self.dag)

        # Persist all mutated entities to DB + log access
        for mut in commit.mutations:
            dag_node = self.dag.entities.get(mut.entity_id)
            if dag_node:
                node_id = self.entity_to_node.get(mut.entity_id, "us-east-1")
                analytics.log_access(
                    node_id=node_id, entity_id=mut.entity_id,
                    entity_type=mut.entity_type, access_type="write",
                    requester_region=dag_node.region, target_region=dag_node.region,
                )
                await commit_repo.upsert_entity(
                    entity_id=mut.entity_id,
                    entity_type=mut.entity_type,
                    region=dag_node.region,
                    node_id=node_id,
                    data_dict=dag_node.data,
                    local_hash=dag_node.local_hash,
                    merkle_root_hash=dag_node.merkle_root_hash,
                    parent_id=dag_node.parent_id,
                    children_ids=dag_node.children_ids,
                )

        # Persist edges to rebac_edges
        for edge in commit.edges:
            await security_repo.upsert_rebac_edge(edge.source, edge.relation, edge.target)

        # Log commit to commit_log table — store the exact signed payload so the
        # chain can be cryptographically re-verified later during propagation.
        await commit_repo.insert_commit(
            transaction_id=commit.transaction_id,
            commit_hash=commit.commit_hash,
            entity_ids=[m.entity_id for m in commit.mutations],
            mutations_json=json.dumps([m.model_dump() for m in commit.mutations]),
            merkle_roots_json=json.dumps(updated_roots),
            hashable_json=commit.signed_payload(),
        )

        return {
            "transaction_id": commit.transaction_id,
            "commit_hash": commit.commit_hash,
            "mutations_applied": len(commit.mutations),
            "updated_merkle_roots": updated_roots,
        }

    async def authorize_rebac(self, clinician_id: str, target_entity_id: str) -> Dict:
        """DB-backed ReBAC authorization using BFS over rebac_edges table."""
        from db import security_repo

        target_entity = self.dag.entities.get(target_entity_id)
        # Log the access attempt for ML training / scoring
        analytics.log_access(
            node_id=clinician_id, entity_id=target_entity_id,
            entity_type=target_entity.entity_type if target_entity else "",
            access_type="query",
            requester_region=target_entity.region if target_entity else "",
            target_region=target_entity.region if target_entity else "",
        )
        authorized = await security_repo.check_path_exists(clinician_id, target_entity_id)

        if authorized:
            return {
                "authorized": True,
                "clinician_id": clinician_id,
                "target_id": target_entity_id,
                "entity_type": target_entity.entity_type if target_entity else "unknown",
                "data": target_entity.data if target_entity else {},
            }
        return {
            "authorized": False,
            "clinician_id": clinician_id,
            "target_id": target_entity_id,
            "reason": (
                f"ReBAC Violation: No active care-team assignment path exists between "
                f"'{clinician_id}' and '{target_entity_id}'."
            ),
        }

    async def evaluate_graph_security(
        self, requesting_node_id: str, requester_region: str, target_entity_id: str
    ) -> Dict:
        """Evaluate and persist security anomaly to DB."""
        from db import security_repo

        target_entity = self.dag.entities.get(target_entity_id)
        # Log the traversal attempt for ML scoring
        analytics.log_access(
            node_id=requesting_node_id, entity_id=target_entity_id,
            entity_type=target_entity.entity_type if target_entity else "",
            access_type="query",
            requester_region=requester_region,
            target_region=target_entity.region if target_entity else "",
        )

        result = self.graph_security.evaluate_traversal(
            requesting_node_id=requesting_node_id,
            requester_region=requester_region,
            target_entity_id=target_entity_id,
        )
        if result.get("flagged"):
            await security_repo.insert_security_event(
                node_id=requesting_node_id,
                event_type=result.get("verdict", "ANOMALY").upper(),
                reason=result["reason"],
                severity=result.get("severity", "CRITICAL"),
                target_entity_id=target_entity_id,
            )
        return result


# Global singleton
cache_store = RegionalCacheStore()
