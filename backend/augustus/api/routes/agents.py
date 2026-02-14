"""Agent CRUD, lifecycle, and overview endpoints."""
from __future__ import annotations

import logging
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from augustus.api.dependencies import get_agent_registry, get_memory
from augustus.exceptions import AgentNotFoundError
from augustus.models.dataclasses import AgentConfig, BasinConfig, TierSettings
from augustus.models.enums import AgentStatus, BasinClass, TierLevel
from augustus.services.agent_registry import AgentRegistry
from augustus.services.memory import MemoryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents", tags=["agents"])


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


class CloneAgentRequest(BaseModel):
    """Request body for cloning an agent."""
    new_agent_id: str


class ParseYamlRequest(BaseModel):
    """Request body for parsing a bootstrap YAML for import."""
    yaml_text: str


# ── Helpers ────────────────────────────────────────────────────────────


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
    """Serialize AgentConfig to JSON-friendly dict."""
    return {
        "agent_id": agent.agent_id,
        "description": agent.description,
        "status": agent.status.value if isinstance(agent.status, AgentStatus) else str(agent.status),
        "model_override": agent.model_override,
        "temperature_override": agent.temperature_override,
        "max_tokens_override": agent.max_tokens_override,
        "max_turns": agent.max_turns,
        "session_interval": agent.session_interval,
        "identity_core": agent.identity_core,
        "session_task": agent.session_task,
        "close_protocol": agent.close_protocol,
        "capabilities": agent.capabilities,
        "basins": [
            {
                "name": b.name,
                "basin_class": b.basin_class.value if isinstance(b.basin_class, BasinClass) else str(b.basin_class),
                "alpha": b.alpha,
                "lambda": b.lambda_,
                "eta": b.eta,
                "tier": b.tier.value if isinstance(b.tier, TierLevel) else int(b.tier),
            }
            for b in agent.basins
        ],
        "tier_settings": (
            {
                "tier_2_auto_approve": agent.tier_settings.tier_2_auto_approve,
                "tier_2_threshold": agent.tier_settings.tier_2_threshold,
                "emergence_auto_approve": agent.tier_settings.emergence_auto_approve,
                "emergence_threshold": agent.tier_settings.emergence_threshold,
            }
            if agent.tier_settings
            else None
        ),
        "created_at": agent.created_at,
        "last_active": agent.last_active,
    }


# ── Default capabilities for import merging ────────────────────────────

_DEFAULT_CAPABILITIES = [
    {"name": "mcp", "enabled": True, "available_from_turn": 1},
    {"name": "rag", "enabled": True, "available_from_turn": 1},
    {"name": "web_search", "enabled": False, "available_from_turn": 1},
    {"name": "memory_query", "enabled": False, "available_from_turn": 1},
    {"name": "memory_write", "enabled": False, "available_from_turn": 5},
    {"name": "file_write", "enabled": False, "available_from_turn": 10},
]


