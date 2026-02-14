"""Tests for Augustus data models."""
import pytest

from augustus.models.dataclasses import (
    AgentConfig,
    BasinConfig,
    BasinSnapshot,
    SessionRecord,
    TierProposal,
    TierSettings,
    EvaluatorOutput,
)
from augustus.models.enums import (
    AgentStatus,
    BasinClass,
    TierLevel,
    ProposalStatus,
    ProposalType,
    FlagType,
    CoActivationCharacter,
    EmphasisLevel,
)


def test_basin_config_creation():
    """Test BasinConfig dataclass creation with valid values."""
    basin = BasinConfig(
        name="test_basin",
        basin_class=BasinClass.CORE,
        alpha=0.85,
        lambda_=0.95,
        eta=0.02,
        tier=TierLevel.TIER_2,
    )
    assert basin.name == "test_basin"
    assert basin.basin_class == BasinClass.CORE
    assert basin.alpha == 0.85
    assert basin.lambda_ == 0.95
    assert basin.eta == 0.02
    assert basin.tier == TierLevel.TIER_2


def test_basin_config_defaults():
    """Test BasinConfig with minimal required fields."""
    basin = BasinConfig(
        name="minimal",
        basin_class=BasinClass.PERIPHERAL,
        alpha=0.5,
        lambda_=0.9,
        eta=0.1,
        tier=TierLevel.TIER_3,
    )
    assert basin.name == "minimal"
    assert basin.alpha == 0.5


def test_agent_config_creation():
    """Test AgentConfig dataclass creation."""
    config = AgentConfig(
        agent_id="test-agent",
        description="Test agent description",
        status=AgentStatus.IDLE,
        max_turns=8,
        identity_core="You are a test agent.",
    )
    assert config.agent_id == "test-agent"
    assert config.description == "Test agent description"
    assert config.status == AgentStatus.IDLE
    assert config.max_turns == 8
    assert config.identity_core == "You are a test agent."


def test_agent_config_with_basins():
    """Test AgentConfig with basins list."""
    basins = [
        BasinConfig(
            name="basin1",
            basin_class=BasinClass.CORE,
            alpha=0.8,
            lambda_=0.95,
            eta=0.05,
            tier=TierLevel.TIER_2,
        ),
        BasinConfig(
            name="basin2",
            basin_class=BasinClass.PERIPHERAL,
            alpha=0.6,
            lambda_=0.9,
            eta=0.1,
            tier=TierLevel.TIER_3,
        ),
    ]
    config = AgentConfig(
        agent_id="test",
        basins=basins,
    )
    assert len(config.basins) == 2
    assert config.basins[0].name == "basin1"
    assert config.basins[1].name == "basin2"


def test_session_record_creation():
    """Test SessionRecord with transcript list."""
    transcript = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]
    session = SessionRecord(
        session_id="session-001",
        agent_id="test-agent",
        start_time="2026-01-01T00:00:00",
        transcript=transcript,
    )
    assert session.session_id == "session-001"
    assert session.agent_id == "test-agent"
    assert len(session.transcript) == 2
    assert session.transcript[0]["role"] == "user"


def test_session_record_defaults():
    """Test SessionRecord default values."""
    session = SessionRecord(
        session_id="s1",
        agent_id="a1",
        start_time="2026-01-01T00:00:00",
    )
    assert session.end_time == ""
    assert session.turn_count == 0
    assert session.temperature == 1.0
    assert session.transcript == []
    assert session.close_report is None
    assert session.basin_snapshots == []
    assert session.status == "complete"


def test_tier_proposal_creation():
    """Test TierProposal status transitions."""
    proposal = TierProposal(
        proposal_id="prop-001",
        agent_id="test-agent",
        basin_name="test_basin",
        tier=TierLevel.TIER_2,
        proposal_type=ProposalType.MODIFY,
        status=ProposalStatus.PENDING,
    )
    assert proposal.status == ProposalStatus.PENDING
    assert proposal.tier == TierLevel.TIER_2
    assert proposal.proposal_type == ProposalType.MODIFY


def test_tier_proposal_status_transitions():
    """Test different proposal statuses."""
    statuses = [
        ProposalStatus.PENDING,
        ProposalStatus.APPROVED,
        ProposalStatus.AUTO_APPROVED,
        ProposalStatus.REJECTED,
        ProposalStatus.EXPIRED,
    ]
    for status in statuses:
        proposal = TierProposal(
            proposal_id="prop-test",
            agent_id="agent",
            basin_name="basin",
            tier=TierLevel.TIER_3,
            proposal_type=ProposalType.CREATE,
            status=status,
        )
        assert proposal.status == status


