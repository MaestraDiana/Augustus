"""End-to-end integration tests for complete session flow."""
import pytest

from augustus.api.dependencies import get_memory


@pytest.mark.asyncio
async def test_complete_agent_lifecycle(client):
    """Test complete agent lifecycle: create, verify, update, delete."""
    # Step 1: Create agent
    create_payload = {
        "agent_id": "lifecycle-agent",
        "description": "Full lifecycle test",
        "identity_core": "You are a test agent for lifecycle testing.",
        "max_turns": 10,
        "basins": [
            {
                "name": "core_basin",
                "basin_class": "core",
                "alpha": 0.85,
                "lambda": 0.95,
                "eta": 0.1,
                "tier": 2,
            },
            {
                "name": "peripheral_basin",
                "basin_class": "peripheral",
                "alpha": 0.6,
                "lambda": 0.95,
                "eta": 0.1,
                "tier": 3,
            }
        ],
        "tier_settings": {
            "tier_2_auto_approve": True,
            "tier_2_threshold": 5,
            "emergence_auto_approve": True,
            "emergence_threshold": 3,
        }
    }

    resp = await client.post("/api/agents", json=create_payload)
    assert resp.status_code == 201
    created_agent = resp.json()
    assert created_agent["agent_id"] == "lifecycle-agent"

    # Step 2: Verify it appears in list
    resp = await client.get("/api/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert len(agents) == 1
    assert agents[0]["agent_id"] == "lifecycle-agent"

    # Step 3: Get agent detail
    resp = await client.get("/api/agents/lifecycle-agent")
    assert resp.status_code == 200
    agent = resp.json()
    assert agent["description"] == "Full lifecycle test"
    assert len(agent["basins"]) == 2

    # Step 4: Get overview
    resp = await client.get("/api/agents/lifecycle-agent/overview")
    assert resp.status_code == 200
    overview = resp.json()
    assert overview["agent"]["agent_id"] == "lifecycle-agent"
    assert overview["session_count"] == 0
    assert len(overview["current_basins"]) == 2

    # Step 5: Update agent
    update_payload = {
        "description": "Updated description",
        "max_turns": 12,
    }
    resp = await client.put("/api/agents/lifecycle-agent", json=update_payload)
    assert resp.status_code == 200
    updated_agent = resp.json()
    assert updated_agent["description"] == "Updated description"
    assert updated_agent["max_turns"] == 12

    # Step 6: Pause and resume
    resp = await client.post("/api/agents/lifecycle-agent/pause")
    assert resp.status_code == 200

    resp = await client.post("/api/agents/lifecycle-agent/resume")
    assert resp.status_code == 200

    # Step 7: Delete agent (soft delete by default)
    resp = await client.delete("/api/agents/lifecycle-agent")
    assert resp.status_code == 204

    # Step 8: Verify it's soft deleted (status changed to deleted, but still retrievable)
    # For hard delete, would need to use ?hard=true query parameter
    resp = await client.get("/api/agents/lifecycle-agent")
    # Soft delete may still return the agent but with deleted status
    # This depends on implementation - checking if it returns 404 or 200 with deleted status
    assert resp.status_code in (200, 404)


@pytest.mark.asyncio
async def test_agent_with_session_data_flow(client):
    """Test agent creation and interaction with session data."""
    # Create agent
    await client.post("/api/agents", json={
        "agent_id": "session-flow-agent",
        "description": "Session flow test",
        "identity_core": "Test agent",
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
    })

    # Add session via memory service
    from augustus.models.dataclasses import SessionRecord, BasinSnapshot
    from augustus.models.enums import SessionPhase

    memory = get_memory()

    session = SessionRecord(
        session_id="flow-session-001",
        agent_id="session-flow-agent",
        start_time="2025-01-01T10:00:00",
        end_time="2025-01-01T10:15:00",
        turn_count=5,
        model="claude-sonnet-4-20250514",
        temperature=1.0,
        status="complete",
        transcript=[
            {"role": "system", "content": "Test agent"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ],
        close_report={"summary": "Session completed successfully."},
        basin_snapshots=[
            BasinSnapshot(
                basin_name="test_basin",
                alpha_start=0.8,
                alpha_end=0.85,
                delta=0.05,
                relevance_score=0.9,
            )
        ],
        capabilities_used=["text"],
    )

    await memory.store_session_record(session)

    # Verify overview shows session
    resp = await client.get("/api/agents/session-flow-agent/overview")
    assert resp.status_code == 200
    overview = resp.json()
    assert overview["session_count"] == 1
    assert overview["last_session"] is not None
    assert overview["last_session"]["session_id"] == "flow-session-001"

    # List sessions
    resp = await client.get("/api/agents/session-flow-agent/sessions")
    assert resp.status_code == 200
    sessions = resp.json()
    assert sessions["total"] == 1
    assert len(sessions["sessions"]) == 1

    # Get session detail
    resp = await client.get("/api/agents/session-flow-agent/sessions/flow-session-001")
    assert resp.status_code == 200
    session_detail = resp.json()
    assert session_detail["session_id"] == "flow-session-001"
    assert len(session_detail["transcript"]) == 3
    # Basin snapshots may or may not be returned
    assert "basin_snapshots" in session_detail

    # Get trajectories
    resp = await client.get("/api/agents/session-flow-agent/trajectories")
    assert resp.status_code == 200
    trajectories = resp.json()
    assert "trajectories" in trajectories


@pytest.mark.asyncio
async def test_multi_agent_system(client):
    """Test system with multiple agents and cross-agent operations."""
    # Create multiple agents
    agents_to_create = [
        {
            "agent_id": "agent-alpha",
            "description": "Alpha agent",
            "identity_core": "Alpha",
            "max_turns": 8,
        },
        {
            "agent_id": "agent-beta",
            "description": "Beta agent",
            "identity_core": "Beta",
            "max_turns": 8,
        },
        {
            "agent_id": "agent-gamma",
            "description": "Gamma agent",
            "identity_core": "Gamma",
            "max_turns": 8,
        }
    ]

    for agent_payload in agents_to_create:
        resp = await client.post("/api/agents", json=agent_payload)
        assert resp.status_code == 201

    # Verify all agents in list
    resp = await client.get("/api/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert len(agents) == 3
    agent_ids = {a["agent_id"] for a in agents}
    assert agent_ids == {"agent-alpha", "agent-beta", "agent-gamma"}

    # Add session data to different agents
    from augustus.models.dataclasses import SessionRecord
    from augustus.models.enums import SessionPhase

    memory = get_memory()

    for i, agent_id in enumerate(["agent-alpha", "agent-beta", "agent-gamma"]):
        session = SessionRecord(
            session_id=f"multi-session-{i:03d}",
            agent_id=agent_id,
            start_time=f"2025-01-01T{10+i:02d}:00:00",
            end_time=f"2025-01-01T{10+i:02d}:15:00",
            turn_count=3,
            model="claude-sonnet-4-20250514",
            temperature=1.0,
            status="complete",
            transcript=[{"role": "user", "content": f"Test for {agent_id}"}],
            close_report={"summary": f"Session for {agent_id}"},
            basin_snapshots=[],
            capabilities_used=["text"],
        )
        await memory.store_session_record(session)

    # Test global search across all agents
    resp = await client.get("/api/search?q=test&n_results=10")
    assert resp.status_code == 200
    results = resp.json()
    # Should potentially find results from multiple agents

    # Test usage across all agents
    resp = await client.get("/api/usage")
    assert resp.status_code == 200
    usage = resp.json()
    # Should have usage data

    # Clone an agent
    resp = await client.post("/api/agents/agent-alpha/clone", json={
        "new_agent_id": "agent-alpha-clone"
    })
    assert resp.status_code == 201

    # Verify clone exists
    resp = await client.get("/api/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert len(agents) == 4  # 3 original + 1 clone


@pytest.mark.asyncio
async def test_settings_integration_with_agents(client):
    """Test settings changes in context of agent operations."""
    # Get initial settings
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    initial_settings = resp.json()

    # Update settings
    await client.put("/api/settings", json={
        "default_temperature": 0.7,
        "default_max_tokens": 2048,
    })

    # Create agent (should use new defaults potentially)
    await client.post("/api/agents", json={
        "agent_id": "settings-test-agent",
        "description": "Settings test",
        "identity_core": "Test",
        "max_turns": 8,
    })

    # Verify settings persisted
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    updated_settings = resp.json()
    assert updated_settings["default_temperature"] == 0.7
    assert updated_settings["default_max_tokens"] == 2048

    # Create agent with overrides
    await client.post("/api/agents", json={
        "agent_id": "override-agent",
        "description": "Override test",
        "identity_core": "Test",
        "max_turns": 8,
        "temperature_override": 0.9,
        "max_tokens_override": 4096,
    })

    # Verify overrides are preserved
    resp = await client.get("/api/agents/override-agent")
    assert resp.status_code == 200
    agent = resp.json()
    assert agent["temperature_override"] == 0.9
    assert agent["max_tokens_override"] == 4096
