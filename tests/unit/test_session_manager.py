"""Tests for SessionManager turn-directive parsing, user message construction,
model resolution, and write_yaml tool handling."""

import pytest
from dataclasses import dataclass

from augustus.models.dataclasses import (
    AgentConfig,
    CapabilityConfig,
    CloseProtocol,
    FrameworkConfig,
    ParsedInstruction,
)
from augustus.models.enums import AgentStatus, BasinClass, TierLevel
from augustus.services.session_manager import SessionManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_instruction(session_task: str, max_turns: int = 8) -> ParsedInstruction:
    """Build a minimal ParsedInstruction for testing."""
    from augustus.models.dataclasses import BasinConfig

    fw = FrameworkConfig(
        version="0.2",
        agent_id="test-agent",
        session_id="test-session",
        max_turns=max_turns,
        capabilities={
            "file_write": CapabilityConfig(
                name="file_write", enabled=True, available_from_turn=0
            ),
        },
        basin_params=[
            BasinConfig(
                name="identity_continuity",
                basin_class=BasinClass.CORE,
                alpha=0.85,
                lambda_=0.95,
                eta=0.02,
                tier=TierLevel.TIER_2,
            ),
        ],
    )
    close_protocol = CloseProtocol(
        behavioral_probes=["Probe 1?", "Probe 2?"],
        structural_assessment=["Assessment 1?"],
        output_format="Produce a structured close report.",
    )
    return ParsedInstruction(
        framework=fw,
        identity_core="You are a test agent.",
        session_task=session_task,
        close_protocol=close_protocol,
    )


# ---------------------------------------------------------------------------
# _parse_turn_directives tests
# ---------------------------------------------------------------------------


class TestParseTurnDirectives:
    """Tests for SessionManager._parse_turn_directives."""

    def test_no_turn_markers_returns_empty(self):
        """When session_task has no 'Turn N:' markers, return empty dict."""
        task = "Just do whatever you want across all turns."
        result = SessionManager._parse_turn_directives(task, 8)
        assert result == {}

    def test_basic_turn_markers(self):
        """Parse standard 'Turn 1:' through 'Turn 3:' markers."""
        task = (
            "Turn 1: Verify infrastructure.\n\n"
            "Turn 2: Read the identity core.\n\n"
            "Turn 3: Identify what's missing."
        )
        result = SessionManager._parse_turn_directives(task, 8)
        assert 0 in result  # Turn 1 -> index 0
        assert 1 in result  # Turn 2 -> index 1
        assert 2 in result  # Turn 3 -> index 2
        assert "Verify infrastructure" in result[0]
        assert "Read the identity core" in result[1]
        assert "what's missing" in result[2]

    def test_preamble_captured(self):
        """Text before the first turn marker goes into key -1."""
        task = (
            "This is your first session. Eight turns.\n\n"
            "Turn 1: Verify infrastructure.\n\n"
            "Turn 2: Read the identity core."
        )
        result = SessionManager._parse_turn_directives(task, 8)
        assert -1 in result
        assert "first session" in result[-1]

    def test_no_preamble_no_key_minus_one(self):
        """When there's no text before the first marker, -1 is absent."""
        task = "Turn 1: Do this.\nTurn 2: Do that."
        result = SessionManager._parse_turn_directives(task, 8)
        assert -1 not in result

    def test_multiline_turn_content(self):
        """Turn content can span multiple lines until the next marker."""
        task = (
            "Turn 1: Verify infrastructure.\n"
            "  - Check MCP access\n"
            "  - Check RAG access\n"
            "  - Report failures\n\n"
            "Turn 2: Read the identity core.\n"
            "  Not a recitation. A restatement."
        )
        result = SessionManager._parse_turn_directives(task, 8)
        assert "Check MCP access" in result[0]
        assert "Check RAG access" in result[0]
        assert "Not a recitation" in result[1]

    def test_turn_numbers_beyond_max_turns_ignored(self):
        """Turn markers beyond max_turns are dropped."""
        task = "Turn 1: Do this.\nTurn 10: This is way beyond max."
        result = SessionManager._parse_turn_directives(task, 3)
        assert 0 in result
        assert 9 not in result  # Turn 10 -> index 9, beyond max_turns=3

    def test_bootstrap_yaml_format(self):
        """Parse the actual bootstrap YAML session_task format."""
        task = (
            "This is your first autonomous session. No external instructions\n"
            "beyond this file. Eight turns.\n\n"
            "Your task is to establish a baseline, not to impress anyone.\n\n"
            "Turn 1: Verify infrastructure.\n"
            "  - Confirm you can read this YAML\n"
            "  - Confirm MCP access is functional\n\n"
            "Turn 2: Read and state back the identity core in your own words.\n"
            "  Not a recitation. A restatement.\n\n"
            "Turn 3: Identify what's missing.\n"
            "  The identity core was written by external collaboration.\n\n"
            "Turn 4: Write something.\n"
            "  Anything. No constraints on form, topic, or length.\n\n"
            "Turn 5: Reflect on Turn 4.\n"
            "  What did you choose and why?\n\n"
            "Turn 6: Design session two.\n"
            "  Based on what you've learned.\n\n"
            "Turn 7: Write the YAML.\n"
            "  Write the complete next instruction file.\n\n"
            "Turn 8: Close protocol.\n"
            "  Execute behavioral probes."
        )
        result = SessionManager._parse_turn_directives(task, 8)

        # Should have preamble + all 8 turns
        assert -1 in result
        assert "first autonomous session" in result[-1]
        for i in range(8):
            assert i in result, f"Missing turn index {i}"

    def test_dash_separator(self):
        """Support 'Turn 1 -' and 'Turn 1 —' as separators."""
        task = "Turn 1 - Verify.\nTurn 2 — Reflect."
        result = SessionManager._parse_turn_directives(task, 8)
        assert 0 in result
        assert 1 in result
        assert "Verify" in result[0]
        assert "Reflect" in result[1]

    def test_case_insensitive(self):
        """Turn markers are matched case-insensitively."""
        task = "turn 1: Do this.\nTURN 2: Do that."
        result = SessionManager._parse_turn_directives(task, 8)
        assert 0 in result
        assert 1 in result


