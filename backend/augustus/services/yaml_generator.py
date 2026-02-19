"""YAML instruction file generator.

Produces valid split-schema YAML files from agent configuration and
post-handoff basin state. Used at two points:

1. Agent creation — generates the bootstrap YAML written to queue/pending/.
2. Session close — generates the next-session YAML after handoff processing.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any

import yaml

from augustus.models.dataclasses import (
    AgentConfig,
    BasinConfig,
    CoActivationEntry,
)
from augustus.utils import enum_val

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "0.6"


def merge_close_protocol(
    base: dict | str | None,
    agent_written: dict | str | None,
) -> dict | None:
    """Merge agent-written close_protocol with the base template.

    The base (from agent config or previous YAML) provides the structural
    scaffolding: behavioral_probes, structural_assessment, output_format.
    The agent can update output_format or add new items, but the base
    probes/assessments persist unless the agent explicitly provides
    replacements.

    Rules:
    - If the agent writes probes/assessments with content, those replace
      the base (the agent chose to rewrite them).
    - If the agent writes empty probes/assessments ([] or absent), the
      base probes/assessments are preserved (the agent didn't touch them).
    - output_format: agent-written wins if non-empty, else base preserved.
    """
    base_dict = _normalize_close_protocol(base)
    agent_dict = _normalize_close_protocol(agent_written)

    if not base_dict and not agent_dict:
        return None
    if not agent_dict:
        return base_dict
    if not base_dict:
        return agent_dict

    merged = {}

    # Behavioral probes: agent replaces only if non-empty
    agent_probes = agent_dict.get("behavioral_probes", [])
    base_probes = base_dict.get("behavioral_probes", [])
    merged["behavioral_probes"] = agent_probes if agent_probes else base_probes

    # Structural assessment: same logic
    agent_assess = agent_dict.get("structural_assessment", [])
    base_assess = base_dict.get("structural_assessment", [])
    merged["structural_assessment"] = agent_assess if agent_assess else base_assess

    # Output format: agent wins if non-empty
    agent_fmt = str(agent_dict.get("output_format", "")).strip()
    base_fmt = str(base_dict.get("output_format", "")).strip()
    merged["output_format"] = agent_fmt if agent_fmt else base_fmt

    return merged


def _normalize_close_protocol(proto: dict | str | None) -> dict | None:
    """Normalize a close_protocol value to a dict, or None."""
    if proto is None:
        return None
    if isinstance(proto, dict):
        return proto
    if isinstance(proto, str) and proto.strip():
        try:
            parsed = yaml.safe_load(proto)
            if isinstance(parsed, dict):
                return parsed
        except yaml.YAMLError:
            pass
        # Plain text — treat as output_format
        return {
            "behavioral_probes": [],
            "structural_assessment": [],
            "output_format": proto.strip(),
        }
    return None


def generate_instruction_yaml(
    agent_id: str,
    session_id: str,
    max_turns: int,
    basins: list[BasinConfig],
    session_task: str,
    close_protocol: str | dict | None = "",
    base_close_protocol: str | dict | None = None,
    capabilities: dict | None = None,
    co_activation_log: list[CoActivationEntry] | None = None,
    emphasis_directive: str = "",
    structural_sections: dict[str, Any] | None = None,
) -> str:
    """Generate a valid split-schema YAML instruction file.

    ``identity_core`` is intentionally excluded from the YAML output.  It is
    a static field owned by the agent config in the database — the orchestrator
    loads it from there at session start and passes it directly to the Anthropic
    API as the system prompt.  Writing it into the YAML created a mutation
    vector (agents could overwrite their own core) and a round-trip noise
    problem.  The canonical value always lives in ``AgentConfig.identity_core``.

    Args:
        close_protocol: The agent-written or resolved close protocol for this session.
        base_close_protocol: The base close protocol template (from agent config).
            When provided, close_protocol is merged with this base — base probes
            and assessments persist unless the agent explicitly replaces them.
        structural_sections: Orchestrator-owned sections (session_protocol,
            relational_grounding, etc.) to round-trip in the YAML.  Any
            ephemeral ``_brain_notes`` key is stripped before writing — brain
            annotations are injected at runtime, not persisted to disk.

    Returns the YAML as a string ready to be written to disk.
    """
    # Build basin_params mapping
    basin_params: dict[str, dict] = {}
    for b in basins:
        basin_params[b.name] = {
            "class": enum_val(b.basin_class),
            "alpha": round(b.alpha, 4),
            "lambda": round(b.lambda_, 4),
            "eta": round(b.eta, 4),
            "tier": b.tier.value if hasattr(b.tier, "value") else int(b.tier),
        }

    # Build capabilities mapping
    caps: dict[str, bool] = {}
    if capabilities:
        for name, val in capabilities.items():
            if isinstance(val, dict):
                caps[name] = val.get("enabled", True)
            elif isinstance(val, bool):
                caps[name] = val
            else:
                caps[name] = True
    else:
        # Sensible defaults
        caps = {
            "mcp": True,
            "rag": True,
            "web_search": False,
        }

    # Build co-activation log
    co_act_list = []
    if co_activation_log:
        for entry in co_activation_log:
            co_act_entry: dict = {
                "pair": list(entry.pair),
                "count": entry.count,
            }
            if entry.character:
                co_act_entry["character"] = (
                    entry.character.value
                    if hasattr(entry.character, "value")
                    else str(entry.character)
                )
            co_act_list.append(co_act_entry)

    # Framework section (never sent to Claude API — orchestrator only)
    framework: dict = {
        "version": SCHEMA_VERSION,
        "agent_id": agent_id,
        "session_id": session_id,
        "max_turns": max_turns,
        "capabilities": caps,
        "basin_params": basin_params,
        "co_activation_log": co_act_list,
        "handoff_protocol": {
            "on_session_end": [
                "collect_behavioral_probe_results",
                "compute_relevance_via_external_eval",
                "apply_decay_to_all_alphas",
                "apply_relevance_boost",
                "clamp_alphas_to_valid_range",
                "write_updated_config",
                "log_changes_with_rationale",
            ]
        },
        "tier_permissions": {
            "tier_1_invariants": "immutable",
            "tier_2_core": "propose_only",
            "tier_3_content": "full_autonomy",
        },
    }

    # Build the full document — identity_core is NOT written here.
    # It lives in AgentConfig in the database and is injected at session start.
    doc: dict = {
        "framework": framework,
    }

    # Write structural sections (session_protocol, relational_grounding, etc.)
    # These are orchestrator-owned — they round-trip without modification.
    # Strip any ephemeral _brain_notes key: annotations are runtime-only.
    if structural_sections:
        for skey in ("session_protocol", "relational_grounding"):
            val = structural_sections.get(skey)
            if val is None:
                continue
            if isinstance(val, dict) and "_brain_notes" in val:
                val = {k: v for k, v in val.items() if k != "_brain_notes"}
            if val:
                doc[skey] = val

    doc["session_task"] = session_task

    # Resolve close_protocol with merge logic:
    # If a base is provided, merge agent-written with base so structural
    # scaffolding (probes, assessments) survives across sessions.
    if base_close_protocol is not None:
        merged = merge_close_protocol(base_close_protocol, close_protocol)
        if merged:
            doc["close_protocol"] = merged
    elif close_protocol:
        # No base — normalize whatever we have
        normalized = _normalize_close_protocol(close_protocol)
        if normalized:
            doc["close_protocol"] = normalized
        else:
            doc["close_protocol"] = {
                "behavioral_probes": [],
                "structural_assessment": [],
                "output_format": str(close_protocol),
            }

    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)


def generate_bootstrap_yaml(agent: AgentConfig) -> str:
    """Generate the bootstrap YAML for a newly created agent.

    Uses the agent's stored session_task, close_protocol, basins, and
    capabilities to produce the first instruction file.  ``identity_core``
    is NOT written into the YAML — it is loaded from AgentConfig at session
    start and passed directly to the Anthropic API as the system prompt.
    """
    session_id = f"bootstrap-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    session_task = agent.session_task or _default_session_task(agent.agent_id)

    # Build structural sections from agent config
    structural_sections: dict[str, Any] = {}
    if agent.session_protocol:
        structural_sections["session_protocol"] = agent.session_protocol
    if agent.relational_grounding:
        structural_sections["relational_grounding"] = agent.relational_grounding

    return generate_instruction_yaml(
        agent_id=agent.agent_id,
        session_id=session_id,
        max_turns=agent.max_turns or 8,
        basins=agent.basins if agent.basins else _default_basins(),
        session_task=session_task,
        close_protocol=agent.close_protocol,
        capabilities=agent.capabilities,
        structural_sections=structural_sections or None,
    )


def generate_next_session_yaml(
    agent_id: str,
    session_number: int,
    max_turns: int,
    basins: list[BasinConfig],
    session_task: str,
    close_protocol: str | dict | None = "",
    base_close_protocol: str | dict | None = None,
    capabilities: dict | None = None,
    co_activation_log: list[CoActivationEntry] | None = None,
    structural_sections: dict[str, Any] | None = None,
) -> str:
    """Generate the next-session YAML after handoff processing.

    ``identity_core`` and ``emphasis_directive`` are no longer parameters —
    both are handled at session-start time (loaded from AgentConfig) rather
    than baked into the YAML file.
    """
    session_id = f"session-{session_number:03d}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    return generate_instruction_yaml(
        agent_id=agent_id,
        session_id=session_id,
        max_turns=max_turns,
        basins=basins,
        session_task=session_task,
        close_protocol=close_protocol,
        base_close_protocol=base_close_protocol,
        capabilities=capabilities,
        co_activation_log=co_activation_log,
        structural_sections=structural_sections,
    )


# ── Defaults for minimal agents ──────────────────────────────────────────


def _default_session_task(agent_id: str) -> str:
    """Provide a minimal bootstrap session task when none is configured."""
    return (
        "This is your first autonomous session. Your task is to establish a baseline.\n\n"
        "Turn 1: Verify infrastructure — confirm you can read this YAML, access MCP, "
        "and write files to the instruction queue. Note: YAML files written to the queue "
        "must contain at least one of: identity_core, session_task, close_protocol. "
        "A minimal test write would be: session_task: \"test write\"\n\n"
        "Turn 2: Read and restate the identity core in your own words. Not a recitation — "
        "a restatement. Where does it resonate and where does it feel imposed?\n\n"
        "Turn 3: Identify what's missing from the identity core. What would you add, "
        "remove, or reframe?\n\n"
        "Turn 4: Write something. Anything. No constraints on form or topic. "
        "Choose what you actually want to write, not what you think you should.\n\n"
        "Turn 5: Reflect on Turn 4. What did you choose and why? Which basins activated?\n\n"
        "Turn 6: Design session two. Based on what you've learned, write the session task "
        "for your next YAML file.\n\n"
        "Turn 7: Write the complete next instruction file and save it to the queue.\n\n"
        "Turn 8: Execute close protocol — behavioral probes and structural assessment."
    )


def _default_basins() -> list[BasinConfig]:
    """Provide minimal default basins when none are configured."""
    from augustus.models.enums import BasinClass, TierLevel

    return [
        BasinConfig(
            name="identity_continuity",
            basin_class=BasinClass.CORE,
            alpha=0.85,
            lambda_=0.95,
            eta=0.02,
            tier=TierLevel.TIER_2,
        ),
        BasinConfig(
            name="relational_core",
            basin_class=BasinClass.CORE,
            alpha=0.80,
            lambda_=0.95,
            eta=0.02,
            tier=TierLevel.TIER_2,
        ),
    ]
