"""Tier proposal listing, approval, and rejection endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from augustus.api.dependencies import get_agent_registry, get_memory, get_tier_enforcer
from augustus.models.dataclasses import TierProposal
from augustus.models.enums import ProposalStatus, ProposalType, TierLevel
from augustus.services.agent_registry import AgentRegistry
from augustus.services.memory import MemoryService
from augustus.services.tier_enforcer import TierEnforcer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents/{agent_id}", tags=["proposals"])


class RejectProposalRequest(BaseModel):
    """Request body for rejecting a proposal."""
    rationale: str = ""


def _proposal_to_dict(p: TierProposal) -> dict:
    """Serialize TierProposal to JSON-friendly dict."""
    return {
        "proposal_id": p.proposal_id,
        "agent_id": p.agent_id,
        "basin_name": p.basin_name,
        "tier": p.tier.value if isinstance(p.tier, TierLevel) else int(p.tier),
        "proposal_type": p.proposal_type.value if isinstance(p.proposal_type, ProposalType) else str(p.proposal_type),
        "status": p.status.value if isinstance(p.status, ProposalStatus) else str(p.status),
        "rationale": p.rationale,
        "session_id": p.session_id,
        "consecutive_count": p.consecutive_count,
        "created_at": p.created_at,
        "resolved_at": p.resolved_at,
        "resolved_by": p.resolved_by,
    }


@router.get("/tier-proposals")
async def list_proposals(
    agent_id: str,
    status: str | None = Query(None, description="Filter by status: pending, approved, auto_approved, rejected, expired"),
    registry: AgentRegistry = Depends(get_agent_registry),
    memory: MemoryService = Depends(get_memory),
) -> list[dict]:
    """List tier proposals for an agent."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    proposals = await memory.get_tier_proposals(agent_id, status=status)
    return [_proposal_to_dict(p) for p in proposals]


@router.post("/tier-proposals/{proposal_id}/approve")
async def approve_proposal(
    agent_id: str,
    proposal_id: str,
    registry: AgentRegistry = Depends(get_agent_registry),
    enforcer: TierEnforcer = Depends(get_tier_enforcer),
) -> dict:
    """Approve a pending tier proposal."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    await enforcer.approve_proposal(proposal_id)
    return {"proposal_id": proposal_id, "status": "approved", "resolved_by": "human"}


@router.post("/tier-proposals/{proposal_id}/reject")
async def reject_proposal(
    agent_id: str,
    proposal_id: str,
    body: RejectProposalRequest | None = None,
    registry: AgentRegistry = Depends(get_agent_registry),
    enforcer: TierEnforcer = Depends(get_tier_enforcer),
) -> dict:
    """Reject a pending tier proposal."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    rationale = body.rationale if body else ""
    await enforcer.reject_proposal(proposal_id, rationale)
    return {"proposal_id": proposal_id, "status": "rejected", "resolved_by": "human"}
