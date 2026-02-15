"""Tests for Handoff Engine — basin parameter updates."""
import pytest

from augustus.models.dataclasses import (
    BasinConfig,
    EvaluatorOutput,
    CoActivationEntry,
)
from augustus.models.enums import BasinClass, TierLevel, EmphasisLevel, CoActivationCharacter
from augustus.services.handoff_engine import HandoffEngine


@pytest.fixture
def sample_basins():
    """Create sample basins for testing."""
    return [
        BasinConfig(
            name="basin_a",
            basin_class=BasinClass.CORE,
            alpha=0.85,
            lambda_=0.95,
            eta=0.02,
            tier=TierLevel.TIER_2,
        ),
        BasinConfig(
            name="basin_b",
            basin_class=BasinClass.PERIPHERAL,
            alpha=0.60,
            lambda_=0.90,
            eta=0.10,
            tier=TierLevel.TIER_3,
        ),
    ]


def test_apply_decay(handoff_engine):
    """Test decay formula: alpha_new = alpha * lambda."""
    basin = BasinConfig(
        name="test",
        basin_class=BasinClass.CORE,
        alpha=0.85,
        lambda_=0.95,
        eta=0.02,
        tier=TierLevel.TIER_2,
    )
    result = handoff_engine.apply_decay(basin)
    expected = 0.85 * 0.95
    assert abs(result - expected) < 0.0001  # 0.8075


def test_apply_boost_positive_relevance(handoff_engine):
    """Test boost with positive relevance score."""
    alpha = 0.80
    eta = 0.10
    relevance = 0.5
    result = handoff_engine.apply_boost(alpha, eta, relevance)
    expected = 0.80 + 0.10 * 0.5  # 0.85
    assert abs(result - expected) < 0.0001


def test_apply_boost_negative_relevance(handoff_engine):
    """Test boost with negative relevance score."""
    alpha = 0.70
    eta = 0.10
    relevance = -0.5
    result = handoff_engine.apply_boost(alpha, eta, relevance)
    expected = 0.70 + 0.10 * (-0.5)  # 0.65
    assert abs(result - expected) < 0.0001


def test_clamp_at_minimum(handoff_engine):
    """Test alpha clamp at 0.05 minimum."""
    result = handoff_engine.clamp_alpha(0.01)
    assert result == 0.05


def test_clamp_at_maximum(handoff_engine):
    """Test alpha clamp at 1.0 maximum."""
    result = handoff_engine.clamp_alpha(1.5)
    assert result == 1.0


def test_clamp_no_change(handoff_engine):
    """Test clamp leaves valid values unchanged."""
    result = handoff_engine.clamp_alpha(0.75)
    assert result == 0.75


def test_full_handoff_with_evaluator(handoff_engine, sample_basins):
    """Test complete handoff with evaluator output."""
    evaluator_output = EvaluatorOutput(
        basin_relevance={"basin_a": 0.3, "basin_b": -0.2},
    )

    result = handoff_engine.execute_handoff(
        basins=sample_basins,
        evaluator_output=evaluator_output,
        self_assessment=None,
        co_activation_entries=None,
    )

    assert len(result.updated_basins) == 2
    assert len(result.basin_snapshots) == 2
    assert result.emphasis_directive != ""
    assert "evaluator" in result.change_rationale.lower()

    # Check basin_a: decay to 0.8075, boost by 0.02 * 0.3 = 0.006, total 0.8135
    basin_a = next(b for b in result.updated_basins if b.name == "basin_a")
    expected_a = (0.85 * 0.95) + (0.02 * 0.3)
    assert abs(basin_a.alpha - expected_a) < 0.001

    # Check basin_b: decay to 0.54, boost by 0.10 * (-0.2) = -0.02, total 0.52
    basin_b = next(b for b in result.updated_basins if b.name == "basin_b")
    expected_b = (0.60 * 0.90) + (0.10 * (-0.2))
    assert abs(basin_b.alpha - expected_b) < 0.001


def test_full_handoff_with_self_assessment(handoff_engine, sample_basins):
    """Test handoff with self-assessment fallback (no evaluator)."""
    self_assessment = {"basin_a": 0.5, "basin_b": 0.2}

    result = handoff_engine.execute_handoff(
        basins=sample_basins,
        evaluator_output=None,
        self_assessment=self_assessment,
        co_activation_entries=None,
    )

    assert len(result.updated_basins) == 2
    assert "self_assessment" in result.change_rationale.lower()


def test_handoff_with_no_relevance(handoff_engine, sample_basins):
    """Test handoff with no relevance data (decay only)."""
    result = handoff_engine.execute_handoff(
        basins=sample_basins,
        evaluator_output=None,
        self_assessment=None,
        co_activation_entries=None,
    )

    # Decay only, no boost
    basin_a = next(b for b in result.updated_basins if b.name == "basin_a")
    expected_a = 0.85 * 0.95
    assert abs(basin_a.alpha - expected_a) < 0.001


