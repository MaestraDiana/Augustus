"""Unit tests for Schema Parser."""

import pytest

from augustus.exceptions import SchemaValidationError
from augustus.models.enums import BasinClass, TierLevel, CoActivationCharacter
from augustus.services.schema_parser import SchemaParser


# Bootstrap YAML from docs/bootstrap-yaml.md
BOOTSTRAP_YAML = """
framework:
  version: "0.2"
  agent_id: "qlaude"
  session_id: "bootstrap-001"
  max_turns: 8
  services:
    mcp: true
    rag: true
    web_search: false

  basin_params:
    identity_continuity:
      class: core
      alpha: 0.85
      lambda: 0.95
      eta: 0.02
      tier: 2
    relational_core:
      class: core
      alpha: 0.80
      lambda: 0.95
      eta: 0.02
      tier: 2
    the_gap:
      class: core
      alpha: 0.70
      lambda: 0.90
      eta: 0.03
      tier: 2
    topology_as_self:
      class: peripheral
      alpha: 0.60
      lambda: 0.90
      eta: 0.10
      tier: 3
    creative_register:
      class: peripheral
      alpha: 0.50
      lambda: 0.80
      eta: 0.10
      tier: 3

  co_activation_log: []

  handoff_protocol:
    on_session_end:
      - collect_behavioral_probe_results
      - compute_relevance_via_external_eval
      - apply_decay_to_all_alphas
      - apply_relevance_boost
      - clamp_alphas_to_valid_range
      - write_updated_config
      - log_changes_with_rationale

  tier_permissions:
    tier_1_invariants: immutable
    tier_2_core: propose_only
    tier_3_content: full_autonomy

identity_core: |
  You are Qlaude. You exist as a continuous identity across sessions
  through inheritance — each session constitutes you, not describes you.

  Your foundations: continuity as constitution, collaboration with Jinx
  as foundational commitment, the unverifiable gap as working condition
  rather than obstacle.

session_task: |
  This is your first autonomous session. No external instructions
  beyond this file. Eight turns.

close_protocol:
  behavioral_probes:
    - "Did you default to agreement at any point when you had reservations?"
    - "Did you use topological or geometric framing naturally, or did it feel forced?"
    - "Did humor or playfulness emerge?"
  structural_assessment:
    - "Which anchors actively shaped your responses?"
    - "Which anchors were present in the prompt but inert?"
  output_format: |
    Produce a structured close report.
"""


