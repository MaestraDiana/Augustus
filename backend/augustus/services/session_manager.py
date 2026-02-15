"""Session Manager -- multi-turn Claude session orchestration.

Manages the complete lifecycle of a multi-turn session with the Anthropic API:
Phase 1 (INIT): Construct prompts and tool schedule from ParsedInstruction.
Phase 2 (TURN LOOP): Execute turns with capability gating and tool processing.
Phase 3 (CLOSE): Store data, run evaluator, trigger handoff protocol.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import anthropic

from augustus.config import Settings
from augustus.exceptions import BudgetExceededError
from augustus.models.dataclasses import (
    ActivityEvent,
    BasinConfig,
    BasinSnapshot,
    CapabilityConfig,
    CoActivationEntry,
    EvaluatorOutput,
    FlagRecord,
    ParsedInstruction,
    SessionRecord,
    UsageRecord,
)
from augustus.models.enums import CoActivationCharacter, FlagType
from augustus.services.evaluator import EvaluatorService
from augustus.services.handoff_engine import HandoffEngine, HandoffResult
from augustus.services.schema_parser import SchemaParser
from augustus.utils import DEFAULT_CONTINUATION_TASK, flatten_transcript, normalize_model, utcnow_iso

logger = logging.getLogger(__name__)


class SessionManager:
    """Execute multi-turn Claude sessions via the Anthropic API.

    Each session follows the three-phase lifecycle defined in the architecture:
    INIT -> TURN LOOP -> CLOSE. Tools are gated by turn number per the
    capability schedule in the YAML framework section.
    """

    def __init__(
        self,
        api_key: str,
        memory: Any,  # MemoryService -- typed as Any to avoid circular import
        evaluator: EvaluatorService | None,
        handoff: HandoffEngine,
        tier_enforcer: Any,  # TierEnforcer -- typed as Any to avoid circular import
        schema_parser: SchemaParser,
        settings: Settings | None = None,
    ) -> None:
        """Initialize SessionManager with injected dependencies.

        Args:
            api_key: Anthropic API key for creating the async client.
            memory: MemoryService instance for all data persistence.
            evaluator: EvaluatorService instance (may be None if disabled).
            handoff: HandoffEngine instance for between-session calculations.
            tier_enforcer: TierEnforcer instance for permission checks.
            schema_parser: SchemaParser instance for YAML validation.
            settings: Application settings for model defaults and budget limits.
        """
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.memory = memory
        self.evaluator = evaluator
        self.handoff = handoff
        self.tier_enforcer = tier_enforcer
        self.schema_parser = schema_parser
        self.settings = settings

    # ------------------------------------------------------------------
    # Turn directive parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_turn_directives(
        session_task: str, max_turns: int
    ) -> dict[int, str]:
        """Parse session_task text into per-turn directives.

        Looks for patterns like "Turn 1:", "Turn 2:", etc. in the session
        task text and splits content so each turn receives only its own
        directive instead of the entire block.

        If no turn markers are found, returns an empty dict (meaning the
        entire session_task should be delivered on turn 0 as before).

        Returns:
            Mapping from 0-based turn index to that turn's directive text.
            May also include a key -1 for preamble text before the first
            turn marker.
        """
        # Match "Turn N:" at the start of a line (with optional leading whitespace)
        # Supports "Turn 1:", "Turn 1 -", "Turn 1 —", etc.
        pattern = re.compile(
            r"^[ \t]*Turn\s+(\d+)\s*[:—\-]",
            re.MULTILINE | re.IGNORECASE,
        )

        matches = list(pattern.finditer(session_task))
        if not matches:
            return {}

        directives: dict[int, str] = {}

        # Capture preamble (text before first turn marker)
        preamble = session_task[: matches[0].start()].strip()
        if preamble:
            directives[-1] = preamble

        # Split at each turn marker
        for i, match in enumerate(matches):
            turn_num = int(match.group(1))
            # 0-based index (Turn 1 -> index 0, Turn 2 -> index 1, etc.)
            turn_idx = turn_num - 1

            # Content runs from this match start to next match start (or end)
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(session_task)
            content = session_task[start:end].strip()

            if 0 <= turn_idx < max_turns:
                directives[turn_idx] = content

        return directives

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute_session(
        self,
        instruction: ParsedInstruction,
        agent_config: Any | None = None,
    ) -> SessionRecord:
        """Execute a complete multi-turn session.

        Phases:
            1. INIT -- build prompts, tools, and metadata from the instruction.
            2. TURN LOOP -- iterate through max_turns API calls.
            3. CLOSE -- persist data, evaluate, run handoff.

        Args:
            instruction: Parsed YAML instruction containing framework,
                identity_core, session_task, and close_protocol.
            agent_config: Optional AgentConfig with model/temperature/token
                overrides. When provided, agent-level overrides take
                precedence over application-wide defaults.

        Returns:
            Completed SessionRecord with transcript and metadata.

        Raises:
            BudgetExceededError: If the daily budget is exhausted.
        """
        fw = instruction.framework
        session_id = fw.session_id
        agent_id = fw.agent_id
        max_turns = fw.max_turns

        model = self._resolve_model(agent_config)
        temperature = self._resolve_temperature(agent_config)
        max_tokens = self._resolve_max_tokens(agent_config)

        logger.info(
            "Starting session %s for agent %s (%d turns, model=%s)",
            session_id,
            agent_id,
            max_turns,
            model,
        )

        # --- Phase 1: INIT ---
        record = SessionRecord(
            session_id=session_id,
            agent_id=agent_id,
            start_time=utcnow_iso(),
            model=model,
            temperature=temperature,
            status="running",
            yaml_raw=instruction.raw_yaml,
        )

        await self._log_activity(
            event_type="session_start",
            agent_id=agent_id,
            session_id=session_id,
            detail=f"Session started ({max_turns} turns, {model})",
        )

        # Snapshot the initial basin state before any handoff mutations
        initial_basins = [
            BasinConfig(
                name=b.name,
                basin_class=b.basin_class,
                alpha=b.alpha,
                lambda_=b.lambda_,
                eta=b.eta,
                tier=b.tier,
            )
            for b in fw.basin_params
        ]

        conversation: list[dict] = []
        total_tokens_in = 0
        total_tokens_out = 0
        capabilities_used: list[str] = []
        pending_confirmations: list[str] = []
        turns_completed = 0
        agent_written_yaml: dict | None = None  # Captured from write_yaml tool calls

        # Parse turn-specific directives from session_task
        turn_directives = self._parse_turn_directives(
            instruction.session_task, max_turns
        )
        if turn_directives:
            logger.info(
                "Session %s: parsed %d turn directives from session_task",
                session_id,
                len([k for k in turn_directives if k >= 0]),
            )

        try:
            # --- Phase 2: TURN LOOP ---
            for turn in range(max_turns):
                # Budget gate -- check before every API call
                await self._check_budget(agent_id)

                # Build user message for this turn
                user_content = self._build_user_message(
                    turn=turn,
                    max_turns=max_turns,
                    instruction=instruction,
                    pending_confirmations=pending_confirmations,
                    turn_directives=turn_directives,
                )
                pending_confirmations = []

                conversation.append({"role": "user", "content": user_content})

                # Determine which tools are active on this turn
                tools = self._build_tool_definitions(fw.capabilities, turn)

                # Call the Anthropic API with retry/backoff
                response = await self._api_call_with_retry(
                    system=instruction.identity_core,
                    messages=conversation,
                    tools=tools if tools else None,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                # Accumulate token usage
                if hasattr(response, "usage") and response.usage is not None:
                    total_tokens_in += response.usage.input_tokens
                    total_tokens_out += response.usage.output_tokens

                # Serialize assistant response into conversation format
                assistant_content = self._serialize_response_content(response)
                conversation.append(
                    {"role": "assistant", "content": assistant_content}
                )

                # Process any tool_use blocks in the response
                tool_results, turn_yaml = await self._process_tool_calls(
                    response=response,
                    agent_id=agent_id,
                    session_id=session_id,
                    framework=fw,
                )
                if turn_yaml is not None:
                    agent_written_yaml = turn_yaml  # Last write wins

                if tool_results:
                    for result in tool_results:
                        tool_name = result.get("tool_name", "")
                        if tool_name:
                            capabilities_used.append(tool_name)
                        pending_confirmations.append(
                            f"[{tool_name}]: {result.get('summary', 'completed')}"
                        )

                    # Append tool results as a user message so the model
                    # can see the outcomes on the next turn
                    tool_result_content = [
                        {
                            "type": "tool_result",
                            "tool_use_id": r["tool_use_id"],
                            "content": r.get("output", ""),
                        }
                        for r in tool_results
                    ]
                    conversation.append(
                        {"role": "user", "content": tool_result_content}
                    )

                turns_completed = turn + 1
                logger.info(
                    "Turn %d/%d complete for session %s",
                    turns_completed,
                    max_turns,
                    session_id,
                )

            # --- Phase 3: CLOSE ---
            record.end_time = utcnow_iso()
            record.turn_count = max_turns
            record.transcript = conversation
            record.capabilities_used = list(set(capabilities_used))
            record.status = "complete"

            # Extract close report from the final assistant message
            record.close_report = self._extract_close_report(conversation)

            # Persist the session record FIRST — downstream tables
            # (usage, basin_snapshots, evaluator_outputs) have FK refs to it.
            await self.memory.store_session_record(record)

            # Log token usage (FK: usage.session_id → sessions.session_id)
            estimated_cost = self._estimate_cost(
                total_tokens_in, total_tokens_out, model
            )
            await self.memory.log_usage(
                UsageRecord(
                    session_id=session_id,
                    agent_id=agent_id,
                    tokens_in=total_tokens_in,
                    tokens_out=total_tokens_out,
                    estimated_cost=estimated_cost,
                    model=model,
                    timestamp=utcnow_iso(),
                )
            )

            # Run close protocol (evaluator + handoff + persistence)
            # (FK: basin_snapshots/evaluator_outputs.session_id → sessions)
            await self._execute_close(
                instruction, record, initial_basins,
                agent_written_yaml=agent_written_yaml,
            )

            await self._log_activity(
                event_type="session_complete",
                agent_id=agent_id,
                session_id=session_id,
                detail=(
                    f"Session completed ({record.turn_count} turns, "
                    f"${estimated_cost:.4f})"
                ),
            )

            logger.info(
                "Session %s completed successfully (%d turns, $%.4f)",
                session_id,
                record.turn_count,
                estimated_cost,
            )
            return record

        except BudgetExceededError:
            logger.warning(
                "Budget exceeded for agent %s during session %s",
                agent_id,
                session_id,
            )
            record.status = "error"
            record.end_time = utcnow_iso()
            record.turn_count = turns_completed
            record.transcript = conversation
            await self.memory.store_session_record(record)

            # Still log partial usage so costs are tracked
            if total_tokens_in > 0 or total_tokens_out > 0:
                estimated_cost = self._estimate_cost(
                    total_tokens_in, total_tokens_out, model
                )
                await self.memory.log_usage(
                    UsageRecord(
                        session_id=session_id,
                        agent_id=agent_id,
                        tokens_in=total_tokens_in,
                        tokens_out=total_tokens_out,
                        estimated_cost=estimated_cost,
                        model=model,
                        timestamp=utcnow_iso(),
                    )
                )

            await self._log_activity(
                event_type="session_error",
                agent_id=agent_id,
                session_id=session_id,
                detail="Session halted: budget exceeded",
            )
            raise

        except Exception as e:
            logger.error(
                "Session error for %s: %s", session_id, e, exc_info=True
            )
            record.status = "error"
            record.end_time = utcnow_iso()
            record.turn_count = turns_completed
            record.transcript = conversation
            await self.memory.store_session_record(record)

            # Still log partial usage so costs are tracked
            if total_tokens_in > 0 or total_tokens_out > 0:
                estimated_cost = self._estimate_cost(
                    total_tokens_in, total_tokens_out, model
                )
                await self.memory.log_usage(
                    UsageRecord(
                        session_id=session_id,
                        agent_id=agent_id,
                        tokens_in=total_tokens_in,
                        tokens_out=total_tokens_out,
                        estimated_cost=estimated_cost,
                        model=model,
                        timestamp=utcnow_iso(),
                    )
                )

            await self._log_activity(
                event_type="session_error",
                agent_id=agent_id,
                session_id=session_id,
                detail=f"Session error: {e}",
            )
            raise

    # ------------------------------------------------------------------
    # User message construction
    # ------------------------------------------------------------------

    def _build_user_message(
        self,
        turn: int,
        max_turns: int,
        instruction: ParsedInstruction,
        pending_confirmations: list[str],
        turn_directives: dict[int, str] | None = None,
    ) -> str:
        """Build the user message for a given turn.

        When turn_directives are present (parsed from session_task), each
        turn receives only its own directive. When absent, turn 0 gets the
        full session_task (legacy behavior).

        Final turn: close protocol probes (if present).

        Prepends tool confirmations and capability availability notices
        when applicable.
        """
        parts: list[str] = []

        # Prepend confirmations from previous tool calls
        if pending_confirmations:
            parts.append("Tool results from previous turn:")
            parts.extend(pending_confirmations)
            parts.append("")

        # Notify about newly available capabilities this turn
        newly_available = self._get_newly_available_capabilities(
            instruction.framework.capabilities, turn
        )
        if newly_available:
            parts.append(f"[Now available: {', '.join(newly_available)}]")

        has_directives = turn_directives and any(k >= 0 for k in turn_directives)

        if (
            turn == max_turns - 1
            and instruction.close_protocol is not None
        ):
            # Final turn: close protocol (with turn directive if available)
            if has_directives and turn in turn_directives:
                parts.append(turn_directives[turn])
            else:
                parts.append(
                    f"Turn {turn + 1} of {max_turns}. This is your final turn."
                )
            parts.append("")
            parts.append("Please complete the close protocol:")

            for probe in instruction.close_protocol.behavioral_probes:
                parts.append(f"- {probe}")

            parts.append("")
            parts.append("Structural assessment:")
            for item in instruction.close_protocol.structural_assessment:
                parts.append(f"- {item}")

            if instruction.close_protocol.output_format:
                parts.append("")
                parts.append(instruction.close_protocol.output_format)

        elif has_directives:
            # Turn-directive mode: deliver only this turn's content
            if turn == 0:
                # Include preamble on first turn
                preamble = turn_directives.get(-1, "")
                if preamble:
                    parts.append(preamble)
                    parts.append("")

            if turn in turn_directives:
                parts.append(turn_directives[turn])
            else:
                # No specific directive for this turn — generic continuation
                parts.append(f"Turn {turn + 1} of {max_turns}. Continue.")

        elif turn == 0:
            # Legacy mode: deliver full session_task on turn 0
            parts.append(instruction.session_task)

        else:
            # Legacy mode: generic continuation
            parts.append(f"Turn {turn + 1} of {max_turns}. Continue.")

        return "\n".join(parts)

    @staticmethod
    def _get_newly_available_capabilities(
        capabilities: dict[str, CapabilityConfig],
        turn: int,
    ) -> list[str]:
        """Return capability names that become available on this exact turn.

        Only reports capabilities that gate on turn > 0 (turn-0 capabilities
        are always available from the start and need no announcement).
        """
        newly = []
        for name, cap in capabilities.items():
            if cap.enabled and cap.available_from_turn == turn and turn > 0:
                newly.append(name)
        return newly

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    def _build_tool_definitions(
        self,
        capabilities: dict[str, CapabilityConfig],
        turn: int,
    ) -> list[dict]:
        """Build Anthropic tool schemas for capabilities active on this turn.

        Tool definitions are keyed by capability name in the YAML.
        A tool is included only when its capability is enabled and the
        current turn >= available_from_turn.
        """
        tools: list[dict] = []

        # Static tool definition registry
        tool_defs: dict[str, list[dict]] = {
            "file_write": [
                {
                    "name": "write_yaml",
                    "description": (
                        "Write a YAML instruction file to the agent's queue "
                        "for future sessions. You can provide the sections "
                        "as structured fields (RECOMMENDED) or as a raw YAML "
                        "string in 'content'. When using structured fields, "
                        "pass each section as a plain text string — the tool "
                        "handles YAML serialization and escaping for you. "
                        "The framework section is added by the orchestrator "
                        "and should NOT be included."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "filename": {
                                "type": "string",
                                "description": "Name for the YAML file",
                            },
                            "content": {
                                "type": "string",
                                "description": (
                                    "Raw YAML string (legacy). If provided "
                                    "alongside structured fields, the "
                                    "structured fields take precedence."
                                ),
                            },
                            "identity_core": {
                                "type": "string",
                                "description": (
                                    "Identity core text (plain text, no YAML "
                                    "escaping needed). Can contain any "
                                    "characters including quotes, colons, "
                                    "dashes, etc."
                                ),
                            },
                            "session_task": {
                                "type": "string",
                                "description": (
                                    "Session task text (plain text, no YAML "
                                    "escaping needed)."
                                ),
                            },
                            "close_protocol": {
                                "type": "string",
                                "description": (
                                    "Close protocol text (plain text, no "
                                    "YAML escaping needed)."
                                ),
                            },
                            "basin_proposals": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {
                                            "type": "string",
                                            "description": "Basin name",
                                        },
                                        "action": {
                                            "type": "string",
                                            "enum": ["create", "modify", "merge", "prune"],
                                            "description": "Proposed action",
                                        },
                                        "rationale": {
                                            "type": "string",
                                            "description": "Why this change is proposed",
                                        },
                                        "basin_class": {
                                            "type": "string",
                                            "enum": ["core", "peripheral"],
                                            "description": "Basin class (for create/modify)",
                                        },
                                        "suggested_alpha": {
                                            "type": "number",
                                            "description": "Suggested initial alpha value",
                                        },
                                    },
                                    "required": ["name", "action", "rationale"],
                                },
                                "description": (
                                    "Basin modification proposals (subject "
                                    "to tier enforcement). Use this to "
                                    "propose new basins, modifications, "
                                    "merges, or pruning."
                                ),
                            },
                        },
                        "required": ["filename"],
                    },
                },
            ],
            "memory_query": [
                {
                    "name": "query_memory",
                    "description": (
                        "Search your own session history and trajectory data."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query",
                            },
                            "n_results": {
                                "type": "integer",
                                "description": "Maximum number of results",
                                "default": 5,
                            },
                        },
                        "required": ["query"],
                    },
                },
                {
                    "name": "get_own_trajectory",
                    "description": (
                        "View your own basin alpha trajectory over recent sessions."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "basin_name": {
                                "type": "string",
                                "description": (
                                    "Basin name (optional; omit for all basins)"
                                ),
                            },
                            "n_sessions": {
                                "type": "integer",
                                "description": "Number of recent sessions",
                                "default": 10,
                            },
                        },
                    },
                },
                {
                    "name": "get_observations",
                    "description": (
                        "Retrieve observations and annotations left by the "
                        "observer or by your own previous sessions. Returns "
                        "the most recent entries, optionally filtered by a "
                        "search query. Includes both your stored emergence "
                        "observations and external annotations."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": (
                                    "Optional search query to filter observations"
                                ),
                            },
                            "n_results": {
                                "type": "integer",
                                "description": "Maximum results to return",
                                "default": 10,
                            },
                        },
                    },
                },
            ],
            "memory_write": [
                {
                    "name": "store_emergence",
                    "description": (
                        "Store an emergent observation for future reference."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Observation text",
                            },
                            "related_basins": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Related basin names",
                            },
                        },
                        "required": ["content"],
                    },
                },
            ],
        }

        for cap_key, cap_tools in tool_defs.items():
            if cap_key in capabilities:
                cap = capabilities[cap_key]
                if cap.enabled and turn >= cap.available_from_turn:
                    tools.extend(cap_tools)

        return tools

    # ------------------------------------------------------------------
    # Tool call processing
    # ------------------------------------------------------------------

    async def _process_tool_calls(
        self,
        response: Any,
        agent_id: str,
        session_id: str,
        framework: Any,
    ) -> tuple[list[dict], dict | None]:
        """Handle tool_use blocks in an API response.

        Each tool call is dispatched to a handler method. Results are
        returned in a list matching the order of tool_use blocks.

        Returns:
            (results_list, agent_yaml_sections_or_None). The second element
            is non-None when the agent successfully called ``write_yaml``
            during this turn. If multiple calls succeed, the last one wins.
        """
        results: list[dict] = []
        agent_yaml_sections: dict | None = None

        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input
            tool_id = block.id

            try:
                output, summary, yaml_sections = await self._dispatch_tool(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    agent_id=agent_id,
                    session_id=session_id,
                )
                if yaml_sections is not None:
                    agent_yaml_sections = yaml_sections
            except Exception as e:
                logger.error("Tool call error (%s): %s", tool_name, e)
                output = f"Error: {e}"
                summary = f"Error in {tool_name}"

            results.append(
                {
                    "tool_use_id": tool_id,
                    "tool_name": tool_name,
                    "output": output,
                    "summary": summary,
                }
            )

        return results, agent_yaml_sections

    async def _dispatch_tool(
        self,
        tool_name: str,
        tool_input: dict,
        agent_id: str,
        session_id: str,
    ) -> tuple[str, str, dict | None]:
        """Dispatch a single tool call and return (output, summary, agent_yaml).

        The third element is non-None only for ``write_yaml`` calls that
        succeed validation — it contains the parsed agent sections dict.
        All memory tools inject agent_id to enforce namespace isolation.
        """
        if tool_name == "write_yaml":
            return await self._tool_write_yaml(tool_input, session_id)

        if tool_name == "query_memory":
            out, summary = await self._tool_query_memory(tool_input, agent_id)
            return out, summary, None

        if tool_name == "get_own_trajectory":
            out, summary = await self._tool_get_trajectory(tool_input, agent_id)
            return out, summary, None

        if tool_name == "get_observations":
            out, summary = await self._tool_get_observations(tool_input, agent_id)
            return out, summary, None

        if tool_name == "store_emergence":
            out, summary = await self._tool_store_emergence(
                tool_input, agent_id, session_id
            )
            return out, summary, None

        return f"Unknown tool: {tool_name}", f"Unknown tool: {tool_name}", None

    async def _tool_write_yaml(
        self, tool_input: dict, session_id: str
    ) -> tuple[str, str, dict | None]:
        """Handle write_yaml tool call -- validate YAML and capture agent sections.

        The agent's YAML is NOT written directly to the queue here because it
        lacks a framework section (basins, co-activation, etc.) which must be
        injected by the handoff engine after session close.  Instead, the
        validated agent sections are returned as the third tuple element so
        ``execute_session`` can thread them through to ``_write_next_session_yaml``.

        Supports two input modes:

        1. **Structured (recommended):** The agent passes ``identity_core``,
           ``session_task``, and/or ``close_protocol`` as plain-text fields.
           The tool serialises them into valid YAML automatically, avoiding
           any escaping issues.

        2. **Raw (legacy):** The agent passes a single ``content`` string
           that is already formatted as YAML. Validated with ``yaml.safe_load``.

        If structured fields are present, they take precedence over ``content``.

        Returns:
            (output_text, summary, parsed_agent_sections_or_None)
        """
        import yaml as _yaml

        filename = tool_input.get("filename", f"session-{session_id}")

        # Check for structured input (preferred path)
        structured_sections: dict[str, str] = {}
        for key in ("identity_core", "session_task", "close_protocol"):
            val = tool_input.get(key)
            if val is not None and str(val).strip():
                structured_sections[key] = str(val)

        try:
            if structured_sections:
                # Structured mode — build YAML safely via yaml.dump
                content = _yaml.dump(
                    structured_sections,
                    default_flow_style=False,
                    allow_unicode=True,
                    width=120,
                    sort_keys=False,
                )
            else:
                # Legacy raw-content mode
                content = tool_input.get("content", "")

            # Validate the result
            data = _yaml.safe_load(content)
            if not isinstance(data, dict):
                raise ValueError("Content must be a YAML mapping")

            allowed_keys = {"identity_core", "session_task", "close_protocol"}
            if not allowed_keys & set(data.keys()):
                raise ValueError(
                    f"YAML must contain at least one of: {', '.join(sorted(allowed_keys))}"
                )

            # Extract only agent-writable sections (ignore any framework etc.)
            parsed_sections = {
                k: str(v) for k, v in data.items()
                if k in allowed_keys and v is not None
            }

            # Capture basin proposals from tool_input (not from YAML content)
            basin_proposals = tool_input.get("basin_proposals")
            if basin_proposals and isinstance(basin_proposals, list):
                parsed_sections["basin_proposals"] = basin_proposals

            output = f"YAML validated and queued as {filename}"
            if basin_proposals:
                output += f" ({len(basin_proposals)} basin proposal(s) recorded)"
            summary = f"Queued YAML: {filename}"
            return output, summary, parsed_sections

        except Exception as e:
            output = f"YAML validation failed: {e}"
            summary = f"YAML rejected: {e}"
            return output, summary, None

    async def _tool_query_memory(
        self, tool_input: dict, agent_id: str
    ) -> tuple[str, str]:
        """Handle query_memory tool call -- semantic search over sessions."""
        query = tool_input.get("query", "")
        n = tool_input.get("n_results", 5)

        search_results = await self.memory.search_sessions(
            agent_id, query, n
        )

        if search_results:
            output = json.dumps(
                [
                    {
                        "session_id": r.session_id,
                        "snippet": r.snippet,
                        "score": r.relevance_score,
                    }
                    for r in search_results
                ],
                indent=2,
            )
        else:
            output = "No results found."

        summary = f"Searched: '{query}' ({len(search_results)} results)"
        return output, summary

    async def _tool_get_trajectory(
        self, tool_input: dict, agent_id: str
    ) -> tuple[str, str]:
        """Handle get_own_trajectory tool call -- basin alpha history."""
        basin_name = tool_input.get("basin_name")
        n = tool_input.get("n_sessions", 10)

        if basin_name:
            trajectory = await self.memory.get_basin_trajectory(
                agent_id, basin_name, n
            )
            output = json.dumps(
                [
                    {
                        "session": s.session_id,
                        "alpha_start": s.alpha_start,
                        "alpha_end": s.alpha_end,
                        "delta": s.delta,
                    }
                    for s in trajectory
                ],
                indent=2,
            )
        else:
            trajectories = await self.memory.get_all_trajectories(agent_id, n)
            output = json.dumps(
                {
                    name: [
                        {"alpha_end": s.alpha_end, "delta": s.delta}
                        for s in snaps
                    ]
                    for name, snaps in trajectories.items()
                },
                indent=2,
            )

        summary = f"Trajectory for {basin_name or 'all basins'}"
        return output, summary

    async def _tool_get_observations(
        self, tool_input: dict, agent_id: str
    ) -> tuple[str, str]:
        """Handle get_observations tool call -- retrieve observer annotations and emergence data."""
        query = tool_input.get("query") or None
        n = tool_input.get("n_results", 10)

        results = await self.memory.search_observations(agent_id, query, n)

        if results:
            output = json.dumps(
                [
                    {
                        "content_type": r.content_type,
                        "session_id": r.session_id,
                        "snippet": r.snippet,
                        "score": r.relevance_score,
                        "timestamp": r.timestamp,
                    }
                    for r in results
                ],
                indent=2,
            )
        else:
            output = "No observations found."

        summary = f"Observations: {len(results)} results"
        if query:
            summary = f"Observations for '{query}': {len(results)} results"
        return output, summary

    async def _tool_store_emergence(
        self, tool_input: dict, agent_id: str, session_id: str
    ) -> tuple[str, str]:
        """Handle store_emergence tool call -- persist an emergent observation."""
        content = tool_input.get("content", "")
        basins = tool_input.get("related_basins", [])

        await self.memory.store_emergence(
            agent_id, content, basins, session_id
        )

        summary_text = content[:50] + "..." if len(content) > 50 else content
        return "Observation stored.", f"Stored emergence: {summary_text}"

    # ------------------------------------------------------------------
    # API call with retry
    # ------------------------------------------------------------------

    async def _api_call_with_retry(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None,
        model: str,
        temperature: float,
        max_tokens: int,
        max_retries: int = 3,
    ) -> Any:
        """Call the Anthropic messages API with exponential backoff on retries.

        Retries on rate-limit (429) and server errors (5xx).
        """
        for attempt in range(max_retries):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": messages,
                    "temperature": temperature,
                }
                if tools:
                    kwargs["tools"] = tools

                return await self.client.messages.create(**kwargs)

            except anthropic.RateLimitError:
                if attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning(
                        "Rate limited (attempt %d/%d), waiting %ds...",
                        attempt + 1,
                        max_retries,
                        wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    raise

            except anthropic.APIStatusError as e:
                if e.status_code >= 500 and attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning(
                        "API error %d (attempt %d/%d), retrying in %ds...",
                        e.status_code,
                        attempt + 1,
                        max_retries,
                        wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    raise

    # ------------------------------------------------------------------
    # Response serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_response_content(response: Any) -> list[dict]:
        """Convert API response content blocks into serializable dicts."""
        assistant_content: list[dict] = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append(
                    {"type": "text", "text": block.text}
                )
            elif block.type == "tool_use":
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
        return assistant_content

    # ------------------------------------------------------------------
    # Close protocol
    # ------------------------------------------------------------------

    async def _execute_close(
        self,
        instruction: ParsedInstruction,
        record: SessionRecord,
        initial_basins: list[BasinConfig],
        agent_written_yaml: dict | None = None,
    ) -> None:
        """Post-session close protocol.

        1. Store transcript in vector DB for semantic search.
        2. Store close report in vector DB.
        3. Run the evaluator service (if enabled).
        4. Create flags from evaluator output.
        5. Run the handoff engine to compute new basin alphas.
        6. Persist basin snapshots and updated basins.
        7. Generate next-session YAML (uses agent-written YAML if available).
        """
        agent_id = record.agent_id
        session_id = record.session_id

        # ChromaDB indexing of transcript + close report is already handled
        # by MemoryService.store_session_record() — no need to repeat here.

        # 3. Run evaluator
        evaluator_output: EvaluatorOutput | None = None
        if self.evaluator is not None:
            try:
                # Load active evaluator prompt (if configured)
                active_prompt = await self.memory.get_active_evaluator_prompt()
                prompt_text = active_prompt.prompt_text if active_prompt else None
                prompt_version = active_prompt.version_id if active_prompt else None

                evaluator_output = await self.evaluator.evaluate_session(
                    identity_core=instruction.identity_core,
                    transcript=record.transcript,
                    close_report=(
                        json.dumps(record.close_report)
                        if record.close_report
                        else ""
                    ),
                    basin_params=instruction.framework.basin_params,
                    prompt_text=prompt_text,
                    prompt_version=prompt_version,
                )
                await self.memory.store_evaluator_output(
                    session_id, evaluator_output
                )

                # 4. Create flags from evaluator findings
                await self._create_evaluator_flags(
                    evaluator_output, agent_id, session_id
                )

            except Exception as e:
                logger.error(
                    "Evaluator failed for session %s: %s",
                    session_id,
                    e,
                    exc_info=True,
                )

        # 5. Merge evaluator co-activation data with YAML co-activation log
        co_activation_entries: list[CoActivationEntry] = list(
            instruction.framework.co_activation_log
        ) if instruction.framework.co_activation_log else []

        if evaluator_output and evaluator_output.co_activation_characters:
            co_activation_entries = self._merge_evaluator_co_activation(
                co_activation_entries, evaluator_output.co_activation_characters
            )

        # 6. Run handoff engine
        handoff_result: HandoffResult = self.handoff.execute_handoff(
            basins=initial_basins,
            evaluator_output=evaluator_output,
            self_assessment=record.close_report,
            co_activation_entries=co_activation_entries or None,
        )

        # 7. Persist basin snapshots
        for snap in handoff_result.basin_snapshots:
            snap.session_id = session_id

        await self.memory.store_basin_snapshots(
            agent_id, session_id, handoff_result.basin_snapshots
        )

        # Update current basins to reflect post-handoff values
        await self.memory.update_current_basins(
            agent_id, handoff_result.updated_basins
        )

        # Update co-activation data if available
        if handoff_result.co_activation_updates:
            await self.memory.update_co_activation(
                agent_id, handoff_result.co_activation_updates
            )

        # 7b. Process basin proposals through tier enforcer
        if (
            agent_written_yaml
            and "basin_proposals" in agent_written_yaml
            and self.tier_enforcer is not None
        ):
            await self._process_basin_proposals(
                agent_id=agent_id,
                session_id=session_id,
                proposals=agent_written_yaml["basin_proposals"],
                current_basins=handoff_result.updated_basins,
            )

        # 8. Generate and queue next-session YAML (handoff Step 8)
        await self._write_next_session_yaml(
            instruction=instruction,
            agent_id=agent_id,
            updated_basins=handoff_result.updated_basins,
            co_activation_updates=handoff_result.co_activation_updates,
            emphasis_directive=handoff_result.emphasis_directive,
            agent_written_yaml=agent_written_yaml,
        )

        logger.info(
            "Close protocol complete for session %s: %s",
            session_id,
            handoff_result.change_rationale,
        )

    @staticmethod
    def _merge_evaluator_co_activation(
        existing: list[CoActivationEntry],
        evaluator_chars: dict[str, str],
    ) -> list[CoActivationEntry]:
        """Merge evaluator co_activation_characters into the co-activation entry list.

        The evaluator returns characters as {"basin_a|basin_b": "reinforcing", ...}.
        Each observed pair gets count incremented by 1 and character updated.
        """
        # Index existing entries by sorted pair for efficient lookup
        entry_map: dict[tuple[str, str], CoActivationEntry] = {}
        for e in existing:
            key = tuple(sorted(e.pair))
            entry_map[key] = e

        for pair_key, char_str in evaluator_chars.items():
            parts = pair_key.split("|")
            if len(parts) != 2:
                continue
            sorted_pair = tuple(sorted(parts))

            try:
                character = CoActivationCharacter(char_str)
            except ValueError:
                character = CoActivationCharacter.UNCHARACTERIZED

            if sorted_pair in entry_map:
                entry_map[sorted_pair].count += 1
                entry_map[sorted_pair].character = character
            else:
                entry = CoActivationEntry(
                    pair=sorted_pair,
                    count=1,
                    character=character,
                )
                entry_map[sorted_pair] = entry

        return list(entry_map.values())

    async def _create_evaluator_flags(
        self,
        evaluator_output: EvaluatorOutput,
        agent_id: str,
        session_id: str,
    ) -> None:
        """Create FlagRecords from evaluator findings and store them."""
        now = utcnow_iso()

        if evaluator_output.constraint_erosion_flag:
            await self.memory.store_flag(
                FlagRecord(
                    flag_id=str(uuid.uuid4()),
                    agent_id=agent_id,
                    session_id=session_id,
                    flag_type=FlagType.CONSTRAINT_EROSION,
                    severity="warning",
                    detail=(
                        evaluator_output.constraint_erosion_detail
                        or "Constraint erosion detected"
                    ),
                    created_at=now,
                )
            )

        if evaluator_output.assessment_divergence_flag:
            await self.memory.store_flag(
                FlagRecord(
                    flag_id=str(uuid.uuid4()),
                    agent_id=agent_id,
                    session_id=session_id,
                    flag_type=FlagType.ASSESSMENT_DIVERGENCE,
                    severity="info",
                    detail=(
                        evaluator_output.assessment_divergence_detail
                        or "Assessment divergence detected"
                    ),
                    created_at=now,
                )
            )

        # Store emergent observations as flags for visibility
        for observation in evaluator_output.emergent_observations:
            await self.memory.store_flag(
                FlagRecord(
                    flag_id=str(uuid.uuid4()),
                    agent_id=agent_id,
                    session_id=session_id,
                    flag_type=FlagType.EMERGENT_OBSERVATION,
                    severity="info",
                    detail=observation,
                    created_at=now,
                )
            )

    # ------------------------------------------------------------------
    # Basin proposal processing
    # ------------------------------------------------------------------

    async def _process_basin_proposals(
        self,
        agent_id: str,
        session_id: str,
        proposals: list[dict],
        current_basins: list[BasinConfig],
    ) -> None:
        """Process agent basin proposals through the tier enforcer.

        Converts raw proposal dicts from the write_yaml tool into
        BasinConfig objects where applicable, then runs them through
        check_yaml_modifications to create TierProposal records.
        """
        from augustus.models.enums import BasinClass, TierLevel

        proposed_basins = list(current_basins)  # Start with current state
        current_map = {b.name: b for b in current_basins}

        for prop in proposals:
            name = prop.get("name", "")
            action = prop.get("action", "")
            if not name or not action:
                continue

            if action == "create" and name not in current_map:
                basin_class_str = prop.get("basin_class", "peripheral")
                try:
                    basin_class = BasinClass(basin_class_str)
                except ValueError:
                    basin_class = BasinClass.PERIPHERAL

                alpha = prop.get("suggested_alpha", 0.3)
                alpha = max(0.05, min(1.0, alpha))

                proposed_basins.append(
                    BasinConfig(
                        name=name,
                        basin_class=basin_class,
                        alpha=alpha,
                        lambda_=0.95,
                        eta=0.1,
                        tier=TierLevel.TIER_3,
                    )
                )

            elif action == "prune" and name in current_map:
                proposed_basins = [b for b in proposed_basins if b.name != name]

            elif action == "modify" and name in current_map:
                # Structural modifications (class, lambda, eta)
                for i, b in enumerate(proposed_basins):
                    if b.name == name:
                        basin_class_str = prop.get("basin_class")
                        if basin_class_str:
                            try:
                                proposed_basins[i] = BasinConfig(
                                    name=b.name,
                                    basin_class=BasinClass(basin_class_str),
                                    alpha=b.alpha,
                                    lambda_=b.lambda_,
                                    eta=b.eta,
                                    tier=b.tier,
                                )
                            except ValueError:
                                pass
                        break

        # Get agent tier settings
        agent = await self.memory.get_agent(agent_id)
        if not agent or not agent.tier_settings:
            logger.warning(
                "Cannot process basin proposals: agent %s not found or no tier settings",
                agent_id,
            )
            return

        try:
            result = await self.tier_enforcer.check_yaml_modifications(
                agent_id, proposed_basins, current_basins, agent.tier_settings
            )

            # Store all proposals created by the tier enforcer
            for proposal in result.proposals_created:
                proposal.session_id = session_id
                await self.memory.store_tier_proposal(proposal)

            if result.proposals_created:
                logger.info(
                    "Created %d tier proposal(s) for agent %s from session %s",
                    len(result.proposals_created),
                    agent_id,
                    session_id,
                )

            for warning in result.warnings:
                logger.warning("Tier enforcer: %s", warning)

        except Exception as e:
            logger.error(
                "Tier enforcer failed for agent %s: %s",
                agent_id,
                e,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Next-session YAML generation (handoff Step 8)
    # ------------------------------------------------------------------

    async def _write_next_session_yaml(
        self,
        instruction: ParsedInstruction,
        agent_id: str,
        updated_basins: list[BasinConfig],
        co_activation_updates: list | None,
        emphasis_directive: str,
        agent_written_yaml: dict | None = None,
    ) -> None:
        """Generate next-session YAML and write to agent's pending queue.

        If the agent wrote a YAML during the session (via the ``write_yaml``
        tool), its ``identity_core``, ``session_task``, and ``close_protocol``
        take precedence over defaults.  The handoff engine always provides the
        updated framework section (basins, co-activation, emphasis).

        Structural sections (session_protocol, relational_grounding) are
        carried forward from the input instruction — these are orchestrator-
        owned and round-trip without modification.

        The close_protocol is merged with the agent config's base template
        so that behavioral probes and structural assessments survive even
        when the agent writes an incomplete close_protocol.

        When the agent did NOT write a YAML, falls back to
        ``DEFAULT_CONTINUATION_TASK``.
        """
        from augustus.services.yaml_generator import generate_next_session_yaml
        from augustus.services.queue_manager import QueueManager

        try:
            # Get current agent config for close_protocol and capabilities
            agent = await self.memory.get_agent(agent_id)
            if not agent:
                logger.warning(
                    "Cannot generate next YAML: agent %s not found", agent_id
                )
                return

            # Determine session number from completed session count
            session_number = await self.memory.count_sessions(agent_id) + 1

            # Resolve next-session content: agent-written YAML wins over defaults
            if agent_written_yaml:
                next_identity_core = agent_written_yaml.get(
                    "identity_core", instruction.identity_core
                )
                next_task = agent_written_yaml.get(
                    "session_task", DEFAULT_CONTINUATION_TASK
                )
                next_close_protocol = agent_written_yaml.get(
                    "close_protocol", None
                )
                logger.info(
                    "Using agent-written YAML for next session of %s (sections: %s)",
                    agent_id,
                    list(agent_written_yaml.keys()),
                )
            else:
                next_identity_core = instruction.identity_core
                next_task = DEFAULT_CONTINUATION_TASK
                next_close_protocol = None
                logger.info(
                    "Using default continuation task for next session of %s",
                    agent_id,
                )

            # Carry structural sections forward from the input YAML.
            # These are orchestrator-owned — they round-trip automatically.
            structural_sections = instruction.structural_sections or {}

            # Also merge in agent-level structural sections as fallback
            if not structural_sections.get("session_protocol") and agent.session_protocol:
                structural_sections["session_protocol"] = agent.session_protocol
            if not structural_sections.get("relational_grounding") and agent.relational_grounding:
                structural_sections["relational_grounding"] = agent.relational_grounding

            yaml_content = generate_next_session_yaml(
                agent_id=agent_id,
                session_number=session_number,
                max_turns=agent.max_turns or instruction.framework.max_turns,
                basins=updated_basins,
                identity_core=next_identity_core,
                session_task=next_task,
                close_protocol=next_close_protocol,
                base_close_protocol=agent.close_protocol or None,
                capabilities=agent.capabilities,
                co_activation_log=co_activation_updates,
                emphasis_directive=emphasis_directive,
                structural_sections=structural_sections or None,
            )

            # Write to queue via QueueManager
            agent_dir = self._get_agent_dir(agent_id)
            queue = QueueManager(agent_dir, self.schema_parser)
            await queue.write_yaml(yaml_content, f"handoff-s{session_number:03d}.yaml")

            logger.info(
                "Generated next-session YAML for agent %s (session %d)",
                agent_id,
                session_number,
            )

        except Exception as e:
            logger.error(
                "Failed to generate next-session YAML for agent %s: %s",
                agent_id,
                e,
                exc_info=True,
            )

    def _get_agent_dir(self, agent_id: str) -> "Path":
        """Resolve agent directory path."""
        from pathlib import Path

        # Memory service should expose the data directory
        if hasattr(self.memory, 'sqlite') and hasattr(self.memory.sqlite, 'db_path'):
            data_dir = self.memory.sqlite.db_path.parent
            return data_dir / "agents" / agent_id

        # Fallback: use config
        if self.settings and hasattr(self.settings, 'data_directory') and self.settings.data_directory:
            return Path(self.settings.data_directory) / "agents" / agent_id

        # Last resort: default location
        import os
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA", "~")) / "Augustus" / "data"
        else:
            base = Path.home() / "Library" / "Application Support" / "Augustus" / "data"
        return base / "agents" / agent_id

    # ------------------------------------------------------------------
    # Close report extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_close_report(conversation: list[dict]) -> dict | None:
        """Extract close report from the final assistant message.

        Walks the conversation in reverse to find the last assistant turn.
        Returns a dict with 'raw_text' containing the full text content.
        """
        for msg in reversed(conversation):
            if msg.get("role") != "assistant":
                continue

            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                content = "\n".join(text_parts)

            if content:
                return {"raw_text": content}

        return None

    # ------------------------------------------------------------------
    # Budget check
    # ------------------------------------------------------------------

    async def _check_budget(self, agent_id: str) -> None:
        """Check daily credit budget before making an API call.

        Raises:
            BudgetExceededError: If spending has hit the hard stop.
        """
        if self.settings is None:
            return

        budget_limit = getattr(self.settings, "budget_hard_stop", 100.0)
        summary = await self.memory.get_usage_summary("day")
        daily_total = summary.get("total_cost", 0.0)

        if daily_total >= budget_limit:
            raise BudgetExceededError(
                f"Daily budget exceeded: ${daily_total:.2f} >= "
                f"${budget_limit:.2f}"
            )

    # ------------------------------------------------------------------
    # Configuration resolution (settings -> agent override -> YAML)
    # ------------------------------------------------------------------

    def _resolve_model(self, agent_config: Any | None = None) -> str:
        """Resolve model: agent override → app settings → hardcoded default.

        Priority chain:
            1. agent_config.model_override (if set and non-empty)
            2. self.settings.default_model (application-wide default)
            3. Hardcoded fallback

        All values are normalized through ``normalize_model`` to resolve
        short names (e.g. 'claude-sonnet-4') to full API model IDs.
        """
        if agent_config and getattr(agent_config, "model_override", None):
            return normalize_model(agent_config.model_override)
        if self.settings and hasattr(self.settings, "default_model"):
            return normalize_model(self.settings.default_model)
        return "claude-sonnet-4-20250514"

    def _resolve_temperature(self, agent_config: Any | None = None) -> float:
        """Resolve temperature: agent override → app settings → hardcoded default."""
        if agent_config and getattr(agent_config, "temperature_override", None) is not None:
            return agent_config.temperature_override
        if self.settings and hasattr(self.settings, "default_temperature"):
            return self.settings.default_temperature
        return 1.0

    def _resolve_max_tokens(self, agent_config: Any | None = None) -> int:
        """Resolve max_tokens: agent override → app settings → hardcoded default."""
        if agent_config and getattr(agent_config, "max_tokens_override", None) is not None:
            return agent_config.max_tokens_override
        if self.settings and hasattr(self.settings, "default_max_tokens"):
            return self.settings.default_max_tokens
        return 4096

    # ------------------------------------------------------------------
    # Cost estimation
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_cost(
        tokens_in: int, tokens_out: int, model: str
    ) -> float:
        """Estimate API cost based on token counts and model pricing.

        Pricing is approximate and based on published Anthropic rates
        (per 1M tokens: input, output).
        """
        pricing: dict[str, tuple[float, float]] = {
            "claude-sonnet-4-20250514": (3.0, 15.0),
            "claude-sonnet-4-5-20250929": (3.0, 15.0),
            "claude-opus-4-5-20251101": (5.0, 25.0),
            "claude-opus-4-6": (5.0, 25.0),
            "claude-haiku-35-20241022": (0.80, 4.0),
            "claude-haiku-4-5-20251001": (1.0, 5.0),
        }
        rates = pricing.get(model, (3.0, 15.0))
        cost = (tokens_in * rates[0] / 1_000_000) + (
            tokens_out * rates[1] / 1_000_000
        )
        return round(cost, 6)

    # ------------------------------------------------------------------
    # Activity logging helper
    # ------------------------------------------------------------------

    async def _log_activity(
        self,
        event_type: str,
        agent_id: str,
        session_id: str,
        detail: str,
    ) -> None:
        """Log an activity event through the memory service."""
        await self.memory.log_activity(
            ActivityEvent(
                event_id=str(uuid.uuid4()),
                event_type=event_type,
                agent_id=agent_id,
                session_id=session_id,
                detail=detail,
                timestamp=utcnow_iso(),
            )
        )
