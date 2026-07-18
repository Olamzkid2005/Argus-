"""
Argus Error Hierarchy — B.11: Unified typed error class hierarchy.

All custom exceptions across the codebase inherit from ``ArgusError``
(or one of its category subclasses), giving consumers a single
``isinstance(e, ArgusError)`` check to distinguish Argus errors from
standard Python/third-party exceptions.

Each error can carry an optional ``ErrorCode`` (from
``error_classifier.ErrorCode``) for reliable code-based classification
by the error_classifier subsystem.
"""


from error_classifier import ErrorCode, tag_error


class ArgusError(Exception):
    """Base class for all Argus-specific exceptions.

    Every custom exception in the codebase should inherit from this class
    (or one of its category subclasses below) so that consumers can use::

        try:
            ...
        except ArgusError as e:
            # handle any known Argus error
            pass

    Subclasses should set a class-level ``default_code`` (an ``ErrorCode``)
    that is used when no specific error code is provided at construction time.
    """

    default_code: ErrorCode | None = None

    def __init__(
        self,
        message: str = "",
        *,
        error_code: ErrorCode | None = None,
        original: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.error_code: ErrorCode | None = error_code or self.default_code
        self.original: Exception | None = original

        # Tag the exception with ErrorCode for code-based classification.
        # The module-level import of tag_error ensures fast-fail at startup
        # if the error_classifier subsystem cannot be loaded.
        if self.error_code is not None:
            tag_error(self, self.error_code)

    def __str__(self) -> str:
        parts = [self.message or ""]
        if self.error_code:
            parts.insert(0, f"[{self.error_code.value}]")
        if self.original:
            parts.append(f"(caused by: {type(self.original).__name__}: {self.original})")
        return " ".join(parts)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(message={self.message!r}, "
            f"error_code={self.error_code}, original={self.original!r})"
        )


# ── Infrastructure errors ──────────────────────────────────────────────


class InfrastructureError(ArgusError):
    """Errors related to infrastructure dependencies (DB, Redis, network, etc.)."""


class DatabaseConnectionError(InfrastructureError):
    """Failed to connect to or query the database."""

    default_code = ErrorCode.DATABASE_ERROR


class MCPTransportError(InfrastructureError):
    """MCP transport layer failure (stdio JSON-RPC)."""


class TracingError(InfrastructureError):
    """Error in the OpenTelemetry or ExecutionSpan tracing subsystem."""


class LockAcquisitionError(InfrastructureError):
    """Failed to acquire a distributed lock (Redis-based)."""


# ── Tool execution errors ──────────────────────────────────────────────


class ToolError(ArgusError):
    """Errors arising from tool execution (scope, security, circuit breaker)."""


class ScopeViolationError(ToolError):
    """Target is outside the authorized engagement scope."""


class SecurityError(ToolError):
    """Security-related failure (sandbox violation, path traversal, etc.)."""


class CircuitOpenError(ToolError):
    """Circuit breaker is open — tool execution temporarily blocked."""


class ArtifactMissingError(ToolError):
    """A required evidence artifact was not found."""


class FindingCapExceededError(ToolError):
    """Per-engagement finding capacity has been exceeded."""


# ── Validation errors ────────────────────────────────────────────────


class ValidationError(ArgusError):
    """Input or state validation failures."""


class FindingValidationError(ValidationError):
    """A finding dict failed schema or business-rule validation."""


class RuleValidationError(ValidationError):
    """A custom rule YAML failed validation."""


class ParserError(ValidationError):
    """A tool-output parser encountered malformed or unexpected data."""


class CustomRuleError(ValidationError):
    """Error during custom rule engine execution or loading."""


# ── State & lifecycle errors ──────────────────────────────────────────


class StateError(ArgusError):
    """Engagement state machine or phase lifecycle errors."""


class InvalidStateTransitionError(StateError):
    """Invalid engagement state transition attempted."""


class EngagementTimeoutError(StateError):
    """Engagement exceeded its maximum allowed runtime."""


# ── Resource / client errors ─────────────────────────────────────────


class ResourceError(ArgusError):
    """Resource exhaustion or rate-limit errors."""


class RetryExhaustedError(ResourceError):
    """Operation failed after exhausting all retry attempts."""


class LLMUnavailableError(ResourceError):
    """LLM provider is unavailable (degraded or fully down)."""

    def __init__(
        self,
        message: str = "",
        *,
        error_code: ErrorCode | None = None,
        original: Exception | None = None,
        status: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message, error_code=error_code, original=original)
        self.status: str | None = status
        self.retry_after: int | None = retry_after


class AuthError(ResourceError):
    """Authentication or authorization failure."""


# ── Concurrency / task errors ─────────────────────────────────────────


class ConcurrencyError(ArgusError):
    """Concurrency, cancellation, or coordination errors."""


class OperatorCanceled(ConcurrencyError):
    """Operation was canceled by the user or supervisor."""


# ── Hypothesis engine errors ─────────────────────────────────────────


class HypothesisError(ArgusError):
    """Base for hypothesis engine failures."""


class HypothesisGenerationError(HypothesisError):
    """generate() failed to produce hypotheses from findings."""
    default_code = ErrorCode.DATABASE_ERROR  # triggers TRANSIENT retry path


class HypothesisPersistenceError(HypothesisError):
    """Postgres write for hypothesis create/update failed."""
    default_code = ErrorCode.DATABASE_ERROR
