class ArmadaError(RuntimeError):
    """Base exception for expected application failures."""


class ConfigurationError(ArmadaError):
    """Configuration is missing or invalid."""


class CapabilityError(ArmadaError):
    """Codex or local capabilities do not satisfy a required gate."""


class GitSafetyError(ArmadaError):
    """A Git safety boundary was violated."""


class PlanningError(ArmadaError):
    """Planning failed or produced an invalid plan."""


class ExecutionError(ArmadaError):
    """Worker execution failed."""


class VerificationError(ArmadaError):
    """Deterministic verification failed."""


class ApprovalRequiredError(ArmadaError):
    """The requested action needs explicit user approval."""


class StateError(ArmadaError):
    """Durable run state is missing, stale, or inconsistent."""


class BudgetError(ArmadaError):
    """The configured credit budget would be exceeded."""


class LunaForgeError(ArmadaError):
    """The pinned Luna Forge runtime is missing, unsafe, or incompatible."""

