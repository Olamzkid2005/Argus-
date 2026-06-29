"""Unit tests for the ArgusError exception hierarchy (B.11).

Tests cover:
- All 20 exception classes instantiate correctly
- isinstance hierarchy matches the expected inheritance tree
- error_code assignment (explicit + default_code fallback)
- __str__ and __repr__ formatting
- Original exception chaining
- LLMUnavailableError custom constructor (status, retry_after)
- Cross-module re-exports (importing from original modules)
"""

from typing import Any

import pytest

from exceptions import (
    ArgusError,
    ArtifactMissingError,
    AuthError,
    CircuitOpenError,
    ConcurrencyError,
    CustomRuleError,
    DatabaseConnectionError,
    EngagementTimeoutError,
    ErrorCode,
    FindingCapExceededError,
    FindingValidationError,
    InfrastructureError,
    InvalidStateTransitionError,
    LLMUnavailableError,
    LockAcquisitionError,
    MCPTransportError,
    OperatorCanceled,
    ParserError,
    ResourceError,
    RetryExhaustedError,
    RuleValidationError,
    ScopeViolationError,
    SecurityError,
    StateError,
    ToolError,
    TracingError,
    ValidationError,
)


# ── All exception classes listed for parameterized tests ──────────────

ALL_EXCEPTIONS: list[type[ArgusError]] = [
    # Base
    ArgusError,
    # Infrastructure
    InfrastructureError,
    DatabaseConnectionError,
    MCPTransportError,
    TracingError,
    LockAcquisitionError,
    # Tool
    ToolError,
    ScopeViolationError,
    SecurityError,
    CircuitOpenError,
    ArtifactMissingError,
    FindingCapExceededError,
    # Validation
    ValidationError,
    FindingValidationError,
    RuleValidationError,
    ParserError,
    CustomRuleError,
    # State
    StateError,
    InvalidStateTransitionError,
    EngagementTimeoutError,
    # Resource
    ResourceError,
    RetryExhaustedError,
    LLMUnavailableError,
    AuthError,
    # Concurrency
    ConcurrencyError,
    OperatorCanceled,
]

# Map: exception class -> expected immediate parent
EXPECTED_PARENT: dict[type[ArgusError], type[ArgusError]] = {
    # Base
    ArgusError: Exception,
    # Infrastructure
    InfrastructureError: ArgusError,
    DatabaseConnectionError: InfrastructureError,
    MCPTransportError: InfrastructureError,
    TracingError: InfrastructureError,
    LockAcquisitionError: InfrastructureError,
    # Tool
    ToolError: ArgusError,
    ScopeViolationError: ToolError,
    SecurityError: ToolError,
    CircuitOpenError: ToolError,
    ArtifactMissingError: ToolError,
    FindingCapExceededError: ToolError,
    # Validation
    ValidationError: ArgusError,
    FindingValidationError: ValidationError,
    RuleValidationError: ValidationError,
    ParserError: ValidationError,
    CustomRuleError: ValidationError,
    # State
    StateError: ArgusError,
    InvalidStateTransitionError: StateError,
    EngagementTimeoutError: StateError,
    # Resource
    ResourceError: ArgusError,
    RetryExhaustedError: ResourceError,
    LLMUnavailableError: ResourceError,
    AuthError: ResourceError,
    # Concurrency
    ConcurrencyError: ArgusError,
    OperatorCanceled: ConcurrencyError,
}

# Which exceptions have custom __init__ (beyond ArgusError base)
CUSTOM_INIT: set[type[ArgusError]] = {LLMUnavailableError}

# Exceptions that set a class-level default_code
EXPECTED_DEFAULT_CODE: dict[type[ArgusError], ErrorCode] = {
    DatabaseConnectionError: ErrorCode.DATABASE_ERROR,
}


class TestHierarchy:
    """Verify the inheritance tree is structurally correct."""

    def test_all_exceptions_are_argus_errors(self):
        """Every custom exception should be an instance of ArgusError."""
        for exc_cls in ALL_EXCEPTIONS:
            assert issubclass(exc_cls, ArgusError), f"{exc_cls.__name__} is not a subclass of ArgusError"

    @pytest.mark.parametrize("exc_cls,expected_parent", EXPECTED_PARENT.items())
    def test_immediate_parent(self, exc_cls: type[ArgusError], expected_parent: type):
        """Verify each exception's immediate parent class."""
        bases = exc_cls.__bases__
        msg = f"{exc_cls.__name__}.__bases__ = {bases}, expected ({expected_parent.__name__},)"
        assert expected_parent in bases, msg

    def test_default_code_is_optional(self):
        """Unless explicitly set, default_code should be None."""
        for exc_cls in ALL_EXCEPTIONS:
            if exc_cls is ArgusError or exc_cls in EXPECTED_DEFAULT_CODE:
                continue
            assert exc_cls.default_code is None, (
                f"{exc_cls.__name__}.default_code should be None, "
                f"got {exc_cls.default_code}"
            )

    def test_database_connection_error_has_default_code(self):
        """DatabaseConnectionError has a hardcoded default_code."""
        assert DatabaseConnectionError.default_code is ErrorCode.DATABASE_ERROR


