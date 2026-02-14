"""Annotation creation endpoints."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from augustus.api.dependencies import get_agent_registry, get_memory
from augustus.models.dataclasses import Annotation
from augustus.services.agent_registry import AgentRegistry
from augustus.services.memory import MemoryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents/{agent_id}", tags=["annotations"])


class CreateAnnotationRequest(BaseModel):
    """Request body for creating an annotation."""
    content: str
    session_id: str | None = None
    tags: list[str] = []


@router.post("/annotations", status_code=201)
async def create_annotation(
    agent_id: str,
    body: CreateAnnotationRequest,
    registry: AgentRegistry = Depends(get_agent_registry),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Add a human annotation for an agent (optionally linked to a session)."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    annotation_id = f"ann-{uuid.uuid4().hex[:12]}"
    annotation = Annotation(
        annotation_id=annotation_id,
        agent_id=agent_id,
        session_id=body.session_id,
        content=body.content,
        tags=body.tags,
        created_at=datetime.utcnow().isoformat(),
    )

    await memory.store_annotation(annotation)

    return {
        "annotation_id": annotation_id,
        "agent_id": agent_id,
        "session_id": body.session_id,
        "content": body.content,
        "tags": body.tags,
        "created_at": annotation.created_at,
    }
