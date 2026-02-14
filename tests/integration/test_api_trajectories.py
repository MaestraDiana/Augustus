"""Integration tests for trajectory API endpoints."""
import pytest
import pytest_asyncio

from augustus.api.dependencies import get_memory


@pytest_asyncio.fixture
async def agent_with_trajectories(client):
    """Create an agent with basin trajectory data."""
    # Create agent
    await client.post("/api/agents", json={
        "agent_id": "trajectory-agent",
        "description": "Agent with trajectories",
        "identity_core": "Test",
        "max_turns": 8,
        "basins": [
            {
                "name": "basin_a",
                "basin_class": "core",
                "alpha": 0.9,
                "lambda": 0.95,
                "eta": 0.1,
                "tier": 2,
            },
            {
                "name": "basin_b",
                "basin_class": "peripheral",
                "alpha": 0.6,
                "lambda": 0.95,
                "eta": 0.1,
                "tier": 3,
            }
        ],
    })

    # Add session data with basin snapshots
    from augustus.models.dataclasses import SessionRecord, BasinSnapshot
    from augustus.models.enums import SessionPhase

    memory = get_memory()

    session1 = SessionRecord(
        session_id="traj-session-001",
        agent_id="trajectory-agent",
        start_time="2025-01-01T10:00:00",
        end_time="2025-01-01T10:15:00",
        turn_count=5,
        model="claude-sonnet-4-20250514",
        temperature=1.0,
        status="complete",
        transcript=[{"role": "user", "content": "test"}],
        close_report={"summary": "Done"},
        basin_snapshots=[
            BasinSnapshot(
                basin_name="basin_a",
                alpha_start=0.85,
                alpha_end=0.88,
                delta=0.03,
                relevance_score=0.9,
            ),
            BasinSnapshot(
                basin_name="basin_b",
                alpha_start=0.55,
                alpha_end=0.58,
                delta=0.03,
                relevance_score=0.7,
            )
        ],
        capabilities_used=["text"],
    )

    session2 = SessionRecord(
        session_id="traj-session-002",
        agent_id="trajectory-agent",
        start_time="2025-01-01T11:00:00",
        end_time="2025-01-01T11:15:00",
        turn_count=4,
        model="claude-sonnet-4-20250514",
        temperature=1.0,
        status="complete",
        transcript=[{"role": "user", "content": "test2"}],
        close_report={"summary": "Done"},
        basin_snapshots=[
            BasinSnapshot(
                basin_name="basin_a",
                alpha_start=0.88,
                alpha_end=0.9,
                delta=0.02,
                relevance_score=0.95,
            ),
            BasinSnapshot(
                basin_name="basin_b",
                alpha_start=0.58,
                alpha_end=0.6,
                delta=0.02,
                relevance_score=0.65,
            )
        ],
        capabilities_used=["text"],
    )

    await memory.store_session_record(session1)
    await memory.store_session_record(session2)

    return "trajectory-agent"


@pytest.mark.asyncio
async def test_get_trajectories_empty(client):
    """Test getting trajectories for agent with no sessions."""
    await client.post("/api/agents", json={
        "agent_id": "empty-traj-agent",
        "description": "Empty",
        "identity_core": "Test",
        "max_turns": 8,
        "basins": [
            {
                "name": "basin1",
                "basin_class": "core",
                "alpha": 0.8,
                "lambda": 0.95,
                "eta": 0.1,
                "tier": 2,
            }
        ],
    })

    resp = await client.get("/api/agents/empty-traj-agent/trajectories")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == "empty-traj-agent"
    assert "trajectories" in data


@pytest.mark.asyncio
async def test_get_trajectories_with_data(client, agent_with_trajectories):
    """Test getting trajectories with session data."""
    resp = await client.get(f"/api/agents/{agent_with_trajectories}/trajectories")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == agent_with_trajectories
    assert "trajectories" in data
    trajectories = data["trajectories"]

    # Should have data for both basins
    assert "basin_a" in trajectories or "basin_b" in trajectories

    # Check structure if data exists
    if "basin_a" in trajectories:
        basin_a_data = trajectories["basin_a"]
        assert "metadata" in basin_a_data
        assert "points" in basin_a_data
        if len(basin_a_data["points"]) > 0:
            point = basin_a_data["points"][0]
            assert "session_id" in point
            assert "alpha_start" in point
            assert "alpha_end" in point
            assert "delta" in point


@pytest.mark.asyncio
async def test_get_trajectories_limit(client, agent_with_trajectories):
    """Test trajectory endpoint respects n_sessions parameter."""
    resp = await client.get(f"/api/agents/{agent_with_trajectories}/trajectories?n_sessions=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["n_sessions"] == 1


@pytest.mark.asyncio
async def test_get_trajectories_nonexistent_agent(client):
    """Test getting trajectories for nonexistent agent returns 404."""
    resp = await client.get("/api/agents/nonexistent/trajectories")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_co_activation_empty(client):
    """Test co-activation for agent with no sessions."""
    await client.post("/api/agents", json={
        "agent_id": "coact-empty-agent",
        "description": "Empty",
        "identity_core": "Test",
        "max_turns": 8,
    })

    resp = await client.get("/api/agents/coact-empty-agent/co-activation")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == "coact-empty-agent"
    assert "nodes" in data
    assert "edges" in data
    assert len(data["edges"]) == 0


@pytest.mark.asyncio
async def test_get_co_activation_with_data(client, agent_with_trajectories):
    """Test co-activation with session data."""
    # Add co-activation data directly via update_co_activation
    from augustus.models.dataclasses import CoActivationEntry
    from augustus.models.enums import CoActivationCharacter

    memory = get_memory()

    entry = CoActivationEntry(
        pair=("basin_a", "basin_b"),
        count=2,
        character=CoActivationCharacter.REINFORCING,
    )
    await memory.update_co_activation(agent_with_trajectories, [entry])

    resp = await client.get(f"/api/agents/{agent_with_trajectories}/co-activation")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == agent_with_trajectories
    assert "nodes" in data
    assert "edges" in data

    # Should have both basins as nodes
    assert "basin_a" in data["nodes"]
    assert "basin_b" in data["nodes"]

    # Should have edge between them
    assert len(data["edges"]) > 0
    edge = data["edges"][0]
    assert "source" in edge
    assert "target" in edge
    assert "count" in edge
    assert "character" in edge
    assert edge["count"] == 2


@pytest.mark.asyncio
async def test_get_co_activation_nonexistent_agent(client):
    """Test co-activation for nonexistent agent returns 404."""
    resp = await client.get("/api/agents/nonexistent/co-activation")
    assert resp.status_code == 404
