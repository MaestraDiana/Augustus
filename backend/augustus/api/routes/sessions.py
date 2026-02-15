"""Session listing and detail endpoints."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from augustus.api.dependencies import get_agent_registry, get_memory, require_agent
from augustus.models.dataclasses import AgentConfig, SessionRecord
from augustus.services.agent_registry import AgentRegistry
from augustus.services.memory import MemoryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents/{agent_id}", tags=["sessions"])


@router.get("/sessions")
async def list_sessions(
    agent_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """List sessions for an agent with pagination."""
    sessions = await memory.list_sessions(agent_id, limit=limit, offset=offset)
    total = await memory.count_sessions(agent_id)

    return {
        "sessions": [s.to_dict() for s in sessions],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/sessions/{session_id}")
async def get_session_detail(
    agent_id: str,
    session_id: str,
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Get full session detail including transcript and close report."""
    session = await memory.get_session(agent_id, session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found for agent '{agent_id}'",
        )

    # Load basin snapshots for this session (not populated by get_session)
    session.basin_snapshots = await memory.get_session_basin_snapshots(
        agent_id, session_id
    )

    result = session.to_dict(include_transcript=True)

    # Attach evaluator output if available
    eval_output = await memory.get_evaluator_output(session_id)
    if eval_output:
        result["evaluator_output"] = {
            "basin_relevance": eval_output.basin_relevance,
            "basin_rationale": eval_output.basin_rationale,
            "co_activation_characters": eval_output.co_activation_characters,
            "constraint_erosion_flag": eval_output.constraint_erosion_flag,
            "constraint_erosion_detail": eval_output.constraint_erosion_detail,
            "assessment_divergence_flag": eval_output.assessment_divergence_flag,
            "assessment_divergence_detail": eval_output.assessment_divergence_detail,
            "emergent_observations": eval_output.emergent_observations,
            "evaluator_prompt_version": eval_output.evaluator_prompt_version,
        }
    else:
        result["evaluator_output"] = None

    # Attach annotations for this session
    annotations = await memory.get_annotations(agent_id, session_id=session_id)
    result["annotations"] = [
        {
            "annotation_id": a.annotation_id,
            "content": a.content,
            "tags": a.tags,
            "created_at": a.created_at,
        }
        for a in annotations
    ]

    return result


@router.get("/sessions/{session_id}/yaml-diff")
async def get_session_yaml_diff(
    agent_id: str,
    session_id: str,
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Get YAML for this session and the previous session for diffing."""
    session = await memory.get_session(agent_id, session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found for agent '{agent_id}'",
        )

    previous = await memory.get_previous_session(agent_id, session_id)

    return {
        "session_id": session_id,
        "yaml_raw": session.yaml_raw or "",
        "previous_session_id": previous.session_id if previous else None,
        "previous_yaml_raw": previous.yaml_raw if previous else "",
        "is_first_session": previous is None,
    }