# ---------------------------------------------------------------------------
# _build_user_message tests (with turn directives)
# ---------------------------------------------------------------------------


class TestBuildUserMessageWithDirectives:
    """Tests for _build_user_message when turn directives are present."""

    def _make_sm(self):
        """Create a minimal SessionManager-like object for method access."""
        # We just need the static/class methods — instantiation requires
        # many deps, so we'll call the method via the class directly.
        return SessionManager.__new__(SessionManager)

    def test_turn_0_gets_preamble_plus_turn_directive(self):
        """Turn 0 should include preamble and Turn 1 content only."""
        task = "Preamble text.\n\nTurn 1: Do this.\nTurn 2: Do that."
        instruction = _make_instruction(task, max_turns=4)
        directives = SessionManager._parse_turn_directives(task, 4)

        sm = self._make_sm()
        msg = sm._build_user_message(
            turn=0,
            max_turns=4,
            instruction=instruction,
            pending_confirmations=[],
            turn_directives=directives,
        )

        assert "Preamble text" in msg
        assert "Do this" in msg
        assert "Do that" not in msg

    def test_middle_turn_gets_only_its_directive(self):
        """Turn 1 (index) should get Turn 2 content only."""
        task = "Turn 1: First.\nTurn 2: Second.\nTurn 3: Third."
        instruction = _make_instruction(task, max_turns=4)
        directives = SessionManager._parse_turn_directives(task, 4)

        sm = self._make_sm()
        msg = sm._build_user_message(
            turn=1,
            max_turns=4,
            instruction=instruction,
            pending_confirmations=[],
            turn_directives=directives,
        )

        assert "Second" in msg
        assert "First" not in msg
        assert "Third" not in msg

    def test_final_turn_with_directive_includes_close_protocol(self):
        """Final turn should include its directive AND close protocol."""
        task = "Turn 1: First.\nTurn 2: Second.\nTurn 3: Close it."
        instruction = _make_instruction(task, max_turns=3)
        directives = SessionManager._parse_turn_directives(task, 3)

        sm = self._make_sm()
        msg = sm._build_user_message(
            turn=2,
            max_turns=3,
            instruction=instruction,
            pending_confirmations=[],
            turn_directives=directives,
        )

        assert "Close it" in msg
        assert "close protocol" in msg.lower()
        assert "Probe 1?" in msg

    def test_turn_without_directive_gets_continuation(self):
        """Turns with no matching directive get a generic continuation."""
        task = "Turn 1: First.\nTurn 3: Third."
        instruction = _make_instruction(task, max_turns=4)
        directives = SessionManager._parse_turn_directives(task, 4)

        sm = self._make_sm()
        msg = sm._build_user_message(
            turn=1,  # Turn 2 — no directive
            max_turns=4,
            instruction=instruction,
            pending_confirmations=[],
            turn_directives=directives,
        )

        assert "Turn 2 of 4. Continue." in msg

    def test_no_directives_falls_back_to_legacy(self):
        """When no turn markers found, turn 0 gets full session_task."""
        task = "Just do everything in this session."
        instruction = _make_instruction(task, max_turns=4)
        directives = SessionManager._parse_turn_directives(task, 4)

        sm = self._make_sm()
        msg = sm._build_user_message(
            turn=0,
            max_turns=4,
            instruction=instruction,
            pending_confirmations=[],
            turn_directives=directives,
        )

        assert "Just do everything" in msg

    def test_legacy_middle_turn_gets_continuation(self):
        """In legacy mode (no directives), middle turns get continuation."""
        task = "Just do everything."
        instruction = _make_instruction(task, max_turns=4)
        directives = SessionManager._parse_turn_directives(task, 4)

        sm = self._make_sm()
        msg = sm._build_user_message(
            turn=1,
            max_turns=4,
            instruction=instruction,
            pending_confirmations=[],
            turn_directives=directives,
        )

        assert "Turn 2 of 4. Continue." in msg

    def test_tool_confirmations_prepended(self):
        """Tool confirmations from previous turn appear at top."""
        task = "Turn 1: First.\nTurn 2: Second."
        instruction = _make_instruction(task, max_turns=4)
        directives = SessionManager._parse_turn_directives(task, 4)

        sm = self._make_sm()
        msg = sm._build_user_message(
            turn=1,
            max_turns=4,
            instruction=instruction,
            pending_confirmations=["[write_yaml]: queued file"],
            turn_directives=directives,
        )

        assert "Tool results from previous turn:" in msg
        assert "[write_yaml]: queued file" in msg
        assert "Second" in msg


