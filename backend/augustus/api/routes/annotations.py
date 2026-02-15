"""Annotation creation endpoints."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from augustus.api.dependencies import get_memory, require_agent
from augustus.models.dataclasses import AgentConfig, Annotation
from augustus.services.memory import MemoryService
from augustus.utils import utcnow_iso

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
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Add a human annotation for an agent (optionally linked to a session)."""
    annotation_id = f"ann-{uuid.uuid4().hex[:12]}"
    annotation = Annotation(
        annotation_id=annotation_id,
        agent_id=agent_id,
        session_id=body.session_id,
        content=body.content,
        tags=body.tags,
        created_at=utcnow_iso(),
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
