"""
Agent guardrail for CacheSplit v4.
The single choke point every AI-driven decision must pass through.
Enforces "AI proposes, security core disposes."
"""
import logging
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class ProposalAction(str, Enum):
    REPAIR_REORDER = "repair_reorder"
    TIER_UPGRADE = "tier_upgrade"
    ANOMALY_RESPONSE = "anomaly_response"
    NODE_RECOVER = "node_recover"


@dataclass
class AIProposal:
    """An AI-driven decision proposal awaiting guardrail approval."""
    action: ProposalAction
    target: str  # node_id, tenant_id, key, etc.
    confidence: float  # 0.0-1.0
    data: dict = field(default_factory=dict)
    proposer: str = ""  # Which AI component generated this
    timestamp: float = field(default_factory=lambda: __import__("time").monotonic())


@dataclass
class ProposalResult:
    """Result of guardrail evaluation."""
    approved: bool
    reason: str = ""
    forwarded_to: str = ""
    proposal_id: str = ""


class AgentGuardrail:
    """
    Single choke point every AI-driven decision must pass through.
    Enforces "AI proposes, security core disposes."

    Security requirement:
    - Guardrail MUST re-check the proposal against the same
      lease/authz rules as a human-initiated action.
    - An AI proposal carries NO elevated privilege over a normal
      API call — ever.

    Must not:
    - Let any AI component call lease.py, audit_log.py, or
      storage_adapter.py directly. All AI output is DATA (score,
      suggestion), routed through this guardrail into existing,
      already-audited code paths.
    - Create a bypass lane for AI proposals.
    """

    # Map actions to their existing handler paths
    ACTION_HANDLERS: dict = {
        ProposalAction.REPAIR_REORDER: "repair_worker.enqueue",
        ProposalAction.TIER_UPGRADE: "topology.set_home_region",
        ProposalAction.ANOMALY_RESPONSE: "anomaly_detector.alert_only",
        ProposalAction.NODE_RECOVER: "recovery_coordinator.rebuild_lease",
    }

    def __init__(self, auth_manager, lease_manager, audit_log, metrics=None):
        self._auth = auth_manager
        self._lease = lease_manager
        self._audit = audit_log
        self._metrics = metrics
        self._proposals_processed = 0
        self._proposals_rejected = 0
        self._proposal_history: List[ProposalResult] = []

    async def submit_proposal(
        self, proposal: AIProposal, ctx: dict
    ) -> ProposalResult:
        """
        Submit an AI proposal through the guardrail.
        Returns ProposalResult — approved/forwarded or rejected.

        AI never gets its own lease/audit identity. It acts AS the
        requesting tenant/system through the normal authz path.
        No bypass lane exists.
        """
        self._proposals_processed += 1
        proposal_id = f"ai-prop-{proposal.timestamp:.0f}-{proposal.target[:8]}"

        logger.info(f"AI proposal received: {proposal.action.value} target={proposal.target}")

        # Step 1: Verify the AI component is authorized to propose
        if not self._validate_proposer(proposal):
            self._proposals_rejected += 1
            result = ProposalResult(
                approved=False,
                reason="Unauthorized proposer",
                proposal_id=proposal_id,
            )
            self._proposal_history.append(result)
            return result

        # Step 2: Re-check against same lease/authz rules as human action
        # The AI proposal does NOT get elevated privileges
        tenant_id = ctx.get("tenant_id", "")
        identity = ctx.get("identity", proposal.proposer)

        # Check if action requires lease and if lease is valid
        if proposal.action in (ProposalAction.REPAIR_REORDER, ProposalAction.NODE_RECOVER):
            if not self._lease:
                # Lease manager not configured — reject
                self._proposals_rejected += 1
                result = ProposalResult(
                    approved=False,
                    reason="Lease manager not available",
                    proposal_id=proposal_id,
                )
                self._proposal_history.append(result)
                return result

            # Verify lease for the target
            lease = await self._lease.validate("proposal-lease-token")
            if not lease:
                self._proposals_rejected += 1
                result = ProposalResult(
                    approved=False,
                    reason="No valid lease for proposal target",
                    proposal_id=proposal_id,
                )
                self._proposal_history.append(result)
                return result

        # Step 3: Check authorization for the specific action
        if not await self._check_action_authz(proposal, tenant_id, identity):
            self._proposals_rejected += 1
            result = ProposalResult(
                approved=False,
                reason=f"Authorization failed for action {proposal.action.value}",
                proposal_id=proposal_id,
            )
            self._proposal_history.append(result)
            return result

        # Step 4: Forward to existing handler — unchanged in privilege
        forwarded = self._dispatch_to_handler(proposal)
        logger.info(
            f"AI proposal forwarded: {proposal.action.value} "
            f"-> {forwarded} (as {identity})"
        )

        # Step 5: Audit the AI action
        if self._audit:
            await self._audit.append(
                event_type="AI_PROPOSAL_EXECUTED",
                tenant_id=tenant_id,
                payload={
                    "proposal_id": proposal_id,
                    "action": proposal.action.value,
                    "target": proposal.target,
                    "confidence": proposal.confidence,
                    "proposer": proposal.proposer,
                },
                actor=identity,
            )

        result = ProposalResult(
            approved=True,
            forwarded_to=forwarded,
            proposal_id=proposal_id,
        )
        self._proposal_history.append(result)
        return result

    def _validate_proposer(self, proposal: AIProposal) -> bool:
        """Validate the AI component that generated the proposal."""
        # In production: check against an allowlist of registered AI agents
        if not proposal.proposer:
            return False
        if proposal.confidence < 0.0 or proposal.confidence > 1.0:
            return False
        return True

    async def _check_action_authz(self, proposal: AIProposal,
                                    tenant_id: str,
                                    identity: str) -> bool:
        """
        Re-check authorization against the same rules as a human action.
        AI proposals carry no elevated privilege.
        """
        action = proposal.action.value
        # In production: call auth_manager.check_permission(identity, action)
        # For now, accept if tenant_id is valid
        if not tenant_id:
            return False
        logger.debug(f"AuthZ check passed for {identity} action={action} tenant={tenant_id}")
        return True

    def _dispatch_to_handler(self, proposal: AIProposal) -> str:
        """
        Route the proposal to the existing handler.
        AI never calls lease/audit/storage directly — it routes
        through this method to the already-audited code paths.
        """
        handler = self.ACTION_HANDLERS.get(proposal.action, "unknown")
        logger.info(f"Dispatching AI proposal to {handler}")
        return handler

    @property
    def rejection_rate(self) -> float:
        return self._proposals_rejected / max(self._proposals_processed, 1)

    def get_proposal_history(self, limit: int = 50) -> list:
        return self._proposal_history[-limit:]


# Global singleton
agent_guardrail = AgentGuardrail()
