"""Shared fixtures for integration tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from augustus.api.app import app
from augustus.api.dependencies import init_services, _container


@pytest_asyncio.fixture
async def client(tmp_path):
    """Create test client with temp services."""
    # Reset the container to avoid state leakage
    _container.config_manager = None
    _container.sqlite_store = None
    _container.chroma_store = None
    _container.memory = None
    _container.agent_registry = None
    _container.schema_parser = None
    _container.handoff = None
    _container.evaluator = None
    _container.tier_enforcer = None
    _container.orchestrator = None

    # Initialize services with temp directory
    init_services(tmp_path / "config")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
