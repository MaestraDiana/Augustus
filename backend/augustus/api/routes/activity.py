"""Activity feed and system alerts endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from augustus.api.dependencies import get_memory
from augustus.models.dataclasses import ActivityEvent
from augustus.services.memory import MemoryService
from augustus.utils import utcnow_iso

logger = logging.getLogger(__name__)
router = APIRouter(tags=["activity"])


def _event_to_dict(e: ActivityEvent) -> dict:
    """Serialize ActivityEvent to JSON-friendly dict."""
    return {
        "event_id": e.event_id,
        "event_type": e.event_type,
        "agent_id": e.agent_id,
        "session_id": e.session_id,
        "content": e.detail,
        "timestamp": e.timestamp,
    }


@router.get("/api/activity-feed")
async def get_activity_feed(
    limit: int = Query(20, ge=1, le=100),
    memory: MemoryService = Depends(get_memory),
) -> list[dict]:
    """Get the most recent activity events."""
    events = await memory.get_activity_feed(limit=limit)
    return [_event_to_dict(e) for e in events]


@router.get("/api/system-alerts")
async def get_system_alerts(
    memory: MemoryService = Depends(get_memory),
) -> list[dict]:
    """Get active system alerts (pending proposals, unreviewed flags, budget warnings, etc.)."""
    raw_alerts = await memory.get_system_alerts()

    severity_map = {"warning": "warn", "error": "error", "info": "info"}
    result = []
    for i, alert in enumerate(raw_alerts):
        result.append({
            "alert_id": str(i + 1),
            "alert_type": severity_map.get(alert.get("severity", "info"), "info"),
            "title": alert.get("message", ""),
            "detail": alert.get("detail", ""),
            "link_type": alert.get("type", ""),
            "agent_id": alert.get("agent_id", ""),
            "timestamp": utcnow_iso(),
            "dismissed": False,
        })
    return result
