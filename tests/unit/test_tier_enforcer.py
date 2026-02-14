"""Tests for Tier Enforcer — permission-based basin modification control."""
import pytest

from augustus.models.dataclasses import BasinConfig, TierSettings
from augustus.models.enums import BasinClass, TierLevel, ProposalStatus
from augustus.services.tier_enforcer import TierEnforcer


@pytest.mark.asyncio
async def test_tier_1_modification_always_blocked(memory_service):
    """Tier 1 modification should always be blocked."""
    enforcer = TierEnforcer(memory_service)

    current = [
        BasinConfig(name="tier1_basin", basin_class=BasinClass.CORE, alpha=0.85, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_1),
    ]
    proposed = [
        BasinConfig(name="tier1_basin", basin_class=BasinClass.CORE, alpha=0.85, lambda_=0.90, eta=0.02, tier=TierLevel.TIER_1),
    ]
    tier_settings = TierSettings()

    result = await enforcer.check_yaml_modifications(
        agent_id="test-agent",
        proposed_basins=proposed,
        current_basins=current,
        tier_settings=tier_settings,
    )

    assert len(result.blocked) == 1
    assert result.blocked[0].basin_name == "tier1_basin"
    assert len(result.proposals_created) == 1
    assert result.proposals_created[0].status == ProposalStatus.REJECTED