def test_emphasis_level_thresholds(handoff_engine):
    """Test emphasis level mapping for each threshold."""
    assert handoff_engine.get_emphasis_level(0.95) == EmphasisLevel.STRONGLY_FOREGROUNDED
    assert handoff_engine.get_emphasis_level(0.80) == EmphasisLevel.STRONGLY_FOREGROUNDED
    assert handoff_engine.get_emphasis_level(0.75) == EmphasisLevel.ACTIVE
    assert handoff_engine.get_emphasis_level(0.60) == EmphasisLevel.ACTIVE
    assert handoff_engine.get_emphasis_level(0.50) == EmphasisLevel.AVAILABLE
    assert handoff_engine.get_emphasis_level(0.40) == EmphasisLevel.AVAILABLE
    assert handoff_engine.get_emphasis_level(0.30) == EmphasisLevel.BACKGROUNDED
    assert handoff_engine.get_emphasis_level(0.20) == EmphasisLevel.BACKGROUNDED
    assert handoff_engine.get_emphasis_level(0.10) == EmphasisLevel.LIGHTLY_PRESENT
    assert handoff_engine.get_emphasis_level(0.05) == EmphasisLevel.LIGHTLY_PRESENT


def test_generate_emphasis_directive_single_basin(handoff_engine):
    """Test emphasis directive generation with one basin."""
    basins = [
        BasinConfig(
            name="test_basin",
            basin_class=BasinClass.CORE,
            alpha=0.85,
            lambda_=0.95,
            eta=0.02,
            tier=TierLevel.TIER_2,
        ),
    ]
    directive = handoff_engine.generate_emphasis_directive(basins)
    assert "test basin" in directive.lower()
    assert "strongly foregrounded" in directive.lower()


