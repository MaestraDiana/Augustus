"""Usage tracking endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from augustus.api.dependencies import get_memory
from augustus.services.memory import MemoryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("")
async def get_usage_summary(
    period: str = Query("day", description="Period: day, week, month, all"),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Get aggregated usage summary for a time period."""
    if period not in ("day", "week", "month", "all"):
        period = "day"

    summary = await memory.get_usage_summary(period=period)

    # Also get per-agent breakdown
    by_agent = await memory.get_usage_by_agent()

    return {
        **summary,
        "by_agent": by_agent,
    }


@router.get("/daily")
async def get_usage_daily(
    days: int = Query(30, ge=1, le=365),
    memory: MemoryService = Depends(get_memory),
) -> list[dict]:
    """Get daily usage breakdown for the last N days."""
    return await memory.get_usage_daily(days=days)
