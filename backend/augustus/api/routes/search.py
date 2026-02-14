"""Semantic search endpoints (agent-scoped and global)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from augustus.api.dependencies import get_agent_registry, get_memory
from augustus.models.dataclasses import SearchResult
from augustus.services.agent_registry import AgentRegistry
from augustus.services.memory import MemoryService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["search"])


def _result_to_dict(r: SearchResult) -> dict:
    """Serialize SearchResult to JSON-friendly dict."""
    return {
        "content_type": r.content_type,
        "agent_id": r.agent_id,
        "session_id": r.session_id,
        "snippet": r.snippet,
        "relevance_score": r.relevance_score,
        "timestamp": r.timestamp,
    }


@router.get("/api/agents/{agent_id}/search")
async def search_agent(
    agent_id: str,
    q: str = Query(..., min_length=1, description="Search query"),
    n_results: int = Query(10, ge=1, le=50),
    registry: AgentRegistry = Depends(get_agent_registry),
    memory: MemoryService = Depends(get_memory),
) -> list[dict]:
    """Semantic search scoped to a single agent."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    results = await memory.search_sessions(agent_id, q, n_results=n_results)
    return [_result_to_dict(r) for r in results]


@router.get("/api/search")
async def search_global(
    q: str = Query(..., min_length=1, description="Search query"),
    n_results: int = Query(10, ge=1, le=50),
    memory: MemoryService = Depends(get_memory),
) -> list[dict]:
    """Global semantic search across all agents."""
    results = await memory.search_all_agents(q, n_results=n_results)
    return [_result_to_dict(r) for r in results]