def _parse_yaml_lenient(yaml_text: str) -> dict[str, Any]:
    """Parse a bootstrap YAML leniently for form population.

    Does not require agent_id or session_id. Returns extracted fields
    plus warnings/errors lists.
    """
    warnings: list[str] = []
    errors: list[str] = []
    result: dict[str, Any] = {
        "max_turns": None,
        "identity_core": None,
        "session_task": None,
        "close_protocol": None,
        "capabilities": None,
        "basins": None,
        "warnings": warnings,
        "errors": errors,
    }

    # Parse YAML
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        errors.append(f"Invalid YAML syntax: {e}")
        return result

    if not isinstance(data, dict):
        errors.append("YAML must be a mapping at top level, got " + type(data).__name__)
        return result

    # Check for unexpected top-level keys
    expected_keys = {"framework", "identity_core", "session_task", "close_protocol"}
    for key in data:
        if key not in expected_keys:
            warnings.append(f"Unexpected top-level field ignored: '{key}'")

    # Extract identity_core
    if "identity_core" in data:
        result["identity_core"] = str(data["identity_core"]).strip()

    # Extract session_task
    if "session_task" in data:
        result["session_task"] = str(data["session_task"]).strip()

    # Extract close_protocol — serialize dict back to YAML text
    if "close_protocol" in data:
        cp = data["close_protocol"]
        if isinstance(cp, dict):
            result["close_protocol"] = yaml.dump(
                cp, default_flow_style=False, sort_keys=False, allow_unicode=True
            ).strip()
        elif cp is not None:
            result["close_protocol"] = str(cp).strip()

    # Extract framework section
    fw = data.get("framework")
    if not isinstance(fw, dict):
        if fw is not None:
            warnings.append("'framework' section is not a mapping, skipping")
        else:
            warnings.append("No 'framework' section found — only textual fields imported")
        return result

    # max_turns
    max_turns = fw.get("max_turns")
    if isinstance(max_turns, int) and 1 <= max_turns <= 50:
        result["max_turns"] = max_turns
    elif max_turns is not None:
        warnings.append(f"'max_turns' value '{max_turns}' invalid, skipping")

    # basin_params
    basin_params = fw.get("basin_params")
    if isinstance(basin_params, dict) and basin_params:
        basins = []
        for name, config in basin_params.items():
            if not isinstance(config, dict):
                warnings.append(f"Basin '{name}' is not a mapping, skipping")
                continue

            basin_class_str = config.get("class", "peripheral")
            if basin_class_str not in ("core", "peripheral", "emergent"):
                warnings.append(
                    f"Basin '{name}' class '{basin_class_str}' unrecognized, defaulting to 'peripheral'"
                )
                basin_class_str = "peripheral"

            alpha = config.get("alpha", 0.5)
            if not isinstance(alpha, (int, float)):
                warnings.append(f"Basin '{name}' alpha is not numeric, defaulting to 0.5")
                alpha = 0.5
            elif alpha < 0.05 or alpha > 1.0:
                clamped = max(0.05, min(1.0, float(alpha)))
                warnings.append(
                    f"Basin '{name}' alpha {alpha} clamped to {clamped}"
                )
                alpha = clamped

            lambda_ = config.get("lambda", 0.95)
            if not isinstance(lambda_, (int, float)):
                lambda_ = 0.95
            else:
                lambda_ = max(0.0, min(1.0, float(lambda_)))

            eta = config.get("eta", 0.1)
            if not isinstance(eta, (int, float)):
                eta = 0.1
            else:
                eta = max(0.0, min(1.0, float(eta)))

            # Tier defaults based on class if not specified
            tier = config.get("tier")
            if tier is None:
                tier = 2 if basin_class_str == "core" else 3
            elif tier not in (1, 2, 3):
                warnings.append(f"Basin '{name}' tier '{tier}' invalid, defaulting from class")
                tier = 2 if basin_class_str == "core" else 3

            basins.append({
                "name": name,
                "class": basin_class_str,
                "alpha": round(float(alpha), 4),
                "lambda": round(float(lambda_), 4),
                "eta": round(float(eta), 4),
                "tier": int(tier),
            })
        if basins:
            result["basins"] = basins
    elif basin_params is not None:
        warnings.append("'basin_params' is empty or not a mapping")

    # capabilities / services
    caps_raw = fw.get("capabilities", fw.get("services"))
    if isinstance(caps_raw, dict) and caps_raw:
        # Start with defaults, then merge YAML values
        caps_by_name = {c["name"]: dict(c) for c in _DEFAULT_CAPABILITIES}
        for name, val in caps_raw.items():
            if isinstance(val, bool):
                if name in caps_by_name:
                    caps_by_name[name]["enabled"] = val
                else:
                    caps_by_name[name] = {
                        "name": name,
                        "enabled": val,
                        "available_from_turn": 1,
                    }
            elif isinstance(val, dict):
                enabled = val.get("enabled", True)
                from_turn = val.get("available_from_turn", 1)
                if name in caps_by_name:
                    caps_by_name[name]["enabled"] = bool(enabled)
                    caps_by_name[name]["available_from_turn"] = int(from_turn)
                else:
                    caps_by_name[name] = {
                        "name": name,
                        "enabled": bool(enabled),
                        "available_from_turn": int(from_turn),
                    }
        result["capabilities"] = list(caps_by_name.values())

    return result


# ── Endpoints ──────────────────────────────────────────────────────────


