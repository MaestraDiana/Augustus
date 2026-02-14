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
        assert result == "claude-sonnet-4-20250514"

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