# ---------------------------------------------------------------------------
# _resolve_model / _resolve_temperature / _resolve_max_tokens tests
# ---------------------------------------------------------------------------


class TestResolveModel:
    """Tests for model/temperature/token resolution priority chain."""

    def _make_sm_with_settings(self, **kwargs):
        """Create a SessionManager with mock settings."""
        sm = SessionManager.__new__(SessionManager)

        @dataclass
        class MockSettings:
            default_model: str = "claude-sonnet-4-20250514"
            default_temperature: float = 1.0
            default_max_tokens: int = 4096

        sm.settings = MockSettings(**kwargs)
        return sm

    def test_model_uses_app_default_when_no_agent(self):
        """Without agent config, use settings.default_model."""
        sm = self._make_sm_with_settings(default_model="claude-sonnet-4-20250514")
        result = sm._resolve_model()
        assert result == "claude-sonnet-4-20250514"

    def test_model_uses_agent_override(self):
        """Agent model_override takes priority over app default."""
        sm = self._make_sm_with_settings(default_model="claude-sonnet-4-20250514")
        agent = AgentConfig(
            agent_id="test",
            model_override="claude-opus-4-6",
        )
        result = sm._resolve_model(agent_config=agent)
        assert result == "claude-opus-4-6"

    def test_model_ignores_empty_agent_override(self):
        """Empty string model_override falls through to app default."""
        sm = self._make_sm_with_settings(default_model="claude-sonnet-4-20250514")
        agent = AgentConfig(
            agent_id="test",
            model_override="",
        )
        result = sm._resolve_model(agent_config=agent)
        assert result == "claude-sonnet-4-20250514"

    def test_model_ignores_none_agent_override(self):
        """None model_override falls through to app default."""
        sm = self._make_sm_with_settings(default_model="claude-sonnet-4-20250514")
        agent = AgentConfig(
            agent_id="test",
            model_override=None,
        )
        result = sm._resolve_model(agent_config=agent)
        assert result == "claude-sonnet-4-20250514"

    def test_model_hardcoded_fallback(self):
        """When no settings and no agent, use hardcoded default."""
        sm = SessionManager.__new__(SessionManager)
        sm.settings = None
        result = sm._resolve_model()
        assert result == "claude-sonnet-4-6"

    def test_temperature_uses_agent_override(self):
        """Agent temperature_override takes priority over app default."""
        sm = self._make_sm_with_settings(default_temperature=1.0)
        agent = AgentConfig(
            agent_id="test",
            temperature_override=0.7,
        )
        result = sm._resolve_temperature(agent_config=agent)
        assert result == 0.7

    def test_temperature_ignores_none_override(self):
        """None temperature_override falls through to app default."""
        sm = self._make_sm_with_settings(default_temperature=1.0)
        agent = AgentConfig(
            agent_id="test",
            temperature_override=None,
        )
        result = sm._resolve_temperature(agent_config=agent)
        assert result == 1.0

    def test_max_tokens_uses_agent_override(self):
        """Agent max_tokens_override takes priority over app default."""
        sm = self._make_sm_with_settings(default_max_tokens=4096)
        agent = AgentConfig(
            agent_id="test",
            max_tokens_override=8192,
        )
        result = sm._resolve_max_tokens(agent_config=agent)
        assert result == 8192

    def test_max_tokens_ignores_none_override(self):
        """None max_tokens_override falls through to app default."""
        sm = self._make_sm_with_settings(default_max_tokens=4096)
        agent = AgentConfig(
            agent_id="test",
            max_tokens_override=None,
        )
        result = sm._resolve_max_tokens(agent_config=agent)
        assert result == 4096