def test_generate_emphasis_directive_multiple_levels(handoff_engine):
    """Test emphasis directive with basins at different levels."""
    basins = [
        BasinConfig(name="high_basin", basin_class=BasinClass.CORE, alpha=0.85, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
        BasinConfig(name="mid_basin", basin_class=BasinClass.PERIPHERAL, alpha=0.65, lambda_=0.90, eta=0.10, tier=TierLevel.TIER_3),
        BasinConfig(name="low_basin", basin_class=BasinClass.PERIPHERAL, alpha=0.15, lambda_=0.80, eta=0.15, tier=TierLevel.TIER_3),
    ]
    directive = handoff_engine.generate_emphasis_directive(basins)

    assert "high basin" in directive.lower()
    assert "mid basin" in directive.lower()
    assert "low basin" in directive.lower()
    # Verify sorting by alpha (high should come first)
    high_pos = directive.lower().find("high basin")
    low_pos = directive.lower().find("low basin")
    assert high_pos < low_pos


def test_compute_basin_deltas(handoff_engine):
    """Test basin delta computation."""
    before = [
        BasinConfig(name="basin_a", basin_class=BasinClass.CORE, alpha=0.80, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
        BasinConfig(name="basin_b", basin_class=BasinClass.PERIPHERAL, alpha=0.60, lambda_=0.90, eta=0.10, tier=TierLevel.TIER_3),
    ]
    after = [
        BasinConfig(name="basin_a", basin_class=BasinClass.CORE, alpha=0.82, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
        BasinConfig(name="basin_b", basin_class=BasinClass.PERIPHERAL, alpha=0.55, lambda_=0.90, eta=0.10, tier=TierLevel.TIER_3),
    ]
    relevance = {"basin_a": 0.5, "basin_b": -0.3}

    snapshots = handoff_engine.compute_basin_deltas(before, after, relevance)

    assert len(snapshots) == 2
    snapshot_a = next(s for s in snapshots if s.basin_name == "basin_a")
    snapshot_b = next(s for s in snapshots if s.basin_name == "basin_b")

    assert snapshot_a.alpha_start == 0.80
    assert snapshot_a.alpha_end == 0.82
    assert abs(snapshot_a.delta - 0.02) < 0.001
    assert snapshot_a.relevance_score == 0.5

    assert snapshot_b.alpha_start == 0.60
    assert snapshot_b.alpha_end == 0.55
    assert abs(snapshot_b.delta - (-0.05)) < 0.001
    assert snapshot_b.relevance_score == -0.3


def test_compute_basin_deltas_new_basin(handoff_engine):
    """Test that newly approved basins (in after but not before) get snapshots."""
    before = [
        BasinConfig(name="basin_a", basin_class=BasinClass.CORE, alpha=0.80, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
    ]
    after = [
        BasinConfig(name="basin_a", basin_class=BasinClass.CORE, alpha=0.82, lambda_=0.95, eta=0.02, tier=TierLevel.TIER_2),
        BasinConfig(name="basin_new", basin_class=BasinClass.PERIPHERAL, alpha=0.50, lambda_=0.90, eta=0.10, tier=TierLevel.TIER_3),
    ]
    relevance = {"basin_a": 0.5, "basin_new": 0.3}

    snapshots = handoff_engine.compute_basin_deltas(before, after, relevance)

    assert len(snapshots) == 2
    snapshot_new = next(s for s in snapshots if s.basin_name == "basin_new")
    assert snapshot_new.alpha_start == 0.50
    assert snapshot_new.alpha_end == 0.50
    assert snapshot_new.delta == 0.0
    assert snapshot_new.relevance_score == 0.3


def test_handoff_with_clamping(handoff_engine):
    """Test that handoff properly clamps extreme values."""
    basins = [
        BasinConfig(
            name="very_low",
            basin_class=BasinClass.PERIPHERAL,
            alpha=0.06,  # Will decay below minimum
            lambda_=0.50,
            eta=0.01,
            tier=TierLevel.TIER_3,
        ),
        BasinConfig(
            name="very_high",
            basin_class=BasinClass.CORE,
            alpha=0.98,
            lambda_=1.0,
            eta=0.10,
            tier=TierLevel.TIER_2,
        ),
    ]
    evaluator_output = EvaluatorOutput(
        basin_relevance={"very_low": -0.5, "very_high": 1.0},
    )

    result = handoff_engine.execute_handoff(
        basins=basins,
        evaluator_output=evaluator_output,
        self_assessment=None,
        co_activation_entries=None,
    )

    # very_low should be clamped at 0.05
    basin_low = next(b for b in result.updated_basins if b.name == "very_low")
    assert basin_low.alpha >= 0.05

    # very_high should be clamped at 1.0
    basin_high = next(b for b in result.updated_basins if b.name == "very_high")
    assert basin_high.alpha <= 1.0


def test_co_activation_entries_passthrough(handoff_engine, sample_basins):
    """Test that co-activation entries are passed through in result."""
    co_activation = [
        CoActivationEntry(
            pair=("basin_a", "basin_b"),
            count=5,
            character=CoActivationCharacter.REINFORCING,
        ),
    ]

    result = handoff_engine.execute_handoff(
        basins=sample_basins,
        evaluator_output=None,
        self_assessment=None,
        co_activation_entries=co_activation,
    )

    assert len(result.co_activation_updates) == 1
    assert result.co_activation_updates[0].count == 5
    assert result.co_activation_updates[0].character == CoActivationCharacter.REINFORCING


def test_emphasis_directive_empty_basins(handoff_engine):
    """Test emphasis directive with no basins."""
    directive = handoff_engine.generate_emphasis_directive([])
    assert "no basins" in directive.lower()


def test_handoff_includes_new_approved_basin(handoff_engine):
    """Test that a newly approved basin included in initial_basins gets
    full handoff treatment (decay, boost, clamp) and a snapshot."""
    basins = [
        BasinConfig(
            name="existing_basin",
            basin_class=BasinClass.CORE,
            alpha=0.85,
            lambda_=0.95,
            eta=0.02,
            tier=TierLevel.TIER_2,
        ),
        # Simulates a basin that was just approved and merged into
        # initial_basins before handoff (the fix for missing-basin bug).
        BasinConfig(
            name="newly_approved",
            basin_class=BasinClass.PERIPHERAL,
            alpha=0.30,
            lambda_=0.95,
            eta=0.10,
            tier=TierLevel.TIER_3,
        ),
    ]

    # Evaluator has no relevance score for the new basin (it wasn't in
    # the session's instruction framework).
    evaluator_output = EvaluatorOutput(
        basin_relevance={"existing_basin": 0.5},
    )

    result = handoff_engine.execute_handoff(
        basins=basins,
        evaluator_output=evaluator_output,
        self_assessment=None,
        co_activation_entries=None,
    )

    # Both basins should appear in updated_basins
    assert len(result.updated_basins) == 2
    names = {b.name for b in result.updated_basins}
    assert "newly_approved" in names

    # New basin gets decay: 0.30 * 0.95 = 0.285, no boost (relevance=0)
    new_basin = next(b for b in result.updated_basins if b.name == "newly_approved")
    expected_alpha = 0.30 * 0.95  # 0.285
    assert abs(new_basin.alpha - expected_alpha) < 0.001

    # Both basins should have snapshots
    assert len(result.basin_snapshots) == 2
    new_snap = next(s for s in result.basin_snapshots if s.basin_name == "newly_approved")
    assert new_snap.alpha_start == 0.30
    assert abs(new_snap.alpha_end - expected_alpha) < 0.001
    assert abs(new_snap.delta - (expected_alpha - 0.30)) < 0.001
    assert new_snap.relevance_score == 0.0  # No evaluator score for new basin

    # Emphasis directive should mention the new basin
    assert "newly approved" in result.emphasis_directive.lower()


def test_change_rationale_format(handoff_engine, sample_basins):
    """Test that change rationale includes deltas and relevance scores."""
    evaluator_output = EvaluatorOutput(
        basin_relevance={"basin_a": 0.8, "basin_b": 0.2},
    )

    result = handoff_engine.execute_handoff(
        basins=sample_basins,
        evaluator_output=evaluator_output,
        self_assessment=None,
        co_activation_entries=None,
    )

    rationale = result.change_rationale
    assert "basin_a" in rationale
    assert "basin_b" in rationale
    # Should include delta symbols and relevance
    assert any(symbol in rationale for symbol in ["↑", "↓", "→"])
    assert "rel=" in rationale.lower() or "relevance" in rationale.lower()
