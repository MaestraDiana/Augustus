"""Data models for Augustus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from augustus.models.enums import (
    AgentStatus,
    BasinClass,
    CoActivationCharacter,
    FlagType,
    ProposalStatus,
    ProposalType,
    TierLevel,
)
from augustus.utils import enum_val


@dataclass
class BasinConfig:
    """Basin parameter configuration."""
    name: str
    basin_class: BasinClass
    alpha: float
    lambda_: float
    eta: float
    tier: TierLevel

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-friendly dict."""
        return {
            "name": self.name,
            "basin_class": enum_val(self.basin_class),
            "alpha": self.alpha,
            "lambda": self.lambda_,
            "eta": self.eta,
            "tier": self.tier.value if hasattr(self.tier, "value") else int(self.tier),
        }


@dataclass
class BasinDefinition:
    """Basin definition with access control and audit trail (from basin_definitions table)."""
    id: int
    agent_id: str
    name: str
    basin_class: BasinClass
    alpha: float
    lambda_: float
    eta: float
    tier: TierLevel
    locked_by_brain: bool = False
    alpha_floor: float | None = None
    alpha_ceiling: float | None = None
    deprecated: bool = False
    deprecated_at: str | None = None
    deprecation_rationale: str | None = None
    created_at: str = ""
    created_by: str = "import"
    last_modified_at: str = ""
    last_modified_by: str = "import"
    last_rationale: str | None = None

    def to_basin_config(self) -> BasinConfig:
        """Convert to BasinConfig for use in handoff engine and session manager."""
        return BasinConfig(
            name=self.name,
            basin_class=self.basin_class,
            alpha=self.alpha,
            lambda_=self.lambda_,
            eta=self.eta,
            tier=self.tier,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-friendly dict."""
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "name": self.name,
            "basin_class": enum_val(self.basin_class),
            "alpha": self.alpha,
            "lambda": self.lambda_,
            "eta": self.eta,
            "tier": self.tier.value if hasattr(self.tier, "value") else int(self.tier),
            "locked_by_brain": self.locked_by_brain,
            "alpha_floor": self.alpha_floor,
            "alpha_ceiling": self.alpha_ceiling,
            "deprecated": self.deprecated,
            "deprecated_at": self.deprecated_at,
            "deprecation_rationale": self.deprecation_rationale,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "last_modified_at": self.last_modified_at,
            "last_modified_by": self.last_modified_by,
            "last_rationale": self.last_rationale,
        }


@dataclass
class BasinModification:
    """Audit trail entry for a basin modification (from basin_modifications table)."""
    id: int
    basin_id: int
    agent_id: str
    session_id: str | None
    modified_by: str
    modification_type: str
    previous_values: dict | None
    new_values: dict
    rationale: str | None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-friendly dict."""
        return {
            "id": self.id,
            "basin_id": self.basin_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "modified_by": self.modified_by,
            "modification_type": self.modification_type,
            "previous_values": self.previous_values,
            "new_values": self.new_values,
            "rationale": self.rationale,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityConfig:
    """Capability configuration with turn-gated availability."""
    name: str
    enabled: bool
    available_from_turn: int = 0


@dataclass
class CoActivationEntry:
    """Co-activation pair with count and character."""
    pair: tuple[str, str]
    count: int
    character: CoActivationCharacter | None = None


@dataclass
class FrameworkConfig:
    """Framework section of YAML instruction."""
    version: str
    agent_id: str
    session_id: str
    max_turns: int
    capabilities: dict[str, CapabilityConfig]
    basin_params: list[BasinConfig]
    co_activation_log: list[CoActivationEntry] = field(default_factory=list)
    handoff_protocol: list[str] = field(default_factory=list)
    tier_permissions: dict[str, str] = field(default_factory=dict)


@dataclass
class CloseProtocol:
    """Close protocol configuration."""
    behavioral_probes: list[str]
    structural_assessment: list[str]
    output_format: str = "json"


@dataclass
class ParsedInstruction:
    """Parsed YAML instruction file."""
    framework: FrameworkConfig
    identity_core: str
    session_task: str
    close_protocol: CloseProtocol | None = None
    raw_yaml: str = ""
    validation_warnings: list[str] = field(default_factory=list)
    structural_sections: dict[str, Any] = field(default_factory=dict)
    """Orchestrator-owned structural sections (session_protocol, relational_grounding, etc.)
    that round-trip through YAML but are not agent-writable."""


@dataclass
class BasinSnapshot:
    """Basin state snapshot for a session."""
    basin_name: str
    alpha_start: float
    alpha_end: float
    delta: float
    relevance_score: float = 0.0
    session_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-friendly dict."""
        return {
            "basin_name": self.basin_name,
            "alpha_start": self.alpha_start,
            "alpha_end": self.alpha_end,
            "delta": self.delta,
            "relevance_score": self.relevance_score,
        }


@dataclass
class SessionRecord:
    """Complete session record."""
    session_id: str
    agent_id: str
    start_time: str
    end_time: str = ""
    turn_count: int = 0
    model: str = ""
    temperature: float = 1.0
    transcript: list[dict] = field(default_factory=list)
    close_report: dict | None = None
    basin_snapshots: list[BasinSnapshot] = field(default_factory=list)
    capabilities_used: list[str] = field(default_factory=list)
    status: str = "complete"
    yaml_raw: str = ""

    def to_dict(self, include_transcript: bool = False) -> dict[str, Any]:
        """Serialize to JSON-friendly dict."""
        result: dict[str, Any] = {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "turn_count": self.turn_count,
            "model": self.model,
            "temperature": self.temperature,
            "status": self.status,
            "capabilities_used": self.capabilities_used,
            "yaml_raw": self.yaml_raw,
        }
        if include_transcript:
            result["transcript"] = self.transcript
            result["close_report"] = self.close_report
            result["basin_snapshots"] = [bs.to_dict() for bs in self.basin_snapshots]
        return result


@dataclass
class TierProposal:
    """Tier modification proposal."""
    proposal_id: str
    agent_id: str
    basin_name: str
    tier: TierLevel
    proposal_type: ProposalType
    status: ProposalStatus = ProposalStatus.PENDING
    rationale: str = ""
    session_id: str = ""
    consecutive_count: int = 0
    created_at: str = ""
    resolved_at: str = ""
    resolved_by: str = ""
    proposed_config: BasinConfig | None = None
    rejection_rationale: str = ""
    modification_rationale: str = ""
    original_params: BasinConfig | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-friendly dict."""
        result = {
            "proposal_id": self.proposal_id,
            "agent_id": self.agent_id,
            "basin_name": self.basin_name,
            "tier": self.tier.value if hasattr(self.tier, "value") else int(self.tier),
            "proposal_type": enum_val(self.proposal_type),
            "status": enum_val(self.status),
            "rationale": self.rationale,
            "session_id": self.session_id,
            "consecutive_count": self.consecutive_count,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
        }
        if self.proposed_config:
            result["proposed_config"] = self.proposed_config.to_dict()
        if self.rejection_rationale:
            result["rejection_rationale"] = self.rejection_rationale
        if self.modification_rationale:
            result["modification_rationale"] = self.modification_rationale
        if self.original_params:
            result["original_params"] = self.original_params.to_dict()
        return result


@dataclass
class EvaluatorOutput:
    """Evaluator service output."""
    basin_relevance: dict[str, float] = field(default_factory=dict)
    basin_rationale: dict[str, str] = field(default_factory=dict)
    co_activation_characters: dict[str, str] = field(default_factory=dict)
    constraint_erosion_flag: bool = False
    constraint_erosion_detail: str | None = None
    assessment_divergence_flag: bool = False
    assessment_divergence_detail: str | None = None
    emergent_observations: list[str] = field(default_factory=list)
    evaluator_prompt_version: str | None = None


@dataclass
class EvaluatorPrompt:
    """Evaluator prompt version."""
    version_id: str
    prompt_text: str
    change_rationale: str = ""
    created_at: str = ""
    is_active: bool = False


@dataclass
class Annotation:
    """Human annotation."""
    annotation_id: str
    agent_id: str
    session_id: str | None = None
    content: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = ""


@dataclass
class FlagRecord:
    """Evaluator flag record."""
    flag_id: str
    agent_id: str
    session_id: str = ""
    flag_type: FlagType = FlagType.EMERGENT_OBSERVATION
    severity: str = "info"
    detail: str = ""
    reviewed: bool = False
    review_note: str | None = None
    reviewed_at: str = ""
    reviewed_by: str = ""
    resolution: str = ""
    resolution_notes: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-friendly dict."""
        result = {
            "flag_id": self.flag_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "flag_type": enum_val(self.flag_type),
            "severity": self.severity,
            "detail": self.detail,
            "reviewed": self.reviewed,
            "review_note": self.review_note,
            "reviewed_at": self.reviewed_at or None,
            "reviewed_by": self.reviewed_by or None,
            "created_at": self.created_at,
        }
        if self.resolution:
            result["resolution"] = self.resolution
            result["resolution_notes"] = self.resolution_notes
        return result


@dataclass
class TierSettings:
    """Agent-level tier modification settings."""
    tier_2_auto_approve: bool = True
    tier_2_threshold: int = 5
    emergence_auto_approve: bool = True
    emergence_threshold: int = 3


@dataclass
class AgentConfig:
    """Agent configuration."""
    agent_id: str
    description: str = ""
    status: AgentStatus = AgentStatus.IDLE
    model_override: str | None = None
    temperature_override: float | None = None
    max_tokens_override: int | None = None
    max_turns: int = 8
    session_interval: int = 300  # seconds between sessions (default 5 min)
    identity_core: str = ""
    session_task: str = ""
    close_protocol: str = ""
    emphasis_directive: str = ""  # Computed by handoff engine; prepended to identity_core at session start
    capabilities: dict = field(default_factory=dict)
    basins: list[BasinConfig] = field(default_factory=list)
    tier_settings: TierSettings | None = None
    session_protocol: dict = field(default_factory=dict)
    relational_grounding: dict = field(default_factory=dict)
    created_at: str = ""
    last_active: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-friendly dict."""
        return {
            "agent_id": self.agent_id,
            "description": self.description,
            "status": enum_val(self.status),
            "model_override": self.model_override,
            "temperature_override": self.temperature_override,
            "max_tokens_override": self.max_tokens_override,
            "max_turns": self.max_turns,
            "session_interval": self.session_interval,
            "identity_core": self.identity_core,
            "session_task": self.session_task,
            "close_protocol": self.close_protocol,
            "emphasis_directive": self.emphasis_directive,
            "capabilities": self.capabilities,
            "basins": [b.to_dict() for b in self.basins],
            "tier_settings": (
                {
                    "tier_2_auto_approve": self.tier_settings.tier_2_auto_approve,
                    "tier_2_threshold": self.tier_settings.tier_2_threshold,
                    "emergence_auto_approve": self.tier_settings.emergence_auto_approve,
                    "emergence_threshold": self.tier_settings.emergence_threshold,
                }
                if self.tier_settings
                else None
            ),
            "session_protocol": self.session_protocol,
            "relational_grounding": self.relational_grounding,
            "created_at": self.created_at,
            "last_active": self.last_active,
        }


@dataclass
class UsageRecord:
    """Credit usage record."""
    session_id: str
    agent_id: str
    tokens_in: int = 0
    tokens_out: int = 0
    estimated_cost: float = 0.0
    model: str = ""
    timestamp: str = ""


@dataclass
class ActivityEvent:
    """Activity feed event."""
    event_id: str
    event_type: str
    agent_id: str = ""
    session_id: str = ""
    detail: str = ""
    timestamp: str = ""


@dataclass
class SearchResult:
    """Semantic search result."""
    content_type: str
    agent_id: str
    session_id: str = ""
    snippet: str = ""
    relevance_score: float = 0.0
    timestamp: str = ""
    full_content: str | None = None
