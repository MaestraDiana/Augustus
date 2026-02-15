"""Agent CRUD, lifecycle, and overview endpoints."""
from __future__ import annotations

import logging
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from augustus.api.dependencies import get_agent_registry, get_container, get_memory, require_agent
from augustus.exceptions import AgentNotFoundError
from augustus.models.dataclasses import AgentConfig, BasinConfig, TierSettings
from augustus.models.enums import AgentStatus, BasinClass, TierLevel
from augustus.services.agent_registry import AgentRegistry
from augustus.services.memory import MemoryService

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
        "session_protocol": None,
        "relational_grounding": None,
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
    expected_keys = {"framework", "identity_core", "session_task", "close_protocol", "session_protocol", "relational_grounding"}
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

    # Extract structural sections (session_protocol, relational_grounding)
    for skey in ("session_protocol", "relational_grounding"):
        if skey in data:
            val = data[skey]
            if isinstance(val, dict):
                result[skey] = yaml.dump(
                    val, default_flow_style=False, sort_keys=False, allow_unicode=True
                ).strip()
            elif val is not None:
                result[skey] = str(val).strip()

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

    return {
        "agent": agent.to_dict(),
        "session_count": session_count,
        "current_basins": [b.to_dict() for b in current_basins],
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