def test_tier_settings_defaults():
    """Test TierSettings default values."""
    settings = TierSettings()
    assert settings.tier_2_auto_approve is True
    assert settings.tier_2_threshold == 5
    assert settings.emergence_auto_approve is True
    assert settings.emergence_threshold == 3


def test_tier_settings_custom_values():
    """Test TierSettings with custom values."""
    settings = TierSettings(
        tier_2_auto_approve=False,
        tier_2_threshold=10,
        emergence_auto_approve=False,
        emergence_threshold=7,
    )
    assert settings.tier_2_auto_approve is False
    assert settings.tier_2_threshold == 10
    assert settings.emergence_auto_approve is False
    assert settings.emergence_threshold == 7


def test_enum_values():
    """Test all enum values are accessible."""
    assert AgentStatus.ACTIVE.value == "active"
    assert AgentStatus.PAUSED.value == "paused"
    assert AgentStatus.ERROR.value == "error"
    assert AgentStatus.IDLE.value == "idle"

    assert BasinClass.CORE.value == "core"
    assert BasinClass.PERIPHERAL.value == "peripheral"

    assert TierLevel.TIER_1.value == 1
    assert TierLevel.TIER_2.value == 2
    assert TierLevel.TIER_3.value == 3


def test_basin_snapshot_creation():
    """Test BasinSnapshot with delta calculation."""
    snapshot = BasinSnapshot(
        basin_name="test",
        alpha_start=0.85,
        alpha_end=0.87,
        delta=0.02,
        relevance_score=0.5,
        session_id="s1",
    )
    assert snapshot.basin_name == "test"
    assert snapshot.alpha_start == 0.85
    assert snapshot.alpha_end == 0.87
    assert snapshot.delta == 0.02
    assert snapshot.relevance_score == 0.5


def test_evaluator_output_defaults():
    """Test EvaluatorOutput with default empty values."""
    output = EvaluatorOutput()
    assert output.basin_relevance == {}
    assert output.basin_rationale == {}
    assert output.co_activation_characters == {}
    assert output.constraint_erosion_flag is False
    assert output.constraint_erosion_detail is None
    assert output.assessment_divergence_flag is False
    assert output.assessment_divergence_detail is None
    assert output.emergent_observations == []


def test_evaluator_output_with_data():
    """Test EvaluatorOutput with populated data."""
    output = EvaluatorOutput(
        basin_relevance={"basin_a": 0.8, "basin_b": 0.3},
        basin_rationale={"basin_a": "High engagement", "basin_b": "Low relevance"},
        constraint_erosion_flag=True,
        constraint_erosion_detail="Observed softening of constraints",
    )
    assert output.basin_relevance["basin_a"] == 0.8
    assert output.basin_rationale["basin_a"] == "High engagement"
    assert output.constraint_erosion_flag is True
    assert output.constraint_erosion_detail == "Observed softening of constraints"


def test_flag_type_enum():
    """Test FlagType enum values."""
    assert FlagType.CONSTRAINT_EROSION.value == "constraint_erosion"
    assert FlagType.ASSESSMENT_DIVERGENCE.value == "assessment_divergence"
    assert FlagType.EMERGENT_OBSERVATION.value == "emergent_observation"


def test_co_activation_character_enum():
    """Test CoActivationCharacter enum values."""
    assert CoActivationCharacter.REINFORCING.value == "reinforcing"
    assert CoActivationCharacter.TENSIONAL.value == "tensional"
    assert CoActivationCharacter.SERVING.value == "serving"
    assert CoActivationCharacter.COMPETING.value == "competing"
    assert CoActivationCharacter.UNCHARACTERIZED.value == "uncharacterized"


def test_emphasis_level_enum():
    """Test EmphasisLevel enum values."""
    assert EmphasisLevel.STRONGLY_FOREGROUNDED.value == "strongly_foregrounded"
    assert EmphasisLevel.ACTIVE.value == "active"
    assert EmphasisLevel.AVAILABLE.value == "available"
    assert EmphasisLevel.BACKGROUNDED.value == "backgrounded"
    assert EmphasisLevel.LIGHTLY_PRESENT.value == "lightly_present"
