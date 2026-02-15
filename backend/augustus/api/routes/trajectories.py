"""Basin trajectory and co-activation endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from augustus.api.dependencies import get_memory, require_agent
from augustus.models.dataclasses import AgentConfig
from augustus.models.enums import CoActivationCharacter
from augustus.services.memory import MemoryService
from augustus.utils import enum_val

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents/{agent_id}", tags=["trajectories"])


@router.get("/trajectories")
async def get_trajectories(
    agent_id: str,
    n_sessions: int = Query(20, ge=1, le=200),
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Get basin alpha trajectories for an agent."""
    trajectories = await memory.get_all_trajectories(agent_id, n_sessions=n_sessions)

    # Get current basins for metadata
    current_basins = await memory.get_current_basins(agent_id)
    basin_meta = {}
    for b in current_basins:
        d = b.to_dict()
        d["current_alpha"] = d.pop("alpha")
        d.pop("name", None)
        basin_meta[b.name] = d

    result = {}
    for basin_name, snapshots in trajectories.items():
        result[basin_name] = {
            "metadata": basin_meta.get(basin_name, {}),
            "points": [
                s.to_dict() | {"session_id": s.session_id}
                for s in snapshots
            ],
        }

    return {
        "agent_id": agent_id,
        "n_sessions": n_sessions,
        "trajectories": result,
    }


@router.get("/co-activation")
async def get_co_activation(
    agent_id: str,
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Get co-activation matrix for an agent."""
    entries = await memory.get_co_activation(agent_id)

    # Build nodes (unique basin names) and edges (co-activation pairs)
    nodes: set[str] = set()
    edges = []
    for entry in entries:
        basin_a, basin_b = entry.pair
        nodes.add(basin_a)
        nodes.add(basin_b)
        character_val = (
            enum_val(entry.character)
            if entry.character
            else "uncharacterized"
        )
        edges.append({
            "source": basin_a,
            "target": basin_b,
            "count": entry.count,
            "character": character_val,
        })

    return {
        "agent_id": agent_id,
        "nodes": sorted(nodes),
        "edges": edges,
    }
