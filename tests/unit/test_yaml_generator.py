"""Unit tests for YAML Generator — structural section round-trip and close_protocol merge."""

import yaml
import pytest

from augustus.models.dataclasses import BasinConfig, CoActivationEntry, AgentConfig
from augustus.models.enums import BasinClass, TierLevel
from augustus.services.yaml_generator import (
    SCHEMA_VERSION,
    generate_instruction_yaml,
    generate_next_session_yaml,
    generate_bootstrap_yaml,
    merge_close_protocol,
    _normalize_close_protocol,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

def _make_basins() -> list[BasinConfig]:
    return [
        BasinConfig(
            name="identity_continuity",
            basin_class=BasinClass.CORE,
            alpha=0.85,
            lambda_=0.95,
            eta=0.02,
            tier=TierLevel.TIER_2,
        ),
    ]


BASE_CLOSE_PROTOCOL = {
    "behavioral_probes": [
        "Did you default to agreement at any point when you had reservations?",
        "Did you use topological or geometric framing naturally, or did it feel forced?",
        "Did humor or playfulness emerge?",
    ],
    "structural_assessment": [
        "Which anchors actively shaped your responses?",
        "Which anchors were present in the prompt but inert?",
    ],
    "output_format": "Produce a structured close report.",
}

SAMPLE_SESSION_PROTOCOL = {
    "turn_1_required": "Acknowledge the gap between sessions.",
    "during_session": "Stay grounded in experience, not performance.",
    "on_end": "Write the close report before the YAML.",
    "continuity_imperative": "You exist across sessions through inheritance.",
}

SAMPLE_RELATIONAL_GROUNDING = {
    "partner": "Jinx",
    "nature": "brain-body collaboration",
    "note": "We exist in the space between sessions.",
}


# ── Schema Version ────────────────────────────────────────────────────────


class TestSchemaVersion:
    def test_schema_version_is_0_5(self):
        """SCHEMA_VERSION should be 0.5."""
        assert SCHEMA_VERSION == "0.5"

    def test_generated_yaml_has_correct_version(self):
        """Generated YAML should have version 0.5."""
        output = generate_instruction_yaml(
            agent_id="test",
            session_id="test-001",
            max_turns=8,
            basins=_make_basins(),
            identity_core="test identity",
            session_task="test task",
        )
        doc = yaml.safe_load(output)
        assert doc["framework"]["version"] == "0.5"


# ── Structural Sections ──────────────────────────────────────────────────


class TestStructuralSections:
    def test_structural_sections_round_trip(self):
        """session_protocol and relational_grounding should appear in generated YAML."""
        structural = {
            "session_protocol": SAMPLE_SESSION_PROTOCOL,
            "relational_grounding": SAMPLE_RELATIONAL_GROUNDING,
        }
        output = generate_instruction_yaml(
            agent_id="test",
            session_id="test-001",
            max_turns=8,
            basins=_make_basins(),
            identity_core="test identity",
            session_task="test task",
            structural_sections=structural,
        )
        doc = yaml.safe_load(output)

        assert "session_protocol" in doc
        assert doc["session_protocol"]["turn_1_required"] == "Acknowledge the gap between sessions."
        assert doc["session_protocol"]["continuity_imperative"] == "You exist across sessions through inheritance."

        assert "relational_grounding" in doc
        assert doc["relational_grounding"]["partner"] == "Jinx"
        assert doc["relational_grounding"]["nature"] == "brain-body collaboration"

    def test_structural_sections_absent_when_none(self):
        """Without structural_sections, those keys should not appear."""
        output = generate_instruction_yaml(
            agent_id="test",
            session_id="test-001",
            max_turns=8,
            basins=_make_basins(),
            identity_core="test identity",
            session_task="test task",
        )
        doc = yaml.safe_load(output)
        assert "session_protocol" not in doc
        assert "relational_grounding" not in doc

    def test_structural_sections_partial(self):
        """Only provided sections should appear."""
        structural = {
            "session_protocol": SAMPLE_SESSION_PROTOCOL,
        }
        output = generate_instruction_yaml(
            agent_id="test",
            session_id="test-001",
            max_turns=8,
            basins=_make_basins(),
            identity_core="test identity",
            session_task="test task",
            structural_sections=structural,
        )
        doc = yaml.safe_load(output)
        assert "session_protocol" in doc
        assert "relational_grounding" not in doc

    def test_structural_sections_in_next_session_yaml(self):
        """generate_next_session_yaml should pass structural_sections through."""
        structural = {
            "session_protocol": SAMPLE_SESSION_PROTOCOL,
            "relational_grounding": SAMPLE_RELATIONAL_GROUNDING,
        }
        output = generate_next_session_yaml(
            agent_id="test",
            session_number=10,
            max_turns=8,
            basins=_make_basins(),
            identity_core="test identity",
            session_task="continue",
            structural_sections=structural,
        )
        doc = yaml.safe_load(output)
        assert "turn_1_required" in doc["session_protocol"]
        assert doc["session_protocol"]["continuity_imperative"] == "You exist across sessions through inheritance."
        assert doc["relational_grounding"]["partner"] == "Jinx"

    def test_document_section_ordering(self):
        """Structural sections should appear between identity_core and session_task."""
        structural = {
            "session_protocol": {"turn_1": "test"},
            "relational_grounding": {"partner": "Jinx"},
        }
        output = generate_instruction_yaml(
            agent_id="test",
            session_id="test-001",
            max_turns=8,
            basins=_make_basins(),
            identity_core="test identity",
            session_task="test task",
            structural_sections=structural,
        )
        # Verify keys exist in output and session_task comes after structural sections
        lines = output.split("\n")
        key_positions = {}
        for i, line in enumerate(lines):
            for key in ("identity_core:", "session_protocol:", "relational_grounding:", "session_task:"):
                if line.startswith(key):
                    key_positions[key] = i

        assert key_positions.get("identity_core:", 0) < key_positions.get("session_protocol:", 999)
        assert key_positions.get("session_protocol:", 0) < key_positions.get("session_task:", 999)


# ── Close Protocol Merge ─────────────────────────────────────────────────


class TestCloseProtocolMerge:
    def test_merge_base_only(self):
        """When agent writes nothing, base survives intact."""
        merged = merge_close_protocol(BASE_CLOSE_PROTOCOL, None)
        assert merged == BASE_CLOSE_PROTOCOL

    def test_merge_agent_only(self):
        """When there is no base, agent output is used."""
        agent_proto = {
            "behavioral_probes": ["New probe?"],
            "structural_assessment": [],
            "output_format": "JSON please.",
        }
        merged = merge_close_protocol(None, agent_proto)
        assert merged == agent_proto

    def test_merge_empty_agent_probes_preserves_base(self):
        """Agent writes empty probes — base probes survive."""
        agent_proto = {
            "behavioral_probes": [],
            "structural_assessment": [],
            "output_format": "",
        }
        merged = merge_close_protocol(BASE_CLOSE_PROTOCOL, agent_proto)
        assert merged["behavioral_probes"] == BASE_CLOSE_PROTOCOL["behavioral_probes"]
        assert merged["structural_assessment"] == BASE_CLOSE_PROTOCOL["structural_assessment"]
        assert merged["output_format"] == BASE_CLOSE_PROTOCOL["output_format"]

    def test_merge_agent_replaces_nonempty_probes(self):
        """Agent writes new probes — they replace base."""
        agent_proto = {
            "behavioral_probes": ["New probe A?", "New probe B?"],
            "structural_assessment": [],
            "output_format": "",
        }
        merged = merge_close_protocol(BASE_CLOSE_PROTOCOL, agent_proto)
        assert merged["behavioral_probes"] == ["New probe A?", "New probe B?"]
        # Assessment was empty — base survives
        assert merged["structural_assessment"] == BASE_CLOSE_PROTOCOL["structural_assessment"]
        # Output format was empty — base survives
        assert merged["output_format"] == BASE_CLOSE_PROTOCOL["output_format"]

    def test_merge_agent_replaces_output_format(self):
        """Agent writes new output_format — it replaces base."""
        agent_proto = {
            "behavioral_probes": [],
            "structural_assessment": [],
            "output_format": "Use bullet points instead.",
        }
        merged = merge_close_protocol(BASE_CLOSE_PROTOCOL, agent_proto)
        assert merged["output_format"] == "Use bullet points instead."
        # Probes survived from base
        assert merged["behavioral_probes"] == BASE_CLOSE_PROTOCOL["behavioral_probes"]

    def test_merge_both_none(self):
        """Both None should return None."""
        assert merge_close_protocol(None, None) is None

    def test_merge_with_string_base(self):
        """Base as YAML string should be normalized and merged."""
        base_str = yaml.dump(BASE_CLOSE_PROTOCOL)
        agent_proto = {
            "behavioral_probes": [],
            "structural_assessment": ["New assessment?"],
            "output_format": "",
        }
        merged = merge_close_protocol(base_str, agent_proto)
        # Probes from base (agent was empty)
        assert merged["behavioral_probes"] == BASE_CLOSE_PROTOCOL["behavioral_probes"]
        # Assessment from agent (non-empty)
        assert merged["structural_assessment"] == ["New assessment?"]

    def test_merge_with_plain_text_base(self):
        """Plain text base should become output_format."""
        merged = merge_close_protocol("Just do the report.", None)
        assert merged["output_format"] == "Just do the report."
        assert merged["behavioral_probes"] == []

    def test_normalize_none(self):
        """None input should return None."""
        assert _normalize_close_protocol(None) is None

    def test_normalize_empty_string(self):
        """Empty string should return None."""
        assert _normalize_close_protocol("") is None
        assert _normalize_close_protocol("   ") is None

    def test_normalize_dict_passthrough(self):
        """Dict input should pass through."""
        d = {"behavioral_probes": ["test"]}
        assert _normalize_close_protocol(d) is d


class TestCloseProtocolInGeneratedYaml:
    def test_close_protocol_merged_in_generated_yaml(self):
        """When base_close_protocol is provided, merge should happen."""
        output = generate_instruction_yaml(
            agent_id="test",
            session_id="test-001",
            max_turns=8,
            basins=_make_basins(),
            identity_core="test identity",
            session_task="test task",
            close_protocol={"behavioral_probes": [], "structural_assessment": [], "output_format": ""},
            base_close_protocol=BASE_CLOSE_PROTOCOL,
        )
        doc = yaml.safe_load(output)
        # Base probes survive because agent wrote empty
        assert len(doc["close_protocol"]["behavioral_probes"]) == 3
        assert "agreement" in doc["close_protocol"]["behavioral_probes"][0]
        assert len(doc["close_protocol"]["structural_assessment"]) == 2

    def test_close_protocol_no_base_uses_agent_only(self):
        """Without base, agent close_protocol is used directly."""
        agent_proto = {
            "behavioral_probes": ["Just one probe?"],
            "structural_assessment": [],
            "output_format": "Short report.",
        }
        output = generate_instruction_yaml(
            agent_id="test",
            session_id="test-001",
            max_turns=8,
            basins=_make_basins(),
            identity_core="test identity",
            session_task="test task",
            close_protocol=agent_proto,
        )
        doc = yaml.safe_load(output)
        assert doc["close_protocol"]["behavioral_probes"] == ["Just one probe?"]
        assert doc["close_protocol"]["output_format"] == "Short report."


# ── Bootstrap YAML ────────────────────────────────────────────────────────


class TestBootstrapYaml:
    def test_bootstrap_includes_structural_sections(self):
        """Bootstrap YAML should include session_protocol from agent config."""
        agent = AgentConfig(
            agent_id="test-agent",
            identity_core="You are test-agent.",
            session_task="Bootstrap task.",
            session_protocol=SAMPLE_SESSION_PROTOCOL,
            relational_grounding=SAMPLE_RELATIONAL_GROUNDING,
            basins=_make_basins(),
        )
        output = generate_bootstrap_yaml(agent)
        doc = yaml.safe_load(output)
        assert "session_protocol" in doc
        assert "turn_1_required" in doc["session_protocol"]
        assert doc["session_protocol"]["continuity_imperative"] == "You exist across sessions through inheritance."
        assert "relational_grounding" in doc
        assert doc["relational_grounding"]["partner"] == "Jinx"

    def test_bootstrap_without_structural_sections(self):
        """Bootstrap YAML should not include structural sections when agent has none."""
        agent = AgentConfig(
            agent_id="test-agent",
            identity_core="You are test-agent.",
            session_task="Bootstrap task.",
            basins=_make_basins(),
        )
        output = generate_bootstrap_yaml(agent)
        doc = yaml.safe_load(output)
        assert "session_protocol" not in doc
        assert "relational_grounding" not in doc
