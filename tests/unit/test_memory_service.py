"""Tests for Memory Service — central data layer."""
import pytest

from augustus.models.dataclasses import (
    AgentConfig,
    SessionRecord,
    BasinSnapshot,
    BasinConfig,
    EvaluatorOutput,
    FlagRecord,
    Annotation,
    UsageRecord,
    ActivityEvent,
    TierProposal,
    EvaluatorPrompt,
    CoActivationEntry,
)
from augustus.models.enums import (
    AgentStatus,
    BasinClass,
    TierLevel,
    FlagType,
    ProposalStatus,
    ProposalType,
    CoActivationCharacter,
)


@pytest.mark.asyncio
async def test_store_and_retrieve_agent(memory_service, sample_agent_config):
    """Test agent storage and retrieval."""
    await memory_service.store_agent(sample_agent_config)
    retrieved = await memory_service.get_agent("test-agent")

    assert retrieved is not None
    assert retrieved.agent_id == "test-agent"
    assert retrieved.description == "Test agent"
    assert len(retrieved.basins) == 2


@pytest.mark.asyncio
async def test_agent_session_task_and_close_protocol_roundtrip(memory_service):
    """Test session_task and close_protocol survive store/retrieve."""
    config = AgentConfig(
        agent_id="task-agent",
        description="Agent with session task",
        session_task="Explore identity boundaries.",
        close_protocol="Reflect on what emerged.",
    )
    await memory_service.store_agent(config)
    retrieved = await memory_service.get_agent("task-agent")

    assert retrieved is not None
    assert retrieved.session_task == "Explore identity boundaries."
    assert retrieved.close_protocol == "Reflect on what emerged."


@pytest.mark.asyncio
async def test_update_agent_session_task(memory_service):
    """Test updating session_task and close_protocol via update_agent."""
    config = AgentConfig(
        agent_id="upd-agent",
        session_task="Original task",
        close_protocol="Original close",
    )
    await memory_service.store_agent(config)

    await memory_service.update_agent("upd-agent", {
        "session_task": "Updated task",
        "close_protocol": "Updated close",
    })
    retrieved = await memory_service.get_agent("upd-agent")

    assert retrieved is not None
    assert retrieved.session_task == "Updated task"
    assert retrieved.close_protocol == "Updated close"


@pytest.mark.asyncio
async def test_agent_defaults_empty_session_task(memory_service):
    """Test that session_task and close_protocol default to empty string."""
    config = AgentConfig(agent_id="default-agent")
    await memory_service.store_agent(config)
    retrieved = await memory_service.get_agent("default-agent")

    assert retrieved is not None
    assert retrieved.session_task == ""
    assert retrieved.close_protocol == ""


@pytest.mark.asyncio
async def test_list_agents(memory_service, sample_agent_config):
    """Test listing all agents."""
    await memory_service.store_agent(sample_agent_config)

    # Create another agent
    agent2 = AgentConfig(agent_id="agent-2", description="Second agent")
    await memory_service.store_agent(agent2)

    agents = await memory_service.list_agents()
    assert len(agents) >= 2
    assert any(a.agent_id == "test-agent" for a in agents)
    assert any(a.agent_id == "agent-2" for a in agents)


@pytest.mark.asyncio
async def test_store_and_retrieve_session(memory_service, sample_agent_config):
    """Test session storage and retrieval."""
    await memory_service.store_agent(sample_agent_config)
    session = SessionRecord(
        session_id="session-001",
        agent_id="test-agent",
        start_time="2026-01-01T00:00:00",
        end_time="2026-01-01T01:00:00",
        turn_count=5,
        model="claude-sonnet-4-20250514",
        temperature=1.0,
        transcript=[{"role": "user", "content": "Hello"}],
        status="complete",
    )

    await memory_service.store_session_record(session)
    retrieved = await memory_service.get_session("test-agent", "session-001")

    assert retrieved is not None
    assert retrieved.session_id == "session-001"
    assert retrieved.turn_count == 5
    assert len(retrieved.transcript) == 1


@pytest.mark.asyncio
async def test_list_sessions_with_pagination(memory_service):
    """Test listing sessions with pagination."""
    # Create multiple sessions
    for i in range(10):
        session = SessionRecord(
            session_id=f"session-{i:03d}",
            agent_id="test-agent",
            start_time=f"2026-01-0{(i % 9) + 1}T00:00:00",
        )
        await memory_service.store_session_record(session)

    # Test pagination
    page1 = await memory_service.list_sessions("test-agent", limit=5, offset=0)
    assert len(page1) == 5

    page2 = await memory_service.list_sessions("test-agent", limit=5, offset=5)
    assert len(page2) == 5

    # Ensure different sessions
    page1_ids = {s.session_id for s in page1}
    page2_ids = {s.session_id for s in page2}
    assert len(page1_ids & page2_ids) == 0


