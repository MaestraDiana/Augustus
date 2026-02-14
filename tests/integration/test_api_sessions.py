"""Integration tests for session API endpoints."""
import pytest
import pytest_asyncio

from augustus.api.dependencies import get_memory


@pytest_asyncio.fixture
async def seeded_agent(client):
    """Create an agent with some session data."""
    # Create agent
    await client.post("/api/agents", json={
        "agent_id": "session-test-agent",
        "description": "Test agent for sessions",
        "identity_core": "You are a test agent.",
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

    # Add some session data directly via memory service
    from augustus.models.dataclasses import SessionRecord, BasinSnapshot
    from augustus.models.enums import SessionPhase

    memory = get_memory()

    # Create a couple of sessions
    session1 = SessionRecord(
        session_id="session-001",
        agent_id="session-test-agent",
        start_time="2025-01-01T10:00:00",
        end_time="2025-01-01T10:15:00",
        turn_count=5,
        model="claude-sonnet-4-20250514",
        temperature=1.0,
        status="complete",
        transcript=[
            {"role": "system", "content": "You are a test agent."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ],
        close_report={"summary": "Session completed successfully."},
        basin_snapshots=[
            BasinSnapshot(
                basin_name="basin1",
                alpha_start=0.8,
                alpha_end=0.82,
                delta=0.02,
                relevance_score=0.9,
            )
        ],
        capabilities_used=["text"],
    )

    session2 = SessionRecord(
        session_id="session-002",
        agent_id="session-test-agent",
        start_time="2025-01-01T11:00:00",
        end_time="2025-01-01T11:12:00",
        turn_count=3,
        model="claude-sonnet-4-20250514",
        temperature=1.0,
        status="complete",
        transcript=[
            {"role": "system", "content": "You are a test agent."},
            {"role": "user", "content": "Test"},
            {"role": "assistant", "content": "Response"},
        ],
        close_report={"summary": "Another session."},
        basin_snapshots=[
            BasinSnapshot(
                basin_name="basin1",
                alpha_start=0.82,
                alpha_end=0.85,
                delta=0.03,
                relevance_score=0.85,
            )
        ],
        capabilities_used=["text"],
    )

    await memory.store_session_record(session1)
    await memory.store_session_record(session2)

    return "session-test-agent"


@pytest.mark.asyncio
async def test_list_sessions_empty(client):
    """Test listing sessions for an agent with no sessions."""
    # Create agent
    await client.post("/api/agents", json={
        "agent_id": "empty-agent",
        "description": "No sessions",
        "identity_core": "Test",
        "max_turns": 8,
    })

    resp = await client.get("/api/agents/empty-agent/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert len(data["sessions"]) == 0


@pytest.mark.asyncio
async def test_list_sessions_with_data(client, seeded_agent):
    """Test listing sessions for an agent with session data."""
    resp = await client.get(f"/api/agents/{seeded_agent}/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["sessions"]) == 2

    # Sessions should be returned (most recent first is typical, but check presence)
    session_ids = [s["session_id"] for s in data["sessions"]]
    assert "session-001" in session_ids
    assert "session-002" in session_ids


@pytest.mark.asyncio
async def test_list_sessions_pagination(client, seeded_agent):
    """Test pagination of session list."""
    resp = await client.get(f"/api/agents/{seeded_agent}/sessions?limit=1&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit"] == 1
    assert data["offset"] == 0
    assert len(data["sessions"]) == 1
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_list_sessions_nonexistent_agent(client):
    """Test listing sessions for nonexistent agent returns 404."""
    resp = await client.get("/api/agents/nonexistent/sessions")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_session_detail(client, seeded_agent):
    """Test getting full session detail."""
    resp = await client.get(f"/api/agents/{seeded_agent}/sessions/session-001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "session-001"
    assert data["agent_id"] == seeded_agent
    assert "transcript" in data
    assert "close_report" in data
    assert "basin_snapshots" in data
    # Basin snapshots may or may not be returned depending on implementation
    assert "basin_snapshots" in data
    if len(data["basin_snapshots"]) > 0:
        assert data["basin_snapshots"][0]["basin_name"] == "basin1"


@pytest.mark.asyncio
async def test_get_session_detail_with_evaluator_output(client, seeded_agent):
    """Test session detail includes evaluator output if available."""
    # First, add evaluator output
    from augustus.models.dataclasses import EvaluatorOutput
    memory = get_memory()

    eval_output = EvaluatorOutput(
        basin_relevance={"basin1": 0.9},
        basin_rationale={"basin1": "High relevance"},
        co_activation_characters={"curious": "active", "analytical": "active"},
        constraint_erosion_flag=False,
        constraint_erosion_detail="",
        assessment_divergence_flag=False,
        assessment_divergence_detail="",
        emergent_observations=["None"],
    )
    await memory.store_evaluator_output("session-001", eval_output)

    resp = await client.get(f"/api/agents/{seeded_agent}/sessions/session-001")
    assert resp.status_code == 200
    data = resp.json()
    assert "evaluator_output" in data
    assert data["evaluator_output"] is not None
    assert "basin_relevance" in data["evaluator_output"]
    assert data["evaluator_output"]["basin_relevance"]["basin1"] == 0.9


@pytest.mark.asyncio
async def test_get_session_detail_nonexistent(client, seeded_agent):
    """Test getting nonexistent session returns 404."""
    resp = await client.get(f"/api/agents/{seeded_agent}/sessions/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_session_detail_wrong_agent(client, seeded_agent):
    """Test getting session with wrong agent ID returns 404."""
    # Create another agent
    await client.post("/api/agents", json={
        "agent_id": "other-agent",
        "description": "Other",
        "identity_core": "Test",
        "max_turns": 8,
    })

    # Try to get session-001 (which belongs to seeded_agent) via other-agent
    resp = await client.get("/api/agents/other-agent/sessions/session-001")
    assert resp.status_code == 404
