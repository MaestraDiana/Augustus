"""Exception classes for Augustus."""


class AugustusError(Exception):
    """Base exception for Augustus."""
    pass


class SchemaValidationError(AugustusError):
    """YAML schema validation failed."""
    pass


class AgentNotFoundError(AugustusError):
    """Agent not found."""
    pass


class BudgetExceededError(AugustusError):
    """Credit budget exceeded."""
    pass


class TierViolationError(AugustusError):
    """Tier permission violation."""
    pass


class QueueError(AugustusError):
    """Queue operation error."""
    pass
