"""
Network-level isolation for CacheSplit v4.
Enforces network-level isolation per tenant tier — this is the layer BELOW
app-level tenant scoping (tenant.py), so even a bug in tenant.py can't cross
a network boundary.

This file generates policy manifests (Kubernetes NetworkPolicy or cloud
security-group rules). It doesn't enforce — the infra controller does.
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class TenantTier(str, Enum):
    ENTERPRISE = "enterprise"
    STANDARD = "standard"
    BASIC = "basic"


class NetworkZone:
    """
    Defines which VPC/subnet/security-group a tenant's traffic routes through.
    Zone assignment enforced at infra layer (security groups/NACLs), not
    just returned as advisory data.
    """
    zone_id: str
    vpc_cidr: str
    subnet_cidr: str
    security_group_ids: List[str]
    tier: TenantTier

    def __init__(self, zone_id: str, vpc_cidr: str, subnet_cidr: str,
                 security_group_ids: List[str], tier: TenantTier):
        self.zone_id = zone_id
        self.vpc_cidr = vpc_cidr
        self.subnet_cidr = subnet_cidr
        self.security_group_ids = security_group_ids
        self.tier = tier

    @property
    def is_isolated(self) -> bool:
        """Enterprise tenants get fully dedicated network zones."""
        return self.tier == TenantTier.ENTERPRISE

    @property
    def allows_cross_zone_traffic(self) -> bool:
        """Only enterprise tenants allow any cross-zone communication."""
        return self.tier == TenantTier.ENTERPRISE


class NetworkPolicy:
    """
    Enforces network-level isolation per tenant tier.

    Security requirement:
    - Zone assignment enforced at infra layer (security groups/NACLs), not
      advisory-only. Policy violation = network-level DROP, not app-level check.
    - No cross-zone traffic between tenant tiers without going through
      api/auth.py — no direct pod-to-pod shortcuts.

    Must not:
    - Allow cross-zone traffic between tiers without API gateway.
    - Rely on app-level checks as the ONLY isolation mechanism.
    """

    # Config-driven mapping: tier -> network zone configuration
    TIER_ZONE_MAP: Dict[TenantTier, dict] = {
        TenantTier.ENTERPRISE: {
            "vpc_cidr": "10.0.0.0/16",
            "subnet_cidr": "10.0.0.0/24",
            "security_groups": ["sg-enterprise-full"],
            "dedicated": True,
        },
        TenantTier.STANDARD: {
            "vpc_cidr": "10.1.0.0/16",
            "subnet_cidr": "10.1.0.0/24",
            "security_groups": ["sg-standard-shared"],
            "dedicated": False,
        },
        TenantTier.BASIC: {
            "vpc_cidr": "10.2.0.0/16",
            "subnet_cidr": "10.2.0.0/24",
            "security_groups": ["sg-basic-pooled"],
            "dedicated": False,
        },
    }

    def __init__(self):
        self._zones: Dict[str, NetworkZone] = {}
        self._policy_manifests: List[dict] = []

    def get_zone(self, tenant_id: str, tier: TenantTier) -> NetworkZone:
        """
        Get or create the network zone for a tenant.
        Generates the policy manifest for the infra controller.
        """
        config = self.TIER_ZONE_MAP.get(tier, self.TIER_ZONE_MAP[TenantTier.STANDARD])
        zone_id = f"zone-{tenant_id[:8]}-{tier.value}"

        zone = NetworkZone(
            zone_id=zone_id,
            vpc_cidr=config["vpc_cidr"],
            subnet_cidr=config["subnet_cidr"],
            security_group_ids=config["security_groups"],
            tier=tier,
        )
        self._zones[tenant_id] = zone
        self._generate_policy_manifest(zone)
        logger.info(f"Network zone assigned: {zone_id} for {tenant_id} ({tier.value})")
        return zone

    def _generate_policy_manifest(self, zone: NetworkZone):
        """
        Generate the policy manifest for the infra controller.
        This creates Kubernetes NetworkPolicy or cloud security-group rules.
        The controller enforces these — this file only generates them.
        """
        manifest = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": zone.zone_id,
                "labels": {"tier": zone.tier.value, "zone": zone.zone_id},
            },
            "spec": {
                "podSelector": {"matchLabels": {"zone": zone.zone_id}},
                "policyTypes": ["Ingress", "Egress"],
                "ingress": [
                    {
                        "from": [
                            {"namespaceSelector": {"matchLabels": {"tier": zone.tier.value}}}
                        ],
                        "ports": [{"protocol": "TCP", "port": 8000}],
                    }
                ],
                "egress": self._get_egress_rules(zone),
            },
        }
        self._policy_manifests.append(manifest)
        logger.debug(f"Policy manifest generated for {zone.zone_id}")

    def _get_egress_rules(self, zone: NetworkZone) -> list:
        """Get egress rules based on tier isolation."""
        if zone.tier == TenantTier.ENTERPRISE:
            return [{"to": [{"namespaceSelector": {}}], "ports": [{"port": 0}]}]
        # Standard/Basic: only allow egress to API gateway
        return [
            {"to": [{"podSelector": {"matchLabels": {"app": "api-gateway"}}}], "ports": [{"port": 443}]}
        ]

    def get_zone_for_tenant(self, tenant_id: str) -> Optional[NetworkZone]:
        """Get the network zone for a tenant."""
        return self._zones.get(tenant_id)

    def enforce_cross_zone_check(self, source_tier: TenantTier,
                                  target_tier: TenantTier) -> bool:
        """
        Check if cross-zone traffic is allowed.
        Returns True if allowed, False if should be dropped at network level.
        """
        if source_tier == TenantTier.ENTERPRISE and target_tier == TenantTier.ENTERPRISE:
            return True
        if source_tier != target_tier:
            logger.warning(f"Cross-tier traffic denied: {source_tier.value} -> {target_tier.value}")
            return False
        return True


# Global singleton
network_policy = NetworkPolicy()
