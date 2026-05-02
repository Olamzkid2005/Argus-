"""
Error Classification and Alerting

Categorizes errors by type and severity for targeted handling and alerting.
"""

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Categories of errors for targeted handling"""
    TRANSIENT = "transient"           # Temporary, likely to succeed on retry
    PERMANENT = "permanent"           # Will never succeed, needs code fix
    INFRASTRUCTURE = "infrastructure" # DB, Redis, network issues
    EXTERNAL = "external"             # Third-party service failures
    VALIDATION = "validation"         # Input validation errors
    RATE_LIMIT = "rate_limit"         # Rate limiting errors
    SECURITY = "security"             # Authentication/authorization failures
    RESOURCE = "resource"             # Out of memory, disk space, etc.
    TIMEOUT = "timeout"               # Time limit exceeded
    UNKNOWN = "unknown"               # Unclassified


class ErrorSeverity(Enum):
    """Severity levels for error alerting"""
    LOW = "low"           # Log only
    MEDIUM = "medium"     # Log + metric
    HIGH = "high"         # Log + metric + alert
    CRITICAL = "critical" # Log + metric + immediate alert + page


@dataclass
class ErrorClassification:
    """Result of error classification"""
    category: ErrorCategory
    severity: ErrorSeverity
    should_retry: bool
    retry_delay_seconds: int
    alert_message: str | None


# Error patterns for automatic classification
ERROR_PATTERNS = {
    ErrorCategory.TRANSIENT: [
        "connection reset", "connection refused", "broken pipe",
        "temporarily unavailable", "try again later", "service unavailable",
        "too many connections", "pool exhausted",
    ],
    ErrorCategory.INFRASTRUCTURE: [
        "database", "postgresql", "psycopg2", "redis", "connection pool",
        "network", "dns", "timeout", "socket",
    ],
    ErrorCategory.EXTERNAL: [
        "http error", "api error", "third party", "webhook",
        "openai", "anthropic", "llm",
    ],
    ErrorCategory.VALIDATION: [
        "invalid", "validation", "required field", "bad request",
        "schema", "malformed",
    ],
    ErrorCategory.RATE_LIMIT: [
        "rate limit", "too many requests", "429", "throttled",
        "quota exceeded", "limit exceeded",
    ],
    ErrorCategory.SECURITY: [
        "unauthorized", "forbidden", "authentication", "permission",
        "access denied", "invalid token", "csrf",
    ],
    ErrorCategory.RESOURCE: [
        "out of memory", "disk full", "no space", "resource",
        "quota", "limit reached",
    ],
    ErrorCategory.TIMEOUT: [
        "time limit", "deadline exceeded", "soft time limit",
        "hard time limit", "timeout",
    ],
}

# Permanent error indicators (should not retry)
PERMANENT_INDICATORS = [
    "not found", "does not exist", "invalid", "unsupported",
    "not implemented", "deprecated", "bad request", "unauthorized",
    "forbidden", "payment required",
]


def classify_error(
    error: Exception,
    task_name: str | None = None,
    retry_count: int = 0
) -> ErrorClassification:
    """
    Classify an error for targeted handling.

    Args:
        error: The exception that occurred
        task_name: Name of the task that failed
        retry_count: Number of retries already attempted

    Returns:
        ErrorClassification with handling recommendations
    """
    error_message = str(error).lower()
    error_type = type(error).__name__

    # Determine category
    category = ErrorCategory.UNKNOWN
    for cat, patterns in ERROR_PATTERNS.items():
        if any(pattern in error_message for pattern in patterns):
            category = cat
            break
        if any(pattern in error_type.lower() for pattern in patterns):
            category = cat
            break

    # Check if error is permanent (should not retry)
    is_permanent = any(ind in error_message for ind in PERMANENT_INDICATORS)

    # Determine if should retry
    if is_permanent or category in (ErrorCategory.VALIDATION, ErrorCategory.SECURITY) or category == ErrorCategory.TIMEOUT and retry_count >= 2 or retry_count >= 3:
        should_retry = False
        retry_delay = 0
    else:
        should_retry = True
        retry_delay = min(2 ** retry_count * 30, 600)  # Exponential backoff, max 10 min

    # Determine severity
    if category in (ErrorCategory.INFRASTRUCTURE, ErrorCategory.RESOURCE):
        severity = ErrorSeverity.HIGH
    elif category == ErrorCategory.SECURITY:
        severity = ErrorSeverity.CRITICAL
    elif retry_count >= 3:
        severity = ErrorSeverity.HIGH
    elif category == ErrorCategory.UNKNOWN:
        severity = ErrorSeverity.MEDIUM
    else:
        severity = ErrorSeverity.LOW

    # Build alert message for high/critical
    alert_message = None
    if severity in (ErrorSeverity.HIGH, ErrorSeverity.CRITICAL):
        alert_message = (
            f"[{severity.value.upper()}] {category.value} error in {task_name or 'unknown task'}: "
            f"{error_type}: {str(error)[:200]}"
        )

    return ErrorClassification(
        category=category,
        severity=severity,
        should_retry=should_retry,
        retry_delay_seconds=retry_delay,
        alert_message=alert_message
    )


def log_classified_error(
    classification: ErrorClassification,
    task_id: str,
    task_name: str,
    error: Exception,
    extra_context: dict[str, Any] | None = None
):
    """
    Log an error with its classification.

    Args:
        classification: The error classification
        task_id: Celery task ID
        task_name: Task name
        error: Original exception
        extra_context: Additional context data
    """
    log_data = {
        "task_id": task_id,
        "task_name": task_name,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "category": classification.category.value,
        "severity": classification.severity.value,
        "should_retry": classification.should_retry,
        "retry_delay": classification.retry_delay_seconds,
        "context": extra_context or {}
    }

    if classification.severity == ErrorSeverity.CRITICAL:
        logger.critical(f"CRITICAL ERROR: {log_data}")
    elif classification.severity == ErrorSeverity.HIGH:
        logger.error(f"HIGH ERROR: {log_data}")
    elif classification.severity == ErrorSeverity.MEDIUM:
        logger.warning(f"MEDIUM ERROR: {log_data}")
    else:
        logger.info(f"LOW ERROR: {log_data}")

    # Send alert if applicable
    if classification.alert_message:
        send_alert(classification.alert_message, classification.severity)


def send_alert(message: str, severity: ErrorSeverity):
    """
    Send an alert for high/critical errors.

    In production, this would integrate with PagerDuty, OpsGenie, Slack, etc.
    For now, it logs the alert.
    """
    alert_channel = os.getenv("ALERT_WEBHOOK_URL")

    if alert_channel:
        try:
            import requests
            requests.post(
                alert_channel,
                json={
                    "text": message,
                    "severity": severity.value,
                    "timestamp": datetime.now(UTC).isoformat()
                },
                timeout=5
            )
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
    else:
        logger.warning(f"ALERT: {message}")


# ═══════════════════════════════════════════════════════════════
# ErrorCode enum — specific error codes for reliable classification
#
# Stolen from: Shannon's apps/worker/src/types/errors.ts
# Two-tier classification:
#   1. Code-based via ErrorCode (preferred — deterministic)
#   2. String-pattern matching (existing — fallback)
# ═══════════════════════════════════════════════════════════════


class ErrorCode(StrEnum):
    """Specific error codes for precise, code-based classification.

    Each code maps to a specific error scenario. Codes are preferred
    over string-pattern matching because they are deterministic and
    survive refactoring of error messages.

    Categories match the existing ErrorCategory enum for compatibility.
    """

    # ── Config errors ──
    CONFIG_NOT_FOUND = "CONFIG_NOT_FOUND"
    CONFIG_VALIDATION_FAILED = "CONFIG_VALIDATION_FAILED"
    CONFIG_PARSE_ERROR = "CONFIG_PARSE_ERROR"

    # ── Tool execution errors ──
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    TOOL_TIMED_OUT = "TOOL_TIMED_OUT"
    TOOL_OUTPUT_EMPTY = "TOOL_OUTPUT_EMPTY"
    TOOL_SCHEMA_MISMATCH = "TOOL_SCHEMA_MISMATCH"

    # ── Pipeline execution errors ──
    STEP_EXECUTION_FAILED = "STEP_EXECUTION_FAILED"
    OUTPUT_VALIDATION_FAILED = "OUTPUT_VALIDATION_FAILED"
    PREREQUISITE_FAILED = "PREREQUISITE_FAILED"
    PHASE_TIMED_OUT = "PHASE_TIMED_OUT"

    # ── Resource errors ──
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"

    # ── I/O errors ──
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    DATABASE_ERROR = "DATABASE_ERROR"
    CHECKPOINT_FAILED = "CHECKPOINT_FAILED"

    # ── Preflight ──
    INVALID_INPUT = "INVALID_INPUT"
    TARGET_UNREACHABLE = "TARGET_UNREACHABLE"
    DNS_RESOLUTION_FAILED = "DNS_RESOLUTION_FAILED"


@dataclass
class CodeBasedClassification:
    """Result of code-based error classification.

    Extends ErrorClassification with a specific ErrorCode.
    """

    category: ErrorCategory
    severity: ErrorSeverity
    should_retry: bool
    retry_delay_seconds: int
    alert_message: str | None
    error_code: ErrorCode | None = None


def classify_by_error_code(code: ErrorCode, retry_count: int = 0) -> CodeBasedClassification:
    """Classify an error by its ErrorCode for reliable, deterministic routing.

    This is the PREFERRED classification method. Use it when the error
    originates from within the Argus codebase and has been tagged with
    an ErrorCode.

    Args:
        code: The ErrorCode to classify.
        retry_count: Number of retries already attempted.

    Returns:
        CodeBasedClassification with handling recommendations.

    Raises:
        ValueError: If the ErrorCode is unknown.
    """
    # ── Resource errors — retryable (wait for reset) ──
    if code in (ErrorCode.RATE_LIMITED, ErrorCode.QUOTA_EXCEEDED):
        delay = min(2 ** retry_count * 30, 600)
        return CodeBasedClassification(
            category=ErrorCategory.RATE_LIMIT,
            severity=ErrorSeverity.MEDIUM,
            should_retry=True,
            retry_delay_seconds=delay,
            alert_message=None,
            error_code=code,
        )

    # ── Config/I/O errors — non-retryable (need manual fix) ──
    if code in (
        ErrorCode.CONFIG_NOT_FOUND,
        ErrorCode.CONFIG_VALIDATION_FAILED,
        ErrorCode.CONFIG_PARSE_ERROR,
        ErrorCode.FILE_NOT_FOUND,
        ErrorCode.INVALID_INPUT,
        ErrorCode.TARGET_UNREACHABLE,
        ErrorCode.DNS_RESOLUTION_FAILED,
    ):
        return CodeBasedClassification(
            category=ErrorCategory.PERMANENT,
            severity=ErrorSeverity.HIGH,
            should_retry=False,
            retry_delay_seconds=0,
            alert_message=f"Configuration or preflight error: {code.value}",
            error_code=code,
        )

    # ── Database errors — retryable transient ──
    if code == ErrorCode.DATABASE_ERROR:
        delay = min(2 ** retry_count * 30, 300)
        return CodeBasedClassification(
            category=ErrorCategory.INFRASTRUCTURE,
            severity=ErrorSeverity.HIGH,
            should_retry=True,
            retry_delay_seconds=delay,
            alert_message=f"Database error (retry {retry_count})",
            error_code=code,
        )

    # ── Tool execution errors ──
    if code in (ErrorCode.TOOL_NOT_FOUND, ErrorCode.TOOL_EXECUTION_FAILED):
        is_retryable = retry_count < 3
        return CodeBasedClassification(
            category=ErrorCategory.TRANSIENT if is_retryable else ErrorCategory.PERMANENT,
            severity=ErrorSeverity.MEDIUM if is_retryable else ErrorSeverity.HIGH,
            should_retry=is_retryable,
            retry_delay_seconds=min(2 ** retry_count * 15, 300) if is_retryable else 0,
            alert_message=f"Tool execution error: {code.value}" if not is_retryable else None,
            error_code=code,
        )

    if code == ErrorCode.TOOL_TIMED_OUT:
        return CodeBasedClassification(
            category=ErrorCategory.TIMEOUT,
            severity=ErrorSeverity.MEDIUM,
            should_retry=True,
            retry_delay_seconds=min(2 ** retry_count * 60, 600),
            alert_message=None,
            error_code=code,
        )

    if code == ErrorCode.TOOL_SCHEMA_MISMATCH:
        return CodeBasedClassification(
            category=ErrorCategory.PERMANENT,
            severity=ErrorSeverity.MEDIUM,
            should_retry=False,
            retry_delay_seconds=0,
            alert_message=f"Tool schema mismatch: {code.value}",
            error_code=code,
        )

    if code == ErrorCode.TOOL_OUTPUT_EMPTY:
        return CodeBasedClassification(
            category=ErrorCategory.TRANSIENT,
            severity=ErrorSeverity.LOW,
            should_retry=True,
            retry_delay_seconds=min(2 ** retry_count * 10, 120),
            alert_message=None,
            error_code=code,
        )

    # ── Pipeline execution errors ──
    if code in (ErrorCode.STEP_EXECUTION_FAILED, ErrorCode.OUTPUT_VALIDATION_FAILED):
        is_retryable = retry_count < 2
        return CodeBasedClassification(
            category=ErrorCategory.TRANSIENT if is_retryable else ErrorCategory.PERMANENT,
            severity=ErrorSeverity.MEDIUM,
            should_retry=is_retryable,
            retry_delay_seconds=min(2 ** retry_count * 30, 300) if is_retryable else 0,
            alert_message=None,
            error_code=code,
        )

    if code == ErrorCode.PREREQUISITE_FAILED:
        return CodeBasedClassification(
            category=ErrorCategory.PERMANENT,
            severity=ErrorSeverity.HIGH,
            should_retry=False,
            retry_delay_seconds=0,
            alert_message=f"Prerequisite not met: {code.value}",
            error_code=code,
        )

    if code == ErrorCode.PHASE_TIMED_OUT:
        return CodeBasedClassification(
            category=ErrorCategory.TIMEOUT,
            severity=ErrorSeverity.HIGH,
            should_retry=False,
            retry_delay_seconds=0,
            alert_message=f"Phase timed out: {code.value}",
            error_code=code,
        )

    if code in (ErrorCode.CHECKPOINT_FAILED,):
        return CodeBasedClassification(
            category=ErrorCategory.INFRASTRUCTURE,
            severity=ErrorSeverity.HIGH,
            should_retry=True,
            retry_delay_seconds=min(2 ** retry_count * 30, 300),
            alert_message=f"Checkpoint error (retry {retry_count})",
            error_code=code,
        )

    # Safe fallback for unknown codes — don't crash, return a sensible default
    return CodeBasedClassification(
        category=ErrorCategory.UNKNOWN,
        severity=ErrorSeverity.MEDIUM,
        should_retry=False,
        retry_delay_seconds=0,
        alert_message=f"Unknown error code: {code.value}",
        error_code=code,
    )


def classify_error_with_code(
    error: Exception,
    error_code: ErrorCode | None = None,
    task_name: str | None = None,
    retry_count: int = 0,
) -> CodeBasedClassification:
    """Classify an error with optional ErrorCode override.

    Two-tier classification:
      1. Code-based via ErrorCode (preferred — used when error_code is provided)
      2. String-pattern matching (fallback — delegates to existing classify_error)

    Args:
        error: The exception that occurred.
        error_code: Optional ErrorCode for precise classification.
        task_name: Name of the task that failed.
        retry_count: Number of retries already attempted.

    Returns:
        CodeBasedClassification with handling recommendations.
    """
    # === TIER 1: Code-based classification (preferred) ===
    if error_code is not None:
        return classify_by_error_code(error_code, retry_count)

    # === TIER 2: String-pattern matching (fallback) ===
    base = classify_error(error, task_name, retry_count)
    return CodeBasedClassification(
        category=base.category,
        severity=base.severity,
        should_retry=base.should_retry,
        retry_delay_seconds=base.retry_delay_seconds,
        alert_message=base.alert_message,
        error_code=None,
    )


def tag_error(
    error: Exception,
    error_code: ErrorCode,
    message: str | None = None,
) -> Exception:
    """Tag an exception with an ErrorCode for downstream classification.

    Attaches the ErrorCode as an attribute on the exception object.
    Downstream classifiers check for this attribute first (code-based),
    falling back to string-pattern matching if absent.

    Args:
        error: The exception to tag.
        error_code: The ErrorCode to attach.
        message: Optional override message.

    Returns:
        The tagged exception (same object, mutated in place).
    """
    error.error_code = error_code  # type: ignore[attr-defined]
    if message:
        error.args = (message, *error.args[1:])
    return error