class TestInstantiation:
    """Verify all exceptions can be instantiated with various signatures."""

    def test_default_construction(self):
        """All exceptions can be constructed with no arguments."""
        for exc_cls in ALL_EXCEPTIONS:
            if exc_cls is ArgusError:
                continue
            instance = exc_cls()
            assert isinstance(instance, exc_cls)
            assert instance.message == ""

    def test_message_only(self):
        """All exceptions accept a plain string message."""
        for exc_cls in ALL_EXCEPTIONS:
            if exc_cls is ArgusError:
                continue
            instance = exc_cls("something went wrong")
            assert instance.message == "something went wrong"
            assert str(instance.args[0]) == "something went wrong"

    def test_error_code_explicit(self):
        """Explicit error_code overrides default_code."""
        instance = DatabaseConnectionError("db down", error_code=ErrorCode.TOOL_EXECUTION_FAILED)
        assert instance.error_code is ErrorCode.TOOL_EXECUTION_FAILED

    def test_error_code_uses_default(self):
        """When no error_code is passed, fall back to default_code."""
        instance = DatabaseConnectionError("db down")
        assert instance.error_code is ErrorCode.DATABASE_ERROR

    def test_no_default_code_means_none(self):
        """Exceptions without default_code get None."""
        instance = TracingError("broken trace")
        assert instance.error_code is None

    def test_original_chaining(self):
        """Original exception is stored and accessible."""
        cause = ValueError("invalid input")
        instance = ParserError("parse failed", original=cause)
        assert instance.original is cause
        assert instance.original.__class__ is ValueError

    def test_argus_error_is_abstract(self):
        """ArgusError itself can be instantiated (it's not abstract)."""
        e = ArgusError("base error")
        assert isinstance(e, ArgusError)
        assert e.message == "base error"
        assert e.error_code is None

    def test_llm_unavailable_extra_fields(self):
        """LLMUnavailableError supports status and retry_after."""
        cause = ConnectionError("API timeout")
        instance = LLMUnavailableError(
            "provider down",
            error_code=ErrorCode.TOOL_EXECUTION_FAILED,
            original=cause,
            status="degraded",
            retry_after=30,
        )
        assert instance.message == "provider down"
        assert instance.error_code is ErrorCode.TOOL_EXECUTION_FAILED
        assert instance.original is cause
        assert instance.status == "degraded"
        assert instance.retry_after == 30

    def test_llm_unavailable_defaults(self):
        """LLMUnavailableError can be constructed with just a message."""
        instance = LLMUnavailableError("rate limited")
        assert instance.message == "rate limited"
        assert instance.error_code is None
        assert instance.original is None
        assert instance.status is None
        assert instance.retry_after is None

    def test_empty_message(self):
        """All exceptions accept an empty message."""
        for exc_cls in ALL_EXCEPTIONS:
            if exc_cls is ArgusError:
                continue
            if exc_cls in CUSTOM_INIT:
                continue  # skip LLMUnavailableError which has custom sig
            instance = exc_cls("")
            assert instance.message == ""


