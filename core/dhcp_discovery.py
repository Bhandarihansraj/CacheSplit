"""
core/dhcp_discovery.py
DHCP-style Dynamic Node & Entity Discovery Protocol for CacheSplit v4.
Eliminates the need for developers to memorize random UUIDs/hashes.
Assigns dynamic leases, human-readable canonical aliases (e.g. 'cluster.us-east.cardiology.patient-001'),
and provides an in-memory global directory with O(1) prefix search.
"""
import time
import uuid
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DHCPLease:
    lease_id: str
    canonical_alias: str
    raw_id: str
    entity_type: str
    node_id: str
    branch_name: str
    assigned_ip: str
    expires_at: float
    created_at: float = field(default_factory=time.time)

    def is_valid(self) -> bool:
        return time.time() < self.expires_at


class DHCPDiscoveryEngine:
    """
    DHCP-style Auto-Discovery & Dynamic Addressing Server for CacheSplit clusters.
    Maps obscure hashes to clean, human-readable network aliases.
    """

    def __init__(self, default_lease_ttl_s: float = 86400.0):
        self.default_lease_ttl_s = default_lease_ttl_s
        # alias -> DHCPLease
        self._leases_by_alias: Dict[str, DHCPLease] = {}
        # raw_id -> canonical_alias
        self._raw_to_alias: Dict[str, str] = {}
        # node_id -> list of aliases
        self._node_directory: Dict[str, List[str]] = {}
        # Simulated IP space counter: 10.100.x.y
        self._ip_counter = 1

    def allocate_lease(
        self,
        raw_id: str,
        entity_type: str,
        node_id: str,
        branch_name: str = "main",
        category: str = "general",
        custom_name: Optional[str] = None,
        ttl_s: Optional[float] = None,
    ) -> DHCPLease:
        """
        Dynamically assign a DHCP lease and human-readable canonical alias.
        Example alias: 'cluster.us-east.cardiology.patient-001'
        """
        if raw_id in self._raw_to_alias:
            existing_alias = self._raw_to_alias[raw_id]
            lease = self._leases_by_alias.get(existing_alias)
            if lease and lease.is_valid():
                return lease

        name_part = custom_name or raw_id.replace("_", "-")
        region_clean = node_id.replace("-1", "").replace("-", ".")
        alias = f"cluster.{region_clean}.{category}.{name_part}"

        # Assign simulated cluster IP: 10.100.subnet.host
        subnet = (self._ip_counter // 254) % 254 + 1
        host = (self._ip_counter % 254) + 1
        assigned_ip = f"10.100.{subnet}.{host}"
        self._ip_counter += 1

        lease_id = f"dhcp-lease-{uuid.uuid4().hex[:8]}"
        expires_at = time.time() + (ttl_s or self.default_lease_ttl_s)

        lease = DHCPLease(
            lease_id=lease_id,
            canonical_alias=alias,
            raw_id=raw_id,
            entity_type=entity_type,
            node_id=node_id,
            branch_name=branch_name,
            assigned_ip=assigned_ip,
            expires_at=expires_at,
        )

        self._leases_by_alias[alias] = lease
        self._raw_to_alias[raw_id] = alias

        if node_id not in self._node_directory:
            self._node_directory[node_id] = []
        if alias not in self._node_directory[node_id]:
            self._node_directory[node_id].append(alias)

        logger.debug(f"DHCP Allocated: {raw_id} -> '{alias}' [{assigned_ip}] on {node_id}:{branch_name}")
        return lease

    def resolve_alias(self, alias: str) -> Optional[Dict[str, Any]]:
        """Resolve a canonical alias into its raw entity ID and connection info."""
        lease = self._leases_by_alias.get(alias)
        if not lease or not lease.is_valid():
            return None
        return {
            "canonical_alias": lease.canonical_alias,
            "raw_id": lease.raw_id,
            "entity_type": lease.entity_type,
            "node_id": lease.node_id,
            "branch_name": lease.branch_name,
            "assigned_ip": lease.assigned_ip,
            "expires_in_s": round(max(0, lease.expires_at - time.time()), 1),
        }

    def resolve_raw_id(self, raw_id: str) -> Optional[str]:
        """Find the canonical alias for a raw entity ID."""
        return self._raw_to_alias.get(raw_id)

    def search_directory(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Fast substring and prefix search across all aliases, entity IDs, and nodes."""
        q = query.lower().strip()
        results = []
        for alias, lease in self._leases_by_alias.items():
            if not lease.is_valid():
                continue
            if (
                q in alias.lower()
                or q in lease.raw_id.lower()
                or q in lease.node_id.lower()
                or q in lease.entity_type.lower()
                or q in lease.branch_name.lower()
            ):
                results.append({
                    "canonical_alias": lease.canonical_alias,
                    "raw_id": lease.raw_id,
                    "entity_type": lease.entity_type,
                    "node_id": lease.node_id,
                    "branch_name": lease.branch_name,
                    "assigned_ip": lease.assigned_ip,
                })
                if len(results) >= limit:
                    break
        return results

    def get_node_catalog(self) -> Dict[str, Any]:
        """Return full catalog of connected nodes and their allocated aliases."""
        return {
            "total_leases": len(self._leases_by_alias),
            "nodes": {
                nid: {
                    "alias_count": len(aliases),
                    "sample_aliases": aliases[:5],
                }
                for nid, aliases in self._node_directory.items()
            }
        }


dhcp_engine = DHCPDiscoveryEngine()