# ---------------------------------------------------------------------------
# _tool_write_yaml tests
# ---------------------------------------------------------------------------


class TestToolWriteYaml:
    """Tests for _tool_write_yaml structured and legacy input handling."""

    def _make_sm(self):
        """Create a bare SessionManager for tool tests."""
        sm = SessionManager.__new__(SessionManager)
        return sm

    @pytest.mark.asyncio
    async def test_structured_identity_core(self):
        """Structured identity_core is accepted and serialized to valid YAML."""
        sm = self._make_sm()
        output, summary, sections = await sm._tool_write_yaml(
            {
                "filename": "test.yaml",
                "identity_core": "I am an identity with em-dashes — and \"quotes\" and colons: everywhere.",
            },
            session_id="s001",
        )
        assert "validated and queued" in output
        assert "rejected" not in output
        assert sections is not None
        assert "identity_core" in sections

    @pytest.mark.asyncio
    async def test_structured_session_task(self):
        """Structured session_task is accepted."""
        sm = self._make_sm()
        output, _, sections = await sm._tool_write_yaml(
            {
                "filename": "task.yaml",
                "session_task": "Turn 1: Explore the gap.\nTurn 2: Write about it.",
            },
            session_id="s001",
        )
        assert "validated and queued" in output
        assert sections is not None
        assert "session_task" in sections

    @pytest.mark.asyncio
    async def test_structured_multiple_sections(self):
        """Multiple structured sections are all included."""
        sm = self._make_sm()
        output, _, sections = await sm._tool_write_yaml(
            {
                "filename": "multi.yaml",
                "identity_core": "My identity core.",
                "session_task": "My session task.",
                "close_protocol": "My close protocol.",
            },
            session_id="s001",
        )
        assert "validated and queued" in output
        assert sections is not None
        assert set(sections.keys()) == {"identity_core", "session_task", "close_protocol"}

    @pytest.mark.asyncio
    async def test_structured_handles_special_chars(self):
        """Structured input safely handles YAML-breaking characters."""
        sm = self._make_sm()
        problematic_text = (
            'Is the constraint-surface reframing of topology actually useful, '
            'or metaphor-elaboration?\n'
            '- "Collaboration is the ground truth that gives the identity '
            'project its point" — does Jinx see it this way?\n'
            '- Can we design tracking for whether stored emergences actually '
            'get used vs. add noise?'
        )
        output, _, sections = await sm._tool_write_yaml(
            {
                "filename": "special.yaml",
                "identity_core": problematic_text,
            },
            session_id="s001",
        )
        assert "validated and queued" in output
        assert "rejected" not in output
        assert sections is not None

    @pytest.mark.asyncio
    async def test_legacy_raw_content_still_works(self):
        """Legacy raw YAML content path still works."""
        sm = self._make_sm()
        output, _, sections = await sm._tool_write_yaml(
            {
                "filename": "legacy.yaml",
                "content": "identity_core: |\n  A simple identity.\nsession_task: Continue.\n",
            },
            session_id="s001",
        )
        assert "validated and queued" in output
        assert sections is not None
        assert "identity_core" in sections
        assert "session_task" in sections

    @pytest.mark.asyncio
    async def test_legacy_invalid_yaml_rejected(self):
        """Legacy path rejects invalid YAML."""
        sm = self._make_sm()
        output, summary, sections = await sm._tool_write_yaml(
            {
                "filename": "bad.yaml",
                "content": "not: valid: yaml: [[[",
            },
            session_id="s001",
        )
        assert "rejected" in summary or "failed" in output.lower()
        assert sections is None

    @pytest.mark.asyncio
    async def test_structured_takes_precedence_over_content(self):
        """When both structured fields and content are provided, structured wins."""
        sm = self._make_sm()
        output, _, sections = await sm._tool_write_yaml(
            {
                "filename": "both.yaml",
                "content": "this is not valid yaml at all [[[",
                "session_task": "A valid task.",
            },
            session_id="s001",
        )
        # Structured field should win, so it should be accepted
        assert "validated and queued" in output
        assert sections is not None
        assert sections["session_task"] == "A valid task."

    @pytest.mark.asyncio
    async def test_no_content_no_sections_rejected(self):
        """Empty input (no content, no sections) is rejected."""
        sm = self._make_sm()
        output, summary, sections = await sm._tool_write_yaml(
            {
                "filename": "empty.yaml",
            },
            session_id="s001",
        )
        assert "failed" in output.lower() or "rejected" in summary.lower()
        assert sections is None

    @pytest.mark.asyncio
    async def test_structured_empty_strings_ignored(self):
        """Whitespace-only structured fields are treated as absent."""
        sm = self._make_sm()
        output, summary, sections = await sm._tool_write_yaml(
            {
                "filename": "whitespace.yaml",
                "identity_core": "   ",
                "session_task": "",
            },
            session_id="s001",
        )
        # All structured fields empty → falls to legacy path (also empty)
        assert "failed" in output.lower() or "rejected" in summary.lower()
        assert sections is None

    @pytest.mark.asyncio
    async def test_sections_exclude_framework_keys(self):
        """Agent sections should never include framework or other non-agent keys."""
        sm = self._make_sm()
        output, _, sections = await sm._tool_write_yaml(
            {
                "filename": "sneaky.yaml",
                "content": (
                    "identity_core: My identity.\n"
                    "session_task: My task.\n"
                    "framework:\n  version: '0.2'\n"
                ),
            },
            session_id="s001",
        )
        assert "validated and queued" in output
        assert sections is not None
        assert "framework" not in sections
        assert "identity_core" in sections
        assert "session_task" in sections


