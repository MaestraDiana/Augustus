"""Tier proposal listing, approval, and rejection endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from augustus.api.dependencies import get_memory, get_tier_enforcer, require_agent
from augustus.models.dataclasses import AgentConfig
from augustus.services.memory import MemoryService
from augustus.services.tier_enforcer import TierEnforcer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents/{agent_id}", tags=["proposals"])


class RejectProposalRequest(BaseModel):
    """Request body for rejecting a proposal."""
    rationale: str = ""


@router.get("/tier-proposals")
async def list_proposals(
    agent_id: str,
    status: str | None = Query(None, description="Filter by status: pending, approved, auto_approved, rejected, expired"),
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