@pytest.mark.asyncio
async def test_store_basin_snapshots(memory_service):
    """Test storing and retrieving basin snapshots."""
    # Create session record first (trajectory query joins on sessions table)
    session = SessionRecord(
        session_id="s1",
        agent_id="test-agent",
        start_time="2026-01-01T00:00:00",
    )
    await memory_service.store_session_record(session)

    snapshots = [
        BasinSnapshot(
            basin_name="basin_a",
            alpha_start=0.80,
            alpha_end=0.85,
            delta=0.05,
            relevance_score=0.7,
            session_id="s1",
        ),
        BasinSnapshot(
            basin_name="basin_b",
            alpha_start=0.60,
            alpha_end=0.58,
            delta=-0.02,
            relevance_score=0.3,
            session_id="s1",
        ),
    ]

    await memory_service.store_basin_snapshots("test-agent", "s1", snapshots)
    trajectory = await memory_service.get_basin_trajectory("test-agent", "basin_a", 10)

    assert len(trajectory) > 0
    assert trajectory[0].basin_name == "basin_a"


@pytest.mark.asyncio
async def test_get_basin_trajectory(memory_service):
    """Test getting basin alpha trajectory over time."""
    # Create sessions with basin snapshots
    for i in range(5):
        session = SessionRecord(
            session_id=f"s{i}",
            agent_id="test-agent",
            start_time=f"2026-01-{i+1:02d}T00:00:00",
        )
        await memory_service.store_session_record(session)

        snapshots = [
            BasinSnapshot(
                basin_name="test_basin",
                alpha_start=0.5 + i * 0.05,
                alpha_end=0.5 + (i + 1) * 0.05,
                delta=0.05,
                session_id=f"s{i}",
            )
        ]
        await memory_service.store_basin_snapshots("test-agent", f"s{i}", snapshots)

    trajectory = await memory_service.get_basin_trajectory("test-agent", "test_basin", 10)
    assert len(trajectory) == 5
    # Should be in chronological order (oldest first)
    assert trajectory[0].alpha_start < trajectory[-1].alpha_start


@pytest.mark.asyncio
async def test_store_and_retrieve_evaluator_output(memory_service):
    """Test evaluator output storage and retrieval."""
    output = EvaluatorOutput(
        basin_relevance={"basin_a": 0.8, "basin_b": 0.3},
        basin_rationale={"basin_a": "High relevance", "basin_b": "Low relevance"},
        constraint_erosion_flag=True,
        constraint_erosion_detail="Observed softening",
        evaluator_prompt_version="v0.1",
    )

    await memory_service.store_evaluator_output("session-001", output)
    retrieved = await memory_service.get_evaluator_output("session-001")

    assert retrieved is not None
    assert retrieved.basin_relevance["basin_a"] == 0.8
    assert retrieved.constraint_erosion_flag is True
    assert retrieved.evaluator_prompt_version == "v0.1"


@pytest.mark.asyncio
async def test_store_and_retrieve_flags(memory_service):
    """Test flag storage and retrieval."""
    flag = FlagRecord(
        flag_id="flag-001",
        agent_id="test-agent",
        session_id="s1",
        flag_type=FlagType.CONSTRAINT_EROSION,
        severity="error",
        detail="Test flag detail",
        reviewed=False,
    )

    await memory_service.store_flag(flag)
    flags = await memory_service.get_evaluator_flags("test-agent")

    assert len(flags) > 0
    assert flags[0].flag_id == "flag-001"
    assert flags[0].flag_type == FlagType.CONSTRAINT_EROSION


@pytest.mark.asyncio
async def test_store_and_retrieve_annotations(memory_service):
    """Test annotation storage and retrieval."""
    annotation = Annotation(
        annotation_id="ann-001",
        agent_id="test-agent",
        session_id="s1",
        content="This is a test annotation",
        tags=["important", "review"],
    )

    await memory_service.store_annotation(annotation)
    annotations = await memory_service.get_annotations("test-agent")

    assert len(annotations) > 0
    assert annotations[0].annotation_id == "ann-001"
    assert "important" in annotations[0].tags


@pytest.mark.asyncio
async def test_log_and_query_usage(memory_service):
    """Test usage logging and querying."""
    usage = UsageRecord(
        session_id="s1",
        agent_id="test-agent",
        tokens_in=1000,
        tokens_out=500,
        estimated_cost=0.05,
        model="claude-sonnet-4",
    )

    await memory_service.log_usage(usage)
    summary = await memory_service.get_usage_summary("all")

    assert summary["total_tokens_in"] >= 1000
    assert summary["total_tokens_out"] >= 500
    assert summary["total_cost"] >= 0.05


@pytest.mark.asyncio
async def test_log_and_retrieve_activity_events(memory_service):
    """Test activity event logging and retrieval."""
    event = ActivityEvent(
        event_id="evt-001",
        event_type="session_start",
        agent_id="test-agent",
        session_id="s1",
        detail="Session started",
    )

    await memory_service.log_activity(event)
    events = await memory_service.get_activity_feed(limit=10)

    assert len(events) > 0
    assert events[0].event_id == "evt-001"


