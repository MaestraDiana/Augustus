"""FastAPI dependency injection."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends

from augustus.config import ConfigManager, Settings
from augustus.db.sqlite_store import SQLiteStore
from augustus.db.chroma_store import ChromaStore
from augustus.models.dataclasses import AgentConfig
from augustus.services.memory import MemoryService
from augustus.services.agent_registry import AgentRegistry
from augustus.services.schema_parser import SchemaParser
from augustus.services.handoff_engine import HandoffEngine
from augustus.services.evaluator import EvaluatorService
from augustus.services.tier_enforcer import TierEnforcer
from augustus.utils import normalize_model

logger = logging.getLogger(__name__)


class ServiceContainer:
    """Holds all initialized service instances."""

    config_manager: ConfigManager | None = None
    sqlite_store: SQLiteStore | None = None
    chroma_store: ChromaStore | None = None
    memory: MemoryService | None = None
    agent_registry: AgentRegistry | None = None
    schema_parser: SchemaParser | None = None
    handoff: HandoffEngine | None = None
    evaluator: EvaluatorService | None = None
    tier_enforcer: TierEnforcer | None = None
    orchestrator: object | None = None  # Set later by main.py


_container = ServiceContainer()


def get_container() -> ServiceContainer:
    """Return the global service container."""
    return _container


def get_memory() -> MemoryService:
    """Return the MemoryService instance."""
    assert _container.memory is not None, "MemoryService not initialized"
    return _container.memory


def get_agent_registry() -> AgentRegistry:
    """Return the AgentRegistry instance."""
    assert _container.agent_registry is not None, "AgentRegistry not initialized"
    return _container.agent_registry


def get_settings() -> Settings:
    """Return the current Settings."""
    assert _container.config_manager is not None, "ConfigManager not initialized"
    return _container.config_manager.settings


def get_config_manager() -> ConfigManager:
    """Return the ConfigManager instance."""
    assert _container.config_manager is not None, "ConfigManager not initialized"
    return _container.config_manager


def get_tier_enforcer() -> TierEnforcer:
    """Return the TierEnforcer instance."""
    assert _container.tier_enforcer is not None, "TierEnforcer not initialized"
    return _container.tier_enforcer


async def require_agent(
    agent_id: str,
    registry: AgentRegistry = Depends(get_agent_registry),
) -> "AgentConfig":
    """FastAPI-injectable dependency that validates agent_id exists.

    Usage in route handlers::

        @router.get("/{agent_id}/something")
        async def my_route(agent: AgentConfig = Depends(require_agent)):
            ...

    Raises HTTPException(404) when the agent doesn't exist.
    """
    from fastapi import HTTPException

    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return agent


def init_services(config_dir: Path | None = None) -> ServiceContainer:
    """Initialize all services and wire dependencies."""
    _container.config_manager = ConfigManager(config_dir)
    data_dir = _container.config_manager.get_data_dir()

    _container.sqlite_store = SQLiteStore(data_dir / "augustus.db")
    _container.chroma_store = ChromaStore(data_dir / "chromadb")
    _container.memory = MemoryService(_container.sqlite_store, _container.chroma_store)
    _container.agent_registry = AgentRegistry(data_dir, _container.memory)
    _container.schema_parser = SchemaParser()
    _container.handoff = HandoffEngine()
    _container.tier_enforcer = TierEnforcer(_container.memory)

    api_key = _container.config_manager.settings.get_api_key()
    if api_key:
        _container.evaluator = EvaluatorService(
            api_key=api_key,
            model=normalize_model(_container.config_manager.settings.evaluator_model),
        )

    logger.info("All services initialized (data_dir=%s)", data_dir)
    return _container


def create_orchestrator() -> object | None:
    """Build SessionManager + Orchestrator from the current container.

    Returns the Orchestrator, or None if no API key is configured.
    Also sets ``_container.orchestrator``.
    """
    from augustus.orchestrator.loop import Orchestrator
    from augustus.services.session_manager import SessionManager

    api_key = (
        _container.config_manager.settings.get_api_key()
        if _container.config_manager
        else ""
    )

    session_mgr = None
    if api_key:
        session_mgr = SessionManager(
            api_key=api_key,
            memory=_container.memory,
            evaluator=_container.evaluator,
            handoff=_container.handoff,
            tier_enforcer=_container.tier_enforcer,
            schema_parser=_container.schema_parser,
            settings=(
                _container.config_manager.settings
                if _container.config_manager
                else None
            ),
        )
    else:
        logger.warning("No API key configured — orchestrator will not start sessions")

    orchestrator = Orchestrator(
        agent_registry=_container.agent_registry,
        memory=_container.memory,
        session_manager=session_mgr,
        evaluator=_container.evaluator,
        handoff=_container.handoff,
        schema_parser=_container.schema_parser,
        config=(
            _container.config_manager.settings
            if _container.config_manager
            else None
        ),
    )
    _container.orchestrator = orchestrator
    return orchestrator
