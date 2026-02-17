"""Evaluator flag listing, review, and resolution endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from augustus.api.dependencies import get_memory, require_agent
from augustus.models.dataclasses import AgentConfig
from augustus.services.memory import MemoryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents/{agent_id}", tags=["flags"])


class ReviewFlagRequest(BaseModel):
    """Request body for reviewing a flag."""
    note: str = ""


class ResolveFlagRequest(BaseModel):
    """Request body for resolving a flag."""
    resolution: str  # acknowledged, addressed, dismissed
    notes: str = ""


@router.get("/evaluator-flags")
async def list_flags(
    agent_id: str,
    flag_type: str | None = Query(None, description="Filter by flag type"),
    reviewed: bool | None = Query(None, description="Filter by review status"),
    limit: int = Query(50, ge=1, le=500),
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> list[dict]:
    """List evaluator flags for an agent."""
    flags = await memory.get_evaluator_flags(
        agent_id, flag_type=flag_type, reviewed=reviewed, limit=limit
    )
    return [f.to_dict() for f in flags]


@router.post("/evaluator-flags/{flag_id}/review")
async def review_flag(
    agent_id: str,
    flag_id: str,
    body: ReviewFlagRequest | None = None,
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Mark an evaluator flag as reviewed."""
    note = body.note if body else ""
    await memory.update_flag_review(flag_id, reviewed=True, note=note, reviewed_by="human")
    await memory.emit_event("flag_resolved", agent_id, {"flag_id": flag_id, "action": "reviewed"})
    return {"flag_id": flag_id, "reviewed": True, "review_note": note}


@router.post("/evaluator-flags/{flag_id}/resolve")
async def resolve_flag(
    agent_id: str,
    flag_id: str,
    body: ResolveFlagRequest,
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Resolve a flag with resolution type and notes."""
    await memory.resolve_flag(flag_id, body.resolution, body.notes, resolved_by="human")
    await memory.emit_event("flag_resolved", agent_id, {"flag_id": flag_id, "resolution": body.resolution})
    return {
        "flag_id": flag_id,
        "resolution": body.resolution,
        "resolved": True,
    }
