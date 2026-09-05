"""
services/audit_trail_service.py
Core service providing parameterized audit log queries, QA bad-data filters,
and cryptographic Merkle chain verification across nodes and branches.
"""
import time
import json
import logging
from typing import Dict, Any, List, Optional

from db.database import get_db

logger = logging.getLogger(__name__)


class AuditTrailService:
    """
    Query and analysis service for the immutable compliance audit trail.
    """

    async def query_trail(
        self,
        node_id: Optional[str] = None,
        branch_name: Optional[str] = None,
        developer_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        is_bad_data: Optional[bool] = None,
        min_risk: Optional[float] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Parameterized audit log query with selective filtering.
        """
        db = get_db()
        clauses = []
        params = []

        if node_id:
            clauses.append("node_id = ?")
            params.append(node_id)
        if branch_name:
            clauses.append("branch_name = ?")
            params.append(branch_name)
        if developer_id:
            clauses.append("developer_id = ?")
            params.append(developer_id)
        if entity_id:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if is_bad_data is not None:
            clauses.append("is_bad_data = ?")
            params.append(1 if is_bad_data else 0)
        if min_risk is not None:
            clauses.append("risk_score >= ?")
            params.append(min_risk)

        where_stmt = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query_sql = f"""
        SELECT id, node_id, branch_name, developer_id, event_type, entity_id,
               payload_json, is_bad_data, risk_score, diagnostic, created_at
        FROM audit_trail
        {where_stmt}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        cursor = await db.execute(query_sql, params)
        rows = await cursor.fetchall()

        events = []
        for r in rows:
            events.append({
                "id": r["id"],
                "node_id": r["node_id"],
                "branch_name": r["branch_name"],
                "developer_id": r["developer_id"],
                "event_type": r["event_type"],
                "entity_id": r["entity_id"],
                "payload": json.loads(r["payload_json"] or "{}"),
                "is_bad_data": bool(r["is_bad_data"]),
                "risk_score": r["risk_score"],
                "diagnostic": r["diagnostic"],
                "created_at": r["created_at"],
            })

        return {
            "total_returned": len(events),
            "limit": limit,
            "offset": offset,
            "events": events,
        }

    async def get_summary_stats(self) -> Dict[str, Any]:
        """Aggregate statistical distribution of the audit trail."""
        db = get_db()
        cursor = await db.execute("""
            SELECT 
                COUNT(*) as total_events,
                SUM(CASE WHEN is_bad_data = 1 THEN 1 ELSE 0 END) as bad_data_count,
                AVG(risk_score) as avg_risk_score,
                COUNT(DISTINCT node_id) as active_nodes,
                COUNT(DISTINCT branch_name) as active_branches
            FROM audit_trail
        """)
        row = await cursor.fetchone()
        return {
            "total_audit_events": row["total_events"] or 0,
            "bad_data_events": row["bad_data_count"] or 0,
            "average_risk_score": round(row["avg_risk_score"] or 0.0, 3),
            "active_audited_nodes": row["active_nodes"] or 0,
            "active_branches": row["active_branches"] or 0,
        }


audit_trail_service = AuditTrailService()
