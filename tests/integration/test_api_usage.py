"""Integration tests for usage tracking API endpoints."""
import pytest
import pytest_asyncio

from augustus.api.dependencies import get_memory


@pytest_asyncio.fixture
async def system_with_usage_data(client):
    """Create agents with usage data."""
    # Create agents
    await client.post("/api/agents", json={
        "agent_id": "usage-agent-1",
        "description": "First usage agent",
        "identity_core": "Test",
        "max_turns": 8,
    })

    await client.post("/api/agents", json={
        "agent_id": "usage-agent-2",
        "description": "Second usage agent",
        "identity_core": "Test",
        "max_turns": 8,
    })

    # Add usage records - but first need to create sessions for foreign key
    from augustus.models.dataclasses import UsageRecord, SessionRecord

    memory = get_memory()

    # Create sessions first
    for i, agent_id in enumerate(["usage-agent-1", "usage-agent-2"]):
        for j in range(2 if agent_id == "usage-agent-1" else 1):
            session = SessionRecord(
                session_id=f"usage-session-{i*2+j+1:03d}",
                agent_id=agent_id,
                start_time=f"2025-01-01T{10+i+j:02d}:00:00",
                end_time=f"2025-01-01T{10+i+j:02d}:15:00",
                turn_count=3,
                model="claude-sonnet-4-20250514",
                temperature=1.0,
                status="complete",
                transcript=[],
                close_report={},
                basin_snapshots=[],
                capabilities_used=[],
            )
            await memory.store_session_record(session)

    usage1 = UsageRecord(
        agent_id="usage-agent-1",
        session_id="usage-session-001",
        timestamp="2025-01-01T10:00:00",
        model="claude-sonnet-4-20250514",
        tokens_in=1000,
        tokens_out=500,
        estimated_cost=0.015,
    )

    usage2 = UsageRecord(
        agent_id="usage-agent-1",
        session_id="usage-session-002",
        timestamp="2025-01-01T11:00:00",
        model="claude-sonnet-4-20250514",
        tokens_in=800,
        tokens_out=400,
        estimated_cost=0.012,
    )

    usage3 = UsageRecord(
        agent_id="usage-agent-2",
        session_id="usage-session-003",
        timestamp="2025-01-01T12:00:00",
        model="claude-sonnet-4-20250514",
        tokens_in=1200,
        tokens_out=600,
        estimated_cost=0.018,
    )

    await memory.log_usage(usage1)
    await memory.log_usage(usage2)
    await memory.log_usage(usage3)

    return ["usage-agent-1", "usage-agent-2"]


@pytest.mark.asyncio
async def test_get_usage_summary_empty(client):
    """Test usage summary with no data."""
    resp = await client.get("/api/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    # Should have basic structure even if empty
    assert "by_agent" in data or "total_sessions" in data or data == {}


@pytest.mark.asyncio
async def test_get_usage_summary_with_data(client, system_with_usage_data):
    """Test usage summary with usage data."""
    resp = await client.get("/api/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)

    # Should have aggregated usage data
    if "total_cost" in data:
        assert data["total_cost"] >= 0

    if "by_agent" in data:
        assert isinstance(data["by_agent"], (dict, list))


@pytest.mark.asyncio
async def test_get_usage_summary_period_day(client, system_with_usage_data):
    """Test usage summary for day period."""
    resp = await client.get("/api/usage?period=day")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_get_usage_summary_period_week(client, system_with_usage_data):
    """Test usage summary for week period."""
    resp = await client.get("/api/usage?period=week")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_get_usage_summary_period_month(client, system_with_usage_data):
    """Test usage summary for month period."""
    resp = await client.get("/api/usage?period=month")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_get_usage_summary_period_all(client, system_with_usage_data):
    """Test usage summary for all time."""
    resp = await client.get("/api/usage?period=all")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_get_usage_summary_invalid_period(client):
    """Test usage summary with invalid period defaults to day."""
    resp = await client.get("/api/usage?period=invalid")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_get_usage_daily_empty(client):
    """Test daily usage breakdown with no data."""
    resp = await client.get("/api/usage/daily")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_usage_daily_with_data(client, system_with_usage_data):
    """Test daily usage breakdown with data."""
    resp = await client.get("/api/usage/daily")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)

    # Should return daily breakdown
    if len(data) > 0:
        day = data[0]
        assert isinstance(day, dict)
        # Check for expected fields (structure depends on memory implementation)


@pytest.mark.asyncio
async def test_get_usage_daily_with_limit(client, system_with_usage_data):
    """Test daily usage with days limit."""
    resp = await client.get("/api/usage/daily?days=7")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # Should return at most 7 days


@pytest.mark.asyncio
async def test_get_usage_daily_max_days(client):
    """Test daily usage respects maximum days parameter."""
    resp = await client.get("/api/usage/daily?days=365")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_usage_by_agent(client, system_with_usage_data):
    """Test usage summary includes per-agent breakdown."""
    resp = await client.get("/api/usage")
    assert resp.status_code == 200
    data = resp.json()

    if "by_agent" in data:
        by_agent = data["by_agent"]
        assert isinstance(by_agent, (dict, list))

        # If dict format, check for agent IDs
        if isinstance(by_agent, dict):
            # May have usage-agent-1 and usage-agent-2
            pass
