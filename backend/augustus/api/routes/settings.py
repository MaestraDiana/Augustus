"""Settings management endpoints."""
from __future__ import annotations

import logging

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from augustus.api.dependencies import get_config_manager, get_settings
from augustus.config import ConfigManager, Settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings", tags=["settings"])


# ── Pydantic models ───────────────────────────────────────────────────


class UpdateSettingsRequest(BaseModel):
    """Request body for updating settings."""
    default_model: str | None = None
    default_temperature: float | None = None
    default_max_tokens: int | None = None
    poll_interval: int | None = None
    max_concurrent_agents: int | None = None
    budget_warning: float | None = None
    budget_hard_stop: float | None = None
    budget_per_session: float | None = None
    budget_per_day: float | None = None
    evaluator_enabled: bool | None = None
    evaluator_model: str | None = None
    formula_in_identity_core: bool | None = None
    dashboard_port: int | None = None
    mcp_enabled: bool | None = None
    auto_update: bool | None = None
    data_directory: str | None = None
    api_key: str | None = None  # Special: triggers encryption


class ValidateKeyRequest(BaseModel):
    """Request body for validating an API key."""
    api_key: str


# ── Helpers ────────────────────────────────────────────────────────────


def _settings_to_dict(s: Settings) -> dict:
    """Serialize Settings to JSON-friendly dict (excluding sensitive data)."""
    return {
        "default_model": s.default_model,
        "default_temperature": s.default_temperature,
        "default_max_tokens": s.default_max_tokens,
        "poll_interval": s.poll_interval,
        "max_concurrent_agents": s.max_concurrent_agents,
        "budget_warning": s.budget_warning,
        "budget_hard_stop": s.budget_hard_stop,
        "budget_per_session": s.budget_per_session,
        "budget_per_day": s.budget_per_day,
        "evaluator_enabled": s.evaluator_enabled,
        "evaluator_model": s.evaluator_model,
        "formula_in_identity_core": s.formula_in_identity_core,
        "dashboard_port": s.dashboard_port,
        "mcp_enabled": s.mcp_enabled,
        "auto_update": s.auto_update,
        "data_directory": s.data_directory,
        "has_api_key": bool(s.api_key_encrypted),
    }


# ── Endpoints ──────────────────────────────────────────────────────────


@router.get("")
async def get_settings_endpoint(
    settings: Settings = Depends(get_settings),
) -> dict:
    """Get all application settings."""
    return _settings_to_dict(settings)


@router.put("")
async def update_settings_endpoint(
    body: UpdateSettingsRequest,
    config: ConfigManager = Depends(get_config_manager),
) -> dict:
    """Update application settings."""
    updates = body.model_dump(exclude_none=True)

    # Handle API key separately (needs encryption)
    api_key = updates.pop("api_key", None)
    if api_key:
        config.settings.set_api_key(api_key)

    if updates:
        config.update(updates)
    elif api_key:
        config.save()

    return _settings_to_dict(config.settings)


@router.post("/validate-key")
async def validate_api_key(
    body: ValidateKeyRequest,
) -> dict:
    """Validate an Anthropic API key by making a test request."""
    try:
        client = anthropic.Anthropic(api_key=body.api_key)
        # A lightweight API call to validate the key
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=10,
            messages=[{"role": "user", "content": "Hello"}],
        )
        return {"valid": True, "message": "API key is valid"}
    except anthropic.AuthenticationError:
        return {"valid": False, "message": "API key is invalid"}
    except anthropic.APIError as e:
        return {"valid": False, "message": f"API error: {str(e)}"}
    except Exception as e:
        return {"valid": False, "message": f"Validation failed: {str(e)}"}
