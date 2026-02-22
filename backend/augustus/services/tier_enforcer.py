"""Tier Permission Enforcer — controls basin modification permissions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from augustus.models.dataclasses import BasinConfig, TierProposal, TierSettings
from augustus.utils import utcnow_iso
from augustus.models.enums import TierLevel, ProposalStatus, ProposalType

logger = logging.getLogger(__name__)


@dataclass
class BasinChange:
    """Detected change between proposed and current basin states."""

    basin_name: str
    change_type: str  # "create", "prune", "modify"
    tier: TierLevel = TierLevel.TIER_3
    current: BasinConfig | None = None
    proposed: BasinConfig | None = None
    detail: str = ""


@dataclass
class TierCheckResult:
    """Result of checking YAML modifications against tier permissions."""

    allowed: list[BasinConfig] = field(default_factory=list)
    blocked: list[BasinChange] = field(default_factory=list)
    proposals_created: list[TierProposal] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ProposalDecision:
    """Decision on a tier modification proposal."""

    approved: bool = False
    reason: str = ""
    auto: bool = False


class TierEnforcer:
    """Enforce tier-based modification permissions on basin parameters."""

    def __init__(self, memory) -> None:
        """Initialize with a MemoryService instance."""
        self.memory = memory

    async def check_yaml_modifications(
        self,
        agent_id: str,
        proposed_basins: list[BasinConfig],
        current_basins: list[BasinConfig],
        tier_settings: TierSettings,
    ) -> TierCheckResult:
        """Compare proposed basins against current basins and check tier permissions."""
        changes = self.detect_basin_changes(proposed_basins, current_basins)
        result = TierCheckResult()

        current_map = {b.name: b for b in current_basins}
        proposed_map = {b.name: b for b in proposed_basins}

        for change in changes:
            if change.tier == TierLevel.TIER_1:
                # Tier 1: Always blocked
                result.blocked.append(change)
                proposal = TierProposal(
                    proposal_id=f"prop-{agent_id}-{change.basin_name}-{utcnow_iso()}",
                    agent_id=agent_id,
                    basin_name=change.basin_name,
                    tier=change.tier,
                    proposal_type=ProposalType(
                        change.change_type
                    )
                    if change.change_type in ("modify", "create", "prune", "merge")
                    else ProposalType.MODIFY,
                    status=ProposalStatus.REJECTED,
                    rationale=f"Tier 1 invariant modification blocked: {change.detail}",
                    created_at=utcnow_iso(),
                    proposed_config=change.proposed,
                )
                result.proposals_created.append(proposal)
                result.warnings.append(
                    f"Tier 1 modification of '{change.basin_name}' blocked"
                )

            elif change.tier == TierLevel.TIER_2:
                # Tier 2: Create proposal, may auto-approve
                proposal = TierProposal(
                    proposal_id=f"prop-{agent_id}-{change.basin_name}-{utcnow_iso()}",
                    agent_id=agent_id,
                    basin_name=change.basin_name,
                    tier=change.tier,
                    proposal_type=ProposalType(
                        change.change_type
                    )
                    if change.change_type in ("modify", "create", "prune", "merge")
                    else ProposalType.MODIFY,
                    status=ProposalStatus.PENDING,
                    rationale=change.detail,
                    created_at=utcnow_iso(),
                    proposed_config=change.proposed,
                )

                decision = await self.process_tier_proposal(
                    agent_id, proposal, tier_settings
                )

                if decision.approved:
                    proposal.status = (
                        ProposalStatus.AUTO_APPROVED
                        if decision.auto
                        else ProposalStatus.APPROVED
                    )
                    proposal.resolved_at = utcnow_iso()
                    proposal.resolved_by = "auto" if decision.auto else "system"
                    if change.proposed:
                        result.allowed.append(change.proposed)
                else:
                    result.blocked.append(change)

                result.proposals_created.append(proposal)

            elif change.tier == TierLevel.TIER_3:
                # Tier 3: Modifications always allowed; new basins check emergence settings
                if change.change_type == "create":
                    # New basin — check emergence settings
                    if await self.is_new_basin_allowed(
                        change.basin_name, agent_id, tier_settings
                    ):
                        if change.proposed:
                            result.allowed.append(change.proposed)
                        # Record as auto-approved
                        proposal = TierProposal(
                            proposal_id=f"prop-{agent_id}-{change.basin_name}-{utcnow_iso()}",
                            agent_id=agent_id,
                            basin_name=change.basin_name,
                            tier=change.tier,
                            proposal_type=ProposalType.CREATE,
                            status=ProposalStatus.AUTO_APPROVED,
                            rationale=change.detail or f"New basin '{change.basin_name}' auto-approved",
                            created_at=utcnow_iso(),
                            resolved_at=utcnow_iso(),
                            resolved_by="auto",
                            proposed_config=change.proposed,
                        )
                        result.proposals_created.append(proposal)
                    else:
                        # Not auto-approved — create a pending proposal for human review
                        proposal = TierProposal(
                            proposal_id=f"prop-{agent_id}-{change.basin_name}-{utcnow_iso()}",
                            agent_id=agent_id,
                            basin_name=change.basin_name,
                            tier=change.tier,
                            proposal_type=ProposalType.CREATE,
                            status=ProposalStatus.PENDING,
                            rationale=change.detail or f"New basin '{change.basin_name}' requires approval",
                            created_at=utcnow_iso(),
                            proposed_config=change.proposed,
                        )
                        result.proposals_created.append(proposal)
                        result.blocked.append(change)
                        result.warnings.append(
                            f"New basin '{change.basin_name}' requires approval"
                        )
                else:
                    # Tier 3 modify/prune — always allowed, but record it
                    if change.proposed:
                        result.allowed.append(change.proposed)
                    proposal = TierProposal(
                        proposal_id=f"prop-{agent_id}-{change.basin_name}-{utcnow_iso()}",
                        agent_id=agent_id,
                        basin_name=change.basin_name,
                        tier=change.tier,
                        proposal_type=ProposalType(
                            change.change_type
                        )
                        if change.change_type in ("modify", "create", "prune", "merge")
                        else ProposalType.MODIFY,
                        status=ProposalStatus.AUTO_APPROVED,
                        rationale=change.detail or f"Tier 3 modification of '{change.basin_name}' auto-approved",
                        created_at=utcnow_iso(),
                        resolved_at=utcnow_iso(),
                        resolved_by="auto",
                        proposed_config=change.proposed,
                    )
                    result.proposals_created.append(proposal)

        # Add unchanged basins
        changed_names = {c.basin_name for c in changes}
        for basin in current_basins:
            if basin.name not in changed_names:
                result.allowed.append(basin)

        return result

    async def process_tier_proposal(
        self,
        agent_id: str,
        proposal: TierProposal,
        tier_settings: TierSettings,
    ) -> ProposalDecision:
        """Process a tier modification proposal."""
        if proposal.tier == TierLevel.TIER_1:
            return ProposalDecision(
                approved=False, reason="Tier 1 invariants are immutable"
            )

        if proposal.tier == TierLevel.TIER_2:
            if not tier_settings.tier_2_auto_approve:
                return ProposalDecision(
                    approved=False, reason="Tier 2 auto-approve is disabled"
                )

            count = await self.memory.get_consecutive_proposal_count(
                agent_id, proposal.basin_name
            )
            count += 1  # Include current proposal
            proposal.consecutive_count = count

            if count >= tier_settings.tier_2_threshold:
                await self.memory.reset_proposal_counter(agent_id, proposal.basin_name)
                return ProposalDecision(
                    approved=True,
                    reason=f"Auto-approved: {count} consecutive proposals >= threshold {tier_settings.tier_2_threshold}",
                    auto=True,
                )
            else:
                await self.memory.increment_proposal_counter(
                    agent_id, proposal.basin_name
                )
                return ProposalDecision(
                    approved=False,
                    reason=f"Pending: {count}/{tier_settings.tier_2_threshold} consecutive proposals",
                )

        if proposal.tier == TierLevel.TIER_3:
            return ProposalDecision(
                approved=True, reason="Tier 3 has full autonomy", auto=True
            )

        return ProposalDecision(approved=False, reason="Unknown tier")

    async def approve_proposal(self, proposal_id: str) -> None:
        """Human-initiated approval — updates status and applies the change."""
        await self.memory.update_proposal_status(
            proposal_id, ProposalStatus.APPROVED, resolved_by="human"
        )

        # Apply the structural change to the agent's configuration
        proposal = await self.memory.get_tier_proposal(proposal_id)
        if proposal and proposal.proposed_config:
            await self.memory.apply_approved_proposal(proposal)
        else:
            logger.warning(
                "Proposal %s approved but no proposed_config stored — "
                "basin must be added manually",
                proposal_id,
            )

    async def reject_proposal(self, proposal_id: str, rationale: str) -> None:
        """Human-initiated rejection. Store rationale and reset counter."""
        await self.memory.reject_proposal_with_rationale(
            proposal_id, rationale, resolved_by="human"
        )

    async def modify_proposal(
        self,
        proposal_id: str,
        modifications: dict,
        rationale: str,
    ) -> None:
        """Approve a proposal with modifications and apply the change."""
        await self.memory.modify_and_apply_proposal(
            proposal_id, modifications, rationale, resolved_by="human"
        )

    def detect_basin_changes(
        self, proposed: list[BasinConfig], current: list[BasinConfig]
    ) -> list[BasinChange]:
        """Detect additions, removals, and modifications between basin lists."""
        current_map = {b.name: b for b in current}
        proposed_map = {b.name: b for b in proposed}
        changes = []

        # Check for additions
        for name, basin in proposed_map.items():
            if name not in current_map:
                changes.append(
                    BasinChange(
                        basin_name=name,
                        change_type="create",
                        tier=basin.tier,
                        proposed=basin,
                        detail=f"New basin '{name}' proposed (class: {basin.basin_class.value})",
                    )
                )

        # Check for removals
        for name, basin in current_map.items():
            if name not in proposed_map:
                changes.append(
                    BasinChange(
                        basin_name=name,
                        change_type="prune",
                        tier=basin.tier,
                        current=basin,
                        detail=f"Basin '{name}' removal proposed",
                    )
                )

        # Check for modifications
        for name in set(current_map) & set(proposed_map):
            curr = current_map[name]
            prop = proposed_map[name]
            # Check for significant changes (alpha changes are handled by handoff, not here)
            if (
                curr.basin_class != prop.basin_class
                or curr.tier != prop.tier
                or abs(curr.lambda_ - prop.lambda_) > 0.001
                or abs(curr.eta - prop.eta) > 0.001
            ):
                changes.append(
                    BasinChange(
                        basin_name=name,
                        change_type="modify",
                        tier=curr.tier,
                        current=curr,
                        proposed=prop,
                        detail=f"Basin '{name}' structural modification proposed",
                    )
                )

        return changes

    async def is_new_basin_allowed(
        self, basin_name: str, agent_id: str, tier_settings: TierSettings
    ) -> bool:
        """Check if a new basin can be auto-added based on emergence settings."""
        if not tier_settings.emergence_auto_approve:
            return False

        count = await self.memory.get_consecutive_proposal_count(agent_id, basin_name)
        return count >= tier_settings.emergence_threshold
