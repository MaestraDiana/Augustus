"""Tier proposal listing, approval, rejection, modification, and creation endpoints."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from augustus.api.dependencies import get_memory, get_tier_enforcer, require_agent
from augustus.models.dataclasses import AgentConfig
from augustus.models.enums import ProposalStatus, ProposalType
from augustus.services.memory import MemoryService
from augustus.services.tier_enforcer import TierEnforcer
from augustus.utils import utcnow_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents/{agent_id}", tags=["proposals"])


class RejectProposalRequest(BaseModel):
    """Request body for rejecting a proposal."""
    rationale: str = ""


class ModifyProposalRequest(BaseModel):
    """Request body for approving a proposal with modifications."""
    modifications: dict[str, Any]
    rationale: str


class CreateProposalRequest(BaseModel):
    """Request body for creating a new pending proposal."""
    basin_name: str
    action: str  # create, modify, prune, merge
    rationale: str
    suggested_params: dict[str, Any] | None = None


@router.get("/tier-proposals")
async def list_proposals(
    agent_id: str,
    status: str | None = Query(None, description="Filter by status: pending, approved, auto_approved, rejected, approved_with_modifications, expired"),
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> list[dict]:
    """List tier proposals for an agent."""
    proposals = await memory.get_tier_proposals(agent_id, status=status)
    return [p.to_dict() for p in proposals]


@router.post("/tier-proposals/{proposal_id}/approve")
async def approve_proposal(
    agent_id: str,
    proposal_id: str,
    agent: AgentConfig = Depends(require_agent),
    enforcer: TierEnforcer = Depends(get_tier_enforcer),
) -> dict:
    """Approve a pending tier proposal."""
    await enforcer.approve_proposal(proposal_id)
    return {"proposal_id": proposal_id, "status": "approved", "resolved_by": "human"}


@router.post("/tier-proposals/{proposal_id}/reject")
async def reject_proposal(
    agent_id: str,
    proposal_id: str,
    body: RejectProposalRequest | None = None,
    agent: AgentConfig = Depends(require_agent),
    enforcer: TierEnforcer = Depends(get_tier_enforcer),
) -> dict:
    """Reject a pending tier proposal."""
    rationale = body.rationale if body else ""
    await enforcer.reject_proposal(proposal_id, rationale)
    return {"proposal_id": proposal_id, "status": "rejected", "resolved_by": "human"}


@router.post("/tier-proposals/{proposal_id}/modify")
async def modify_proposal(
    agent_id: str,
    proposal_id: str,
    body: ModifyProposalRequest,
    agent: AgentConfig = Depends(require_agent),
    enforcer: TierEnforcer = Depends(get_tier_enforcer),
) -> dict:
    """Approve a proposal with modified parameters."""
    await enforcer.modify_proposal(proposal_id, body.modifications, body.rationale)
    return {
        "proposal_id": proposal_id,
        "status": "approved_with_modifications",
        "resolved_by": "human",
        "modifications": body.modifications,
    }


@router.post("/tier-proposals")
async def create_proposal(
    agent_id: str,
    body: CreateProposalRequest,
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Create a new pending tier proposal (brain-initiated).

    Use this to flag 'consider changing X' without immediately applying it.
    The proposal appears in get_pending_review_items for later review.
    """
    from augustus.models.dataclasses import BasinConfig, TierProposal
    from augustus.models.enums import BasinClass, TierLevel

    try:
        proposal_type = ProposalType(body.action)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action '{body.action}'. Must be one of: create, modify, prune, merge",
        )

    # Determine tier from existing basin or default to T3
    current_basins = await memory.get_current_basins(agent_id)
    existing = next((b for b in current_basins if b.name == body.basin_name), None)
    tier = existing.tier if existing else TierLevel.TIER_3

    # Build proposed_config from suggested_params
    proposed_config: BasinConfig | None = None
    if body.suggested_params:
        try:
            bc_str = body.suggested_params.get("basin_class")
            basin_class = BasinClass(bc_str) if bc_str else (
                existing.basin_class if existing else BasinClass.PERIPHERAL
            )
            alpha = body.suggested_params.get("alpha",
                existing.alpha if existing else 0.3
            )
            lambda_ = body.suggested_params.get("lambda_decay",
                existing.lambda_ if existing else 0.95
            )
            eta = body.suggested_params.get("eta",
                existing.eta if existing else 0.1
            )
            tier_val = body.suggested_params.get("tier")
            if tier_val is not None:
                tier = TierLevel(int(tier_val))

            proposed_config = BasinConfig(
                name=body.basin_name,
                basin_class=basin_class,
                alpha=max(0.05, min(1.0, float(alpha))),
                lambda_=float(lambda_),
                eta=float(eta),
                tier=tier,
            )
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid suggested_params: {e}")
    elif existing:
        proposed_config = existing

    proposal_id = f"prop-brain-{agent_id}-{body.basin_name}-{utcnow_iso()}"
    proposal = TierProposal(
        proposal_id=proposal_id,
        agent_id=agent_id,
        basin_name=body.basin_name,
        tier=tier,
        proposal_type=proposal_type,
        status=ProposalStatus.PENDING,
        rationale=body.rationale,
        created_at=utcnow_iso(),
        proposed_config=proposed_config,
    )
    await memory.store_tier_proposal(proposal)

    return {
        "proposal_id": proposal_id,
        "basin_name": body.basin_name,
        "action": body.action,
        "status": "pending",
        "rationale": body.rationale,
    }
