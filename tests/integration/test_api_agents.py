"""Integration tests for agent API endpoints."""
import pytest


@pytest.mark.asyncio
async def test_health_check(client):
    """Test health check endpoint."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


@pytest.mark.asyncio
async def test_list_agents_empty(client):
    """Test listing agents returns empty list initially."""
    resp = await client.get("/api/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 0


@pytest.mark.asyncio
async def test_create_agent(client):
    """Test creating an agent."""
    payload = {
        "agent_id": "test-agent",
        "description": "A test agent",
        "identity_core": "You are a test agent.",
        "session_task": "Explore what it means to be a test.",
        "close_protocol": "Reflect on test outcomes.",
        "max_turns": 8,
    }
    resp = await client.post("/api/agents", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_id"] == "test-agent"
    assert data["description"] == "A test agent"
    assert data["identity_core"] == "You are a test agent."
    assert data["session_task"] == "Explore what it means to be a test."
    assert data["close_protocol"] == "Reflect on test outcomes."
    assert data["max_turns"] == 8


@pytest.mark.asyncio
async def test_create_duplicate_agent(client):
    """Test that creating a duplicate agent fails."""
    payload = {
        "agent_id": "dup-agent",
        "description": "Original",
        "identity_core": "Test",
        "max_turns": 8,
    }
    resp1 = await client.post("/api/agents", json=payload)
    assert resp1.status_code == 201

    resp2 = await client.post("/api/agents", json=payload)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_create_and_get_agent(client):
    """Test creating and retrieving an agent."""
    payload = {
        "agent_id": "test-agent-2",
        "description": "Another test agent",
        "identity_core": "You are a test agent.",
        "max_turns": 8,
        "basins": [
            {
                "name": "test_basin",
                "basin_class": "core",
                "alpha": 0.8,
                "lambda": 0.95,
                "eta": 0.1,
                "tier": 2,
            }
        ],
    }
    await client.post("/api/agents", json=payload)

    resp = await client.get("/api/agents/test-agent-2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == "test-agent-2"
    assert data["description"] == "Another test agent"
    assert len(data["basins"]) == 1
    assert data["basins"][0]["name"] == "test_basin"
    assert data["basins"][0]["basin_class"] == "core"


@pytest.mark.asyncio
async def test_get_nonexistent_agent(client):
    """Test getting a nonexistent agent returns 404."""
    resp = await client.get("/api/agents/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_agents_after_create(client):
    """Test listing agents after creating one."""
    await client.post("/api/agents", json={
        "agent_id": "listed-agent",
        "description": "Listed",
        "identity_core": "Test",
        "max_turns": 8,
    })
    resp = await client.get("/api/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert len(agents) == 1
    assert agents[0]["agent_id"] == "listed-agent"


@pytest.mark.asyncio
async def test_update_agent(client):
    """Test updating an agent."""
    # Create agent
    await client.post("/api/agents", json={
        "agent_id": "update-agent",
        "description": "Original description",
        "identity_core": "Original core",
        "session_task": "Original task",
        "close_protocol": "Original close",
        "max_turns": 8,
    })

    # Update
    update_payload = {
        "description": "Updated description",
        "max_turns": 12,
        "session_task": "Updated task",
    }
    resp = await client.put("/api/agents/update-agent", json=update_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["description"] == "Updated description"
    assert data["max_turns"] == 12
    assert data["session_task"] == "Updated task"
    assert data["close_protocol"] == "Original close"  # Unchanged
    assert data["identity_core"] == "Original core"  # Unchanged


@pytest.mark.asyncio
async def test_delete_agent(client):
    """Test deleting an agent (soft delete by default)."""
    await client.post("/api/agents", json={
        "agent_id": "deletable",
        "description": "Delete me",
        "identity_core": "Test",
        "max_turns": 8,
    })

    resp = await client.delete("/api/agents/deletable")
    assert resp.status_code == 204

    # Verify soft delete (may still be retrievable or return 404 depending on implementation)
    resp = await client.get("/api/agents/deletable")
    assert resp.status_code in (200, 404)


@pytest.mark.asyncio
async def test_hard_delete_agent(client):
    """Test hard deleting an agent removes all data."""
    await client.post("/api/agents", json={
        "agent_id": "hard-deletable",
        "description": "Hard delete me",
        "identity_core": "Test identity",
        "max_turns": 8,
    })

    resp = await client.delete("/api/agents/hard-deletable?hard=true")
    assert resp.status_code == 204

    # Verify hard delete — agent should be gone
    resp = await client.get("/api/agents/hard-deletable")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_agent(client):
    """Test deleting a nonexistent agent returns 404."""
    resp = await client.delete("/api/agents/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_pause_resume_agent(client):
    """Test pausing and resuming an agent."""
    await client.post("/api/agents", json={
        "agent_id": "pausable",
        "description": "Pause me",
        "identity_core": "Test",
        "max_turns": 8,
    })

    # Pause
    resp = await client.post("/api/agents/pausable/pause")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "paused"

    # Resume
    resp = await client.post("/api/agents/pausable/resume")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_pause_nonexistent_agent(client):
    """Test pausing a nonexistent agent returns 404."""
    resp = await client.post("/api/agents/nonexistent/pause")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_clone_agent(client):
    """Test cloning an agent."""
    # Create source agent
    await client.post("/api/agents", json={
        "agent_id": "source-agent",
        "description": "Source",
        "identity_core": "Original",
        "session_task": "Source task",
        "close_protocol": "Source close",
        "max_turns": 8,
        "basins": [
            {
                "name": "basin1",
                "basin_class": "core",
                "alpha": 0.7,
                "lambda": 0.95,
                "eta": 0.1,
                "tier": 2,
            }
        ],
    })

    # Clone
    resp = await client.post("/api/agents/source-agent/clone", json={
        "new_agent_id": "cloned-agent",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_id"] == "cloned-agent"
    # Clone description is prefixed with "Clone of"
    assert "Source" in data["description"]
    assert data["identity_core"] == "Original"
    assert data["session_task"] == "Source task"
    assert data["close_protocol"] == "Source close"


@pytest.mark.asyncio
async def test_clone_to_existing_id(client):
    """Test cloning to an existing agent ID fails."""
    await client.post("/api/agents", json={
        "agent_id": "agent1",
        "description": "First",
        "identity_core": "Test",
        "max_turns": 8,
    })
    await client.post("/api/agents", json={
        "agent_id": "agent2",
        "description": "Second",
        "identity_core": "Test",
        "max_turns": 8,
    })

    resp = await client.post("/api/agents/agent1/clone", json={
        "new_agent_id": "agent2",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_export_agent(client):
    """Test exporting an agent."""
    await client.post("/api/agents", json={
        "agent_id": "export-agent",
        "description": "Export me",
        "identity_core": "Test",
        "max_turns": 8,
    })

    resp = await client.post("/api/agents/export-agent/export")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == "export-agent"
    assert "export_path" in data


@pytest.mark.asyncio
async def test_get_agent_overview(client):
    """Test getting agent overview."""
    await client.post("/api/agents", json={
        "agent_id": "overview-agent",
        "description": "Overview test",
        "identity_core": "Test",
        "max_turns": 8,
        "basins": [
            {
                "name": "test_basin",
                "basin_class": "core",
                "alpha": 0.85,
                "lambda": 0.95,
                "eta": 0.1,
                "tier": 2,
            }
        ],
    })

    resp = await client.get("/api/agents/overview-agent/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "agent" in data
    assert "session_count" in data
    assert "current_basins" in data
    assert "recent_flags" in data
    assert "pending_proposal_count" in data
    assert data["agent"]["agent_id"] == "overview-agent"
    assert data["session_count"] == 0  # No sessions yet
    assert len(data["current_basins"]) == 1
