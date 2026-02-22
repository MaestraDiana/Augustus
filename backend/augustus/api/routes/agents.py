"""Agent CRUD, lifecycle, and overview endpoints."""
from __future__ import annotations

import logging
import re
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from augustus.api.dependencies import get_agent_registry, get_container, get_memory, require_agent
from augustus.exceptions import AgentNotFoundError
from augustus.models.dataclasses import AgentConfig, BasinConfig, TierSettings
from augustus.models.enums import AgentStatus, BasinClass, TierLevel
from augustus.services.agent_registry import AgentRegistry
from augustus.services.memory import MemoryService
from augustus.services.schema_parser import parse_yaml_lenient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents", tags=["agents"])


def _parse_structural_section(raw: str) -> dict:
    """Parse a structural-section string (session_protocol / relational_grounding).

    Returns a dict.  Accepts valid YAML dicts, plain text (wrapped as
    ``{"content": text}``), or empty strings (returns ``{}``).
    """
    if not raw or not raw.strip():
        return {}
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError:
        # Not valid YAML — treat as freeform text
        return {"content": raw}
    if isinstance(parsed, dict):
        return parsed
    # Valid YAML but not a dict (e.g. a plain string or list) — wrap it
    return {"content": raw}


# ── Pydantic request/response models ──────────────────────────────────


class BasinConfigIn(BaseModel):
    """Basin configuration input."""
    name: str
    basin_class: str = "peripheral"
    alpha: float = 0.5
    lambda_: float = Field(0.95, alias="lambda")
    eta: float = 0.1
    tier: int = 3

    class Config:
        populate_by_name = True


class TierSettingsIn(BaseModel):
    """Tier settings input."""
    tier_2_auto_approve: bool = True
    tier_2_threshold: int = 5
    emergence_auto_approve: bool = True
    emergence_threshold: int = 3


class CreateAgentRequest(BaseModel):
    """Request body for creating an agent."""
    agent_id: str
    description: str = ""
    model_override: str | None = None
    temperature_override: float | None = None
    max_tokens_override: int | None = None
    max_turns: int = 8
    session_interval: int = 300
    identity_core: str = ""
    session_task: str = ""
    close_protocol: str = ""
    capabilities: dict = {}
    basins: list[BasinConfigIn] = []
    tier_settings: TierSettingsIn | None = None
    session_protocol: str = ""
    relational_grounding: str = ""


class UpdateAgentRequest(BaseModel):
    """Request body for updating an agent."""
    description: str | None = None
    model_override: str | None = None
    temperature_override: float | None = None
    max_tokens_override: int | None = None
    max_turns: int | None = None
    session_interval: int | None = None
    identity_core: str | None = None
    session_task: str | None = None
    close_protocol: str | None = None
    capabilities: dict | None = None
    basins: list[BasinConfigIn] | None = None
    tier_settings: TierSettingsIn | None = None
    session_protocol: str | None = None
    relational_grounding: str | None = None


class CloneAgentRequest(BaseModel):
    """Request body for cloning an agent."""
    new_agent_id: str


class ParseYamlRequest(BaseModel):
    """Request body for parsing a bootstrap YAML for import."""
    yaml_text: str


# ── Helpers ────────────────────────────────────────────────────────────


_AGENT_ID_RE = re.compile(r"^[a-z0-9_-]{1,64}$")


def _validate_agent_id(agent_id: str) -> None:
    """Raise HTTPException 422 if agent_id is not safe for use as a path component and DB key."""
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(
            status_code=422,
            detail=(
                "agent_id must be 1–64 characters and contain only lowercase letters, "
                "digits, hyphens, and underscores."
            ),
        )


def _basin_in_to_config(b: BasinConfigIn) -> BasinConfig:
    """Convert Pydantic basin input to dataclass."""
    try:
        basin_class = BasinClass(b.basin_class)
    except ValueError:
        basin_class = BasinClass.PERIPHERAL
    try:
        tier = TierLevel(b.tier)
    except (ValueError, TypeError):
        tier = TierLevel.TIER_3
    return BasinConfig(
        name=b.name,
        basin_class=basin_class,
        alpha=b.alpha,
        lambda_=b.lambda_,
        eta=b.eta,
        tier=tier,
    )


def _agent_to_dict(agent: AgentConfig) -> dict[str, Any]:
    """Serialize AgentConfig to JSON-friendly dict. Delegates to AgentConfig.to_dict()."""
    return agent.to_dict()


# ── Endpoints ──────────────────────────────────────────────────────────