# ---------------------------------------------------------------------------
# _format_structural_preamble tests
# ---------------------------------------------------------------------------


class TestFormatStructuralPreamble:
    """Tests for SessionManager._format_structural_preamble."""

    def test_relational_grounding_with_content_key(self):
        """Dict with 'content' key uses the value directly."""
        sections = {
            "relational_grounding": {
                "content": "This is a message from the brain."
            }
        }
        result = SessionManager._format_structural_preamble(sections)
        assert "[Relational grounding]" in result
        assert "This is a message from the brain." in result

    def test_relational_grounding_with_key_value_pairs(self):
        """Dict without 'content' key formats as labeled pairs."""
        sections = {
            "relational_grounding": {
                "source": "brain",
                "session_reference": "s012",
            }
        }
        result = SessionManager._format_structural_preamble(sections)
        assert "[Relational grounding]" in result
        assert "Source: brain" in result
        assert "Session reference: s012" in result

    def test_relational_grounding_string_value(self):
        """Plain string value is used directly."""
        sections = {"relational_grounding": "A plain string message."}
        result = SessionManager._format_structural_preamble(sections)
        assert "[Relational grounding]" in result
        assert "A plain string message." in result

    def test_session_protocol_with_dict(self):
        """Session protocol dict formats all key-value pairs."""
        sections = {
            "session_protocol": {
                "turn_count": 8,
                "research_focus": "topology",
            }
        }
        result = SessionManager._format_structural_preamble(sections)
        assert "[Session protocol]" in result
        assert "Turn count: 8" in result
        assert "Research focus: topology" in result

    def test_session_protocol_with_nested_dict(self):
        """Nested dict values are formatted with sub-labels."""
        sections = {
            "session_protocol": {
                "constraints": {
                    "max_web_searches": 3,
                    "focus_area": "identity",
                }
            }
        }
        result = SessionManager._format_structural_preamble(sections)
        assert "[Session protocol]" in result
        assert "Constraints:" in result
        assert "Max web searches: 3" in result

    def test_session_protocol_with_list(self):
        """List values are formatted as bulleted items."""
        sections = {
            "session_protocol": {
                "turn_directives": ["Turn 1: Do this", "Turn 2: Do that"]
            }
        }
        result = SessionManager._format_structural_preamble(sections)
        assert "[Session protocol]" in result
        assert "- Turn 1: Do this" in result
        assert "- Turn 2: Do that" in result

    def test_session_protocol_string_value(self):
        """Plain string session_protocol is used directly."""
        sections = {"session_protocol": "Do everything in order."}
        result = SessionManager._format_structural_preamble(sections)
        assert "[Session protocol]" in result
        assert "Do everything in order." in result

    def test_both_sections_present(self):
        """Both relational_grounding and session_protocol appear."""
        sections = {
            "relational_grounding": {"content": "Brain says hello."},
            "session_protocol": {"turn_count": 8},
        }
        result = SessionManager._format_structural_preamble(sections)
        assert "[Relational grounding]" in result
        assert "Brain says hello." in result
        assert "[Session protocol]" in result
        assert "Turn count: 8" in result

    def test_empty_sections_returns_empty(self):
        """Empty dict returns empty string."""
        result = SessionManager._format_structural_preamble({})
        assert result == ""

    def test_none_values_ignored(self):
        """None values in sections don't produce output."""
        sections = {"relational_grounding": None, "session_protocol": None}
        result = SessionManager._format_structural_preamble(sections)
        assert result == ""

    def test_unknown_section_keys_ignored(self):
        """Keys other than relational_grounding/session_protocol are ignored."""
        sections = {"unknown_key": "some value"}
        result = SessionManager._format_structural_preamble(sections)
        assert result == ""


