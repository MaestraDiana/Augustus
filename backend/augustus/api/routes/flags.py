"""Evaluator flag listing and review endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from augustus.api.dependencies import get_agent_registry, get_memory
from augustus.models.dataclasses import FlagRecord
from augustus.models.enums import FlagType
from augustus.services.agent_registry import AgentRegistry
from augustus.services.memory import MemoryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents/{agent_id}", tags=["flags"])


class ReviewFlagRequest(BaseModel):
    """Request body for reviewing a flag."""
    note: str = ""


def _flag_to_dict(f: FlagRecord) -> dict:
    """Serialize FlagRecord to JSON-friendly dict."""
    return {
        "flag_id": f.flag_id,
        "agent_id": f.agent_id,
        "session_id": f.session_id,
        "flag_type": f.flag_type.value if isinstance(f.flag_type, FlagType) else str(f.flag_type),
        "severity": f.severity,
        "detail": f.detail,
        "reviewed": f.reviewed,
        "review_note": f.review_note,
        "reviewed_at": f.reviewed_at or None,
        "reviewed_by": f.reviewed_by or None,
        "created_at": f.created_at,
    }


@router.get("/evaluator-flags")
async def list_flags(
    agent_id: str,
    flag_type: str | None = Query(None, description="Filter by flag type"),
    reviewed: bool | None = Query(None, description="Filter by review status"),
    limit: int = Query(50, ge=1, le=500),
    registry: AgentRegistry = Depends(get_agent_registry),
    memory: MemoryService = Depends(get_memory),
) -> list[dict]:
    """List evaluator flags for an agent."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    flags = await memory.get_evaluator_flags(
        agent_id, flag_type=flag_type, reviewed=reviewed, limit=limit
    )
    return [_flag_to_dict(f) for f in flags]


@router.post("/evaluator-flags/{flag_id}/review")
async def review_flag(
    agent_id: str,
    flag_id: str,
    body: ReviewFlagRequest | None = None,
    registry: AgentRegistry = Depends(get_agent_registry),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Mark an evaluator flag as reviewed."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    note = body.note if body else ""
    await memory.update_flag_review(flag_id, reviewed=True, note=note, reviewed_by="human")
    return {"flag_id": flag_id, "reviewed": True, "review_note": note}
