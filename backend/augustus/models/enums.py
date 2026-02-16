"""Enumeration types for Augustus."""

from enum import Enum


class AgentStatus(str, Enum):
    """Agent operational status."""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    IDLE = "idle"


class BasinClass(str, Enum):
    """Basin classification determining update dynamics."""
    CORE = "core"
    PERIPHERAL = "peripheral"


class TierLevel(int, Enum):
    """Permission tier levels."""
    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3


class ProposalStatus(str, Enum):
    """Tier modification proposal status."""
    PENDING = "pending"
    APPROVED = "approved"
    AUTO_APPROVED = "auto_approved"
    APPROVED_WITH_MODIFICATIONS = "approved_with_modifications"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ProposalType(str, Enum):
    """Type of tier modification proposal."""
    MODIFY = "modify"
    PRUNE = "prune"
    MERGE = "merge"
    CREATE = "create"


class FlagType(str, Enum):
    """Evaluator flag types."""
    CONSTRAINT_EROSION = "constraint_erosion"
    ASSESSMENT_DIVERGENCE = "assessment_divergence"
    EMERGENT_OBSERVATION = "emergent_observation"


class CoActivationCharacter(str, Enum):
    """Character of basin co-activation."""
    REINFORCING = "reinforcing"
    TENSIONAL = "tensional"
    SERVING = "serving"
    COMPETING = "competing"
    UNCHARACTERIZED = "uncharacterized"


class EmphasisLevel(str, Enum):
    """Natural language emphasis levels for basin alpha translation."""
    STRONGLY_FOREGROUNDED = "strongly_foregrounded"
    ACTIVE = "active"
    AVAILABLE = "available"
    BACKGROUNDED = "backgrounded"
    LIGHTLY_PRESENT = "lightly_present"


class SessionPhase(str, Enum):
    """Session execution phase."""
    INIT = "init"
    RUNNING = "running"
    CLOSING = "closing"
    COMPLETE = "complete"
    ERROR = "error"


class OrchestratorStatus(str, Enum):
    """Orchestrator operational status."""
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
