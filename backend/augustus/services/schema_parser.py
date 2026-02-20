"""YAML instruction file parser and validator."""

import logging
from typing import Any

import yaml

from augustus.exceptions import SchemaValidationError
from augustus.models.dataclasses import (
    BasinConfig,
    CapabilityConfig,
    CloseProtocol,
    CoActivationEntry,
    FrameworkConfig,
    ParsedInstruction,
)
from augustus.models.enums import BasinClass, CoActivationCharacter, TierLevel

logger = logging.getLogger(__name__)


class SchemaParser:
    """Parse and validate YAML instruction files."""

    MIN_VERSION = "0.2"

    def parse(self, yaml_text: str) -> ParsedInstruction:
        """Parse YAML instruction file and route sections."""
        try:
            data = yaml.safe_load(yaml_text)
        except yaml.YAMLError as e:
            raise SchemaValidationError(f"Invalid YAML: {e}")

        if not isinstance(data, dict):
            raise SchemaValidationError("YAML must be a mapping at top level")

        # Extract sections
        framework_raw = data.get("framework")
        identity_core = data.get("identity_core")
        session_task = data.get("session_task")
        close_protocol_raw = data.get("close_protocol")

        warnings = []

        # Capture structural sections that must round-trip between sessions.
        # These are delivered to Claude as session context in the turn 0 user
        # message (via SessionManager._format_structural_preamble), and also
        # preserved by the orchestrator for YAML regeneration.
        structural_keys = {"session_protocol", "relational_grounding"}
        structural_sections: dict[str, Any] = {}
        for skey in structural_keys:
            if skey in data and data[skey] is not None:
                structural_sections[skey] = data[skey]

        # Note unknown top-level keys — these are allowed (schema evolves)
        # but tracked for debugging
        known_keys = {
            "framework", "identity_core", "session_task", "close_protocol",
        } | structural_keys
        for key in data:
            if key not in known_keys:
                warnings.append(f"Unknown top-level field: '{key}'")

        # Validate required sections
        if not framework_raw:
            raise SchemaValidationError("Missing required 'framework' section")
        if not session_task:
            raise SchemaValidationError("Missing required 'session_task' section")

        # identity_core is no longer written to YAML — it lives in AgentConfig.
        # Accept it if present (e.g. legacy files or agent-written overrides)
        # but do not require it.  The session manager loads it from the DB.
        if identity_core:
            warnings.append(
                "'identity_core' found in YAML — this field is now DB-owned. "
                "The YAML value will be ignored; identity_core loads from AgentConfig."
            )

        if not close_protocol_raw:
            warnings.append("Missing 'close_protocol' section")

        # Parse framework (strict)
        framework = self.validate_framework(framework_raw)

        # Parse close protocol (if present)
        close_protocol = None
        if close_protocol_raw:
            close_protocol = self.parse_close_protocol(close_protocol_raw)

        return ParsedInstruction(
            framework=framework,
            identity_core="",  # Loaded from AgentConfig at session start, not from YAML
            session_task=str(session_task).strip(),
            close_protocol=close_protocol,
            raw_yaml=yaml_text,
            validation_warnings=warnings,
            structural_sections=structural_sections,
        )

    def validate_framework(self, fw: dict[str, Any]) -> FrameworkConfig:
        """Strict validation of framework section."""
        # version — accept any version >= MIN_VERSION
        version = fw.get("version")
        try:
            ver = tuple(int(x) for x in str(version).split("."))
            min_ver = tuple(int(x) for x in self.MIN_VERSION.split("."))
            if ver < min_ver:
                raise SchemaValidationError(
                    f"Version '{version}' is below minimum '{self.MIN_VERSION}'"
                )
        except (ValueError, AttributeError):
            raise SchemaValidationError(
                f"Invalid version '{version}', expected semver >= '{self.MIN_VERSION}'"
            )

        # agent_id
        agent_id = fw.get("agent_id", "")
        if not agent_id or not isinstance(agent_id, str):
            raise SchemaValidationError("'agent_id' is required and must be a non-empty string")

        # session_id
        session_id = fw.get("session_id", "")
        if not session_id:
            raise SchemaValidationError("'session_id' is required")

        # max_turns
        max_turns = fw.get("max_turns")
        if not isinstance(max_turns, int) or max_turns < 1 or max_turns > 20:
            raise SchemaValidationError(f"'max_turns' must be integer in [1, 20], got {max_turns}")

        # basin_params
        basin_params_raw = fw.get("basin_params", {})
        if not basin_params_raw:
            raise SchemaValidationError("'basin_params' must contain at least one basin")
        basins = self.validate_basin_params(basin_params_raw, max_turns)

        # capabilities (support both "capabilities" and "services" keys)
        caps_raw = fw.get("capabilities", fw.get("services", {}))
        capabilities = self.validate_capabilities(caps_raw, max_turns)

        # co_activation_log
        co_activation = []
        for entry in fw.get("co_activation_log", []):
            pair = tuple(entry.get("pair", []))
            count = entry.get("count", 0)
            char_str = entry.get("character")
            character = None
            if char_str:
                try:
                    character = CoActivationCharacter(char_str)
                except ValueError:
                    character = CoActivationCharacter.UNCHARACTERIZED
            co_activation.append(CoActivationEntry(pair=pair, count=count, character=character))

        # handoff_protocol
        handoff = []
        hp = fw.get("handoff_protocol", {})
        if isinstance(hp, dict):
            handoff = hp.get("on_session_end", [])

        # tier_permissions
        tier_perms = fw.get("tier_permissions", {})

        return FrameworkConfig(
            version=str(version),
            agent_id=str(agent_id),
            session_id=str(session_id),
            max_turns=max_turns,
            capabilities=capabilities,
            basin_params=basins,
            co_activation_log=co_activation,
            handoff_protocol=handoff,
            tier_permissions=tier_perms,
        )

    def validate_basin_params(self, params: dict[str, Any], max_turns: int) -> list[BasinConfig]:
        """Validate basin parameters."""
        basins = []
        for name, config in params.items():
            if not isinstance(config, dict):
                raise SchemaValidationError(f"Basin '{name}' must be a mapping")

            # Warn on special characters in basin names
            if not all(c.isalnum() or c in ("_", "-") for c in name):
                logger.warning(f"Basin name '{name}' contains special characters")

            basin_class_str = config.get("class", "peripheral")
            try:
                basin_class = BasinClass(basin_class_str)
            except ValueError:
                raise SchemaValidationError(
                    f"Basin '{name}' class must be 'core' or 'peripheral', got '{basin_class_str}'"
                )

            alpha = config.get("alpha")
            if not isinstance(alpha, (int, float)) or alpha < 0.05 or alpha > 1.0:
                raise SchemaValidationError(
                    f"Basin '{name}' alpha must be in [0.05, 1.0], got {alpha}"
                )

            lambda_ = config.get("lambda", 0.9)
            if not isinstance(lambda_, (int, float)) or lambda_ < 0.0 or lambda_ > 1.0:
                raise SchemaValidationError(
                    f"Basin '{name}' lambda must be in [0.0, 1.0], got {lambda_}"
                )

            eta = config.get("eta", 0.05)
            if not isinstance(eta, (int, float)) or eta < 0.0 or eta > 1.0:
                raise SchemaValidationError(
                    f"Basin '{name}' eta must be in [0.0, 1.0], got {eta}"
                )

            tier_val = config.get("tier", 3)
            try:
                tier = TierLevel(tier_val)
            except ValueError:
                tier = TierLevel.TIER_3

            basins.append(
                BasinConfig(
                    name=name,
                    basin_class=basin_class,
                    alpha=float(alpha),
                    lambda_=float(lambda_),
                    eta=float(eta),
                    tier=tier,
                )
            )

        return basins

    def validate_capabilities(
        self, caps: dict[str, Any], max_turns: int
    ) -> dict[str, CapabilityConfig]:
        """Validate capabilities configuration."""
        result = {}
        if not caps:
            return result

        for name, config in caps.items():
            if isinstance(config, bool):
                # Simple "service: true/false" format
                result[name] = CapabilityConfig(
                    name=name, enabled=config, available_from_turn=0
                )
            elif isinstance(config, dict):
                enabled = config.get("enabled", True)
                from_turn = config.get("available_from_turn", 0)
                if not isinstance(from_turn, int) or from_turn < 0 or from_turn >= max_turns:
                    raise SchemaValidationError(
                        f"Capability '{name}' available_from_turn must be in [0, {max_turns - 1}]"
                    )
                result[name] = CapabilityConfig(
                    name=name, enabled=bool(enabled), available_from_turn=from_turn
                )
            else:
                logger.warning(f"Unexpected capability format for '{name}'")

        return result

    def parse_close_protocol(self, proto: dict[str, Any]) -> CloseProtocol:
        """Parse close protocol section."""
        if not isinstance(proto, dict):
            return CloseProtocol(
                behavioral_probes=[], structural_assessment=[], output_format=""
            )

        probes = proto.get("behavioral_probes", [])
        assessment = proto.get("structural_assessment", [])
        output_format = proto.get("output_format", "")

        return CloseProtocol(
            behavioral_probes=[str(p) for p in probes],
            structural_assessment=[str(a) for a in assessment],
            output_format=str(output_format).strip(),
        )


