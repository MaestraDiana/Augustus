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
    preferred_provider: str | None = None
    api_key: str | None = None  # Anthropic key
    gemini_api_key: str | None = None  # Gemini key


class ValidateKeyRequest(BaseModel):
    """Request body for validating an API key."""
    api_key: str
    provider: str = "anthropic"


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
        "preferred_provider": s.preferred_provider,
        "has_api_key": bool(s.api_key_encrypted),
        "has_gemini_api_key": bool(s.gemini_api_key_encrypted),
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

    # Handle API keys separately (they need encryption)
    api_key = updates.pop("api_key", None)
    if api_key:
        config.settings.set_api_key(api_key, "anthropic")
        
    gemini_key = updates.pop("gemini_api_key", None)
    if gemini_key:
        config.settings.set_api_key(gemini_key, "gemini")

    if updates:
        config.update(updates)
    elif api_key or gemini_key:
        config.save()

    return _settings_to_dict(config.settings)


@router.post("/validate-key")
async def validate_api_key(
    body: ValidateKeyRequest,
) -> dict:
    """Validate an API key with the specified provider."""
    from augustus.services.llm import AnthropicClient, GeminiClient
    
    try:
        if body.provider == "gemini":
            client = GeminiClient(api_key=body.api_key)
        else:
            client = AnthropicClient(api_key=body.api_key)
            
        is_valid = await client.validate_key()
        if is_valid:
            return {"valid": True, "message": f"{body.provider.capitalize()} API key is valid"}
        else:
            return {"valid": False, "message": f"Invalid {body.provider} API key"}
            
    except Exception as e:
        logger.error(f"Key validation error: {e}")
        return {"valid": False, "message": f"Validation failed: {str(e)}"}