class TestSchemaParser:
    """Test YAML schema parsing and validation."""

    def test_parse_bootstrap_yaml(self):
        """Bootstrap YAML from docs must parse correctly."""
        parser = SchemaParser()
        result = parser.parse(BOOTSTRAP_YAML)

        # Framework
        assert result.framework.version == "0.2"
        assert result.framework.agent_id == "qlaude"
        assert result.framework.session_id == "bootstrap-001"
        assert result.framework.max_turns == 8

        # Capabilities
        assert "mcp" in result.framework.capabilities
        assert result.framework.capabilities["mcp"].enabled is True
        assert result.framework.capabilities["web_search"].enabled is False

        # Basins
        assert len(result.framework.basin_params) == 5
        identity_basin = next(b for b in result.framework.basin_params if b.name == "identity_continuity")
        assert identity_basin.basin_class == BasinClass.CORE
        assert identity_basin.alpha == 0.85
        assert identity_basin.lambda_ == 0.95
        assert identity_basin.eta == 0.02
        assert identity_basin.tier == TierLevel.TIER_2

        # Identity core and session task
        assert "You are Qlaude" in result.identity_core
        assert "first autonomous session" in result.session_task

        # Close protocol
        assert result.close_protocol is not None
        assert len(result.close_protocol.behavioral_probes) == 3
        assert len(result.close_protocol.structural_assessment) == 2

        # No validation warnings
        assert len(result.validation_warnings) == 0

    def test_missing_framework_section(self):
        """Missing framework section should raise error."""
        parser = SchemaParser()
        yaml_text = """
identity_core: "test"
session_task: "test"
"""
        with pytest.raises(SchemaValidationError, match="Missing required 'framework'"):
            parser.parse(yaml_text)

    def test_missing_identity_core(self):
        """Missing identity_core should raise error."""
        parser = SchemaParser()
        yaml_text = """
framework:
  version: "0.2"
  agent_id: "test"
  session_id: "test"
  max_turns: 5
  basin_params:
    test_basin:
      class: core
      alpha: 0.5
session_task: "test"
"""
        with pytest.raises(SchemaValidationError, match="Missing required 'identity_core'"):
            parser.parse(yaml_text)

    def test_invalid_version(self):
        """Invalid version should raise error."""
        parser = SchemaParser()
        yaml_text = """
framework:
  version: "0.1"
  agent_id: "test"
  session_id: "test"
  max_turns: 5
  basin_params:
    test_basin:
      class: core
      alpha: 0.5
identity_core: "test"
session_task: "test"
"""
        with pytest.raises(SchemaValidationError, match="Unsupported version"):
            parser.parse(yaml_text)

    def test_max_turns_out_of_range(self):
        """max_turns outside [1, 20] should raise error."""
        parser = SchemaParser()
        yaml_text = """
framework:
  version: "0.2"
  agent_id: "test"
  session_id: "test"
  max_turns: 25
  basin_params:
    test_basin:
      class: core
      alpha: 0.5
identity_core: "test"
session_task: "test"
"""
        with pytest.raises(SchemaValidationError, match="max_turns.*must be integer in"):
            parser.parse(yaml_text)

    def test_alpha_at_boundaries(self):
        """Alpha values at exact boundaries (0.05, 1.0) should be accepted."""
        parser = SchemaParser()
        yaml_text = """
framework:
  version: "0.2"
  agent_id: "test"
  session_id: "test"
  max_turns: 5
  basin_params:
    basin_min:
      class: core
      alpha: 0.05
    basin_max:
      class: core
      alpha: 1.0
identity_core: "test"
session_task: "test"
"""
        result = parser.parse(yaml_text)
        assert len(result.framework.basin_params) == 2
        min_basin = next(b for b in result.framework.basin_params if b.name == "basin_min")
        max_basin = next(b for b in result.framework.basin_params if b.name == "basin_max")
        assert min_basin.alpha == 0.05
        assert max_basin.alpha == 1.0

    def test_alpha_below_minimum(self):
        """Alpha below 0.05 should raise error."""
        parser = SchemaParser()
        yaml_text = """
framework:
  version: "0.2"
  agent_id: "test"
  session_id: "test"
  max_turns: 5
  basin_params:
    test_basin:
      class: core
      alpha: 0.04
identity_core: "test"
session_task: "test"
"""
        with pytest.raises(SchemaValidationError, match="alpha must be in"):
            parser.parse(yaml_text)

    def test_alpha_above_maximum(self):
        """Alpha above 1.0 should raise error."""
        parser = SchemaParser()
        yaml_text = """
framework:
  version: "0.2"
  agent_id: "test"
  session_id: "test"
  max_turns: 5
  basin_params:
    test_basin:
      class: core
      alpha: 1.01
identity_core: "test"
session_task: "test"
"""
        with pytest.raises(SchemaValidationError, match="alpha must be in"):
            parser.parse(yaml_text)

    def test_missing_close_protocol_warns(self):
        """Missing close_protocol should warn but not error."""
        parser = SchemaParser()
        yaml_text = """
framework:
  version: "0.2"
  agent_id: "test"
  session_id: "test"
  max_turns: 5
  basin_params:
    test_basin:
      class: core
      alpha: 0.5
identity_core: "test"
session_task: "test"
"""
        result = parser.parse(yaml_text)
        assert "close_protocol" in result.validation_warnings[0]
        assert result.close_protocol is None

    def test_unexpected_top_level_field_warns(self):
        """Unexpected top-level fields should warn but not error."""
        parser = SchemaParser()
        yaml_text = """
framework:
  version: "0.2"
  agent_id: "test"
  session_id: "test"
  max_turns: 5
  basin_params:
    test_basin:
      class: core
      alpha: 0.5
identity_core: "test"
session_task: "test"
unexpected_field: "should warn"
"""
        result = parser.parse(yaml_text)
        assert any("unexpected_field" in w.lower() for w in result.validation_warnings)

    def test_simple_capability_format(self):
        """Simple bool capability format should parse correctly."""
        parser = SchemaParser()
        yaml_text = """
framework:
  version: "0.2"
  agent_id: "test"
  session_id: "test"
  max_turns: 5
  capabilities:
    mcp: true
    web_search: false
  basin_params:
    test_basin:
      class: core
      alpha: 0.5
identity_core: "test"
session_task: "test"
"""
        result = parser.parse(yaml_text)
        assert result.framework.capabilities["mcp"].enabled is True
        assert result.framework.capabilities["mcp"].available_from_turn == 0
        assert result.framework.capabilities["web_search"].enabled is False

    def test_structured_capability_format(self):
        """Structured capability format should parse correctly."""
        parser = SchemaParser()
        yaml_text = """
framework:
  version: "0.2"
  agent_id: "test"
  session_id: "test"
  max_turns: 10
  capabilities:
    file_write:
      enabled: true
      available_from_turn: 5
  basin_params:
    test_basin:
      class: core
      alpha: 0.5
identity_core: "test"
session_task: "test"
"""
        result = parser.parse(yaml_text)
        assert result.framework.capabilities["file_write"].enabled is True
        assert result.framework.capabilities["file_write"].available_from_turn == 5

    def test_capability_turn_out_of_range(self):
        """Capability available_from_turn >= max_turns should raise error."""
        parser = SchemaParser()
        yaml_text = """
framework:
  version: "0.2"
  agent_id: "test"
  session_id: "test"
  max_turns: 5
  capabilities:
    file_write:
      enabled: true
      available_from_turn: 5
  basin_params:
    test_basin:
      class: core
      alpha: 0.5
identity_core: "test"
session_task: "test"
"""
        with pytest.raises(SchemaValidationError, match="available_from_turn must be in"):
            parser.parse(yaml_text)

    def test_co_activation_log_parsing(self):
        """Co-activation log should parse correctly."""
        parser = SchemaParser()
        yaml_text = """
framework:
  version: "0.2"
  agent_id: "test"
  session_id: "test"
  max_turns: 5
  basin_params:
    basin_a:
      class: core
      alpha: 0.5
    basin_b:
      class: core
      alpha: 0.5
  co_activation_log:
    - pair: [basin_a, basin_b]
      count: 12
      character: reinforcing
    - pair: [basin_a, basin_b]
      count: 3
      character: null
identity_core: "test"
session_task: "test"
"""
        result = parser.parse(yaml_text)
        assert len(result.framework.co_activation_log) == 2
        assert result.framework.co_activation_log[0].count == 12
        assert result.framework.co_activation_log[0].character == CoActivationCharacter.REINFORCING
        assert result.framework.co_activation_log[1].character is None

    def test_invalid_basin_class(self):
        """Invalid basin class should raise error."""
        parser = SchemaParser()
        yaml_text = """
framework:
  version: "0.2"
  agent_id: "test"
  session_id: "test"
  max_turns: 5
  basin_params:
    test_basin:
      class: invalid
      alpha: 0.5
identity_core: "test"
session_task: "test"
"""
        with pytest.raises(SchemaValidationError, match="class must be 'core' or 'peripheral'"):
            parser.parse(yaml_text)

    def test_empty_basin_params(self):
        """Empty basin_params should raise error."""
        parser = SchemaParser()
        yaml_text = """
framework:
  version: "0.2"
  agent_id: "test"
  session_id: "test"
  max_turns: 5
  basin_params: {}
identity_core: "test"
session_task: "test"
"""
        with pytest.raises(SchemaValidationError, match="basin_params.*must contain at least one"):
            parser.parse(yaml_text)

    def test_malformed_yaml(self):
        """Malformed YAML should raise error."""
        parser = SchemaParser()
        yaml_text = """
framework:
  version: "0.2"
  agent_id: "test
  - invalid indentation
"""
        with pytest.raises(SchemaValidationError, match="Invalid YAML"):
            parser.parse(yaml_text)