@router.post("/parse-yaml")
async def parse_yaml_for_import(body: ParseYamlRequest) -> dict:
    """Parse a bootstrap YAML file for agent form population.

    Lenient parsing — does not require agent_id or session_id.
    Returns extracted fields with warnings for any issues.
    """
    return parse_yaml_lenient(body.yaml_text)


def _get_queue_status(agent_id: str) -> dict:
    """Get queue status for an agent from the orchestrator."""
    container = get_container()
    orch = container.orchestrator
    if orch and hasattr(orch, "get_agent_queue_status"):
        return orch.get_agent_queue_status(agent_id)
    return {"pending_count": 0, "has_active": False, "is_running": False, "queue_status": "idle"}


@router.get("")
async def list_agents(
    registry: AgentRegistry = Depends(get_agent_registry),
    memory: MemoryService = Depends(get_memory),
) -> list[dict]:
    """List all agents with session counts and queue status."""
    agents = await registry.list_agents()
    result = []
    for a in agents:
        d = _agent_to_dict(a)
        d["session_count"] = await memory.count_sessions(a.agent_id)
        d["queue_status"] = _get_queue_status(a.agent_id)
        result.append(d)
    return result


@router.post("", status_code=201)
async def create_agent(
    body: CreateAgentRequest,
    registry: AgentRegistry = Depends(get_agent_registry),
) -> dict:
    """Create a new agent."""
    _validate_agent_id(body.agent_id)
    try:
        # Check if agent already exists
        existing = await registry.get_agent(body.agent_id)
        if existing:
            raise HTTPException(status_code=409, detail=f"Agent '{body.agent_id}' already exists")

        basins = [_basin_in_to_config(b) for b in body.basins]
        tier_settings = None
        if body.tier_settings:
            tier_settings = TierSettings(
                tier_2_auto_approve=body.tier_settings.tier_2_auto_approve,
                tier_2_threshold=body.tier_settings.tier_2_threshold,
                emergence_auto_approve=body.tier_settings.emergence_auto_approve,
                emergence_threshold=body.tier_settings.emergence_threshold,
            )

        # Parse structural sections from YAML strings back to dicts.
        # If the string is valid YAML that produces a dict, use it directly.
        # If it's plain text or non-dict YAML, wrap it so the data isn't lost.
        session_protocol = _parse_structural_section(body.session_protocol)
        relational_grounding = _parse_structural_section(body.relational_grounding)

        config = AgentConfig(
            agent_id=body.agent_id,
            description=body.description,
            model_override=body.model_override,
            temperature_override=body.temperature_override,
            max_tokens_override=body.max_tokens_override,
            max_turns=body.max_turns,
            session_interval=body.session_interval,
            identity_core=body.identity_core,
            session_task=body.session_task,
            close_protocol=body.close_protocol,
            capabilities=body.capabilities,
            basins=basins,
            tier_settings=tier_settings,
            session_protocol=session_protocol,
            relational_grounding=relational_grounding,
        )

        await registry.create_agent(config)
        created = await registry.get_agent(body.agent_id)
        return _agent_to_dict(created) if created else {"agent_id": body.agent_id, "status": "created"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to create agent '%s'", body.agent_id)
        raise HTTPException(status_code=500, detail=f"Failed to create agent: {exc}") from exc


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Get agent detail."""
    d = agent.to_dict()
    d["session_count"] = await memory.count_sessions(agent_id)
    d["queue_status"] = _get_queue_status(agent_id)
    return d


@router.put("/{agent_id}")
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    agent: AgentConfig = Depends(require_agent),
    registry: AgentRegistry = Depends(get_agent_registry),
) -> dict:
    """Update agent configuration."""
    updates: dict[str, Any] = {}
    if body.description is not None:
        updates["description"] = body.description
    if body.model_override is not None:
        updates["model_override"] = body.model_override
    if body.temperature_override is not None:
        updates["temperature_override"] = body.temperature_override
    if body.max_tokens_override is not None:
        updates["max_tokens_override"] = body.max_tokens_override
    if body.max_turns is not None:
        updates["max_turns"] = body.max_turns
    if body.session_interval is not None:
        updates["session_interval"] = body.session_interval
    if body.identity_core is not None:
        updates["identity_core"] = body.identity_core
    if body.session_task is not None:
        updates["session_task"] = body.session_task
    if body.close_protocol is not None:
        updates["close_protocol"] = body.close_protocol
    if body.capabilities is not None:
        updates["capabilities"] = body.capabilities
    if body.basins is not None:
        updates["basins"] = [
            {
                "name": b.name,
                "basin_class": b.basin_class,
                "alpha": b.alpha,
                "lambda_": b.lambda_,
                "eta": b.eta,
                "tier": b.tier,
            }
            for b in body.basins
        ]
    if body.tier_settings is not None:
        updates["tier_settings"] = {
            "tier_2_auto_approve": body.tier_settings.tier_2_auto_approve,
            "tier_2_threshold": body.tier_settings.tier_2_threshold,
            "emergence_auto_approve": body.tier_settings.emergence_auto_approve,
            "emergence_threshold": body.tier_settings.emergence_threshold,
        }
    if body.session_protocol is not None:
        updates["session_protocol"] = _parse_structural_section(body.session_protocol)
    if body.relational_grounding is not None:
        updates["relational_grounding"] = _parse_structural_section(body.relational_grounding)

    try:
        await registry.update_agent(agent_id, updates)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # If any YAML-affecting field changed, regenerate the pending instruction file.
    # Description and tier_settings are metadata-only — no YAML rebuild needed.
    yaml_fields = {
        "identity_core", "session_task", "close_protocol",
        "session_protocol", "relational_grounding",
        "basins", "capabilities", "max_turns",
        "model_override", "temperature_override", "max_tokens_override",
    }
    changed_yaml_fields = yaml_fields & updates.keys()
    if changed_yaml_fields:
        try:
            await registry.regenerate_pending_yaml(agent_id, changed_fields=changed_yaml_fields)
        except Exception as e:
            logger.warning(f"YAML regeneration failed for '{agent_id}': {e}")

    updated = await registry.get_agent(agent_id)
    return _agent_to_dict(updated) if updated else {"agent_id": agent_id}


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: str,
    hard: bool = Query(False, description="Hard delete removes all data"),
    registry: AgentRegistry = Depends(get_agent_registry),
) -> None:
    """Delete an agent (soft by default)."""
    try:
        await registry.delete_agent(agent_id, hard_delete=hard)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")


@router.post("/{agent_id}/pause")
async def pause_agent(
    agent_id: str,
    agent: AgentConfig = Depends(require_agent),
    registry: AgentRegistry = Depends(get_agent_registry),
) -> dict:
    """Pause an agent."""
    await registry.pause_agent(agent_id)
    return {"agent_id": agent_id, "status": "paused"}


@router.post("/{agent_id}/resume")
async def resume_agent(
    agent_id: str,
    agent: AgentConfig = Depends(require_agent),
    registry: AgentRegistry = Depends(get_agent_registry),
) -> dict:
    """Resume a paused agent."""
    await registry.resume_agent(agent_id)
    return {"agent_id": agent_id, "status": "active"}


@router.post("/{agent_id}/clone", status_code=201)
async def clone_agent(
    agent_id: str,
    body: CloneAgentRequest,
    registry: AgentRegistry = Depends(get_agent_registry),
) -> dict:
    """Clone an agent to a new ID."""
    _validate_agent_id(body.new_agent_id)
    # Check target doesn't exist
    existing = await registry.get_agent(body.new_agent_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Target agent '{body.new_agent_id}' already exists",
        )
    try:
        await registry.clone_agent(agent_id, body.new_agent_id)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Source agent '{agent_id}' not found")

    cloned = await registry.get_agent(body.new_agent_id)
    return _agent_to_dict(cloned) if cloned else {"agent_id": body.new_agent_id, "status": "created"}


@router.get("/{agent_id}/export")
async def export_agent(
    agent_id: str,
    registry: AgentRegistry = Depends(get_agent_registry),
) -> FileResponse:
    """Export agent data as a downloadable ZIP archive."""
    try:
        zip_path = await registry.export_agent(agent_id)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=zip_path.name,
    )


@router.get("/{agent_id}/overview")
async def get_agent_overview(
    agent_id: str,
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Get agent overview summary (agent info + session count + current basins + recent flags)."""
    session_count = await memory.count_sessions(agent_id)
    current_basins = await memory.get_current_basins(agent_id)
    flags = await memory.get_evaluator_flags(agent_id, limit=5)
    proposals = await memory.get_tier_proposals(agent_id, status="pending")
    recent = await memory.list_sessions(agent_id, limit=1)
    last_session = recent[0] if recent else None

    # Include basin_definitions for lock/deprecation metadata (v0.9.5)
    basin_defs = await memory.get_basin_definitions(agent_id, include_deprecated=True)

    return {
        "agent": agent.to_dict(),
        "session_count": session_count,
        "current_basins": [b.to_dict() for b in current_basins],
        "basin_definitions": [d.to_dict() for d in basin_defs],
        "recent_flags": [f.to_dict() for f in flags],
        "pending_proposal_count": len(proposals),
        "queue_status": _get_queue_status(agent_id),
        "last_session": (
            {
                "session_id": last_session.session_id,
                "start_time": last_session.start_time,
                "end_time": last_session.end_time,
                "turn_count": last_session.turn_count,
                "status": last_session.status,
            }
            if last_session
            else None
        ),
    }


class DeprecateBasinRequest(BaseModel):
    """Request body for deprecating a basin."""
    basin_name: str
    rationale: str


@router.post("/{agent_id}/basins/deprecate")
async def deprecate_basin(
    agent_id: str,
    body: DeprecateBasinRequest,
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Soft-deprecate a basin. Preserves history but excludes from future sessions."""
    await memory.deprecate_basin(agent_id, body.basin_name, body.rationale)
    await memory.emit_event("basin_updated", agent_id, {"basin_name": body.basin_name, "action": "deprecated"})
    return {
        "status": "deprecated",
        "basin_name": body.basin_name,
        "rationale": body.rationale,
    }


@router.post("/{agent_id}/basins/undeprecate")
async def undeprecate_basin(
    agent_id: str,
    basin_name: str = Query(..., description="Name of the basin to restore"),
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Restore a deprecated basin to active tracking."""
    basin = await memory.undeprecate_basin(agent_id, basin_name)
    if not basin:
        raise HTTPException(
            status_code=404,
            detail=f"Basin '{basin_name}' not found in basin_current for agent '{agent_id}'",
        )
    await memory.emit_event("basin_updated", agent_id, {"basin_name": basin_name, "action": "restored"})
    return {
        "status": "restored",
        "basin": basin.to_dict(),
    }


# ── Basin Definitions (v0.9.5) ────────────────────────────────────────


@router.get("/{agent_id}/basin-definitions")
async def get_basin_definitions(
    agent_id: str,
    include_deprecated: bool = False,
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Get all basin definitions for an agent."""
    await memory.ensure_basin_migration(agent_id)
    defs = await memory.get_basin_definitions(agent_id, include_deprecated=include_deprecated)
    return {"basin_definitions": [d.to_dict() for d in defs]}


@router.get("/{agent_id}/basin-definitions/{basin_name}/history")
async def get_basin_definition_history(
    agent_id: str,
    basin_name: str,
    limit: int = Query(20, ge=1, le=200),
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Get modification history for a basin."""
    mods = await memory.get_basin_modifications(agent_id, basin_name, limit)
    return {"modifications": [m.to_dict() for m in mods]}


@router.put("/{agent_id}/basin-definitions/{basin_name}")
async def update_basin_definition(
    agent_id: str,
    basin_name: str,
    request: Request,
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Update a basin definition (brain-level operation)."""
    body = await request.json()
    modifications = body.get("modifications", {})
    rationale = body.get("rationale", "")
    result = await memory.update_basin_definition(
        agent_id, basin_name, modifications,
        modified_by="brain", rationale=rationale, override_lock=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"Basin '{basin_name}' not found")
    await memory.emit_event("basin_updated", agent_id, {"basin_name": basin_name, "action": "modified"})
    return result.to_dict()


@router.post("/{agent_id}/basin-definitions/{basin_name}/lock")
async def lock_basin(
    agent_id: str,
    basin_name: str,
    request: Request,
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Lock a basin to prevent body modifications."""
    body = await request.json()
    rationale = body.get("rationale", "Locked by brain")
    result = await memory.update_basin_definition(
        agent_id, basin_name, {"locked_by_brain": 1},
        modified_by="brain", rationale=rationale, override_lock=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"Basin '{basin_name}' not found")
    await memory.emit_event("basin_updated", agent_id, {"basin_name": basin_name, "action": "locked"})
    return {"status": "locked", "basin": result.to_dict()}


@router.post("/{agent_id}/basin-definitions/{basin_name}/unlock")
async def unlock_basin(
    agent_id: str,
    basin_name: str,
    request: Request,
    agent: AgentConfig = Depends(require_agent),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Unlock a basin to allow body modifications."""
    body = await request.json()
    rationale = body.get("rationale", "Unlocked by brain")
    result = await memory.update_basin_definition(
        agent_id, basin_name, {"locked_by_brain": 0},
        modified_by="brain", rationale=rationale, override_lock=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"Basin '{basin_name}' not found")
    await memory.emit_event("basin_updated", agent_id, {"basin_name": basin_name, "action": "unlocked"})
    return {"status": "unlocked", "basin": result.to_dict()}