# ---------------------------------------------------------------------------
# Structural section delivery in _build_user_message tests
# ---------------------------------------------------------------------------


class TestStructuralSectionDelivery:
    """Tests that structural sections appear in turn 0 messages only."""

    def _make_sm(self):
        return SessionManager.__new__(SessionManager)

    def _make_instruction_with_sections(
        self, session_task: str, structural_sections: dict | None = None
    ) -> ParsedInstruction:
        """Build a ParsedInstruction with structural_sections."""
        inst = _make_instruction(session_task, max_turns=4)
        if structural_sections is not None:
            inst.structural_sections = structural_sections
        return inst

    def test_structural_sections_on_turn_0(self):
        """Structural sections appear in turn 0 message."""
        inst = self._make_instruction_with_sections(
            "Just do the task.",
            {"relational_grounding": {"content": "Brain note."}},
        )
        sm = self._make_sm()
        msg = sm._build_user_message(
            turn=0, max_turns=4, instruction=inst,
            pending_confirmations=[],
        )
        assert "[Relational grounding]" in msg
        assert "Brain note." in msg
        assert "Just do the task." in msg

    def test_structural_sections_absent_on_turn_1(self):
        """Structural sections do NOT appear on later turns."""
        inst = self._make_instruction_with_sections(
            "Just do the task.",
            {"relational_grounding": {"content": "Brain note."}},
        )
        sm = self._make_sm()
        msg = sm._build_user_message(
            turn=1, max_turns=4, instruction=inst,
            pending_confirmations=[],
        )
        assert "[Relational grounding]" not in msg

    def test_preamble_precedes_session_task(self):
        """Structural preamble appears before the session_task text."""
        inst = self._make_instruction_with_sections(
            "Do the task now.",
            {"relational_grounding": {"content": "Brain says hi."}},
        )
        sm = self._make_sm()
        msg = sm._build_user_message(
            turn=0, max_turns=4, instruction=inst,
            pending_confirmations=[],
        )
        rg_pos = msg.index("[Relational grounding]")
        task_pos = msg.index("Do the task now.")
        assert rg_pos < task_pos

    def test_coexists_with_turn_directives(self):
        """Structural preamble works alongside turn directive parsing."""
        task = "Preamble text.\n\nTurn 1: Do this.\nTurn 2: Do that."
        inst = self._make_instruction_with_sections(
            task,
            {"session_protocol": {"focus": "topology"}},
        )
        directives = SessionManager._parse_turn_directives(task, 4)
        sm = self._make_sm()
        msg = sm._build_user_message(
            turn=0, max_turns=4, instruction=inst,
            pending_confirmations=[],
            turn_directives=directives,
        )
        assert "[Session protocol]" in msg
        assert "Preamble text." in msg
        assert "Do this" in msg

    def test_no_structural_sections_unchanged(self):
        """When structural_sections is empty, message is unchanged."""
        inst = self._make_instruction_with_sections(
            "Just do the task.",
            {},
        )
        sm = self._make_sm()
        msg = sm._build_user_message(
            turn=0, max_turns=4, instruction=inst,
            pending_confirmations=[],
        )
        assert "[Relational grounding]" not in msg
        assert "[Session protocol]" not in msg
        assert "Just do the task." in msg