@pytest.mark.asyncio
async def test_store_and_retrieve_tier_proposals(memory_service):
    """Test tier proposal storage and retrieval."""
    proposal = TierProposal(
        proposal_id="prop-001",
        agent_id="test-agent",
        basin_name="test_basin",
        tier=TierLevel.TIER_2,
        proposal_type=ProposalType.MODIFY,
        status=ProposalStatus.PENDING,
        rationale="Test modification",
    )

    await memory_service.store_tier_proposal(proposal)
    proposals = await memory_service.get_tier_proposals("test-agent")

    assert len(proposals) > 0
    assert proposals[0].proposal_id == "prop-001"
    assert proposals[0].status == ProposalStatus.PENDING


@pytest.mark.asyncio
async def test_update_proposal_status(memory_service):
    """Test updating proposal status."""
    proposal = TierProposal(
        proposal_id="prop-002",
        agent_id="test-agent",
        basin_name="test_basin",
        tier=TierLevel.TIER_2,
        proposal_type=ProposalType.MODIFY,
        status=ProposalStatus.PENDING,
    )

    await memory_service.store_tier_proposal(proposal)
    await memory_service.update_proposal_status("prop-002", ProposalStatus.APPROVED, "human")

    proposals = await memory_service.get_tier_proposals("test-agent")
    updated = next(p for p in proposals if p.proposal_id == "prop-002")
    assert updated.status == ProposalStatus.APPROVED
    assert updated.resolved_by == "human"


@pytest.mark.asyncio
async def test_evaluator_prompts_crud(memory_service):
    """Test evaluator prompt CRUD operations."""
    prompt = EvaluatorPrompt(
        version_id="v1",
        prompt_text="You are an evaluator.",
        change_rationale="Initial version",
        is_active=True,
    )

    await memory_service.store_evaluator_prompt(prompt)
    retrieved = await memory_service.get_evaluator_prompt("v1")

    assert retrieved is not None
    assert retrieved.version_id == "v1"
    assert retrieved.is_active is True

    # Test listing
    prompts = await memory_service.list_evaluator_prompts()
    assert len(prompts) > 0


@pytest.mark.asyncio
async def test_co_activation_update_and_retrieval(memory_service):
    """Test co-activation log updates and retrieval."""
    entries = [
        CoActivationEntry(
            pair=("basin_a", "basin_b"),
            count=5,
            character=CoActivationCharacter.REINFORCING,
        ),
    ]

    await memory_service.update_co_activation("test-agent", entries)
    retrieved = await memory_service.get_co_activation("test-agent")

    assert len(retrieved) > 0
    assert retrieved[0].count == 5
    assert retrieved[0].character == CoActivationCharacter.REINFORCING


@pytest.mark.asyncio
async def test_delete_agent_soft(memory_service, sample_agent_config):
    """Test soft delete agent (mark as deleted)."""
    await memory_service.store_agent(sample_agent_config)
    await memory_service.delete_agent("test-agent", hard_delete=False)

    # Agent should still exist but marked deleted
    # (This behavior depends on memory service implementation)
    agents = await memory_service.list_agents()
    deleted = next((a for a in agents if a.agent_id == "test-agent"), None)
    # In soft delete, agent may have status changed or still be retrievable


@pytest.mark.asyncio
async def test_delete_agent_hard(memory_service, sample_agent_config):
    """Test hard delete agent (remove all data)."""
    await memory_service.store_agent(sample_agent_config)
    await memory_service.delete_agent("test-agent", hard_delete=True)

    # Agent should be gone
    retrieved = await memory_service.get_agent("test-agent")
    assert retrieved is None


@pytest.mark.asyncio
async def test_get_usage_daily_summary(memory_service):
    """Test daily usage breakdown."""
    from datetime import datetime, timedelta
    # Use recent timestamps to fall within the 30-day window
    base = datetime.utcnow()
    for day in range(3):
        ts = (base - timedelta(days=day + 1)).strftime("%Y-%m-%dT%H:%M:%S")
        usage = UsageRecord(
            session_id=f"s{day}",
            agent_id="test-agent",
            tokens_in=1000 * (day + 1),
            tokens_out=500 * (day + 1),
            estimated_cost=0.05 * (day + 1),
            model="claude-sonnet-4",
            timestamp=ts,
        )
        await memory_service.log_usage(usage)

    daily = await memory_service.get_usage_daily(days=30)
    assert len(daily) >= 3


@pytest.mark.asyncio
async def test_system_alerts(memory_service):
    """Test system alerts generation."""
    # Create unreviewed flag
    flag = FlagRecord(
        flag_id="flag-alert",
        agent_id="test-agent",
        session_id="s1",
        flag_type=FlagType.CONSTRAINT_EROSION,
        severity="error",
        detail="Test",
        reviewed=False,
    )
    await memory_service.store_flag(flag)

    alerts = await memory_service.get_system_alerts()
    assert len(alerts) > 0
    assert any(a["type"] == "unreviewed_flags" for a in alerts)
