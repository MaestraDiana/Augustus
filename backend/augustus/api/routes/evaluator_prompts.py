"""Evaluator prompt version management endpoints."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from augustus.api.dependencies import get_memory
from augustus.models.dataclasses import EvaluatorPrompt
from augustus.services.memory import MemoryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/evaluator-prompts", tags=["evaluator-prompts"])


# ── Pydantic models ───────────────────────────────────────────────────


class CreatePromptRequest(BaseModel):
    """Request body for creating a new evaluator prompt version."""
    prompt_text: str
    change_rationale: str = ""
    set_active: bool = False


# ── Helpers ────────────────────────────────────────────────────────────


def _prompt_to_dict(p: EvaluatorPrompt) -> dict:
    """Serialize EvaluatorPrompt to JSON-friendly dict."""
    return {
        "version_id": p.version_id,
        "prompt_text": p.prompt_text,
        "change_rationale": p.change_rationale,
        "created_at": p.created_at,
        "is_active": p.is_active,
    }


# ── Endpoints ──────────────────────────────────────────────────────────


@router.get("")
async def list_evaluator_prompts(
    memory: MemoryService = Depends(get_memory),
) -> list[dict]:
    """List all evaluator prompt versions."""
    prompts = await memory.list_evaluator_prompts()
    return [_prompt_to_dict(p) for p in prompts]


@router.post("", status_code=201)
async def create_evaluator_prompt(
    body: CreatePromptRequest,
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Create a new evaluator prompt version."""
    version_id = f"v-{uuid.uuid4().hex[:8]}"
    prompt = EvaluatorPrompt(
        version_id=version_id,
        prompt_text=body.prompt_text,
        change_rationale=body.change_rationale,
        created_at=datetime.utcnow().isoformat(),
        is_active=False,
    )

    await memory.store_evaluator_prompt(prompt)

    if body.set_active:
        await memory.set_active_evaluator_prompt(version_id)
        prompt.is_active = True

    return _prompt_to_dict(prompt)


@router.put("/{version_id}/activate")
async def activate_evaluator_prompt(
    version_id: str,
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Set a specific evaluator prompt version as active."""
    existing = await memory.get_evaluator_prompt(version_id)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Evaluator prompt version '{version_id}' not found",
        )

    await memory.set_active_evaluator_prompt(version_id)
    return {"version_id": version_id, "is_active": True}