@pytest.mark.asyncio
async def test_tier_2_modification_creates_proposal(memory_service):
    """Tier 2 modification should create a proposal."""
    enforcer = TierEnforcer(memory_service)

    current = [
        BasinConfig(name="tier2_basin", basin_class=BasinClass.CORE, alpha=0.80, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
    ]
    proposed = [
        BasinConfig(name="tier2_basin", basin_class=BasinClass.CORE, alpha=0.80, lambda_=0.95, eta=0.05, tier=TierLevel.TIER_2),
    ]
    tier_settings = TierSettings(tier_2_auto_approve=False)

    result = await enforcer.check_yaml_modifications(
        agent_id="test-agent",
        proposed_basins=proposed,
        current_basins=current,
        tier_settings=tier_settings,
    )

    assert len(result.proposals_created) == 1
    assert result.proposals_created[0].tier == TierLevel.TIER_2
    assert result.proposals_created[0].status == ProposalStatus.PENDING


@pytest.mark.asyncio
async def test_tier_2_auto_approve_at_threshold(memory_service):
    """Tier 2 should auto-approve at threshold."""
    enforcer = TierEnforcer(memory_service)
    agent_id = "test-agent"
    basin_name = "tier2_basin"

    # Set up consecutive count at threshold - 1 via a pending proposal
    from augustus.models.dataclasses import TierProposal
    from augustus.models.enums import ProposalType
    prev_proposal = TierProposal(
        proposal_id="prev-prop",
        agent_id=agent_id,
        basin_name=basin_name,
        tier=TierLevel.TIER_2,
        proposal_type=ProposalType.MODIFY,
        status=ProposalStatus.PENDING,
        consecutive_count=4,
        created_at="2026-01-01T00:00:00",
    )
    await memory_service.store_tier_proposal(prev_proposal)

    current = [
        BasinConfig(name=basin_name, basin_class=BasinClass.CORE, alpha=0.80, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
    ]
    proposed = [
        BasinConfig(name=basin_name, basin_class=BasinClass.CORE, alpha=0.80, lambda_=0.95, eta=0.05, tier=TierLevel.TIER_2),
    ]
    tier_settings = TierSettings(tier_2_auto_approve=True, tier_2_threshold=5)

    result = await enforcer.check_yaml_modifications(
        agent_id=agent_id,
        proposed_basins=proposed,
        current_basins=current,
        tier_settings=tier_settings,
    )

    assert len(result.allowed) > 0
    assert any(b.name == basin_name for b in result.allowed)
    assert result.proposals_created[0].status == ProposalStatus.AUTO_APPROVED


@pytest.mark.asyncio
async def test_tier_2_auto_approve_disabled(memory_service):
    """Tier 2 with auto-approve disabled should always stay pending."""
    enforcer = TierEnforcer(memory_service)

    current = [
        BasinConfig(name="tier2_basin", basin_class=BasinClass.CORE, alpha=0.80, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
    ]
    proposed = [
        BasinConfig(name="tier2_basin", basin_class=BasinClass.CORE, alpha=0.80, lambda_=0.95, eta=0.05, tier=TierLevel.TIER_2),
    ]
    tier_settings = TierSettings(tier_2_auto_approve=False)

    result = await enforcer.check_yaml_modifications(
        agent_id="test-agent",
        proposed_basins=proposed,
        current_basins=current,
        tier_settings=tier_settings,
    )

    assert len(result.blocked) == 1
    assert result.proposals_created[0].status == ProposalStatus.PENDING


@pytest.mark.asyncio
async def test_tier_3_modification_always_allowed(memory_service):
    """Tier 3 modification should always be allowed."""
    enforcer = TierEnforcer(memory_service)

    current = [
        BasinConfig(name="tier3_basin", basin_class=BasinClass.PERIPHERAL, alpha=0.60, lambda_=0.90, eta=0.10, tier=TierLevel.TIER_3),
    ]
    proposed = [
        BasinConfig(name="tier3_basin", basin_class=BasinClass.PERIPHERAL, alpha=0.60, lambda_=0.85, eta=0.10, tier=TierLevel.TIER_3),
    ]
    tier_settings = TierSettings()

    result = await enforcer.check_yaml_modifications(
        agent_id="test-agent",
        proposed_basins=proposed,
        current_basins=current,
        tier_settings=tier_settings,
    )

    assert len(result.allowed) > 0
    assert any(b.name == "tier3_basin" for b in result.allowed)
    assert len(result.blocked) == 0


@pytest.mark.asyncio
async def test_tier_3_new_basin_with_emergence_enabled(memory_service):
    """Tier 3 new basin with emergence auto-approve should be allowed."""
    enforcer = TierEnforcer(memory_service)
    agent_id = "test-agent"
    basin_name = "new_basin"

    # Set consecutive count to meet emergence threshold via a pending proposal
    from augustus.models.dataclasses import TierProposal
    from augustus.models.enums import ProposalType
    prev_proposal = TierProposal(
        proposal_id="prev-emergence",
        agent_id=agent_id,
        basin_name=basin_name,
        tier=TierLevel.TIER_3,
        proposal_type=ProposalType.CREATE,
        status=ProposalStatus.PENDING,
        consecutive_count=3,
        created_at="2026-01-01T00:00:00",
    )
    await memory_service.store_tier_proposal(prev_proposal)

    current = []
    proposed = [
        BasinConfig(name=basin_name, basin_class=BasinClass.PERIPHERAL, alpha=0.50, lambda_=0.85, eta=0.15, tier=TierLevel.TIER_3),
    ]
    tier_settings = TierSettings(emergence_auto_approve=True, emergence_threshold=3)

    result = await enforcer.check_yaml_modifications(
        agent_id=agent_id,
        proposed_basins=proposed,
        current_basins=current,
        tier_settings=tier_settings,
    )

    assert len(result.allowed) > 0
    assert any(b.name == basin_name for b in result.allowed)


@pytest.mark.asyncio
async def test_tier_3_new_basin_with_emergence_disabled(memory_service):
    """Tier 3 new basin with emergence disabled should be blocked."""
    enforcer = TierEnforcer(memory_service)

    current = []
    proposed = [
        BasinConfig(name="new_basin", basin_class=BasinClass.PERIPHERAL, alpha=0.50, lambda_=0.85, eta=0.15, tier=TierLevel.TIER_3),
    ]
    tier_settings = TierSettings(emergence_auto_approve=False)

    result = await enforcer.check_yaml_modifications(
        agent_id="test-agent",
        proposed_basins=proposed,
        current_basins=current,
        tier_settings=tier_settings,
    )

    assert len(result.blocked) > 0
    assert any(c.basin_name == "new_basin" for c in result.blocked)


@pytest.mark.asyncio
async def test_detect_basin_additions(memory_service):
    """Test detection of basin additions."""
    enforcer = TierEnforcer(memory_service)

    current = [
        BasinConfig(name="existing", basin_class=BasinClass.CORE, alpha=0.80, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
    ]
    proposed = [
        BasinConfig(name="existing", basin_class=BasinClass.CORE, alpha=0.80, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
        BasinConfig(name="new_basin", basin_class=BasinClass.PERIPHERAL, alpha=0.60, lambda_=0.90, eta=0.10, tier=TierLevel.TIER_3),
    ]

    changes = enforcer.detect_basin_changes(proposed, current)

    assert len(changes) == 1
    assert changes[0].change_type == "create"
    assert changes[0].basin_name == "new_basin"


@pytest.mark.asyncio
async def test_detect_basin_removals(memory_service):
    """Test detection of basin removals."""
    enforcer = TierEnforcer(memory_service)

    current = [
        BasinConfig(name="to_remove", basin_class=BasinClass.PERIPHERAL, alpha=0.60, lambda_=0.90, eta=0.10, tier=TierLevel.TIER_3),
        BasinConfig(name="stays", basin_class=BasinClass.CORE, alpha=0.80, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
    ]
    proposed = [
        BasinConfig(name="stays", basin_class=BasinClass.CORE, alpha=0.80, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
    ]

    changes = enforcer.detect_basin_changes(proposed, current)

    assert len(changes) == 1
    assert changes[0].change_type == "prune"
    assert changes[0].basin_name == "to_remove"


@pytest.mark.asyncio
async def test_detect_basin_modifications(memory_service):
    """Test detection of basin structural modifications."""
    enforcer = TierEnforcer(memory_service)

    current = [
        BasinConfig(name="modified", basin_class=BasinClass.CORE, alpha=0.80, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
    ]
    proposed = [
        BasinConfig(name="modified", basin_class=BasinClass.PERIPHERAL, alpha=0.80, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
    ]

    changes = enforcer.detect_basin_changes(proposed, current)

    assert len(changes) == 1
    assert changes[0].change_type == "modify"
    assert changes[0].basin_name == "modified"


@pytest.mark.asyncio
async def test_no_changes_detected_for_identical_basins(memory_service):
    """Test that identical basins produce no changes."""
    enforcer = TierEnforcer(memory_service)

    basins = [
        BasinConfig(name="unchanged", basin_class=BasinClass.CORE, alpha=0.80, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
    ]

    changes = enforcer.detect_basin_changes(basins, basins)

    # Alpha changes are handled by handoff, not here
    assert len(changes) == 0


@pytest.mark.asyncio
async def test_multiple_tiers_mixed(memory_service):
    """Test multiple modifications across different tiers."""
    enforcer = TierEnforcer(memory_service)

    current = [
        BasinConfig(name="tier1", basin_class=BasinClass.CORE, alpha=0.85, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_1),
        BasinConfig(name="tier2", basin_class=BasinClass.CORE, alpha=0.80, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
        BasinConfig(name="tier3", basin_class=BasinClass.PERIPHERAL, alpha=0.60, lambda_=0.90, eta=0.10, tier=TierLevel.TIER_3),
    ]
    proposed = [
        BasinConfig(name="tier1", basin_class=BasinClass.PERIPHERAL, alpha=0.85, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_1),  # Modify T1 - blocked
        BasinConfig(name="tier2", basin_class=BasinClass.PERIPHERAL, alpha=0.80, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),  # Modify T2 - proposal
        BasinConfig(name="tier3", basin_class=BasinClass.CORE, alpha=0.60, lambda_=0.90, eta=0.10, tier=TierLevel.TIER_3),  # Modify T3 - allowed
    ]
    tier_settings = TierSettings(tier_2_auto_approve=False)

    result = await enforcer.check_yaml_modifications(
        agent_id="test-agent",
        proposed_basins=proposed,
        current_basins=current,
        tier_settings=tier_settings,
    )

    # Tier 1 blocked
    assert any(c.basin_name == "tier1" for c in result.blocked)
    # Tier 2 creates pending proposal
    tier2_proposal = next((p for p in result.proposals_created if p.basin_name == "tier2"), None)
    assert tier2_proposal is not None
    assert tier2_proposal.status == ProposalStatus.PENDING
    # Tier 3 allowed
    assert any(b.name == "tier3" for b in result.allowed)
