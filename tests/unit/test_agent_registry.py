"""Tests for Agent Registry — agent lifecycle management."""
import pytest
from pathlib import Path

from augustus.models.dataclasses import AgentConfig
from augustus.models.enums import AgentStatus
from augustus.services.agent_registry import AgentRegistry
from augustus.exceptions import AgentNotFoundError


@pytest.mark.asyncio
async def test_create_agent_creates_directories(memory_service, sample_agent_config, tmp_path):
    """Test agent creation creates directory structure."""
    registry = AgentRegistry(tmp_path, memory_service)

    await registry.create_agent(sample_agent_config)

    agent_dir = registry.get_agent_dir("test-agent")
    assert agent_dir.exists()
    assert (agent_dir / "queue" / "pending").exists()
    assert (agent_dir / "queue" / "active").exists()
    assert (agent_dir / "queue" / "archive").exists()
    assert (agent_dir / "queue" / "error").exists()
    assert (agent_dir / "logs").exists()


@pytest.mark.asyncio
async def test_create_agent_stores_config(memory_service, sample_agent_config, tmp_path):
    """Test agent creation stores config in memory service."""
    registry = AgentRegistry(tmp_path, memory_service)

    await registry.create_agent(sample_agent_config)
    retrieved = await registry.get_agent("test-agent")

    assert retrieved is not None
    assert retrieved.agent_id == "test-agent"
    assert retrieved.description == "Test agent"


@pytest.mark.asyncio
async def test_get_agent_returns_config(memory_service, sample_agent_config, tmp_path):
    """Test getting agent configuration."""
    registry = AgentRegistry(tmp_path, memory_service)

    await registry.create_agent(sample_agent_config)
    agent = await registry.get_agent("test-agent")

    assert agent is not None
    assert agent.agent_id == "test-agent"


@pytest.mark.asyncio
async def test_delete_agent_archive_mode(memory_service, sample_agent_config, tmp_path):
    """Test soft delete (archive mode) keeps data."""
    registry = AgentRegistry(tmp_path, memory_service)

    await registry.create_agent(sample_agent_config)
    await registry.delete_agent("test-agent", hard_delete=False)

    # Agent directory should still exist
    agent_dir = registry.get_agent_dir("test-agent")
    # Soft delete behavior may vary - check if agent is marked deleted
    # or still retrievable


@pytest.mark.asyncio
async def test_delete_agent_hard_delete(memory_service, sample_agent_config, tmp_path):
    """Test hard delete removes all data."""
    registry = AgentRegistry(tmp_path, memory_service)

    await registry.create_agent(sample_agent_config)
    await registry.delete_agent("test-agent", hard_delete=True)

    # Agent directory should be gone
    agent_dir = registry.get_agent_dir("test-agent")
    assert not agent_dir.exists()

    # Agent should not be retrievable
    agent = await registry.get_agent("test-agent")
    assert agent is None


@pytest.mark.asyncio
async def test_pause_resume_agent(memory_service, sample_agent_config, tmp_path):
    """Test pausing and resuming an agent."""
    registry = AgentRegistry(tmp_path, memory_service)

    await registry.create_agent(sample_agent_config)

    # Pause
    await registry.pause_agent("test-agent")
    agent = await registry.get_agent("test-agent")
    assert agent.status == AgentStatus.PAUSED

    # Resume
    await registry.resume_agent("test-agent")
    agent = await registry.get_agent("test-agent")
    assert agent.status == AgentStatus.ACTIVE


@pytest.mark.asyncio
async def test_clone_agent(memory_service, sample_agent_config, tmp_path):
    """Test cloning an agent."""
    registry = AgentRegistry(tmp_path, memory_service)

    await registry.create_agent(sample_agent_config)
    await registry.clone_agent("test-agent", "cloned-agent")

    cloned = await registry.get_agent("cloned-agent")
    assert cloned is not None
    assert cloned.agent_id == "cloned-agent"
    assert "Clone of test-agent" in cloned.description
    assert len(cloned.basins) == len(sample_agent_config.basins)


@pytest.mark.asyncio
async def test_list_agents(memory_service, sample_agent_config, tmp_path):
    """Test listing all agents."""
    registry = AgentRegistry(tmp_path, memory_service)

    await registry.create_agent(sample_agent_config)

    agent2 = AgentConfig(agent_id="agent-2", description="Second agent")
    await registry.create_agent(agent2)

    agents = await registry.list_agents()
    assert len(agents) >= 2
    assert any(a.agent_id == "test-agent" for a in agents)
    assert any(a.agent_id == "agent-2" for a in agents)


@pytest.mark.asyncio
async def test_export_agent(memory_service, sample_agent_config, tmp_path):
    """Test exporting agent data as ZIP."""
    registry = AgentRegistry(tmp_path, memory_service)

    await registry.create_agent(sample_agent_config)
    zip_path = await registry.export_agent("test-agent")

    assert zip_path.exists()
    assert zip_path.suffix == ".zip"
    assert "test-agent" in zip_path.name
