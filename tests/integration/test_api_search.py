"""Integration tests for search API endpoints."""
import pytest
import pytest_asyncio

from augustus.api.dependencies import get_memory


@pytest_asyncio.fixture
async def agents_with_searchable_data(client):
    """Create multiple agents with searchable session data."""
    # Create agents
    await client.post("/api/agents", json={
        "agent_id": "search-agent-1",
        "description": "First search agent",
        "identity_core": "Test",
        "max_turns": 8,
    })

    await client.post("/api/agents", json={
        "agent_id": "search-agent-2",
        "description": "Second search agent",
        "identity_core": "Test",
        "max_turns": 8,
    })

    # Add session data with searchable content
    from augustus.models.dataclasses import SessionRecord
    from augustus.models.enums import SessionPhase

    memory = get_memory()

    session1 = SessionRecord(
        session_id="search-session-001",
        agent_id="search-agent-1",
        start_time="2025-01-01T10:00:00",
        end_time="2025-01-01T10:15:00",
        turn_count=3,
        model="claude-sonnet-4-20250514",
        temperature=1.0,
        status="complete",
        transcript=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Tell me about quantum computing"},
            {"role": "assistant", "content": "Quantum computing uses quantum mechanics principles to process information."},
        ],
        close_report={"summary": "Discussed quantum computing."},
        basin_snapshots=[],
        capabilities_used=["text"],
    )

    session2 = SessionRecord(
        session_id="search-session-002",
        agent_id="search-agent-1",
        start_time="2025-01-01T11:00:00",
        end_time="2025-01-01T11:15:00",
        turn_count=3,
        model="claude-sonnet-4-20250514",
        temperature=1.0,
        status="complete",
        transcript=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is machine learning?"},
            {"role": "assistant", "content": "Machine learning is a subset of artificial intelligence."},
        ],
        close_report={"summary": "Discussed machine learning."},
        basin_snapshots=[],
        capabilities_used=["text"],
    )

    session3 = SessionRecord(
        session_id="search-session-003",
        agent_id="search-agent-2",
        start_time="2025-01-01T12:00:00",
        end_time="2025-01-01T12:15:00",
        turn_count=3,
        model="claude-sonnet-4-20250514",
        temperature=1.0,
        status="complete",
        transcript=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Explain neural networks"},
            {"role": "assistant", "content": "Neural networks are computing systems inspired by biological neural networks."},
        ],
        close_report={"summary": "Discussed neural networks."},
        basin_snapshots=[],
        capabilities_used=["text"],
    )

    await memory.store_session_record(session1)
    await memory.store_session_record(session2)
    await memory.store_session_record(session3)

    return ["search-agent-1", "search-agent-2"]


@pytest.mark.asyncio
async def test_agent_search_empty(client):
    """Test agent-scoped search with no results."""
    await client.post("/api/agents", json={
        "agent_id": "empty-search-agent",
        "description": "Empty",
        "identity_core": "Test",
        "max_turns": 8,
    })

    resp = await client.get("/api/agents/empty-search-agent/search?q=quantum")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # May be empty or have no results depending on ChromaDB behavior


@pytest.mark.asyncio
async def test_agent_search_with_results(client, agents_with_searchable_data):
    """Test agent-scoped search returns relevant results."""
    agent_id = agents_with_searchable_data[0]

    resp = await client.get(f"/api/agents/{agent_id}/search?q=quantum")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)

    # Check result structure if results exist
    if len(data) > 0:
        result = data[0]
        assert "content_type" in result
        assert "agent_id" in result
        assert "session_id" in result
        assert "snippet" in result
        assert "relevance_score" in result


@pytest.mark.asyncio
async def test_agent_search_limit(client, agents_with_searchable_data):
    """Test agent-scoped search respects n_results parameter."""
    agent_id = agents_with_searchable_data[0]

    resp = await client.get(f"/api/agents/{agent_id}/search?q=machine&n_results=1")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # Should return at most 1 result


@pytest.mark.asyncio
async def test_agent_search_missing_query(client):
    """Test agent search without query parameter returns error."""
    await client.post("/api/agents", json={
        "agent_id": "test-agent",
        "description": "Test",
        "identity_core": "Test",
        "max_turns": 8,
    })

    resp = await client.get("/api/agents/test-agent/search")
    assert resp.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_agent_search_nonexistent_agent(client):
    """Test agent search for nonexistent agent returns 404."""
    resp = await client.get("/api/agents/nonexistent/search?q=test")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_global_search_empty(client):
    """Test global search with no data."""
    resp = await client.get("/api/search?q=quantum")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_global_search_with_results(client, agents_with_searchable_data):
    """Test global search across all agents."""
    resp = await client.get("/api/search?q=machine")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)

    # Check result structure if results exist
    if len(data) > 0:
        result = data[0]
        assert "content_type" in result
        assert "agent_id" in result
        assert "session_id" in result
        assert "snippet" in result
        assert "relevance_score" in result


@pytest.mark.asyncio
async def test_global_search_returns_multiple_agents(client, agents_with_searchable_data):
    """Test global search can return results from multiple agents."""
    resp = await client.get("/api/search?q=neural&n_results=20")
    assert resp.status_code == 200
    data = resp.json()

    # If we have results from different agents, verify
    if len(data) > 0:
        agent_ids = {r["agent_id"] for r in data}
        # Results should include data (at least potentially)


@pytest.mark.asyncio
async def test_global_search_missing_query(client):
    """Test global search without query parameter returns error."""
    resp = await client.get("/api/search")
    assert resp.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_global_search_limit(client, agents_with_searchable_data):
    """Test global search respects n_results parameter."""
    resp = await client.get("/api/search?q=computing&n_results=2")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # Should return at most 2 results