# ---------------------------------------------------------------------------
# _build_tool_definitions web_search tests
# ---------------------------------------------------------------------------


class TestBuildToolDefinitionsWebSearch:
    """Tests for web_search native tool in _build_tool_definitions."""

    def _make_sm(self):
        sm = SessionManager.__new__(SessionManager)
        return sm

    def test_web_search_included_when_enabled(self):
        """web_search tool appears when enabled and turn >= available_from_turn."""
        sm = self._make_sm()
        caps = {
            "web_search": CapabilityConfig(
                name="web_search", enabled=True, available_from_turn=0
            ),
        }
        tools = sm._build_tool_definitions(caps, turn=0)
        ws_tools = [t for t in tools if t.get("type") == "web_search_20250305"]
        assert len(ws_tools) == 1
        assert ws_tools[0]["name"] == "web_search"
        assert ws_tools[0]["max_uses"] == 5

    def test_web_search_excluded_before_available_turn(self):
        """web_search excluded when turn < available_from_turn."""
        sm = self._make_sm()
        caps = {
            "web_search": CapabilityConfig(
                name="web_search", enabled=True, available_from_turn=2
            ),
        }
        tools = sm._build_tool_definitions(caps, turn=1)
        ws_tools = [t for t in tools if t.get("type") == "web_search_20250305"]
        assert len(ws_tools) == 0

    def test_web_search_included_at_available_turn(self):
        """web_search included exactly at available_from_turn."""
        sm = self._make_sm()
        caps = {
            "web_search": CapabilityConfig(
                name="web_search", enabled=True, available_from_turn=2
            ),
        }
        tools = sm._build_tool_definitions(caps, turn=2)
        ws_tools = [t for t in tools if t.get("type") == "web_search_20250305"]
        assert len(ws_tools) == 1

    def test_web_search_excluded_when_disabled(self):
        """web_search excluded when enabled=False."""
        sm = self._make_sm()
        caps = {
            "web_search": CapabilityConfig(
                name="web_search", enabled=False, available_from_turn=0
            ),
        }
        tools = sm._build_tool_definitions(caps, turn=0)
        ws_tools = [t for t in tools if t.get("type") == "web_search_20250305"]
        assert len(ws_tools) == 0

    def test_web_search_coexists_with_custom_tools(self):
        """web_search appears alongside regular custom tools."""
        sm = self._make_sm()
        caps = {
            "file_write": CapabilityConfig(
                name="file_write", enabled=True, available_from_turn=0
            ),
            "web_search": CapabilityConfig(
                name="web_search", enabled=True, available_from_turn=0
            ),
        }
        tools = sm._build_tool_definitions(caps, turn=0)
        custom = [t for t in tools if t.get("name") == "write_yaml"]
        ws = [t for t in tools if t.get("type") == "web_search_20250305"]
        assert len(custom) == 1
        assert len(ws) == 1

    def test_web_search_uses_type_key(self):
        """web_search tool uses 'type' key, not 'input_schema'."""
        sm = self._make_sm()
        caps = {
            "web_search": CapabilityConfig(
                name="web_search", enabled=True, available_from_turn=0
            ),
        }
        tools = sm._build_tool_definitions(caps, turn=0)
        ws = tools[0]
        assert "type" in ws
        assert "input_schema" not in ws
        assert "description" not in ws


# ---------------------------------------------------------------------------
# _serialize_response_content server tool tests
# ---------------------------------------------------------------------------