# ── Standalone helpers ──────────────────────────────────────────────────────

_DEFAULT_CAPABILITIES: list[dict[str, Any]] = [
    {"name": "mcp", "enabled": True, "available_from_turn": 1},
    {"name": "rag", "enabled": True, "available_from_turn": 1},
    {"name": "web_search", "enabled": False, "available_from_turn": 1},
    {"name": "memory_query", "enabled": False, "available_from_turn": 1},
    {"name": "memory_write", "enabled": False, "available_from_turn": 5},
    {"name": "file_write", "enabled": False, "available_from_turn": 10},
]


def parse_yaml_lenient(yaml_text: str) -> dict[str, Any]:
    """Parse a bootstrap YAML leniently for agent form population.

    Does not require agent_id or session_id.  Returns extracted fields
    plus ``warnings`` and ``errors`` lists so callers can surface issues
    without raising exceptions.
    """
    warnings: list[str] = []
    errors: list[str] = []
    result: dict[str, Any] = {
        "max_turns": None,
        "identity_core": None,
        "session_task": None,
        "close_protocol": None,
        "session_protocol": None,
        "relational_grounding": None,
        "capabilities": None,
        "basins": None,
        "warnings": warnings,
        "errors": errors,
    }

    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        errors.append(f"Invalid YAML syntax: {e}")
        return result

    if not isinstance(data, dict):
        errors.append("YAML must be a mapping at top level, got " + type(data).__name__)
        return result

    expected_keys = {
        "framework", "identity_core", "session_task",
        "close_protocol", "session_protocol", "relational_grounding",
    }
    for key in data:
        if key not in expected_keys:
            warnings.append(f"Unexpected top-level field ignored: '{key}'")

    if "identity_core" in data:
        result["identity_core"] = str(data["identity_core"]).strip()

    if "session_task" in data:
        result["session_task"] = str(data["session_task"]).strip()

    if "close_protocol" in data:
        cp = data["close_protocol"]
        if isinstance(cp, dict):
            result["close_protocol"] = yaml.dump(
                cp, default_flow_style=False, sort_keys=False, allow_unicode=True
            ).strip()
        elif cp is not None:
            result["close_protocol"] = str(cp).strip()

    for skey in ("session_protocol", "relational_grounding"):
        if skey in data:
            val = data[skey]
            if isinstance(val, dict):
                result[skey] = yaml.dump(
                    val, default_flow_style=False, sort_keys=False, allow_unicode=True
                ).strip()
            elif val is not None:
                result[skey] = str(val).strip()

    fw = data.get("framework")
    if not isinstance(fw, dict):
        if fw is not None:
            warnings.append("'framework' section is not a mapping, skipping")
        else:
            warnings.append("No 'framework' section found — only textual fields imported")
        return result

    max_turns = fw.get("max_turns")
    if isinstance(max_turns, int) and 1 <= max_turns <= 50:
        result["max_turns"] = max_turns
    elif max_turns is not None:
        warnings.append(f"'max_turns' value '{max_turns}' invalid, skipping")

    basin_params = fw.get("basin_params")
    if isinstance(basin_params, dict) and basin_params:
        basins = []
        for name, config in basin_params.items():
            if not isinstance(config, dict):
                warnings.append(f"Basin '{name}' is not a mapping, skipping")
                continue

            basin_class_str = config.get("class", "peripheral")
            if basin_class_str not in ("core", "peripheral", "emergent"):
                warnings.append(
                    f"Basin '{name}' class '{basin_class_str}' unrecognized, defaulting to 'peripheral'"
                )
                basin_class_str = "peripheral"

            alpha = config.get("alpha", 0.5)
            if not isinstance(alpha, (int, float)):
                warnings.append(f"Basin '{name}' alpha is not numeric, defaulting to 0.5")
                alpha = 0.5
            elif alpha < 0.05 or alpha > 1.0:
                clamped = max(0.05, min(1.0, float(alpha)))
                warnings.append(f"Basin '{name}' alpha {alpha} clamped to {clamped}")
                alpha = clamped

            lambda_ = config.get("lambda", 0.95)
            if not isinstance(lambda_, (int, float)):
                lambda_ = 0.95
            else:
                lambda_ = max(0.0, min(1.0, float(lambda_)))

            eta = config.get("eta", 0.1)
            if not isinstance(eta, (int, float)):
                eta = 0.1
            else:
                eta = max(0.0, min(1.0, float(eta)))

            tier = config.get("tier")
            if tier is None:
                tier = 2 if basin_class_str == "core" else 3
            elif tier not in (1, 2, 3):
                warnings.append(f"Basin '{name}' tier '{tier}' invalid, defaulting from class")
                tier = 2 if basin_class_str == "core" else 3

            basins.append({
                "name": name,
                "class": basin_class_str,
                "alpha": round(float(alpha), 4),
                "lambda": round(float(lambda_), 4),
                "eta": round(float(eta), 4),
                "tier": int(tier),
            })
        if basins:
            result["basins"] = basins
    elif basin_params is not None:
        warnings.append("'basin_params' is empty or not a mapping")

    caps_raw = fw.get("capabilities", fw.get("services"))
    if isinstance(caps_raw, dict) and caps_raw:
        caps_by_name = {c["name"]: dict(c) for c in _DEFAULT_CAPABILITIES}
        for name, val in caps_raw.items():
            if isinstance(val, bool):
                if name in caps_by_name:
                    caps_by_name[name]["enabled"] = val
                else:
                    caps_by_name[name] = {"name": name, "enabled": val, "available_from_turn": 1}
            elif isinstance(val, dict):
                enabled = val.get("enabled", True)
                from_turn = val.get("available_from_turn", 1)
                if name in caps_by_name:
                    caps_by_name[name]["enabled"] = bool(enabled)
                    caps_by_name[name]["available_from_turn"] = int(from_turn)
                else:
                    caps_by_name[name] = {
                        "name": name,
                        "enabled": bool(enabled),
                        "available_from_turn": int(from_turn),
                    }
        result["capabilities"] = list(caps_by_name.values())

    return result
