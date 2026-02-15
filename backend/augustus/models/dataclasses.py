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


@dataclass
class BasinConfig:
    """Basin parameter configuration."""
    name: str
    basin_class: BasinClass
    alpha: float
    lambda_: float
    eta: float
    tier: TierLevel


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
    created_at: str = ""


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
    capabilities: dict = field(default_factory=dict)
    basins: list[BasinConfig] = field(default_factory=list)
    tier_settings: TierSettings | None = None
    session_protocol: dict = field(default_factory=dict)
    relational_grounding: dict = field(default_factory=dict)
    created_at: str = ""
    last_active: str = ""


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