class TestIsinstance:
    """Verify isinstance checks work correctly throughout the hierarchy."""

    def test_base_isinstance(self):
        """Every exception passes isinstance(e, ArgusError)."""
        for exc_cls in ALL_EXCEPTIONS:
            if exc_cls is ArgusError:
                continue
            instance = exc_cls("test")
            assert isinstance(instance, ArgusError), f"{exc_cls.__name__} not isinstance ArgusError"

    def test_database_isinsance(self):
        """DatabaseConnectionError is both InfrastructureError and ArgusError."""
        e = DatabaseConnectionError("no db")
        assert isinstance(e, DatabaseConnectionError)
        assert isinstance(e, InfrastructureError)
        assert isinstance(e, ArgusError)
        assert isinstance(e, Exception)

    def test_scope_violation_isinstance(self):
        """ScopeViolationError is both ToolError and ArgusError."""
        e = ScopeViolationError("out of scope")
        assert isinstance(e, ScopeViolationError)
        assert isinstance(e, ToolError)
        assert isinstance(e, ArgusError)

    def test_validation_isinstance(self):
        """ParserError is both ValidationError and ArgusError."""
        e = ParserError("bad output")
        assert isinstance(e, ParserError)
        assert isinstance(e, ValidationError)
        assert isinstance(e, ArgusError)

    def test_state_isinstance(self):
        """InvalidStateTransitionError is both StateError and ArgusError."""
        e = InvalidStateTransitionError("bad transition")
        assert isinstance(e, InvalidStateTransitionError)
        assert isinstance(e, StateError)
        assert isinstance(e, ArgusError)

    def test_operator_canceled_isinstance(self):
        """OperatorCanceled is ConcurrencyError (not ResourceError)."""
        e = OperatorCanceled("cancelled")
        assert isinstance(e, OperatorCanceled)
        assert isinstance(e, ConcurrencyError)
        assert isinstance(e, ArgusError)
        assert not isinstance(e, ResourceError)

    def test_negative_isinstance(self):
        """A ToolError is not a StateError (or vice versa)."""
        assert not isinstance(SecurityError("test"), StateError)
        assert not isinstance(InvalidStateTransitionError("test"), ToolError)
        assert not isinstance(ParserError("test"), InfrastructureError)
        assert not isinstance(RetryExhaustedError("test"), ValidationError)
        assert not isinstance(OperatorCanceled("test"), ResourceError)

    def test_catch_all_argus_error(self):
        """A single except ArgusError catches any custom exception."""
        exceptions_to_try: list[ArgusError] = [
            DatabaseConnectionError("a"),
            TracingError("b"),
            SecurityError("c"),
            ParserError("d"),
            InvalidStateTransitionError("e"),
            RetryExhaustedError("f"),
            AuthError("g"),
            OperatorCanceled("h"),
        ]
        for exc in exceptions_to_try:
            try:
                raise exc
            except ArgusError:
                pass  # expected
            except Exception:
                pytest.fail(f"{type(exc).__name__} was not caught by except ArgusError")


class TestStringRepresentation:
    """Verify __str__ and __repr__ formats."""

    @pytest.mark.parametrize("exc_cls", [e for e in ALL_EXCEPTIONS if e is not ArgusError])
    def test_str_basic(self, exc_cls):
        """__str__ includes the message."""
        msg = "test message"
        instance = exc_cls(msg)
        s = str(instance)
        assert msg in s
        # Exceptions with default_code will have an error code prefix
        if exc_cls in EXPECTED_DEFAULT_CODE:
            expected_code = EXPECTED_DEFAULT_CODE[exc_cls].value
            assert expected_code in s

    def test_str_with_error_code(self):
        """__str__ prepends [ERROR_CODE] when error_code is set."""
        instance = DatabaseConnectionError("db down")
        s = str(instance)
        assert s.startswith(f"[{ErrorCode.DATABASE_ERROR.value}]")
        assert "db down" in s

    def test_str_with_original(self):
        """__str__ appends cause info when original is set."""
        cause = ValueError("bad value")
        instance = ParserError("parse failed", original=cause)
        s = str(instance)
        assert "parse failed" in s
        assert "ValueError" in s
        assert "bad value" in s

    def test_str_with_code_and_original(self):
        """__str__ combines error_code prefix + message + cause."""
        cause = RuntimeError("timeout")
        instance = DatabaseConnectionError("query failed", original=cause)
        s = str(instance)
        assert s.startswith(f"[{ErrorCode.DATABASE_ERROR.value}]")
        assert "query failed" in s
        assert "RuntimeError" in s
        assert "timeout" in s

    def test_str_empty_message(self):
        """__str__ handles empty message gracefully."""
        instance = TracingError()
        assert str(instance) == ""

    def test_repr_format(self):
        """__repr__ returns a reconstructable-looking representation."""
        cause = ValueError("bad")
        instance = SecurityError("blocked", error_code=ErrorCode.TOOL_EXECUTION_FAILED, original=cause)
        r = repr(instance)
        assert "SecurityError" in r
        assert "message=" in r
        assert "'blocked'" in r
        assert "error_code=" in r
        assert "TOOL_EXECUTION_FAILED" in r
        assert "original=" in r

    def test_repr_no_code_or_original(self):
        """__repr__ works with just a message."""
        instance = ParserError("bad output")
        r = repr(instance)
        assert "ParserError" in r
        assert "message='bad output'" in r
        assert "error_code=None" in r
        assert "original=None" in r


