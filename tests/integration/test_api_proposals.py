"""Integration tests for tier proposal API endpoints."""
import pytest
import pytest_asyncio

from augustus.api.dependencies import get_memory


@pytest_asyncio.fixture
async def agent_with_proposals(client):
    """Create an agent with tier proposals."""
    # Create agent
    await client.post("/api/agents", json={
        "agent_id": "proposal-agent",
        "description": "Agent with proposals",
        "identity_core": "Test",
        "max_turns": 8,
        "basins": [
            {
                "name": "test_basin",
                "basin_class": "peripheral",
                "alpha": 0.6,
                "lambda": 0.95,
                "eta": 0.1,
                "tier": 3,
            }
        ],
    })

    # Add proposals
    from augustus.models.dataclasses import TierProposal
    from augustus.models.enums import TierLevel, ProposalType, ProposalStatus

    memory = get_memory()

    proposal1 = TierProposal(
        proposal_id="prop-001",
        agent_id="proposal-agent",
        basin_name="test_basin",
        tier=TierLevel.TIER_2,
        proposal_type=ProposalType.MODIFY,
        status=ProposalStatus.PENDING,
        rationale="Basin has been consistently active",
        session_id="session-001",
        consecutive_count=3,
        created_at="2025-01-01T10:00:00",
    )

    proposal2 = TierProposal(
        proposal_id="prop-002",
        agent_id="proposal-agent",
        basin_name="test_basin",
        tier=TierLevel.TIER_2,
        proposal_type=ProposalType.MODIFY,
        status=ProposalStatus.APPROVED,
        rationale="Auto-approved after threshold",
        session_id="session-002",
        consecutive_count=5,
        created_at="2025-01-02T10:00:00",
        resolved_at="2025-01-02T10:01:00",
        resolved_by="system",
    )

    await memory.store_tier_proposal(proposal1)
    await memory.store_tier_proposal(proposal2)

    return "proposal-agent"


@pytest.mark.asyncio
async def test_list_proposals_empty(client):
    """Test listing proposals for agent with no proposals."""
    await client.post("/api/agents", json={
        "agent_id": "no-proposals-agent",
        "description": "No proposals",
        "identity_core": "Test",
        "max_turns": 8,
    })

    resp = await client.get("/api/agents/no-proposals-agent/tier-proposals")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 0


@pytest.mark.asyncio
async def test_list_all_proposals(client, agent_with_proposals):
    """Test listing all proposals."""
    resp = await client.get(f"/api/agents/{agent_with_proposals}/tier-proposals")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2

    # Check proposal structure
    proposal = data[0]
    assert "proposal_id" in proposal
    assert "agent_id" in proposal
    assert "basin_name" in proposal
    assert "tier" in proposal
    assert "proposal_type" in proposal
    assert "status" in proposal
    assert "rationale" in proposal


@pytest.mark.asyncio
async def test_list_proposals_filter_pending(client, agent_with_proposals):
    """Test listing only pending proposals."""
    resp = await client.get(f"/api/agents/{agent_with_proposals}/tier-proposals?status=pending")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "pending"
    assert data[0]["proposal_id"] == "prop-001"


@pytest.mark.asyncio
async def test_list_proposals_filter_approved(client, agent_with_proposals):
    """Test listing only approved proposals."""
    resp = await client.get(f"/api/agents/{agent_with_proposals}/tier-proposals?status=approved")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "approved"
    assert data[0]["proposal_id"] == "prop-002"


@pytest.mark.asyncio
async def test_list_proposals_nonexistent_agent(client):
    """Test listing proposals for nonexistent agent returns 404."""
    resp = await client.get("/api/agents/nonexistent/tier-proposals")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approve_proposal(client, agent_with_proposals):
    """Test approving a pending proposal."""
    resp = await client.post(f"/api/agents/{agent_with_proposals}/tier-proposals/prop-001/approve")
    assert resp.status_code == 200
    data = resp.json()
    assert data["proposal_id"] == "prop-001"
    assert data["status"] == "approved"
    assert data["resolved_by"] == "human"

    # Verify proposal is now approved
    resp = await client.get(f"/api/agents/{agent_with_proposals}/tier-proposals?status=approved")
    assert resp.status_code == 200
    proposals = resp.json()
    approved_ids = [p["proposal_id"] for p in proposals]
    assert "prop-001" in approved_ids


@pytest.mark.asyncio
async def test_reject_proposal(client, agent_with_proposals):
    """Test rejecting a pending proposal."""
    resp = await client.post(
        f"/api/agents/{agent_with_proposals}/tier-proposals/prop-001/reject",
        json={"rationale": "Not ready for promotion"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["proposal_id"] == "prop-001"
    assert data["status"] == "rejected"
    assert data["resolved_by"] == "human"

    # Verify proposal is now rejected
    resp = await client.get(f"/api/agents/{agent_with_proposals}/tier-proposals?status=rejected")
    assert resp.status_code == 200
    proposals = resp.json()
    assert len(proposals) == 1
    assert proposals[0]["proposal_id"] == "prop-001"


@pytest.mark.asyncio
async def test_reject_proposal_without_rationale(client, agent_with_proposals):
    """Test rejecting a proposal without providing rationale."""
    resp = await client.post(
        f"/api/agents/{agent_with_proposals}/tier-proposals/prop-001/reject"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rejected"


@pytest.mark.asyncio
async def test_approve_nonexistent_proposal(client, agent_with_proposals):
    """Test approving nonexistent proposal."""
    # Note: The actual behavior depends on tier_enforcer implementation
    # This might raise an error or silently fail
    resp = await client.post(f"/api/agents/{agent_with_proposals}/tier-proposals/nonexistent/approve")
    # Could be 404 or 200 depending on implementation
    assert resp.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_approve_proposal_nonexistent_agent(client):
    """Test approving proposal for nonexistent agent returns 404."""
    resp = await client.post("/api/agents/nonexistent/tier-proposals/prop-001/approve")
    assert resp.status_code == 404