@router.post("/parse-yaml")
async def parse_yaml_for_import(body: ParseYamlRequest) -> dict:
    """Parse a bootstrap YAML file for agent form population.

    Lenient parsing — does not require agent_id or session_id.
    Returns extracted fields with warnings for any issues.
    """
    return _parse_yaml_lenient(body.yaml_text)


@router.get("")
async def list_agents(
    registry: AgentRegistry = Depends(get_agent_registry),
    memory: MemoryService = Depends(get_memory),
) -> list[dict]:
    """List all agents with session counts."""
    agents = await registry.list_agents()
    result = []
    for a in agents:
        d = _agent_to_dict(a)
        d["session_count"] = await memory.count_sessions(a.agent_id)
        result.append(d)
    return result


@router.post("", status_code=201)
async def create_agent(
    body: CreateAgentRequest,
    registry: AgentRegistry = Depends(get_agent_registry),
) -> dict:
    """Create a new agent."""
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
    )

    await registry.create_agent(config)
    created = await registry.get_agent(body.agent_id)
    return _agent_to_dict(created) if created else {"agent_id": body.agent_id, "status": "created"}


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    registry: AgentRegistry = Depends(get_agent_registry),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Get agent detail."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    d = _agent_to_dict(agent)
    d["session_count"] = await memory.count_sessions(agent_id)
    return d


@router.put("/{agent_id}")
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    registry: AgentRegistry = Depends(get_agent_registry),
) -> dict:
    """Update agent configuration."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

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

    try:
        await registry.update_agent(agent_id, updates)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # If any YAML-affecting field changed, regenerate the pending instruction file.
    # Description and tier_settings are metadata-only — no YAML rebuild needed.
    yaml_fields = {
        "identity_core", "session_task", "close_protocol",
        "basins", "capabilities", "max_turns",
        "model_override", "temperature_override", "max_tokens_override",
    }
    if yaml_fields & updates.keys():
        try:
            await registry.regenerate_pending_yaml(agent_id)
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
    registry: AgentRegistry = Depends(get_agent_registry),
) -> dict:
    """Pause an agent."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    await registry.pause_agent(agent_id)
    return {"agent_id": agent_id, "status": "paused"}


@router.post("/{agent_id}/resume")
async def resume_agent(
    agent_id: str,
    registry: AgentRegistry = Depends(get_agent_registry),
) -> dict:
    """Resume a paused agent."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    await registry.resume_agent(agent_id)
    return {"agent_id": agent_id, "status": "active"}


@router.post("/{agent_id}/clone", status_code=201)
async def clone_agent(
    agent_id: str,
    body: CloneAgentRequest,
    registry: AgentRegistry = Depends(get_agent_registry),
) -> dict:
    """Clone an agent to a new ID."""
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
    registry: AgentRegistry = Depends(get_agent_registry),
    memory: MemoryService = Depends(get_memory),
) -> dict:
    """Get agent overview summary (agent info + session count + current basins + recent flags)."""
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # Get session count
    session_count = await memory.count_sessions(agent_id)

    # Get current basins
    current_basins = await memory.get_current_basins(agent_id)
    basins_out = [
        {
            "name": b.name,
            "basin_class": b.basin_class.value if isinstance(b.basin_class, BasinClass) else str(b.basin_class),
            "alpha": b.alpha,
            "lambda": b.lambda_,
            "eta": b.eta,
            "tier": b.tier.value if isinstance(b.tier, TierLevel) else int(b.tier),
        }
        for b in current_basins
    ]

    # Get recent flags
    flags = await memory.get_evaluator_flags(agent_id, limit=5)
    flags_out = [
        {
            "flag_id": f.flag_id,
            "flag_type": f.flag_type.value if hasattr(f.flag_type, "value") else str(f.flag_type),
            "severity": f.severity,
            "detail": f.detail,
            "reviewed": f.reviewed,
            "created_at": f.created_at,
        }
        for f in flags
    ]

    # Get pending proposals count
    proposals = await memory.get_tier_proposals(agent_id, status="pending")
    pending_proposal_count = len(proposals)

    # Last session info
    recent = await memory.list_sessions(agent_id, limit=1)
    last_session = recent[0] if recent else None

    return {
        "agent": _agent_to_dict(agent),
        "session_count": session_count,
        "current_basins": basins_out,
        "recent_flags": flags_out,
        "pending_proposal_count": pending_proposal_count,
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