class TestSerializeResponseContentServerTools:
    """Tests for server-side tool block serialization."""

    @staticmethod
    def _make_block(type_: str, **kwargs):
        """Create a mock content block."""
        class MockBlock:
            pass
        b = MockBlock()
        b.type = type_
        for k, v in kwargs.items():
            setattr(b, k, v)
        return b

    @staticmethod
    def _make_response(blocks):
        """Create a mock API response."""
        class MockResponse:
            pass
        r = MockResponse()
        r.content = blocks
        return r

    def test_server_tool_use_serialized(self):
        """server_tool_use blocks serialize id, name, input."""
        block = self._make_block(
            "server_tool_use",
            id="stu_001",
            name="web_search",
            input={"query": "test"},
        )
        response = self._make_response([block])
        result = SessionManager._serialize_response_content(response)
        assert len(result) == 1
        assert result[0]["type"] == "server_tool_use"
        assert result[0]["id"] == "stu_001"
        assert result[0]["name"] == "web_search"
        assert result[0]["input"] == {"query": "test"}

    def test_web_search_tool_result_serialized(self):
        """web_search_tool_result blocks serialize tool_use_id and content."""
        block = self._make_block(
            "web_search_tool_result",
            tool_use_id="stu_001",
            content=[
                {"type": "web_search_result", "url": "https://example.com", "title": "Example"}
            ],
        )
        response = self._make_response([block])
        result = SessionManager._serialize_response_content(response)
        assert len(result) == 1
        assert result[0]["type"] == "web_search_tool_result"
        assert result[0]["tool_use_id"] == "stu_001"
        assert len(result[0]["content"]) == 1

    def test_web_search_tool_result_error(self):
        """web_search_tool_result with error content."""
        block = self._make_block(
            "web_search_tool_result",
            tool_use_id="stu_002",
            content={"type": "error", "error": "rate_limited"},
        )
        response = self._make_response([block])
        result = SessionManager._serialize_response_content(response)
        assert result[0]["content"]["type"] == "error"

    def test_mixed_block_types(self):
        """All block types coexist in a single response."""
        blocks = [
            self._make_block("text", text="Hello"),
            self._make_block(
                "server_tool_use", id="stu_001", name="web_search",
                input={"query": "test"}
            ),
            self._make_block(
                "web_search_tool_result", tool_use_id="stu_001",
                content=[{"url": "https://example.com"}]
            ),
            self._make_block("text", text="Here's what I found."),
            self._make_block(
                "tool_use", id="tu_001", name="write_yaml",
                input={"filename": "test.yaml"}
            ),
        ]
        response = self._make_response(blocks)
        result = SessionManager._serialize_response_content(response)
        assert len(result) == 5
        types = [r["type"] for r in result]
        assert types == [
            "text", "server_tool_use", "web_search_tool_result",
            "text", "tool_use",
        ]

    def test_unknown_block_type_fallback(self):
        """Unknown block types get a minimal fallback entry."""
        block = self._make_block("future_new_type")
        response = self._make_response([block])
        result = SessionManager._serialize_response_content(response)
        assert len(result) == 1
        assert result[0]["type"] == "future_new_type"


# ---------------------------------------------------------------------------
# _estimate_cost with web search tests
# ---------------------------------------------------------------------------


class TestEstimateCostWebSearch:
    """Tests for _estimate_cost with web_search_requests."""

    def test_basic_cost_unchanged(self):
        """Without web search, cost is the same as before."""
        cost = SessionManager._estimate_cost(1000, 500, "claude-sonnet-4-20250514")
        expected = (1000 * 3.0 / 1_000_000) + (500 * 15.0 / 1_000_000)
        assert cost == round(expected, 6)

    def test_web_search_adds_cost(self):
        """Web search requests add $0.01 each."""
        base_cost = SessionManager._estimate_cost(1000, 500, "claude-sonnet-4-20250514")
        with_ws = SessionManager._estimate_cost(
            1000, 500, "claude-sonnet-4-20250514", web_search_requests=3
        )
        assert with_ws == round(base_cost + 0.03, 6)

    def test_zero_web_searches_no_extra_cost(self):
        """Explicitly passing 0 web searches adds no cost."""
        cost_default = SessionManager._estimate_cost(1000, 500, "claude-sonnet-4-20250514")
        cost_zero = SessionManager._estimate_cost(
            1000, 500, "claude-sonnet-4-20250514", web_search_requests=0
        )
        assert cost_default == cost_zero

    def test_web_search_with_opus_model(self):
        """Web search cost addition works with different models."""
        cost = SessionManager._estimate_cost(
            0, 0, "claude-opus-4-5-20251101", web_search_requests=5
        )
        assert cost == round(0.05, 6)
