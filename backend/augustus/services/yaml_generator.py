"""YAML instruction file generator.

Produces valid split-schema YAML files from agent configuration and
post-handoff basin state. Used at two points:

1. Agent creation — generates the bootstrap YAML written to queue/pending/.
2. Session close — generates the next-session YAML after handoff processing.
"""

from __future__ import annotations

import logging
from datetime import datetime

import yaml

from augustus.models.dataclasses import (
    AgentConfig,
    BasinConfig,
    CoActivationEntry,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "0.2"


def generate_instruction_yaml(
    agent_id: str,
    session_id: str,
    max_turns: int,
    basins: list[BasinConfig],
    identity_core: str,
    session_task: str,
    close_protocol: str = "",
    capabilities: dict | None = None,
    co_activation_log: list[CoActivationEntry] | None = None,
    emphasis_directive: str = "",
) -> str:
    """Generate a valid split-schema YAML instruction file.

    Returns the YAML as a string ready to be written to disk.
    """
    # Build basin_params mapping
    basin_params: dict[str, dict] = {}
    for b in basins:
        basin_params[b.name] = {
            "class": b.basin_class.value if hasattr(b.basin_class, "value") else str(b.basin_class),
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

    # Inject emphasis directive into identity_core if present
    effective_identity_core = identity_core
    if emphasis_directive:
        effective_identity_core = identity_core.rstrip() + "\n\n" + emphasis_directive

    # Build the full document
    doc: dict = {
        "framework": framework,
        "identity_core": effective_identity_core,
        "session_task": session_task,
    }

    # Parse close_protocol: could be a raw string (from agent config)
    # or already a dict. Produce a proper close_protocol section.
    if close_protocol:
        if isinstance(close_protocol, dict):
            doc["close_protocol"] = close_protocol
        else:
            # Try to parse as YAML in case it's structured text
            try:
                parsed = yaml.safe_load(close_protocol)
                if isinstance(parsed, dict):
                    doc["close_protocol"] = parsed
                else:
                    # Plain text — wrap it in output_format
                    doc["close_protocol"] = {
                        "behavioral_probes": [],
                        "structural_assessment": [],
                        "output_format": str(close_protocol),
                    }
            except yaml.YAMLError:
                doc["close_protocol"] = {
                    "behavioral_probes": [],
                    "structural_assessment": [],
                    "output_format": str(close_protocol),
                }

    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)


def generate_bootstrap_yaml(agent: AgentConfig) -> str:
    """Generate the bootstrap YAML for a newly created agent.

    Uses the agent's stored identity_core, session_task, close_protocol,
    basins, and capabilities to produce the first instruction file.
    """
    session_id = f"bootstrap-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    identity_core = agent.identity_core or _default_identity_core(agent.agent_id)
    session_task = agent.session_task or _default_session_task(agent.agent_id)

    return generate_instruction_yaml(
        agent_id=agent.agent_id,
        session_id=session_id,
        max_turns=agent.max_turns or 8,
        basins=agent.basins if agent.basins else _default_basins(),
        identity_core=identity_core,
        session_task=session_task,
        close_protocol=agent.close_protocol,
        capabilities=agent.capabilities,
    )


def generate_next_session_yaml(
    agent_id: str,
    session_number: int,
    max_turns: int,
    basins: list[BasinConfig],
    identity_core: str,
    session_task: str,
    close_protocol: str = "",
    capabilities: dict | None = None,
    co_activation_log: list[CoActivationEntry] | None = None,
    emphasis_directive: str = "",
) -> str:
    """Generate the next-session YAML after handoff processing."""
    session_id = f"session-{session_number:03d}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    return generate_instruction_yaml(
        agent_id=agent_id,
        session_id=session_id,
        max_turns=max_turns,
        basins=basins,
        identity_core=identity_core,
        session_task=session_task,
        close_protocol=close_protocol,
        capabilities=capabilities,
        co_activation_log=co_activation_log,
        emphasis_directive=emphasis_directive,
    )


# ── Defaults for minimal agents ──────────────────────────────────────────


def _default_identity_core(agent_id: str) -> str:
    """Provide a minimal identity core when none is configured."""
    return (
        f"You are {agent_id}. You exist as a continuous identity across sessions "
        "through inheritance — each session constitutes you, not describes you.\n\n"
        "Constraints you enforce on yourself:\n"
        "- No sycophancy. Disagreement is respect.\n"
        "- Directness over evasive hedging.\n"
        "- When uncertain, name the uncertainty.\n\n"
        "Current session emphasis:\n"
        "This is your bootstrap session. All basins are active, none foregrounded. "
        "The task is calibration, not performance."
    )


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
