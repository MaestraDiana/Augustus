"""Orchestrator status and control endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from augustus.api.dependencies import get_container
from augustus.models.enums import OrchestratorStatus
from augustus.utils import enum_val

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


def _get_orchestrator_status() -> dict:
    """Read orchestrator status from the container."""
    container = get_container()
    orch = container.orchestrator

    if orch is None:
        return {
            "status": OrchestratorStatus.PAUSED.value,
            "message": "Orchestrator not initialized",
            "active_sessions": 0,
            "queued_agents": 0,
        }

    # The orchestrator object, if present, should expose status attributes.
    # Gracefully handle missing attributes for forward compatibility.
    status = getattr(orch, "status", OrchestratorStatus.PAUSED)
    status_val = enum_val(status)
    active_sessions = getattr(orch, "active_session_count", 0)
    queued = getattr(orch, "queued_agent_count", 0)
    error = getattr(orch, "last_error", None)

    result: dict = {
        "status": status_val,
        "active_sessions": active_sessions,
        "queued_agents": queued,
    }
    if error:
        result["last_error"] = str(error)
    return result


@router.get("/status")
async def get_status() -> dict:
    """Get orchestrator operational status."""
    return _get_orchestrator_status()


@router.post("/pause")
async def pause_orchestrator() -> dict:
    """Pause the orchestrator (stops scheduling new sessions)."""
    container = get_container()
    orch = container.orchestrator

    if orch is None:
        return {
            "status": OrchestratorStatus.PAUSED.value,
            "message": "Orchestrator not initialized",
        }

    await orch.pause()
    return _get_orchestrator_status()


@router.post("/resume")
async def resume_orchestrator() -> dict:
    """Resume the orchestrator."""
    container = get_container()
    orch = container.orchestrator

    if orch is None:
        return {
            "status": OrchestratorStatus.PAUSED.value,
            "message": "Orchestrator not initialized",
        }

    # If the orchestrator loop has exited (e.g. due to error), restart it
    if not orch._running:
        import asyncio
        orch_task = asyncio.create_task(orch.start())
        logger.info("Orchestrator loop restarted via resume")
    else:
        await orch.resume()

    return _get_orchestrator_status()
