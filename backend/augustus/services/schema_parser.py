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

    SUPPORTED_VERSION = "0.2"

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

        # Check for unexpected top-level keys
        expected_keys = {"framework", "identity_core", "session_task", "close_protocol"}
        for key in data:
            if key not in expected_keys:
                warnings.append(f"Unexpected top-level field: '{key}'")

        # Validate required sections
        if not framework_raw:
            raise SchemaValidationError("Missing required 'framework' section")
        if not identity_core:
            raise SchemaValidationError("Missing required 'identity_core' section")
        if not session_task:
            raise SchemaValidationError("Missing required 'session_task' section")

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
            identity_core=str(identity_core).strip(),
            session_task=str(session_task).strip(),
            close_protocol=close_protocol,
            raw_yaml=yaml_text,
            validation_warnings=warnings,
        )

    def validate_framework(self, fw: dict[str, Any]) -> FrameworkConfig:
        """Strict validation of framework section."""
        # version
        version = fw.get("version")
        if str(version) != self.SUPPORTED_VERSION:
            raise SchemaValidationError(
                f"Unsupported version '{version}', expected '{self.SUPPORTED_VERSION}'"
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