class TestCrossModuleReimport:
    """Verify the exceptions are still accessible from their original modules."""

    def _import_from(self, module_path: str, name: str) -> type:
        """Dynamically import *name* from *module_path*."""
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, name)

    def test_mcp_transport_error(self):
        cls = self._import_from("mcp_transport", "MCPTransportError")
        assert cls is MCPTransportError
        assert issubclass(cls, InfrastructureError)

    @pytest.mark.skipif(
        True,
        reason="opentelemetry not installed — tracing module cannot import",
    )
    def test_tracing_error(self):
        cls = self._import_from("tracing", "TracingError")
        assert cls is TracingError
        assert issubclass(cls, InfrastructureError)

    def test_lock_acquisition_error(self):
        cls = self._import_from("distributed_lock", "LockAcquisitionError")
        assert cls is LockAcquisitionError
        assert issubclass(cls, InfrastructureError)

    def test_scope_violation_error(self):
        cls = self._import_from("tools.scope_validator", "ScopeViolationError")
        assert cls is ScopeViolationError
        assert issubclass(cls, ToolError)

    @pytest.mark.skipif(
        True,
        reason="opentelemetry not installed — tool_runner imports tracing",
    )
    def test_security_error(self):
        cls = self._import_from("tools.tool_runner", "SecurityError")
        assert cls is SecurityError
        assert issubclass(cls, ToolError)

    def test_circuit_open_error(self):
        cls = self._import_from("tools.circuit_breaker", "CircuitOpenError")
        assert cls is CircuitOpenError
        assert issubclass(cls, ToolError)

    def test_artifact_missing_error(self):
        cls = self._import_from("tool_core.storage", "ArtifactMissingError")
        assert cls is ArtifactMissingError
        assert issubclass(cls, ToolError)

    def test_invalid_state_transition_error(self):
        cls = self._import_from("state_machine", "InvalidStateTransitionError")
        assert cls is InvalidStateTransitionError
        assert issubclass(cls, StateError)

    def test_llm_unavailable_error(self):
        cls = self._import_from("llm_client", "LLMUnavailableError")
        assert cls is LLMUnavailableError
        assert issubclass(cls, ResourceError)

    def test_auth_error(self):
        cls = self._import_from("tools.auth_manager", "AuthError")
        assert cls is AuthError
        assert issubclass(cls, ResourceError)

    def test_finding_cap_exceeded_error(self):
        cls = self._import_from(
            "database.repositories.finding_repository", "FindingCapExceededError"
        )
        assert cls is FindingCapExceededError
        assert issubclass(cls, ToolError)

    def test_parser_error(self):
        cls = self._import_from("parsers.parsers.base", "ParserError")
        assert cls is ParserError
        assert issubclass(cls, ValidationError)

    def test_finding_validation_error(self):
        cls = self._import_from("models.finding", "FindingValidationError")
        assert cls is FindingValidationError
        assert issubclass(cls, ValidationError)

    def test_retry_exhausted_error(self):
        cls = self._import_from("utils.retry", "RetryExhaustedError")
        assert cls is RetryExhaustedError
        assert issubclass(cls, ResourceError)

    def test_operator_canceled(self):
        cls = self._import_from("tasks.base", "OperatorCanceled")
        assert cls is OperatorCanceled
        assert issubclass(cls, ConcurrencyError)

    def test_custom_rule_error(self):
        cls = self._import_from("custom_rules.engine", "CustomRuleError")
        assert cls is CustomRuleError
        assert issubclass(cls, ValidationError)

    def test_rule_validation_error(self):
        cls = self._import_from("custom_rules.validator", "RuleValidationError")
        assert cls is RuleValidationError
        assert issubclass(cls, ValidationError)

    @pytest.mark.skipif(
        True,
        reason="opentelemetry not installed — orchestrator imports tracing",
    )
    def test_engagement_timeout_error(self):
        cls = self._import_from("orchestrator_pkg.orchestrator", "EngagementTimeoutError")
        assert cls is EngagementTimeoutError
        assert issubclass(cls, StateError)

    def test_database_connection_error(self):
        cls = self._import_from("database.connection", "DatabaseConnectionError")
        assert cls is DatabaseConnectionError
        assert issubclass(cls, InfrastructureError)
