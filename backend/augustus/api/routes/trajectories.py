"""Basin trajectory and co-activation endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from augustus.api.dependencies import get_agent_registry, get_memory
from augustus.models.enums import BasinClass, CoActivationCharacter, TierLevel
from augustus.services.agent_registry import AgentRegistry
from augustus.services.memory import MemoryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents/{agent_id}", tags=["trajectories"])


@router.get("/trajectories")
async def get_trajectories(
    agent_id: str,
    n_sessions: int = Query(20, ge=1, le=200),
    registry: AgentRegistry = Depends(get_agent_registry),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Get basin alpha trajectories for an agent."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    trajectories = await memory.get_all_trajectories(agent_id, n_sessions=n_sessions)

    # Get current basins for metadata
    current_basins = await memory.get_current_basins(agent_id)
    basin_meta = {}
    for b in current_basins:
        basin_meta[b.name] = {
            "basin_class": b.basin_class.value if isinstance(b.basin_class, BasinClass) else str(b.basin_class),
            "tier": b.tier.value if isinstance(b.tier, TierLevel) else int(b.tier),
            "current_alpha": b.alpha,
            "lambda": b.lambda_,
            "eta": b.eta,
        }

    result = {}
    for basin_name, snapshots in trajectories.items():
        result[basin_name] = {
            "metadata": basin_meta.get(basin_name, {}),
            "points": [
                {
                    "session_id": s.session_id,
                    "alpha_start": s.alpha_start,
                    "alpha_end": s.alpha_end,
                    "delta": s.delta,
                    "relevance_score": s.relevance_score,
                }
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
    registry: AgentRegistry = Depends(get_agent_registry),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Get co-activation matrix for an agent."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    entries = await memory.get_co_activation(agent_id)

    # Build nodes (unique basin names) and edges (co-activation pairs)
    nodes: set[str] = set()
    edges = []
    for entry in entries:
        basin_a, basin_b = entry.pair
        nodes.add(basin_a)
        nodes.add(basin_b)
        character_val = (
            entry.character.value
            if isinstance(entry.character, CoActivationCharacter)
            else str(entry.character) if entry.character else "uncharacterized"
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
