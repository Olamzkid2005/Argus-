"""
Error Classification and Alerting

Categorizes errors by type and severity for targeted handling and alerting.
"""

import logging
import os
from datetime import datetime, UTC
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass

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
    alert_message: Optional[str]


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
    task_name: Optional[str] = None,
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
    if is_permanent or category in (ErrorCategory.VALIDATION, ErrorCategory.SECURITY):
        should_retry = False
        retry_delay = 0
    elif category == ErrorCategory.TIMEOUT and retry_count >= 2:
        should_retry = False
        retry_delay = 0
    elif retry_count >= 3:
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
    extra_context: Optional[Dict[str, Any]] = None
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
